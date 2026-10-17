from __future__ import annotations

import html
import re
from collections import OrderedDict

from .lexicon import Lexicon, normalized
from .models import Analysis
from .runtime import configure_java


WORDS = re.compile(r"[^\W_]+(?:[-/+*:.][^\W_]+)*", re.UNICODE)
BONDED_WORDS = re.compile(r"[A-Za-z0-9_]+(?:[-/+*:.][A-Za-z0-9_]+)*", re.UNICODE)
DOSE = re.compile(
    r"(?<![A-Za-z0-9_])(?<!\d[.,])(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>mmol|mmHg|mcg|μg|µg|mg|kg|ml|g)"
    r"(?:\s*/\s*(?:kg|ml|L|min|h))?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
SYMBOL = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:[-/*:+.][A-Za-z0-9_]+)*(?:\+)?(?![A-Za-z0-9_])"
)
SENTENCE = re.compile(r"[\n。！？!?;；]+|(?<=[A-Za-zÀ-ỹ])\.(?=\s|$)|,(?=\s)")
STRUCTURAL_HEADINGS = frozenset({
    "abstract", "background", "objective", "methods", "materials", "results",
    "conclusions", "design", "setting", "participants", "intervention",
    "outcome", "primary", "secondary", "case", "figure", "table",
})
SPELLING = {"haemoglobin":"hemoglobin", "haemorrhage":"hemorrhage", "oesophagus":"esophagus", "oestrogen":"estrogen", "paediatric":"pediatric", "anaemia":"anemia", "diarrhoea":"diarrhea", "leucocyte":"leukocyte"}
INFLECTION = {"thrombi":"thrombus", "diverticula":"diverticulum", "metastases":"metastasis", "foci":"focus", "lumina":"lumen", "matrices":"matrix"}
GREEK = str.maketrans({"α":"alpha", "β":"beta", "γ":"gamma"})


def unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v and not any(c.isspace() for c in v)))


def _is_han(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
        or 0x30000 <= codepoint <= 0x3134F
    )


def _touches_han(text: str, start: int, end: int) -> bool:
    return (start > 0 and _is_han(text[start - 1])) or (end < len(text) and _is_han(text[end]))


def exact_tokens(text: str, *, lexicon: Lexicon | None = None) -> tuple[str, ...]:
    """Inspect case before lowercasing; preserve literal ambiguity, never invent CUI."""
    raw = normalized(html.unescape(text))
    tokens = []
    for match in DOSE.finditer(raw):
        value = match.group("value")
        unit = match.group("unit").lower()
        if unit in {"μg", "µg"}:
            unit = "mcg"
        route = re.search(r"/\s*(?:kg|ml|L|min|h)$", match.group(), re.IGNORECASE)
        suffix = re.sub(r"\s+", "", route.group()).lower() if route else ""
        tokens.append(value + unit + suffix)
    for match in SYMBOL.finditer(raw):
        term = match.group()
        if any(c.isdigit() for c in term) or (term.isupper() and 2 <= len(term) <= 8) or any(c in term for c in "/+-*:"):
            literal = term.lower()
            tokens.extend((literal, re.sub(r"[-/+]", "", literal)))
            if term.isupper() and literal not in STRUCTURAL_HEADINGS:
                tokens.append("case_upper_" + literal)
        elif lexicon is not None and _touches_han(raw, match.start(), match.end()):
            # Promote a Latin word embedded in Han text only when the current
            # medical lexicon recognizes it; arbitrary English stays unmarked.
            if lexicon.anchors(term, "en"):
                tokens.append(term.lower())
    return unique(tokens)


def _underthesea_fixed_words(terms: list[str]) -> list[str]:
    """Escape lexicon literals for Underthesea's verbose-regex fixed_words API."""
    # Underthesea escapes spaces but interpolates every other character into a
    # regex. Lexicon entries can contain punctuation such as an unmatched ')'.
    return [re.escape(term).replace(r"\ ", " ") for term in terms]


class MedicalAnalyzer:
    def __init__(self, lexicon: Lexicon, *, cache_entries: int = 256):
        configure_java()
        from pyserini.analysis import Analyzer, get_lucene_analyzer
        import jieba
        from opencc import OpenCC

        self.lexicon = lexicon
        self.english = Analyzer(get_lucene_analyzer("en", stemmer="krovetz", stopwords=False))
        self.chinese = jieba.Tokenizer()
        self.opencc = OpenCC("t2s")
        for term in lexicon.segmentation_terms("zh"):
            self.chinese.add_word(self.opencc.convert(term))
        self.cache_entries = cache_entries
        self.cache = OrderedDict()

    def analyze(self, text: str, language: str, *, index_mode: bool) -> Analysis:
        key = (text, language, index_mode)
        if len(text) <= 4096 and key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        raw = normalized(html.unescape(text))
        if language == "zh":
            raw = self.opencc.convert(raw)
        anchors = set(self.lexicon.anchors(raw, language))
        if language == "zh":
            for match in SYMBOL.finditer(raw):
                if _touches_han(raw, match.start(), match.end()):
                    anchors.update(self.lexicon.anchors(match.group(), "en"))
        anchors = tuple(sorted(anchors))
        exact = exact_tokens(raw, lexicon=self.lexicon)
        lower = raw.replace("μg", "mcg").translate(GREEK).lower()
        compound, broad = [], []
        if language == "vi":
            from underthesea import word_tokenize
            for sentence in SENTENCE.split(lower):
                if not sentence.strip():
                    continue
                fixed = _underthesea_fixed_words(self.lexicon.segmentation_matches(sentence, "vi"))
                compound.extend(word_tokenize(sentence, format="text", fixed_words=fixed).split())
                syllables = [m.group().lower() for m in WORDS.finditer(sentence)]
                broad.extend(syllables)
                for n in (2, 3):
                    broad.extend("_".join(syllables[i:i+n]) for i in range(max(0, len(syllables)-n+1)))
        elif language == "zh":
            for sentence in SENTENCE.split(lower):
                compound.extend(t for t in self.chinese.cut(sentence, HMM=True) if any(c.isalnum() for c in t))
                if index_mode:
                    broad.extend(t for t in self.chinese.cut_for_search(sentence, HMM=True) if any(c.isalnum() for c in t))
                else:
                    broad.extend(t for t in self.chinese.cut(sentence, HMM=True) if len(t) >= 2 and any(c.isalnum() for c in t))
                for segment in re.findall(r"[\u3400-\u9fff]+", sentence):
                    broad.extend(segment[i:i+2] for i in range(len(segment)-1))
        elif language == "en":
            for sentence in SENTENCE.split(lower):
                if not sentence.strip():
                    continue
                words = [m.group() for m in WORDS.finditer(sentence)]
                canonical = [SPELLING.get(w, INFLECTION.get(w, w)) for w in words]
                broad.extend(words)
                broad.extend(canonical)
                spans = self.lexicon.segmentation_spans(sentence, "en")
                multi_spans = [s for s in spans if " " in s[2]]
                if multi_spans:
                    parts = []
                    last_idx = 0
                    for start, stop, term in multi_spans:
                        parts.append(sentence[last_idx:start])
                        parts.append(term.replace(" ", "_"))
                        last_idx = stop
                    parts.append(sentence[last_idx:])
                    bonded_sentence = "".join(parts)
                    tokens = [m.group() for m in BONDED_WORDS.finditer(bonded_sentence)]
                    canonical_tokens = [t if "_" in t else SPELLING.get(t, INFLECTION.get(t, t)) for t in tokens]
                    compound.extend(self.english.analyze(" ".join(canonical_tokens)))
                else:
                    compound.extend(self.english.analyze(" ".join(canonical)))
            broad.extend(exact)
        else:
            raise ValueError(f"Unsupported language: {language}")
        # Preserve TF in compound. Auxiliary alternatives are unique per record.
        compound = tuple(t for t in compound if any(c.isalnum() for c in t))
        result = Analysis({"contents": compound, "broad": unique(broad), "exact": exact, "anchors": anchors})
        if len(text) <= 4096 and self.cache_entries:
            self.cache[key] = result
            self.cache.move_to_end(key)
            if len(self.cache) > self.cache_entries:
                self.cache.popitem(last=False)
        return result
