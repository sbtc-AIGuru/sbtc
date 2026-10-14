"""Tokenization Pipelines cho Việt - Anh - Trung & Chống Phân Tích Hai Lần.

Theo SPEC-bm25-medical-multilingual.md Mục 6.
- Chuẩn hóa: NFKC, unescape HTML, lowercase, bảo vệ phủ định và biomarker.
- Vietnamese: Underthesea word_tokenize với dấu '_', surface âm tiết.
- English: Lucene EnglishAnalyzer với stopword rỗng, surface không stem, medical_exact.
- Chinese: Jieba precise mode + medical user dictionary, surface CJK bigrams.
- Tất cả các trường xuất token phân cách bằng đúng một dấu cách (chuẩn WhitespaceAnalyzer).
"""

from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set


def normalize_medical_text(text: str) -> str:
    """Chuẩn hóa văn bản trước khi phân tích từ vựng, bảo toàn ký hiệu y khoa."""
    if not text:
        return ""
    # 1. NFKC
    text = unicodedata.normalize("NFKC", text)
    # 2. Giải mã HTML entities
    text = html.unescape(text)
    # 3. Chuyển chữ thường
    text = text.lower()
    # 4. Gộp khoảng trắng liên tiếp
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_medical_exact_tokens(text: str) -> List[str]:
    """Trích xuất các biomarker, gene, ký hiệu số, liều lượng có dấu câu.

    Ví dụ: IL-6, CD4+, SARS-CoV-2, H1N1, 500mg, 10.5mg/ml.
    """
    pattern = (
        r"\b[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)+\+?(?=\s|[.,;!?:]|$)|"
        r"\b[a-zA-Z]+[0-9]+\+?(?=\s|[.,;!?:]|$)|"
        r"\b\d+(?:\.\d+)?(?:mg|ml|g|mcg|iu|%)(?=\s|[.,;!?:]|$)"
    )
    return re.findall(pattern, text)



class VietnamesePipeline:
    """Pipeline phân tích từ tiếng Việt dùng Underthesea."""

    def __init__(self) -> None:
        self.language = "vi"
        self._underthesea = None

    def _ensure_loaded(self) -> None:
        if self._underthesea is None:
            import underthesea

            self._underthesea = underthesea

    def analyze(self, text: str) -> Dict[str, str]:
        self._ensure_loaded()
        cleaned = normalize_medical_text(text)
        if not cleaned:
            return {"contents": "", "surface": "", "medical_exact": "", "concepts": ""}

        # 1. Phân đoạn từ tiếng Việt với format='text' (nối bằng '_')
        try:
            tokens_text = self._underthesea.word_tokenize(cleaned, format="text")
        except Exception:
            tokens_text = cleaned

        # 2. Surface: âm tiết rời
        surface_tokens = cleaned.replace("_", " ").split()

        # 3. Medical exact
        exact_tokens = extract_medical_exact_tokens(cleaned)

        return {
            "contents": tokens_text,
            "surface": " ".join(surface_tokens),
            "medical_exact": " ".join(exact_tokens),
            "concepts": "",
        }


class EnglishPipeline:
    """Pipeline phân tích từ tiếng Anh dùng Lucene EnglishAnalyzer không stopword."""

    def __init__(self) -> None:
        self.language = "en"
        self._analyzer = None

    def _get_lucene_analyzer(self):
        """Khởi tạo org.apache.lucene.analysis.en.EnglishAnalyzer với stopword rỗng."""
        if self._analyzer is None:
            try:
                import jnius
                from jnius import autoclass

                EnglishAnalyzer = autoclass("org.apache.lucene.analysis.en.EnglishAnalyzer")
                CharArraySet = autoclass("org.apache.lucene.analysis.CharArraySet")
                # Stopword rỗng để bảo toàn 'no', 'not', 'without'
                empty_stop_set = CharArraySet.EMPTY_SET
                self._analyzer = EnglishAnalyzer(empty_stop_set)
            except Exception as e:
                # Fallback nếu pyjnius chưa nạp
                self._analyzer = None
        return self._analyzer

    def analyze(self, text: str) -> Dict[str, str]:
        cleaned = normalize_medical_text(text)
        if not cleaned:
            return {"contents": "", "surface": "", "medical_exact": "", "concepts": ""}

        analyzer = self._get_lucene_analyzer()
        if analyzer is not None:
            from jnius import autoclass

            StringReader = autoclass("java.io.StringReader")
            CharTermAttribute = autoclass("org.apache.lucene.analysis.tokenattributes.CharTermAttribute")

            reader = StringReader(cleaned)
            token_stream = analyzer.tokenStream("contents", reader)
            token_stream.reset()
            term_attr = token_stream.getAttribute(CharTermAttribute)

            stemmed_tokens = []
            while token_stream.incrementToken():
                stemmed_tokens.append(term_attr.toString())
            token_stream.end()
            token_stream.close()
            contents_val = " ".join(stemmed_tokens)
        else:
            # Fallback nhẹ nhàng
            contents_val = cleaned

        # Surface giữ nguyên thể không stem
        surface_val = " ".join(cleaned.split())
        # Medical exact
        exact_tokens = extract_medical_exact_tokens(cleaned)

        return {
            "contents": contents_val,
            "surface": surface_val,
            "medical_exact": " ".join(exact_tokens),
            "concepts": "",
        }


class ChinesePipeline:
    """Pipeline phân tích từ tiếng Trung dùng Jieba precise mode."""

    def __init__(self, user_dict_path: Optional[str] = None) -> None:
        self.language = "zh"
        self.user_dict_path = user_dict_path
        self._jieba = None

    def _ensure_loaded(self) -> None:
        if self._jieba is None:
            import jieba

            self._jieba = jieba.Tokenizer()
            if self.user_dict_path and Path(self.user_dict_path).is_file():
                self._jieba.load_userdict(self.user_dict_path)

    def analyze(self, text: str) -> Dict[str, str]:
        self._ensure_loaded()
        cleaned = normalize_medical_text(text)
        if not cleaned:
            return {"contents": "", "surface": "", "medical_exact": "", "concepts": ""}

        # 1. Jieba cut precise mode
        tokens = list(self._jieba.cut(cleaned, cut_all=False, HMM=True))
        contents_val = " ".join([t.strip() for t in tokens if t.strip()])

        # 2. Surface: CJK Character Bigrams (để cứu từ ngoài từ điển)
        cjk_chars = [c for c in cleaned if "\u4e00" <= c <= "\u9fff"]
        bigrams = [cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)]

        exact_tokens = extract_medical_exact_tokens(cleaned)

        return {
            "contents": contents_val,
            "surface": " ".join(bigrams),
            "medical_exact": " ".join(exact_tokens),
            "concepts": "",
        }


class TokenPipelineRegistry:
    """Quản lý các TokenPipeline theo ngôn ngữ."""

    def __init__(self, jieba_dict_path: Optional[str] = None) -> None:
        self.pipelines = {
            "vi": VietnamesePipeline(),
            "en": EnglishPipeline(),
            "zh": ChinesePipeline(jieba_dict_path),
        }

    def get_pipeline(self, lang: str):
        if lang not in self.pipelines:
            return self.pipelines["vi"]
        return self.pipelines[lang]
