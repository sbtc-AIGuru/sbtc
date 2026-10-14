"""ResultSelector: Chọn Lựa Ứng Viên Nộp Bài Tối Ưu Hóa Điểm F2.

Theo SPEC-bm25-medical-multilingual.md Mục 10.1.
FixedBudgetSelector: Tối đa 20 tài liệu, 40 chunks.
Giới hạn tối đa 4 chunks / doc, phạt overlap mềm, hydrate nguyên bản từ TextStore.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Set, Tuple

from sbtc.Scripts.Retrieval.config import BudgetConfig
from sbtc.Scripts.Retrieval.evaluation import btc_tokens
from sbtc.Scripts.Retrieval.models import OriginalChunk, SearchHit, SubmissionChunk, SubmissionItem
from sbtc.Scripts.Retrieval.text_store import SourcePointerTextStore


class FixedBudgetSelector:
    """Lựa chọn kết quả theo ngân sách cố định tối ưu F2."""

    def __init__(self, config: BudgetConfig) -> None:
        self.config = config

    def select(
        self,
        query_id: int,
        candidate_docs: Sequence[SearchHit],
        candidate_chunks: Sequence[SearchHit],
        text_store: SourcePointerTextStore,
    ) -> SubmissionItem:
        """Thực hiện lựa chọn và hydrate bài nộp."""
        # 1. Chọn tài liệu (Relevant Docs)
        selected_docs: List[str] = []
        seen_doc_ids: Set[int] = set()

        for d_hit in candidate_docs:
            if d_hit.doc_id > 0 and d_hit.doc_id not in seen_doc_ids:
                seen_doc_ids.add(d_hit.doc_id)
                selected_docs.append(str(d_hit.doc_id))
                if len(selected_docs) >= self.config.max_selected_docs:
                    break

        # 2. Chọn Chunks sơ bộ (lấy dư candidate để bù trừ overlap penalty)
        candidate_chunk_ids: List[str] = []
        doc_raw_counts: Dict[int, int] = {}

        for c_hit in candidate_chunks:
            if not c_hit.chunk_id:
                continue
            doc_id = c_hit.doc_id
            curr_count = doc_raw_counts.get(doc_id, 0)
            if curr_count < self.config.max_chunks_per_doc * 2:
                candidate_chunk_ids.append(c_hit.chunk_id)
                doc_raw_counts[doc_id] = curr_count + 1
                if len(candidate_chunk_ids) >= self.config.max_selected_chunks * 2:
                    break

        # 3. Hydrate chunk nguyên bản từ SQLite TextStore
        hydrated_chunks_map = text_store.get_many(candidate_chunk_ids)

        # 4. Phạt overlap, dedup nội dung và áp dụng per-doc cap chính thức
        selected_submission_chunks: List[SubmissionChunk] = []
        doc_spans: Dict[int, List[Tuple[int, int]]] = {}
        doc_btc_texts: Dict[int, Set[str]] = {}
        doc_accepted_counts: Dict[int, int] = {}

        for cid in candidate_chunk_ids:
            if cid not in hydrated_chunks_map:
                continue
            orig = hydrated_chunks_map[cid]
            doc_id = orig.doc_id

            # Áp dụng per-doc cap
            if doc_accepted_counts.get(doc_id, 0) >= self.config.max_chunks_per_doc:
                continue

            # Kiểm tra dedup theo normalized BTC text trong cùng doc
            norm_tokens = " ".join(btc_tokens(orig.chunk_text))
            if norm_tokens in doc_btc_texts.setdefault(doc_id, set()):
                continue

            # Kiểm tra overlap interval char spans
            is_heavy_overlap = False
            spans = doc_spans.setdefault(doc_id, [])
            for s_start, s_end in spans:
                overlap_start = max(orig.start_char, s_start)
                overlap_end = min(orig.end_char, s_end)
                if overlap_end > overlap_start:
                    overlap_len = overlap_end - overlap_start
                    chunk_len = orig.end_char - orig.start_char
                    if chunk_len > 0 and (overlap_len / chunk_len) > self.config.overlap_penalty_threshold:
                        is_heavy_overlap = True
                        break

            if is_heavy_overlap:
                continue

            # Đạt điều kiện chọn
            spans.append((orig.start_char, orig.end_char))
            doc_btc_texts[doc_id].add(norm_tokens)
            doc_accepted_counts[doc_id] = doc_accepted_counts.get(doc_id, 0) + 1

            selected_submission_chunks.append(
                SubmissionChunk(
                    doc_id=str(orig.doc_id),
                    chunk_text=orig.chunk_text,
                    chunk_order=orig.chunk_order,
                )
            )

            if len(selected_submission_chunks) >= self.config.max_selected_chunks:
                break

        # 5. Bổ sung các doc_id từ chunks được chọn vào relevant_docs nếu chưa có
        for sc in selected_submission_chunks:
            if sc.doc_id != "0":
                did_int = int(sc.doc_id)
                if did_int not in seen_doc_ids:
                    seen_doc_ids.add(did_int)
                    selected_docs.append(sc.doc_id)
                    if len(selected_docs) >= self.config.max_selected_docs:
                        break

        return SubmissionItem(
            id=query_id,
            relevant_docs=selected_docs,
            relevant_chunks=selected_submission_chunks,
        )


class AdaptiveBudgetSelector:
    """Lựa chọn kết quả theo ngưỡng điểm động (Dynamic Score Threshold) tối ưu F2."""

    def __init__(self, config: BudgetConfig) -> None:
        self.config = config

    def select(
        self,
        query_id: int,
        candidate_docs: Sequence[SearchHit],
        candidate_chunks: Sequence[SearchHit],
        text_store: SourcePointerTextStore,
    ) -> SubmissionItem:
        """Thực hiện lựa chọn động theo tỷ lệ điểm so với top-1."""
        # 1. Chọn tài liệu động
        selected_docs: List[str] = []
        seen_doc_ids: Set[int] = set()

        if candidate_docs:
            top_doc_score = candidate_docs[0].score
            doc_min_score = top_doc_score * self.config.doc_score_ratio

            for d_hit in candidate_docs:
                if d_hit.doc_id <= 0:
                    continue
                # Nếu điểm tụt quá ngưỡng và đã đạt số lượng tối thiểu, dừng lấy
                if d_hit.score < doc_min_score and len(selected_docs) >= self.config.min_selected_docs:
                    break
                if d_hit.doc_id not in seen_doc_ids:
                    seen_doc_ids.add(d_hit.doc_id)
                    selected_docs.append(str(d_hit.doc_id))
                    if len(selected_docs) >= self.config.max_selected_docs:
                        break

        # 2. Chọn Chunks sơ bộ theo ngưỡng động
        candidate_chunk_ids: List[str] = []
        doc_raw_counts: Dict[int, int] = {}

        if candidate_chunks:
            top_chunk_score = candidate_chunks[0].score
            chunk_min_score = top_chunk_score * self.config.chunk_score_ratio

            for c_hit in candidate_chunks:
                if not c_hit.chunk_id:
                    continue
                # Nếu điểm tụt quá ngưỡng và đã gom đủ chunk tối thiểu
                if c_hit.score < chunk_min_score and len(candidate_chunk_ids) >= self.config.min_selected_chunks:
                    break
                doc_id = c_hit.doc_id
                curr_count = doc_raw_counts.get(doc_id, 0)
                if curr_count < self.config.max_chunks_per_doc * 2:
                    candidate_chunk_ids.append(c_hit.chunk_id)
                    doc_raw_counts[doc_id] = curr_count + 1
                    if len(candidate_chunk_ids) >= self.config.max_selected_chunks * 2:
                        break

        # 3. Hydrate chunk nguyên bản từ SQLite TextStore
        hydrated_chunks_map = text_store.get_many(candidate_chunk_ids)

        # 4. Phạt overlap, dedup nội dung và áp dụng per-doc cap chính thức
        selected_submission_chunks: List[SubmissionChunk] = []
        doc_spans: Dict[int, List[Tuple[int, int]]] = {}
        doc_btc_texts: Dict[int, Set[str]] = {}
        doc_accepted_counts: Dict[int, int] = {}

        for cid in candidate_chunk_ids:
            if cid not in hydrated_chunks_map:
                continue
            orig = hydrated_chunks_map[cid]
            doc_id = orig.doc_id

            # Áp dụng per-doc cap
            if doc_accepted_counts.get(doc_id, 0) >= self.config.max_chunks_per_doc:
                continue

            # Kiểm tra dedup theo normalized BTC text trong cùng doc
            norm_tokens = " ".join(btc_tokens(orig.chunk_text))
            if norm_tokens in doc_btc_texts.setdefault(doc_id, set()):
                continue

            # Kiểm tra overlap interval char spans
            is_heavy_overlap = False
            spans = doc_spans.setdefault(doc_id, [])
            for s_start, s_end in spans:
                overlap_start = max(orig.start_char, s_start)
                overlap_end = min(orig.end_char, s_end)
                if overlap_end > overlap_start:
                    overlap_len = overlap_end - overlap_start
                    chunk_len = orig.end_char - orig.start_char
                    if chunk_len > 0 and (overlap_len / chunk_len) > self.config.overlap_penalty_threshold:
                        is_heavy_overlap = True
                        break

            if is_heavy_overlap:
                continue

            # Đạt điều kiện chọn
            spans.append((orig.start_char, orig.end_char))
            doc_btc_texts[doc_id].add(norm_tokens)
            doc_accepted_counts[doc_id] = doc_accepted_counts.get(doc_id, 0) + 1

            selected_submission_chunks.append(
                SubmissionChunk(
                    doc_id=str(orig.doc_id),
                    chunk_text=orig.chunk_text,
                    chunk_order=orig.chunk_order,
                )
            )

            if len(selected_submission_chunks) >= self.config.max_selected_chunks:
                break

        # 5. Bổ sung các doc_id từ chunks được chọn vào relevant_docs nếu chưa có
        for sc in selected_submission_chunks:
            if sc.doc_id != "0":
                did_int = int(sc.doc_id)
                if did_int not in seen_doc_ids:
                    seen_doc_ids.add(did_int)
                    selected_docs.append(sc.doc_id)
                    if len(selected_docs) >= self.config.max_selected_docs:
                        break

        return SubmissionItem(
            id=query_id,
            relevant_docs=selected_docs,
            relevant_chunks=selected_submission_chunks,
        )


def create_selector(config: BudgetConfig):
    """Khởi tạo selector phù hợp dựa trên cấu hình."""
    if config.adaptive_selector:
        return AdaptiveBudgetSelector(config)
    return FixedBudgetSelector(config)

