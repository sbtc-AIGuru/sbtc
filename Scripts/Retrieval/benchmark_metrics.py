"""Benchmark IR Metrics: MRR, MAP, Recall@K, Precision@K cho Document và Chunk.

Theo chuẩn đánh giá Information Retrieval và chuẩn hóa đối soát của BTC ViBioMIR.
Đo lường chi tiết chất lượng xếp hạng (Ranked Candidates) từ 1 đến K.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

# Đảm bảo JAVA_HOME được nhận diện chính xác
if "JAVA_HOME" not in os.environ:
    conda_jvm = Path(sys.executable).resolve().parent.parent / "lib" / "jvm"
    if conda_jvm.is_dir():
        os.environ["JAVA_HOME"] = str(conda_jvm)

# Bảo vệ offline cho pyserini không phụ thuộc vào internet
from collections import defaultdict
try:
    import pyserini.prebuilt_index_info as pinfo
    pinfo._LazyLucenePrebuiltInvertedIndexJson._load = lambda self: defaultdict(lambda: {"urls": [], "md5": ""})
    pinfo._LazyLucenePrebuiltInvertedIndexJson.__getitem__ = lambda self, key: {"urls": [], "md5": ""}
except Exception:
    pass

import pyarrow.parquet as pq

from sbtc.Scripts.Retrieval.config import BM25Config
from sbtc.Scripts.Retrieval.evaluation import btc_tokens, lcs_tokens_length
from sbtc.Scripts.Retrieval.fusion import CandidateFusion
from sbtc.Scripts.Retrieval.lexicon import MedicalLexicon
from sbtc.Scripts.Retrieval.lucene_backend import LuceneSearchBackend
from sbtc.Scripts.Retrieval.models import QueryInput, SearchHit
from sbtc.Scripts.Retrieval.query_bridge import QueryBridge
from sbtc.Scripts.Retrieval.query_builder import LuceneQueryBuilder
from sbtc.Scripts.Retrieval.text_store import SourcePointerTextStore


def compute_doc_metrics_for_query(
    ranked_doc_ids: Sequence[int],
    gt_doc_ids: Set[int],
    k_list: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, float]:
    """Tính Precision@K, Recall@K, MRR, MAP cho cấp Document."""
    metrics: Dict[str, float] = {}
    if not gt_doc_ids:
        for k in k_list:
            metrics[f"P@{k}"] = 0.0
            metrics[f"R@{k}"] = 0.0
        metrics["MRR"] = 0.0
        metrics["MAP"] = 0.0
        return metrics

    # 1. P@K và R@K
    hits = [1 if did in gt_doc_ids else 0 for did in ranked_doc_ids]

    for k in k_list:
        sub_hits = hits[:k]
        num_correct = sum(sub_hits)
        metrics[f"P@{k}"] = num_correct / k
        metrics[f"R@{k}"] = num_correct / len(gt_doc_ids)

    # 2. Reciprocal Rank (RR)
    rr = 0.0
    for idx, h in enumerate(hits, start=1):
        if h == 1:
            rr = 1.0 / idx
            break
    metrics["MRR"] = rr

    # 3. Average Precision (AP)
    ap_sum = 0.0
    num_hits = 0
    for idx, h in enumerate(hits, start=1):
        if h == 1:
            num_hits += 1
            ap_sum += num_hits / idx
    metrics["MAP"] = ap_sum / len(gt_doc_ids) if len(gt_doc_ids) > 0 else 0.0

    return metrics


def compute_chunk_metrics_for_query(
    ranked_chunks: Sequence[Tuple[int, str]],  # List of (doc_id, chunk_text)
    gt_chunks: Sequence[Dict[str, Any]],  # List of dict with doc_id, tokens
    k_list: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, float]:
    """Tính Precision@K, Recall@K, MRR, MAP cho cấp Chunk theo chuẩn BTC."""
    metrics: Dict[str, float] = {}
    if not gt_chunks:
        for k in k_list:
            metrics[f"P@{k}"] = 0.0
            metrics[f"R@{k}"] = 0.0
        metrics["MRR"] = 0.0
        metrics["MAP"] = 0.0
        return metrics

    num_gt = len(gt_chunks)
    # Xác định hit cho từng chunk tại từng rank
    # pred_is_hit[i] = True nếu ranked_chunks[i] khớp ít nhất 1 gt_chunk
    # và ghi nhận gt_chunk nào được khớp
    pred_hits = []
    matched_gt_indices_per_rank: List[Set[int]] = []

    for c_doc_id, c_text in ranked_chunks:
        c_tokens = btc_tokens(c_text)
        is_hit = False
        matched_gts = set()

        if c_tokens:
            for g_idx, g in enumerate(gt_chunks):
                if c_doc_id == g["doc_id"]:
                    len_g = len(g["tokens"])
                    lcs = lcs_tokens_length(c_tokens, g["tokens"])
                    # Chuẩn BTC: 5 * LCS >= 2 * len(g)
                    if 5 * lcs >= 2 * len_g:
                        is_hit = True
                        matched_gts.add(g_idx)

        pred_hits.append(1 if is_hit else 0)
        matched_gt_indices_per_rank.append(matched_gts)

    # 1. P@K và R@K
    for k in k_list:
        sub_pred_hits = pred_hits[:k]
        sub_gt_matched = set()
        for s in matched_gt_indices_per_rank[:k]:
            sub_gt_matched.update(s)

        metrics[f"P@{k}"] = sum(sub_pred_hits) / k if k > 0 else 0.0
        metrics[f"R@{k}"] = len(sub_gt_matched) / num_gt if num_gt > 0 else 0.0

    # 2. Reciprocal Rank (MRR)
    rr = 0.0
    for idx, h in enumerate(pred_hits, start=1):
        if h == 1:
            rr = 1.0 / idx
            break
    metrics["MRR"] = rr

    # 3. Average Precision (MAP)
    ap_sum = 0.0
    covered_gts = set()
    num_hits = 0
    for idx, (h, mgts) in enumerate(zip(pred_hits, matched_gt_indices_per_rank), start=1):
        if h == 1:
            num_hits += 1
            ap_sum += num_hits / idx
    metrics["MAP"] = ap_sum / num_gt if num_gt > 0 else 0.0

    return metrics


def run_benchmark(
    config_path: str = "sbtc/Scripts/Retrieval/configs/bm25-test.toml",
    queries_path: str = "for_valid/queries.parquet",
    gt_path: str = "for_valid/ground_truth.json",
    top_k: int = 50,
) -> None:
    """Thực thi đo đạc toàn diện các chỉ số IR."""
    print("=" * 70)
    print("CHƯƠNG TRÌNH ĐO ĐẠC CHUYÊN SÂU CHỈ SỐ IR (MRR, MAP, P@K, R@K)")
    print("=" * 70)

    config = BM25Config.from_toml(config_path)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    # 1. Nạp queries và ground truth
    table = pq.read_table(queries_path)
    q_ids = table.column("id").to_pylist()
    q_texts = table.column("query").to_pylist()
    queries = [QueryInput(id=int(i), query=str(t)) for i, t in zip(q_ids, q_texts)]

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    gt_map = {item["id"]: item for item in gt_data}

    # 2. Khởi tạo components
    db_path = config.run_dir / "metadata.sqlite"
    text_store = SourcePointerTextStore(db_path, repo_root, read_only=True)
    lexicon = MedicalLexicon.from_jsonl(config.bridge.lexicon_path) if config.bridge.lexicon_path else MedicalLexicon()
    bridge = QueryBridge(config.bridge, lexicon)
    q_builder = LuceneQueryBuilder(config.boost_doc)
    backend = LuceneSearchBackend(config, q_builder)
    backend.initialize()
    fusion = CandidateFusion(rrf_k=config.budgets.rrf_k)

    print(f"Đã nạp {len(queries)} queries từ {queries_path}")
    print(f"Đo đạc trên Top-{top_k} ranked candidates...")

    doc_macro_metrics: Dict[str, float] = {}
    chunk_macro_metrics: Dict[str, float] = {}
    k_list = [1, 3, 5, 10]

    for k in k_list:
        doc_macro_metrics[f"P@{k}"] = 0.0
        doc_macro_metrics[f"R@{k}"] = 0.0
        chunk_macro_metrics[f"P@{k}"] = 0.0
        chunk_macro_metrics[f"R@{k}"] = 0.0
    doc_macro_metrics["MRR"] = 0.0
    doc_macro_metrics["MAP"] = 0.0
    chunk_macro_metrics["MRR"] = 0.0
    chunk_macro_metrics["MAP"] = 0.0

    start_time = time.time()

    for q in queries:
        gt_item = gt_map.get(q.id)
        if not gt_item:
            continue

        gt_docs = set(int(d) for d in gt_item.get("relevant_docs", []))
        gt_chunks = []
        for g in gt_item.get("relevant_chunks", []):
            toks = btc_tokens(g.get("chunk_text", ""))
            if toks:
                gt_chunks.append({"doc_id": int(g.get("doc_id")), "tokens": toks})

        # Thực hiện tìm kiếm candidate
        analyzed_queries = bridge.bridge(q)
        doc_runs: Dict[str, List[SearchHit]] = {}
        chunk_runs: Dict[str, List[SearchHit]] = {}

        for aq in analyzed_queries:
            run_key = f"{aq.language}_{aq.variant_key}"
            d_hits = backend.search_partition("documents", aq.language, aq, k=top_k)
            if d_hits:
                doc_runs[f"doc_{run_key}"] = d_hits
            c_hits = backend.search_partition("chunks", aq.language, aq, k=top_k * 2)
            if c_hits:
                chunk_runs[f"chunk_{run_key}"] = c_hits

        fused_docs, fused_chunks = fusion.fuse(doc_runs, chunk_runs)

        # 1. Đo lường Document
        ranked_doc_ids = [h.doc_id for h in fused_docs if h.doc_id > 0][:top_k]
        q_doc_m = compute_doc_metrics_for_query(ranked_doc_ids, gt_docs, k_list)
        for m_k, val in q_doc_m.items():
            doc_macro_metrics[m_k] += val

        # 2. Đo lường Chunk
        # Hydrate text cho top_k chunks
        ranked_cids = [h.chunk_id for h in fused_chunks if h.chunk_id][:top_k]
        hydrated_map = text_store.get_many(ranked_cids)
        ranked_chunk_payloads = []
        for cid in ranked_cids:
            if cid in hydrated_map:
                c_obj = hydrated_map[cid]
                ranked_chunk_payloads.append((c_obj.doc_id, c_obj.chunk_text))

        q_chunk_m = compute_chunk_metrics_for_query(ranked_chunk_payloads, gt_chunks, k_list)
        for m_k, val in q_chunk_m.items():
            chunk_macro_metrics[m_k] += val

    num_q = len(queries)
    for m_k in doc_macro_metrics:
        doc_macro_metrics[m_k] /= num_q
    for m_k in chunk_macro_metrics:
        chunk_macro_metrics[m_k] /= num_q

    backend.close()
    text_store.close()

    elapsed = time.time() - start_time
    print(f"\nThời gian thực thi: {elapsed:.2f}s ({num_q / elapsed:.2f} QPS)")
    print("\n" + "=" * 70)
    print("BẢNG TỔNG HỢP CHỈ SỐ XẾP HẠNG TÀI LIỆU (DOCUMENT LEVEL)")
    print("-" * 70)
    print(f"  MRR (Mean Reciprocal Rank): {doc_macro_metrics['MRR']:.4f}")
    print(f"  MAP (Mean Average Precision): {doc_macro_metrics['MAP']:.4f}")
    print("-" * 70)
    for k in k_list:
        p_val = doc_macro_metrics[f"P@{k}"]
        r_val = doc_macro_metrics[f"R@{k}"]
        print(f"  Top-{k:<2}:  Precision@{k:<2} = {p_val:.4f} ({p_val*100:5.2f}%)  |  Recall@{k:<2} = {r_val:.4f} ({r_val*100:5.2f}%)")

    print("\n" + "=" * 70)
    print("BẢNG TỔNG HỢP CHỈ SỐ XẾP HẠNG ĐOẠN VĂN (CHUNK LEVEL - LCS >= 40%)")
    print("-" * 70)
    print(f"  MRR (Mean Reciprocal Rank): {chunk_macro_metrics['MRR']:.4f}")
    print(f"  MAP (Mean Average Precision): {chunk_macro_metrics['MAP']:.4f}")
    print("-" * 70)
    for k in k_list:
        p_val = chunk_macro_metrics[f"P@{k}"]
        r_val = chunk_macro_metrics[f"R@{k}"]
        print(f"  Top-{k:<2}:  Precision@{k:<2} = {p_val:.4f} ({p_val*100:5.2f}%)  |  Recall@{k:<2} = {r_val:.4f} ({r_val*100:5.2f}%)")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
