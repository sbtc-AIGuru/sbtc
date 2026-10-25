"""Stream ViBioMIR chunks into a shared VI/EN/ZH BM25 index.

Run with --help; indexing is limited to 1,000 records unless --all is explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from functools import cache
from itertools import islice
from pathlib import Path
from time import monotonic
from typing import Any

from elasticsearch import Elasticsearch
from elasticsearch.helpers import streaming_bulk

DATA_PATH = Path(__file__).resolve().parents[3] / "datav3/ViBioMIR_chunks_with_recovery.jsonl"
INDEX_NAME = os.getenv("ELASTICSEARCH_INDEX", "vibiomir_bm25")
BATCH_SIZE = int(os.getenv("ELASTICSEARCH_BATCH_SIZE", "1000"))
WORKERS = int(os.getenv("ELASTICSEARCH_WORKERS", "1"))
LANGUAGES = ("vi", "en", "zh")
PIPELINE = {"version": 1, "vi": "pyvi-0.1.1", "zh": "opencc-0.1.7-t2s"}


def connect_elasticsearch() -> Elasticsearch:
    """Connect using environment settings and verify the server's version."""
    options: dict[str, Any] = {
        "request_timeout": float(os.getenv("ELASTICSEARCH_TIMEOUT", "60")),
        "max_retries": 3,
        "retry_on_timeout": True,
    }
    if api_key := os.getenv("ELASTICSEARCH_API_KEY"):
        options["api_key"] = api_key
    elif username := os.getenv("ELASTICSEARCH_USERNAME"):
        options["basic_auth"] = (username, os.environ["ELASTICSEARCH_PASSWORD"])
    if ca_certs := os.getenv("ELASTICSEARCH_CA_CERTS"):
        options["ca_certs"] = ca_certs
    client = Elasticsearch(os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"), **options)
    try:
        version = client.info()["version"]["number"]
        major, minor = map(int, version.split(".")[:2])
        if major != 9 or minor < 5:
            raise RuntimeError(f"Expected Elasticsearch 9.5+ (9.x), found {version}")
    except Exception:
        client.close()
        raise
    return client


def index_definition() -> dict[str, Any]:
    """Define keyword metadata and separate analyzers with BM25 similarity."""
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "medical_vi": {
                        "type": "custom", "tokenizer": "whitespace", "filter": ["lowercase"],
                    },
                    "medical_en": {
                        "type": "custom", "tokenizer": "standard", "filter": ["lowercase"],
                    },
                },
            },
        },
        "mappings": {
            "dynamic": False,
            "_meta": {"vibiomir_pipeline": PIPELINE},
            "properties": {
                **{name: {"type": "keyword"} for name in ("doc_id", "chunk_id", "lang")},
                "content": {"type": "text", "index": False},
                **{
                    f"content_{lang}": {
                        "type": "text", "analyzer": analyzer, "similarity": "BM25",
                    }
                    for lang, analyzer in zip(LANGUAGES, ("medical_vi", "medical_en", "smartcn"))
                },
            },
        },
    }


def create_index(client: Elasticsearch, index: str = INDEX_NAME) -> None:
    """Create once; reject incompatible existing mappings without modifying them."""
    definition = index_definition()
    if not client.indices.exists(index=index):
        client.indices.create(index=index, **definition)
        return
    mappings = client.indices.get_mapping(index=index)
    for entry in mappings.values():
        mapping = entry["mappings"]
        if mapping.get("_meta", {}).get("vibiomir_pipeline") != PIPELINE:
            raise ValueError("Index uses another preprocessing pipeline; choose a new ELASTICSEARCH_INDEX")
        for field, expected in definition["mappings"]["properties"].items():
            actual = mapping.get("properties", {}).get(field, {})
            if any(actual.get(key) != value for key, value in expected.items()):
                raise ValueError(f"Incompatible mapping for {field}; choose a new ELASTICSEARCH_INDEX")


@cache
def _vietnamese_tokenizer() -> Any:
    from pyvi import ViTokenizer

    return ViTokenizer


@cache
def _chinese_converter() -> Any:
    from opencc import OpenCC

    return OpenCC("t2s")


def prepare_text(text: str, lang: str) -> str:
    """Apply identical preprocessing to documents and queries; never translate."""
    if lang not in LANGUAGES:
        raise ValueError(f"Unsupported language {lang!r}; expected vi, en or zh")
    text = unicodedata.normalize("NFC", text)
    if lang == "vi":
        return _vietnamese_tokenizer().tokenize(text)
    if lang == "zh":
        return _chinese_converter().convert(text)
    return text


def read_jsonl(path: str | Path, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield source records one line at a time, stopping before the next record."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    with Path(path).open(encoding="utf-8") as source:
        lines = ((number, line) for number, line in enumerate(source, 1) if line.strip())
        for number, line in islice(lines, limit):
            try:
                record = json.loads(line)
                if record["language"] not in LANGUAGES or not record["content"].strip():
                    raise ValueError("Expected nonempty content and language vi/en/zh")
                if record["doc_id"] is None or not record["chunk_id"]:
                    raise ValueError("Missing document/chunk identifier")
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise ValueError(f"Invalid JSONL record {path}:{number}: {error}") from error
            yield record


def _prepare_record(record: dict[str, Any]) -> dict[str, Any]:
    lang = record["language"]
    return {
        **record,
        "doc_id": str(record["doc_id"]),
        "chunk_id": str(record["chunk_id"]),
        "lang": lang,
        f"content_{lang}": prepare_text(record["content"], lang),
    }


def iter_actions(path: str | Path, index: str = INDEX_NAME,
                 limit: int | None = None, *, workers: int = 1) -> Iterator[dict[str, Any]]:
    """Prepare a bounded stream, optionally in parallel, and assign stable IDs."""
    if workers < 1:
        raise ValueError("workers must be positive")
    pool_context = ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext()
    with pool_context as pool:
        records = read_jsonl(path, limit)
        # Python 3.14 buffersize bounds the queued chunks instead of reading the whole corpus.
        sources = (pool.map(_prepare_record, records, chunksize=32, buffersize=workers * 2)
                   if pool is not None else map(_prepare_record, records))
        for source in sources:
            identity = json.dumps([source["doc_id"], source["chunk_id"]], ensure_ascii=False)
            yield {
                "_op_type": "index",
                "_index": index,
                "_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                "_source": source,
            }


def bulk_index(client: Elasticsearch, path: str | Path, *, index: str = INDEX_NAME,
               batch_size: int = BATCH_SIZE, limit: int | None = 1000,
               workers: int = WORKERS) -> tuple[int, int]:
    """Stream batches, retry temporary errors and report final success/failure counts."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    success = failed = 0
    started = last_report = monotonic()
    for ok, item in streaming_bulk(
        client, iter_actions(path, index, limit, workers=workers), chunk_size=batch_size,
        max_chunk_bytes=16 * 1024 * 1024, max_retries=3,
        initial_backoff=2, max_backoff=30, retry_on_status=(429, 502, 503, 504),
        raise_on_error=False, yield_ok=True,
    ):
        success += int(ok)
        failed += int(not ok)
        if not ok and failed <= 5:
            result = next(iter(item.values()))
            error_type = result.get("error", {}).get("type", "unknown")
            print(f"Failed _id={result.get('_id')} status={result.get('status')} type={error_type}",
                  file=sys.stderr)
        now = monotonic()
        if (success + failed) % batch_size == 0 or now - last_report >= 5:
            print(f"success={success:,} failed={failed:,} rate={success / max(now - started, .001):.1f} docs/s",
                  flush=True)
            last_report = now
    print(f"Complete: success={success:,} failed={failed:,} "
          f"rate={success / max(monotonic() - started, .001):.1f} docs/s", flush=True)
    return success, failed


def search_bm25(query: str, lang: str, top_k: int = 5, *,
                client: Elasticsearch, index: str = INDEX_NAME) -> list[dict[str, Any]]:
    """Search one language field using the same preprocessing as indexing."""
    if not query.strip() or top_k < 1:
        raise ValueError("query must be nonempty and top_k must be positive")
    response = client.search(index=index, size=top_k, query={
        "bool": {
            "must": [{"match": {f"content_{lang}": prepare_text(query, lang)}}],
            "filter": [{"term": {"lang": lang}}],
        },
    }, source_excludes=[f"content_{value}" for value in LANGUAGES])
    return response["hits"]["hits"]


def check_analyzers(client: Elasticsearch, index: str = INDEX_NAME) -> dict[str, list[str]]:
    """Call _analyze with medical examples through the complete text pipeline."""
    examples = {
        "vi": "Bệnh nhân không bị suy thận và đái tháo đường.",
        "en": "No diabetes, not hepatitis, nor cancer, without insulin deficiency.",
        "zh": "患者沒有糖尿病，醫生建議檢查腎功能。",
    }
    tokens = {}
    for lang, text in examples.items():
        result = client.indices.analyze(index=index, field=f"content_{lang}", text=prepare_text(text, lang))
        tokens[lang] = [token["token"] for token in result["tokens"]]
        if not tokens[lang]:
            raise RuntimeError(f"Analyzer for {lang} returned no tokens")
    if not {"no", "not", "nor", "without", "diabetes", "hepatitis"}.issubset(tokens["en"]):
        raise RuntimeError("English analyzer removed negations or changed medical terms")
    if not any("_" in token for token in tokens["vi"]):
        raise RuntimeError("Vietnamese compound words were not preserved")
    return tokens


def main() -> None:
    """Expose index creation, analyzer checks, bounded imports and BM25 search."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=INDEX_NAME)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-index")
    commands.add_parser("analyze")
    ingest = commands.add_parser("index")
    ingest.add_argument("--data-path", type=Path, default=DATA_PATH)
    ingest.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ingest.add_argument("--workers", type=int, default=WORKERS,
                        help="Preprocessing processes; >1 requires Python 3.14+")
    limits = ingest.add_mutually_exclusive_group()
    limits.add_argument("--limit", type=int, default=1000)
    limits.add_argument("--all", action="store_true", help="Explicitly import the entire file")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--lang", choices=LANGUAGES, required=True)
    search.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.command == "index":
        if not args.data_path.is_file():
            parser.error(f"File not found: {args.data_path}")
        if args.batch_size < 1 or args.limit < 1 or args.workers < 1:
            parser.error("batch-size, limit and workers must be positive")
    with connect_elasticsearch() as client:
        if args.command in ("create-index", "index"):
            create_index(client, args.index)
        if args.command == "analyze":
            print(json.dumps(check_analyzers(client, args.index), ensure_ascii=False, indent=2))
        elif args.command == "index":
            # Fail before importing any records if dependencies or analyzers are unavailable.
            check_analyzers(client, args.index)
            _, failed = bulk_index(client, args.data_path, index=args.index,
                                   batch_size=args.batch_size, limit=None if args.all else args.limit,
                                   workers=args.workers)
            client.indices.refresh(index=args.index)
            if failed:
                raise SystemExit(1)
        elif args.command == "search":
            print(json.dumps(search_bm25(args.query, args.lang, args.top_k, client=client,
                                        index=args.index), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
