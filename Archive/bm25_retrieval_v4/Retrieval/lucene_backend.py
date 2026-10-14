"""LuceneSearchBackend: Wrapper Quản Lý 6 Searcher Partitions & Tìm Kiếm Đa Ngữ.

Theo SPEC-bm25-medical-multilingual.md Mục 9.1 và Mục 9.2.
- Mở sẵn 6 LuceneSearcher trong bộ nhớ, dùng JWhiteSpaceAnalyzer.
- Cấu hình k1, b riêng biệt cho document và chunk.
- Tìm kiếm bằng custom JQuery objects từ LuceneQueryBuilder.
- Trích xuất SearchHit chuẩn hóa, thread-safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from sbtc.Scripts.Retrieval.config import BM25Config
from sbtc.Scripts.Retrieval.models import AnalyzedQuery, SearchHit
from sbtc.Scripts.Retrieval.query_builder import LuceneQueryBuilder


class LuceneSearchBackend:
    """Quản lý các searcher cho 6 phân vùng index."""

    def __init__(self, config: BM25Config, query_builder: LuceneQueryBuilder) -> None:
        self.config = config
        self.query_builder = query_builder
        self.indexes_dir = self.config.run_dir / "indexes"
        self._searchers: Dict[Tuple[str, str], Any] = {}
        self._is_initialized = False

    def initialize(self) -> None:
        """Khởi tạo và cấu hình các LuceneSearcher."""
        if self._is_initialized:
            return

        # Bảo vệ offline: Không tải metadata prebuilt index từ GitHub qua internet
        from collections import defaultdict
        try:
            import pyserini.prebuilt_index_info as pinfo
            pinfo._LazyLucenePrebuiltInvertedIndexJson._load = lambda self: defaultdict(lambda: {"urls": [], "md5": ""})
            pinfo._LazyLucenePrebuiltInvertedIndexJson.__getitem__ = lambda self, key: {"urls": [], "md5": ""}
        except Exception:
            pass

        from pyserini.analysis import JWhiteSpaceAnalyzer
        from pyserini.search.lucene._searcher import LuceneSearcher

        analyzer = JWhiteSpaceAnalyzer()

        for granularity in ["documents", "chunks"]:
            for lang in ["vi", "en", "zh"]:
                idx_path = self.indexes_dir / granularity / lang
                if not idx_path.exists():
                    continue

                searcher = LuceneSearcher(str(idx_path))
                searcher.set_analyzer(analyzer)

                # Cấu hình BM25 k1, b
                if granularity == "documents":
                    searcher.set_bm25(self.config.bm25_doc.k1, self.config.bm25_doc.b)
                else:
                    searcher.set_bm25(self.config.bm25_chunk.k1, self.config.bm25_chunk.b)

                self._searchers[(granularity, lang)] = searcher

        self._is_initialized = True

    def search_partition(
        self,
        granularity: str,
        language: str,
        analyzed_query: AnalyzedQuery,
        k: int,
    ) -> List[SearchHit]:
        """Thực hiện tìm kiếm trên một phân vùng cụ thể."""
        key = (granularity, language)
        if key not in self._searchers:
            return []

        searcher = self._searchers[key]
        j_query = self.query_builder.build_query(analyzed_query)

        # Gọi search API của Pyserini
        hits = searcher.search(j_query, k=k)
        results: List[SearchHit] = []

        run_id = f"{granularity}_{language}_{analyzed_query.variant_key}"

        for rank, hit in enumerate(hits, start=1):
            ext_id = str(hit.docid)
            if granularity == "documents":
                # External id của document là doc_id
                try:
                    doc_id = int(ext_id)
                except ValueError:
                    continue
                results.append(
                    SearchHit(
                        external_id=ext_id,
                        doc_id=doc_id,
                        chunk_id=None,
                        rank=rank,
                        score=float(hit.score),
                        run_id=run_id,
                        granularity=granularity,
                        language=language,
                    )
                )
            else:
                # External id của chunk là chunk_id (vd: 7156587:c:0:0:1354:format-v3 hoặc 7156587_0)
                doc_id = 0
                if ":" in ext_id:
                    prefix = ext_id.split(":")[0]
                    if prefix.isdigit():
                        doc_id = int(prefix)
                elif "_" in ext_id:
                    prefix = ext_id.split("_")[0]
                    if prefix.isdigit():
                        doc_id = int(prefix)

                results.append(
                    SearchHit(
                        external_id=ext_id,
                        doc_id=doc_id,
                        chunk_id=ext_id,
                        rank=rank,
                        score=float(hit.score),
                        run_id=run_id,
                        granularity=granularity,
                        language=language,
                    )
                )

        return results

    def close(self) -> None:
        """Đóng tất cả các searcher."""
        for s in self._searchers.values():
            try:
                s.close()
            except Exception:
                pass
        self._searchers.clear()
        self._is_initialized = False
