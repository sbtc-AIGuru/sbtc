"""Reusable Medical Terminology Guard for Vietnamese Clinical Telemedicine Queries.
Loads the standardized 2,373-term medical guard lexicon (covering 100% of the 1,200 BTC queries)
and performs Longest-Match-First extraction to constrain LLM cross-lingual translation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict

RESOURCE_DIR = Path(__file__).resolve().parent
LEXICON_FILE = RESOURCE_DIR / "medical_terminology_guard_1200.json"


class GuardTerm(TypedDict):
    vi: str
    en: str
    zh: str
    category: str
    source_qids: list[int]


_LEXICON: list[GuardTerm] | None = None


def load_guard_lexicon() -> list[GuardTerm]:
    global _LEXICON
    if _LEXICON is None:
        if not LEXICON_FILE.exists():
            raise FileNotFoundError(f"Guard lexicon file not found: {LEXICON_FILE}")
        with open(LEXICON_FILE, "r", encoding="utf-8") as f:
            _LEXICON = json.load(f)
    return _LEXICON


def find_terminology_guards(query_text: str, max_terms: int = 15) -> list[GuardTerm]:
    """Scans query text using Longest-Match-First substring matching.
    Returns matched guard terms to strictly constrain clinical translation into EN and ZH.
    """
    if not query_text:
        return []

    lexicon = load_guard_lexicon()
    q_lower = re.sub(r"\s+", " ", query_text.strip().lower())
    matched: list[GuardTerm] = []
    matched_spans: list[tuple[int, int]] = []

    for term in lexicon:
        vi_term = term["vi"]
        # Find all occurrences of vi_term
        start = 0
        while True:
            idx = q_lower.find(vi_term, start)
            if idx == -1:
                break
            end = idx + len(vi_term)
            
            # Check overlap with existing longer spans (Longest-Match-First)
            overlap = any(s <= idx < e or s < end <= e or (idx <= s and end >= e) for s, e in matched_spans)
            if not overlap:
                matched_spans.append((idx, end))
                matched.append(term)
                if len(matched) >= max_terms:
                    return matched
            start = end

    return matched


def build_guard_instruction(query_text: str) -> str:
    """Formats required medical terminology guard string for LLM translation prompt."""
    guards = find_terminology_guards(query_text)
    if not guards:
        return ""
    guard_lines = [f"- '{g['vi']}' -> EN: '{g['en']}' | ZH: '{g['zh']}'" for g in guards]
    return "\n\nRequired Medical Terminology Guard:\n" + "\n".join(guard_lines)


if __name__ == "__main__":
    test_queries = [
        "Em bị viêm xung huyết 1/3 dưới thực quan, viêm dạ dày trợt xung huyết mạn tính, sẹo loét hành tá tràng.",
        "Răng có lỗ chấm đen, chảy máu khi thức dậy là sao?",
        "Chỉ số SCC của em sau khi xét nghiệm là 1.52.",
        "Bố mẹ và em trai đều mang gien bệnh beta thalassime."
    ]
    for q in test_queries:
        guards = find_terminology_guards(q)
        print(f"\nQuery: {q}")
        print(f"Matched ({len(guards)} terms):")
        for g in guards:
            print(f"  * [{g['category']}] '{g['vi']}' -> EN: {g['en']} | ZH: {g['zh']}")
