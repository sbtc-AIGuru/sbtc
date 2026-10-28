"""Validate both embedding parts and stream idempotent upserts to Qdrant."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import numpy as np
import pyarrow.parquet as pq


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_parts(roots):
    parts = []
    for root in map(Path, roots):
        manifest = json.loads((root / "manifest.json").read_text())
        if not manifest["complete"] or manifest["rows"] != manifest["expected_rows"]:
            raise ValueError(f"Incomplete embedding output: {root}")
        parts.append((root, manifest))
    if sorted(manifest["part"] for _, manifest in parts) != [1, 2]:
        raise ValueError("Supply exactly one complete part 1 and one complete part 2")
    first = parts[0][1]
    receipts = []
    for root, manifest in parts:
        if manifest["source"] != first["source"] or manifest["encoder"] != first["encoder"]:
            raise ValueError("Parts have different source data or encoder configurations")
        computed_profile = hashlib.sha256(json.dumps(manifest["encoder"], sort_keys=True).encode()).hexdigest()
        if manifest["profile_id"] != computed_profile:
            raise ValueError("Invalid encoder profile ID")
        if manifest["rows"] != sum(entry["rows"] for entry in manifest["files"]):
            raise ValueError("Manifest file counts differ")
        for receipt in manifest["files"]:
            if Path(receipt["file"]).name != receipt["file"]:
                raise ValueError("Invalid Parquet filename")
            if receipt["part"] != manifest["part"] or receipt["profile_id"] != computed_profile:
                raise ValueError("File belongs to another part or encoder")
            if receipt["source_sha256"] != first["source"]["source_sha256"]:
                raise ValueError("File belongs to another source")
            receipts.append((root / receipt["file"], receipt))
    next_line = 1
    for path, receipt in sorted(receipts, key=lambda item: item[1]["start_line"]):
        if receipt["start_line"] != next_line or receipt["end_line"] - next_line + 1 != receipt["rows"]:
            raise ValueError("Missing or overlapping source ranges between parts")
        if file_hash(path) != receipt["sha256"]:
            raise ValueError(f"Parquet checksum differs: {path}")
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows != receipt["rows"]:
            raise ValueError("Parquet row count differs")
        metadata = json.loads(parquet.schema_arrow.metadata[b"vibiomir_embedding"])
        if metadata["profile_id"] != computed_profile or metadata["source_sha256"] != receipt["source_sha256"]:
            raise ValueError("Parquet metadata differs")
        next_line = receipt["end_line"] + 1
    if next_line - 1 != first["source"]["total_rows"]:
        raise ValueError("The two parts do not cover the full corpus")
    return first, sorted(receipts, key=lambda item: item[1]["start_line"])


def iter_points(path, dimension, batch_size, receipt):
    expected_line = receipt["start_line"]
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "https://vibiomir.org/chunks")
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        data = batch.to_pydict()
        vectors = np.asarray(data["vector"], dtype=np.float32)
        if vectors.shape != (batch.num_rows, dimension) or not np.isfinite(vectors).all():
            raise ValueError("Invalid embedding shape or values")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-5):
            raise ValueError("Vectors are not normalized")
        payloads = []
        for index, value in enumerate(data["payload_json"]):
            payload = json.loads(value)
            metadata = payload["_embedding"]
            content_hash = hashlib.sha256(payload["content"].encode()).hexdigest()
            if (data["source_line"][index] != expected_line or metadata["source_line"] != expected_line
                    or metadata["source_sha256"] != receipt["source_sha256"]
                    or metadata["profile_id"] != receipt["profile_id"]
                    or payload["chunk_id"] != data["chunk_id"][index]
                    or payload["doc_id"] != data["doc_id"][index]
                    or content_hash != data["content_sha256"][index]
                    or metadata["content_sha256"] != content_hash
                    or payload["content"] != data["content"][index]
                    or str(uuid.uuid5(namespace, payload["chunk_id"])) != data["point_id"][index]):
                raise ValueError("Point ID, payload or source mapping differs")
            payloads.append(payload)
            expected_line += 1
        yield data["point_id"], vectors, payloads
    if expected_line != receipt["end_line"] + 1:
        raise ValueError("Parquet source coverage differs")


def import_parts(roots, url, api_key, collection, checkpoint, batch_size=128, validate_only=False):
    manifest, files = load_parts(roots)
    dimension = manifest["encoder"]["dimension"]
    if validate_only:
        rows = 0
        for path, receipt in files:
            for ids, _, _ in iter_points(path, dimension, batch_size, receipt):
                rows += len(ids)
        print(json.dumps(dict(validated_rows=rows, complete=True)))
        return
    if not url:
        raise ValueError("Set QDRANT_URL or pass --url")
    from qdrant_client import QdrantClient, models
    from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

    client = QdrantClient(url=url, api_key=api_key, timeout=120)
    vector_name = manifest["encoder"]["vector_name"]
    created = not client.collection_exists(collection)
    if created:
        client.create_collection(collection_name=collection,
            vectors_config={vector_name: models.VectorParams(size=dimension, distance=models.Distance.COSINE,
                                                             on_disk=True)}, on_disk_payload=True)
    vectors = client.get_collection(collection).config.params.vectors
    if (not isinstance(vectors, dict) or vector_name not in vectors or
            vectors[vector_name].size != dimension or vectors[vector_name].distance != models.Distance.COSINE):
        raise ValueError("Existing collection must have the matching named vector and cosine distance")
    identity = dict(destination_hash=hashlib.sha256(url.encode()).hexdigest(), collection=collection,
                    source_sha256=manifest["source"]["source_sha256"], profile_id=manifest["profile_id"])
    checkpoint = Path(checkpoint)
    state = dict(identity=identity, completed={})
    if checkpoint.exists() and not created:
        state = json.loads(checkpoint.read_text())
        if state["identity"] != identity:
            raise ValueError("Checkpoint belongs to another Qdrant destination or embedding set")
    uploaded = 0
    for path, receipt in files:
        key = f"part-{receipt['part']}/{path.name}"
        if state["completed"].get(key) == receipt["sha256"]:
            continue
        for ids, vectors, payloads in iter_points(path, dimension, batch_size, receipt):
            points = [models.PointStruct(id=identifier, vector={vector_name: vector.tolist()}, payload=payload)
                      for identifier, vector, payload in zip(ids, vectors, payloads)]
            for attempt in range(4):
                try:
                    client.upsert(collection_name=collection, points=points, wait=True)
                    break
                except (ResponseHandlingException, UnexpectedResponse) as error:
                    if isinstance(error, UnexpectedResponse) and error.status_code not in (408, 429, 500, 502, 503, 504):
                        raise
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
            uploaded += len(ids)
        state["completed"][key] = receipt["sha256"]
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".partial")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(checkpoint)
        print(json.dumps(dict(file=key, rows_upserted_this_run=uploaded)), flush=True)
    print(json.dumps(dict(complete=True, expected_points=manifest["source"]["total_rows"],
                          collection=collection, rows_upserted_this_run=uploaded)))
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", nargs=2, required=True, metavar=("PART1", "PART2"))
    parser.add_argument("--url", default=os.environ.get("QDRANT_URL"))
    parser.add_argument("--collection", default="vibiomir_qwen3_06b_1024")
    parser.add_argument("--checkpoint", default="/kaggle/working/qdrant_import_checkpoint.json")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    import_parts(args.parts, args.url, os.environ.get("QDRANT_API_KEY"), args.collection,
                 args.checkpoint, args.batch_size, args.validate_only)
