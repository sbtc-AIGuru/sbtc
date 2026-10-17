from __future__ import annotations

import importlib.metadata
import json
import os
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import VERSION
from .analyzers import MedicalAnalyzer
from .lexicon import Lexicon
from .models import ANALYZER_PROFILE, INDEX_SCHEMA_VERSION, MANIFEST_FORMAT_VERSION, Analysis, LANGUAGES
from .store import TextStore
from .utils import atomic_json, job_lock, sha_bytes, sha_file, source_id

LANGUAGE_BITS = {"vi": 1, "en": 2, "zh": 4}


def languages(text: str, hints=(), prior="und") -> tuple[str, ...]:
    known = set(hints) & set(LANGUAGES)
    if not known and prior in LANGUAGES:
        known.add(prior)
    if not known:
        if any("\u3400" <= c <= "\u9fff" for c in text):
            known.add("zh")
        elif any(c in "ăâđêôơưĂÂĐÊÔƠƯ" or "\u1ea0" <= c <= "\u1ef9" for c in text):
            known.add("vi")
        else:
            known.update(("vi", "en"))
    return tuple(sorted(known))


def union_body(children: list[dict]) -> str:
    segments, parts, cursor = [], [], -1
    for c in sorted(children, key=lambda x: (x["start_char"], x["end_char"])):
        start, end, text = c["start_char"], c["end_char"], c["chunk_text"]
        if type(start) is not int or type(end) is not int or start < 0 or end < start or len(text) != end-start:
            raise ValueError("Chunk char offsets/length mismatch")
        for left, right, original in reversed(segments):
            if right <= start:
                break
            low, high = max(left, start), min(right, end)
            if low < high and original[low-left:high-left] != text[low-start:high-start]:
                raise ValueError("Overlapping chunks disagree about source text")
        if end > cursor:
            if cursor >= 0 and start > cursor:
                parts.append("\n\n")
            parts.append(text[max(0, cursor-start):])
            segments.append((max(start, cursor), end, text[max(0, cursor-start):]))
            cursor = end
    return "".join(parts)


def title_text(record: dict, children: list[dict]) -> str:
    if not record.get("title_spans"):
        return ""
    span = record["title_spans"][0]
    for child in children:
        if child["start_char"] <= span["start_char"] < span["end_char"] <= child["end_char"]:
            return child["chunk_text"][span["start_char"]-child["start_char"]:span["end_char"]-child["start_char"]]
    return ""


def analysis_fingerprint(lexicon: Lexicon) -> str:
    code = {p.name: sha_file(p) for p in Path(__file__).parent.glob("*.py") if p.name in {"analyzers.py", "lexicon.py", "models.py"}}
    packages = {name: importlib.metadata.version(name) for name in ("pyserini", "jieba", "underthesea", "opencc-python-reimplemented", "pyahocorasick")}
    payload = {"profile": ANALYZER_PROFILE, "index_schema_version": INDEX_SCHEMA_VERSION, "lexicon": lexicon.sha256, "code": code, "packages": packages}
    return sha_bytes(json.dumps(payload, sort_keys=True).encode())


def fingerprint(lexicon: Lexicon) -> str:
    """Backward-compatible name for the analyzer/schema fingerprint."""
    return analysis_fingerprint(lexicon)


def build_policy_fingerprint(policy: dict) -> str:
    encoded = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha_bytes(encoded)


class CorpusPreparer:
    def __init__(self, analyzer: MedicalAnalyzer):
        self.analyzer = analyzer

    def prepare(self, input_dir: Path, output: Path, corpus: Path, *, limit: int | None = None, scope: Path | None = None) -> dict:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        files = sorted(input_dir.resolve().glob("part-*.jsonl"))
        if not files:
            raise ValueError("No input chunk shards")
        analysis_hash = analysis_fingerprint(self.analyzer.lexicon)
        build_policy = {"mode": "bulk", "version": "bulk-indexcollection-v1"}
        spec = {"fingerprint": analysis_hash, "analysis_fingerprint": analysis_hash, "analyzer_profile": ANALYZER_PROFILE, "index_schema_version": INDEX_SCHEMA_VERSION, "build_policy_fingerprint": build_policy_fingerprint(build_policy), "corpus_sha": sha_file(corpus), "scope_sha": sha_file(scope) if scope else None, "limit": limit, "inputs": [{"path": str(p), "sha": sha_file(p)} for p in files]}
        spec_hash = sha_bytes(json.dumps(spec, sort_keys=True).encode())
        output = output.resolve()
        @contextmanager
        def safe_writable_store():
            manifest_path = output / "manifest.json"
            if manifest_path.exists():
                previous = json.loads(manifest_path.read_text())
                if previous.get("spec_hash") != spec_hash or previous.get("analyzer_profile") != ANALYZER_PROFILE:
                    raise RuntimeError("Input/analyzer/lexicon fingerprint changed or snapshot profile is incompatible: use a new run directory")
            elif any(item.name != ".lock" for item in output.iterdir()):
                raise RuntimeError("Refusing a nonempty run directory without a compatible manifest")
            with TextStore(output / "metadata.sqlite", writable=True) as writable:
                yield writable

        with job_lock(output), safe_writable_store() as store:
            manifest_path = output / "manifest.json"
            if manifest_path.exists():
                previous = json.loads(manifest_path.read_text())
                if previous["spec_hash"] != spec_hash:
                    raise RuntimeError("Input/analyzer/lexicon fingerprint changed: use a new run directory")
            else:
                atomic_json(manifest_path, {"version": VERSION, "manifest_format_version": MANIFEST_FORMAT_VERSION, "index_schema_version": INDEX_SCHEMA_VERSION, "analyzer_profile": ANALYZER_PROFILE, "build_mode": "bulk", "build_policy": build_policy, "build_policy_fingerprint": spec["build_policy_fingerprint"], "spec_hash": spec_hash, "spec": spec, "prepared": False, "indexes": {}, "lexicon_metadata": self.analyzer.lexicon.metadata})
            if not store.db.execute("SELECT 1 FROM corpus LIMIT 1").fetchone():
                import pyarrow.parquet as pq
                for batch in pq.ParquetFile(corpus).iter_batches(batch_size=10000, columns=["id", "url"]):
                    store.db.executemany("INSERT INTO corpus VALUES(?,?)", [(source_id(i), u) for i, u in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist())])
                store.db.commit()
            scope_ids = None
            if scope:
                scope_ids = {}
                with scope.open() as f:
                    for line in f:
                        item = json.loads(line)
                        i = source_id(item["id"])
                        if i in scope_ids:
                            raise ValueError("Duplicate ID in source scope")
                        scope_ids[i] = item["url"]
            totals = Counter()
            for sid, source in enumerate(files):
                existing = store.db.execute("SELECT counters,stages FROM tasks WHERE source=?", (sid,)).fetchone()
                if existing:
                    for item in json.loads(existing["stages"]):
                        if sha_file(Path(item["path"])) != item["sha"]:
                            raise RuntimeError("Prepared shard changed")
                    totals.update(json.loads(existing["counters"]))
                    if limit and totals["records"] >= limit:
                        break
                    continue
                if limit and totals["records"] >= limit:
                    break
                stat = source.stat()
                counts, stages = Counter(), []
                temporary_paths = []
                with store.db, ExitStack() as stack:
                    store.db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?)", (sid, str(source), spec["inputs"][sid]["sha"], stat.st_size, stat.st_mtime_ns))
                    writers = {}
                    for granularity in ("documents", "chunks"):
                        for lang in LANGUAGES:
                            final = output / "prepared" / granularity / lang / source.name
                            final.parent.mkdir(parents=True, exist_ok=True)
                            temp = final.with_suffix(".jsonl.tmp")
                            temporary_paths.append((temp, final))
                            writers[(granularity, lang)] = stack.enter_context(temp.open("w", encoding="utf-8"))
                    with source.open("rb") as f:
                        while True:
                            offset = f.tell()
                            payload = f.readline(64 * 1024**2 + 1)
                            if len(payload) > 64 * 1024**2:
                                raise ValueError(f"Record exceeds 64 MiB safety budget: {source}:{offset}")
                            if not payload:
                                break
                            record = json.loads(payload)
                            doc = source_id(record["doc_id"])
                            actual = store.db.execute("SELECT url FROM corpus WHERE id=?", (doc,)).fetchone()
                            if actual is None or actual[0] != record["url"] or (scope_ids is not None and scope_ids.get(doc) != record["url"]):
                                raise ValueError(f"Source membership/URL mismatch: {doc}")
                            store.db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", (doc, record["url"], sid, offset, len(payload), sha_bytes(payload)))
                            counts["records"] += 1
                            if record.get("status") != "ok":
                                counts["skipped_status"] += 1
                            else:
                                children = []
                                for c in record["children"]:
                                    if source_id(c["doc_id"]) != doc or type(c["chunk_order"]) is not int or c["chunk_order"] < 0 or not isinstance(c["chunk_text"], str) or not isinstance(c["chunk_id"], str) or not c["chunk_id"]:
                                        raise ValueError("Invalid child identity/schema")
                                    if c.get("retrieval_eligible", True) and c["chunk_text"].strip():
                                        children.append(c)
                                    else:
                                        counts["skipped_child"] += 1
                                body = union_body(children)
                                title = title_text(record, children)
                                for child in children:
                                    store.db.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", (child["chunk_id"], doc, child["chunk_order"], child["start_char"], child["end_char"], sha_bytes(child["chunk_text"].encode())))
                                    counts["chunks"] += 1
                                    counts["oversized"] += bool(child.get("oversized_reason"))
                                    route_mask = self._write(writers, "chunks", child["chunk_id"], child["chunk_text"], title, languages(child["chunk_text"], child.get("content_languages", []), record.get("source_language")), counts)
                                    store.db.execute("INSERT INTO chunk_routes VALUES(?,?)", (child["chunk_id"], route_mask))
                                if body.strip():
                                    counts["ok_documents"] += 1
                                    route_mask = self._write(writers, "documents", str(doc), body, title, languages(body, [x for c in children for x in c.get("content_languages", [])], record.get("source_language")), counts)
                                    store.db.execute("INSERT INTO document_routes VALUES(?,?)", (doc, route_mask))
                            if limit and totals["records"] + counts["records"] >= limit:
                                break
                    for writer in writers.values():
                        writer.flush()
                        os.fsync(writer.fileno())
                    for temp, final in temporary_paths:
                        os.replace(temp, final)
                        stages.append({"path": str(final), "sha": sha_file(final)})
                    store.db.execute("INSERT INTO tasks VALUES(?,?,?)", (sid, json.dumps(dict(counts)), json.dumps(stages)))
                totals.update(counts)
                print(json.dumps({"shard": source.name, "counters": dict(totals)}, ensure_ascii=False), flush=True)
            manifest = json.loads(manifest_path.read_text())
            manifest.update(prepared=True, counts=dict(totals))
            atomic_json(manifest_path, manifest)
            return manifest

    def _write(self, writers, granularity, identifier, text, title, language_views, counts):
        route_mask = 0
        for lang in language_views:
            analysis = self.analyzer.analyze(text, lang, index_mode=True)
            fields = dict(analysis.fields)
            fields["title"] = self.analyzer.analyze(title, lang, index_mode=True).fields["contents"] if title else ()
            if not fields["contents"]:
                fields["contents"] = fields.get("broad", ()) or fields.get("exact", ())
            if not fields["contents"]:
                counts["empty_view"] += 1
                continue
            writers[(granularity, lang)].write(json.dumps(Analysis(fields).record(identifier), ensure_ascii=False) + "\n")
            counts[f"views_{granularity}_{lang}"] += 1
            route_mask |= LANGUAGE_BITS[lang]
        return route_mask
