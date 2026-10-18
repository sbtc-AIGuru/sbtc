from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


FIELDS = ("contents", "broad", "exact", "anchors", "title")
LANGUAGES = ("vi", "en", "zh")
ANALYZER_PROFILE = "medical-no-folded-v1"
INDEX_SCHEMA_VERSION = 2
MANIFEST_FORMAT_VERSION = 2


@dataclass(frozen=True)
class Analysis:
    fields: Mapping[str, tuple[str, ...]]

    def record(self, identifier: str) -> dict:
        return {"id": identifier, **{f: " ".join(self.fields.get(f, ())) for f in FIELDS}}


@dataclass(frozen=True)
class Hit:
    identifier: str
    score: float
    rank: int


class Analyzer(Protocol):
    def analyze(self, text: str, language: str, *, index_mode: bool) -> Analysis: ...


class SearchBackend(Protocol):
    def search(self, granularity: str, language: str, fields: Mapping[str, Sequence[str]], *, k: int, k1: float, b: float) -> list[Hit]: ...
    def close(self) -> None: ...
