"""BM25Engine: Bộ Điều Phối Retrieval Đa Ngữ Y Khoa.

Theo SPEC-bm25-medical-multilingual.md Mục 5 & Mục 11.
Kết nối đồng bộ: QueryBridge -> LuceneSearchBackend -> CandidateFusion -> ResultSelector -> TextStore.
"""

from __future__ import annotations

from typing import Dict, Iterable, Iterator, List, Sequence

from sbtc.Scripts.Retrieval.config import BM25Config
from sbtc.Scripts.Retrieval.fusion import CandidateFusion
from sbtc.Scripts.Retrieval.lucene_backend import LuceneSearchBackend
from sbtc.Scripts.Retrieval.models import QueryInput, SearchHit, SubmissionItem
from sbtc.Scripts.Retrieval.query_bridge import QueryBridge
from sbtc.Scripts.Retrieval.selectors import FixedBudgetSelector
from sbtc.Scripts.Retrieval.text_store import SourcePointerTextStore


class BM25Engine:
    """Engine tìm kiếm Lexical BM25 tích hợp đa ngữ."""

    def __init__(
        self,
        config: BM25Config,
        bridge: QueryBridge,
        backend: LuceneSearchBackend,
        fusion: CandidateFusion,
        selector: FixedBudgetSelector,
        text_store: SourcePointerTextStore,
    ) -> None:
        self.config = config
        self.bridge = bridge
        self.backend = backend
        self.fusion = fusion
        self.selector = selector
        self.text_store = text_store

    def search(self, query: QueryInput) -> SubmissionItem:
        """Thực hiện quy trình truy hồi trọn vẹn cho một query."""
        # 1. Cầu nối truy vấn (QueryBridge)
        analyzed_queries = self.bridge.bridge(query)

        doc_runs: Dict[str, List[SearchHit]] = {}
        chunk_runs: Dict[str, List[SearchHit]] = {}

        k_docs = self.config.budgets.candidate_docs_per_variant
        k_chunks = self.config.budgets.candidate_chunks_per_variant

        # 2. Tìm kiếm song song trên các phân vùng index theo từng biến thể
        for aq in analyzed_queries:
            run_key = f"{aq.language}_{aq.variant_key}"

            # Tìm trên Documents
            d_hits = self.backend.search_partition("documents", aq.language, aq, k=k_docs)
            if d_hits:
                doc_runs[f"doc_{run_key}"] = d_hits

            # Tìm trên Chunks
            c_hits = self.backend.search_partition("chunks", aq.language, aq, k=k_chunks)
            if c_hits:
                chunk_runs[f"chunk_{run_key}"] = c_hits

        # 3. Dung hợp xếp hạng bằng Weighted RRF
        fused_docs, fused_chunks = self.fusion.fuse(doc_runs, chunk_runs)

        # 4. Lựa chọn và hydrate bài nộp qua FixedBudgetSelector & TextStore
        return self.selector.select(query.id, fused_docs, fused_chunks, self.text_store)

    def search_batch(self, queries: Iterable[QueryInput]) -> Iterator[SubmissionItem]:
        """Thực hiện tìm kiếm theo lô cho danh sách truy vấn."""
        for q in queries:
            yield self.search(q)
