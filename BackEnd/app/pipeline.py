"""Qdrant dense + Elasticsearch BM25 -> adaptive RRF -> optional Qwen -> BTC JSON."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import logging
import math
import os
from pathlib import Path
from threading import Event, Lock, local
from time import monotonic
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import requests
from elastic_transport import TransportError
from elasticsearch import ApiError

from .Database.postgre_db import PostgreManager
from .Database.qdrant_db import QdrantManager, parse_dense_weight
from .Database.elastic_search import connect_elasticsearch, index_definition, PIPELINE as ES_PIPELINE, BM25_SEARCH_PROFILE
from .Retrieval.hybrid import HybridRetriever
from .Retrieval.query_inputs import QWEN_CONFIG, combine_query_files
from .Retrieval.qwen_reranker import QwenReranker, MODEL_NAME, MODEL_REVISION, INSTRUCTION
from .Retrieval.export import btc_normalized
from .Retrieval.utils import atomic_json, sha_file, source_id

LOGGER = logging.getLogger(__name__)
DEFAULT_TOP_K = 200
DEFAULT_BRANCH_LIMIT = 100
DEFAULT_HNSW_EF = 512
DEFAULT_MAX_CHUNKS = None
SEARCH_METHODS = {"4-branch": "query_original_dense", "6-branch": "query_multilingual_dense",
                  "3-branch": "query_multilingual_dense"}
SUBMISSION_FORMAT = "integer-doc-ids-v1"
GTE_CONFIG = {
    "model": "Alibaba-NLP/gte-multilingual-base",
    "revision": "9bbca17d9273fd0d03d5725c7a4b0f6b45142062",
    "code_revision": "40ced75c3017eb27626c9d4ea981bde21a2662f4",
    "dimension": 768, "max_length": 8192,
}
COLUMN_ALIASES = {
    "id": ("id", "query_id"),
    "original_query": ("query", "original_query"),
    "eng_query": ("english", "eng_query", "english_query"),
    "chinese_query": ("chinese", "chinese_query"),
}
VECTOR_COLUMNS = {
    "original_query": "vector_original",
    "eng_query": "vector_english",
    "chinese_query": "vector_chinese",
}
EMBEDDING_CONFIG = {
    **GTE_CONFIG, "pooling": "CLS", "normalized": True, "storage_dtype": "float32",
    "query_prefix": "",
    "window_aggregation": "token-weighted mean of L2-normalized windows, then L2",
}


class PipelineError(RuntimeError):
    """Failed rows are available as .failures; no final submission was written."""

    def __init__(self, failures: list[dict]):
        self.failures = failures
        super().__init__(f"{len(failures)} query/queries failed; inspect the errors file and resume")


class PipelinePaused(RuntimeError):
    """Processing stopped at a batch boundary; successful rows remain checkpointed."""


class PipelineSetupError(RuntimeError):
    """An actionable, safe service/model setup error, not a failed input row."""

    def __init__(self, stage: str, code: str, message: str):
        self.stage, self.code = stage, code
        super().__init__(message)


def _model_cache(cache_dir=None):
    configured = cache_dir or os.getenv("PIPELINE_MODEL_CACHE")
    if configured:
        return str(Path(configured).expanduser())
    project_cache = Path(__file__).resolve().parents[2] / "artifacts/model-cache"
    snapshot = project_cache / "models--Alibaba-NLP--gte-multilingual-base/snapshots" / GTE_CONFIG["revision"]
    return str(project_cache) if snapshot.is_dir() else None


def load_dense_encoder(*, device: str = "cpu", batch_size: int = 8, cache_dir=None) -> Callable:
    """Load cached pinned GTE weights; reuse the indexer's exact window/pooling code."""
    import torch
    from transformers import AutoConfig, AutoModel, AutoTokenizer
    from Scripts.Qdrant.build_gte_qdrant import encode_records, normalize_vectors

    config = {**GTE_CONFIG, "batch_size": batch_size, "token_budget": 16_384}
    options = {"revision": config["revision"], "local_files_only": True}
    resolved_cache = _model_cache(cache_dir)
    if resolved_cache:
        options["cache_dir"] = resolved_cache
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            config["model"], trust_remote_code=True,
            code_revision=config["code_revision"], **options,
        )
        model_config = AutoConfig.from_pretrained(
            config["model"], trust_remote_code=True,
            code_revision=config["code_revision"], **options,
        )
        model = AutoModel.from_pretrained(
            config["model"], config=model_config, trust_remote_code=True,
            code_revision=config["code_revision"], attn_implementation="sdpa",
            torch_dtype=torch.float16 if torch.device(device).type == "cuda" else torch.float32,
            low_cpu_mem_usage=False, _fast_init=False, **options,
        )
    except OSError as exc:
        raise PipelineSetupError(
            "encoding", "ENCODER_MODEL_UNAVAILABLE",
            "Chưa nạp được model GTE đúng revision từ cache. Cần có weights/tokenizer của "
            "Alibaba-NLP/gte-multilingual-base và code Alibaba-NLP/new-impl. "
            "Đặt PIPELINE_MODEL_CACHE tới cache đã tải; file Parquet không phải nguyên nhân lỗi.",
        ) from exc
    if not hasattr(tokenizer, "build_inputs_with_special_tokens"):
        # Transformers 5 removed this legacy API. GTE uses single-sequence
        # XLM-R windows: retain the indexer's original BOS/content/EOS layout.
        tokenizer.build_inputs_with_special_tokens = lambda ids: [
            tokenizer.bos_token_id, *ids, tokenizer.eos_token_id,
        ]
    if not hasattr(model, "get_extended_attention_mask"):
        # The pinned GTE code calls the Transformers 4 encoder-mask API.
        # Restore its exact 2-D padding-mask expansion for Transformers 5.
        def extended_attention_mask(attention_mask, input_shape):
            mask = attention_mask[:, None, None, :].to(dtype=model.dtype)
            return (1.0 - mask) * torch.finfo(model.dtype).min

        model.get_extended_attention_mask = extended_attention_mask
    with torch.device("cpu"):
        model.embeddings.register_buffer(
            "position_ids", torch.arange(model_config.max_position_embeddings), persistent=False,
        )
        model.embeddings._init_rope(model_config)
    if model_config.hidden_size != config["dimension"]:
        raise ValueError("Encoder dimension does not match the GTE snapshot")
    model.eval().to(device)

    def forward(windows):
        features = tokenizer.pad(windows, padding=True, return_tensors="pt")
        features = {name: tensor.to(device) for name, tensor in features.items()}
        with torch.inference_mode():
            vectors = model(**features).last_hidden_state[:, 0].float().cpu().numpy()
        return normalize_vectors(vectors)

    def encode(texts):
        vectors, _ = encode_records([{"text": text} for text in texts], tokenizer, forward, config)
        return vectors

    return encode


def _check_qdrant(*, url, manifest_path, timeout, collection=None, dimension=768):
    manager = (QdrantManager.from_manifest(manifest_path, url=url, timeout=timeout)
               if manifest_path else QdrantManager(url, collection, timeout=timeout))
    with manager:
        try:
            info = manager.refresh_collection()
        except requests.RequestException as exc:
            missing = exc.response is not None and exc.response.status_code == 404
            raise PipelineSetupError(
                "retrieval", "QDRANT_COLLECTION_MISSING" if missing else "QDRANT_UNAVAILABLE",
                ("Qdrant chưa có collection đã cấu hình. Kiểm tra QDRANT_URL và QDRANT_COLLECTION."
                 if missing else "Không kết nối được collection Qdrant. Kiểm tra URL, API key và dịch vụ."),
            ) from exc
        vectors = info["config"]["params"]["vectors"]
        specification = vectors if "size" in vectors else vectors.get(manager.dense_vector_name)
        if specification is None and manager.dense_vector_name is None:
            specification = vectors.get("dense")
        if specification is None and len(vectors) == 1:
            specification = next(iter(vectors.values()))
        if specification is None or specification.get("size") != dimension:
            raise PipelineSetupError(
                "retrieval", "QDRANT_DENSE_MISMATCH",
                "Vector dense của Qdrant không khớp model/kích thước trong file query.",
            )


def _check_elasticsearch(client, index):
    try:
        mappings = client.indices.get_mapping(index=index)
        expected = index_definition()["mappings"]
        for entry in mappings.values():
            mapping = entry["mappings"]
            if (mapping.get("_meta", {}).get("vibiomir_pipeline") != ES_PIPELINE or
                    any(mapping.get("properties", {}).get(field) != specification
                        for field, specification in expected["properties"].items())):
                raise PipelineSetupError("retrieval", "ELASTICSEARCH_MAPPING_MISMATCH",
                                         "Elasticsearch cần mapping BM25 VI/EN/ZH đúng pipeline hiện tại.")
    except (ApiError, TransportError, RuntimeError) as exc:
        if isinstance(exc, PipelineSetupError):
            raise
        missing = getattr(exc, "status_code", None) == 404
        raise PipelineSetupError(
            "retrieval", "ELASTICSEARCH_INDEX_MISSING" if missing else "ELASTICSEARCH_UNAVAILABLE",
            "Kiểm tra dịch vụ Elasticsearch, ELASTICSEARCH_URL và ELASTICSEARCH_INDEX.",
        ) from exc


def _columns(schema: pa.Schema, overrides: dict | None) -> dict[str, str]:
    overrides = overrides or {}
    if overrides.keys() - COLUMN_ALIASES.keys():
        raise ValueError("Unknown column mapping; use id/original_query/eng_query/chinese_query")
    result = {}
    for field, aliases in COLUMN_ALIASES.items():
        matches = [overrides[field]] if field in overrides else [s for s in aliases if s in schema.names]
        if len(matches) != 1 or matches[0] not in schema.names:
            raise ValueError(f"Map {field} to exactly one Parquet column; available: {schema.names}")
        name = matches[0]
        kind = schema.field(name).type
        valid = pa.types.is_integer(kind) if field == "id" else (
            pa.types.is_string(kind) or pa.types.is_large_string(kind)
        )
        if not valid:
            raise ValueError(f"Invalid Parquet type for {field}: {kind}")
        result[field] = name
    return result


def _embedding_columns(schema: pa.Schema, dense_encoder=None) -> list[str]:
    metadata = schema.metadata or {}
    if dense_encoder is not None and not (
        set(VECTOR_COLUMNS.values()) & set(schema.names) or b"query_embedding" in metadata
    ):
        # Keep the explicit Python encoder injection; never load an encoder automatically.
        return []
    names = [*VECTOR_COLUMNS.values(), "query_sha256"]
    if not set(names) <= set(schema.names):
        raise ValueError("Parquet cần vector_original/vector_english/vector_chinese và query_sha256 từ notebook Colab.")
    try:
        provenance = json.loads(metadata[b"query_embedding"])
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Parquet thiếu metadata query_embedding hợp lệ từ notebook Colab.") from exc
    if not isinstance(provenance, dict) or provenance.get("format_version") != 1:
        raise ValueError("Unsupported query embedding format")
    encoder = provenance.get("encoder")
    expected = QWEN_CONFIG if isinstance(encoder, dict) and encoder.get("model") == QWEN_CONFIG["model"] else EMBEDDING_CONFIG
    if not isinstance(encoder, dict) or any(encoder.get(k) != v for k, v in expected.items()):
        raise ValueError("Query embedding metadata differs from the pinned index encoder")
    expected_mapping = {COLUMN_ALIASES[key][0]: value for key, value in VECTOR_COLUMNS.items()}
    if provenance.get("vector_columns") != expected_mapping:
        raise ValueError("Query embedding language/vector mapping differs from the notebook")
    for name in VECTOR_COLUMNS.values():
        dtype = pa.float16() if expected == QWEN_CONFIG else pa.float32()
        if schema.field(name).type != pa.list_(dtype, expected["dimension"]):
            raise ValueError(f"{name} must contain {expected['dimension']} {dtype} values")
    if not pa.types.is_string(schema.field("query_sha256").type):
        raise ValueError("query_sha256 must be a string column")
    return names


def _query_vectors(record: dict, query: dict, *, dimension=768, tolerance=2e-5) -> dict:
    content = json.dumps([query[key] for key in VECTOR_COLUMNS], ensure_ascii=False, separators=(",", ":"))
    if record["query_sha256"] != hashlib.sha256(content.encode("utf-8")).hexdigest():
        raise ValueError("Query text differs from the cached embedding hash")
    vectors = {}
    for key, column in VECTOR_COLUMNS.items():
        vector = record[column]
        if vector is None or len(vector) != dimension or any(
            value is None or not math.isfinite(value) for value in vector
        ):
            raise ValueError(f"Invalid cached vector: {column}")
        if not math.isclose(math.fsum(value * value for value in vector), 1, rel_tol=0, abs_tol=tolerance):
            raise ValueError(f"Cached vector is not L2-normalized: {column}")
        vectors[key] = vector
    return vectors


def _doc_id(value) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal() and str(int(value)) == value:
        value = int(value)
    return source_id(value)


def _candidates(hits: list[dict], metadata: dict) -> tuple[list[int], list[dict], dict]:
    docs, chunks, identities = [], [], {}
    seen_docs, seen_text, seen_ids = set(), set(), {}
    for hit in hits:
        payload = hit["payload"]
        chunk_id = payload.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError("Qdrant payload has no original chunk_id; point UUID is not a chunk ID")
        source = metadata.get(chunk_id)
        doc, text = payload.get("doc_id"), payload.get("chunk_text")
        if source is not None:
            if doc is not None and _doc_id(doc) != _doc_id(source["doc_id"]):
                raise ValueError(f"Conflicting source document for chunk {chunk_id}")
            if text is not None and text != source["chunk_text"]:
                raise ValueError(f"Conflicting source text for chunk {chunk_id}")
            doc, text = source["doc_id"], source["chunk_text"]
        if doc is None or text is None:
            raise ValueError(f"Missing PostgreSQL source fields for chunk {chunk_id}")
        doc = _doc_id(doc)
        if not isinstance(text, str):
            raise ValueError(f"Non-string source text for chunk {chunk_id}")
        identity = (doc, text)
        if chunk_id in seen_ids and seen_ids[chunk_id] != identity:
            raise ValueError(f"Conflicting Qdrant payloads for chunk {chunk_id}")
        seen_ids[chunk_id] = identity
        if doc not in seen_docs:
            docs.append(doc)
            seen_docs.add(doc)
        normalized = (doc, btc_normalized(text))
        if not text.strip() or normalized in seen_text:
            continue
        seen_text.add(normalized)
        chunks.append({"doc_id": doc, "chunk_text": text})
        identities[identity] = chunk_id
    return docs, chunks, identities


def _checkpoint(path: Path, signature: str, resume: bool) -> dict[int, dict]:
    if not path.exists():
        if resume:
            raise FileNotFoundError(f"Checkpoint does not exist: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps({"version": 1, "signature": signature}) + "\n")
        return {}
    if not resume:
        raise FileExistsError(f"Checkpoint exists; use resume=True or a new output: {path}")
    completed = {}
    with path.open("r+b") as stream:
        if json.loads(stream.readline()) != {"version": 1, "signature": signature}:
            raise ValueError("Checkpoint input/configuration changed; choose a new output")
        while True:
            position = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                # Only the interrupted final append is uncommitted.
                stream.seek(position)
                stream.truncate()
                break
            item = json.loads(line)
            if item["row"] in completed:
                raise ValueError("Duplicate checkpoint row")
            completed[item["row"]] = item
    return completed


def run_pipeline(
    parquet_path: str | Path, output_path: str | Path | None = None, *,
    zip_path: str | Path | None = None, columns: dict | None = None,
    batch_size: int = 16, workers: int = 4,
    top_k: int = DEFAULT_TOP_K, branch_limit: int = DEFAULT_BRANCH_LIMIT,
    hnsw_ef: int | None = DEFAULT_HNSW_EF,
    search_mode: str = "4-branch",
    max_docs: int | None = None, max_chunks: int | None = DEFAULT_MAX_CHUNKS,
    limit: int | None = None, query_filter: dict | None = None,
    start: int | None = None, end: int | None = None,
    manifest_path: str | Path | None = None, qdrant_url: str | None = None,
    timeout: float = 30,
    device: str = "cpu", encoder_batch_size: int = 8,
    model_cache: str | Path | None = None,
    rerank: bool = False,
    reranker_device: str | None = None, reranker_batch_size: int = 4,
    reranker_max_length: int = 8192, reranker_token_budget: int = 8192,
    dense_encoder: Callable | None = None, qdrant_factory: Callable | None = None,
    elasticsearch_factory: Callable | None = None,
    postgres_manager: PostgreManager | None = None, reranker=None,
    checkpoint_path: str | Path | None = None, resume: bool = False,
    resume_tag: str = "",
    progress_callback: Callable | None = None, stop_event: Event | None = None,
) -> list[dict]:
    """Return BTC predictions in input order and optionally write JSON plus ZIP.

    ``qdrant_factory(encoder)`` must return an owned manager per worker. Injected
    PostgreSQL/reranker instances remain caller-owned. A checkpoint stores successful rows
    and original chunk IDs; failed rows are retried on resume. With injected
    components, supply a stable ``resume_tag`` identifying their configuration.
    Missing translations are errors: all search modes require VI/EN/ZH.
    Dense vectors and encoder metadata come from the Colab Parquet; no model is loaded.
    An explicitly supplied dense_encoder remains supported for text-only Python inputs.
    search_mode selects dense VI/EN/ZH only (3), dense VI + BM25 (4), or dense VI/EN/ZH + BM25 (6).
    Defaults retrieve 100 per branch and retain the top 200 fused points in RRF
    order for documents/chunks after source deduplication. Set rerank=True to enable
    Qwen scoring; max_docs and max_chunks optionally limit their respective outputs.
    ``start``/``end`` are inclusive 1-based input row positions, not query IDs.
    Omitted bounds select the first/last row. Progress follows durable queries;
    stop_event pauses before the next batch without losing committed rows.
    Dense search uses hnsw_ef=512; None keeps the Qdrant snapshot's search default.
    """
    if min(batch_size, workers, top_k, branch_limit, encoder_batch_size) < 1:
        raise ValueError("Batch sizes, worker counts and retrieval limits must be positive")
    if hnsw_ef is not None and hnsw_ef < 1:
        raise ValueError("hnsw_ef must be positive")
    if search_mode not in SEARCH_METHODS:
        raise ValueError("search_mode must be '3-branch', '4-branch' or '6-branch'")
    if timeout <= 0 or (limit is not None and limit < 1):
        raise ValueError("Timeouts and limit must be positive")
    if rerank:
        if reranker_batch_size < 1:
            raise ValueError("Reranker batch size must be positive")
        if not 1 <= reranker_max_length <= 32768 or reranker_token_budget < reranker_max_length:
            raise ValueError("Require reranker_max_length <= 32768 and reranker_token_budget >= reranker_max_length")
    if any(value is not None and value < 0 for value in (max_docs, max_chunks)):
        raise ValueError("Output budgets must be nonnegative")
    injected = any(value is not None for value in (dense_encoder, qdrant_factory, elasticsearch_factory, postgres_manager, reranker))
    if resume and injected and not resume_tag:
        raise ValueError("Set resume_tag to identify injected component configuration")
    parquet_path = Path(parquet_path)
    parquet = pq.ParquetFile(parquet_path)
    mapping = _columns(parquet.schema_arrow, columns)
    row_count = parquet.metadata.num_rows
    vector_columns = _embedding_columns(parquet.schema_arrow, dense_encoder) if row_count else []
    encoder_config = json.loads(parquet.schema_arrow.metadata[b"query_embedding"])["encoder"] if vector_columns else GTE_CONFIG
    is_qwen = encoder_config.get("model") == QWEN_CONFIG["model"]
    collection = os.getenv("QDRANT_COLLECTION", "vibiomir_qwen3_06b_1024_fp16_dense" if is_qwen else "sbtc_gte_multilingual")
    weight_columns = ["dense_weight"] if "dense_weight" in parquet.schema_arrow.names else []
    dense_fields = (tuple(VECTOR_COLUMNS) if search_mode != "4-branch" else ("original_query",))
    if any(value is not None and value < 1 for value in (start, end)):
        raise ValueError("start and end must be positive 1-based row positions")
    first = (start or 1) - 1
    stop = end if end is not None else row_count
    if (start is not None or end is not None) and (first >= row_count or stop > row_count or stop <= first):
        raise ValueError("Selected start/end range is outside the Parquet rows")
    if limit is not None:
        stop = min(stop, first + limit)
    total = stop - first
    output = Path(output_path) if output_path else None
    archive = Path(zip_path) if zip_path else None
    if output and output.suffix.lower() != ".json":
        raise ValueError("Competition output must be a .json file")
    if archive and (output is None or archive.suffix.lower() != ".zip"):
        raise ValueError("zip_path requires JSON output and a .zip suffix")
    for path in (output, archive):
        if path and path.exists():
            raise FileExistsError(f"Output exists; choose a new path: {path}")
    checkpoint = Path(checkpoint_path) if checkpoint_path else (
        output.with_suffix(".checkpoint.jsonl") if output else None
    )
    if resume and checkpoint is None:
        raise ValueError("resume requires a checkpoint_path or output_path")
    errors_path = output.with_suffix(".errors.json") if output else None
    paths = [p.resolve() for p in (parquet_path, output, archive, checkpoint, errors_path) if p]
    if len(paths) != len(set(paths)):
        raise ValueError("Input, output, archive, checkpoint and error paths must differ")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8")) if manifest_path else None
    if manifest:
        profile = manifest.get("embedding", {}) if is_qwen else manifest["signature"]
        expected = {"model_id": QWEN_CONFIG["model"], "revision": QWEN_CONFIG["revision"],
                    "dimension": 1024, "pooling": "last_token", "normalize": True,
                    "document_prompt": "", "dtype": "float16", "padding_side": "left"} if is_qwen else GTE_CONFIG
        if any(profile.get(k) != v for k, v in expected.items()):
            raise ValueError("Manifest embedding model differs from the query encoder")
    settings = {
        "submission_format": SUBMISSION_FORMAT, "search_mode": search_mode,
        "input": sha_file(parquet_path), "columns": mapping, "top_k": top_k,
        "embedding_source": "parquet-v1" if vector_columns else "injected-encoder",
        "fusion": "qdrant-dense-elasticsearch-bm25-adaptive-rrf-v1",
        "document_candidates": "top-k-rrf-v1",
        "branch_limit": branch_limit, "max_docs": max_docs, "max_chunks": max_chunks,
        "limit": limit, "filter": query_filter, "manifest": manifest, "encoder": encoder_config,
        "url": qdrant_url or os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        "collection": collection,
        "dense_vector": os.getenv("QDRANT_DENSE_VECTOR_NAME"),
        "elasticsearch_url": os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
        "elasticsearch_index": os.getenv("ELASTICSEARCH_INDEX", "vibiomir_bm25"),
        "bm25_search_profile": BM25_SEARCH_PROFILE,
        "database": os.getenv("DATABASE_URL"), "resume_tag": resume_tag,
        "reranker": {"model": MODEL_NAME, "revision": MODEL_REVISION,
                     "instruction": INSTRUCTION, "max_length": reranker_max_length,
                     "device": reranker_device or device, "window_pooling": "max-v1"} if rerank else None,
    }
    if start is not None or end is not None:
        settings["range"] = [start, end]
    if hnsw_ef is not None:
        settings["hnsw_ef"] = hnsw_ef
    # Store only the digest: settings can contain private connection configuration.
    signature = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    completed = _checkpoint(checkpoint, signature, resume) if checkpoint else {}
    if any(row < first or row >= stop for row in completed):
        raise ValueError("Checkpoint row is outside the selected range")
    failures, seen_ids = [], set()
    thread_state, managers, manager_lock = local(), [], Lock()
    batch_vectors = {}
    batch_weights = {}
    checked_qdrant = False
    checked_elasticsearch = False
    elastic_client = None

    def encoded(texts):
        if texts != thread_state.dense_texts:
            raise ValueError("Dense query text/vector alignment mismatch")
        return thread_state.vectors

    def retrieve(item):
        row, identifier, query = item
        try:
            thread_state.dense_texts = [query[field] for field in dense_fields]
            thread_state.vectors = batch_vectors[row]
            if not hasattr(thread_state, "manager"):
                if qdrant_factory:
                    manager = qdrant_factory(encoded)
                elif manifest_path:
                    manager = QdrantManager.from_manifest(manifest_path, url=qdrant_url,
                                                         dense_encoder=encoded, timeout=timeout)
                else:
                    manager = QdrantManager(qdrant_url, collection, dense_encoder=encoded, timeout=timeout)
                thread_state.manager = manager
                with manager_lock:
                    managers.append(manager)
            hits = HybridRetriever(thread_state.manager, elastic_client, settings["elasticsearch_index"]).query(
                query, query_filter=query_filter, multilingual_dense=search_mode != "4-branch",
                include_bm25=search_mode != "3-branch",
                top_k=top_k, branch_limit=branch_limit, dense_weight=batch_weights[row], hnsw_ef=hnsw_ef,
            )
            if not isinstance(hits, list) or any(
                not isinstance(hit, dict) or not isinstance(hit.get("payload"), dict)
                for hit in hits
            ):
                raise ValueError("Invalid retrieval payloads")
            return row, identifier, query, hits
        except Exception as exc:
            return row, identifier, query, exc

    def failed(row, identifier, stage, exc):
        # Service exception strings may contain SQL, URLs or credentials.
        failures.append({"row": row, "id": identifier, "stage": stage,
                         "error_type": type(exc).__name__})

    def report_progress():
        if progress_callback:
            progress_callback({"total": total, "completed": len(completed),
                               "failed": len(failures), "start": first + 1, "end": stop})

    report_progress()

    with ExitStack() as resources:
        retrieval_pool = resources.enter_context(ThreadPoolExecutor(max_workers=workers))
        journal = resources.enter_context(checkpoint.open("a", encoding="utf-8")) if checkpoint else None
        index = 0
        try:
            for batch in parquet.iter_batches(batch_size=batch_size, columns=[*mapping.values(), *vector_columns, *weight_columns]):
                if index >= stop:
                    break
                if stop_event is not None and stop_event.is_set():
                    if errors_path:
                        atomic_json(errors_path, failures)
                    raise PipelinePaused("Paused at a durable batch checkpoint")
                if index + batch.num_rows <= first:
                    index += batch.num_rows
                    continue
                active = []
                batch_vectors = {}
                batch_weights = {}
                for record in batch.to_pylist():
                    if index >= stop:
                        break
                    row, index = index, index + 1
                    if row < first:
                        continue
                    identifier = record[mapping["id"]]
                    try:
                        source_id(identifier)
                        if identifier in seen_ids:
                            raise ValueError("Duplicate query ID")
                        seen_ids.add(identifier)
                        query = {field: record[name] for field, name in mapping.items() if field != "id"}
                        if any(not isinstance(text, str) or not text.strip() for text in query.values()):
                            raise ValueError("VI/EN/ZH query text must be nonempty")
                        batch_weights[row] = (1.0 if search_mode == "3-branch" else
                                              parse_dense_weight(record.get("dense_weight")))
                        if vector_columns:
                            vectors = _query_vectors(record, query, dimension=encoder_config["dimension"],
                                                     tolerance=0.002 if is_qwen else 2e-5)
                            batch_vectors[row] = [vectors[field] for field in dense_fields]
                        if row in completed:
                            if completed[row]["prediction"]["id"] != identifier:
                                raise ValueError("Checkpoint query alignment mismatch")
                        else:
                            active.append((row, identifier, query))
                    except ValueError as exc:
                        failed(row, identifier, "input", exc)
                if active:
                    batch_started = monotonic()
                    LOGGER.info("Retrieving %d queries (rows %d–%d)", len(active), active[0][0] + 1, active[-1][0] + 1)
                    if not checked_qdrant and qdrant_factory is None and any(batch_weights[row] > 0 for row, _, _ in active):
                        _check_qdrant(url=qdrant_url, manifest_path=manifest_path, timeout=timeout,
                                      collection=collection, dimension=encoder_config["dimension"])
                        checked_qdrant = True
                    if not checked_elasticsearch and any(batch_weights[row] < 1 for row, _, _ in active):
                        try:
                            elastic_client = (elasticsearch_factory() if elasticsearch_factory else connect_elasticsearch())
                            resources.callback(elastic_client.close)
                            _check_elasticsearch(elastic_client, settings["elasticsearch_index"])
                        except (ApiError, TransportError, RuntimeError) as exc:
                            if isinstance(exc, PipelineSetupError):
                                raise
                            raise PipelineSetupError("retrieval", "ELASTICSEARCH_UNAVAILABLE",
                                                     "Không kết nối được Elasticsearch. Kiểm tra ELASTICSEARCH_URL và dịch vụ.") from exc
                        checked_elasticsearch = True
                    if not vector_columns:
                        texts = list(dict.fromkeys(query[field] for _, _, query in active for field in dense_fields))
                        try:
                            vectors = dense_encoder(texts)
                            if len(vectors) != len(texts):
                                raise ValueError("Encoder returned the wrong number of vectors")
                            by_text = dict(zip(texts, vectors, strict=True))
                            batch_vectors = {row: [by_text[query[field]] for field in dense_fields]
                                             for row, _, query in active}
                        except Exception as exc:
                            for row, identifier, _ in active:
                                failed(row, identifier, "encoding", exc)
                            report_progress()
                            continue
                    retrieved = list(retrieval_pool.map(retrieve, active))
                    LOGGER.info("Retrieval finished in %.1fs; hydrating source fields", monotonic() - batch_started)
                    needed = set()
                    for _, _, _, hits in retrieved:
                        if isinstance(hits, Exception):
                            continue
                        for hit in hits[:top_k]:
                            payload = hit.get("payload") or {}
                            if payload.get("doc_id") is None or payload.get("chunk_text") is None:
                                chunk_id = payload.get("chunk_id")
                                if isinstance(chunk_id, str) and chunk_id:
                                    needed.add(chunk_id)
                    metadata, database_error = {}, None
                    if needed:
                        try:
                            if postgres_manager is None:
                                postgres_manager = PostgreManager()
                                resources.callback(postgres_manager.close)
                            metadata = postgres_manager.get_submission_chunks(sorted(needed))
                        except Exception as exc:
                            database_error = exc
                    ready = []
                    for row, identifier, query, hits in retrieved:
                        if isinstance(hits, Exception):
                            failed(row, identifier, "retrieval", hits)
                            continue
                        try:
                            docs, chunks, identities = _candidates(hits, metadata)
                            ready.append((row, identifier, query, docs, chunks, identities))
                        except Exception as exc:
                            failed(row, identifier, "hydration", database_error or exc)
                    if rerank and any(item[4] for item in ready) and reranker is None:
                        LOGGER.info("Loading local Qwen reranker on %s", reranker_device or device)
                        try:
                            reranker = QwenReranker(
                                device=reranker_device or device, batch_size=reranker_batch_size,
                                max_length=reranker_max_length, token_budget=reranker_token_budget,
                                cache_dir=_model_cache(model_cache),
                            )
                        except OSError as exc:
                            raise PipelineSetupError(
                                "reranking", "RERANKER_MODEL_UNAVAILABLE",
                                "Chưa nạp được Qwen3-Reranker-0.6B từ cache. Tải model đúng revision "
                                "theo PIPELINE.md và đặt PIPELINE_MODEL_CACHE; pipeline không tự tải model.",
                            ) from exc

                    def finish(item):
                        row, identifier, query, docs, chunks, identities = item
                        try:
                            started = monotonic()
                            if rerank and chunks:
                                LOGGER.info("Reranking query id=%s: %d chunks", identifier, len(chunks))
                                scores = reranker.score(query["original_query"], [c["chunk_text"] for c in chunks])
                                if len(scores) != len(chunks) or not all(math.isfinite(s) for s in scores):
                                    raise ValueError("Reranker must return one finite score per candidate")
                                order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
                                chunks = [chunks[i] for i in order]
                            prediction = {"id": identifier, "relevant_docs": docs, "relevant_chunks": chunks}
                            prediction["relevant_docs"] = prediction["relevant_docs"][:max_docs]
                            prediction["relevant_chunks"] = prediction["relevant_chunks"][:max_chunks]
                            chunk_ids = [identities[(c["doc_id"], c["chunk_text"])]
                                         for c in prediction["relevant_chunks"]]
                            LOGGER.info("Finished query id=%s in %.1fs", identifier, monotonic() - started)
                            return {"row": row, "prediction": prediction, "chunk_ids": chunk_ids}
                        except Exception as exc:
                            return row, identifier, exc

                    # Commit each query durably; optional model forwards stay sequential.
                    for item in ready:
                        result = finish(item)
                        if isinstance(result, tuple):
                            failed(result[0], result[1], "reranking", result[2])
                        else:
                            completed[result["row"]] = result
                            if journal:
                                journal.write(json.dumps(result, ensure_ascii=False) + "\n")
                                journal.flush()
                                os.fsync(journal.fileno())
                        if errors_path:
                            atomic_json(errors_path, failures)
                        report_progress()
                report_progress()
                LOGGER.info("Processed %d/%d queries; %d failed", index - first, total, len(failures))
                if index >= stop:
                    break
        finally:
            for manager in managers:
                manager.close()
    if errors_path:
        atomic_json(errors_path, failures)
    if failures:
        raise PipelineError(failures)
    if set(completed) != set(range(first, stop)):
        raise ValueError("Prediction count or checkpoint row coverage differs from input")
    predictions = [completed[row]["prediction"] for row in range(first, stop)]
    if output:
        atomic_json(output, predictions)
    if archive:
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix(".zip.partial")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target:
            target.write(output, arcname=output.name)
        temporary.replace(archive)
    return predictions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/pipeline/submission.json"))
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--manifest", dest="manifest_path", type=Path)
    parser.add_argument("--qdrant-url")
    parser.add_argument("--query-text", type=Path, help="Original text Parquet for Qwen replacement-vector output")
    parser.add_argument("--search-mode", choices=SEARCH_METHODS, default="4-branch")
    for name, default in (("batch-size", 16), ("workers", 4),
                          ("top-k", DEFAULT_TOP_K), ("branch-limit", DEFAULT_BRANCH_LIMIT), ("encoder-batch-size", 8),
                          ("hnsw-ef", DEFAULT_HNSW_EF),
                          ("reranker-batch-size", 4), ("reranker-max-length", 8192),
                          ("reranker-token-budget", 8192)):
        parser.add_argument("--" + name, type=int, default=default)
    parser.add_argument("--max-chunks", type=int, default=DEFAULT_MAX_CHUNKS,
                        help="Maximum output chunks per query (default: all retrieved chunks)")
    parser.add_argument("--max-docs", type=int, help="Maximum output document IDs per query (default: all within top-k)")
    for name in ("limit", "start", "end"):
        parser.add_argument("--" + name, type=int)
    parser.add_argument("--device", default="cpu", help="Default device for optional Qwen reranking")
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--rerank", action="store_true", help="Enable local Qwen reranking (disabled by default)")
    parser.add_argument("--reranker-device", help="Defaults to --device")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-tag", default="")
    for field in COLUMN_ALIASES:
        parser.add_argument("--" + field.replace("_", "-") + "-column")
    options = vars(parser.parse_args(argv))
    options["output_path"] = options.pop("output")
    query_text = options.pop("query_text")
    if query_text:
        combined = options["output_path"].with_suffix(".input.parquet")
        combined.parent.mkdir(parents=True, exist_ok=True)
        if not options["resume"] or not combined.exists():
            combine_query_files(options["parquet_path"], query_text, combined)
        else:
            info = json.loads(pq.read_schema(combined).metadata[b"query_embedding"])
            if (info.get("source_sha256") != sha_file(query_text) or
                    info.get("embedding_sha256") != sha_file(options["parquet_path"])):
                raise ValueError("Query text/embedding source changed; choose a new output")
        options["parquet_path"] = combined
    options["columns"] = {field: options.pop(field + "_column") for field in COLUMN_ALIASES}
    options["columns"] = {key: value for key, value in options["columns"].items() if value}
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        predictions = run_pipeline(**options)
    except (PipelineError, PipelineSetupError) as exc:
        LOGGER.error("%s", exc)
        return 1
    LOGGER.info("Wrote %d predictions to %s", len(predictions), options["output_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
