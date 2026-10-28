"""Read embedding outputs through their manifests, with bounded memory."""

import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_outputs(input_root="/kaggle/input", required_parts=(1, 2, 3)):
    manifests = {}
    required_parts = sorted(required_parts)
    for path in Path(input_root).rglob("manifest.json"):
        manifest = json.loads(path.read_text())
        if manifest.get("schema_version") != "vibiomir-embedding-v1":
            continue
        part = manifest["part"]
        if part not in required_parts:
            continue
        if part in manifests:
            raise ValueError(f"Part {part} attached more than once; keep one completed version per part")
        if not manifest["complete"] or manifest["rows"] != manifest["expected_rows"]:
            raise ValueError(f"Part {part} is incomplete: {path}")
        manifests[part] = (path, manifest)
    if sorted(manifests) != required_parts:
        raise ValueError(f"Add Input completed parts {required_parts}; found {sorted(manifests)}")
    first = manifests[required_parts[0]][1]
    profile_id = hashlib.sha256(json.dumps(first["encoder"], sort_keys=True).encode()).hexdigest()
    files = []
    for part, (manifest_path, manifest) in sorted(manifests.items()):
        if (manifest["encoder"] != first["encoder"] or manifest["source"] != first["source"]
                or manifest["profile_id"] != profile_id):
            raise ValueError("Parts use different encoder profiles or source data")
        ranges = [item for item in manifest["source"]["shards"] if item["part"] == part]
        expected_rows = sum(item["rows"] for item in ranges)
        if manifest["rows"] != expected_rows:
            raise ValueError(f"Part {part} row count differs from source partition")
        next_line = min(item["start_line"] for item in ranges)
        end_line = max(item["end_line"] for item in ranges)
        for receipt in sorted(manifest["files"], key=lambda item: item["start_line"]):
            if (Path(receipt["file"]).name != receipt["file"] or receipt["part"] != part
                    or receipt["start_line"] != next_line
                    or receipt["end_line"] - receipt["start_line"] + 1 != receipt["rows"]
                    or receipt["profile_id"] != profile_id
                    or receipt["source_sha256"] != manifest["source"]["source_sha256"]):
                raise ValueError(f"Invalid file/source mapping in part {part}")
            path = manifest_path.parent / receipt["file"]
            if not path.is_file():
                raise FileNotFoundError(f"Manifest references a missing file: {path}")
            parquet = pq.ParquetFile(path)
            metadata = json.loads(parquet.schema_arrow.metadata[b"vibiomir_embedding"])
            vector_type = parquet.schema_arrow.field("vector").type
            if (parquet.metadata.num_rows != receipt["rows"]
                    or not pa.types.is_fixed_size_list(vector_type)
                    or vector_type.list_size != manifest["encoder"]["dimension"]
                    or vector_type.value_type != pa.float32()
                    or metadata["profile_id"] != profile_id
                    or metadata["source_sha256"] != receipt["source_sha256"]):
                raise ValueError(f"Parquet schema/metadata differs: {path}")
            files.append(dict(path=str(path), receipt=receipt))
            next_line = receipt["end_line"] + 1
        if next_line != end_line + 1:
            raise ValueError(f"Missing source rows in part {part}")
    return dict(parts=required_parts, rows=sum(item[1]["rows"] for item in manifests.values()),
                source_rows=first["source"]["total_rows"], source_sha256=first["source"]["source_sha256"],
                encoder=first["encoder"], profile_id=profile_id,
                full_corpus=len(required_parts) == first["source"]["num_parts"], files=files)


def iter_embedding_batches(catalog, batch_size=128, columns=None):
    for item in catalog["files"]:
        yield from pq.ParquetFile(item["path"]).iter_batches(batch_size=batch_size, columns=columns)


def verify_outputs(catalog, verify_checksums=True, metadata_sample_per_file=128):
    scanned_rows = sampled_rows = 0
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "https://vibiomir.org/chunks")
    for file_index, item in enumerate(catalog["files"], 1):
        path, receipt = Path(item["path"]), item["receipt"]
        if verify_checksums and file_hash(path) != receipt["sha256"]:
            raise ValueError(f"Checksum differs: {path}")
        parquet = pq.ParquetFile(path)
        next_line = receipt["start_line"]
        for batch in parquet.iter_batches(batch_size=2048, columns=["source_line", "vector"]):
            lines = batch.column(0).to_numpy()
            vectors = batch.column(1).flatten().to_numpy().reshape(len(lines), catalog["encoder"]["dimension"])
            if (not np.array_equal(lines, np.arange(next_line, next_line + len(lines)))
                    or not np.isfinite(vectors).all()
                    or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=2e-5)):
                raise ValueError(f"Invalid vector values or source order: {path}")
            next_line += len(lines)
            scanned_rows += len(lines)
        if next_line != receipt["end_line"] + 1:
            raise ValueError(f"Source coverage differs: {path}")
        sample = next(parquet.iter_batches(batch_size=metadata_sample_per_file)).to_pylist()
        for row in sample:
            payload = json.loads(row["payload_json"])
            provenance = payload["_embedding"]
            content_hash = hashlib.sha256(payload["content"].encode()).hexdigest()
            if (payload["chunk_id"] != row["chunk_id"] or payload["doc_id"] != row["doc_id"]
                    or payload["content"] != row["content"]
                    or provenance["source_line"] != row["source_line"]
                    or provenance["source_byte"] != row["source_byte"]
                    or content_hash != row["content_sha256"]
                    or provenance["content_sha256"] != content_hash
                    or provenance["profile_id"] != catalog["profile_id"]
                    or str(uuid.uuid5(namespace, row["chunk_id"])) != row["point_id"]):
                raise ValueError(f"Vector/payload ID mapping differs: {path}")
            sampled_rows += 1
        if file_index % 25 == 0 or file_index == len(catalog["files"]):
            print(json.dumps(dict(files_checked=file_index, files_total=len(catalog["files"]),
                                  vector_rows_checked=scanned_rows)), flush=True)
    if scanned_rows != catalog["rows"]:
        raise ValueError("Total scanned rows differs from manifests")
    return dict(passed=True, parts=catalog["parts"], full_corpus=catalog["full_corpus"],
                parquet_files=len(catalog["files"]), vector_rows_checked=scanned_rows,
                metadata_rows_sampled=sampled_rows, all_file_checksums_verified=verify_checksums,
                dimension=catalog["encoder"]["dimension"], dtype="float32", normalized=True,
                source_sha256=catalog["source_sha256"], profile_id=catalog["profile_id"])
