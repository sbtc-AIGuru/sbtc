from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from pathlib import Path

from .utils import sha_bytes


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS corpus(id INTEGER PRIMARY KEY, url TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, path TEXT UNIQUE, sha TEXT, bytes INTEGER, mtime INTEGER);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, url TEXT, source INTEGER REFERENCES sources(id), offset INTEGER, bytes INTEGER, sha TEXT);
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, doc INTEGER REFERENCES documents(id), ord INTEGER, start INTEGER, end INTEGER, sha TEXT);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc);
CREATE TABLE IF NOT EXISTS tasks(source INTEGER PRIMARY KEY REFERENCES sources(id), counters TEXT NOT NULL, stages TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_routes(doc_id INTEGER PRIMARY KEY REFERENCES documents(id), language_mask INTEGER NOT NULL CHECK(language_mask BETWEEN 0 AND 7));
CREATE TABLE IF NOT EXISTS chunk_routes(chunk_id TEXT PRIMARY KEY REFERENCES chunks(id), language_mask INTEGER NOT NULL CHECK(language_mask BETWEEN 0 AND 7));
"""


class TextStore:
    def __init__(self, path: Path, *, writable=False, cache_bytes=64 * 1024**2):
        self.db = sqlite3.connect(str(path) if writable else f"file:{path.resolve()}?mode=ro", uri=not writable)
        self.db.row_factory = sqlite3.Row
        if writable:
            self.db.executescript(SCHEMA)
        self.cache_bytes = cache_bytes
        self.cache = OrderedDict()
        self.cache_size = 0

    def metadata(self, chunk_id: str) -> dict:
        row = self.db.execute("SELECT id AS chunk_id,doc AS doc_id,ord AS chunk_order,start,end,sha FROM chunks WHERE id=?", (chunk_id,)).fetchone()
        if row is None:
            raise KeyError(chunk_id)
        return dict(row)

    def document_exists(self, doc_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone() is not None

    def validate_sources(self):
        for row in self.db.execute("SELECT path,bytes,mtime FROM sources"):
            stat = Path(row["path"]).stat()
            if stat.st_size != row["bytes"] or stat.st_mtime_ns != row["mtime"]:
                raise RuntimeError(f"SourceChanged: {row['path']}")

    def get(self, chunk_id: str) -> dict:
        meta = self.metadata(chunk_id)
        row = self.db.execute("SELECT d.*,s.path,s.bytes AS file_bytes,s.mtime FROM documents d JOIN sources s ON d.source=s.id WHERE d.id=?", (meta["doc_id"],)).fetchone()
        path = Path(row["path"])
        stat = path.stat()
        if stat.st_size != row["file_bytes"] or stat.st_mtime_ns != row["mtime"]:
            raise RuntimeError(f"SourceChanged: {path}")
        if row["id"] in self.cache:
            data, size = self.cache[row["id"]]
            self.cache.move_to_end(row["id"])
        else:
            with path.open("rb") as f:
                f.seek(row["offset"])
                payload = f.read(row["bytes"])
            if sha_bytes(payload) != row["sha"]:
                raise RuntimeError("Source record hash mismatch")
            parsed = json.loads(payload)
            if parsed["doc_id"] != row["id"]:
                raise RuntimeError("Source document identity mismatch")
            data = {c["chunk_id"]: c for c in parsed.get("children", [])}
            # Decoded Python strings/dicts consume more than the raw JSON byte count.
            size = len(payload) * 5
            if size <= self.cache_bytes:
                self.cache[row["id"]] = (data, size)
                self.cache_size += size
                while self.cache_size > self.cache_bytes:
                    _, (_, old_size) = self.cache.popitem(last=False)
                    self.cache_size -= old_size
        child = data[chunk_id]
        if child["doc_id"] != meta["doc_id"] or child["chunk_order"] != meta["chunk_order"] or sha_bytes(child["chunk_text"].encode()) != meta["sha"]:
            raise RuntimeError("Source chunk identity/text mismatch")
        return {"doc_id": str(meta["doc_id"]), "chunk_order": meta["chunk_order"], "chunk_text": child["chunk_text"]}

    def get_many(self, identifiers) -> dict:
        return {identifier: self.get(identifier) for identifier in identifiers}

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
