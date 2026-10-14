"""BtcEvaluator: Đánh giá Độc lập theo Chuẩn BTC ViBioMIR.

Theo SPEC-bm25-medical-multilingual.md Mục 4 & Mục 14.
Triển khai chuẩn hóa 5 bước BTC, LCS tokens DP O(min(N,M)), many-to-many matching,
tính toán độc lập Precision, Recall, F2 (beta=2) cho cả Document và Chunk.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Set, Tuple


def btc_tokens(text: str) -> List[str]:
    """Quy chuẩn chuẩn hóa và tách token 5 bước của BTC."""
    if not text:
        return []
    # 1. Chuẩn hóa NFKC
    text = unicodedata.normalize("NFKC", text)
    # 2. Giải mã HTML entities
    text = html.unescape(text)
    # 3. Chuyển chữ thường
    text = text.lower()
    # 4. Gộp khoảng trắng liên tiếp và strip
    text = re.sub(r"\s+", " ", text).strip()
    # 5. Tách token theo khoảng trắng
    return text.split()


def lcs_tokens_length(tokens_a: Sequence[str], tokens_b: Sequence[str]) -> int:
    """Tính độ dài Longest Common Subsequence (LCS) giữa 2 chuỗi token.

    Tối ưu bộ nhớ O(min(len(a), len(b))) bằng rolling 1D array.
    """
    n, m = len(tokens_a), len(tokens_b)
    if n == 0 or m == 0:
        return 0

    # Đảm bảo tokens_b là chuỗi ngắn hơn để tối ưu bộ nhớ
    if n < m:
        tokens_a, tokens_b = tokens_b, tokens_a
        n, m = m, n

    prev = [0] * (m + 1)
    curr = [0] * (m + 1)

    for i in range(1, n + 1):
        elem_a = tokens_a[i - 1]
        for j in range(1, m + 1):
            if elem_a == tokens_b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = prev[j] if prev[j] >= curr[j - 1] else curr[j - 1]
        prev, curr = curr, [0] * (m + 1)

    return prev[m]


def compute_f_beta(p: float, r: float, beta: float = 2.0) -> float:
    """Tính điểm F_beta (mặc định beta=2)."""
    if p + r == 0:
        return 0.0
    beta_sq = beta * beta
    return (1 + beta_sq) * (p * r) / (beta_sq * p + r)


@dataclass(frozen=True)
class QueryEvaluationResult:
    """Kết quả chấm điểm chi tiết cho một query duy nhất."""

    query_id: int
    doc_precision: float
    doc_recall: float
    doc_f2: float
    chunk_precision: float
    chunk_recall: float
    chunk_f2: float
    num_pred_docs: int
    num_gt_docs: int
    num_pred_chunks: int
    num_gt_chunks: int


@dataclass(frozen=True)
class MacroEvaluationReport:
    """Báo cáo Macro-Average trên toàn bộ tập truy vấn."""

    total_queries: int
    macro_doc_precision: float
    macro_doc_recall: float
    macro_doc_f2: float
    macro_chunk_precision: float
    macro_chunk_recall: float
    macro_chunk_f2: float
    query_results: Sequence[QueryEvaluationResult]

    def print_summary(self) -> None:
        """In bảng tóm tắt kết quả chấm điểm."""
        print("=" * 60)
        print(f"BÁO CÁO ĐÁNH GIÁ CHUẨN BTC (Số lượng queries: {self.total_queries})")
        print("-" * 60)
        print(f"DOCUMENT LEVEL:")
        print(f"  Macro Precision: {self.macro_doc_precision:.4f}")
        print(f"  Macro Recall:    {self.macro_doc_recall:.4f}")
        print(f"  Macro F2:        {self.macro_doc_f2:.4f}")
        print("-" * 60)
        print(f"CHUNK LEVEL (Overlap tokens >= 40%):")
        print(f"  Macro Precision: {self.macro_chunk_precision:.4f}")
        print(f"  Macro Recall:    {self.macro_chunk_recall:.4f}")
        print(f"  Macro F2:        {self.macro_chunk_f2:.4f}")
        print("=" * 60)


class BtcEvaluator:
    """Công cụ đánh giá độc lập theo quy tắc BTC."""

    @staticmethod
    def load_predictions(pred_path: str | Path) -> List[dict]:
        """Nạp file dự đoán (hỗ trợ file .json trực tiếp hoặc file .zip chứa 1 file .json ở root)."""
        path = Path(pred_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file dự đoán: {path}")

        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                json_files = [f for f in zf.namelist() if f.endswith(".json") and not f.startswith("__MACOSX")]
                if len(json_files) != 1:
                    raise ValueError(f"File ZIP nộp bài phải chứa đúng 1 file .json, tìm thấy: {json_files}")
                with zf.open(json_files[0]) as jf:
                    return json.loads(jf.read().decode("utf-8"))
        else:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    @classmethod
    def evaluate(
        cls,
        predictions: Sequence[Mapping[str, Any]],
        ground_truth: Sequence[Mapping[str, Any]],
    ) -> MacroEvaluationReport:
        """Thực hiện chấm điểm so khớp giữa danh sách dự đoán và ground truth."""
        pred_map = {item["id"]: item for item in predictions}
        gt_map = {item["id"]: item for item in ground_truth}

        all_query_ids = sorted(list(gt_map.keys()))
        query_results: List[QueryEvaluationResult] = []

        total_doc_p = 0.0
        total_doc_r = 0.0
        total_doc_f2 = 0.0

        total_chunk_p = 0.0
        total_chunk_r = 0.0
        total_chunk_f2 = 0.0

        for qid in all_query_ids:
            gt_item = gt_map[qid]
            pred_item = pred_map.get(qid, {"id": qid, "relevant_docs": [], "relevant_chunks": []})

            # --- 1. Đánh giá cấp Document ---
            gt_docs: Set[str] = set(str(d) for d in gt_item.get("relevant_docs", []))
            pred_docs: Set[str] = set(str(d) for d in pred_item.get("relevant_docs", []))

            intersection_docs = pred_docs.intersection(gt_docs)
            num_tp_docs = len(intersection_docs)

            doc_p = num_tp_docs / len(pred_docs) if pred_docs else 0.0
            doc_r = num_tp_docs / len(gt_docs) if gt_docs else 0.0
            doc_f2 = compute_f_beta(doc_p, doc_r, beta=2.0)

            # --- 2. Đánh giá cấp Chunk ---
            gt_chunks_raw = gt_item.get("relevant_chunks", [])
            pred_chunks_raw = pred_item.get("relevant_chunks", [])

            # Tokenize các chunk
            gt_chunks = []
            for g in gt_chunks_raw:
                g_tokens = btc_tokens(g.get("chunk_text", ""))
                if g_tokens:
                    gt_chunks.append({"doc_id": str(g.get("doc_id")), "tokens": g_tokens})

            pred_chunks = []
            for c in pred_chunks_raw:
                c_tokens = btc_tokens(c.get("chunk_text", ""))
                if c_tokens:
                    pred_chunks.append({"doc_id": str(c.get("doc_id")), "tokens": c_tokens})

            num_pred_c = len(pred_chunks)
            num_gt_c = len(gt_chunks)

            # Bảng khớp many-to-many:
            # pred_matches[i] = True nếu pred_chunks[i] khớp ít nhất 1 gt_chunk
            # gt_matched[j] = True nếu gt_chunks[j] được khớp bởi ít nhất 1 pred_chunk
            pred_matches = [False] * num_pred_c
            gt_matched = [False] * num_gt_c

            for i, c in enumerate(pred_chunks):
                for j, g in enumerate(gt_chunks):
                    # Chỉ xét khi cùng doc_id
                    if c["doc_id"] == g["doc_id"]:
                        # Bất đẳng thức integer: 5 * LCS >= 2 * len(g) tương đương LCS/len(g) >= 0.40
                        len_g = len(g["tokens"])
                        lcs_len = lcs_tokens_length(c["tokens"], g["tokens"])
                        if 5 * lcs_len >= 2 * len_g:
                            pred_matches[i] = True
                            gt_matched[j] = True

            chunk_p = sum(pred_matches) / num_pred_c if num_pred_c > 0 else 0.0
            chunk_r = sum(gt_matched) / num_gt_c if num_gt_c > 0 else 0.0
            chunk_f2 = compute_f_beta(chunk_p, chunk_r, beta=2.0)

            query_results.append(
                QueryEvaluationResult(
                    query_id=qid,
                    doc_precision=doc_p,
                    doc_recall=doc_r,
                    doc_f2=doc_f2,
                    chunk_precision=chunk_p,
                    chunk_recall=chunk_r,
                    chunk_f2=chunk_f2,
                    num_pred_docs=len(pred_docs),
                    num_gt_docs=len(gt_docs),
                    num_pred_chunks=num_pred_c,
                    num_gt_chunks=num_gt_c,
                )
            )

            total_doc_p += doc_p
            total_doc_r += doc_r
            total_doc_f2 += doc_f2
            total_chunk_p += chunk_p
            total_chunk_r += chunk_r
            total_chunk_f2 += chunk_f2

        n_queries = len(all_query_ids)
        if n_queries == 0:
            return MacroEvaluationReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [])

        return MacroEvaluationReport(
            total_queries=n_queries,
            macro_doc_precision=total_doc_p / n_queries,
            macro_doc_recall=total_doc_r / n_queries,
            macro_doc_f2=total_doc_f2 / n_queries,
            macro_chunk_precision=total_chunk_p / n_queries,
            macro_chunk_recall=total_chunk_r / n_queries,
            macro_chunk_f2=total_chunk_f2 / n_queries,
            query_results=query_results,
        )
