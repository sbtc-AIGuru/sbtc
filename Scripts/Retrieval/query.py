from __future__ import annotations

import json
import re
from pathlib import Path

from .analyzers import MedicalAnalyzer, exact_tokens
from .utils import sha_bytes, source_id
from .translation import validate_provenance


def iter_queries(path: Path):
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq
        iterator = (x for batch in pq.ParquetFile(path).iter_batches(batch_size=128, columns=["id", "query"]) for x in batch.to_pylist())
    elif path.suffix == ".jsonl":
        def lines():
            with path.open() as f:
                for line in f:
                    yield json.loads(line)
        iterator = lines()
    elif path.suffix == ".json":
        iterator = iter(json.loads(path.read_text()))
    else:
        raise ValueError("Queries require parquet/json/jsonl")
    seen = set()
    for q in iterator:
        identifier = source_id(q["id"])
        if identifier in seen or not isinstance(q["query"], str):
            raise ValueError("Duplicate query ID or non-string query")
        seen.add(identifier)
        yield {"id": identifier, "query": q["query"]}


class QueryProjector:
    def __init__(self, analyzer: MedicalAnalyzer, cache_path: Path | None = None):
        self.analyzer = analyzer
        self.cache = {}
        if cache_path:
            if cache_path.stat().st_size > 16 * 1024**2:
                raise ValueError("Translation cache exceeds 16 MiB budget")
            with cache_path.open() as f:
                for line in f:
                    item = json.loads(line)
                    provenance = item.get("provenance", {})
                    if not isinstance(provenance, dict) or not isinstance(item.get("translations"), dict):
                        raise ValueError("Translation cache lacks provenance or translations")
                    validate_provenance(provenance)
                    key = item["query_sha256"]
                    if not isinstance(item.get("source_query"), str) or sha_bytes(item["source_query"].encode()) != key:
                        raise ValueError("Translation cache source/query hash mismatch")
                    if any(not isinstance(v, str) for v in item["translations"].values()):
                        raise ValueError("Translation must be text")
                    if key in self.cache:
                        raise ValueError("Duplicate translation cache query hash")
                    self.cache[key] = item

    def project(self, text: str):
        if not text.strip():
            return [], []
        anchors = self.analyzer.lexicon.anchors(text, "vi")
        cached = self.cache.get(sha_bytes(text.encode()), {})
        translations = cached.get("translations", {})
        runs, warnings = [], []
        numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text))
        translations = {l: v for l, v in translations.items() if numbers <= set(re.findall(r"\d+(?:[.,]\d+)?", v))}
        if len(translations) < len(cached.get("translations", {})):
            warnings.append("translation_number_guard: dropped translation missing source numbers")
        if not all(isinstance(translations.get(l), str) and translations[l].strip() for l in ("en", "zh")):
            warnings.append("full_query_translation_missing: EN/ZH coverage limited to available aliases/anchors/literals")
        for lang in ("vi", "en", "zh"):
            variants = [("original", text)] if lang == "vi" else []
            aliases = self.analyzer.lexicon.aliases(anchors, lang)
            if aliases:
                variants.append(("aliases", "; ".join(aliases)))
            if lang in translations and isinstance(translations[lang], str) and translations[lang].strip():
                variants.append(("translation", translations[lang]))
            for name, variant in variants:
                a = self.analyzer.analyze(variant, lang, index_mode=False).fields
                if a.get("contents"):
                    runs.append((lang, name+"-compound", {"contents": a["contents"], "title": a["contents"]}))
                broad = {"broad": a["broad"]} if a.get("broad") else {}
                if broad:
                    runs.append((lang, name+"-broad", broad))
            if anchors:
                runs.append((lang, "anchors", {"anchors": anchors}))
            exact = exact_tokens(text, lexicon=self.analyzer.lexicon)
            if exact:
                runs.append((lang, "international", {"exact": exact}))
        if any(sum(len(set(t)) for t in fields.values()) > 128 for _, _, fields in runs):
            warnings.append("query_term_budget: channels limited to 128 clauses with per-field allocation")
        return runs, warnings
