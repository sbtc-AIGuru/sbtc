"""Two independent T4 workers, resumable Parquet shards, lossless payloads."""

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import time
import uuid

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd


POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://vibiomir.org/chunks")
PROFILE_FIELDS = ("model_id", "revision", "dimension", "max_length", "dtype", "pooling",
                  "normalize", "document_prompt", "vector_name")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def encoder_profile(config):
    profile = {key: config[key] for key in PROFILE_FIELDS}
    profile.update(attention="sdpa", padding_side="left", truncation=False,
                   output_dtype="float32", point_id="uuid5(vibiomir namespace, chunk_id)")
    return profile


def profile_id(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


def point_id(chunk_id):
    return str(uuid.uuid5(POINT_NAMESPACE, chunk_id))


def source_records(path, shard):
    line_number = shard["start_line"]
    offset = shard["start_byte"]
    raw_hash = hashlib.sha256()
    with Path(path).open("rb") as compressed:
        with zstd.ZstdDecompressor().stream_reader(compressed) as reader:
            for line in io.BufferedReader(reader):
                raw_hash.update(line)
                yield json.loads(line), line_number, offset
                line_number += 1
                offset += len(line)
    if (line_number - shard["start_line"], offset, raw_hash.hexdigest()) != (
            shard["rows"], shard["end_byte"], shard["raw_sha256"]):
        raise ValueError("Decompressed input does not match source manifest")


def batches_by_length(lengths, max_batch_size, padded_token_budget):
    batch = []
    longest = 0
    for index in sorted(range(len(lengths)), key=lengths.__getitem__):
        next_longest = max(longest, lengths[index])
        if batch and (len(batch) >= max_batch_size or
                      next_longest * (len(batch) + 1) > padded_token_budget):
            yield batch
            batch, longest = [], 0
        batch.append(index)
        longest = max(longest, lengths[index])
    if batch:
        yield batch


def embed_records(records, tokenizer, model, config, device):
    import torch
    import torch.nn.functional as functional

    features = tokenizer([record[0]["content"] for record in records], padding=False,
                         truncation=False, add_special_tokens=True)
    lengths = [len(ids) for ids in features["input_ids"]]
    if max(lengths) > config["max_length"]:
        index = lengths.index(max(lengths))
        raise ValueError(f"Chunk {records[index][0]['chunk_id']} has {lengths[index]} tokens; "
                         "increase max_length explicitly; no content was truncated")
    vectors = np.empty((len(records), config["dimension"]), dtype=np.float32)
    queue = list(batches_by_length(lengths, config["max_batch_size"], config["padded_token_budget"]))
    oom_retries = 0
    with torch.inference_mode():
        while queue:
            indices = queue.pop(0)
            inputs = hidden = pooled = normalized = None
            try:
                inputs = tokenizer.pad([{key: value[index] for key, value in features.items()}
                                        for index in indices], padding=True, return_tensors="pt")
                inputs = {key: value.to(device) for key, value in inputs.items()}
                hidden = model(**inputs, use_cache=False, return_dict=True).last_hidden_state
                # Left padding means the final position is a real token for every row.
                pooled = hidden[:, -1].float()
                normalized = functional.normalize(pooled, p=2, dim=1)
                vectors[indices] = normalized.cpu().numpy()
            except torch.OutOfMemoryError:
                if len(indices) == 1:
                    raise
                oom_retries += 1
                middle = len(indices) // 2
                queue[0:0] = [indices[:middle], indices[middle:]]
            finally:
                del inputs, hidden, pooled, normalized
            if oom_retries:
                torch.cuda.empty_cache()
    norms = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(vectors).all() or not np.allclose(norms, 1, atol=2e-5):
        raise ValueError("Invalid embedding vectors")
    return vectors, lengths, oom_retries


def parquet_schema(dimension, metadata):
    return pa.schema([
        ("point_id", pa.string()), ("chunk_id", pa.string()), ("doc_id", pa.int64()),
        ("source_line", pa.int64()), ("source_byte", pa.int64()),
        ("content", pa.large_string()), ("content_origin", pa.string()),
        ("token_count", pa.int32()), ("input_token_count", pa.int32()),
        ("content_sha256", pa.string()), ("payload_json", pa.large_string()),
        ("vector", pa.list_(pa.float32(), dimension)),
    ], metadata={b"vibiomir_embedding": json.dumps(metadata, sort_keys=True).encode()})


def write_shard(path, records, vectors, lengths, config, source_manifest, gpu):
    profile = encoder_profile(config)
    metadata = dict(schema_version="vibiomir-embedding-v1", encoder=profile,
                    profile_id=profile_id(profile), source_sha256=source_manifest["source_sha256"],
                    part=config["part"], gpu=gpu)
    columns = {name: [] for name in parquet_schema(config["dimension"], metadata).names if name != "vector"}
    for (record, line_number, offset), length in zip(records, lengths):
        if "_embedding" in record:
            raise ValueError("Input already contains reserved _embedding metadata")
        content_hash = hashlib.sha256(record["content"].encode()).hexdigest()
        payload = dict(record)
        payload["_embedding"] = dict(source_file=source_manifest["source_file"],
            source_sha256=source_manifest["source_sha256"], source_line=line_number,
            source_byte=offset, content_sha256=content_hash, profile_id=metadata["profile_id"],
            model_id=config["model_id"], revision=config["revision"], part=config["part"],
            gpu=gpu, input_token_count=length, truncated=False)
        values = dict(point_id=point_id(record["chunk_id"]), chunk_id=record["chunk_id"],
                      doc_id=record["doc_id"], source_line=line_number, source_byte=offset,
                      content=record["content"], content_origin=record.get("content_origin"),
                      token_count=record.get("token_count"), input_token_count=length,
                      content_sha256=content_hash, payload_json=json.dumps(payload, ensure_ascii=False))
        for key, value in values.items():
            columns[key].append(value)
    schema = parquet_schema(config["dimension"], metadata)
    arrays = [pa.array(columns[field.name], type=field.type) for field in schema if field.name != "vector"]
    arrays.append(pa.FixedSizeListArray.from_arrays(pa.array(vectors.ravel()), config["dimension"]))
    table = pa.Table.from_arrays(arrays, schema=schema)
    temporary = Path(str(path) + ".partial")
    pq.write_table(table, temporary, compression="zstd", compression_level=3,
                   row_group_size=1024, use_dictionary=["content_origin"])
    temporary.replace(path)
    receipt = dict(file=path.name, rows=len(records), sha256=file_hash(path),
                   start_line=records[0][1], end_line=records[-1][1],
                   start_byte=records[0][2], part=config["part"], gpu=gpu,
                   source_sha256=source_manifest["source_sha256"], profile_id=metadata["profile_id"],
                   min_tokens=min(lengths), max_tokens=max(lengths))
    atomic_json(Path(str(path) + ".json"), receipt)
    return receipt


def validate_shard(path, receipt, config, source_manifest):
    if receipt["profile_id"] != profile_id(encoder_profile(config)):
        raise ValueError("Checkpoint encoder configuration differs")
    if receipt["source_sha256"] != source_manifest["source_sha256"]:
        raise ValueError("Checkpoint corpus differs")
    if file_hash(path) != receipt["sha256"]:
        raise ValueError(f"Checkpoint checksum mismatch: {path}")
    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows != receipt["rows"]:
        raise ValueError("Checkpoint row count differs")
    if receipt["rows"] != receipt["end_line"] - receipt["start_line"] + 1:
        raise ValueError("Checkpoint has inconsistent source range")
    metadata = json.loads(parquet.schema_arrow.metadata[b"vibiomir_embedding"])
    if metadata["profile_id"] != receipt["profile_id"] or metadata["source_sha256"] != receipt["source_sha256"]:
        raise ValueError("Parquet encoder/source metadata differs")
    next_line = receipt["start_line"]
    for batch in parquet.iter_batches(batch_size=1024, columns=["source_line", "vector"]):
        lines = batch.column(0).to_numpy()
        if not np.array_equal(lines, np.arange(next_line, next_line + len(lines))):
            raise ValueError("Checkpoint has missing or reordered rows")
        next_line += len(lines)
        values = batch.column(1).values.to_numpy().reshape(len(lines), config["dimension"])
        if not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=2e-5):
            raise ValueError("Checkpoint contains invalid vectors")


def restore_shards(output, shard, config, source_manifest, gpu):
    candidates = {}
    for root in [output, *map(Path, config["resume_roots"])]:
        if not root.is_dir():
            raise ValueError(f"Resume directory does not exist: {root}")
        for path in root.glob(f"p{config['part']}-gpu{gpu}-*.parquet.json"):
            receipt = json.loads(path.read_text())
            if Path(receipt["file"]).name != receipt["file"]:
                raise ValueError("Invalid checkpoint filename")
            key = receipt["start_line"]
            if key in candidates and candidates[key][1] != receipt:
                raise ValueError("Conflicting checkpoints for the same source range")
            candidates[key] = (path.parent / receipt["file"], receipt)
    receipts = []
    next_line = shard["start_line"]
    for source, receipt in sorted(candidates.values(), key=lambda item: item[1]["start_line"]):
        if receipt["start_line"] != next_line or receipt["end_line"] > shard["end_line"]:
            raise ValueError("Checkpoint is not a contiguous prefix of this GPU's source range")
        if receipt["part"] != config["part"] or receipt["gpu"] != gpu:
            raise ValueError("Checkpoint belongs to another worker")
        validate_shard(source, receipt, config, source_manifest)
        destination = output / receipt["file"]
        if source.resolve() != destination.resolve():
            temporary = Path(str(destination) + ".partial")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
            atomic_json(Path(str(destination) + ".json"), receipt)
        receipts.append(receipt)
        next_line = receipt["end_line"] + 1
    return receipts


def run(config):
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer

    started = time.time()
    rank = int(os.environ["LOCAL_RANK"])
    if int(os.environ.get("WORLD_SIZE", "0")) != 2 or torch.cuda.device_count() != 2:
        raise RuntimeError("Exactly two visible GPUs and two torchrun workers are required")
    device = f"cuda:{rank}"
    torch.cuda.set_device(rank)
    name = torch.cuda.get_device_name(rank)
    if config["require_t4"] and "T4" not in name:
        raise RuntimeError(f"GPU {rank} is {name}; select Kaggle GPU T4 x2")
    torch.set_num_threads(2)
    print(f"[GPU {rank}] {name}; loading a dedicated model replica", flush=True)
    inputs = Path(config["input_root"])
    manifests = list(inputs.rglob("source_manifest.json"))
    matches = [(path, json.loads(path.read_text())) for path in manifests]
    matches = [(path, data) for path, data in matches
               if data.get("source_sha256") == config["expected_source_sha256"]]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one matching source manifest, found {len(matches)}")
    manifest_path, source_manifest = matches[0]
    shard = next(s for s in source_manifest["shards"] if s["part"] == config["part"] and s["gpu"] == rank)
    source = manifest_path.parent / shard["file"]
    if file_hash(source) != shard["compressed_sha256"]:
        raise ValueError("Compressed input checksum mismatch")
    output = Path(config["output_root"]) / f"part-{config['part']}"
    output.mkdir(parents=True, exist_ok=True)
    receipts = restore_shards(output, shard, config, source_manifest, rank)
    resumed = sum(item["rows"] for item in receipts)
    # Both workers share HF cache; Hub file locks protect the download.
    model_path = snapshot_download(config["model_id"], revision=config["revision"],
                                   allow_patterns=["*.json", "*.txt", "*.safetensors"], max_workers=2)
    tokenizer = AutoTokenizer.from_pretrained(model_path, padding_side="left")
    model = AutoModel.from_pretrained(model_path, torch_dtype=torch.float16,
                                     attn_implementation="sdpa").to(device).eval()
    if model.config.hidden_size != config["dimension"]:
        raise ValueError("Unexpected model embedding dimension")
    pending = []
    origins = Counter()
    new_rows = 0
    total_oom = 0
    inference_start = time.time()

    def commit(records):
        nonlocal new_rows, total_oom
        vectors, lengths, oom = embed_records(records, tokenizer, model, config, device)
        path = output / f"p{config['part']}-gpu{rank}-{records[0][1]:09d}.parquet"
        receipt = write_shard(path, records, vectors, lengths, config, source_manifest, rank)
        receipts.append(receipt)
        new_rows += len(records)
        total_oom += oom
        origins.update(row[0].get("content_origin", "unknown") for row in records)
        seconds = time.time() - inference_start
        rate = new_rows / max(seconds, 1)
        progress = dict(gpu=rank, device=name, rows=resumed + new_rows, expected_rows=shard["rows"],
                        rows_per_second=round(rate, 2),
                        eta_hours=round((shard["rows"] - resumed - new_rows) / max(rate, .001) / 3600, 2),
                        max_allocated_gib=round(torch.cuda.max_memory_allocated(rank) / 2**30, 3))
        atomic_json(output / f"progress-gpu{rank}.json", progress)
        print(json.dumps(progress), flush=True)

    for record in source_records(source, shard):
        if record[1] < shard["start_line"] + resumed:
            continue
        if time.time() >= config["deadline_unix"]:
            break
        pending.append(record)
        if len(pending) == config["output_rows"]:
            commit(pending)
            pending = []
    if pending:
        commit(pending)
    count = sum(item["rows"] for item in receipts)
    worker = dict(run_id=config["run_id"], gpu=rank, device=name, rows=count, expected_rows=shard["rows"],
                  resumed_rows=resumed, new_rows=new_rows, complete=count == shard["rows"],
                  elapsed_seconds=round(time.time() - started, 2), oom_batch_splits=total_oom,
                  new_content_origins=dict(origins), files=receipts,
                  peak_allocated_gib=round(torch.cuda.max_memory_allocated(rank) / 2**30, 3))
    atomic_json(output / f"worker-gpu{rank}.json", worker)
    # Release GPU memory before waiting for the other worker's final receipt.
    del model
    torch.cuda.empty_cache()
    if rank == 0:
        other = output / "worker-gpu1.json"
        while True:
            other_worker = json.loads(other.read_text()) if other.exists() else {}
            if other_worker.get("run_id") == config["run_id"]:
                break
            time.sleep(2)
        workers = [worker, other_worker]
        if any(w["rows"] == 0 for w in workers):
            raise RuntimeError("Both GPUs must process nonempty source partitions")
        summary = dict(schema_version="vibiomir-embedding-v1", part=config["part"],
                       complete=all(w["complete"] for w in workers),
                       rows=sum(w["rows"] for w in workers),
                       expected_rows=sum(w["expected_rows"] for w in workers),
                       source=source_manifest, encoder=encoder_profile(config),
                       profile_id=profile_id(encoder_profile(config)), gpu_workers=workers,
                       files=[entry for w in workers for entry in w["files"]],
                       elapsed_seconds=round(time.time() - started, 2))
        atomic_json(output / "manifest.json", summary)
        print(json.dumps(dict(part=config["part"], complete=summary["complete"],
                              rows=summary["rows"], expected_rows=summary["expected_rows"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args()
    run(json.loads(Path(arguments.config).read_text()))
