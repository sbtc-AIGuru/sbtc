"""Kaggle-only storage/restore adapter for the existing retrieval pipeline."""

from collections import OrderedDict
from contextlib import nullcontext
from copy import deepcopy
import gzip
import hashlib
import json
import logging
import math
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time
from urllib.parse import quote
import zipfile

import requests

from BackEnd.app.Database.qdrant_db import QdrantManager
from BackEnd.app.Retrieval.utils import sha_file, source_id

QDRANT_VERSION = "1.19.2"
QDRANT_SHA256 = "50b253243309ed0ae50a19f678f0d0adcc4f0b567b3bd2c5c0c7e02fa8404bb6"


def find_input(name, configured=None):
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    matches = sorted(Path("/kaggle/input").rglob(name))
    if len(matches) != 1:
        raise ValueError(f"Set the input path explicitly: {name}: {matches}")
    return matches[0]


def build_source_index(source, database, manifest, *, local_source=None):
    """Index JSONL/line-oriented JSON by byte position; never duplicate corpus text."""
    source, database = Path(source), Path(database)
    local_source = Path(local_source) if local_source else None
    identity = {"source_bytes": source.stat().st_size,
                "source_sha256": manifest["signature"]["source_sha256"], "format": 1}
    receipt = database.with_suffix(".receipt.json")
    if database.exists() and receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["identity"] != identity:
            raise ValueError("SQLite index belongs to a different source")
        if local_source and (saved.get("local_source") != str(local_source) or
                             not local_source.exists() or local_source.stat().st_size != identity["source_bytes"]):
            raise ValueError("Local source mirror is missing or differs from the index receipt")
        return saved
    database.parent.mkdir(parents=True, exist_ok=True)
    partial = database.with_suffix(".partial.sqlite")
    partial.unlink(missing_ok=True)
    db = sqlite3.connect(partial)
    db.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=FILE;
        PRAGMA cache_size=-65536;
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY, doc_id INTEGER NOT NULL,
            offset INTEGER NOT NULL, bytes INTEGER NOT NULL, position INTEGER NOT NULL
        ) WITHOUT ROWID;
    """)
    digest, documents, chunks, pending = hashlib.sha256(), 0, 0, []
    started = time.monotonic()
    array, closed, previous_comma = False, False, True
    mirror_partial = local_source.with_suffix(local_source.suffix + ".partial") if local_source else None
    try:
        with source.open("rb") as stream, (mirror_partial.open("wb") if mirror_partial else nullcontext()) as mirror:
            while True:
                offset = stream.tell()
                raw = stream.readline()
                if not raw:
                    break
                digest.update(raw)
                if mirror is not None:
                    mirror.write(raw)
                line = raw.strip()
                if not line:
                    continue
                if closed:
                    raise ValueError("Unexpected content after merged.json array")
                if line == b"[" and documents == 0 and not array:
                    array = True
                    continue
                if array and line == b"]":
                    if documents and previous_comma:
                        raise ValueError("Trailing comma in merged.json")
                    closed = True
                    continue
                if array:
                    if not previous_comma:
                        raise ValueError("Missing separator in merged.json")
                    previous_comma = line.endswith(b",")
                    if previous_comma:
                        line = line[:-1]
                document = json.loads(line)
                doc_id = source_id(document["doc_id"])
                for position, child in enumerate(document["children"]):
                    if child["doc_id"] != doc_id or not isinstance(child["chunk_text"], str):
                        raise ValueError(f"Invalid source identity/text for {child['chunk_id']}")
                    if not isinstance(child["chunk_id"], str) or not child["chunk_id"]:
                        raise ValueError("Missing source chunk_id")
                    pending.append((child["chunk_id"], doc_id, offset, len(raw), position))
                    chunks += 1
                    if len(pending) >= 5000:
                        db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)", pending)
                        db.commit()
                        pending.clear()
                documents += 1
                if documents % 25000 == 0:
                    print(f"Source index: {documents:,} docs / {chunks:,} chunks; "
                          f"{offset / 1024**3:.1f} GiB; {time.monotonic()-started:.0f}s", flush=True)
        if array and not closed:
            raise ValueError("Missing closing array bracket")
        db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)", pending)
        db.commit()
        if digest.hexdigest() != identity["source_sha256"]:
            raise ValueError("JSON source checksum differs from snapshot source")
        if documents != manifest["signature"]["expected_documents"]:
            raise ValueError("Source document count differs from snapshot source")
        if chunks != manifest["signature"]["expected_chunks"]:
            raise ValueError("Source chunk count differs from snapshot source")
    finally:
        db.close()
    if local_source:
        mirror_partial.replace(local_source)
    partial.replace(database)
    result = {"identity": identity, "documents": documents, "chunks": chunks,
              "index_bytes": database.stat().st_size, "seconds": time.monotonic()-started}
    if local_source:
        result["local_source"] = str(local_source)
        result["local_source_bytes"] = local_source.stat().st_size
    receipt.write_text(json.dumps(result, indent=2))
    return result


class JsonSourceStore:
    """The get_submission_chunks interface used by run_pipeline, backed by SQLite."""

    def __init__(self, source, database, cache_bytes=32 * 1024**2):
        self.stream = Path(source).open("rb")
        self.db = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True)
        self.db.execute("PRAGMA cache_size=-16384")
        self.cache = OrderedDict()
        self.cache_bytes, self.cached_bytes = cache_bytes, 0

    def get_submission_chunks(self, chunk_ids, *, batch_size=500):
        identifiers = list(dict.fromkeys(chunk_ids))
        result = dict.fromkeys(identifiers)
        for start in range(0, len(identifiers), batch_size):
            batch = identifiers[start:start + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = self.db.execute(
                f"SELECT chunk_id,doc_id,offset,bytes,position FROM chunks "
                f"WHERE chunk_id IN ({placeholders}) ORDER BY offset,position", batch,
            )
            for chunk_id, doc_id, offset, size, position in rows:
                if offset in self.cache:
                    document, memory = self.cache[offset]
                    self.cache.move_to_end(offset)
                else:
                    self.stream.seek(offset)
                    raw = self.stream.read(size).strip()
                    document = json.loads(raw[:-1] if raw.endswith(b",") else raw)
                    memory = size * 5
                    if memory <= self.cache_bytes:
                        self.cache[offset] = document, memory
                        self.cached_bytes += memory
                        while self.cached_bytes > self.cache_bytes:
                            _, (_, old_memory) = self.cache.popitem(last=False)
                            self.cached_bytes -= old_memory
                child = document["children"][position]
                if document["doc_id"] != doc_id or child["doc_id"] != doc_id or child["chunk_id"] != chunk_id:
                    raise ValueError(f"SQLite/source identity mismatch: {chunk_id}")
                result[chunk_id] = {"chunk_id": chunk_id, "doc_id": doc_id,
                                    "chunk_text": child["chunk_text"]}
        return result

    def close(self):
        self.stream.close()
        self.db.close()


class SourceQdrant(QdrantManager):
    """Keep query/fusion intact, allow cold searches, optionally fetch only chunk IDs."""

    def __init__(self, *args, ids_only=True, exact_search=False, record_queries=None, replay_queries=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids_only = ids_only
        self.exact_search = exact_search
        self.record_queries, self.replay_queries = record_queries, replay_queries

    def _dense_query(self, vector):
        query = super()._dense_query(vector)
        if self.exact_search:
            query["params"] = {"exact": True}
        return query

    def _request(self, method, path, body=None):
        is_query = method == "POST" and path.endswith("/points/query")
        original_body = deepcopy(body) if is_query and (
            self.record_queries is not None or self.replay_queries is not None
        ) else None
        if is_query and self.replay_queries is not None:
            recorded = self.replay_queries.pop(0)
            if recorded["body"] != original_body:
                raise ValueError("Parity replay query differs from the recorded live request")
            result = deepcopy(recorded["result"])
            if self.ids_only:
                for point in result["points"]:
                    point["payload"] = {"chunk_id": point["payload"]["chunk_id"]}
            return result
        if is_query:
            if self.ids_only:
                body = {**body, "with_payload": ["chunk_id"]}
            # The client timeout alone does not extend Qdrant's server-side query deadline.
            path += f"?timeout={max(1, int(self.timeout) - 10)}"
        try:
            result = super()._request(method, path, body)
            if is_query and self.record_queries is not None:
                self.record_queries.append({"body": original_body, "result": deepcopy(result)})
            return result
        except requests.RequestException as error:
            response = error.response
            logging.getLogger(__name__).error(
                "Qdrant request failed: %s; HTTP=%s; detail=%s",
                type(error).__name__, response.status_code if response is not None else None,
                response.text[:1500] if response is not None else "No HTTP response",
            )
            raise


def compare_query_traces(baseline, live, boundary=None):
    """Allow tied ordering/cutoff choices only with live evidence of equal scores."""
    if not baseline or len(baseline) != len(live):
        raise ValueError("Live parity query count differs from baseline")
    permutations, substitutions = 0, 0
    for index, (first, second) in enumerate(zip(baseline, live, strict=True)):
        if first["body"] != second["body"]:
            raise ValueError("Live parity query parameters differ from baseline")
        left, right = first["result"]["points"], second["result"]["points"]
        left_ids = [p["payload"]["chunk_id"] for p in left]
        right_ids = [p["payload"]["chunk_id"] for p in right]
        if len(left_ids) != len(right_ids):
            raise ValueError("Live query candidate set differs from baseline")
        scores = {p["payload"]["chunk_id"]: p["score"] for p in left}
        changed = set(left_ids) ^ set(right_ids)
        if changed:
            if boundary is None or len(boundary) != len(baseline):
                raise ValueError("Live query candidate set differs without cutoff tie evidence")
            control = boundary[index]
            expected_body = {**first["body"], "limit": sum(p["limit"] for p in first["body"]["prefetch"])}
            if control["body"] != expected_body:
                raise ValueError("Cutoff tie control query parameters differ")
            control_scores = {p["payload"]["chunk_id"]: p["score"] for p in control["result"]["points"]}
            cutoff = left[-1]["score"]
            for point in left + right:
                key, score = point["payload"]["chunk_id"], point["score"]
                if key not in control_scores or not math.isclose(control_scores[key], score, rel_tol=0, abs_tol=1e-12):
                    raise ValueError("Cutoff tie control changed a candidate score")
                if key in changed and not math.isclose(score, cutoff, rel_tol=0, abs_tol=1e-12):
                    raise ValueError("Live query candidate set changed above the cutoff tie")
            substitutions += len(set(left_ids) - set(right_ids))
        for original, current in zip(left, right, strict=True):
            if not math.isclose(original["score"], current["score"], rel_tol=0, abs_tol=1e-12):
                raise ValueError("Live query changed ordering across distinct scores")
            key = current["payload"]["chunk_id"]
            if key in scores and not math.isclose(scores[key], current["score"], rel_tol=0, abs_tol=1e-12):
                raise ValueError("Live query changed a candidate score")
        permutations += left_ids != right_ids
    return {"queries": len(baseline), "identical_candidate_sets": substitutions == 0,
            "identical_scores": True, "order_changes_only_within_ties": True,
            "cutoff_tie_candidate_substitutions": substitutions,
            "cutoff_ties_verified_by_expanded_live_query": substitutions > 0,
            "queries_with_tie_permutations": permutations}


def restore_qdrant(manifest_path, state_dir, *, port=6333, search_threads=2, timeout=3600):
    manifest_path, state = Path(manifest_path), Path(state_dir).resolve()
    if not state.is_relative_to(Path("/kaggle/temp")):
        raise ValueError("Qdrant state must be under /kaggle/temp")
    manifest = json.loads(manifest_path.read_text())
    if not manifest["complete"] or manifest["qdrant_version"] != QDRANT_VERSION:
        raise ValueError("Require the complete pinned Qdrant 1.19.2 hybrid snapshot")
    for directory in ("storage", "snapshots", "snapshot_temp", "bin"):
        (state / directory).mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already in use; stop the previous notebook server first")
    if any((state / "storage").iterdir()):
        raise RuntimeError("Qdrant storage is not empty; use a new TEMP_ROOT for a fresh restore")
    # CLI recovery renames the restored collection before normal startup creates its parent.
    (state / "storage" / "collections").mkdir()
    snapshot = manifest_path.parent / manifest["snapshot_file"]
    free = shutil.disk_usage(state).free
    required = 3 * manifest["raw_snapshot_bytes"] + 2 * 1024**3
    print(f"Temp disk: free={free / 1024**3:.1f} GiB, restore budget={required / 1024**3:.1f} GiB", flush=True)
    if free < required:
        raise RuntimeError("Insufficient /kaggle/temp disk for snapshot + restore staging + storage")
    print("Verifying compressed snapshot checksum", flush=True)
    if sha_file(snapshot) != manifest["snapshot_sha256"]:
        raise ValueError("Compressed snapshot SHA-256 mismatch")
    raw = state / "snapshots" / "restore.snapshot"
    print("Unpacking snapshot into /kaggle/temp", flush=True)
    digest = hashlib.sha256()
    with gzip.open(snapshot, "rb") as src, raw.open("wb") as dst:
        while block := src.read(8 * 1024**2):
            digest.update(block)
            dst.write(block)
    if raw.stat().st_size != manifest["raw_snapshot_bytes"] or digest.hexdigest() != manifest["raw_snapshot_sha256"]:
        raise ValueError("Raw snapshot size/SHA-256 mismatch")
    archive, binary = state / "bin" / "qdrant.tar.gz", state / "bin" / "qdrant"
    url = f"https://github.com/qdrant/qdrant/releases/download/v{QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz"
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with archive.open("wb") as stream:
            for block in response.iter_content(1024**2):
                stream.write(block)
    if sha_file(archive) != QDRANT_SHA256:
        raise ValueError("Official Qdrant binary archive SHA-256 mismatch")
    with tarfile.open(archive) as bundle:
        member = next(m for m in bundle.getmembers() if Path(m.name).name == "qdrant" and m.isfile())
        with bundle.extractfile(member) as src, binary.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    binary.chmod(0o755)
    archive.unlink()
    config = {
        "log_level": "WARN", "telemetry_disabled": True,
        "storage": {"storage_path": str(state / "storage"),
                    "snapshots_path": str(state / "snapshots"),
                    "temp_path": str(state / "snapshot_temp"),
                    "on_disk_payload": True, "low_memory_mode": "no_populate",
                    "performance": {"max_search_threads": search_threads, "optimizer_cpu_budget": 1},
                    "optimizers_overwrite": {"max_optimization_threads": 0}},
        "service": {"host": "127.0.0.1", "http_port": port, "grpc_port": None,
                    "max_workers": 2, "max_request_size_mb": 64},
    }
    config_path = state / "qdrant.yaml"
    config_path.write_text(json.dumps(config))
    log_path = state / "qdrant.log"
    log = log_path.open("w")
    process = subprocess.Popen(
        [str(binary), "--config-path", str(config_path), "--disable-telemetry",
         "--snapshot", f"{raw}:{manifest['collection']}"],
        cwd=state, stdout=log, stderr=subprocess.STDOUT,
    )
    url, started, last_print = f"http://127.0.0.1:{port}", time.monotonic(), 0
    try:
        while time.monotonic() - started < timeout:
            if process.poll() is not None:
                raise RuntimeError(f"Qdrant exited: {log_path.read_text()[-6000:]}")
            try:
                response = requests.get(url + "/readyz", timeout=2)
                if response.ok:
                    break
            except (requests.ConnectionError, requests.Timeout):
                pass
            if time.monotonic() - last_print >= 30:
                print(f"Restoring Qdrant: {time.monotonic()-started:.0f}s", flush=True)
                last_print = time.monotonic()
            time.sleep(2)
        else:
            raise TimeoutError(f"Qdrant restore exceeded {timeout}s: {log_path}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        if response.json()["version"] != QDRANT_VERSION:
            raise ValueError("Restored server version differs from snapshot")
        path = "/collections/" + quote(manifest["collection"], safe="")
        response = requests.post(url + path + "/points/count", json={"exact": True}, timeout=300)
        response.raise_for_status()
        if response.json()["result"]["count"] != manifest["points"]:
            raise ValueError("Restored point count differs from snapshot")
        with QdrantManager.from_manifest(manifest_path, url=url, timeout=300) as manager:
            info = manager.refresh_collection()
        schema = manifest["vector_schema"]
        if schema["sparse"] not in info["config"]["params"].get("sparse_vectors", {}):
            raise ValueError("Restored collection is missing BM25")
        if info["optimizer_status"] != "ok":
            raise ValueError(f"Restored optimizer error: {info['optimizer_status']}")
        raw.unlink()
        print(f"Restored {manifest['points']:,} hybrid points; state={state}", flush=True)
        return process, log, {"points": manifest["points"], "version": QDRANT_VERSION,
                              "seconds": time.monotonic()-started, "state_dir": str(state),
                              "collection_status": info["status"]}
    except BaseException:
        stop_qdrant(process, log)
        raise


def stop_qdrant(process, log):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    log.close()


def validate_submission(output, archive, checkpoint, expected_ids, store, *, start_row=0):
    """Check BTC types/order, ZIP content, and every output chunk against JSON."""
    from BackEnd.app.Retrieval.export import btc_normalized

    predictions = json.loads(Path(output).read_text())
    if [p["id"] for p in predictions] != expected_ids or len(set(expected_ids)) != len(expected_ids):
        raise ValueError("Submission query IDs/order differ from the Parquet selection")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.namelist() != [Path(output).name] or bundle.read(Path(output).name) != Path(output).read_bytes():
            raise ValueError("ZIP content differs from submission JSON")
    checked, records, seen_rows = 0, 0, set()
    with Path(checkpoint).open() as stream:
        next(stream)
        for line in stream:
            item = json.loads(line)
            row = item["row"]
            if row in seen_rows or not start_row <= row < start_row + len(predictions):
                raise ValueError("Duplicate/out-of-range checkpoint row")
            seen_rows.add(row)
            prediction = predictions[row - start_row]
            if item["prediction"] != prediction:
                raise ValueError("Checkpoint prediction/order differs from submission")
            if set(prediction) != {"id", "relevant_docs", "relevant_chunks"}:
                raise ValueError("Unexpected BTC output keys")
            source_id(prediction["id"])
            documents = prediction["relevant_docs"]
            if len(set(documents)) != len(documents):
                raise ValueError("Duplicate output document")
            for doc_id in documents:
                source_id(doc_id)
            chunks = prediction["relevant_chunks"]
            if len(item["chunk_ids"]) != len(chunks):
                raise ValueError("Checkpoint chunk count mismatch")
            source = store.get_submission_chunks(item["chunk_ids"])
            seen = set()
            for chunk_id, chunk in zip(item["chunk_ids"], chunks, strict=True):
                if set(chunk) != {"doc_id", "chunk_text"}:
                    raise ValueError("Unexpected BTC chunk keys")
                source_id(chunk["doc_id"])
                text = source[chunk_id]
                if text is None or chunk != {"doc_id": text["doc_id"], "chunk_text": text["chunk_text"]}:
                    raise ValueError(f"Output chunk differs from JSON source: {chunk_id}")
                key = chunk["doc_id"], btc_normalized(chunk["chunk_text"])
                if not chunk["chunk_text"].strip() or key in seen:
                    raise ValueError("Empty/duplicate output chunk")
                seen.add(key)
                checked += 1
            records += 1
    if records != len(predictions):
        raise ValueError("Checkpoint query coverage differs from submission")
    return {"queries": records, "source_chunks_verified": checked,
            "submission_sha256": sha_file(Path(output)), "zip_sha256": sha_file(Path(archive)),
            "schema": "integer-doc-ids-v1", "zip_matches_json": True}
