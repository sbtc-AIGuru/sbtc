"""Tokenization Pipelines cho Việt - Anh - Trung & Khóa Thực Thể Y Khoa Đa Ngữ.

Theo đặc tả kỹ thuật:
- Chuẩn hóa: NFKC, unescape HTML, lowercase, bảo vệ phủ định và biomarker.
- Drug & Dosage: Tích hợp DrugDosageRecognizer 2 tầng nhận diện tên thuốc, liều lượng và cặp thuốc_liều.
- Concept Mapping: Tự động trích xuất mã concept chuẩn (MC0001 - MC0378) từ 407 concept mappings.
- Vietnamese: Trie Longest-match Pre-merging (50k base_vi) khóa cụm y khoa trước Underthesea.
- English: Lucene EnglishAnalyzer không stopword, bảo toàn stem y khoa.
- Chinese: Jieba precise mode kết hợp 50k base_zh user dictionary + CJK bigrams.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sbtc.Scripts.Retrieval.drug_dosage import DrugDosageRecognizer


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


def extract_biomarker_exact_tokens(text: str) -> List[str]:
    """Trích xuất các biomarker, gene, ký hiệu số, liều lượng có dấu câu."""
    pattern = (
        r"\b[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)+\+?(?=\s|[.,;!?:]|$)|"
        r"\b[a-zA-Z]+[0-9]+\+?(?=\s|[.,;!?:]|$)"
    )
    return re.findall(pattern, text)


class ConceptMatcher:
    """Quản lý và so khớp nhanh Concept IDs đa ngữ qua Trie."""

    def __init__(self, concepts_path: Optional[str | Path] = None) -> None:
        if concepts_path is None:
            default_p = Path(__file__).resolve().parent / "resources" / "concepts_aligned_vi_en_zh.jsonl"
            concepts_path = default_p if default_p.is_file() else None
        else:
            concepts_path = Path(concepts_path).resolve()

        self.concepts_path = concepts_path
        self.tries: Dict[str, Dict[str, Any]] = {"vi": {}, "en": {}, "zh": {}}
        self._load()

    def _load(self) -> None:
        if not self.concepts_path or not self.concepts_path.is_file():
            return

        with open(self.concepts_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                d = json.loads(line_str)
                cid = d["concept_id"]
                for lang in ["vi", "en", "zh"]:
                    term = d.get(lang, "").strip().lower()
                    if term:
                        self._insert(lang, term, cid)

    def _insert(self, lang: str, phrase: str, concept_id: str) -> None:
        curr = self.tries[lang]
        for ch in phrase:
            if ch not in curr:
                curr[ch] = {}
            curr = curr[ch]
        if "_concepts" not in curr:
            curr["_concepts"] = []
        curr["_concepts"].append(concept_id)

    def extract_concepts(self, text: str, lang: str) -> List[str]:
        """Trích xuất danh sách concept_id xuất hiện trong văn bản."""
        if lang not in self.tries:
            return []
        text_lower = text.lower()
        trie = self.tries[lang]
        n = len(text_lower)
        found_concepts: List[str] = []
        seen = set()

        i = 0
        while i < n:
            curr = trie
            longest_match_concepts = None
            longest_end = -1
            j = i
            while j < n and text_lower[j] in curr:
                curr = curr[text_lower[j]]
                if "_concepts" in curr:
                    # Ranh giới từ
                    if j + 1 == n or not text_lower[j + 1].isalnum():
                        longest_match_concepts = curr["_concepts"]
                        longest_end = j + 1
                j += 1

            if longest_match_concepts and longest_end != -1:
                for cid in longest_match_concepts:
                    if cid not in seen:
                        seen.add(cid)
                        found_concepts.append(cid)
                i = longest_end
            else:
                i += 1

        return found_concepts


class PhrasePreMergeTrie:
    """Trie nạp 50k từ vựng y tế tiếng Việt để tiền ghép nối dấu '_'."""

    def __init__(self, vocab_path: Optional[str | Path] = None) -> None:
        if vocab_path is None:
            default_p = Path(__file__).resolve().parent / "resources" / "base_vi.txt"
            vocab_path = default_p if default_p.is_file() else None
        else:
            vocab_path = Path(vocab_path).resolve()

        self.vocab_path = vocab_path
        self.root: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.vocab_path or not self.vocab_path.is_file():
            return
        with open(self.vocab_path, "r", encoding="utf-8") as f:
            for line in f:
                phrase = line.strip().lower()
                if " " in phrase:  # Chỉ cần tiền ghép cho cụm >= 2 từ
                    curr = self.root
                    for ch in phrase:
                        if ch not in curr:
                            curr[ch] = {}
                        curr = curr[ch]
                    curr["_end"] = True

    def pre_merge(self, text: str) -> str:
        """Gộp các cụm từ y tế bằng dấu gạch dưới '_'."""
        if not self.root:
            return text
        text_lower = text.lower()
        n = len(text)
        i = 0
        out_parts = []

        while i < n:
            curr = self.root
            longest_end = -1
            j = i
            while j < n and text_lower[j] in curr:
                curr = curr[text_lower[j]]
                if "_end" in curr:
                    if j + 1 == n or not text_lower[j + 1].isalnum():
                        longest_end = j + 1
                j += 1

            if longest_end != -1:
                matched_phrase = text[i:longest_end]
                out_parts.append(matched_phrase.replace(" ", "_"))
                i = longest_end
            else:
                out_parts.append(text[i])
                i += 1

        return "".join(out_parts)


class VietnamesePipeline:
    """Pipeline phân tích từ tiếng Việt dùng Underthesea kết hợp 50k Base Data."""

    def __init__(
        self,
        drug_recognizer: Optional[DrugDosageRecognizer] = None,
        concept_matcher: Optional[ConceptMatcher] = None,
        pre_merge_trie: Optional[PhrasePreMergeTrie] = None,
    ) -> None:
        self.language = "vi"
        self._underthesea = None
        self.drug_recognizer = drug_recognizer or DrugDosageRecognizer()
        self.concept_matcher = concept_matcher or ConceptMatcher()
        self.pre_merge_trie = pre_merge_trie or PhrasePreMergeTrie()

    def _ensure_loaded(self) -> None:
        if self._underthesea is None:
            import underthesea

            self._underthesea = underthesea

    def analyze(self, text: str) -> Dict[str, str]:
        self._ensure_loaded()
        cleaned = normalize_medical_text(text)
        if not cleaned:
            return {"contents": "", "surface": "", "medical_exact": "", "concepts": ""}

        # 1. Trích xuất thuốc và liều lượng qua DrugDosageRecognizer
        drug_str, exact_tokens = self.drug_recognizer.process_text_tokens(cleaned, language="vi")
        biomarkers = extract_biomarker_exact_tokens(cleaned)
        all_exact = list(dict.fromkeys(exact_tokens + biomarkers))

        # 2. Tiền ghép từ y khoa 50k base_vi trước khi đưa sang Underthesea
        merged_text = self.pre_merge_trie.pre_merge(cleaned)

        # 3. Phân đoạn từ tiếng Việt với format='text' (nối bằng '_')
        try:
            tokens_text = self._underthesea.word_tokenize(merged_text, format="text")
        except Exception:
            tokens_text = merged_text

        # 4. Surface: âm tiết rời
        surface_tokens = cleaned.replace("_", " ").split()

        # 5. Concept IDs
        concepts = self.concept_matcher.extract_concepts(cleaned, "vi")

        return {
            "contents": tokens_text,
            "surface": " ".join(surface_tokens),
            "medical_exact": " ".join(all_exact),
            "concepts": " ".join(concepts),
        }


class EnglishPipeline:
    """Pipeline phân tích từ tiếng Anh dùng Lucene EnglishAnalyzer không stopword."""

    def __init__(
        self,
        drug_recognizer: Optional[DrugDosageRecognizer] = None,
        concept_matcher: Optional[ConceptMatcher] = None,
    ) -> None:
        self.language = "en"
        self._analyzer = None
        self.drug_recognizer = drug_recognizer or DrugDosageRecognizer()
        self.concept_matcher = concept_matcher or ConceptMatcher()

    def _get_lucene_analyzer(self):
        if self._analyzer is None:
            try:
                import jnius
                from jnius import autoclass

                EnglishAnalyzer = autoclass("org.apache.lucene.analysis.en.EnglishAnalyzer")
                CharArraySet = autoclass("org.apache.lucene.analysis.CharArraySet")
                empty_stop_set = CharArraySet.EMPTY_SET
                self._analyzer = EnglishAnalyzer(empty_stop_set)
            except Exception:
                self._analyzer = None
        return self._analyzer

    def analyze(self, text: str) -> Dict[str, str]:
        cleaned = normalize_medical_text(text)
        if not cleaned:
            return {"contents": "", "surface": "", "medical_exact": "", "concepts": ""}

        # 1. Trích xuất thuốc & liều lượng
        drug_str, exact_tokens = self.drug_recognizer.process_text_tokens(cleaned, language="en")
        biomarkers = extract_biomarker_exact_tokens(cleaned)
        all_exact = list(dict.fromkeys(exact_tokens + biomarkers))

        # 2. Lucene EnglishAnalyzer
        contents_val = " ".join(cleaned.split())
        analyzer = self._get_lucene_analyzer()
        if analyzer is not None:
            try:
                from jnius import autoclass

                CharTermAttribute = autoclass("org.apache.lucene.analysis.tokenattributes.CharTermAttribute")
                token_stream = analyzer.tokenStream("contents", cleaned)
                token_stream.reset()
                term_attr = token_stream.getAttribute(CharTermAttribute)

                stemmed_tokens = []
                while token_stream.incrementToken():
                    stemmed_tokens.append(term_attr.toString())
                token_stream.end()
                token_stream.close()
                contents_val = " ".join(stemmed_tokens)
            except Exception:
                contents_val = " ".join(cleaned.split())

        surface_val = " ".join(cleaned.split())
        concepts = self.concept_matcher.extract_concepts(cleaned, "en")

        return {
            "contents": contents_val,
            "surface": surface_val,
            "medical_exact": " ".join(all_exact),
            "concepts": " ".join(concepts),
        }


class ChinesePipeline:
    """Pipeline phân tích từ tiếng Trung dùng Jieba precise mode kết hợp 50k UserDict."""

    def __init__(
        self,
        user_dict_path: Optional[str] = None,
        drug_recognizer: Optional[DrugDosageRecognizer] = None,
        concept_matcher: Optional[ConceptMatcher] = None,
    ) -> None:
        self.language = "zh"
        if user_dict_path is None:
            default_zh = Path(__file__).resolve().parent / "resources" / "base_zh.txt"
            user_dict_path = str(default_zh) if default_zh.is_file() else None
        self.user_dict_path = user_dict_path
        self._jieba = None
        self.drug_recognizer = drug_recognizer or DrugDosageRecognizer()
        self.concept_matcher = concept_matcher or ConceptMatcher()

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

        # 1. Trích xuất thuốc & liều lượng
        drug_str, exact_tokens = self.drug_recognizer.process_text_tokens(cleaned, language="zh")
        biomarkers = extract_biomarker_exact_tokens(cleaned)
        all_exact = list(dict.fromkeys(exact_tokens + biomarkers))

        # 2. Jieba cut precise mode
        tokens = list(self._jieba.cut(cleaned, cut_all=False, HMM=True))
        contents_val = " ".join([t.strip() for t in tokens if t.strip()])

        # 3. Surface: CJK Character Bigrams
        cjk_chars = [c for c in cleaned if "\u4e00" <= c <= "\u9fff"]
        bigrams = [cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)]

        # 4. Concepts
        concepts = self.concept_matcher.extract_concepts(cleaned, "zh")

        return {
            "contents": contents_val,
            "surface": " ".join(bigrams),
            "medical_exact": " ".join(all_exact),
            "concepts": " ".join(concepts),
        }


class TokenPipelineRegistry:
    """Quản lý các TokenPipeline theo ngôn ngữ."""

    def __init__(self, jieba_dict_path: Optional[str] = None) -> None:
        drug_rec = DrugDosageRecognizer()
        concept_matcher = ConceptMatcher()
        pre_merge = PhrasePreMergeTrie()

        self.pipelines = {
            "vi": VietnamesePipeline(drug_rec, concept_matcher, pre_merge),
            "en": EnglishPipeline(drug_rec, concept_matcher),
            "zh": ChinesePipeline(jieba_dict_path, drug_rec, concept_matcher),
        }

    def get_pipeline(self, lang: str):
        if lang not in self.pipelines:
            return self.pipelines["vi"]
        return self.pipelines[lang]
