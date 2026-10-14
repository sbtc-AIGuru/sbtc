"""QueryBridge: Cầu Nối Truy Vấn Xuyên Ngôn Ngữ & Mở Rộng Thuật Ngữ Y Khoa.

Theo SPEC-bm25-medical-multilingual.md Mục 7.
- Hai chế độ: lexical-control và multilingual.
- Giới hạn mở rộng tối đa 128 clauses / query.
- Bảo vệ ký tự viết tắt, số, biomarker, không làm mất dấu phủ định.
- Hỗ trợ cache bản dịch deterministic trên đĩa.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from sbtc.Scripts.Retrieval.config import QueryBridgeConfig
from sbtc.Scripts.Retrieval.lexicon import MedicalLexicon
from sbtc.Scripts.Retrieval.models import AnalyzedQuery, QueryInput


class QueryBridge:
    """Điều phối phân tích, mở rộng thuật ngữ và chuẩn bị truy vấn đa ngữ."""

    def __init__(
        self,
        config: QueryBridgeConfig,
        lexicon: MedicalLexicon | None = None,
        translation_cache_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.lexicon = lexicon or MedicalLexicon()
        self.translation_cache_dir = translation_cache_dir
        if self.translation_cache_dir:
            self.translation_cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_query_hash(text: str) -> str:
        """Tính SHA256 query hash."""
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()

    def _get_cached_translation(self, query_hash: str, target_lang: str) -> str | None:
        """Đọc bản dịch đã lưu trong cache đĩa."""
        if not self.translation_cache_dir:
            return None
        cache_file = self.translation_cache_dir / f"{query_hash}_{target_lang}.json"
        if cache_file.is_file():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("translated_text")
            except Exception:
                return None
        return None

    def bridge(self, query: QueryInput) -> Sequence[AnalyzedQuery]:
        """Tạo danh sách các truy vấn đã phân tích cho các ngôn ngữ và biến thể."""
        q_text = query.query.strip()
        q_hash = self.compute_query_hash(q_text)
        results: List[AnalyzedQuery] = []

        # 1. Truy vấn gốc tiếng Việt (Base VI)
        results.append(
            AnalyzedQuery(
                query_id=query.id,
                query_hash=q_hash,
                language="vi",
                variant_key="original",
                tokens_map={
                    "contents": q_text,
                    "surface": q_text,
                    "medical_exact": q_text,
                },
            )
        )

        # Nếu ở chế độ lexical-control, dừng ở đây hoặc chỉ ánh xạ symbol chung
        if self.config.mode == "lexical-control":
            # Tạo thêm variant tìm kiếm chéo trên EN và ZH bằng chuỗi gốc
            results.append(
                AnalyzedQuery(
                    query_id=query.id,
                    query_hash=q_hash,
                    language="en",
                    variant_key="original_cross",
                    tokens_map={"contents": q_text, "surface": q_text},
                )
            )
            results.append(
                AnalyzedQuery(
                    query_id=query.id,
                    query_hash=q_hash,
                    language="zh",
                    variant_key="original_cross",
                    tokens_map={"contents": q_text, "surface": q_text},
                )
            )
            return results

        # 2. Chế độ multilingual: Mở rộng thực thể qua MedicalLexicon
        aliases = self.lexicon.get_aliases_for_query(q_text, max_aliases=5)
        if aliases:
            expanded_text = q_text + " " + " ".join(aliases)
            results.append(
                AnalyzedQuery(
                    query_id=query.id,
                    query_hash=q_hash,
                    language="vi",
                    variant_key="alias_expanded",
                    tokens_map={
                        "contents": expanded_text,
                        "surface": expanded_text,
                        "medical_exact": " ".join(aliases),
                    },
                )
            )

        # 3. Tìm bản dịch EN/ZH từ Cache
        for target_lang in ["en", "zh"]:
            trans_text = self._get_cached_translation(q_hash, target_lang)
            if trans_text:
                results.append(
                    AnalyzedQuery(
                        query_id=query.id,
                        query_hash=q_hash,
                        language=target_lang,
                        variant_key=f"translated_{target_lang}",
                        tokens_map={
                            "contents": trans_text,
                            "surface": trans_text,
                        },
                    )
                )
            else:
                # Fallback: dùng các alias thuộc ngôn ngữ đích nếu có trong lexicon
                concepts = self.lexicon.find_concepts(q_text)
                lang_terms = []
                for _, entry in concepts:
                    target_label = entry.labels.get(target_lang)
                    if target_label:
                        lang_terms.append(target_label)

                if lang_terms:
                    fallback_text = " ".join(lang_terms)
                    results.append(
                        AnalyzedQuery(
                            query_id=query.id,
                            query_hash=q_hash,
                            language=target_lang,
                            variant_key=f"lexicon_fallback_{target_lang}",
                            tokens_map={"contents": fallback_text, "surface": fallback_text},
                        )
                    )

        return results
