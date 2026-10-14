"""MedicalLexicon: Từ điển Y khoa Đa ngữ & Trie Longest-Match Matching.

Theo SPEC-bm25-medical-multilingual.md Mục 7.1.
Hỗ trợ nhận diện thực thể y khoa, bảo vệ từ viết tắt (ambiguity check),
cung cấp canonical concept IDs cho index và query expansion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class LexiconEntry:
    """Một thực thể y khoa trong từ điển."""

    concept_id: str
    concept_type: str
    labels: Mapping[str, str]  # {'vi': 'suy thận', 'en': 'renal failure', 'zh': '肾衰竭'}
    aliases: Sequence[str] = field(default_factory=list)
    ambiguity: bool = False


class TrieNode:
    """Node trong cây Trie phục vụ Longest-Match."""

    def __init__(self) -> None:
        self.children: Dict[str, TrieNode] = {}
        self.entry: Optional[LexiconEntry] = None
        self.matched_language: str = ""


class MedicalLexicon:
    """Quản lý từ điển y khoa và thuật toán đối khớp Longest-Match."""

    def __init__(self, entries: Sequence[LexiconEntry] | None = None) -> None:
        self.entries = list(entries) if entries else []
        self.root = TrieNode()
        self._build_trie()

    def _build_trie(self) -> None:
        """Xây dựng cây Trie từ các nhãn và bí danh."""
        for entry in self.entries:
            # Bỏ qua nếu là từ viết tắt mơ hồ (như MS) trừ khi có xử lý đặc biệt
            if entry.ambiguity:
                continue

            # Nạp các label theo ngôn ngữ
            for lang, text in entry.labels.items():
                if text:
                    self._insert_phrase(text.lower().strip(), entry, lang)

            # Nạp các aliases
            for alias in entry.aliases:
                if alias:
                    self._insert_phrase(alias.lower().strip(), entry, "alias")

    def _insert_phrase(self, phrase: str, entry: LexiconEntry, lang: str) -> None:
        curr = self.root
        for char in phrase:
            if char not in curr.children:
                curr.children[char] = TrieNode()
            curr = curr.children[char]
        curr.entry = entry
        curr.matched_language = lang

    def find_concepts(self, text: str) -> List[Tuple[str, LexiconEntry]]:
        """Tìm các concept y khoa xuất hiện trong chuỗi bằng Longest-Match."""
        text_lower = text.lower()
        n = len(text_lower)
        matches: List[Tuple[str, LexiconEntry]] = []
        i = 0

        while i < n:
            curr = self.root
            longest_match_entry: Optional[LexiconEntry] = None
            longest_match_end = -1
            j = i

            while j < n and text_lower[j] in curr.children:
                curr = curr.children[text_lower[j]]
                if curr.entry:
                    longest_match_entry = curr.entry
                    longest_match_end = j + 1
                j += 1

            if longest_match_entry and longest_match_end != -1:
                matched_str = text_lower[i:longest_match_end]
                matches.append((matched_str, longest_match_entry))
                i = longest_match_end  # Nhảy qua đoạn đã khớp
            else:
                i += 1

        return matches

    def get_aliases_for_query(self, text: str, max_aliases: int = 5) -> List[str]:
        """Lấy danh sách các bí danh hoặc nhãn ngôn ngữ khác cho câu query."""
        concepts = self.find_concepts(text)
        aliases: Set[str] = set()

        for _, entry in concepts:
            for lang, label in entry.labels.items():
                if label and label.lower() not in text.lower():
                    aliases.add(label)
                    if len(aliases) >= max_aliases:
                        break
            for a in entry.aliases:
                if a and a.lower() not in text.lower():
                    aliases.add(a)
                    if len(aliases) >= max_aliases:
                        break

        return list(aliases)[:max_aliases]

    @classmethod
    def from_jsonl(cls, jsonl_path: str | Path) -> MedicalLexicon:
        """Đọc từ điển từ file JSONL."""
        path = Path(jsonl_path).resolve()
        if not path.is_file():
            return cls([])

        entries: List[LexiconEntry] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                d = json.loads(line_str)
                entries.append(
                    LexiconEntry(
                        concept_id=d["concept_id"],
                        concept_type=d.get("type", "medical"),
                        labels=d.get("labels", {}),
                        aliases=d.get("aliases", []),
                        ambiguity=d.get("ambiguity", False),
                    )
                )

        return cls(entries)
