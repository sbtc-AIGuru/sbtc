"""Stream the three ViBioMIR embedding outputs into a portable FP16 dense collection."""

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
import time
import uuid

import numpy as np
import psutil
import pyarrow.parquet as pq
import requests

if __package__:
    from .read_vibiomir_outputs import discover_outputs
    from .restore_vibiomir_qdrant import verify_collection
else:
    from read_vibiomir_outputs import discover_outputs
    from restore_vibiomir_qdrant import verify_collection

QDRANT_VERSION = "1.19.2"
QDRANT_URL = f"https://github.com/qdrant/qdrant/releases/download/v{QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz"
QDRANT_SHA256 = "50b253243309ed0ae50a19f678f0d0adcc4f0b567b3bd2c5c0c7e02fa8404bb6"
VECTOR_NAME = "qwen3_dense"
PAYLOAD_INDEXES = {"chunk_id": "keyword", "doc_id": "integer", "content_origin": "keyword"}
NAMESPACE = uuid.UUID("ba368b92-593b-53e5-9fca-f889a83f6f8f")

def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def output_budget(config: dict) -> int:
    root = Path(config["output_budget_root"])
    used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    return max(0, min(config["output_limit_bytes"] - used,
                      shutil.disk_usage(root).free - 512 * 1024**2))


def download_qdrant(config: dict) -> Path:
    binary = Path(config["binary"])
    if binary.exists():
        return binary
    binary.parent.mkdir(parents=True, exist_ok=True)
    archive = binary.with_suffix(".tar.gz")
    with requests.get(QDRANT_URL, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with archive.open("wb") as stream:
            for block in response.iter_content(1024**2):
                stream.write(block)
    if checksum(archive) != QDRANT_SHA256:
        raise ValueError("Official Qdrant release archive SHA-256 mismatch")
    with tarfile.open(archive) as bundle:
        member = next(item for item in bundle.getmembers()
                      if Path(item.name).name == "qdrant" and item.isfile())
        with bundle.extractfile(member) as source, binary.open("wb") as destination:
            shutil.copyfileobj(source, destination)
    binary.chmod(0o755)
    return binary


def api(config: dict, method: str, path: str, body=None, session=None, timeout=300):
    connection = session or requests
    response = connection.request(method, config["qdrant_url"] + path, json=body, timeout=timeout)
    if not response.ok:
        raise RuntimeError(f"Qdrant {method} {path}: HTTP {response.status_code}: {response.text[:1500]}")
    return response.json().get("result")


def start_server(config: dict):
    binary = download_qdrant(config)
    port = config["port"]
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already in use; refusing to attach to another database")
    state = Path(config["state_dir"])
    for directory in ("storage", "snapshots", "snapshot_temp"):
        (state / directory).mkdir(parents=True, exist_ok=True)
    server_config = {
        "log_level": "WARN", "telemetry_disabled": True,
        "storage": {"storage_path": str(state / "storage"),
                    "snapshots_path": str(state / "snapshots"),
                    "temp_path": str(state / "snapshot_temp"),
                    "on_disk_payload": True, "low_memory_mode": "no_populate",
                    "performance": {"max_search_threads": 2, "optimizer_cpu_budget": 2}},
        "service": {"host": "127.0.0.1", "http_port": port, "grpc_port": port + 1,
                    "max_request_size_mb": 64, "max_workers": 2},
    }
    # JSON syntax is valid YAML; Qdrant's loader expects a .yaml config path.
    config_path = state / "qdrant_config.yaml"
    write_json(config_path, server_config)
    log = (Path(config["output"]) / "qdrant.log").open("a", encoding="utf-8")
    process = subprocess.Popen([str(binary), "--config-path", str(config_path), "--disable-telemetry"],
                               cwd=state, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("Qdrant exited during startup; inspect qdrant.log")
            try:
                response = requests.get(config["qdrant_url"] + "/readyz", timeout=1)
                if response.ok:
                    version = requests.get(config["qdrant_url"], timeout=5).json()["version"]
                    if version != QDRANT_VERSION:
                        raise RuntimeError(f"Expected Qdrant {QDRANT_VERSION}; server reports {version}")
                    print(f"Qdrant {version} READY at {config['qdrant_url']}", flush=True)
                    return process, log
            except requests.ConnectionError:
                pass
            time.sleep(0.5)
        raise TimeoutError("Qdrant did not become ready in 60 seconds")
    except BaseException:
        stop_server(process, log)
        raise


def stop_server(process, log) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    log.close()


def count_points(config: dict) -> int:
    return api(config, "POST", f"/collections/{config['collection']}/points/count", {"exact": True})["count"]


def signature(config, catalog):
    identity = {"source_sha256": catalog["source_sha256"], "profile_id": catalog["profile_id"],
                "encoder": catalog["encoder"], "expected_chunks": catalog["rows"],
                "dimension": catalog["encoder"]["dimension"], "collection": config["collection"],
                "dense_datatype": "float16", "vector_name": VECTOR_NAME,
                "hnsw_m": config["hnsw_m"], "ef_construction": config["ef_construction"],
                "payload_indexes": PAYLOAD_INDEXES}
    receipts = [item["receipt"] for item in catalog["files"]]
    identity["files_sha256"] = hashlib.sha256(json.dumps(receipts, sort_keys=True).encode()).hexdigest()
    return identity


def load_catalog(config):
    catalog = discover_outputs(config["input_root"], required_parts=(1, 2, 3))
    if (not catalog["full_corpus"] or catalog["rows"] != config["expected_chunks"]
            or catalog["encoder"]["dimension"] != config["dimension"]
            or catalog["encoder"]["vector_name"] != VECTOR_NAME
            or catalog["source_sha256"] != config["source_sha256"]
            or catalog["profile_id"] != config["profile_id"]):
        raise ValueError("Inputs differ from the required full ViBioMIR source/encoder profile")
    payload_bytes = 0
    for index, item in enumerate(catalog["files"], 1):
        path = Path(item["path"])
        if checksum(path) != item["receipt"]["sha256"]:
            raise ValueError(f"Parquet checksum mismatch: {path}")
        parquet = pq.ParquetFile(path)
        column = parquet.schema_arrow.get_field_index("payload_json")
        payload_bytes += sum(parquet.metadata.row_group(i).column(column).total_uncompressed_size
                             for i in range(parquet.num_row_groups))
        if index % 25 == 0 or index == len(catalog["files"]):
            print(f"INPUT VERIFIED: {index}/{len(catalog['files'])} files; {catalog['rows']:,} total vectors", flush=True)
    catalog["payload_bytes"] = payload_bytes
    return catalog


def check_resources(config, catalog):
    state = Path(config["state_dir"])
    mounts = [m for m in psutil.disk_partitions(all=True) if state.resolve().is_relative_to(Path(m.mountpoint))]
    kind = max(mounts, key=lambda m: len(m.mountpoint)).fstype if mounts else "unknown"
    if kind in {"tmpfs", "ramfs"}:
        raise RuntimeError(f"Qdrant state must use disk, not {kind}: {state}")
    vectors = catalog["rows"] * config["dimension"] * 2
    graph = catalog["rows"] * (8 * config["hnsw_m"] + 128)
    collection = vectors + graph + catalog["payload_bytes"]
    required = 4 * collection + 4 * 1024**3
    free = shutil.disk_usage(state).free
    budget = output_budget(config)
    report = {"state_filesystem": kind, "state_free_bytes": free,
              "estimated_collection_bytes": collection, "required_state_bytes": required,
              "output_available_bytes": budget, "raw_fp16_vector_bytes": vectors,
              "estimated_graph_bytes": graph, "parquet_payload_uncompressed_bytes": catalog["payload_bytes"],
              "ram_available_bytes": psutil.virtual_memory().available}
    write_json(Path(config["output"]) / "preflight.json", report)
    print("RESOURCES:", json.dumps(report), flush=True)
    if free < required:
        raise RuntimeError("Insufficient disk for collection, snapshots, rewrites and restore verification")
    if budget < vectors + 512 * 1024**2:
        raise RuntimeError("Output budget cannot hold the FP16 vectors plus export headroom")
    if min(psutil.virtual_memory().available, psutil.virtual_memory().total) < 3 * 1024**3:
        raise RuntimeError("Less than 3 GiB RAM available for the disk-backed CPU pipeline")


def create_collection(config):
    name = config["collection"]
    existing = api(config, "GET", "/collections")["collections"]
    if not any(c["name"] == name for c in existing):
        api(config, "PUT", f"/collections/{name}", {
            "vectors": {VECTOR_NAME: {"size": config["dimension"], "distance": "Cosine",
                                       "on_disk": True, "datatype": "float16"}},
            "on_disk_payload": True, "shard_number": 1,
            "hnsw_config": {"m": 0, "on_disk": True, "max_indexing_threads": 2},
            "optimizers_config": {"default_segment_number": 2, "max_segment_size": 500_000,
                                  "indexing_threshold": config["indexing_threshold_kb"],
                                  "max_optimization_threads": 1},
        })
    info = api(config, "GET", f"/collections/{name}")
    params = info["config"]["params"]
    expected = {"size": config["dimension"], "distance": "Cosine", "datatype": "float16", "on_disk": True}
    if (set(params["vectors"]) != {VECTOR_NAME} or params.get("sparse_vectors")
            or any(params["vectors"][VECTOR_NAME].get(k) != v for k, v in expected.items())
            or not params.get("on_disk_payload")):
        raise ValueError("Existing collection is not the expected disk-backed FP16 dense schema")
    for field, kind in PAYLOAD_INDEXES.items():
        api(config, "PUT", f"/collections/{name}/index?wait=true",
            {"field_name": field, "field_schema": {"type": kind, "on_disk": True}})


def iter_points(path, receipt, dimension, batch_size, skip_rows=0):
    seen = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        data = batch.to_pydict()
        vectors = np.asarray(data["vector"], dtype=np.float32)
        if (vectors.shape != (batch.num_rows, dimension) or not np.isfinite(vectors).all()
                or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-5, rtol=0)):
            raise ValueError(f"Invalid embedding values in {path}")
        points = []
        for index in range(batch.num_rows):
            row = {k: v[index] for k, v in data.items() if k != "vector"}
            payload = json.loads(row["payload_json"])
            provenance = payload["_embedding"]
            source_line = receipt["start_line"] + seen + index
            content_hash = hashlib.sha256(payload["content"].encode("utf-8")).hexdigest()
            if (row["source_line"] != source_line or provenance["source_line"] != source_line
                    or provenance["source_byte"] != row["source_byte"]
                    or provenance["source_sha256"] != receipt["source_sha256"]
                    or provenance["profile_id"] != receipt["profile_id"]
                    or provenance["part"] != receipt["part"] or provenance["gpu"] != receipt["gpu"]
                    or provenance["input_token_count"] != row["input_token_count"]
                    or provenance["truncated"] is not False
                    or any(payload[k] != row[k] for k in ("chunk_id", "doc_id", "content", "content_origin", "token_count"))
                    or row["content_sha256"] != content_hash or provenance["content_sha256"] != content_hash
                    or str(uuid.uuid5(NAMESPACE, payload["chunk_id"])) != row["point_id"]):
                raise ValueError(f"Payload, point ID or provenance mismatch: {path}, line {source_line}")
            if seen + index >= skip_rows:
                points.append({"id": row["point_id"], "vector": {VECTOR_NAME: vectors[index].tolist()},
                               "payload": payload})
        seen += batch.num_rows
        if points:
            yield points, seen
    if seen != receipt["rows"] or not 0 <= skip_rows <= seen:
        raise ValueError("Parquet/checkpoint row count differs")


def upsert(config, points, session):
    for attempt in range(4):
        try:
            response = session.put(f"{config['qdrant_url']}/collections/{config['collection']}/points?wait=true",
                                   json={"points": points}, timeout=180)
            if response.status_code in (408, 429, 500, 502, 503, 504):
                if attempt == 3:
                    response.raise_for_status()
            else:
                response.raise_for_status()
                if response.json()["result"]["status"] != "completed":
                    raise RuntimeError("Qdrant did not acknowledge completed upsert")
                return
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 3:
                raise
        time.sleep(2**attempt)


def checkpoint_path(config):
    return Path(config["state_dir"]) / "ingestion_checkpoint.json"


def ingest(config, catalog, state, started):
    initial_rows = state["rows"]
    output = Path(config["output"])
    samples_path = output / "verification_samples.json"
    samples = json.loads(samples_path.read_text()) if samples_path.exists() else []
    sample_stride = max(1, len(catalog["files"]) // 48)
    with requests.Session() as session:
        for file_index, item in enumerate(catalog["files"]):
            if file_index < state["file_index"]:
                continue
            path, receipt = Path(item["path"]), item["receipt"]
            skip = state["file_rows"] if file_index == state["file_index"] else 0
            for points, end_row in iter_points(path, receipt, config["dimension"], config["batch_size"], skip):
                if time.monotonic() - started > config["ingest_stop_seconds"]:
                    raise TimeoutError("Controlled stop: preserve recovery snapshot before the session limit")
                upsert(config, points, session)
                # Store the sample before its checkpoint; replaying a batch remains idempotent.
                if (file_index % sample_stride == 0 or not samples) and end_row - len(points) == 0:
                    point = points[0]
                    sample = {"id": point["id"], "payload": point["payload"], "vector": point["vector"][VECTOR_NAME]}
                    if all(s["id"] != point["id"] for s in samples):
                        samples.append(sample)
                        write_json(samples_path, samples)
                state.update(file_index=file_index, file_rows=end_row,
                             rows=state["rows"] + len(points), phase="ingesting")
                write_json(checkpoint_path(config), state)
                if end_row == receipt["rows"] or state["rows"] % (config["batch_size"] * 100) == 0:
                    seconds = max(0.001, time.monotonic() - started)
                    print(json.dumps({"phase": "ingesting", "part": receipt["part"], "file": path.name,
                                      "rows": state["rows"], "expected": catalog["rows"],
                                      "new_rows_per_second": round((state["rows"] - initial_rows) / seconds, 1),
                                      "elapsed_seconds": round(seconds, 1)}), flush=True)
            state.update(file_index=file_index + 1, file_rows=0)
            write_json(checkpoint_path(config), state)
    if state["rows"] != catalog["rows"] or count_points(config) != catalog["rows"]:
        raise ValueError("Committed rows or exact Qdrant count differs from the full corpus")
    state["phase"] = "ingested"
    write_json(checkpoint_path(config), state)


def wait_for_index(config):
    name = config["collection"]
    api(config, "PATCH", f"/collections/{name}", {
        "hnsw_config": {"m": config["hnsw_m"], "ef_construct": config["ef_construction"],
                        "on_disk": True, "max_indexing_threads": 2},
    })
    deadline = time.monotonic() + config["index_timeout_seconds"]
    stable = 0
    while time.monotonic() < deadline:
        info = api(config, "GET", f"/collections/{name}")
        if info["optimizer_status"] != "ok" or info["status"] == "red":
            raise RuntimeError(f"Optimizer error: {info['optimizer_status']}")
        allowance = info["segments_count"] * math.ceil(config["indexing_threshold_kb"] * 1024 / (config["dimension"] * 2))
        ready = info["status"] == "green" and info.get("indexed_vectors_count", 0) >= config["expected_chunks"] - allowance
        stable = stable + 1 if ready else 0
        print(json.dumps({"phase": "indexing", "status": info["status"], "points": info["points_count"],
                          "indexed": info.get("indexed_vectors_count", 0), "segments": info["segments_count"]}), flush=True)
        if stable >= 3:
            return info
        time.sleep(config["index_poll_seconds"])
    raise TimeoutError("HNSW optimization timed out; export recovery, not a complete snapshot")


def snapshot_raw(config):
    name = config["collection"]
    before = count_points(config)
    result = api(config, "POST", f"/collections/{name}/snapshots?wait=true", timeout=3600)
    if count_points(config) != before:
        raise ValueError("Collection changed while creating snapshot")
    raw = Path(config["state_dir"]) / "snapshots" / name / Path(result["name"]).name
    if not raw.is_file() or not tarfile.is_tarfile(raw):
        raise ValueError("Qdrant snapshot is missing or invalid")
    return raw, before


def snapshot_manifest(config, identity, state, points, complete):
    return {"schema_version": "vibiomir-qdrant-dense-v1", "complete": complete,
            "collection": config["collection"], "qdrant_version": QDRANT_VERSION,
            "signature": identity, "points": points, "checkpoint": state.copy(),
            "vector_schema": {"dense": VECTOR_NAME, "dense_datatype": "float16"},
            "payload_indexes": PAYLOAD_INDEXES, "embedding": identity["encoder"],
            "storage": {"dense_datatype": "float16", "on_disk": True},
            "parent_mapping": {"document_key": "doc_id", "parent_id_available": False}}


def verify_snapshot_restore(config, raw, manifest, samples):
    name = config["collection"] + "_restore_check"
    if any(c["name"] == name for c in api(config, "GET", "/collections")["collections"]):
        raise ValueError("Restore verification collection already exists")
    api(config, "PUT", f"/collections/{name}/snapshots/recover?wait=true",
        {"location": raw.resolve().as_uri(), "priority": "snapshot"}, timeout=3600)
    try:
        return verify_collection(config["qdrant_url"], manifest, samples, collection=name)
    finally:
        api(config, "DELETE", f"/collections/{name}?timeout=120")


def export_snapshot(config, identity, state, complete):
    raw, points = snapshot_raw(config)
    manifest = snapshot_manifest(config, identity, state, points, complete)
    output = Path(config["output"])
    samples = json.loads((output / "verification_samples.json").read_text())
    manifest["restore_verification"] = verify_snapshot_restore(config, raw, manifest, samples)
    manifest["raw_snapshot_sha256"] = checksum(raw)
    manifest["raw_snapshot_bytes"] = raw.stat().st_size
    prefix = "vibiomir_qwen3_dense" if complete else "RECOVERY_vibiomir_qwen3_dense"
    source = raw
    if raw.stat().st_size > output_budget(config):
        source = Path(config["state_dir"]) / f"{prefix}.snapshot.gz"
        print("Compressing snapshot losslessly outside Output", flush=True)
        with raw.open("rb") as reader, gzip.open(source, "wb", compresslevel=3) as writer:
            shutil.copyfileobj(reader, writer, 8 * 1024**2)
        digest = hashlib.sha256()
        with gzip.open(source, "rb") as reader:
            for block in iter(lambda: reader.read(8 * 1024**2), b""):
                digest.update(block)
        if digest.hexdigest() != manifest["raw_snapshot_sha256"]:
            raise ValueError("Compressed snapshot failed lossless verification")
    if source.stat().st_size > output_budget(config):
        raise RuntimeError(f"Snapshot exceeds Output budget; raw snapshot remains in this runtime at {raw}")
    suffix = ".snapshot.gz" if source.suffix == ".gz" else ".snapshot"
    target = output / (prefix + suffix)
    if target.exists():
        raise FileExistsError("Export already exists; choose a fresh output directory")
    partial = target.with_suffix(target.suffix + ".partial")
    shutil.copyfile(source, partial)
    manifest.update(snapshot_file=target.name, snapshot_bytes=partial.stat().st_size,
                    snapshot_sha256=checksum(partial))
    if manifest["snapshot_sha256"] != checksum(source):
        raise ValueError("Export checksum mismatch")
    partial.replace(target)
    write_json(output / "ingestion_checkpoint.json", state)
    write_json(output / "snapshot_manifest.json", manifest)
    write_json(output / "verification_report.json", manifest["restore_verification"])
    print(json.dumps({"phase": "snapshot_exported", "complete": complete,
                      "points": points, "file": target.name, "bytes": manifest["snapshot_bytes"]}), flush=True)
    return manifest


def restore_for_resume(config, identity):
    folder = Path(config["resume_from"])
    manifest = json.loads((folder / "snapshot_manifest.json").read_text())
    if manifest["signature"] != identity or manifest["qdrant_version"] != QDRANT_VERSION:
        raise ValueError("Resume snapshot belongs to a different input/configuration")
    snapshot = folder / manifest["snapshot_file"]
    if checksum(snapshot) != manifest["snapshot_sha256"]:
        raise ValueError("Resume snapshot checksum mismatch")
    raw = Path(config["state_dir"]) / "snapshots" / "resume.snapshot"
    opener = gzip.open if snapshot.suffix == ".gz" else open
    with opener(snapshot, "rb") as source, raw.open("wb") as destination:
        shutil.copyfileobj(source, destination, 8 * 1024**2)
    if checksum(raw) != manifest["raw_snapshot_sha256"]:
        raise ValueError("Unpacked resume checksum mismatch")
    api(config, "PUT", f"/collections/{config['collection']}/snapshots/recover?wait=true",
        {"location": raw.resolve().as_uri(), "priority": "snapshot"}, timeout=3600)
    if count_points(config) != manifest["points"]:
        raise ValueError("Restored snapshot exact count differs")
    samples = json.loads((folder / "verification_samples.json").read_text())
    verify_collection(config["qdrant_url"], manifest, samples)
    write_json(Path(config["output"]) / "verification_samples.json", samples)
    state = manifest["checkpoint"]
    write_json(checkpoint_path(config), state)
    return state


def smoke_test(config, catalog):
    smoke = {**config, "collection": config["collection"] + "_preflight"}
    first = catalog["files"][0]
    points, _ = next(iter_points(first["path"], first["receipt"], config["dimension"], 3))
    create_collection(smoke)
    try:
        with requests.Session() as session:
            upsert(smoke, points, session)
        identity = signature(config, catalog)
        manifest = snapshot_manifest(smoke, identity, {}, len(points), False)
        samples = [{"id": p["id"], "payload": p["payload"], "vector": p["vector"][VECTOR_NAME]} for p in points]
        raw, _ = snapshot_raw(smoke)
        verify_snapshot_restore(smoke, raw, manifest, samples)
        api(smoke, "DELETE", f"/collections/{smoke['collection']}/snapshots/{raw.name}")
        print("PREFLIGHT PASSED: real FP16 upsert, payload lookup, snapshot and restore", flush=True)
    finally:
        api(smoke, "DELETE", f"/collections/{smoke['collection']}?timeout=120")


def run_pipeline(config):
    started = time.monotonic()
    output, state_dir = Path(config["output"]), Path(config["state_dir"])
    for path in (output, state_dir, Path(config["output_budget_root"])):
        path.mkdir(parents=True, exist_ok=True)
    if (output / "snapshot_manifest.json").exists():
        raise FileExistsError("Export exists; use a fresh Output directory")
    process = log = None
    collection_ready = False
    identity = state = None
    try:
        write_json(output / "pipeline_status.json", {"success": False, "stage": "validating_inputs"})
        catalog = load_catalog(config)
        identity = signature(config, catalog)
        saved = state_dir / "run_signature.json"
        if saved.exists() and json.loads(saved.read_text()) != identity:
            raise ValueError("State belongs to another input/configuration")
        write_json(saved, identity)
        write_json(output / "input_catalog.json", catalog)
        write_json(output / "encoder_profile.json", catalog["encoder"])
        check_resources(config, catalog)
        process, log = start_server(config)
        existing = api(config, "GET", "/collections")["collections"]
        state = {"identity": identity, "rows": 0, "file_index": 0, "file_rows": 0, "phase": "new"}
        if config.get("resume_from"):
            if existing:
                raise ValueError("Resume requires new empty state, not an existing database")
            state = restore_for_resume(config, identity)
        elif checkpoint_path(config).exists():
            state = json.loads(checkpoint_path(config).read_text())
            if state["identity"] != identity:
                raise ValueError("Checkpoint identity mismatch")
        elif existing:
            raise ValueError("Existing database without matching checkpoint; restore the matching snapshot")
        if not existing and not config.get("resume_from"):
            if state["rows"]:
                raise ValueError("Checkpoint exists but database is missing; attach matching recovery snapshot")
            smoke_test(config, catalog)
        create_collection(config)
        collection_ready = True
        count = count_points(config)
        if count < state["rows"] or count > state["rows"] + config["batch_size"]:
            raise ValueError("Database count inconsistent with committed checkpoint")
        write_json(checkpoint_path(config), state)
        write_json(output / "pipeline_status.json", {"success": False, "stage": "ingesting"})
        ingest(config, catalog, state, started)
        # Keep this checkpoint snapshot in runtime scratch; export recovery on controlled failure.
        # This avoids keeping two full snapshots in the limited Kaggle Output directory.
        pre_index, _ = snapshot_raw(config)
        print(f"Pre-index runtime snapshot: {pre_index}; not yet durable across Kaggle sessions", flush=True)
        state["phase"] = "indexing"
        write_json(checkpoint_path(config), state)
        write_json(output / "pipeline_status.json", {"success": False, "stage": "indexing"})
        wait_for_index(config)
        samples = json.loads((output / "verification_samples.json").read_text())
        manifest = snapshot_manifest(config, identity, state, catalog["rows"], True)
        verify_collection(config["qdrant_url"], manifest, samples)
        write_json(output / "dense_query_example.json", {"dense_vector": samples[0]["vector"],
                   "chunk_id": samples[0]["payload"]["chunk_id"],
                   "note": "Stored-vector smoke test. Encode new queries with the pinned Qwen3 encoder."})
        state["phase"] = "indexed"
        write_json(checkpoint_path(config), state)
        export_snapshot(config, identity, state, complete=True)
        write_json(output / "pipeline_status.json", {"success": True, "stage": "snapshot_exported"})
    except (Exception, KeyboardInterrupt) as error:
        status = {"success": False, "stage": state["phase"] if state else "preflight", "error": str(error)}
        if collection_ready and state is not None:
            try:
                if count_points(config) and (output / "verification_samples.json").exists():
                    export_snapshot(config, identity, state, complete=False)
                    status["recovery_exported"] = True
            except Exception as recovery_error:
                status["recovery_error"] = str(recovery_error)
                print("Recovery export failed:", str(recovery_error), flush=True)
        write_json(output / "pipeline_status.json", status)
        print("PIPELINE FAILED:", json.dumps(status), flush=True)
        raise
    finally:
        if process is not None:
            stop_server(process, log)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run_pipeline(json.loads(args.config.read_text()))
