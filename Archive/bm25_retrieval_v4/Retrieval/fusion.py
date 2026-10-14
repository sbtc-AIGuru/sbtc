"""CandidateFusion: Dung Hợp Xếp Hạng Hai Luồng bằng Weighted RRF.

Theo SPEC-bm25-medical-multilingual.md Mục 9.3 & Mục 9.4.
- Reciprocal Rank Fusion: score(x) = sum_r w_r / (k + rank_r(x)) với rrf_k = 60.
- Tránh so sánh trực tiếp raw BM25 score giữa các ngôn ngữ/phân vùng khác nhau.
- Tự động bổ sung document run từ chunk run (lấy hit chunk cao nhất của mỗi tài liệu).
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Set, Tuple

from sbtc.Scripts.Retrieval.models import SearchHit


class CandidateFusion:
    """Thực hiện dung hợp xếp hạng từ nhiều runs tìm kiếm."""

    def __init__(self, rrf_k: int = 60) -> None:
        self.rrf_k = rrf_k

    def fuse(
        self,
        doc_runs: Mapping[str, Sequence[SearchHit]],
        chunk_runs: Mapping[str, Sequence[SearchHit]],
        run_weights: Mapping[str, float] | None = None,
    ) -> Tuple[List[SearchHit], List[SearchHit]]:
        """Dung hợp cả danh sách doc runs và chunk runs.

        Returns:
            (fused_docs, fused_chunks)
        """
        weights = run_weights or {}

        # 1. Dung hợp Chunks
        chunk_rrf_scores: Dict[str, float] = {}
        chunk_hit_cache: Dict[str, SearchHit] = {}

        for run_name, hits in chunk_runs.items():
            w = weights.get(run_name, 1.0)
            seen_cids: Set[str] = set()
            rank = 1

            for hit in hits:
                if not hit.chunk_id or hit.chunk_id in seen_cids:
                    continue
                seen_cids.add(hit.chunk_id)

                contribution = w / (self.rrf_k + rank)
                chunk_rrf_scores[hit.chunk_id] = chunk_rrf_scores.get(hit.chunk_id, 0.0) + contribution
                if hit.chunk_id not in chunk_hit_cache:
                    chunk_hit_cache[hit.chunk_id] = hit
                rank += 1

        sorted_chunks = sorted(chunk_rrf_scores.items(), key=lambda x: x[1], reverse=True)
        fused_chunks: List[SearchHit] = []
        for r, (cid, score) in enumerate(sorted_chunks, start=1):
            base_hit = chunk_hit_cache[cid]
            fused_chunks.append(
                SearchHit(
                    external_id=cid,
                    doc_id=base_hit.doc_id,
                    chunk_id=cid,
                    rank=r,
                    score=score,
                    run_id="fused_chunk_rrf",
                    granularity="chunk",
                    language="all",
                )
            )

        # 2. Tạo thêm synthetic doc run từ chunk runs (lấy chunk rank cao nhất cho doc)
        synthetic_doc_hits: List[SearchHit] = []
        seen_synthetic_docs: Set[int] = set()
        for hit in fused_chunks:
            if hit.doc_id not in seen_synthetic_docs:
                seen_synthetic_docs.add(hit.doc_id)
                synthetic_doc_hits.append(
                    SearchHit(
                        external_id=str(hit.doc_id),
                        doc_id=hit.doc_id,
                        chunk_id=None,
                        rank=len(synthetic_doc_hits) + 1,
                        score=hit.score,
                        run_id="doc_from_chunk",
                        granularity="document",
                    )
                )

        combined_doc_runs: Dict[str, Sequence[SearchHit]] = dict(doc_runs)
        combined_doc_runs["doc_from_chunks"] = synthetic_doc_hits

        # 3. Dung hợp Documents
        doc_rrf_scores: Dict[int, float] = {}
        doc_hit_cache: Dict[int, SearchHit] = {}

        for run_name, hits in combined_doc_runs.items():
            w = weights.get(run_name, 1.0)
            seen_dids: Set[int] = set()
            rank = 1

            for hit in hits:
                if hit.doc_id in seen_dids:
                    continue
                seen_dids.add(hit.doc_id)

                contribution = w / (self.rrf_k + rank)
                doc_rrf_scores[hit.doc_id] = doc_rrf_scores.get(hit.doc_id, 0.0) + contribution
                if hit.doc_id not in doc_hit_cache:
                    doc_hit_cache[hit.doc_id] = hit
                rank += 1

        sorted_docs = sorted(doc_rrf_scores.items(), key=lambda x: x[1], reverse=True)
        fused_docs: List[SearchHit] = []
        for r, (did, score) in enumerate(sorted_docs, start=1):
            base_hit = doc_hit_cache[did]
            fused_docs.append(
                SearchHit(
                    external_id=str(did),
                    doc_id=did,
                    chunk_id=None,
                    rank=r,
                    score=score,
                    run_id="fused_doc_rrf",
                    granularity="document",
                    language="all",
                )
            )

        return fused_docs, fused_chunks
