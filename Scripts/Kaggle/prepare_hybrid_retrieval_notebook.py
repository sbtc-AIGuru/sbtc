"""Build a modular private Kaggle notebook and its paired query/source dataset."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/kaggle-hybrid-retrieval-20261026"
NAME = "ViBioMIR_Hybrid_Qwen3_Elasticsearch_Kaggle.ipynb"
REF = "nhminh107/vibiomir-hybrid-retrieval-qwen3-es-20261026"
DATASET = "nhminh107/vibiomir-query-weighted-qwen3-20261026"
TEXT_PATH = Path("/home/nhminh/Downloads/query_rewritten_weighted.parquet")
VECTOR_PATH = ROOT / "query/query_rewritten_weighted_qwen3_1024_fp16.parquet"
SOURCES = [
    "BackEnd/__init__.py", "BackEnd/app/__init__.py", "BackEnd/app/pipeline.py",
    "BackEnd/app/Database/__init__.py", "BackEnd/app/Database/models.py",
    "BackEnd/app/Database/adapter.py", "BackEnd/app/Database/postgre_db.py",
    "BackEnd/app/Database/qdrant_db.py", "BackEnd/app/Database/elastic_search.py",
    "BackEnd/app/Retrieval/__init__.py", "BackEnd/app/Retrieval/hybrid.py",
    "BackEnd/app/Retrieval/query_inputs.py", "BackEnd/app/Retrieval/qwen_reranker.py",
    "BackEnd/app/Retrieval/export.py", "BackEnd/app/Retrieval/store.py",
    "BackEnd/app/Retrieval/utils.py", "BackEnd/app/api/main.py",
    "FrontEnd/index.html", "FrontEnd/app.js", "FrontEnd/styles.css",
    "Scripts/Kaggle/restore_vibiomir_qdrant.py",
    "Scripts/Kaggle/hybrid_retrieval_runtime.py",
    "Scripts/LanguageLabeling/label_chunks.py",
]
INPUT_KERNELS = [
    "nhminh107/vibiomir-qdrant-snapshot-recheck-20261025/1",
    "nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025/1",
]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def cell(kind, name, source):
    result = {"cell_type": kind, "id": name, "metadata": {}, "source": source.strip() + "\n"}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def notebook_document(input_hashes, *, run_full=False, hnsw_ef=512):
    if hnsw_ef is not None and hnsw_ef < 1:
        raise ValueError("hnsw_ef must be positive")
    cells = [cell("markdown", "intro", """
# ViBioMIR — Qwen3 dense + Elasticsearch BM25 + adaptive RRF

Chạy pipeline hiện tại trên Kaggle, không tạo lại embedding. **Mỗi code cell là một module**;
markdown ngay trước cell mô tả đầu vào, đầu ra và cách chạy lại.

- Qdrant: snapshot Qwen3 0.6B, 1024 chiều, FP16, HNSW đã dựng đủ 4.936.835 point.
- Elasticsearch 9.5.1: BM25 riêng `content_vi/content_en/content_zh`; giữ PyVi/OpenCC/SmartCN.
- Dùng nguyên `BackEnd.app.pipeline.run_pipeline`, adaptive weighted RRF `k=2`, checkpoint,
  khử trùng lặp, tùy chọn Qwen rerank và schema JSON/ZIP. Không dùng Qdrant BM25.
- Hai file query nằm trong dataset riêng tư đi kèm; corpus tải từ link Drive đã cung cấp.

**Bản upload mặc định `RUN_PIPELINE=False`**: kiểm tra mã nguồn, query và RRF, không tải corpus,
restore 18,82 GB snapshot hoặc dựng Elasticsearch. Để chạy thật: chọn **CPU + Internet**,
đổi `RUN_PIPELINE=True`, rồi **Run All**. Toàn bộ corpus sẽ được index BM25 trong phiên Kaggle.
Tất cả dữ liệu lớn ở `/kaggle/temp`; chỉ kết quả/checkpoint/log nhỏ ở `/kaggle/working/retrieval`.
Phiên Kaggle mới mất dịch vụ/index tạm; có hướng dẫn checkpoint ở cuối notebook.
""")]

    def module(name, title, description, source):
        cells.append(cell("markdown", name + "-description", f"## {title}\n\n{description}"))
        cells.append(cell("code", name, source))

    module("configuration", "01 · Cấu hình lần chạy", "Chỉ sửa tham số ở cell này. Mặc định: 4 nhánh, 100/nhánh, top 200, ef=512, tắt rerank. `HNSW_EF=None` giữ mặc định snapshot; đổi ef/exact phải dùng `OUTPUT_NAME` mới.", '''
RUN_PIPELINE = False
SEARCH_MODE = "4-branch"       # "3-branch" (Dense VI/EN/ZH), "4-branch" hoặc "6-branch"
BRANCH_LIMIT = 100
TOP_K = 200
HNSW_EF = None                # None giữ nguyên mặc định; có thể tự thử 128/256/512
EXACT_SEARCH = False          # True quét exact rất tốn CPU, không bật cho chạy thường
RERANK = False
WORKERS = 4
BATCH_SIZE = 32
START = None                  # Dòng 1-based, inclusive; None từ đầu file
END = None                    # None đến cuối file
LIMIT = None                  # None chạy đủ 1.200 query
MAX_DOCS = None
MAX_CHUNKS = None
QUERY_FILTER = None
REQUEST_TIMEOUT = 300
QUERY_RETRIES = 2
SMOKE_QUERIES = 3
ES_BATCH_SIZE = 1000          # Preprocessing 1 worker, tương thích Python Kaggle hiện có
ES_HEAP_GB = 2
SERVICE_THREADS = 2
RESTORE_TIMEOUT = 7200
TEMP_ROOT = "/kaggle/temp/sbtc-hybrid-20261026"
OUTPUT_DIR = "/kaggle/working/retrieval"
OUTPUT_NAME = "submission"
RESUME = True
RERANKER_DEVICE = "cpu"       # Nếu tự bật GPU, đặt "cuda:0"
RERANKER_BATCH_SIZE = 4
RERANKER_MAX_LENGTH = 8192
RERANKER_TOKEN_BUDGET = 8192
CHUNK_URL = "https://drive.google.com/uc?export=download&id=1KtU4YsDJrn837dQgeLispoD3fb_uWMSp"
CHUNK_BYTES = 5_734_771_809
SOURCE_SHA256 = "a45123b3de7a9b048f83418515a3ec6b3dd09e1e4491dd361429b787659a3e7f"
LABELED_SHA256 = "c973c3117f917ee7c14d8e671c459d8ca5a783610c62e3c8b00141a9bfbb91ae"
LABELS_SHA256 = "2d57697aa826dc8f0c53efb831380341ab5a3f6a8fe8f54b15e83632fd104a5b"
LANGUAGE_COUNTS = {"vi": 3_811_358, "en": 540_913, "zh": 584_564}
SNAPSHOT_SHA256 = "fb8b93924f5141ae5603033ea4c1df46ee29315f0e4c2ab1541680b9ed358646"
EXPECTED_POINTS = 4_936_835
SNAPSHOT_KERNEL = "nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025/1"
''')
    module("environment", "02 · Môi trường và dependency", "Dùng Python kernel có sẵn, không tạo venv. Cài dependency vào chính kernel; cache đặt trong temp. Dừng sớm nếu không phải Kaggle hoặc thư mục tạm nằm ngoài `/kaggle/temp`.", '''
import atexit
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

if not Path("/kaggle/input").is_dir():
    raise RuntimeError("Notebook này dành cho Kaggle; kiểm thử local bằng test đóng gói.")
TEMP = Path(TEMP_ROOT).resolve()
if not TEMP.is_relative_to(Path("/kaggle/temp")):
    raise ValueError("TEMP_ROOT phải nằm trong /kaggle/temp")
TEMP.mkdir(parents=True, exist_ok=True)
TEMP.chmod(0o755)
OUT = Path(OUTPUT_DIR)
OUT.mkdir(parents=True, exist_ok=True)
for key, name in {"TMPDIR": "tmp", "XDG_CACHE_HOME": "cache", "HF_HOME": "huggingface", "PIP_CACHE_DIR": "pip-cache"}.items():
    os.environ[key] = str(TEMP / name)
    Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
os.environ.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", TOKENIZERS_PARALLELISM="false")
os.environ.pop("DATABASE_URL", None)
packages = ["numpy>=1.26", "pyarrow>=18", "requests>=2.32,<3", "sqlalchemy>=2,<3",
            "orjson>=3.10,<4",
            "python-dotenv>=1,<2", "elasticsearch==9.5.1", "pyvi==0.1.1",
            "opencc-python-reimplemented==0.1.7", "gdown>=5.2,<6",
            "fastapi>=0.115,<1", "uvicorn>=0.30,<1", "python-multipart>=0.0.20,<1"]
subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *packages], check=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", force=True,
                    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(OUT / "pipeline.log")])
print("Python:", sys.version, "CPU:", os.cpu_count(), "RUN_PIPELINE:", RUN_PIPELINE)
''')
    module("source-code", "03 · Nạp nguyên mã pipeline", "Kaggle tự giải nén ZIP thành thư mục `pipeline_source/`. Dùng manifest SHA-256 để kiểm tra từng file trước khi import; không clone repo, không đóng gói `.env`, API key hoặc credentials. API/UI cũng có trong thư mục mã nguồn để đối chiếu; notebook gọi pipeline trực tiếp.", f'''
EXPECTED_INPUT_HASHES = {input_hashes!r}
INPUT = Path("/kaggle/input")

def unique_input(name):
    paths = sorted(INPUT.rglob(name))
    if len(paths) != 1:
        raise ValueError(f"Cần đúng một {{name}}; thấy {{len(paths)}}")
    return paths[0]

def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()

for name, expected in EXPECTED_INPUT_HASHES.items():
    if name == "pipeline_source.zip":
        continue  # Kaggle expands this archive; verify its individual members below.
    if file_hash(unique_input(name)) != expected:
        raise ValueError(f"Input checksum mismatch: {{name}}")
manifest_file = unique_input("source-manifest.json")
source_manifest = json.loads(manifest_file.read_text())
SOURCE = manifest_file.parent / "pipeline_source"
CODE = TEMP / "code"
CODE.mkdir(exist_ok=True)
for name, expected in source_manifest["sources"].items():
    target = (CODE / name).resolve()
    if not target.is_relative_to(CODE.resolve()):
        raise ValueError("Unsafe source archive path")
    content = (SOURCE / name).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"Source checksum mismatch: {{name}}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
sys.path.insert(0, str(CODE))
from BackEnd.app import pipeline
from BackEnd.app.Retrieval.query_inputs import combine_query_files
from Scripts.Kaggle import hybrid_retrieval_runtime as runtime
REPORT = {{"success": False, "mode": "full" if RUN_PIPELINE else "validation-only",
           "source_hashes": source_manifest["sources"], "input_hashes": EXPECTED_INPUT_HASHES,
           "settings": {{"search_mode": SEARCH_MODE, "branch_limit": BRANCH_LIMIT, "top_k": TOP_K,
                        "hnsw_ef": HNSW_EF, "exact": EXACT_SEARCH, "rerank": RERANK,
                        "start": START, "end": END, "limit": LIMIT}}}}
print("Verified source files:", len(source_manifest["sources"]))
''')
    module("query-input", "04 · Ghép query gốc và vector", "Đầu vào: hai Parquet gốc được upload nguyên byte. Đầu ra: Parquet gồm text + vector + dense_weight. Kiểm tra source SHA, row ID, norm FP16 và hash text của cả 1.200 dòng; không embedding lại.", '''
import pyarrow.parquet as pq
vector_path = unique_input("query_rewritten_weighted_qwen3_1024_fp16.parquet")
text_path = unique_input("query_rewritten_weighted.parquet")
query_path = TEMP / "query_with_text.parquet"
if not query_path.exists():
    combine_query_files(vector_path, text_path, query_path)
else:
    provenance = json.loads(pq.read_schema(query_path).metadata[b"query_embedding"])
    if (provenance.get("embedding_sha256") != EXPECTED_INPUT_HASHES[vector_path.name] or
            provenance.get("source_sha256") != EXPECTED_INPUT_HASHES[text_path.name]):
        raise ValueError("Cached combined query belongs to other inputs; use a fresh TEMP_ROOT")
with pq.ParquetFile(query_path) as source:
    mapping = pipeline._columns(source.schema_arrow, None)
    pipeline._embedding_columns(source.schema_arrow)
    query_rows = source.metadata.num_rows
    for batch in source.iter_batches(batch_size=64):
        for row in batch.to_pylist():
            query = {key: row[name] for key, name in mapping.items() if key != "id"}
            pipeline._query_vectors(row, query, dimension=1024, tolerance=.002)
            if SEARCH_MODE != "3-branch":
                pipeline.parse_dense_weight(row.get("dense_weight"))
REPORT["query_rows"] = query_rows
print("Validated query rows:", query_rows)
''')
    module("rrf-self-check", "05 · Kiểm tra adaptive RRF", "Kiểm tra nhẹ, luôn chạy kể cả chế độ validation-only. Xác nhận công thức rank-weighting Qdrant, ghép bằng chunk_id và loại hoàn toàn nhánh trọng số 0; không gọi dịch vụ.", '''
from BackEnd.app.Retrieval.hybrid import weighted_rrf
def fixture_hit(chunk_id):
    return {"id": chunk_id, "payload": {"chunk_id": chunk_id, "doc_id": 1, "chunk_text": "Original"}}
a, b = fixture_hit("a"), fixture_hit("b")
fused = weighted_rrf([[a], [b]], [.75, .25], 2)
assert fused[0]["payload"]["chunk_id"] == "a"
assert abs(fused[0]["score"] - 1 / (1 / .75 + 1)) < 1e-6
assert len(weighted_rrf([[a], [b]], [1, 0], 10)) == 1
REPORT["rrf_self_check"] = "passed"
runtime.atomic_json(OUT / "run_report.json", REPORT)
print("Adaptive weighted RRF checks passed")
''')
    module("snapshot-input", "06 · Xác minh nguồn snapshot", "Gắn output version 1 của cả notebook recheck và notebook snapshot gốc. Kiểm tra chứng nhận ràng buộc đúng SHA/signature/count. Manifest recovery gốc giữ nguyên; tạo manifest runtime riêng từ chứng nhận đã xác minh.", '''
if RUN_PIPELINE:
    expected = {"snapshot_kernel": SNAPSHOT_KERNEL, "snapshot_sha256": SNAPSHOT_SHA256,
                "points": EXPECTED_POINTS, "source_sha256": SOURCE_SHA256}
    manifest_path, snapshot_path, runtime_manifest = runtime.verify_snapshot_inputs(INPUT, expected)
    runtime_manifest_path = TEMP / "runtime-snapshot-manifest.json"
    runtime.atomic_json(runtime_manifest_path, runtime_manifest)
    budget = 3 * snapshot_path.stat().st_size + (2 * 1024**3 if SEARCH_MODE == "3-branch" else CHUNK_BYTES + 20 * 1024**3)
    REPORT["disk"] = runtime.ensure_free_disk(TEMP, budget)
    print("Snapshot:", snapshot_path, "points:", runtime_manifest["points"])
else:
    print("Skipped snapshot restore preflight: RUN_PIPELINE=False")
''')
    module("chunk-download", "07 · Tải corpus từ Google Drive", "Tải streaming/resume bằng gdown vào temp. Chỉ chấp nhận đúng 5.734.771.809 byte và SHA-256 nguồn đã dùng để embedding snapshot. File tải lỗi không được coi là corpus hoàn chỉnh.", '''
if RUN_PIPELINE and SEARCH_MODE != "3-branch":
    source_path = runtime.download_chunks(CHUNK_URL, TEMP / "ViBioMIR_chunks_with_recovery.jsonl",
                                          SOURCE_SHA256, CHUNK_BYTES)
    REPORT["corpus"] = {"sha256": SOURCE_SHA256, "bytes": source_path.stat().st_size}
    print("Verified corpus:", source_path)
else:
    print("Skipped 5.73 GB corpus download")
''')
    module("language-preparation", "08 · Gán nhãn ngôn ngữ như bản local", "Corpus gốc của snapshot chưa có language. Dùng nguyên detect_language của dự án: NFC, có chữ Hán → zh, có dấu Việt → vi, còn lại en. Ghi một bản riêng, giữ nguyên các trường gốc; kiểm tra checksum nhãn, checksum corpus đã gán nhãn và số lượng từng ngôn ngữ khớp bản Elasticsearch local.", '''
if RUN_PIPELINE and SEARCH_MODE != "3-branch":
    bm25_source_path = TEMP / "ViBioMIR_chunks_with_language.jsonl"
    REPORT["languages"] = runtime.prepare_languages(source_path, bm25_source_path,
        source_sha256=SOURCE_SHA256, labeled_sha256=LABELED_SHA256,
        labels_sha256=LABELS_SHA256, expected_counts=LANGUAGE_COUNTS)
    print("Verified language enrichment:", REPORT["languages"])
else:
    print("Skipped full corpus language preparation")
''')
    module("elasticsearch-install", "09 · Chuẩn bị Elasticsearch + SmartCN", "Tải archive chính thức Elasticsearch 9.5.1 và SmartCN 9.5.1, kiểm tra SHA-512 trước khi giải nén/cài plugin. Không dùng Docker hoặc thay sysctl của máy Kaggle.", '''
if RUN_PIPELINE and SEARCH_MODE != "3-branch":
    es_home = runtime.install_elasticsearch(TEMP / "elasticsearch")
    print("Elasticsearch installed:", es_home)
else:
    print("Skipped Elasticsearch binary/plugin installation")
''')
    module("elasticsearch-service", "10 · Khởi động Elasticsearch", "Chỉ bind 127.0.0.1:9200. Nếu kernel chạy root, dịch vụ hạ quyền xuống tài khoản nobody trong thư mục riêng; không đổi tài khoản notebook. Heap mặc định 2 GiB, giới hạn 2 CPU processors.", '''
if RUN_PIPELINE and SEARCH_MODE != "3-branch":
    os.environ["ELASTICSEARCH_URL"] = "http://127.0.0.1:9200"
    os.environ["ELASTICSEARCH_INDEX"] = "vibiomir_bm25"
    for key in ("ELASTICSEARCH_API_KEY", "ELASTICSEARCH_USERNAME", "ELASTICSEARCH_PASSWORD", "ELASTICSEARCH_CA_CERTS"):
        os.environ.pop(key, None)
    es_process, es_log, REPORT["elasticsearch_service"] = runtime.start_elasticsearch(
        es_home, heap_gb=ES_HEAP_GB, processors=SERVICE_THREADS)
    atexit.register(runtime.stop_service, es_process, es_log)
    print(REPORT["elasticsearch_service"])
else:
    print("Skipped Elasticsearch startup")
''')
    module("bm25-index", "11 · Dựng BM25 ba ngôn ngữ", "Dùng nguyên mapping, prepare_text và bulk_index của dự án trên bản corpus có language. Đọc JSONL streaming, batch 1.000, một worker để tương thích Python Kaggle. Đây là cell tốn thời gian; phải đạt đủ count mới cho chạy retrieval. Chạy lại cùng phiên dùng receipt, không nạp lại index đã hoàn tất.", '''
if RUN_PIPELINE and SEARCH_MODE != "3-branch":
    REPORT["bm25"] = runtime.build_bm25(bm25_source_path, "vibiomir_bm25", TEMP / "bm25-receipt.json",
        source_sha256=LABELED_SHA256, expected_count=EXPECTED_POINTS, batch_size=ES_BATCH_SIZE)
    runtime.atomic_json(OUT / "run_report.json", REPORT)
    print("BM25 complete:", REPORT["bm25"])
else:
    print("Skipped full corpus BM25 indexing")
''')
    module("qdrant-service", "12 · Restore Qdrant dense", "Tải binary Qdrant 1.19.2 đã pin SHA-256, stage và kiểm tra snapshot, restore graph sẵn có vào temp. Giữ m=32, ef_construct=100, FP16/on-disk; không upsert, embedding hay dựng lại HNSW. Server/client timeout được đặt rõ để tránh deadline 60 giây của phiên cold-start.", '''
if RUN_PIPELINE:
    os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
    os.environ["QDRANT_COLLECTION"] = runtime_manifest["collection"]
    os.environ["QDRANT_DENSE_VECTOR_NAME"] = "qwen3_dense"
    os.environ.pop("QDRANT_API_KEY", None)
    qdrant_process, qdrant_log, REPORT["qdrant_service"] = runtime.restore_qdrant(
        snapshot_path, runtime_manifest, TEMP / "qdrant", search_threads=SERVICE_THREADS, timeout=RESTORE_TIMEOUT)
    atexit.register(runtime.stop_service, qdrant_process, qdrant_log)
    from Scripts.Kaggle.restore_vibiomir_qdrant import verify_collection
    samples = json.loads((manifest_path.parent / "verification_samples.json").read_text())
    REPORT["snapshot_verification"] = verify_collection(
        os.environ["QDRANT_URL"], runtime_manifest, samples, search_timeout=max(1, REQUEST_TIMEOUT - 10))
    runtime.atomic_json(OUT / "run_report.json", REPORT)
    print("Restored dense points:", REPORT["qdrant_service"]["points"])
else:
    print("Skipped snapshot staging and Qdrant restore")
''')
    module("reranker", "13 · Reranker tùy chọn", "Mặc định bỏ qua. Nếu bật, tải model đúng revision vào cache temp rồi dùng nguyên QwenReranker của dự án. Không tự bật GPU; CPU reranking có thể làm phiên chạy rất lâu.", '''
if RUN_PIPELINE and RERANK:
    optional = ["transformers>=4.57,<6", "huggingface_hub>=0.34,<2"]
    if importlib.util.find_spec("torch") is None:
        optional.append("torch>=2.5")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *optional], check=True)
    import shutil
    from BackEnd.app.Retrieval.qwen_reranker import MODEL_NAME, MODEL_REVISION
    hf = shutil.which("hf")
    if hf is None:
        raise RuntimeError("huggingface_hub did not provide the hf CLI")
    subprocess.run([hf, "download", MODEL_NAME, "--revision", MODEL_REVISION,
                    "--cache-dir", str(TEMP / "huggingface"), "--include", "*.json", "*.safetensors",
                    "merges.txt", "vocab.json", "tokenizer.model"], check=True)
else:
    print("Reranker disabled; no model weights downloaded")
''')
    module("retrieval-options", "14 · Adapter và cấu hình pipeline", "Adapter chỉ thêm deadline, tùy chọn ef/exact và log Qdrant; scoring/RRF vẫn chạy nguyên mã đã đóng gói. Checkpoint fingerprint nhận diện nguồn/index và tham số tìm kiếm.", '''
if RUN_PIPELINE:
    run_identity = {**REPORT["settings"], "max_docs": MAX_DOCS, "max_chunks": MAX_CHUNKS,
                    "query_filter": QUERY_FILTER, "snapshot_sha256": SNAPSHOT_SHA256,
                    "reranker_device": RERANKER_DEVICE, "reranker_batch_size": RERANKER_BATCH_SIZE,
                    "reranker_max_length": RERANKER_MAX_LENGTH, "reranker_token_budget": RERANKER_TOKEN_BUDGET,
                    "source_sha256": SOURCE_SHA256, "input_hashes": EXPECTED_INPUT_HASHES}
    run_signature = hashlib.sha256(json.dumps(run_identity, sort_keys=True).encode()).hexdigest()
    def qdrant_factory(encoder):
        return runtime.NotebookQdrant.from_manifest(runtime_manifest_path,
            dense_encoder=encoder, timeout=REQUEST_TIMEOUT, hnsw_ef=HNSW_EF, exact=EXACT_SEARCH)
    options = dict(manifest_path=runtime_manifest_path, qdrant_factory=qdrant_factory,
        search_mode=SEARCH_MODE, branch_limit=BRANCH_LIMIT, top_k=TOP_K, hnsw_ef=HNSW_EF,
        query_filter=QUERY_FILTER,
        workers=WORKERS, batch_size=BATCH_SIZE, timeout=REQUEST_TIMEOUT, max_docs=MAX_DOCS,
        max_chunks=MAX_CHUNKS, rerank=RERANK, device=RERANKER_DEVICE,
        reranker_batch_size=RERANKER_BATCH_SIZE, reranker_max_length=RERANKER_MAX_LENGTH,
        reranker_token_budget=RERANKER_TOKEN_BUDGET, model_cache=TEMP / "huggingface",
        resume_tag="kaggle-hybrid-v1:" + EXPECTED_INPUT_HASHES["pipeline_source.zip"] +
            ":source=" + SOURCE_SHA256 + ":ef=" + str(HNSW_EF) + ":exact=" + str(EXACT_SEARCH))
else:
    print("Validation-only: retrieval configuration is ready")
''')
    module("backend-smoke", "15 · Smoke test hai backend", "Chạy tối đa 3 query ở phạm vi đã chọn trước khi chạy toàn bộ. Kiểm tra truy hồi và vector đã có, không dùng query giả/embedding mới. Log Qdrant ghi hits/limit/ef/latency; Elasticsearch ghi HTTP request ở mức INFO.", '''
if RUN_PIPELINE:
    smoke = pipeline.run_pipeline(query_path, start=START, end=END, limit=SMOKE_QUERIES,
                                  **{**options, "rerank": False})
    if not smoke or not all(row["relevant_docs"] and row["relevant_chunks"] for row in smoke):
        raise ValueError("Smoke queries returned no candidates")
    REPORT["smoke"] = [{"id": row["id"], "docs": len(row["relevant_docs"]), "chunks": len(row["relevant_chunks"])} for row in smoke]
    print(REPORT["smoke"])
    del smoke
else:
    print("Skipped live backend smoke test")
''')
    module("pipeline-run", "16 · Chạy pipeline và checkpoint", "Mặc định chạy đủ 1.200 dòng. Chỉ retry lỗi retrieval qua checkpoint, giữ kết quả đã lưu; lỗi input/hydration/rerank dừng và giữ báo cáo. Cell này có thể chạy lại trong cùng phiên. Output tồn tại chỉ được dùng lại khi REPORT đã xác nhận thành công.", '''
if RUN_PIPELINE:
    output_path, archive_path = OUT / (OUTPUT_NAME + ".json"), OUT / (OUTPUT_NAME + ".zip")
    checkpoint_path = output_path.with_suffix(".checkpoint.jsonl")
    saved_report = OUT / (OUTPUT_NAME + ".verified.json")
    if output_path.exists():
        saved = json.loads(saved_report.read_text()) if saved_report.exists() else {}
        if saved.get("output_sha256") != file_hash(output_path) or saved.get("run_signature") != run_signature:
            raise FileExistsError("Output already exists without matching verification; use a new OUTPUT_NAME")
        print("Output already verified:", output_path)
    else:
        run_started = time.monotonic()
        for attempt in range(QUERY_RETRIES + 1):
            try:
                predictions = pipeline.run_pipeline(query_path, output_path, zip_path=archive_path,
                    start=START, end=END, limit=LIMIT, resume=RESUME and checkpoint_path.exists(), **options)
                del predictions
                break
            except pipeline.PipelineError as error:
                if attempt == QUERY_RETRIES or any(row["stage"] != "retrieval" for row in error.failures):
                    REPORT["failed_queries"] = error.failures
                    runtime.atomic_json(OUT / "run_report.json", REPORT)
                    raise
                print("Retrying failed retrieval rows:", len(error.failures))
                time.sleep(min(30, 2 ** attempt))
        REPORT["retrieval_seconds"] = time.monotonic() - run_started
else:
    REPORT["validation_only_passed"] = True
    runtime.atomic_json(OUT / "run_report.json", REPORT)
    print("Validation-only complete. Set RUN_PIPELINE=True to run real corpus retrieval.")
''')
    module("output-validation", "17 · Kiểm tra và bàn giao JSON/ZIP", "Kiểm tra ID và thứ tự query, schema checkpoint, nguyên văn từng chunk qua lookup Qdrant (3 nhánh) hoặc Elasticsearch (4/6 nhánh) và SHA nội dung ZIP. Không đưa corpus, storage hoặc snapshot vào Output; chỉ submission/checkpoint/report/log.", '''
if RUN_PIPELINE:
    ids = pq.read_table(query_path, columns=["id"])["id"].to_pylist()
    first, stop = (START or 1) - 1, END if END is not None else len(ids)
    if LIMIT is not None:
        stop = min(stop, first + LIMIT)
    if SEARCH_MODE == "3-branch":
        with qdrant_factory(None) as manager:
            validation = runtime.validate_results(output_path, archive_path, checkpoint_path,
                ids[first:stop], qdrant=manager)
    else:
        with runtime.connect_elasticsearch() as client:
            validation = runtime.validate_results(output_path, archive_path, checkpoint_path,
                ids[first:stop], client=client, index="vibiomir_bm25")
    validation["output_sha256"] = file_hash(output_path)
    validation["run_signature"] = run_signature
    runtime.atomic_json(saved_report, validation)
    REPORT.update(success=True, validation=validation)
    runtime.atomic_json(OUT / "run_report.json", REPORT)
    from IPython.display import FileLink, display
    display(FileLink(str(archive_path)))
    print(json.dumps(validation, indent=2))
else:
    print("No submission produced in validation-only mode")
''')
    module("shutdown", "18 · Đóng dịch vụ", "Dừng các process của notebook và đóng log khi hoàn tất. Kết quả vẫn nằm trong Output. Muốn chạy lại retrieval sau cell này cần khởi động dịch vụ lại; phiên mới phải tải/restore/index lại. Đổi cấu hình hoặc nguồn thì chọn OUTPUT_NAME/TEMP_ROOT mới, không trộn checkpoint.", '''
if RUN_PIPELINE:
    runtime.stop_service(qdrant_process, qdrant_log)
    atexit.unregister(runtime.stop_service)
    if SEARCH_MODE != "3-branch":
        runtime.stop_service(es_process, es_log)
    print("Services stopped; output preserved:", OUT)
else:
    print("No services were started")
''')
    configuration_description = next(item for item in cells if item["id"] == "configuration-description")
    configuration_description["source"] += '\nChọn `SEARCH_MODE="3-branch"` để chỉ dùng Dense VI/EN/ZH, mỗi nhánh RRF 1/3, bỏ qua `dense_weight`. Chế độ này bỏ qua cell 07–11: không tải corpus hoặc dựng Elasticsearch. Đổi chế độ cần chọn OUTPUT_NAME/TEMP_ROOT mới.\n'
    if run_full:
        suffix = "ef" + str(hnsw_ef) if hnsw_ef is not None else "default"
        cells[0]["source"] = cells[0]["source"].replace(
            "**Bản upload mặc định `RUN_PIPELINE=False`**: kiểm tra mã nguồn, query và RRF, không tải corpus,\n"
            "restore 18,82 GB snapshot hoặc dựng Elasticsearch. Để chạy thật: chọn **CPU + Internet**,\n"
            "đổi `RUN_PIPELINE=True`, rồi **Run All**. Toàn bộ corpus sẽ được index BM25 trong phiên Kaggle.",
            f"**Bản chạy đầy đủ: `RUN_PIPELINE=True`, `HNSW_EF={hnsw_ef}`** trên CPU + Internet.\n"
            "Tải corpus, dựng BM25, restore snapshot Qdrant và chạy đủ 1.200 query.\n"
            f"Output riêng `submission_{suffix}` để không trộn checkpoint cấu hình khác.")
        configuration = next(item for item in cells if item["id"] == "configuration")
        configuration["source"] = configuration["source"].replace("RUN_PIPELINE = False", "RUN_PIPELINE = True").replace(
            'OUTPUT_NAME = "submission"', f'OUTPUT_NAME = "submission_{suffix}"').replace(
            'TEMP_ROOT = "/kaggle/temp/sbtc-hybrid-20261026"',
            f'TEMP_ROOT = "/kaggle/temp/sbtc-hybrid-20261026-{suffix}"')
    if hnsw_ef is not None:
        configuration = next(item for item in cells if item["id"] == "configuration")
        configuration["source"] = configuration["source"].replace("HNSW_EF = None", f"HNSW_EF = {hnsw_ef}")
    return {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python"},
                         "kaggle": {"isGpuEnabled": False, "isInternetEnabled": True}}, "cells": cells}


def prepare(output=OUTPUT, text_path=TEXT_PATH, vector_path=VECTOR_PATH, *, write_notebook=True,
            run_full=False, hnsw_ef=512):
    output = Path(output)
    data, kernel = output / "queries", output / "kernel"
    data.mkdir(parents=True, exist_ok=True)
    kernel.mkdir(parents=True, exist_ok=True)
    hashes = {name: digest(ROOT / name) for name in SOURCES}
    with zipfile.ZipFile(data / "pipeline_source.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in SOURCES:
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 26, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, (ROOT / name).read_bytes())
    (data / "source-manifest.json").write_text(json.dumps({"sources": hashes}, indent=2) + "\n")
    for source in (Path(text_path), Path(vector_path)):
        shutil.copy2(source, data / source.name)
    input_hashes = {path.name: digest(path) for path in data.iterdir() if path.name != "dataset-metadata.json"}
    notebook = notebook_document(input_hashes, run_full=run_full, hnsw_ef=hnsw_ef)
    text = json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"
    (kernel / NAME).write_text(text)
    if write_notebook:
        (ROOT / "BackEnd/app/Database/Notebook" / NAME).write_text(text)
    metadata = {"id": REF, "title": "ViBioMIR Hybrid Retrieval Qwen3 ES 20261026", "code_file": NAME,
                "language": "python", "kernel_type": "notebook", "is_private": True,
                "enable_gpu": False, "enable_tpu": False, "enable_internet": True,
                "dataset_sources": [DATASET], "competition_sources": [], "kernel_sources": INPUT_KERNELS}
    (kernel / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    dataset_metadata = {"id": DATASET, "title": "ViBioMIR Query Weighted Qwen3 20261026",
        "licenses": [{"name": "other"}],
        "description": "Private paired query Parquet files and exact retrieval source bundle. No additional redistribution permission is granted."}
    (data / "dataset-metadata.json").write_text(json.dumps(dataset_metadata, indent=2) + "\n")
    (output / "package-manifest.json").write_text(json.dumps({"dataset": DATASET, "notebook": REF,
        "input_hashes": input_hashes, "notebook_sha256": digest(kernel / NAME),
        "kernel_sources": INPUT_KERNELS, "default_run_pipeline": run_full,
        "hnsw_ef": hnsw_ef}, indent=2) + "\n")
    print(kernel / NAME)
    return notebook


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--query-text", type=Path, default=TEXT_PATH)
    parser.add_argument("--query-vectors", type=Path, default=VECTOR_PATH)
    parser.add_argument("--run-full", action="store_true", help="Prepare an explicitly requested full corpus run")
    parser.add_argument("--hnsw-ef", type=int, default=512)
    args = parser.parse_args()
    prepare(args.output, args.query_text, args.query_vectors, run_full=args.run_full, hnsw_ef=args.hnsw_ef)
