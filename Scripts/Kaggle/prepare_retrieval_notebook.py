"""Package existing retrieval sources into an uploadable CPU Kaggle notebook.

This only writes artifacts. It never imports or executes the retrieval pipeline.
"""

import base64
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "BackEnd/app/Database/Notebook/Kaggle_Retrieval_CPU.ipynb"
UPLOAD = ROOT / "artifacts/kaggle-retrieval"
SOURCES = [
    "BackEnd/__init__.py", "BackEnd/app/__init__.py", "BackEnd/app/pipeline.py",
    "BackEnd/app/Database/__init__.py", "BackEnd/app/Database/models.py",
    "BackEnd/app/Database/adapter.py", "BackEnd/app/Database/postgre_db.py",
    "BackEnd/app/Database/qdrant_db.py", "BackEnd/app/Retrieval/__init__.py",
    "BackEnd/app/Retrieval/qwen_reranker.py", "BackEnd/app/Retrieval/export.py",
    "BackEnd/app/Retrieval/store.py", "BackEnd/app/Retrieval/utils.py",
    "Scripts/Kaggle/retrieval_runtime.py", "Scripts/Kaggle/check_retrieval.py",
]


def cell(source, kind="code"):
    result = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def main(notebook_only=False):
    buffer = io.BytesIO()
    hashes = {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in SOURCES:
            content = (ROOT / name).read_bytes()
            hashes[name] = hashlib.sha256(content).hexdigest()
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 21, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, content)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    bundle_hash = hashlib.sha256(buffer.getvalue()).hexdigest()
    cells = [cell('''# Cấu hình: sửa tại đây, chọn CPU + Internet rồi Run All / Save Version (Run All).
RERANK = False
SEARCH_MODE = "4-branch"
EXACT_SEARCH = False             # True: quét chính xác nhánh dense; False: giữ tìm kiếm hiện tại
BRANCH_LIMIT = 100
TOP_K = 150

WORKERS = 2
BATCH_SIZE = 8
REQUEST_TIMEOUT = 300
QUERY_RETRIES = 2                # Thử lại lỗi mạng qua checkpoint; không chạy lại query đã đạt
QDRANT_SEARCH_THREADS = 2
RESTORE_TIMEOUT = 3600
PARITY_QUERIES = 3
LIMIT = None                    # None: toàn bộ query; số nguyên: chạy thử số query đó
START = None                    # Vị trí dòng 1-based, inclusive
END = None
MAX_DOCS = None
MAX_CHUNKS = None
QUERY_FILTER = None

QUERY_PATH = None               # Tự tìm đúng tên tệp trong /kaggle/input
SOURCE_PATH = None
SNAPSHOT_MANIFEST_PATH = None
TEMP_ROOT = "/kaggle/temp/sbtc-retrieval"
OUTPUT_DIR = "/kaggle/working/retrieval"
OUTPUT_NAME = "submission"
RESUME = True                   # Tiếp tục checkpoint nếu cell truy xuất bị gián đoạn

RERANKER_BATCH_SIZE = 1
RERANKER_MAX_LENGTH = 8192
RERANKER_TOKEN_BUDGET = 8192
'''), cell('''## Truy xuất CPU từ snapshot GTE + BM25

Giữ nguyên `BackEnd.app.pipeline.run_pipeline` và weighted RRF theo `dense_weight`
của từng query. Dùng vector có sẵn trong Parquet, không tải GTE hoặc tạo lại embedding.
SQLite chỉ giữ vị trí byte trong JSONL/JSON; văn bản đầu ra lấy nguyên văn từ bản
sao byte-for-byte trong temp, tạo cùng lượt quét/checksum nguồn để tránh random I/O trên input.
Snapshot, Qdrant, SQLite và cache nằm trong `/kaggle/temp`; chỉ kết quả và báo cáo
được lưu ở `/kaggle/working/retrieval`.

Inputs: dataset `nhminh107/sbtc-datav2-etl-20261016`, output notebook
`nhminh107/sbtc-gte-qdrant-snapshot-2gpu-20261017`, và dataset query đi kèm.
Kiểm tra đối chiếu payload Qdrant ↔ JSON trên vài query trước khi chạy toàn bộ;
kiểm tra ID, schema, văn bản gốc và ZIP sau khi hoàn tất. Nếu lỗi, cell dừng và giữ
checkpoint; không tạo bài nộp hoàn chỉnh từ kết quả thiếu query.
''', "markdown"), cell('''import atexit
import base64
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

if not Path("/kaggle/input").is_dir():
    raise RuntimeError("Notebook này chỉ chạy/kiểm thử trên Kaggle.")
TEMP = Path(TEMP_ROOT).resolve()
if not TEMP.is_relative_to(Path("/kaggle/temp")):
    raise ValueError("TEMP_ROOT phải nằm dưới /kaggle/temp")
TEMP.mkdir(parents=True, exist_ok=True)
OUT = Path(OUTPUT_DIR)
OUT.mkdir(parents=True, exist_ok=True)
for name, value in {
    "TMPDIR": str(TEMP / "tmp"), "HF_HOME": str(TEMP / "huggingface"),
    "XDG_CACHE_HOME": str(TEMP / "cache"), "PIP_CACHE_DIR": str(TEMP / "pip-cache"),
    "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false",
}.items():
    os.environ[name] = value
    if name.endswith("HOME") or name in {"TMPDIR", "PIP_CACHE_DIR"}:
        Path(value).mkdir(parents=True, exist_ok=True)
requirements = {"requests": "requests>=2.32,<3", "pyarrow": "pyarrow>=18",
                "sqlalchemy": "sqlalchemy>=2,<3", "dotenv": "python-dotenv>=1,<2",
                "psutil": "psutil>=5"}
missing = [spec for module, spec in requirements.items() if importlib.util.find_spec(module) is None]
if missing:
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", *missing], check=True)
''' + f'BUNDLE_SHA256 = {bundle_hash!r}\nSOURCE_HASHES = {hashes!r}\n' +
        f'packed = base64.b64decode({encoded!r})\n' + '''if hashlib.sha256(packed).hexdigest() != BUNDLE_SHA256:
    raise ValueError("Embedded source bundle checksum mismatch")
CODE = TEMP / "code"
CODE.mkdir(exist_ok=True)
with zipfile.ZipFile(io.BytesIO(packed)) as bundle:
    bundle.extractall(CODE)
for name, expected in SOURCE_HASHES.items():
    if hashlib.sha256((CODE / name).read_bytes()).hexdigest() != expected:
        raise ValueError(f"Embedded source checksum mismatch: {name}")
sys.path.insert(0, str(CODE))
import pyarrow.parquet as pq
import psutil
from BackEnd.app.pipeline import run_pipeline, PipelineError, _columns, _embedding_columns
from BackEnd.app.Database.qdrant_db import QdrantManager
from Scripts.Kaggle.retrieval_runtime import (
    find_input, build_source_index, JsonSourceStore, SourceQdrant,
    restore_qdrant, stop_qdrant, validate_submission, compare_query_traces,
)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", force=True,
                    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(OUT / "pipeline.log")])
RUN_STARTED = time.monotonic()
REPORT = {"success": False, "runtime": "Kaggle CPU", "source_hashes": SOURCE_HASHES,
          "bundle_sha256": BUNDLE_SHA256, "settings": {
              "rerank": RERANK, "search_mode": SEARCH_MODE, "exact_search": EXACT_SEARCH, "branch_limit": BRANCH_LIMIT,
              "top_k": TOP_K, "workers": WORKERS, "batch_size": BATCH_SIZE,
              "timeout": REQUEST_TIMEOUT, "server_query_timeout": max(1, int(REQUEST_TIMEOUT) - 10),
              "query_retries": QUERY_RETRIES,
              "limit": LIMIT, "start": START, "end": END}}
(OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
print(f"CPU={os.cpu_count()}, RAM={psutil.virtual_memory().total / 1024**3:.1f} GiB")
print("Pipeline source SHA-256:", SOURCE_HASHES["BackEnd/app/pipeline.py"])
subprocess.run([sys.executable, str(CODE / "Scripts/Kaggle/check_retrieval.py")],
               cwd=CODE, env={**os.environ, "PYTHONPATH": str(CODE)}, check=True)
REPORT["adapter_tests"] = "passed on Kaggle"
'''), cell('''# Inputs và chỉ mục SQLite nhỏ, không sao chép toàn bộ văn bản corpus.
query_path = find_input("query_rewritten_final_embeddings_weighted.parquet", QUERY_PATH)
if SOURCE_PATH:
    source_path = find_input("merged.jsonl", SOURCE_PATH)
else:
    source_matches = sorted(Path("/kaggle/input").rglob("merged.jsonl")) + sorted(Path("/kaggle/input").rglob("merged.json"))
    if len(source_matches) != 1:
        raise ValueError(f"Set SOURCE_PATH explicitly: {source_matches}")
    source_path = source_matches[0]
manifest_path = find_input("snapshot_manifest.json", SNAPSHOT_MANIFEST_PATH)
manifest = json.loads(manifest_path.read_text())
parquet = pq.ParquetFile(query_path)
mapping = _columns(parquet.schema_arrow, None)
_embedding_columns(parquet.schema_arrow)
os.environ["QDRANT_COLLECTION"] = manifest["collection"]
os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
os.environ.pop("DATABASE_URL", None)
print("Query:", query_path, "rows:", parquet.metadata.num_rows)
print("Corpus:", source_path, "Snapshot manifest:", manifest_path)
index_path = TEMP / "source.sqlite"
local_source = TEMP / ("corpus" + source_path.suffix)
REPORT["source_index"] = build_source_index(source_path, index_path, manifest, local_source=local_source)
store = JsonSourceStore(local_source, index_path)
atexit.register(store.close)
print(json.dumps(REPORT["source_index"], indent=2))
'''), cell('''# Restore bằng binary chính thức, đúng phiên bản/checksum; tất cả trạng thái trong temp.
process, qdrant_log, REPORT["restore"] = restore_qdrant(
    manifest_path, TEMP / "qdrant", search_threads=QDRANT_SEARCH_THREADS,
    timeout=RESTORE_TIMEOUT,
)
atexit.register(stop_qdrant, process, qdrant_log)
payload_trace, live_trace = [], []

def source_factory(encoder):
    return SourceQdrant.from_manifest(manifest_path, url=os.environ["QDRANT_URL"],
                                      dense_encoder=encoder, timeout=REQUEST_TIMEOUT, exact_search=EXACT_SEARCH)

def payload_factory(encoder):
    return SourceQdrant.from_manifest(manifest_path, url=os.environ["QDRANT_URL"],
                                      dense_encoder=encoder, timeout=REQUEST_TIMEOUT, exact_search=EXACT_SEARCH, ids_only=False,
                                      record_queries=payload_trace)

def live_check_factory(encoder):
    return SourceQdrant.from_manifest(manifest_path, url=os.environ["QDRANT_URL"],
                                      dense_encoder=encoder, timeout=REQUEST_TIMEOUT, exact_search=EXACT_SEARCH,
                                      record_queries=live_trace)

options = dict(
    manifest_path=manifest_path, qdrant_url=os.environ["QDRANT_URL"],
    search_mode=SEARCH_MODE, top_k=TOP_K, branch_limit=BRANCH_LIMIT,
    batch_size=BATCH_SIZE, workers=WORKERS, timeout=REQUEST_TIMEOUT,
    max_docs=MAX_DOCS, max_chunks=MAX_CHUNKS, query_filter=QUERY_FILTER,
    start=START, end=END, postgres_manager=store, device="cpu",
    resume_tag="kaggle-json-pointer-v1:" + BUNDLE_SHA256 + ":" + manifest["signature"]["source_sha256"] + ":exact=" + str(EXACT_SEARCH),
)
if PARITY_QUERIES < 1:
    raise ValueError("PARITY_QUERIES phải >= 1 để kiểm tra đối chiếu trước khi chạy")
parity_limit = min(PARITY_QUERIES, LIMIT) if LIMIT is not None else PARITY_QUERIES
checks = OUT / "checks" / OUTPUT_NAME
checks.mkdir(parents=True, exist_ok=True)
(OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
check_options = {**options, "workers": 1}

def parity_run(name, factory, trace=None):
    path = checks / (name + ".json")
    trace_path = checks / (name + ".queries.json")
    if path.exists():
        if trace is not None:
            trace.extend(json.loads(trace_path.read_text()))
        return json.loads(path.read_text())
    try:
        return run_pipeline(query_path, path, qdrant_factory=factory, limit=parity_limit,
                            resume=RESUME and path.with_suffix(".checkpoint.jsonl").exists(), **check_options)
    except Exception as error:
        REPORT["parity_error"] = {"error_type": type(error).__name__,
                                  "failures": getattr(error, "failures", [])}
        (OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
        print("Parity failure:", REPORT["parity_error"], flush=True)
        raise
    finally:
        if trace is not None:
            trace_path.write_text(json.dumps(trace, ensure_ascii=False))
        shutil.copyfile(TEMP / "qdrant" / "qdrant.log", OUT / "qdrant.log")

baseline = parity_run("payload", payload_factory, payload_trace)
live_hydrated = parity_run("json_live", live_check_factory, live_trace)
boundary_trace = []
control_manager = source_factory(None)
for recorded in payload_trace:
    body = {**recorded["body"], "limit": sum(p["limit"] for p in recorded["body"]["prefetch"])}
    result = control_manager._request("POST", control_manager._path + "/points/query", body)
    boundary_trace.append({"body": body, "result": result})
(checks / "cutoff_control.queries.json").write_text(json.dumps(boundary_trace, ensure_ascii=False))
live_comparison = compare_query_traces(payload_trace, live_trace, boundary_trace)
# Separate live RRF requests can permute tied hits. Replay identical ordered hits
# to verify that replacing PostgreSQL with JSON hydration preserves output exactly.
replay_trace = deepcopy(payload_trace)

def replay_factory(encoder):
    return SourceQdrant.from_manifest(manifest_path, url=os.environ["QDRANT_URL"],
                                      dense_encoder=encoder, timeout=REQUEST_TIMEOUT, exact_search=EXACT_SEARCH,
                                      replay_queries=replay_trace)

replayed = parity_run("json_replay", replay_factory)
if baseline != replayed:
    raise ValueError("JSON hydration changed the output for identical ordered Qdrant hits")
if not baseline or any(not p["relevant_chunks"] for p in baseline):
    raise ValueError("Đối chiếu không có ứng viên; kiểm tra snapshot/query trước khi chạy")
REPORT["parity"] = {"queries": len(baseline), "exact_predictions_match": True,
                    "baseline": "unchanged run_pipeline + original Qdrant payload",
                    "adapter": "unchanged run_pipeline + identical ordered hits + SQLite/JSON hydration",
                    "live_query_comparison": live_comparison}
print("PASS:", REPORT["parity"])
(OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
del baseline, live_hydrated, replayed, payload_trace, live_trace, replay_trace, boundary_trace
'''), cell('''# Chạy toàn bộ query, checkpoint sau từng query, Qwen chỉ tải khi bật RERANK.
if RERANK:
    if importlib.util.find_spec("torch") is None:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", "torch>=2.6"], check=True)
    if importlib.util.find_spec("transformers") is None:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir",
                        "transformers>=4.56,<6", "huggingface-hub>=0.30"], check=True)
    from huggingface_hub import snapshot_download
    from BackEnd.app.Retrieval.qwen_reranker import MODEL_NAME, MODEL_REVISION
    snapshot_download(MODEL_NAME, revision=MODEL_REVISION, cache_dir=TEMP / "huggingface" / "hub")
output = OUT / (OUTPUT_NAME + ".json")
archive = OUT / (OUTPUT_NAME + ".zip")
checkpoint = output.with_suffix(".checkpoint.jsonl")

def progress(state):
    if state["completed"] % BATCH_SIZE == 0 or state["completed"] == state["total"]:
        print(f"Progress {state['completed']}/{state['total']}; failures={state['failed']}", flush=True)

try:
    if not output.exists():
        for attempt in range(QUERY_RETRIES + 1):
            try:
                predictions = run_pipeline(
                    query_path, output, zip_path=archive, checkpoint_path=checkpoint,
                    resume=RESUME and checkpoint.exists(), limit=LIMIT, qdrant_factory=source_factory,
                    rerank=RERANK, reranker_device="cpu", reranker_batch_size=RERANKER_BATCH_SIZE,
                    reranker_max_length=RERANKER_MAX_LENGTH, reranker_token_budget=RERANKER_TOKEN_BUDGET,
                    model_cache=TEMP / "huggingface" / "hub", progress_callback=progress, **options,
                )
                break
            except PipelineError as error:
                transient = {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "ChunkedEncodingError"}
                if not RESUME or attempt == QUERY_RETRIES or any(
                    f["stage"] != "retrieval" or f["error_type"] not in transient for f in error.failures
                ):
                    raise
                REPORT.setdefault("retrieval_retries", []).append({"attempt": attempt + 1, "failures": error.failures})
                (OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
                print("Retrying transient retrieval failures from checkpoint:", error.failures, flush=True)
                time.sleep(2)
        del predictions
    else:
        print("Đã có submission; kiểm tra lại ở cell tiếp theo.")
except BaseException as error:
    REPORT["error_type"] = type(error).__name__
    REPORT["seconds"] = time.monotonic() - RUN_STARTED
    (OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
    shutil.copyfile(TEMP / "qdrant" / "qdrant.log", OUT / "qdrant.log")
    raise
'''), cell('''# Kiểm tra toàn bộ schema/ID/thứ tự, từng chunk nguyên văn và nội dung ZIP.
first = (START or 1) - 1
stop = END if END is not None else parquet.metadata.num_rows
if LIMIT is not None:
    stop = min(stop, first + LIMIT)
expected_ids = pq.read_table(query_path, columns=[mapping["id"]]).column(0).to_pylist()[first:stop]
REPORT["validation"] = validate_submission(output, archive, checkpoint, expected_ids, store, start_row=first)
REPORT["seconds"] = time.monotonic() - RUN_STARTED
REPORT["resources"] = {
    "python_rss_gib": psutil.Process().memory_info().rss / 1024**3,
    "qdrant_rss_gib": psutil.Process(process.pid).memory_info().rss / 1024**3,
    "temp_free_gib": shutil.disk_usage(TEMP).free / 1024**3,
}
REPORT["success"] = True
(OUT / "run_report.json").write_text(json.dumps(REPORT, indent=2))
shutil.copyfile(TEMP / "qdrant" / "qdrant.log", OUT / "qdrant.log")
print(json.dumps(REPORT, indent=2))
print("Kết quả:", output, archive)
stop_qdrant(process, qdrant_log)
''')]
    notebook = {"cells": cells, "metadata": {"kernelspec": {
        "display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"}},
        "nbformat": 4, "nbformat_minor": 4}
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n")
    kernel_dir, dataset_dir = UPLOAD / "kernel", UPLOAD / "queries"
    kernel_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(NOTEBOOK, kernel_dir / NOTEBOOK.name)
    kernel_metadata = {
        "id": "nhminh107/sbtc-retrieval-cpu-20261021", "title": "SBTC Retrieval CPU 20261021",
        "code_file": NOTEBOOK.name, "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": False, "enable_internet": True,
        "dataset_sources": ["nhminh107/sbtc-datav2-etl-20261016",
                            "nhminh107/sbtc-query-embeddings-weighted-20261021"],
        "kernel_sources": ["nhminh107/sbtc-gte-qdrant-snapshot-2gpu-20261017"],
        "competition_sources": [], "model_sources": [],
    }
    (kernel_dir / "kernel-metadata.json").write_text(json.dumps(kernel_metadata, indent=2) + "\n")
    if not notebook_only:
        query = ROOT / "artifacts/query-embeddings/query_rewritten_final_embeddings_weighted.parquet"
        shutil.copyfile(query, dataset_dir / query.name)
        metadata = {
            "title": "SBTC query embeddings weighted 20261021",
            "id": "nhminh107/sbtc-query-embeddings-weighted-20261021",
            "licenses": [{"name": "other"}],
            "description": "Private input for the SBTC CPU retrieval notebook. Original weighted query Parquet, unchanged. Rights retained by the original authors; private use only.",
        }
        (dataset_dir / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (UPLOAD / "source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"Prepared {NOTEBOOK}; {len(SOURCES)} source files, bundle SHA-256 {bundle_hash}")
    print(f"Upload folders: {dataset_dir}; {kernel_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook-only", action="store_true", help="Reuse the query dataset already uploaded to Kaggle")
    main(notebook_only=parser.parse_args().notebook_only)
