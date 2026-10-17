"""Standalone runner embedded in the Kaggle two-GPU GTE/HNSW notebook."""

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from time import monotonic
from itertools import islice

import faiss
import numpy as np
import psutil

CGROUP_ROOT = Path("/sys/fs/cgroup")


def write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def iter_chunks(source: Path, rank: int):
    # Split documents before parsing: each GPU reads half of the JSON objects.
    with source.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if (line_number - 1) % 2 != rank:
                continue
            document = json.loads(line)
            for position, child in enumerate(document.get("children", [])):
                text = child["chunk_text"]
                if not isinstance(text, str):
                    raise ValueError(f"Non-string chunk_text at line {line_number}, child {position}")
                yield {
                    "chunk_id": child["chunk_id"], "doc_id": document["doc_id"],
                    "parent_id": child["parent_id"], "chunk_order": child["chunk_order"],
                    "start_char": child["start_char"], "end_char": child["end_char"],
                    "source_line": line_number, "empty_text": not text.strip(),
                    "retrieval_eligible": child.get("retrieval_eligible"), "text": text,
                }


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


def run_worker(config: dict, rank: int) -> None:
    config = {**config, "rank": rank}
    scratch = Path(config["scratch"])
    done = scratch / f"gpu{rank}.done.json"
    if done.exists():
        print(f"GPU {rank}: completed shard already exists", flush=True)
        return
    tokenizer, forward = load_encoder(config)
    smoke = [{"text": text} for text in ("English test.", "Kiểm tra tiếng Việt.", "中文测试。")]
    encode_records(smoke, tokenizer, forward, config)
    progress_path = scratch / f"gpu{rank}.progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {
        "chunks": 0, "long_chunks": 0, "empty_chunks": 0, "vector_bytes": 0, "metadata_bytes": 0,
    }
    count, long_chunks, empty_chunks = (progress[key] for key in ("chunks", "long_chunks", "empty_chunks"))
    resumed_count = count
    if progress["vector_bytes"] != count * config["dimension"] * 4:
        raise ValueError("Checkpoint vector byte count does not match committed chunk count")
    started = monotonic()
    vectors_path, mapping_path = scratch / f"gpu{rank}.f32", scratch / f"gpu{rank}.jsonl"
    for path, key in ((vectors_path, "vector_bytes"), (mapping_path, "metadata_bytes")):
        if progress[key] and (not path.exists() or path.stat().st_size < progress[key]):
            raise ValueError(f"Checkpoint file is shorter than committed progress: {path}")
    with vectors_path.open("r+b" if vectors_path.exists() else "w+b") as vectors_file, (
        mapping_path.open("r+b" if mapping_path.exists() else "w+b")
    ) as metadata_file:
        # Discard only an uncommitted tail left by an interrupted batch.
        for stream, key in ((vectors_file, "vector_bytes"), (metadata_file, "metadata_bytes")):
            stream.seek(progress[key])
            stream.truncate()
        records = []

        def write_batch() -> None:
            nonlocal count, long_chunks, empty_chunks
            vectors, long_count = encode_records(records, tokenizer, forward, config)
            vectors.tofile(vectors_file)
            for record in records:
                record.pop("text")
                empty_chunks += record["empty_text"]
                metadata_file.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
            count += len(records)
            long_chunks += long_count
            for stream in (vectors_file, metadata_file):
                stream.flush()
                os.fsync(stream.fileno())
            write_json_atomic(progress_path, {
                "chunks": count, "long_chunks": long_chunks, "empty_chunks": empty_chunks,
                "vector_bytes": vectors_file.tell(), "metadata_bytes": metadata_file.tell(),
            })
            if count % (config["buffer_size"] * 20) == 0:
                elapsed = monotonic() - started
                print(f"GPU {rank}: {count:,} chunks; {(count - resumed_count) / elapsed:.1f} chunks/s", flush=True)
            records.clear()

        for record in islice(iter_chunks(Path(config["source"]), rank), count, None):
            records.append(record)
            if len(records) == config["buffer_size"]:
                write_batch()
        if records:
            write_batch()
    result = {"chunks": count, "long_chunks": long_chunks, "empty_chunks": empty_chunks,
              "resumed_chunks": resumed_count,
              "seconds": round(monotonic() - started, 2)}
    write_json_atomic(done, result)
    print(f"GPU {rank} complete: {result}", flush=True)


def prepare_source(config: dict) -> dict:
    source = Path(config["source"])
    digest = hashlib.sha256()
    documents = chunks = 0
    with source.open("rb") as stream:
        for line in stream:
            digest.update(line)
            document = json.loads(line)
            documents += 1
            chunks += len(document.get("children", []))
            if documents % 200_000 == 0:
                print(f"Validate: {documents:,} documents; {chunks:,} chunks", flush=True)
    if digest.hexdigest() != config["source_sha256"]:
        raise ValueError("Source SHA-256 differs from the uploaded ETL corpus")
    if documents != config["expected_documents"] or chunks != config["expected_chunks"]:
        raise ValueError(f"Unexpected corpus counts: documents={documents}, chunks={chunks}")
    return {"documents": documents, "chunks": chunks, "sha256": digest.hexdigest()}


def embedding_signature(config: dict) -> dict:
    # HNSW parameters and output paths can change without recomputing embeddings.
    return {key: config[key] for key in (
        "source_sha256", "expected_documents", "expected_chunks", "model", "revision",
        "code_revision", "dimension", "max_length",
    )}


def embed_two_gpus(config: dict, config_path: Path) -> None:
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
        raise RuntimeError("Select GPU T4 x2 in Kaggle Settings; two CUDA GPUs are required")
    scratch = Path(config["scratch"])
    scratch.mkdir(parents=True, exist_ok=True)
    signature = scratch / "config.json"
    if signature.exists() and json.loads(signature.read_text()) != embedding_signature(config):
        raise ValueError("Scratch directory belongs to another configuration; choose a new directory")
    write_json_atomic(signature, embedding_signature(config))
    completed_bytes = sum(
        (scratch / f"gpu{rank}.f32").stat().st_size for rank in range(2)
        if (scratch / f"gpu{rank}.done.json").exists()
    )
    required_bytes = max(0, config["expected_chunks"] * config["dimension"] * 4 - completed_bytes)
    if shutil.disk_usage(scratch).free < required_bytes + 2 * 1024**3:
        raise RuntimeError("Not enough scratch disk space for float32 embeddings and mapping")
    counts = prepare_source(config)
    write_json_atomic(scratch / "source.json", counts)
    workers = []
    for rank in range(2):
        environment = {**os.environ, "CUDA_VISIBLE_DEVICES": str(rank),
                       "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "TOKENIZERS_PARALLELISM": "false"}
        workers.append(subprocess.Popen(
            [sys.executable, "-u", __file__, "worker", "--config", str(config_path), "--rank", str(rank)],
            env=environment,
        ))
    try:
        codes = [worker.wait() for worker in workers]
    except BaseException:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            worker.wait()
        raise
    if any(codes):
        raise RuntimeError(f"Embedding workers failed: {codes}; completed shards are kept for retry")


def create_index(dimension: int, count: int, config: dict):
    index = faiss.IndexHNSWFlat(dimension, config["hnsw_m"], faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = config["ef_construction"]
    index.hnsw.efSearch = config["ef_search"]
    # resize then shrink retains C++ capacity, avoiding a second full vector copy.
    storage = faiss.downcast_index(index.storage)
    allocations = [
        (storage.codes, count * dimension * 4),
        (index.hnsw.neighbors, count * (2 * config["hnsw_m"] + 4)),
        (index.hnsw.levels, count), (index.hnsw.offsets, count + 1),
    ]
    for vector, capacity in allocations:
        original_size = vector.size()
        vector.resize(capacity)
        vector.resize(original_size)
    return index


def memory_snapshot() -> dict:
    host = psutil.virtual_memory()
    result = {"host_total": host.total, "host_available": host.available,
              "available": host.available}
    maximum, usage = CGROUP_ROOT / "memory.max", CGROUP_ROOT / "memory.current"
    if maximum.exists() and usage.exists() and maximum.read_text().strip().isdigit():
        limit, current = int(maximum.read_text()), int(usage.read_text())
        statistics = CGROUP_ROOT / "memory.stat"
        stats = dict((key, int(value)) for key, value in (
            line.split() for line in statistics.read_text().splitlines()
        )) if statistics.exists() else {}
        # Disk page cache can be evicted. tmpfs/shmem and dirty pages cannot be
        # treated as immediately reclaimable free RAM.
        file_lru = stats.get("inactive_file", 0) + stats.get("active_file", 0)
        clean_file = max(0, stats.get("file", file_lru) - stats.get("shmem", 0)
                         - stats.get("file_dirty", 0) - stats.get("file_writeback", 0))
        reclaimable = min(file_lru, clean_file)
        available = max(0, min(limit, limit - current + reclaimable))
        result.update(cgroup_limit=limit, cgroup_current=current,
                      reclaimable_file_cache=reclaimable, shmem=stats.get("shmem", 0),
                      available=min(host.available, available))
    return result


def available_memory() -> int:
    return memory_snapshot()["available"]


def index_bytes(config: dict) -> int:
    return config["expected_chunks"] * (4 * config["dimension"] + 4 * (2 * config["hnsw_m"] + 4) + 12)


def check_memory(config: dict) -> dict:
    snapshot = memory_snapshot()
    required = index_bytes(config) + 2 * 1024**3
    print("RAM diagnostics (bytes):", json.dumps({**snapshot, "required": required}), flush=True)
    if snapshot["available"] < required:
        raise RuntimeError(
            f"HNSW needs {required / 1024**3:.2f} GiB including headroom; "
            f"available after reclaimable disk cache: {snapshot['available'] / 1024**3:.2f} GiB"
        )
    return snapshot


def filesystem_type(path: Path) -> str:
    path = path.resolve()
    mounts = [mount for mount in psutil.disk_partitions(all=True)
              if path.is_relative_to(Path(mount.mountpoint))]
    return max(mounts, key=lambda mount: len(mount.mountpoint)).fstype if mounts else "unknown"


def check_disk_space(config: dict) -> None:
    scratch, output = Path(config["scratch"]), Path(config["output"])
    temporary = Path(config.get("build_temp", config["output"]))
    archive = Path(config.get("checkpoint_archive", config["scratch"])).parent
    checkpoint_bytes = config["expected_chunks"] * (config["dimension"] * 4 + 512)
    output_bytes = index_bytes(config) + config["expected_chunks"] * 512
    # During a cross-device move, source and destination coexist until copying
    # finishes. On one device shutil.move renames without another full copy.
    phases = [
        [(scratch, checkpoint_bytes)],
        [(scratch, checkpoint_bytes), (temporary, output_bytes)],
        [(scratch, checkpoint_bytes), (temporary, output_bytes)]
        + ([(archive, checkpoint_bytes)] if scratch.stat().st_dev != archive.stat().st_dev else []),
        [(archive, checkpoint_bytes), (temporary, output_bytes)]
        + ([(output, output_bytes)] if temporary.stat().st_dev != output.stat().st_dev else []),
    ]
    required, paths = {}, {}
    for phase in phases:
        totals = {}
        for path, size in phase:
            device = path.stat().st_dev
            paths[device] = path
            totals[device] = totals.get(device, 0) + size
        for device, size in totals.items():
            required[device] = max(required.get(device, 0), size)
    existing = sum(path.stat().st_size for path in scratch.glob("gpu*.*") if path.is_file())
    for device, size in required.items():
        path = paths[device]
        credit = existing if device == scratch.stat().st_dev else 0
        remaining = max(0, size - credit) + 1024**3
        free = shutil.disk_usage(path).free
        print(f"Disk budget: {path}; required free={remaining / 1024**3:.2f} GiB; free={free / 1024**3:.2f} GiB", flush=True)
        if free < remaining:
            raise RuntimeError(f"Not enough disk space on filesystem containing {path}")


def preflight(config: dict) -> None:
    scratch, output = Path(config["scratch"]), Path(config["output"])
    temporary = Path(config["build_temp"])
    archive = Path(config["checkpoint_archive"])
    if archive.resolve().is_relative_to(scratch.resolve()) or scratch.resolve().is_relative_to(archive.resolve()):
        raise ValueError("Checkpoint archive must be separate from active checkpoints")
    if archive.exists():
        raise FileExistsError(f"Checkpoint archive already exists: {archive}")
    if (output / "build_manifest.json").exists():
        raise FileExistsError("A completed index already exists in the output directory")
    for path in (scratch, output, temporary, archive.parent):
        path.mkdir(parents=True, exist_ok=True)
        kind = filesystem_type(path)
        print(f"Storage: {path}; filesystem={kind}; free={shutil.disk_usage(path).free / 1024**3:.1f} GiB", flush=True)
        if kind in {"tmpfs", "ramfs"}:
            raise RuntimeError(f"Use a disk-backed directory instead of {kind}: {path}")
    resume = config.get("resume_from")
    if resume and not (scratch / "config.json").exists():
        previous = Path(resume)
        if json.loads((previous / "config.json").read_text()) != embedding_signature(config):
            raise ValueError("Resume checkpoints use different source/model settings")
        for name in ("source.json", *(f"gpu{rank}.{suffix}" for rank in range(2)
                     for suffix in ("f32", "jsonl", "progress.json", "done.json")), "config.json"):
            if (previous / name).exists():
                shutil.copy2(previous / name, scratch / name)
    snapshot = check_memory(config)
    check_disk_space(config)
    # This runs in its own process before loading models. A genuine allocation
    # failure is discovered now, not after several hours of embedding.
    probe = create_index(config["dimension"], config["expected_chunks"], config)
    print(f"Full HNSW capacity allocation passed; RSS={psutil.Process().memory_info().rss / 1024**3:.2f} GiB", flush=True)
    del probe
    gc.collect()
    write_json_atomic(output / "preflight.json", snapshot)
    print("PREFLIGHT PASSED: RAM allocation and disk-backed storage verified", flush=True)


def build_index(config: dict) -> None:
    scratch, output = Path(config["scratch"]), Path(config["output"])
    if json.loads((scratch / "config.json").read_text()) != embedding_signature(config):
        raise ValueError("Embedding configuration does not match the current configuration")
    shards = [json.loads((scratch / f"gpu{rank}.done.json").read_text()) for rank in range(2)]
    count = sum(shard["chunks"] for shard in shards)
    if count != config["expected_chunks"]:
        raise ValueError(f"Embedding count mismatch: {count}")
    check_memory(config)
    output.mkdir(parents=True, exist_ok=True)
    final = output / "gte_multilingual_hnsw_flat.faiss"
    metadata = output / "chunk_mapping.sqlite"
    if any(path.exists() for path in (final, metadata, output / "build_manifest.json")):
        raise FileExistsError("Completed output exists; use a new output directory")
    temporary = Path(config.get("build_temp", config["output"]))
    temporary.mkdir(parents=True, exist_ok=True)
    check_disk_space(config)
    partial_index = temporary / "gte_multilingual_hnsw_flat.faiss.partial"
    partial_metadata = temporary / "chunk_mapping.sqlite.partial"
    if partial_index.exists() or partial_metadata.exists():
        raise FileExistsError("Partial output exists; inspect it or choose a new output directory")
    faiss.omp_set_num_threads(config["faiss_threads"])
    index = create_index(config["dimension"], count, config)
    started = monotonic()
    with sqlite3.connect(partial_metadata) as database:
        database.execute("""CREATE TABLE chunks (
            vector_id INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE,
            doc_id INTEGER NOT NULL, parent_id TEXT, chunk_order INTEGER,
            start_char INTEGER, end_char INTEGER, source_line INTEGER,
            empty_text INTEGER NOT NULL, retrieval_eligible INTEGER
        )""")
        for rank, shard in enumerate(shards):
            vector_path = scratch / f"gpu{rank}.f32"
            if vector_path.stat().st_size != shard["chunks"] * config["dimension"] * 4:
                raise ValueError(f"Incomplete embedding shard {rank}")
            with vector_path.open("rb") as vectors_file, (
                scratch / f"gpu{rank}.jsonl"
            ).open(encoding="utf-8") as mapping_file:
                processed = 0
                while processed < shard["chunks"]:
                    batch_size = min(config["add_batch_size"], shard["chunks"] - processed)
                    vectors = np.fromfile(vectors_file, dtype=np.float32, count=batch_size * config["dimension"])
                    vectors = vectors.reshape(batch_size, config["dimension"])
                    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
                        raise ValueError("Stored embeddings must be finite and L2 normalized")
                    base = index.ntotal
                    rows = []
                    for offset in range(batch_size):
                        record = json.loads(next(mapping_file))
                        rows.append((base + offset, *(record[key] for key in (
                            "chunk_id", "doc_id", "parent_id", "chunk_order", "start_char",
                            "end_char", "source_line", "empty_text", "retrieval_eligible",
                        ))))
                    database.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                    index.add(vectors)
                    database.commit()
                    processed += batch_size
                    elapsed = monotonic() - started
                    print(f"HNSW: {index.ntotal:,}/{count:,}; {index.ntotal / elapsed:.1f} vectors/s", flush=True)
                if mapping_file.readline():
                    raise ValueError(f"Extra mapping rows in shard {rank}")
        if database.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] != index.ntotal:
            raise ValueError("Vector count and metadata count differ")
    faiss.write_index(index, str(partial_index))
    del index
    gc.collect()
    # Reload only after releasing the first index, keeping peak RAM bounded.
    verified = faiss.read_index(str(partial_index))
    if verified.ntotal != count or verified.d != config["dimension"]:
        raise ValueError("Saved FAISS index dimensions or count differ")
    if not isinstance(verified, faiss.IndexHNSWFlat) or verified.metric_type != faiss.METRIC_INNER_PRODUCT:
        raise ValueError("Saved index is not HNSW Flat with inner product")
    del verified
    gc.collect()
    archive = config.get("checkpoint_archive")
    if archive:
        # Keep recovery files in Output on failure. After successful validation,
        # move them outside Output so checkpoint + index do not exceed its quota.
        if Path(archive).exists():
            raise FileExistsError(f"Checkpoint archive already exists: {archive}")
        shutil.move(str(scratch), archive)
    shutil.move(str(partial_metadata), str(metadata))
    shutil.move(str(partial_index), str(final))
    manifest = {**config, "chunks": count, "shards": shards,
                "faiss_version": faiss.__version__, "numpy_version": np.__version__,
                "index_type": "IndexHNSWFlat", "pooling": "CLS", "normalized": True,
                "long_text": "token-window length-weighted mean followed by L2 normalization",
                "vector_order": "GPU 0 shard followed by GPU 1 shard; see SQLite vector_id",
                "build_seconds": round(monotonic() - started, 2), "index_bytes": final.stat().st_size}
    (output / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Ready: {final}; {count:,} vectors", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["preflight", "embed", "worker", "build"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rank", type=int, choices=[0, 1])
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.stage == "preflight":
        preflight(config)
    elif args.stage == "embed":
        embed_two_gpus(config, args.config)
    elif args.stage == "worker":
        run_worker(config, args.rank)
    else:
        build_index(config)


if __name__ == "__main__":
    main()
