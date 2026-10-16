"""Crash-recoverable single-batch staging and incremental Lucene indexing."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import resource
import shutil
import sqlite3
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from . import VERSION
from .analyzers import MedicalAnalyzer
from .corpus import (
    LANGUAGE_BITS,
    analysis_fingerprint,
    build_policy_fingerprint,
    languages,
    title_text,
    union_body,
)
from .index_writer import DirectLucenePartition
from .lexicon import Lexicon
from .models import ANALYZER_PROFILE, FIELDS, INDEX_SCHEMA_VERSION, MANIFEST_FORMAT_VERSION, LANGUAGES
from .runtime import configure_java
from .store import SCHEMA
from .utils import atomic_json, fsync_directory, job_lock, sha_bytes, sha_file, source_id


ROLLING_SCHEMA = """
CREATE TABLE IF NOT EXISTS record_state(
    doc_id INTEGER PRIMARY KEY REFERENCES documents(id),
    source_index INTEGER NOT NULL,
    record_offset INTEGER NOT NULL,
    status TEXT NOT NULL,
    skipped_child INTEGER NOT NULL,
    oversized INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rolling_progress(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    cursor TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rolling_batches(
    batch_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL UNIQUE,
    start_cursor TEXT NOT NULL,
    end_cursor TEXT,
    status TEXT NOT NULL,
    stage_path TEXT NOT NULL,
    stage_bytes INTEGER NOT NULL DEFAULT 0,
    stage_sha256 TEXT,
    event_count INTEGER NOT NULL DEFAULT 0,
    event_digest TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rolling_receipts(
    batch_id TEXT NOT NULL REFERENCES rolling_batches(batch_id),
    partition_name TEXT NOT NULL,
    stage_sha256 TEXT NOT NULL,
    event_digest TEXT NOT NULL,
    live_documents INTEGER NOT NULL,
    commit_data TEXT NOT NULL,
    PRIMARY KEY(batch_id, partition_name)
);
"""

MAX_SOURCE_LINE_BYTES = 64 * 1024**2
MAX_METADATA_ONLY_RECORDS = 10_000


def _cursor(source_index: int, record_offset: int = 0, next_event_ordinal: int = 0) -> dict[str, int]:
    return {
        "source_index": source_index,
        "record_offset": record_offset,
        "next_event_ordinal": next_event_ordinal,
    }


def _cursor_load(encoded: str) -> dict[str, int]:
    value = json.loads(encoded)
    keys = ("source_index", "record_offset", "next_event_ordinal")
    if not isinstance(value, dict) or any(type(value.get(key)) is not int or value[key] < 0 for key in keys):
        raise RuntimeError("Rolling cursor is malformed")
    return {key: value[key] for key in keys}


def _json_string_content(value: str):
    """Yield UTF-8 JSON string content in bounded pieces without joining a field."""
    escapes = {"\"": b'\\"', "\\": b"\\\\", "\b": b"\\b", "\f": b"\\f", "\n": b"\\n", "\r": b"\\r", "\t": b"\\t"}
    buffer = bytearray()
    for char in value:
        codepoint = ord(char)
        if char in escapes:
            piece = escapes[char]
        elif codepoint < 0x20 or 0xD800 <= codepoint <= 0xDFFF:
            piece = f"\\u{codepoint:04x}".encode("ascii")
        else:
            piece = char.encode("utf-8")
        if buffer and len(buffer) + len(piece) > 8192:
            yield bytes(buffer)
            buffer.clear()
        buffer.extend(piece)
    if buffer:
        yield bytes(buffer)


def _json_string(value: str):
    yield b'"'
    yield from _json_string_content(value)
    yield b'"'


def _prepared_jsonl(identifier: str, fields: dict[str, tuple[str, ...]]):
    """Serialize the index record a field/token at a time under a small buffer."""
    yield b'{"id":'
    yield from _json_string(identifier)
    for field in FIELDS:
        yield b","
        yield from _json_string(field)
        yield b':"'
        first = True
        for token in fields.get(field, ()):
            if not isinstance(token, str) or any(char.isspace() for char in token):
                raise ValueError(f"Prepared field {field!r} contains an invalid token")
            if not first:
                yield b" "
            yield from _json_string_content(token)
            first = False
        yield b'"'
    yield b"}\n"


def _prepared_jsonl_size(identifier: str, fields: dict[str, tuple[str, ...]]) -> int:
    return sum(len(part) for part in _prepared_jsonl(identifier, fields))


def _tree_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_symlink():
            raise RuntimeError(f"Symlink is not allowed inside rolling staging: {entry}")
        if entry.is_file():
            total += entry.stat().st_size
    return total


class RollingIndexer:
    """Index BM25 records from source shards while bounding temporary JSONL stage."""

    def __init__(
        self,
        analyzer: MedicalAnalyzer,
        *,
        staging_target_bytes: int = 250_000_000,
        staging_max_bytes: int = 300_000_000,
        control_reserve_bytes: int = 1_000_000,
        writer_ram_buffer_mib: int = 16,
        disk_reserve_bytes: int = 2_000_000_000,
        limit: int | None = None,
    ):
        if staging_target_bytes <= 0 or staging_max_bytes <= 0 or control_reserve_bytes < 512:
            raise ValueError("Staging sizes and control reserve must be positive")
        if staging_target_bytes > staging_max_bytes - control_reserve_bytes:
            raise ValueError("Staging target must leave the full control reserve below the hard cap")
        if writer_ram_buffer_mib <= 0 or disk_reserve_bytes < 0:
            raise ValueError("Writer buffer must be positive and disk reserve cannot be negative")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        self.analyzer = analyzer
        self.staging_target_bytes = staging_target_bytes
        self.staging_max_bytes = staging_max_bytes
        self.control_reserve_bytes = control_reserve_bytes
        self.writer_ram_buffer_mib = writer_ram_buffer_mib
        self.disk_reserve_bytes = disk_reserve_bytes
        self.limit = limit

    def run(self, input_dir: Path, output: Path, corpus: Path, *, scope: Path | None = None) -> dict:
        configure_java()
        files = sorted(input_dir.resolve().glob("part-*.jsonl"))
        if not files:
            raise ValueError("No input chunk shards")
        output = output.resolve()
        if any(output == source or output in source.parents for source in files):
            raise RuntimeError("Do not write rolling artifacts inside source chunk directory")
        policy = {
            "mode": "rolling",
            "version": "rolling-indexwriter-v1",
            "staging_target_bytes": self.staging_target_bytes,
            "staging_max_bytes": self.staging_max_bytes,
            "control_reserve_bytes": self.control_reserve_bytes,
            "writer_ram_buffer_mib": self.writer_ram_buffer_mib,
            "merge_scheduler": "serial",
            "disk_reserve_bytes": self.disk_reserve_bytes,
            "limit": self.limit,
        }
        import pyserini
        jars = sorted((Path(pyserini.__file__).parent / "resources/jars").glob("anserini-*-fatjar.jar"))
        if len(jars) != 1:
            raise RuntimeError("Rolling index requires exactly one pinned Anserini fatjar")
        implementation = Path(__file__).parent
        policy["implementation_sha256"] = {
            name: sha_file(implementation / name)
            for name in ("rolling.py", "index_writer.py", "corpus.py", "store.py", "models.py", "runtime.py", "utils.py")
        }
        policy["runtime"] = {
            "pyserini": importlib.metadata.version("pyserini"),
            "pyjnius": importlib.metadata.version("pyjnius"),
            "anserini_fatjar_sha256": sha_file(jars[0]),
            "java_home": os.environ.get("JAVA_HOME"),
            "java_tool_options": os.environ.get("JAVA_TOOL_OPTIONS", "-Xmx2g"),
        }
        analysis_hash = analysis_fingerprint(self.analyzer.lexicon)
        spec = {
            "fingerprint": analysis_hash,
            "analysis_fingerprint": analysis_hash,
            "analyzer_profile": ANALYZER_PROFILE,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "corpus_sha": sha_file(corpus),
            "scope_sha": sha_file(scope) if scope else None,
            "limit": self.limit,
            "inputs": [{"path": str(path), "sha": sha_file(path)} for path in files],
        }
        policy_hash = build_policy_fingerprint(policy)
        spec["build_policy_fingerprint"] = policy_hash
        spec_hash = sha_bytes(json.dumps(spec, sort_keys=True).encode())
        run_id = uuid.uuid4().hex

        with job_lock(output):
            manifest = self._initialize_or_resume(output, run_id, spec, spec_hash, policy, policy_hash)
            if manifest.get("status") == "READY":
                return manifest
            with self._open_registry(output) as db:
                self._load_corpus(db, corpus)
                scope_ids = self._load_scope(scope)
                self._register_sources(db, files, spec["inputs"])

                published = output / "indexes"
                building = output / "indexes.building"
                if published.exists() and not building.exists():
                    self._finalize_published(output, manifest, published)
                    return json.loads((output / "manifest.json").read_text())

                self._ensure_partitions(output, manifest)
                writers = self._open_writers(output, manifest)
                try:
                    self._recover_active_batch(output, db, writers)
                    while True:
                        pending = db.execute(
                            "SELECT * FROM rolling_batches WHERE status IN ('PREPARING','PREPARED','COMMITTING','COMMITTED') ORDER BY sequence DESC LIMIT 1"
                        ).fetchone()
                        if pending:
                            if pending["status"] == "PREPARING":
                                self._discard_preparing(output, db, pending)
                                continue
                            if pending["status"] in {"PREPARED", "COMMITTING"}:
                                self._commit_batch(output, db, manifest, writers, pending)
                            self._cleanup_batch(output, db, pending["batch_id"])
                            continue
                        progress = db.execute("SELECT cursor,status FROM rolling_progress WHERE singleton=1").fetchone()
                        if progress["status"] == "COMPLETE":
                            break
                        if self._build_one_batch(output, db, manifest, files, scope_ids):
                            break
                    self._verify_final_indexes(output, db, manifest)
                finally:
                    self._close_writers(writers)

                self._publish(output, db, manifest)
                return json.loads((output / "manifest.json").read_text())

    def _initialize_or_resume(self, root: Path, new_run_id: str, spec: dict, spec_hash: str, policy: dict, policy_hash: str) -> dict:
        manifest_path = root / "manifest.json"
        owner_path = root / ".rolling-owner.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("build_mode") != "rolling" or manifest.get("spec_hash") != spec_hash:
                raise RuntimeError("Rolling run configuration/source fingerprint changed; use a new run directory")
            if manifest.get("build_policy_fingerprint") != policy_hash:
                raise RuntimeError("Rolling build policy changed; resume requires the original byte and writer settings")
            if manifest.get("analyzer_profile") != ANALYZER_PROFILE or manifest.get("index_schema_version") != INDEX_SCHEMA_VERSION:
                raise RuntimeError("Rolling run schema/profile is incompatible")
            expected_owner = {"run_id": manifest.get("run_id"), "spec_hash": spec_hash}
            if not owner_path.is_file() or json.loads(owner_path.read_text()) != expected_owner:
                raise RuntimeError("Rolling run ownership marker is missing or mismatched")
            return manifest
        if any(item.name != ".lock" for item in root.iterdir()):
            raise RuntimeError("Refusing to initialize a nonempty run directory without a rolling manifest")
        manifest = {
            "version": VERSION,
            "manifest_format_version": MANIFEST_FORMAT_VERSION,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "analyzer_profile": ANALYZER_PROFILE,
            "build_mode": "rolling",
            "build_policy": policy,
            "build_policy_fingerprint": policy_hash,
            "run_id": new_run_id,
            "spec_hash": spec_hash,
            "spec": spec,
            "status": "INITIALIZING",
            "prepared": False,
            "indexes": {},
            "counts": {},
            "lexicon_metadata": self.analyzer.lexicon.metadata,
        }
        atomic_json(owner_path, {"run_id": new_run_id, "spec_hash": spec_hash})
        atomic_json(manifest_path, manifest)
        atomic_json(root / "staging" / ".owner.json", {"run_id": new_run_id, "spec_hash": spec_hash})
        atomic_json(root / "indexes.building" / ".owner.json", {"run_id": new_run_id, "spec_hash": spec_hash})
        manifest["status"] = "BUILDING"
        atomic_json(manifest_path, manifest)
        return manifest

    def _open_registry(self, root: Path):
        path = root / "metadata.sqlite"
        db = sqlite3.connect(path, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(SCHEMA)
        db.executescript(ROLLING_SCHEMA)
        db.execute(
            "INSERT OR IGNORE INTO rolling_progress(singleton,cursor,status) VALUES(1,?,'RUNNING')",
            (json.dumps(_cursor(0)),),
        )
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return _RegistryContext(db)

    def _load_corpus(self, db: sqlite3.Connection, corpus: Path) -> None:
        import pyarrow.parquet as pq

        db.execute("CREATE TEMP TABLE IF NOT EXISTS incoming_corpus(id INTEGER PRIMARY KEY,url TEXT NOT NULL)")
        for batch in pq.ParquetFile(corpus).iter_batches(batch_size=10_000, columns=["id", "url"]):
            rows = [(source_id(identifier), url) for identifier, url in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist())]
            db.execute("DELETE FROM incoming_corpus")
            db.executemany("INSERT INTO incoming_corpus VALUES(?,?)", rows)
            mismatch = db.execute(
                "SELECT incoming_corpus.id FROM incoming_corpus JOIN corpus USING(id) WHERE incoming_corpus.url != corpus.url LIMIT 1"
            ).fetchone()
            if mismatch:
                raise ValueError(f"Corpus URL changed for document ID {mismatch[0]}")
            db.execute("INSERT OR IGNORE INTO corpus SELECT id,url FROM incoming_corpus")
        db.execute("DROP TABLE incoming_corpus")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @staticmethod
    def _load_scope(scope: Path | None) -> dict[int, str] | None:
        if scope is None:
            return None
        result = {}
        with scope.open(encoding="utf-8") as source:
            for line in source:
                item = json.loads(line)
                identifier = source_id(item["id"])
                if identifier in result:
                    raise ValueError("Duplicate ID in source scope")
                result[identifier] = item["url"]
        return result

    @staticmethod
    def _register_sources(db: sqlite3.Connection, files: list[Path], inputs: list[dict]) -> None:
        for index, source in enumerate(files):
            stat = source.stat()
            if sha_file(source) != inputs[index]["sha"]:
                raise RuntimeError(f"SourceChanged while initializing rolling run: {source}")
            record = (index, str(source), inputs[index]["sha"], stat.st_size, stat.st_mtime_ns)
            existing = db.execute("SELECT id,path,sha,bytes,mtime FROM sources WHERE id=?", (index,)).fetchone()
            if existing:
                if tuple(existing) != record:
                    raise RuntimeError(f"SourceChanged: {source}")
            else:
                db.execute("INSERT INTO sources VALUES(?,?,?,?,?)", record)

    def _ensure_partitions(self, root: Path, manifest: dict) -> None:
        building = root / "indexes.building"
        owner = json.loads((building / ".owner.json").read_text())
        if owner != {"run_id": manifest["run_id"], "spec_hash": manifest["spec_hash"]}:
            raise RuntimeError("Lucene build directory ownership marker is mismatched")
        any_committed = self._has_committed_batches(root)
        for granularity in ("documents", "chunks"):
            for lang in LANGUAGES:
                partition = f"{granularity}/{lang}"
                path = building / granularity / lang
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    try:
                        receipt = DirectLucenePartition.read_committed(path)
                    except Exception as error:
                        if any_committed:
                            raise RuntimeError(f"Committed rolling partition is unreadable: {partition}") from error
                        self._remove_owned_partition(building, path)
                    else:
                        self._validate_commit_identity(receipt["user_data"], manifest, partition)
                        continue
                if any_committed:
                    raise RuntimeError(f"Partition is missing after rolling commits began: {partition}")
                with DirectLucenePartition(
                    path,
                    run_id=manifest["run_id"],
                    spec_hash=manifest["spec_hash"],
                    partition=partition,
                    mode="create",
                    ram_buffer_mib=self.writer_ram_buffer_mib,
                ):
                    pass
        manifest["status"] = "BUILDING"
        atomic_json(root / "manifest.json", manifest)

    @staticmethod
    def _remove_owned_partition(building: Path, path: Path) -> None:
        if path.is_symlink() or building.resolve() not in path.resolve().parents:
            raise RuntimeError(f"Refusing to remove path outside owned Lucene build tree: {path}")
        if path.exists():
            shutil.rmtree(path)

    @staticmethod
    def _has_committed_batches(root: Path) -> bool:
        with sqlite3.connect(f"file:{root / 'metadata.sqlite'}?mode=ro", uri=True) as db:
            try:
                return db.execute("SELECT 1 FROM rolling_batches WHERE status IN ('COMMITTED','CLEANED') LIMIT 1").fetchone() is not None
            except sqlite3.OperationalError:
                return False

    def _open_writers(self, root: Path, manifest: dict) -> dict[str, DirectLucenePartition]:
        writers = {}
        try:
            for granularity in ("documents", "chunks"):
                for lang in LANGUAGES:
                    partition = f"{granularity}/{lang}"
                    writers[partition] = DirectLucenePartition(
                        root / "indexes.building" / granularity / lang,
                        run_id=manifest["run_id"],
                        spec_hash=manifest["spec_hash"],
                        partition=partition,
                        mode="append",
                        ram_buffer_mib=self.writer_ram_buffer_mib,
                    )
        except BaseException:
            self._close_writers(writers)
            raise
        return writers

    @staticmethod
    def _close_writers(writers: dict[str, DirectLucenePartition]) -> None:
        error = None
        for writer in writers.values():
            try:
                writer.close()
            except BaseException as close_error:
                error = error or close_error
        if error:
            raise error

    def _build_one_batch(self, root: Path, db: sqlite3.Connection, manifest: dict, files: list[Path], scope_ids: dict[int, str] | None) -> bool:
        row = db.execute("SELECT cursor,status FROM rolling_progress WHERE singleton=1").fetchone()
        current = _cursor_load(row["cursor"])
        if row["status"] == "COMPLETE":
            return True
        active = None
        stage = None
        stage_stack = None
        handles = None
        payload_bytes = 0
        event_count = 0
        event_digest = hashlib.sha256()
        partition_counts = {f"{g}/{lang}": 0 for g in ("documents", "chunks") for lang in LANGUAGES}
        metadata_only_since_flush = 0
        started = time.monotonic()

        try:
            if self.limit is not None and current["next_event_ordinal"] == 0 and db.execute("SELECT count(*) FROM documents").fetchone()[0] >= self.limit:
                self._save_progress(db, _cursor(len(files)), "COMPLETE")
                return True
            self._ensure_disk_reserve(root, self.staging_max_bytes)
            while current["source_index"] < len(files):
                source_index = current["source_index"]
                source = files[source_index]
                with source.open("rb") as stream:
                    stream.seek(current["record_offset"])
                    while True:
                        record_offset = stream.tell()
                        payload = stream.readline(MAX_SOURCE_LINE_BYTES + 1)
                        if len(payload) > MAX_SOURCE_LINE_BYTES:
                            raise ValueError(f"Record exceeds 64 MiB safety budget: {source}:{record_offset}")
                        if not payload:
                            expected_source = db.execute("SELECT sha FROM sources WHERE id=?", (source_index,)).fetchone()
                            if expected_source is None or sha_file(source) != expected_source[0]:
                                raise RuntimeError(f"SourceChanged while reading rolling shard: {source}")
                            current = _cursor(source_index + 1)
                            if active is None:
                                self._save_progress(db, current, "RUNNING")
                            if active is not None:
                                break
                            break
                        record_end = stream.tell()
                        record = json.loads(payload)
                        self._begin_record_transaction(db, active)
                        children, body, title = self._register_record(
                            db, source_index, record_offset, payload, record, source, scope_ids
                        )
                        record_events = self._iter_views(record, children, body, title)
                        event_ordinal = 0
                        should_seal = False
                        consumed_any = False
                        for event in record_events:
                            if event_ordinal < current["next_event_ordinal"]:
                                event_ordinal += 1
                                continue
                            event_size = _prepared_jsonl_size(event["identifier"], event["fields"])
                            if event_size + self.control_reserve_bytes > self.staging_max_bytes:
                                raise RuntimeError(
                                    "PreparedRecordExceedsBudget: "
                                    f"{event['granularity']}:{event['identifier']}:{event['language']} "
                                    f"serializes to {event_size} bytes; hard cap is {self.staging_max_bytes}"
                                )
                            if active is not None and payload_bytes and (
                                payload_bytes + event_size > self.staging_target_bytes
                                or payload_bytes + event_size + self.control_reserve_bytes > self.staging_max_bytes
                            ):
                                current = _cursor(source_index, record_offset, event_ordinal)
                                should_seal = True
                                break
                            if active is None:
                                active, stage, stage_stack, handles = self._start_batch(root, db, current)
                            if payload_bytes + event_size + self.control_reserve_bytes > self.staging_max_bytes:
                                raise RuntimeError("Rolling staging hard byte cap would be exceeded")
                            self._ensure_disk_reserve(root, event_size)
                            partition = f"{event['granularity']}/{event['language']}"
                            event_digest.update(partition.encode("utf-8") + b"\0")
                            for part in _prepared_jsonl(event["identifier"], event["fields"]):
                                handles[partition].write(part)
                                event_digest.update(part)
                            payload_bytes += event_size
                            event_count += 1
                            partition_counts[partition] += 1
                            self._add_route(db, event["granularity"], event["identifier"], event["language"])
                            consumed_any = True
                            event_ordinal += 1
                            current = _cursor(source_index, record_offset, event_ordinal)
                            if payload_bytes >= self.staging_target_bytes:
                                should_seal = True
                                break
                        if should_seal:
                            self._seal_batch(
                                root, db, active, stage, handles, current, payload_bytes, event_count,
                                event_digest.hexdigest(), partition_counts, started,
                            )
                            return False
                        current = _cursor(source_index, record_end, 0)
                        if active is None:
                            self._save_progress(db, current, "RUNNING")
                            metadata_only_since_flush += 1
                        if active is not None and not consumed_any:
                            metadata_only_since_flush += 1
                        if metadata_only_since_flush >= MAX_METADATA_ONLY_RECORDS:
                            if active is not None:
                                self._seal_batch(
                                    root, db, active, stage, handles, current, payload_bytes, event_count,
                                    event_digest.hexdigest(), partition_counts, started,
                                )
                                return False
                            self._save_progress(db, current, "RUNNING")
                            metadata_only_since_flush = 0
                        if self.limit is not None and db.execute("SELECT count(*) FROM documents").fetchone()[0] >= self.limit:
                            current = _cursor(len(files))
                            if active is not None:
                                self._seal_batch(
                                    root, db, active, stage, handles, current, payload_bytes, event_count,
                                    event_digest.hexdigest(), partition_counts, started,
                                )
                                return False
                            self._save_progress(db, current, "COMPLETE")
                            return True
                    if current["source_index"] > source_index:
                        continue
                    if active is not None:
                        continue
            current = _cursor(len(files))
            if active is not None:
                self._seal_batch(
                    root, db, active, stage, handles, current, payload_bytes, event_count,
                    event_digest.hexdigest(), partition_counts, started,
                )
                return False
            self._save_progress(db, current, "COMPLETE")
            return True
        except BaseException:
            if db.in_transaction:
                db.rollback()
            if handles:
                for handle in handles.values():
                    try:
                        handle.close()
                    except OSError:
                        pass
            if stage_stack:
                stage_stack.close()
            raise

    @staticmethod
    def _begin_record_transaction(db: sqlite3.Connection, active) -> None:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")

    def _register_record(self, db: sqlite3.Connection, source_index: int, offset: int, payload: bytes, record: dict, source: Path, scope_ids: dict[int, str] | None):
        doc_id = source_id(record["doc_id"])
        actual = db.execute("SELECT url FROM corpus WHERE id=?", (doc_id,)).fetchone()
        if actual is None or actual[0] != record["url"] or (scope_ids is not None and scope_ids.get(doc_id) != record["url"]):
            raise ValueError(f"Source membership/URL mismatch: {doc_id}")
        source_row = db.execute("SELECT path,sha,bytes,mtime FROM sources WHERE id=?", (source_index,)).fetchone()
        stat = source.stat()
        if source_row is None or source_row["path"] != str(source) or stat.st_size != source_row["bytes"] or stat.st_mtime_ns != source_row["mtime"]:
            raise RuntimeError(f"SourceChanged: {source}")
        values = (doc_id, record["url"], source_index, offset, len(payload), sha_bytes(payload))
        existing = db.execute("SELECT id,url,source,offset,bytes,sha FROM documents WHERE id=?", (doc_id,)).fetchone()
        if existing:
            if tuple(existing) != values:
                raise ValueError(f"Duplicate document ID points to different source record: {doc_id}")
        else:
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", values)

        status = str(record.get("status", ""))
        children = []
        skipped = 0
        oversized = 0
        if status == "ok":
            for child in record["children"]:
                if source_id(child["doc_id"]) != doc_id or type(child["chunk_order"]) is not int or child["chunk_order"] < 0 or not isinstance(child["chunk_text"], str) or not isinstance(child["chunk_id"], str) or not child["chunk_id"]:
                    raise ValueError("Invalid child identity/schema")
                if child.get("retrieval_eligible", True) and child["chunk_text"].strip():
                    children.append(child)
                    oversized += bool(child.get("oversized_reason"))
                else:
                    skipped += 1
            body = union_body(children)
            title = title_text(record, children)
        else:
            body, title = "", ""

        record_state = (doc_id, source_index, offset, status, skipped, oversized)
        old_state = db.execute("SELECT doc_id,source_index,record_offset,status,skipped_child,oversized FROM record_state WHERE doc_id=?", (doc_id,)).fetchone()
        if old_state:
            if tuple(old_state) != record_state:
                raise ValueError(f"Document record changed during rolling replay: {doc_id}")
        else:
            db.execute("INSERT INTO record_state VALUES(?,?,?,?,?,?)", record_state)
        if record_state:
            db.execute("INSERT OR IGNORE INTO document_routes VALUES(?,0)", (doc_id,))

        for child in children:
            metadata = (child["chunk_id"], doc_id, child["chunk_order"], child["start_char"], child["end_char"], sha_bytes(child["chunk_text"].encode("utf-8")))
            old_chunk = db.execute("SELECT id,doc,ord,start,end,sha FROM chunks WHERE id=?", (child["chunk_id"],)).fetchone()
            if old_chunk:
                if tuple(old_chunk) != metadata:
                    raise ValueError(f"Chunk ID points to conflicting original text/parent: {child['chunk_id']}")
            else:
                db.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", metadata)
            db.execute("INSERT OR IGNORE INTO chunk_routes VALUES(?,0)", (child["chunk_id"],))
        return children, body, title

    def _iter_views(self, record: dict, children: list[dict], body: str, title: str):
        if record.get("status") != "ok":
            return
        for child in children:
            lang_views = languages(child["chunk_text"], child.get("content_languages", []), record.get("source_language", "und"))
            for lang in lang_views:
                event = self._analyze_view("chunks", child["chunk_id"], child["chunk_text"], title, lang)
                if event is not None:
                    yield event
        if body.strip():
            hints = [language for child in children for language in child.get("content_languages", [])]
            for lang in languages(body, hints, record.get("source_language", "und")):
                event = self._analyze_view("documents", str(record["doc_id"]), body, title, lang)
                if event is not None:
                    yield event

    def _analyze_view(self, granularity: str, identifier: str, text: str, title: str, language: str):
        analysis = self.analyzer.analyze(text, language, index_mode=True)
        fields = dict(analysis.fields)
        fields["title"] = self.analyzer.analyze(title, language, index_mode=True).fields["contents"] if title else ()
        if not fields["contents"]:
            fields["contents"] = fields.get("broad", ()) or fields.get("exact", ())
        if not fields["contents"]:
            return None
        return {"granularity": granularity, "identifier": identifier, "language": language, "fields": fields}

    def _start_batch(self, root: Path, db: sqlite3.Connection, start_cursor: dict):
        latest = db.execute("SELECT coalesce(max(sequence),0)+1 FROM rolling_batches").fetchone()[0]
        batch_id = f"batch-{latest:08d}"
        stage_root = root / "staging"
        stage = stage_root / batch_id
        if stage.exists() or stage.is_symlink():
            raise RuntimeError(f"Unexpected staging path already exists: {stage}")
        stage.mkdir()
        atomic_json(stage / "owner.json", {"run_id": json.loads((root / ".rolling-owner.json").read_text())["run_id"], "batch_id": batch_id})
        stage_stack = ExitStack()
        handles = {}
        try:
            for granularity in ("documents", "chunks"):
                for lang in LANGUAGES:
                    partition = f"{granularity}/{lang}"
                    handles[partition] = stage_stack.enter_context((stage / f"{granularity}-{lang}.jsonl").open("wb"))
            db.execute(
                "INSERT INTO rolling_batches(batch_id,sequence,start_cursor,status,stage_path,created_at) VALUES(?,?,?,'PREPARING',?,?)",
                (batch_id, latest, json.dumps(start_cursor, sort_keys=True), str(stage.relative_to(root)), time.time()),
            )
            return batch_id, stage, stage_stack, handles
        except BaseException:
            stage_stack.close()
            raise

    def _seal_batch(self, root: Path, db: sqlite3.Connection, batch_id: str, stage: Path, handles: dict, end_cursor: dict, payload_bytes: int, event_count: int, event_digest: str, partition_counts: dict[str, int], started: float) -> None:
        for handle in handles.values():
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
        fsync_directory(stage)
        partitions = {}
        for partition, count in partition_counts.items():
            granularity, lang = partition.split("/")
            path = stage / f"{granularity}-{lang}.jsonl"
            partitions[partition] = {"file": path.name, "bytes": path.stat().st_size, "sha256": sha_file(path), "records": count}
        batch_identity = {
            "run_id": json.loads((root / ".rolling-owner.json").read_text())["run_id"],
            "batch_id": batch_id,
            "start_cursor": _cursor_load(db.execute("SELECT start_cursor FROM rolling_batches WHERE batch_id=?", (batch_id,)).fetchone()[0]),
            "end_cursor": end_cursor,
            "partitions": {key: value["sha256"] for key, value in partitions.items()},
            "event_count": event_count,
            "event_digest": event_digest,
        }
        stage_sha = sha_bytes(json.dumps(batch_identity, sort_keys=True, separators=(",", ":")).encode())
        control = {**batch_identity, "partitions": partitions, "stage_sha256": stage_sha, "payload_bytes": payload_bytes}
        atomic_json(stage / "batch.json", control)
        stage_bytes = _tree_bytes(root / "staging")
        if stage_bytes > self.staging_max_bytes:
            raise RuntimeError(f"Rolling staging hard cap exceeded at seal: {stage_bytes} > {self.staging_max_bytes}")
        db.execute(
            "UPDATE rolling_batches SET end_cursor=?,status='PREPARED',stage_bytes=?,stage_sha256=?,event_count=?,event_digest=? WHERE batch_id=? AND status='PREPARING'",
            (json.dumps(end_cursor, sort_keys=True), stage_bytes, stage_sha, event_count, event_digest, batch_id),
        )
        db.commit()
        self._append_metric(root, {
            "batch_id": batch_id,
            "status": "PREPARED",
            "stage_bytes": stage_bytes,
            "payload_bytes": payload_bytes,
            "events": event_count,
            "seconds": round(time.monotonic() - started, 3),
            "free_bytes": shutil.disk_usage(root).free,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        })

    def _add_route(self, db: sqlite3.Connection, granularity: str, identifier: str, language: str) -> None:
        table, key = ("document_routes", "doc_id") if granularity == "documents" else ("chunk_routes", "chunk_id")
        bit = LANGUAGE_BITS[language]
        db.execute(
            f"INSERT INTO {table}({key},language_mask) VALUES(?,?) ON CONFLICT({key}) DO UPDATE SET language_mask=language_mask | excluded.language_mask",
            (int(identifier) if granularity == "documents" else identifier, bit),
        )

    def _save_progress(self, db: sqlite3.Connection, cursor: dict, status: str) -> None:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE rolling_progress SET cursor=?,status=? WHERE singleton=1", (json.dumps(cursor, sort_keys=True), status))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _ensure_disk_reserve(self, root: Path, additional_bytes: int) -> None:
        free = shutil.disk_usage(root).free
        required = self.disk_reserve_bytes + additional_bytes
        if free < required:
            raise OSError(f"Rolling disk reserve would be breached: free={free}, required={required}")

    def _recover_active_batch(self, root: Path, db: sqlite3.Connection, writers: dict[str, DirectLucenePartition]) -> None:
        pending = db.execute(
            "SELECT * FROM rolling_batches WHERE status IN ('PREPARING','PREPARED','COMMITTING','COMMITTED') ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if not pending:
            cleaned = db.execute("SELECT batch_id,stage_path FROM rolling_batches WHERE status='CLEANED' ORDER BY sequence DESC").fetchall()
            for row in cleaned:
                stage = root / row["stage_path"]
                if stage.exists():
                    self._cleanup_batch(root, db, row["batch_id"])
                    return
            self._remove_orphan_stage(root, db)
            return
        if pending["status"] == "PREPARING":
            self._discard_preparing(root, db, pending)
            return
        if pending["status"] in {"PREPARED", "COMMITTING"}:
            self._commit_batch(root, db, json.loads((root / "manifest.json").read_text()), writers, pending)
        self._cleanup_batch(root, db, pending["batch_id"])

    def _discard_preparing(self, root: Path, db: sqlite3.Connection, pending) -> None:
        stage = self._owned_stage_path(root, pending["stage_path"], pending["batch_id"])
        if stage.exists():
            self._remove_stage_files(root, stage, pending["batch_id"])
        if db.in_transaction:
            db.rollback()
        db.execute("DELETE FROM rolling_batches WHERE batch_id=? AND status='PREPARING'", (pending["batch_id"],))
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _remove_orphan_stage(self, root: Path, db: sqlite3.Connection) -> None:
        stage_root = root / "staging"
        owner = json.loads((stage_root / ".owner.json").read_text())
        expected = json.loads((root / ".rolling-owner.json").read_text())
        if owner != expected:
            raise RuntimeError("Staging root ownership marker is mismatched")
        rows = {row[0] for row in db.execute("SELECT stage_path FROM rolling_batches")}
        for child in stage_root.iterdir():
            if child.name == ".owner.json":
                continue
            if child.is_symlink() or not child.is_dir() or str(child.relative_to(root)) in rows:
                raise RuntimeError(f"Unexpected orphan staging entry: {child}")
            owner_path = child / "owner.json"
            if not owner_path.is_file():
                raise RuntimeError(f"Unowned orphan staging entry: {child}")
            owner_record = json.loads(owner_path.read_text())
            if owner_record.get("run_id") != expected["run_id"] or not child.name.startswith("batch-"):
                raise RuntimeError(f"Orphan staging ownership mismatch: {child}")
            self._remove_stage_files(root, child, child.name)

    def _commit_batch(self, root: Path, db: sqlite3.Connection, manifest: dict, writers: dict[str, DirectLucenePartition], pending) -> None:
        stage = self._owned_stage_path(root, pending["stage_path"], pending["batch_id"])
        if not stage.is_dir():
            raise RuntimeError(f"PREPARED rolling batch is missing its durable stage: {pending['batch_id']}")
        control = json.loads((stage / "batch.json").read_text())
        self._validate_batch_control(root, manifest, pending, control, stage)
        db.execute("UPDATE rolling_batches SET status='COMMITTING' WHERE batch_id=? AND status IN ('PREPARED','COMMITTING')", (pending["batch_id"],))
        previous_row = db.execute(
            "SELECT batch_id FROM rolling_batches WHERE sequence < ? AND status IN ('COMMITTED','CLEANED') ORDER BY sequence DESC LIMIT 1",
            (pending["sequence"],),
        ).fetchone()
        previous_id = previous_row[0] if previous_row else "__initial__"

        for partition in sorted(control["partitions"]):
            self._ensure_disk_reserve(root, 0)
            staged = control["partitions"][partition]
            payload_path = stage / staged["file"]
            receipt = DirectLucenePartition.read_committed(root / "indexes.building" / partition)
            self._validate_commit_identity(receipt["user_data"], manifest, partition)
            current_batch = receipt["user_data"].get("batch_id")
            stored = db.execute("SELECT * FROM rolling_receipts WHERE batch_id=? AND partition_name=?", (pending["batch_id"], partition)).fetchone()
            if current_batch == pending["batch_id"]:
                if receipt["user_data"].get("stage_sha256") != staged["sha256"] or receipt["user_data"].get("event_digest") != staged["sha256"]:
                    raise RuntimeError(f"Committed partition receipt does not match staged payload: {partition}")
                if stored and stored["stage_sha256"] != staged["sha256"]:
                    raise RuntimeError(f"SQLite/Lucene receipt mismatch: {partition}")
                committed = receipt
            elif current_batch == previous_id:
                if stored:
                    raise RuntimeError(f"SQLite says partition is committed but Lucene is at previous batch: {partition}")
                writer = writers[partition]
                added, digest = writer.add_jsonl(payload_path)
                if added != staged["records"] or digest != staged["sha256"]:
                    raise RuntimeError(f"Staged partition changed while indexing: {partition}")
                committed = writer.commit_batch(
                    batch_id=pending["batch_id"],
                    stage_sha256=staged["sha256"],
                    event_digest=digest,
                )
            else:
                raise RuntimeError(f"Unexpected Lucene commit order for {partition}: {current_batch} != {previous_id}")
            user_data = committed["user_data"]
            if int(user_data.get("cumulative_live_docs", -1)) != committed["documents"]:
                raise RuntimeError(f"Lucene live-document receipt mismatch: {partition}")
            db.execute(
                "INSERT INTO rolling_receipts VALUES(?,?,?,?,?,?) ON CONFLICT(batch_id,partition_name) DO UPDATE SET stage_sha256=excluded.stage_sha256,event_digest=excluded.event_digest,live_documents=excluded.live_documents,commit_data=excluded.commit_data",
                (pending["batch_id"], partition, staged["sha256"], staged["sha256"], committed["documents"], json.dumps(user_data, sort_keys=True)),
            )
        receipt_count = db.execute("SELECT count(*) FROM rolling_receipts WHERE batch_id=?", (pending["batch_id"],)).fetchone()[0]
        if receipt_count != 6:
            raise RuntimeError(f"Rolling batch missing partition receipts: {receipt_count}/6")
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE rolling_batches SET status='COMMITTED' WHERE batch_id=?", (pending["batch_id"],))
        end_cursor = _cursor_load(pending["end_cursor"])
        complete = end_cursor["source_index"] >= len(manifest["spec"]["inputs"])
        db.execute("UPDATE rolling_progress SET cursor=?,status=? WHERE singleton=1", (pending["end_cursor"], "COMPLETE" if complete else "RUNNING"))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _validate_batch_control(self, root: Path, manifest: dict, pending, control: dict, stage: Path) -> None:
        if control.get("run_id") != manifest["run_id"] or control.get("batch_id") != pending["batch_id"]:
            raise RuntimeError("Rolling stage run/batch identity mismatch")
        if control.get("start_cursor") != _cursor_load(pending["start_cursor"]) or control.get("end_cursor") != _cursor_load(pending["end_cursor"]):
            raise RuntimeError("Rolling batch cursor does not match its registry record")
        for partition, info in control["partitions"].items():
            expected_name = partition.replace("/", "-") + ".jsonl"
            if info.get("file") != expected_name:
                raise RuntimeError(f"Unexpected stage file mapping for {partition}")
            path = stage / expected_name
            if path.is_symlink() or not path.is_file() or path.stat().st_size != info["bytes"] or sha_file(path) != info["sha256"]:
                raise RuntimeError(f"Rolling staged file hash/length mismatch: {path}")
        stage_bytes = _tree_bytes(root / "staging")
        if stage_bytes != pending["stage_bytes"] or stage_bytes > self.staging_max_bytes:
            raise RuntimeError(f"Rolling stage byte count changed: {stage_bytes} != {pending['stage_bytes']}")
        identity = {
            "run_id": control["run_id"], "batch_id": control["batch_id"],
            "start_cursor": control["start_cursor"], "end_cursor": control["end_cursor"],
            "partitions": {key: value["sha256"] for key, value in control["partitions"].items()},
            "event_count": control["event_count"], "event_digest": control["event_digest"],
        }
        if sha_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()) != control.get("stage_sha256"):
            raise RuntimeError("Rolling batch manifest signature mismatch")
        if control.get("stage_sha256") != pending["stage_sha256"] or control.get("event_digest") != pending["event_digest"]:
            raise RuntimeError("Rolling SQLite/stage batch digest mismatch")

    @staticmethod
    def _validate_commit_identity(user_data: dict, manifest: dict, partition: str) -> None:
        expected = {
            "run_id": manifest["run_id"],
            "spec_hash": manifest["spec_hash"],
            "schema_version": str(INDEX_SCHEMA_VERSION),
            "analyzer_profile": ANALYZER_PROFILE,
            "partition": partition,
        }
        mismatch = {key: (user_data.get(key), value) for key, value in expected.items() if user_data.get(key) != value}
        if mismatch:
            raise RuntimeError(f"Lucene commit identity mismatch: {partition}: {mismatch}")

    def _cleanup_batch(self, root: Path, db: sqlite3.Connection, batch_id: str) -> None:
        row = db.execute("SELECT stage_path,status FROM rolling_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if not row or row["status"] not in {"COMMITTED", "CLEANED"}:
            raise RuntimeError(f"Cannot clean uncommitted staging batch: {batch_id}")
        stage = self._owned_stage_path(root, row["stage_path"], batch_id)
        if stage.exists():
            owner = json.loads((stage / "owner.json").read_text())
            if owner.get("run_id") != json.loads((root / ".rolling-owner.json").read_text())["run_id"]:
                raise RuntimeError(f"Stage cleanup ownership mismatch: {batch_id}")
            for payload in stage.glob("*.jsonl"):
                if payload.is_symlink() or not payload.is_file():
                    raise RuntimeError(f"Unsafe stage payload during cleanup: {payload}")
                payload.unlink()
            fsync_directory(stage)
        if row["status"] != "CLEANED":
            db.execute("UPDATE rolling_batches SET status='CLEANED' WHERE batch_id=? AND status='COMMITTED'", (batch_id,))
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if stage.exists():
            self._remove_stage_files(root, stage, batch_id)
        self._append_metric(root, {"batch_id": batch_id, "status": "CLEANED", "stage_bytes": _tree_bytes(root / "staging"), "free_bytes": shutil.disk_usage(root).free})

    @staticmethod
    def _owned_stage_path(root: Path, relative: str, batch_id: str) -> Path:
        expected = Path("staging") / batch_id
        if Path(relative) != expected:
            raise RuntimeError(f"Unexpected stage path in registry: {relative}")
        path = root / expected
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            raise RuntimeError(f"Unsafe rolling stage path: {path}")
        return path

    def _remove_stage_files(self, root: Path, stage: Path, batch_id: str) -> None:
        allowed = {"owner.json", "batch.json"}
        allowed.update(f"{granularity}-{lang}.jsonl" for granularity in ("documents", "chunks") for lang in LANGUAGES)
        if stage.is_symlink() or not stage.is_dir():
            raise RuntimeError(f"Unsafe staging directory: {stage}")
        owner_path = stage / "owner.json"
        if not owner_path.is_file():
            raise RuntimeError(f"Refusing to clean an unowned staging directory: {stage}")
        owner = json.loads(owner_path.read_text())
        expected_run = json.loads((root / ".rolling-owner.json").read_text())["run_id"]
        if owner != {"run_id": expected_run, "batch_id": batch_id}:
            raise RuntimeError(f"Staging cleanup owner mismatch: {stage}")
        unexpected = {path.name for path in stage.iterdir()} - allowed
        if unexpected:
            raise RuntimeError(f"Unexpected files prevent staging cleanup: {sorted(unexpected)}")
        shutil.rmtree(stage)
        fsync_directory(stage.parent)

    def _verify_final_indexes(self, root: Path, db: sqlite3.Connection, manifest: dict) -> None:
        latest = db.execute("SELECT batch_id FROM rolling_batches WHERE status IN ('COMMITTED','CLEANED') ORDER BY sequence DESC LIMIT 1").fetchone()
        expected_batch = latest[0] if latest else "__initial__"
        expected_counts = self._counts(db)
        for granularity in ("documents", "chunks"):
            for lang in LANGUAGES:
                partition = f"{granularity}/{lang}"
                path = root / "indexes.building" / granularity / lang
                receipt = DirectLucenePartition.read_committed(path)
                self._validate_commit_identity(receipt["user_data"], manifest, partition)
                expected = expected_counts[f"views_{granularity}_{lang}"]
                if receipt["documents"] != expected or receipt["user_data"].get("batch_id") != expected_batch:
                    raise RuntimeError(f"Final partition integrity mismatch {partition}: live={receipt['documents']}, expected={expected}")

    @staticmethod
    def _counts(db: sqlite3.Connection) -> dict[str, int]:
        counts = {
            "records": db.execute("SELECT count(*) FROM documents").fetchone()[0],
            "chunks": db.execute("SELECT count(*) FROM chunks").fetchone()[0],
            "skipped_status": db.execute("SELECT count(*) FROM record_state WHERE status!='ok'").fetchone()[0],
            "skipped_child": db.execute("SELECT coalesce(sum(skipped_child),0) FROM record_state").fetchone()[0],
            "oversized": db.execute("SELECT coalesce(sum(oversized),0) FROM record_state").fetchone()[0],
        }
        for granularity, table in (("documents", "document_routes"), ("chunks", "chunk_routes")):
            key = "doc_id" if granularity == "documents" else "chunk_id"
            for lang, bit in LANGUAGE_BITS.items():
                counts[f"views_{granularity}_{lang}"] = db.execute(
                    f"SELECT count(*) FROM {table} WHERE (language_mask & ?) != 0", (bit,)
                ).fetchone()[0]
        counts["ok_documents"] = db.execute("SELECT count(*) FROM document_routes WHERE language_mask != 0").fetchone()[0]
        return {key: int(value) for key, value in counts.items()}

    def _publish(self, root: Path, db: sqlite3.Connection, manifest: dict) -> None:
        building = root / "indexes.building"
        target = root / "indexes"
        completion = {
            "run_id": manifest["run_id"], "spec_hash": manifest["spec_hash"],
            "analyzer_profile": ANALYZER_PROFILE, "index_schema_version": INDEX_SCHEMA_VERSION,
        }
        atomic_json(building / "completion.json", completion)
        if target.exists():
            raise RuntimeError(f"Refusing to replace a published index tree: {target}")
        os.replace(building, target)
        fsync_directory(root)
        manifest["indexes"] = {
            f"{granularity}/{lang}": {"documents": self._counts(db)[f"views_{granularity}_{lang}"]}
            for granularity in ("documents", "chunks") for lang in LANGUAGES
        }
        manifest["counts"] = self._counts(db)
        manifest["prepared"] = True
        manifest["status"] = "READY"
        atomic_json(root / "manifest.json", manifest)

    def _finalize_published(self, root: Path, manifest: dict, published: Path) -> None:
        marker_path = published / "completion.json"
        if not marker_path.is_file():
            raise RuntimeError("Published index tree has no completion marker")
        marker = json.loads(marker_path.read_text())
        expected = {"run_id": manifest["run_id"], "spec_hash": manifest["spec_hash"], "analyzer_profile": ANALYZER_PROFILE, "index_schema_version": INDEX_SCHEMA_VERSION}
        if marker != expected:
            raise RuntimeError("Published index completion marker is incompatible")
        if manifest.get("status") != "READY":
            with sqlite3.connect(f"file:{root / 'metadata.sqlite'}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                manifest["counts"] = self._counts(db)
                manifest["indexes"] = {
                    f"{granularity}/{lang}": {"documents": manifest["counts"][f"views_{granularity}_{lang}"]}
                    for granularity in ("documents", "chunks") for lang in LANGUAGES
                }
            manifest["prepared"] = True
            manifest["status"] = "READY"
            atomic_json(root / "manifest.json", manifest)

    @staticmethod
    def _append_metric(root: Path, metric: dict) -> None:
        path = root / "rolling_metrics.jsonl"
        with path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(metric, ensure_ascii=False, separators=(",", ":")) + "\n")
            target.flush()
            os.fsync(target.fileno())


class _RegistryContext:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc_value, traceback):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()
        return False
