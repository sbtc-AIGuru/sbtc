"""Kaggle T4 x2: GTE embeddings -> disk-backed Qdrant -> portable snapshot."""

import argparse
import gc
import gzip
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import uuid
import zlib

import numpy as np
import psutil
import requests

QDRANT_VERSION = "1.19.2"
QDRANT_URL = f"https://github.com/qdrant/qdrant/releases/download/v{QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz"
QDRANT_SHA256 = "50b253243309ed0ae50a19f678f0d0adcc4f0b567b3bd2c5c0c7e02fa8404bb6"


def padded_batches(order: list[int], lengths: list[int], batch_size: int, token_budget: int):
    offset = 0
    while offset < len(order):
        longest = lengths[order[offset]]
        size = min(batch_size, max(1, token_budget // longest))
        yield order[offset:offset + size]
        offset += size

def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    vectors = np.ascontiguousarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(vectors).all() or np.any(norms <= 1e-12):
        raise ValueError("Non-finite or zero embedding; no vector was inserted")
    return vectors / norms

def encode_records(records: list[dict], tokenizer, forward, config: dict) -> tuple[np.ndarray, int]:
    tokens = tokenizer(
        [record["text"] for record in records], add_special_tokens=False,
        truncation=False, return_attention_mask=False, return_token_type_ids=False,
    )["input_ids"]
    payload = config["max_length"] - tokenizer.num_special_tokens_to_add(pair=False)
    windows, owners, weights = [], [], []
    long_chunks = 0
    for owner, ids in enumerate(tokens):
        long_chunks += len(ids) > payload
        for start in range(0, max(1, len(ids)), payload):
            piece = ids[start:start + payload]
            windows.append({"input_ids": tokenizer.build_inputs_with_special_tokens(piece)})
            owners.append(owner)
            weights.append(max(1, len(piece)))
    lengths = [len(window["input_ids"]) for window in windows]
    order = sorted(range(len(windows)), key=lengths.__getitem__, reverse=True)
    sums = np.zeros((len(records), config["dimension"]), dtype=np.float32)
    for positions in padded_batches(order, lengths, config["batch_size"], config["token_budget"]):
        vectors = forward([windows[position] for position in positions])
        for position, vector in zip(positions, vectors, strict=True):
            sums[owners[position]] += vector * weights[position]
    return normalize_vectors(sums), long_chunks

def load_encoder(config: dict):
    import torch
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("Each worker must see exactly one usable CUDA GPU")
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    torch.cuda.synchronize(device)
    tokenizer = AutoTokenizer.from_pretrained(config["model"], revision=config["revision"])
    model_config = AutoConfig.from_pretrained(
        config["model"], revision=config["revision"], trust_remote_code=True,
        code_revision=config["code_revision"],
    )
    model = AutoModel.from_pretrained(
        config["model"], revision=config["revision"], code_revision=config["code_revision"],
        config=model_config, trust_remote_code=True, attn_implementation="sdpa",
        torch_dtype=torch.float16, low_cpu_mem_usage=False, _fast_init=False,
    )
    # GTE stores these buffers outside the checkpoint. Rebuild them before CUDA.
    with torch.device("cpu"):
        model.embeddings.register_buffer(
            "position_ids", torch.arange(model_config.max_position_embeddings), persistent=False,
        )
        model.embeddings._init_rope(model_config)
    if model_config.hidden_size != config["dimension"]:
        raise ValueError("Unexpected model embedding dimension")
    model.eval().to(device)
    print(f"GPU {config['rank']}: {torch.cuda.get_device_name(0)}; SDPA; float16", flush=True)

    def forward(windows: list[dict]) -> np.ndarray:
        def infer(items: list[dict]) -> np.ndarray:
            features = tokenizer.pad(items, padding=True, return_tensors="pt")
            features = {name: tensor.to(device) for name, tensor in features.items()}
            with torch.inference_mode():
                embeddings = model(**features).last_hidden_state[:, 0].float()
            return normalize_vectors(embeddings.cpu().numpy())

        retry = False
        try:
            return infer(windows)
        except torch.cuda.OutOfMemoryError:
            if len(windows) == 1:
                raise RuntimeError("CUDA OOM at batch size 1; no chunk was skipped") from None
            retry = True
        if retry:
            # Release exception frames before retrying smaller batches.
            gc.collect()
            torch.cuda.empty_cache()
            middle = len(windows) // 2
            config["batch_size"] = min(config["batch_size"], middle)
            print(f"GPU {config['rank']}: OOM, retry batch_size={middle}", flush=True)
            return np.concatenate([forward(windows[:middle]), forward(windows[middle:])])

    return tokenizer, forward


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


def signature(config: dict) -> dict:
    return {key: config[key] for key in (
        "source_sha256", "expected_documents", "expected_chunks", "model", "revision",
        "code_revision", "dimension", "max_length", "collection",
    )}


def make_record(document: dict, child: dict, line: int) -> dict:
    text = child["chunk_text"]
    if not isinstance(text, str):
        raise ValueError(f"Non-string chunk_text at source line {line}")
    return {
        "chunk_id": child["chunk_id"], "doc_id": document["doc_id"],
        "parent_id": child["parent_id"], "chunk_order": child["chunk_order"],
        "start_char": child["start_char"], "end_char": child["end_char"],
        "source_line": line, "url": document.get("url"),
        "source_language": document.get("source_language"),
        "retrieval_eligible": child.get("retrieval_eligible"),
        "empty_text": not text.strip(), "chunk_text": text,
    }


def iter_records(source: Path, rank: int):
    with source.open(encoding="utf-8") as stream:
        for line, raw in enumerate(stream, start=1):
            if (line - 1) % 2 != rank:
                continue
            document = json.loads(raw)
            for child in document.get("children", []):
                yield make_record(document, child, line)


def validate_source(config: dict) -> dict:
    digest, compressor = hashlib.sha256(), zlib.compressobj(level=1, wbits=31)
    documents = payload_bytes = compressed_bytes = 0
    shards = [0, 0]
    with Path(config["source"]).open("rb") as stream:
        for documents, raw in enumerate(stream, start=1):
            digest.update(raw)
            document = json.loads(raw)
            for child in document.get("children", []):
                record = make_record(document, child, documents)
                payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
                payload_bytes += len(payload)
                compressed_bytes += len(compressor.compress(payload))
                shards[(documents - 1) % 2] += 1
            if documents % 200_000 == 0:
                print(f"Validate: {documents:,} documents; {sum(shards):,} chunks", flush=True)
    compressed_bytes += len(compressor.flush())
    if digest.hexdigest() != config["source_sha256"]:
        raise ValueError("Source SHA-256 differs from the uploaded ETL corpus")
    if documents != config["expected_documents"] or sum(shards) != config["expected_chunks"]:
        raise ValueError(f"Unexpected corpus counts: {documents} documents; {sum(shards)} chunks")
    return {"documents": documents, "chunks": sum(shards), "shards": shards,
            "sha256": digest.hexdigest(), "payload_bytes": payload_bytes,
            "gzip_payload_bytes": compressed_bytes}


def output_budget(config: dict) -> int:
    root = Path(config["output_budget_root"])
    used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    return max(0, min(config["output_limit_bytes"] - used,
                      shutil.disk_usage(root).free - 512 * 1024**2))


def check_resources(config: dict, source: dict) -> None:
    state = Path(config["state_dir"])
    mounts = [mount for mount in psutil.disk_partitions(all=True)
              if state.resolve().is_relative_to(Path(mount.mountpoint))]
    kind = max(mounts, key=lambda mount: len(mount.mountpoint)).fstype if mounts else "unknown"
    if kind in {"tmpfs", "ramfs"}:
        raise RuntimeError(f"Qdrant state must be on disk, not {kind}: {state}")
    vectors = config["expected_chunks"] * config["dimension"] * 4
    graph = config["expected_chunks"] * (8 * config["hnsw_m"] + 128)
    collection = vectors + graph + source["payload_bytes"]
    # Covers segment rewrites, the collection, snapshot temporary data and export.
    required = 4 * collection + 4 * 1024**3
    free = shutil.disk_usage(state).free
    print(f"Qdrant disk ({kind}): free={free / 1024**3:.2f} GiB; budget={required / 1024**3:.2f} GiB", flush=True)
    if free < required:
        raise RuntimeError("Not enough state disk space for Qdrant plus snapshot copies")
    estimated_export = vectors + graph + int(source["gzip_payload_bytes"] * 1.5) + 512 * 1024**2
    budget = output_budget(config)
    print(f"Output: remaining={budget / 1024**3:.2f} GiB; estimated compressed snapshot={estimated_export / 1024**3:.2f} GiB", flush=True)
    if budget < estimated_export:
        raise RuntimeError("Output budget is too small for the estimated snapshot; use a larger output filesystem")
    host = psutil.virtual_memory()
    maximum = Path("/sys/fs/cgroup/memory.max")
    limit = int(maximum.read_text()) if maximum.exists() and maximum.read_text().strip().isdigit() else host.total
    print(f"RAM: host={host.total / 1024**3:.1f} GiB; cgroup limit={limit / 1024**3:.1f} GiB; disk-backed vectors/payload/HNSW", flush=True)
    if min(host.total, limit) < 8 * 1024**3:
        raise RuntimeError("Two model workers plus Qdrant require at least 8 GiB RAM")


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


def create_collection(config: dict) -> None:
    name = config["collection"]
    response = requests.get(config["qdrant_url"] + f"/collections/{name}", timeout=30)
    if response.status_code != 404:
        response.raise_for_status()
        vectors = response.json()["result"]["config"]["params"]["vectors"]
        if vectors["size"] != config["dimension"] or vectors["distance"] != "Cosine":
            raise ValueError("Existing collection vector configuration does not match")
        return
    api(config, "PUT", f"/collections/{name}", {
        "vectors": {"size": config["dimension"], "distance": "Cosine", "on_disk": True,
                    "datatype": "float32"},
        "on_disk_payload": True, "shard_number": 1,
        "hnsw_config": {"m": 0, "on_disk": True, "max_indexing_threads": 2},
        "optimizers_config": {"default_segment_number": 2, "max_segment_size": 500_000,
                              "indexing_threshold": config["indexing_threshold_kb"],
                              "max_optimization_threads": 1},
    })


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "sbtc:" + chunk_id))


def upsert_batch(config: dict, records: list[dict], vectors: np.ndarray, session) -> None:
    for start in range(0, len(records), config["upsert_batch_size"]):
        rows = records[start:start + config["upsert_batch_size"]]
        points = [{"id": point_id(row["chunk_id"]), "vector": vector.tolist(), "payload": row}
                  for row, vector in zip(rows, vectors[start:start + len(rows)], strict=True)]
        # An acknowledgement can be lost after Qdrant commits. Stable UUIDs make
        # replaying this upsert safe; progress is written only after wait=true.
        for attempt in range(3):
            try:
                result = api(config, "PUT", f"/collections/{config['collection']}/points?wait=true",
                             {"points": points}, session=session)
                if result["status"] != "completed":
                    raise RuntimeError(f"Upsert was not completed: {result}")
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)


def progress_path(config: dict, rank: int) -> Path:
    return Path(config["output"]) / f"gpu{rank}.progress.json"


def run_worker(config: dict, rank: int) -> None:
    config = {**config, "rank": rank}
    progress = progress_path(config, rank)
    saved = json.loads(progress.read_text()) if progress.exists() else {"chunks": 0, "long_chunks": 0}
    count, long_chunks = saved["chunks"], saved["long_chunks"]
    expected = config["shards"][rank]
    if count == expected:
        print(f"GPU {rank}: shard already complete ({count:,} chunks)", flush=True)
        return
    if count > expected:
        raise ValueError("Checkpoint count exceeds source shard size")
    tokenizer, forward = load_encoder(config)
    smoke = [{"text": text} for text in ("English test.", "Kiểm tra tiếng Việt.", "中文测试。")]
    encode_records(smoke, tokenizer, forward, config)
    started, resumed = time.monotonic(), count
    records = []
    with requests.Session() as session:
        def commit():
            nonlocal count, long_chunks
            vectors, long_count = encode_records(
                [{"text": row["chunk_text"]} for row in records], tokenizer, forward, config,
            )
            upsert_batch(config, records, vectors, session)
            count += len(records)
            long_chunks += long_count
            write_json(progress, {"chunks": count, "long_chunks": long_chunks})
            if count % (config["buffer_size"] * 20) == 0 or count == expected:
                speed = (count - resumed) / max(0.001, time.monotonic() - started)
                print(f"GPU {rank}: {count:,}/{expected:,} chunks committed to Qdrant; {speed:.1f} chunks/s", flush=True)
            records.clear()

        for record in islice(iter_records(Path(config["source"]), rank), count, None):
            records.append(record)
            if len(records) == config["buffer_size"]:
                commit()
        if records:
            commit()
    if count != expected:
        raise ValueError(f"GPU {rank} count mismatch: {count} != {expected}")


def embed_two_gpus(config: dict, config_path: Path) -> None:
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
        raise RuntimeError("Select GPU T4 x2: two CUDA GPUs are required")
    workers = []
    try:
        for rank in range(2):
            environment = {**os.environ, "CUDA_VISIBLE_DEVICES": str(rank),
                           "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                           "TOKENIZERS_PARALLELISM": "false"}
            workers.append(subprocess.Popen([
                sys.executable, "-u", __file__, "worker", "--config", str(config_path), "--rank", str(rank),
            ], env=environment))
        while any(worker.poll() is None for worker in workers):
            if any(worker.poll() not in (None, 0) for worker in workers):
                raise RuntimeError("An embedding worker failed; stopping its peer before recovery snapshot")
            time.sleep(1)
        if any(worker.returncode for worker in workers):
            raise RuntimeError(f"Embedding workers failed: {[worker.returncode for worker in workers]}")
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()


def count_points(config: dict) -> int:
    return api(config, "POST", f"/collections/{config['collection']}/points/count", {"exact": True})["count"]


def wait_for_index(config: dict) -> dict:
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
            raise RuntimeError(f"Qdrant optimizer error: {info['optimizer_status']}")
        # Small appendable segments below indexing_threshold are intentionally
        # left as plain vectors. Do not wait for indexed_vectors_count == total.
        allowance = info["segments_count"] * math.ceil(
            config["indexing_threshold_kb"] * 1024 / (config["dimension"] * 4),
        )
        indexed = info.get("indexed_vectors_count", 0)
        ready = info["status"] == "green" and indexed >= config["expected_chunks"] - allowance
        stable = stable + 1 if ready else 0
        print(f"Index: status={info['status']}; indexed={indexed:,}; points={info['points_count']:,}; segments={info['segments_count']}", flush=True)
        if stable >= 3:
            return info
        time.sleep(config.get("index_poll_seconds", 15))
    raise TimeoutError("HNSW optimization timed out; export a recovery snapshot instead of claiming success")


def check_search(config: dict) -> None:
    name = config["collection"]
    points = api(config, "POST", f"/collections/{name}/points/scroll",
                 {"limit": 1, "with_vector": True, "with_payload": True})["points"]
    if not points or "chunk_text" not in points[0]["payload"]:
        raise ValueError("Collection has no readable point with chunk text")
    result = api(config, "POST", f"/collections/{name}/points/query", {
        "query": points[0]["vector"], "limit": 3, "with_payload": True,
    })["points"]
    if not result or result[0]["score"] < 0.99:
        raise ValueError("Stored-vector similarity smoke test failed")
    print("SEARCH PASSED: vectors and chunk payloads are readable", flush=True)


def export_snapshot(config: dict, complete: bool) -> dict:
    name = config["collection"]
    # A terminated worker can leave a previously accepted upsert on the server.
    # Record a count only when it stays stable across snapshot creation.
    for attempt in range(2):
        before = count_points(config)
        result = api(config, "POST", f"/collections/{name}/snapshots?wait=true", timeout=3600)
        points = count_points(config)
        if points == before:
            break
        if attempt == 1:
            raise RuntimeError("Collection kept changing during snapshot creation; manifest was not published")
    raw = Path(config["state_dir"]) / "snapshots" / name / Path(result["name"]).name
    if not raw.is_file() or not tarfile.is_tarfile(raw):
        raise ValueError("Qdrant did not produce a valid collection snapshot archive")
    raw_sha256 = checksum(raw)
    prefix = "sbtc_gte_multilingual" if complete else "RECOVERY_sbtc_gte_multilingual"
    source = raw
    if raw.stat().st_size > output_budget(config):
        source = Path(config["state_dir"]) / f"{prefix}.snapshot.gz"
        print("Compressing snapshot losslessly outside Kaggle Output", flush=True)
        with raw.open("rb") as reader, gzip.open(source, "wb", compresslevel=1) as writer:
            shutil.copyfileobj(reader, writer, length=8 * 1024**2)
        digest = hashlib.sha256()
        with gzip.open(source, "rb") as reader:
            for block in iter(lambda: reader.read(8 * 1024**2), b""):
                digest.update(block)
        if digest.hexdigest() != raw_sha256:
            raise ValueError("Compressed snapshot does not match the original snapshot")
    if source.stat().st_size > output_budget(config):
        raise RuntimeError(f"Snapshot exceeds Output quota even after compression. Original kept at {raw}")
    suffix = ".snapshot.gz" if source != raw else ".snapshot"
    target = Path(config["output"]) / (prefix + suffix)
    if target.exists():
        raise FileExistsError(f"Snapshot output exists: {target}")
    partial = target.with_suffix(target.suffix + ".partial")
    shutil.copyfile(source, partial)
    exported_sha256 = checksum(partial)
    if exported_sha256 != checksum(source):
        raise ValueError("Exported snapshot checksum mismatch")
    partial.replace(target)
    progress = {}
    for rank in range(2):
        path = progress_path(config, rank)
        progress[str(rank)] = json.loads(path.read_text()) if path.exists() else {"chunks": 0, "long_chunks": 0}
    manifest = {
        "complete": complete, "collection": name, "qdrant_version": QDRANT_VERSION,
        "signature": signature(config), "points": points, "progress": progress,
        "snapshot_file": target.name, "snapshot_bytes": target.stat().st_size,
        "snapshot_sha256": exported_sha256, "raw_snapshot_sha256": raw_sha256,
        "raw_snapshot_bytes": raw.stat().st_size,
        "embedding": {"pooling": "CLS", "normalized": True, "inference": "float16",
                      "storage": "float32", "long_text": "8192-token windows, content-length-weighted mean, L2"},
        "payload": "chunk_text, chunk_id, doc_id, parent_id, offsets, URL, language and flags",
    }
    write_json(Path(config["output"]) / "snapshot_manifest.json", manifest)
    print(f"{'SUCCESS' if complete else 'RECOVERY ONLY'}: {target}; {manifest['points']:,} points", flush=True)
    return manifest


def restore_for_resume(config: dict) -> None:
    folder = Path(config["resume_from"])
    manifest = json.loads((folder / "snapshot_manifest.json").read_text())
    if manifest["signature"] != signature(config) or manifest["qdrant_version"] != QDRANT_VERSION:
        raise ValueError("Resume snapshot source/model/Qdrant version does not match")
    snapshot = folder / manifest["snapshot_file"]
    if checksum(snapshot) != manifest["snapshot_sha256"]:
        raise ValueError("Resume snapshot checksum mismatch")
    # file:// recovery is restricted to the server's snapshots directory.
    raw = Path(config["state_dir"]) / "snapshots" / "resume.snapshot"
    opener = gzip.open if snapshot.suffix == ".gz" else open
    with opener(snapshot, "rb") as source, raw.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=8 * 1024**2)
    if checksum(raw) != manifest["raw_snapshot_sha256"]:
        raise ValueError("Unpacked resume snapshot checksum mismatch")
    api(config, "PUT", f"/collections/{config['collection']}/snapshots/recover?wait=true", {
        "location": raw.resolve().as_uri(), "priority": "snapshot",
    }, timeout=3600)
    if count_points(config) != manifest["points"]:
        raise ValueError("Restored snapshot point count differs from its manifest")
    for rank in range(2):
        write_json(progress_path(config, rank), manifest["progress"][str(rank)])
    print(f"Restored {manifest['points']:,} points from attached snapshot", flush=True)


def run_pipeline(config: dict, config_path: Path) -> None:
    output, state = Path(config["output"]), Path(config["state_dir"])
    for path in (output, state, Path(config["output_budget_root"])):
        path.mkdir(parents=True, exist_ok=True)
    if (output / "snapshot_manifest.json").exists():
        raise FileExistsError("Snapshot output exists; choose a new output directory")
    saved = state / "run_signature.json"
    if saved.exists() and json.loads(saved.read_text()) != signature(config):
        raise ValueError("State directory belongs to a different corpus/model; choose a new state directory")
    write_json(saved, signature(config))
    source = validate_source(config)
    write_json(output / "source_manifest.json", source)
    check_resources(config, source)
    config["shards"] = source["shards"]
    write_json(config_path, config)
    process = log = None
    collection_ready = False
    try:
        process, log = start_server(config)
        if config.get("resume_from"):
            # Restore is permitted only into an empty server owned by this run.
            if api(config, "GET", "/collections")["collections"]:
                raise ValueError("Resume requires a new empty Qdrant state directory")
            restore_for_resume(config)
        create_collection(config)
        collection_ready = True
        committed = sum(json.loads(progress_path(config, rank).read_text())["chunks"]
                        for rank in range(2) if progress_path(config, rank).exists())
        if count_points(config) < committed:
            raise ValueError("Progress files exist but Qdrant data is missing; restore the matching snapshot")
        # Snapshot/restore support is tested before the costly GPU phase by the
        # companion integration test; real server readiness is checked here.
        print("PREFLIGHT PASSED: source, storage and real Qdrant server verified", flush=True)
        embed_two_gpus(config, config_path)
        if count_points(config) != config["expected_chunks"]:
            raise ValueError("Qdrant count differs from the corpus (missing or duplicate chunk IDs)")
        wait_for_index(config)
        check_search(config)
        export_snapshot(config, complete=True)
        write_json(output / "pipeline_status.json", {"success": True, "stage": "snapshot_exported"})
    except Exception as error:
        write_json(output / "pipeline_status.json", {"success": False, "error": str(error)})
        print(f"PIPELINE FAILED: {error}", flush=True)
        if collection_ready:
            try:
                if count_points(config):
                    export_snapshot(config, complete=False)
            except Exception as recovery_error:
                print(f"Recovery snapshot failed: {recovery_error}. Database remains at {state}", flush=True)
        raise
    finally:
        if process is not None:
            stop_server(process, log)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["run", "worker"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rank", type=int, choices=[0, 1])
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.stage == "worker":
        run_worker(config, args.rank)
    else:
        run_pipeline(config, args.config)


if __name__ == "__main__":
    main()
