"""CLI: Giao Diện Dòng Lệnh BM25 Medical Multilingual Retrieval.

Theo SPEC-bm25-medical-multilingual.md Mục 16.
Cung cấp các lệnh: preflight, build, search, prepare-queries, evaluate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from sbtc.Scripts.Retrieval.analyzers import TokenPipelineRegistry
from sbtc.Scripts.Retrieval.config import BM25Config
from sbtc.Scripts.Retrieval.corpus import CorpusReader
from sbtc.Scripts.Retrieval.engine import BM25Engine
from sbtc.Scripts.Retrieval.evaluation import BtcEvaluator
from sbtc.Scripts.Retrieval.export import SubmissionWriter
from sbtc.Scripts.Retrieval.fusion import CandidateFusion
from sbtc.Scripts.Retrieval.identity import IdentityRegistry
from sbtc.Scripts.Retrieval.index_builder import IndexBuilder
from sbtc.Scripts.Retrieval.lexicon import MedicalLexicon
from sbtc.Scripts.Retrieval.lucene_backend import LuceneSearchBackend
from sbtc.Scripts.Retrieval.models import QueryInput
from sbtc.Scripts.Retrieval.quality import QualityPolicy
from sbtc.Scripts.Retrieval.query_bridge import QueryBridge
from sbtc.Scripts.Retrieval.query_builder import LuceneQueryBuilder
from sbtc.Scripts.Retrieval.selectors import FixedBudgetSelector, create_selector
from sbtc.Scripts.Retrieval.text_store import SourcePointerTextStore


def cmd_preflight(args: argparse.Namespace) -> None:
    """Kiểm tra điều kiện môi trường, đĩa cứng, RAM và tính toàn vẹn dữ liệu."""
    print("=" * 60)
    print("PREFLIGHT RESOURCE & ENVIRONMENT CHECK")
    print("=" * 60)

    config = BM25Config.from_toml(args.config)
    print(f"Cấu hình: {args.config}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")

    # 1. Kiểm tra Java
    java_cmd = shutil.which("java")
    print(f"Java binary: {java_cmd or 'KHÔNG TÌM THẤY'}")
    if not java_cmd:
        print("[LỖI] Java không có trong PATH. Cần OpenJDK 21.")
        sys.exit(1)

    # 2. Kiểm tra dung lượng đĩa
    config.run_dir.parent.mkdir(parents=True, exist_ok=True)
    stat_vfs = os.statvfs(config.run_dir.parent)
    avail_gb = (stat_vfs.f_bavail * stat_vfs.f_frsize) / (1024**3)
    print(f"Dung lượng đĩa trống khả dụng: {avail_gb:.2f} GB")
    if avail_gb < 10.0:
        print("[CẢNH BÁO] Dung lượng đĩa khả dụng dưới 10 GB. Cần cẩn trọng khi build full corpus.")

    # 3. Kiểm tra file Parquet
    print(f"Kiểm tra Parquet whitelist: {config.corpus_snapshot}")
    id_registry = IdentityRegistry.from_parquet(config.corpus_snapshot)
    print(f"  -> Tổng số ID hợp lệ: {id_registry.doc_count:,}")
    print(f"  -> Min ID: {id_registry.min_id}, Max ID: {id_registry.max_id}")
    print(f"  -> SHA256: {id_registry.parquet_sha256[:16]}...")

    # 4. Kiểm tra thư mục Chunks
    reader = CorpusReader(
        config.chunk_input,
        id_registry,
        QualityPolicy(config.quality),
    )
    shards = reader.get_shard_files()
    print(f"Tìm thấy {len(shards)} file shard trong: {config.chunk_input}")

    print("=" * 60)
    print("PREFLIGHT STATUS: OK! Sẵn sàng cho quá trình build.")
    print("=" * 60)


def cmd_build(args: argparse.Namespace) -> None:
    """Xây dựng SQLite SourcePointerTextStore và 6 partition Lucene Indexes."""
    config = BM25Config.from_toml(args.config)
    if args.run_dir:
        config = BM25Config(
            corpus_snapshot=config.corpus_snapshot,
            source_scope=config.source_scope,
            chunk_input=config.chunk_input,
            run_dir=Path(args.run_dir).resolve(),
            queries_path=config.queries_path,
            bm25_doc=config.bm25_doc,
            bm25_chunk=config.bm25_chunk,
            boost_doc=config.boost_doc,
            boost_chunk=config.boost_chunk,
            budgets=config.budgets,
            quality=config.quality,
            bridge=config.bridge,
            resources=config.resources,
        )

    config.run_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    print(f"Khởi động build tại run_dir: {config.run_dir}")
    id_registry = IdentityRegistry.from_parquet(config.corpus_snapshot)
    quality_policy = QualityPolicy(config.quality)
    reader = CorpusReader(config.chunk_input, id_registry, quality_policy)

    # Khởi tạo SQLite Pointer Store
    db_path = config.run_dir / "metadata.sqlite"
    text_store = SourcePointerTextStore(db_path, repo_root, read_only=False)

    pipeline_registry = TokenPipelineRegistry()
    index_builder = IndexBuilder(config, pipeline_registry)

    # Đăng ký các shard và mở staging writers
    staging_handles = {}
    for gran in ["documents", "chunks"]:
        for lang in ["vi", "en", "zh"]:
            s_dir = index_builder._get_staging_dir(gran, lang)
            staging_handles[(gran, lang)] = open(s_dir / "staging.jsonl", "w", encoding="utf-8")

    registered_shards = {}
    for shard_path in reader.get_shard_files():
        rel_path = str(shard_path.relative_to(repo_root))
        size, mtime, sha256_h = reader.compute_file_stats(shard_path)
        s_id = text_store.register_shard(rel_path, size, mtime, sha256_h)
        registered_shards[shard_path] = s_id

    print("Bắt đầu đọc streaming records và tạo staging data...")
    docs_batch = []
    chunks_batch = []
    total_docs = 0
    total_chunks = 0
    start_time = time.time()

    for shard_path, byte_offset, byte_len, record, rec_sha in reader.stream_records():
        doc_id = record.get("doc_id") or record.get("id")
        if doc_id is None:
            continue
        # Ép kiểu int nếu là string
        if isinstance(doc_id, str) and doc_id.isdigit():
            doc_id = int(doc_id)

        # Kiểm tra Parquet membership
        if not id_registry.is_valid_doc_id(doc_id):
            continue

        # Kiểm tra quality
        eligible, reason = quality_policy.evaluate_doc(record)
        if not eligible:
            continue

        shard_id = registered_shards[shard_path]
        url = record.get("url", "")

        docs_batch.append((doc_id, url, shard_id, byte_offset, byte_len, rec_sha))
        total_docs += 1

        # Xác định ngôn ngữ chính của tài liệu (mặc định vi)
        doc_lang = record.get("language", "vi")
        if doc_lang not in ["vi", "en", "zh"]:
            doc_lang = "vi"

        # Ghi staging cho documents & chunks
        index_builder.prepare_and_stage_record(record, doc_lang, staging_handles)

        for ch in record.get("children", []):
            cid = ch["chunk_id"]
            c_order = ch["chunk_order"]
            c_text = ch.get("chunk_text", "")
            c_sha = hashlib_sha256(c_text.encode("utf-8"))
            s_char = ch.get("start_char", 0)
            e_char = ch.get("end_char", 0)
            p_id = ch.get("parent_id")
            q_state = ch.get("quality_state", "ok")

            chunks_batch.append((cid, doc_id, c_order, p_id, s_char, e_char, c_sha, q_state))
            total_chunks += 1

        if len(docs_batch) >= 1000:
            text_store.insert_batch(docs_batch, chunks_batch)
            docs_batch.clear()
            chunks_batch.clear()
            if total_docs % 5000 == 0:
                print(f"Đã xử lý {total_docs:,} docs, {total_chunks:,} chunks ({time.time() - start_time:.1f}s)...")

    if docs_batch:
        text_store.insert_batch(docs_batch, chunks_batch)

    # Đóng tất cả staging handles
    for fh in staging_handles.values():
        fh.close()

    text_store.close()
    print(f"Giai đoạn Staging hoàn tất: {total_docs:,} docs, {total_chunks:,} chunks trong {time.time() - start_time:.1f}s.")

    # Tiến hành gọi Lucene Indexer cho 6 phân vùng tuần tự
    print("\nBắt đầu xây dựng 6 partition Lucene Indexes...")
    for gran in ["documents", "chunks"]:
        for lang in ["vi", "en", "zh"]:
            index_builder.run_indexer_subprocess(gran, lang)

    print("\nBUILD HOÀN TẤT THÀNH CÔNG!")


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def cmd_search(args: argparse.Namespace) -> None:
    """Thực hiện truy hồi BM25 theo batch và đóng gói file nộp bài chuẩn BTC."""
    config = BM25Config.from_toml(args.config)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    queries_file = Path(args.queries).resolve() if args.queries else config.queries_path
    if not queries_file or not queries_file.is_file():
        raise FileNotFoundError(f"Không tìm thấy file queries: {queries_file}")

    # Đọc queries từ Parquet
    import pyarrow.parquet as pq

    table = pq.read_table(queries_file)
    q_ids = table.column("id").to_pylist()
    q_texts = table.column("query").to_pylist()
    queries = [QueryInput(id=int(i), query=str(t)) for i, t in zip(q_ids, q_texts)]
    print(f"Đã nạp {len(queries)} queries từ {queries_file}")

    # Khởi tạo engine
    db_path = config.run_dir / "metadata.sqlite"
    text_store = SourcePointerTextStore(db_path, repo_root, read_only=True)

    lexicon = MedicalLexicon.from_jsonl(config.bridge.lexicon_path) if config.bridge.lexicon_path else MedicalLexicon()
    bridge = QueryBridge(config.bridge, lexicon)
    q_builder = LuceneQueryBuilder(config.boost_doc)
    backend = LuceneSearchBackend(config, q_builder)
    backend.initialize()

    fusion = CandidateFusion(rrf_k=config.budgets.rrf_k)
    selector = create_selector(config.budgets)

    engine = BM25Engine(config, bridge, backend, fusion, selector, text_store)

    output_dir = Path(args.output).resolve().parent if args.output else config.run_dir / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    writer = SubmissionWriter(output_dir, expected_query_ids=q_ids)

    print("Bắt đầu truy hồi...")
    start_time = time.time()
    submission_items = []

    for idx, q in enumerate(queries, start=1):
        item = engine.search(q)
        submission_items.append(item)
        if idx % 50 == 0 or idx == len(queries):
            elapsed = time.time() - start_time
            print(f"Đã xử lý {idx}/{len(queries)} queries ({idx / elapsed:.2f} qps)...")

    json_p, zip_p = writer.write_submission(submission_items)
    backend.close()
    text_store.close()

    print("\nTRUY HỒI VÀ ĐÓNG GÓI BÀI NỘP HOÀN TẤT:")
    print(f"  JSON file: {json_p}")
    print(f"  ZIP file:  {zip_p}")


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Chấm điểm độc lập bằng BtcEvaluator."""
    print("Thực hiện đánh giá độc lập chuẩn BTC...")
    preds = BtcEvaluator.load_predictions(args.predictions)
    with open(args.qrels, "r", encoding="utf-8") as f:
        qrels = json.load(f)

    report = BtcEvaluator.evaluate(preds, qrels)
    report.print_summary()

    if args.output:
        out_p = Path(args.output).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "total_queries": report.total_queries,
                    "macro_doc_precision": report.macro_doc_precision,
                    "macro_doc_recall": report.macro_doc_recall,
                    "macro_doc_f2": report.macro_doc_f2,
                    "macro_chunk_precision": report.macro_chunk_precision,
                    "macro_chunk_recall": report.macro_chunk_recall,
                    "macro_chunk_f2": report.macro_chunk_f2,
                },
                f,
                indent=2,
            )
        print(f"Đã lưu báo cáo đánh giá tại: {out_p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 Medical Multilingual Retrieval CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Preflight
    p_pre = subparsers.add_parser("preflight", help="Kiểm tra môi trường và tài nguyên")
    p_pre.add_argument("--config", required=True, help="Đường dẫn file TOML cấu hình")

    # Build
    p_bld = subparsers.add_parser("build", help="Xây dựng TextStore và Lucene Indexes")
    p_bld.add_argument("--config", required=True, help="Đường dẫn file TOML cấu hình")
    p_bld.add_argument("--run-dir", default=None, help="Thư mục run")

    # Search
    p_src = subparsers.add_parser("search", help="Tìm kiếm và xuất bài nộp")
    p_src.add_argument("--config", required=True, help="Đường dẫn file TOML cấu hình")
    p_src.add_argument("--queries", default=None, help="Đường dẫn file query.parquet")
    p_src.add_argument("--output", default=None, help="Đường dẫn file output")

    # Evaluate
    p_eva = subparsers.add_parser("evaluate", help="Chấm điểm độc lập chuẩn BTC")
    p_eva.add_argument("--predictions", required=True, help="File .json hoặc .zip dự đoán")
    p_eva.add_argument("--qrels", required=True, help="File ground truth JSON")
    p_eva.add_argument("--output", default=None, help="File xuất báo cáo JSON")

    args = parser.parse_args()
    if args.command == "preflight":
        cmd_preflight(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)


if __name__ == "__main__":
    main()
