from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path


DEFAULT_LEXICON = Path(__file__).parent / "resources/concepts.json"
CJK = re.compile(r"[\u3400-\u9fff]")


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


class Lexicon:
    """Namespaced, auditable aliases with Aho-Corasick phrase matching."""

    def __init__(self, path: Path = DEFAULT_LEXICON):
        import ahocorasick
        from opencc import OpenCC

        self.path = Path(path).resolve()
        payload = self.path.read_bytes()
        hasher = hashlib.sha256(payload)
        data = json.loads(payload)
        self.metadata = data["metadata"]
        self.entries = {}
        self.matchers = {}
        self.opencc = OpenCC("t2s")
        for entry in data["concepts"]:
            identifier = entry["concept_id"]
            if not isinstance(identifier, str) or ":" not in identifier or identifier in self.entries:
                raise ValueError("Concept IDs must be unique and namespaced")
            if not entry.get("source") or not entry.get("license"):
                raise ValueError("Lexicon entry missing source/license")
            self.entries[identifier] = entry
        for language in ("vi", "en", "zh"):
            terms = {}
            for identifier, entry in self.entries.items():
                for term in entry.get("labels", {}).get(language, []) + entry.get("aliases", {}).get(language, []):
                    if term in entry.get("ambiguous_aliases", []):
                        continue
                    key = self.normalize(term, language)
                    if key:
                        terms.setdefault(key, []).append(identifier)
            automaton = ahocorasick.Automaton()
            for term, identifiers in terms.items():
                automaton.add_word(term, (term, tuple(identifiers)))
            if terms:
                automaton.make_automaton()
            self.matchers[language] = (automaton, terms)

        # Load external segmentation terms (schema v2 or companion files)
        self.segmentation_dict: dict[str, set[str]] = {"vi": set(), "zh": set(), "en": set()}
        raw_seg = data.get("segmentation_terms", {})
        for lang in ("vi", "zh", "en"):
            seg_terms: list[str] = []
            if lang in raw_seg:
                val = raw_seg[lang]
                if isinstance(val, list):
                    seg_terms.extend(val)
                elif isinstance(val, str):
                    seg_file = self.path.parent / val
                    if seg_file.exists():
                        seg_bytes = seg_file.read_bytes()
                        hasher.update(seg_bytes)
                        seg_terms.extend(seg_bytes.decode("utf-8").splitlines())
            else:
                default_seg_file = self.path.parent / f"segmentation_{lang}.txt"
                if default_seg_file.exists():
                    seg_bytes = default_seg_file.read_bytes()
                    hasher.update(seg_bytes)
                    seg_terms.extend(seg_bytes.decode("utf-8").splitlines())
            for t in seg_terms:
                cleaned = self.normalize(t.strip(), lang)
                if cleaned and len(cleaned) > 1:
                    self.segmentation_dict[lang].add(cleaned)

        self.sha256 = hasher.hexdigest()

        # Build dedicated Aho-Corasick automaton for Vietnamese segmentation
        all_vi_seg = set(self.segmentation_dict["vi"])
        for term in self.matchers["vi"][1].keys():
            all_vi_seg.add(term)

        self.vi_seg_automaton = ahocorasick.Automaton()
        for term in all_vi_seg:
            self.vi_seg_automaton.add_word(term, term)
        if all_vi_seg:
            self.vi_seg_automaton.make_automaton()
        self.has_vi_seg = bool(all_vi_seg)

        # Build dedicated Aho-Corasick automaton for English segmentation
        all_en_seg = set(self.segmentation_dict["en"])
        for term in self.matchers["en"][1].keys():
            all_en_seg.add(term)

        self.en_seg_automaton = ahocorasick.Automaton()
        for term in all_en_seg:
            self.en_seg_automaton.add_word(term, term)
        if all_en_seg:
            self.en_seg_automaton.make_automaton()
        self.has_en_seg = bool(all_en_seg)

    def matches(self, text: str, language: str) -> list[tuple[int, int, str, str]]:
        text = self.normalize(text, language)
        automaton, terms = self.matchers[language]
        if not terms:
            return []
        result = []
        for end, (term, identifiers) in automaton.iter(text):
            start, stop = end - len(term) + 1, end + 1
            if not CJK.search(term):
                if start and (text[start - 1].isalnum() or text[start - 1] == "_"):
                    continue
                if stop < len(text) and (text[stop].isalnum() or text[stop] == "_"):
                    continue
            # Ambiguous terms sharing multiple concepts remain lexical, not grounded.
            if len(identifiers) == 1:
                result.append((start, stop, term, identifiers[0]))
        return sorted(result, key=lambda x: (x[0], -(x[1] - x[0]), x[3]))

    def normalize(self, text: str, language: str) -> str:
        value = normalized(text).lower()
        return self.opencc.convert(value) if language == "zh" else value

    def anchors(self, text: str, language: str) -> tuple[str, ...]:
        return tuple(sorted({m[3] for m in self.matches(text, language)}))

    def terms(self, language: str) -> tuple[str, ...]:
        return tuple(self.matchers[language][1])

    def segmentation_terms(self, language: str) -> tuple[str, ...]:
        """Return segmentation terms for language (concepts + approved segmentation terms)."""
        if language == "zh":
            terms = set(self.segmentation_dict.get("zh", set()))
            terms.update(self.matchers["zh"][1].keys())
            return tuple(sorted(terms))
        elif language == "vi":
            terms = set(self.segmentation_dict.get("vi", set()))
            terms.update(self.matchers["vi"][1].keys())
            return tuple(sorted(terms))
        elif language == "en":
            terms = set(self.segmentation_dict.get("en", set()))
            terms.update(self.matchers["en"][1].keys())
            return tuple(sorted(terms))
        return ()

    def segmentation_spans(self, sentence: str, language: str) -> list[tuple[int, int, str]]:
        """Return non-overlapping greedy longest-match spans (start, stop, term) with word boundaries."""
        if language == "en" and self.has_en_seg:
            automaton = self.en_seg_automaton
        elif language == "vi" and self.has_vi_seg:
            automaton = self.vi_seg_automaton
        else:
            return []
        text = self.normalize(sentence, language)
        hits = []
        for end, term in automaton.iter(text):
            start = end - len(term) + 1
            stop = end + 1
            if start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
                continue
            if stop < len(text) and (text[stop].isalnum() or text[stop] == "_"):
                continue
            hits.append((start, stop, term))
        hits.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
        selected = []
        occupied = [False] * (len(text) + 1)
        for s, e, term in hits:
            if not any(occupied[s:e]):
                selected.append((s, e, term))
                for i in range(s, e):
                    occupied[i] = True
        return sorted(selected, key=lambda x: x[0])

    def segmentation_matches(self, sentence: str, language: str) -> list[str]:
        """Find matching segmentation terms with whole-word boundary check, sorted longest-first."""
        if language == "vi" and self.has_vi_seg:
            automaton = self.vi_seg_automaton
        elif language == "en" and self.has_en_seg:
            automaton = self.en_seg_automaton
        else:
            return []
        text = self.normalize(sentence, language)
        matches = []
        for end, term in automaton.iter(text):
            start = end - len(term) + 1
            stop = end + 1
            if start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
                continue
            if stop < len(text) and (text[stop].isalnum() or text[stop] == "_"):
                continue
            matches.append(term)
        # Sort longest-first to ensure greedy grouping of larger medical compound terms
        matches.sort(key=lambda t: (-len(t), t))
        return matches

    def aliases(self, identifiers: tuple[str, ...], language: str) -> tuple[str, ...]:
        values = []
        for identifier in identifiers:
            entry = self.entries[identifier]
            for term in entry.get("labels", {}).get(language, []) + entry.get("aliases", {}).get(language, []):
                if term not in entry.get("ambiguous_aliases", []):
                    values.append(term)
        return tuple(dict.fromkeys(values))
