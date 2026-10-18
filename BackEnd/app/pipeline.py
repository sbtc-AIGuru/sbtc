"""Four-branch Qdrant retrieval -> source hydration -> LLM reranking -> BTC JSON."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import logging
import os
from pathlib import Path
from threading import Event, Lock, local
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from .Database.postgre_db import PostgreManager
from .Database.qdrant_db import QdrantManager
from .LLM import llm_as_reranker
from .Retrieval.export import btc_normalized
from .Retrieval.utils import atomic_json, sha_file, source_id

LOGGER = logging.getLogger(__name__)
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


def _check_qdrant(*, url, manifest_path, timeout):
    manager = (QdrantManager.from_manifest(manifest_path, url=url, timeout=timeout)
               if manifest_path else QdrantManager(url, timeout=timeout))
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
        sparse = info["config"]["params"].get("sparse_vectors") or {}
        if manager.sparse_vector_name not in sparse:
            raise PipelineSetupError(
                "retrieval", "QDRANT_HYBRID_REQUIRED",
                "Collection hiện không có vector BM25. Pipeline bốn nhánh cần collection hybrid GTE + BM25; "
                "snapshot chỉ có dense chưa đủ để chạy.",
            )


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


def _doc_id(value) -> str:
    if isinstance(value, str) and value.isascii() and value.isdecimal() and str(int(value)) == value:
        value = int(value)
    return str(source_id(value))


def _candidates(hits: list[dict], metadata: dict) -> tuple[list[str], list[dict], dict]:
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
    batch_size: int = 16, workers: int = 4, llm_workers: int = 2,
    top_k: int = 100, branch_limit: int = 50,
    max_docs: int | None = None, max_chunks: int | None = None,
    limit: int | None = None, query_filter: dict | None = None,
    start: int | None = None, end: int | None = None,
    manifest_path: str | Path | None = None, qdrant_url: str | None = None,
    timeout: float = 30, llm_timeout: float = 120,
    device: str = "cpu", encoder_batch_size: int = 8,
    model_cache: str | Path | None = None,
    dense_encoder: Callable | None = None, qdrant_factory: Callable | None = None,
    postgres_manager: PostgreManager | None = None, llm_client=None,
    checkpoint_path: str | Path | None = None, resume: bool = False,
    resume_tag: str = "",
    progress_callback: Callable | None = None, stop_event: Event | None = None,
) -> list[dict]:
    """Return BTC predictions in input order and optionally write JSON plus ZIP.

    ``qdrant_factory(encoder)`` must return an owned manager per worker. Injected
    PostgreSQL/LLM clients remain caller-owned. A checkpoint stores successful rows
    and original chunk IDs; failed rows are retried on resume. With injected
    components, supply a stable ``resume_tag`` identifying their configuration.
    Missing translations are errors: the four-branch method requires VI/EN/ZH.
    No relevance cutoff is assumed; defaults retain all 100 fused candidates.
    ``start``/``end`` are inclusive 1-based input row positions, not query IDs.
    Omitted bounds select the first/last row. Progress follows durable batches;
    stop_event pauses before the next batch without losing committed rows.
    """
    if min(batch_size, workers, llm_workers, top_k, branch_limit, encoder_batch_size) < 1:
        raise ValueError("Batch sizes, worker counts and retrieval limits must be positive")
    if timeout <= 0 or llm_timeout <= 0 or (limit is not None and limit < 1):
        raise ValueError("Timeouts and limit must be positive")
    if any(value is not None and value < 0 for value in (max_docs, max_chunks)):
        raise ValueError("Output budgets must be nonnegative")
    injected = any(value is not None for value in (dense_encoder, qdrant_factory, postgres_manager, llm_client))
    if resume and injected and not resume_tag:
        raise ValueError("Set resume_tag to identify injected component configuration")
    parquet_path = Path(parquet_path)
    parquet = pq.ParquetFile(parquet_path)
    mapping = _columns(parquet.schema_arrow, columns)
    row_count = parquet.metadata.num_rows
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
    if manifest and any(manifest["signature"].get(k) != v for k, v in GTE_CONFIG.items()):
        raise ValueError("Manifest embedding model differs from the pinned GTE encoder")
    settings = {
        "input": sha_file(parquet_path), "columns": mapping, "top_k": top_k,
        "branch_limit": branch_limit, "max_docs": max_docs, "max_chunks": max_chunks,
        "limit": limit, "filter": query_filter, "manifest": manifest, "gte": GTE_CONFIG,
        "url": qdrant_url or os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        "collection": os.getenv("QDRANT_COLLECTION", "sbtc_gte_multilingual"),
        "dense_vector": os.getenv("QDRANT_DENSE_VECTOR_NAME"),
        "sparse_vector": os.getenv("QDRANT_SPARSE_VECTOR_NAME", "bm25"),
        "database": os.getenv("DATABASE_URL"), "llm": llm_as_reranker.MODEL_NAME,
        "llm_url": llm_as_reranker.LLM_BASE_URL, "resume_tag": resume_tag,
    }
    if start is not None or end is not None:
        settings["range"] = [start, end]
    # Store only the digest: settings can contain private connection configuration.
    signature = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    completed = _checkpoint(checkpoint, signature, resume) if checkpoint else {}
    if any(row < first or row >= stop for row in completed):
        raise ValueError("Checkpoint row is outside the selected range")
    failures, seen_ids = [], set()
    thread_state, managers, manager_lock = local(), [], Lock()
    batch_vectors = {}
    checked_qdrant = False

    def encoded(texts):
        return [batch_vectors[text] for text in texts]

    def retrieve(item):
        row, identifier, query = item
        try:
            if not hasattr(thread_state, "manager"):
                if qdrant_factory:
                    manager = qdrant_factory(encoded)
                elif manifest_path:
                    manager = QdrantManager.from_manifest(manifest_path, url=qdrant_url,
                                                         dense_encoder=encoded, timeout=timeout)
                else:
                    manager = QdrantManager(qdrant_url, dense_encoder=encoded, timeout=timeout)
                thread_state.manager = manager
                with manager_lock:
                    managers.append(manager)
            hits = thread_state.manager.query_original_dense(
                query, query_filter=query_filter, with_payload=True,
                top_k=top_k, branch_limit=branch_limit,
            )
            if not isinstance(hits, list) or any(
                not isinstance(hit, dict) or not isinstance(hit.get("payload"), dict)
                for hit in hits
            ):
                raise ValueError("Invalid Qdrant point payloads")
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
        rerank_pool = resources.enter_context(ThreadPoolExecutor(max_workers=llm_workers))
        journal = resources.enter_context(checkpoint.open("a", encoding="utf-8")) if checkpoint else None
        index = 0
        try:
            for batch in parquet.iter_batches(batch_size=batch_size, columns=list(mapping.values())):
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
                        if row in completed:
                            if completed[row]["prediction"]["id"] != identifier:
                                raise ValueError("Checkpoint query alignment mismatch")
                        else:
                            active.append((row, identifier, query))
                    except ValueError as exc:
                        failed(row, identifier, "input", exc)
                if active:
                    if not checked_qdrant and qdrant_factory is None:
                        _check_qdrant(url=qdrant_url, manifest_path=manifest_path, timeout=timeout)
                        checked_qdrant = True
                    if dense_encoder is None:
                        # Initialization failures affect the service, not every row
                        # in every batch. Surface them once, before row processing.
                        dense_encoder = load_dense_encoder(device=device, batch_size=encoder_batch_size,
                                                           cache_dir=model_cache)
                    texts = list(dict.fromkeys(query["original_query"] for _, _, query in active))
                    try:
                        vectors = dense_encoder(texts)
                        if len(vectors) != len(texts):
                            raise ValueError("Encoder returned the wrong number of vectors")
                        batch_vectors = dict(zip(texts, vectors, strict=True))
                    except Exception as exc:
                        for row, identifier, _ in active:
                            failed(row, identifier, "encoding", exc)
                        report_progress()
                        continue
                    retrieved = list(retrieval_pool.map(retrieve, active))
                    needed = set()
                    for _, _, _, hits in retrieved:
                        if isinstance(hits, Exception):
                            continue
                        for hit in hits:
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
                    if any(item[4] for item in ready) and llm_client is None:
                        try:
                            if not llm_as_reranker.LLM_API_KEY:
                                raise ValueError("LLM_API_KEY must be configured")
                            llm_client = resources.enter_context(llm_as_reranker.OpenAI(
                                api_key=llm_as_reranker.LLM_API_KEY,
                                base_url=llm_as_reranker.LLM_BASE_URL, timeout=llm_timeout,
                            ))
                        except Exception as exc:
                            for row, identifier, _, _, chunks, _ in ready:
                                if chunks:
                                    failed(row, identifier, "reranking", exc)
                            ready = [item for item in ready if not item[4]]

                    def finish(item):
                        row, identifier, query, docs, chunks, identities = item
                        try:
                            prediction = llm_as_reranker.rerank(
                                query["original_query"],
                                {"id": identifier, "relevant_docs": docs, "relevant_chunks": chunks},
                                client=llm_client,
                            )
                            prediction["relevant_docs"] = prediction["relevant_docs"][:max_docs]
                            prediction["relevant_chunks"] = prediction["relevant_chunks"][:max_chunks]
                            chunk_ids = [identities[(c["doc_id"], c["chunk_text"])]
                                         for c in prediction["relevant_chunks"]]
                            return {"row": row, "prediction": prediction, "chunk_ids": chunk_ids}
                        except Exception as exc:
                            return row, identifier, exc

                    for result in rerank_pool.map(finish, ready):
                        if isinstance(result, tuple):
                            failed(result[0], result[1], "reranking", result[2])
                        else:
                            completed[result["row"]] = result
                            if journal:
                                journal.write(json.dumps(result, ensure_ascii=False) + "\n")
                    if journal:
                        journal.flush()
                        os.fsync(journal.fileno())
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
    for name, default in (("batch-size", 16), ("workers", 4), ("llm-workers", 2),
                          ("top-k", 100), ("branch-limit", 50), ("encoder-batch-size", 8)):
        parser.add_argument("--" + name, type=int, default=default)
    for name in ("max-docs", "max-chunks", "limit", "start", "end"):
        parser.add_argument("--" + name, type=int)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--llm-timeout", type=float, default=120)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-tag", default="")
    for field in COLUMN_ALIASES:
        parser.add_argument("--" + field.replace("_", "-") + "-column")
    options = vars(parser.parse_args(argv))
    options["output_path"] = options.pop("output")
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
