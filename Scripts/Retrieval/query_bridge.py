"""QueryBridge: Cầu Nối Truy Vấn Xuyên Ngôn Ngữ & Chắt Lọc Thuật Ngữ Y Khoa.

Theo đặc tả kỹ thuật:
- Chắt lọc câu hỏi (Query Distillation): Loại bỏ hư từ hội thoại rác tiếng Việt
  (bệnh nhân, tuổi, cho hỏi, có sao không, như thế nào, thì, nên, làm, gì, để...).
- Bảo toàn thực thể y khoa cốt lõi (50k base_vi, thuốc, liều lượng, biomarker).
- Đồng bộ hóa mã Concept đa ngữ (MC0001 - MC0378) sang các biến thể EN và ZH.
- Hai chế độ: lexical-control và multilingual.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set

from sbtc.Scripts.Retrieval.analyzers import TokenPipelineRegistry
from sbtc.Scripts.Retrieval.config import QueryBridgeConfig
from sbtc.Scripts.Retrieval.lexicon import MedicalLexicon
from sbtc.Scripts.Retrieval.models import AnalyzedQuery, QueryInput


# Danh sách hư từ y khoa hội thoại và từ dừng câu hỏi rác tiếng Việt
MEDICAL_CONVERSATIONAL_STOPWORDS = {
    # Đại từ / từ xưng hô / người
    "bệnh_nhân", "benh_nhan", "người_bệnh", "nguoi_benh",
    "nam", "nữ", "nu", "tuổi", "tuoi", "tôi", "toi", "em", "mình", "minh",
    "bác_sĩ", "bac_si", "anh", "chị", "chi", "người", "nguoi",
    # Từ nghi vấn / câu hỏi hội thoại
    "cho_hỏi", "cho_hoi", "cho_em_hỏi", "hỏi", "hoi", "có_sao_không", "sao_không",
    "như_thế_nào", "như_nào", "thế_nào", "the_nao", "làm_sao", "lam_sao",
    "có_nên", "co_nen", "làm_gì", "lam_gi", "bao_nhiêu", "bao_lâu", "được_không", "duoc_khong",
    "phải_làm_sao", "cách_chữa", "điều_trị_như_thế_nào", "uống_được_không",
    "dùng_được_không", "an_toàn_không", "nguy_hiểm_không",
    # Hư từ nối / trợ từ
    "thì", "thi", "là", "la", "mà", "ma", "ở", "o", "với", "voi", "của", "cua",
    "để", "de", "những", "nhung", "các", "cac", "một_số", "mot_so", "một", "mot",
    "do", "vì", "vi", "nên", "nen", "khi", "bị", "bi", "được", "duoc", "có", "co",
    "và", "va", "hay", "hoặc", "hoac", "nếu", "neu", "gì", "gi",
}


def distill_medical_query(tokens_str: str) -> str:
    """Loại bỏ hư từ hội thoại, dấu câu và số tuổi, giữ lại thực thể y khoa cốt lõi."""
    if not tokens_str:
        return ""
    # Xóa dấu câu thừa ở ranh giới (?, !, ., :, ;)
    cleaned_tokens_str = re.sub(r"[?!.,;:]+", " ", tokens_str)
    tokens = cleaned_tokens_str.split()
    distilled = []
    for t in tokens:
        t_clean = t.strip()
        t_lower = t_clean.lower()
        if not t_clean or t_lower in MEDICAL_CONVERSATIONAL_STOPWORDS:
            continue
        # Bỏ qua các số nguyên đơn lẻ <= 120 (thường là tuổi bệnh nhân)
        if t_clean.isdigit() and int(t_clean) <= 120:
            continue
        distilled.append(t_clean)

    if distilled:
        return " ".join(distilled)
    return tokens_str


class QueryBridge:
    """Điều phối phân tích, mở rộng thuật ngữ và chuẩn bị truy vấn đa ngữ."""

    def __init__(
        self,
        config: QueryBridgeConfig,
        lexicon: MedicalLexicon | None = None,
        translation_cache_dir: Path | None = None,
        pipelines: TokenPipelineRegistry | None = None,
    ) -> None:
        self.config = config
        self.lexicon = lexicon or MedicalLexicon()
        self.translation_cache_dir = translation_cache_dir
        if self.translation_cache_dir:
            self.translation_cache_dir.mkdir(parents=True, exist_ok=True)
        self.pipelines = pipelines or TokenPipelineRegistry()

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

        # 1. Phân tích câu hỏi tiếng Việt qua VietnamesePipeline
        vi_pipeline = self.pipelines.get_pipeline("vi")
        vi_analysis = vi_pipeline.analyze(q_text)

        # Chắt lọc query: loại bỏ hư từ hội thoại
        distilled_contents = distill_medical_query(vi_analysis.get("contents", q_text))
        concepts_val = vi_analysis.get("concepts", "")

        results.append(
            AnalyzedQuery(
                query_id=query.id,
                query_hash=q_hash,
                language="vi",
                variant_key="original",
                tokens_map={
                    "contents": distilled_contents,
                    "surface": vi_analysis.get("surface", q_text),
                    "medical_exact": vi_analysis.get("medical_exact", ""),
                    "concepts": concepts_val,
                },
            )
        )

        # Nếu ở chế độ lexical-control: ánh xạ symbol chung và chia sẻ concepts
        if self.config.mode == "lexical-control":
            en_analysis = self.pipelines.get_pipeline("en").analyze(q_text)
            zh_analysis = self.pipelines.get_pipeline("zh").analyze(q_text)
            results.append(
                AnalyzedQuery(
                    query_id=query.id,
                    query_hash=q_hash,
                    language="en",
                    variant_key="original_cross",
                    tokens_map={
                        "contents": en_analysis.get("contents", q_text),
                        "surface": en_analysis.get("surface", q_text),
                        "medical_exact": en_analysis.get("medical_exact", ""),
                        "concepts": concepts_val,
                    },
                )
            )
            results.append(
                AnalyzedQuery(
                    query_id=query.id,
                    query_hash=q_hash,
                    language="zh",
                    variant_key="original_cross",
                    tokens_map={
                        "contents": zh_analysis.get("contents", q_text),
                        "surface": zh_analysis.get("surface", q_text),
                        "medical_exact": zh_analysis.get("medical_exact", ""),
                        "concepts": concepts_val,
                    },
                )
            )
            return results

        # 2. Chế độ multilingual: Mở rộng thực thể qua MedicalLexicon
        aliases = self.lexicon.get_aliases_for_query(q_text, max_aliases=5)
        if aliases:
            expanded_text = q_text + " " + " ".join(aliases)
            exp_analysis = vi_pipeline.analyze(expanded_text)
            results.append(
                AnalyzedQuery(
                    query_id=query.id,
                    query_hash=q_hash,
                    language="vi",
                    variant_key="alias_expanded",
                    tokens_map={
                        "contents": distill_medical_query(exp_analysis.get("contents", expanded_text)),
                        "surface": exp_analysis.get("surface", expanded_text),
                        "medical_exact": exp_analysis.get("medical_exact", ""),
                        "concepts": exp_analysis.get("concepts", concepts_val),
                    },
                )
            )

        # 3. Tìm bản dịch EN/ZH từ Cache hoặc từ điển MedicalLexicon
        for target_lang in ["en", "zh"]:
            trans_text = self._get_cached_translation(q_hash, target_lang)
            if trans_text:
                target_analysis = self.pipelines.get_pipeline(target_lang).analyze(trans_text)
                results.append(
                    AnalyzedQuery(
                        query_id=query.id,
                        query_hash=q_hash,
                        language=target_lang,
                        variant_key=f"translated_{target_lang}",
                        tokens_map={
                            "contents": target_analysis.get("contents", trans_text),
                            "surface": target_analysis.get("surface", trans_text),
                            "medical_exact": target_analysis.get("medical_exact", ""),
                            "concepts": target_analysis.get("concepts", concepts_val),
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
                    target_analysis = self.pipelines.get_pipeline(target_lang).analyze(fallback_text)
                    results.append(
                        AnalyzedQuery(
                            query_id=query.id,
                            query_hash=q_hash,
                            language=target_lang,
                            variant_key=f"lexicon_fallback_{target_lang}",
                            tokens_map={
                                "contents": target_analysis.get("contents", fallback_text),
                                "surface": target_analysis.get("surface", fallback_text),
                                "medical_exact": target_analysis.get("medical_exact", ""),
                                "concepts": target_analysis.get("concepts", concepts_val),
                            },
                        )
                    )

        return results
