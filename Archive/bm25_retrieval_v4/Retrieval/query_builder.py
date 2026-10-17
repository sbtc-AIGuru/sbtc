"""Lucene QueryBuilder: Dựng Cấu Trúc Query Java An Toàn Tuyệt Đối.

Theo SPEC-bm25-medical-multilingual.md Mục 9.2.
Không dùng Lucene QueryParser parse chuỗi thô để tránh lỗi cú pháp với '+', '-', ':', '()'.
Dựng trực tiếp TermQuery, BoostQuery, BooleanQuery và DisjunctionMaxQuery qua pyjnius.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sbtc.Scripts.Retrieval.config import FieldBoostConfig
from sbtc.Scripts.Retrieval.models import AnalyzedQuery


class LuceneQueryBuilder:
    """Xây dựng đối tượng org.apache.lucene.search.Query an toàn từ AnalyzedQuery."""

    def __init__(self, boost_config: FieldBoostConfig) -> None:
        self.boosts = boost_config
        self._classes_loaded = False

    def _ensure_java_classes(self) -> None:
        """Nạp các class Lucene cần thiết."""
        if not self._classes_loaded:
            import jnius
            from jnius import autoclass

            self.Term = autoclass("org.apache.lucene.index.Term")
            self.TermQuery = autoclass("org.apache.lucene.search.TermQuery")
            self.BoostQuery = autoclass("org.apache.lucene.search.BoostQuery")
            self.BooleanQueryBuilder = autoclass("org.apache.lucene.search.BooleanQuery$Builder")
            self.BooleanClauseOccur = autoclass("org.apache.lucene.search.BooleanClause$Occur")
            self.DisjunctionMaxQuery = autoclass("org.apache.lucene.search.DisjunctionMaxQuery")
            self.ArrayList = autoclass("java.util.ArrayList")
            self._classes_loaded = True

    def build_query(self, analyzed: AnalyzedQuery) -> Any:
        """Dựng Lucene Query Java object từ AnalyzedQuery.

        Tạo BooleanQuery cấp cao nhất với các BooleanClause Occur.SHOULD.
        """
        self._ensure_java_classes()

        root_builder = self.BooleanQueryBuilder()
        tokens_map = analyzed.tokens_map

        field_weights = {
            "contents": self.boosts.contents,
            "title": self.boosts.title,
            "section": self.boosts.section,
            "surface": self.boosts.surface,
            "medical_exact": self.boosts.medical_exact,
            "concepts": self.boosts.concepts,
        }

        has_any_clause = False

        for field_name, boost_val in field_weights.items():
            if field_name not in tokens_map or boost_val <= 0.0:
                continue

            text_tokens = tokens_map[field_name].strip()
            if not text_tokens:
                continue

            tokens = text_tokens.split()
            for token in tokens:
                token_clean = token.strip()
                if not token_clean:
                    continue

                # Tạo Term và TermQuery
                term_obj = self.Term(field_name, token_clean)
                t_query = self.TermQuery(term_obj)

                # Bọc BoostQuery
                if abs(boost_val - 1.0) > 1e-4:
                    b_query = self.BoostQuery(t_query, float(boost_val))
                else:
                    b_query = t_query

                # Add clause Occur.SHOULD
                root_builder.add(b_query, self.BooleanClauseOccur.SHOULD)
                has_any_clause = True

        if not has_any_clause:
            # Fallback nếu query rỗng: tạo match none query hoặc match all rỗng
            MatchNoDocsQuery = autoclass("org.apache.lucene.search.MatchNoDocsQuery")
            return MatchNoDocsQuery()

        return root_builder.build()
