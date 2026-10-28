"""Restore and revalidate the existing ViBioMIR recovery snapshot on Kaggle CPU."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import time

import psutil
import requests

if __package__:
    from . import vibiomir_qdrant_runtime as runtime
    from .restore_vibiomir_qdrant import verify_collection
else:
    import vibiomir_qdrant_runtime as runtime
    from restore_vibiomir_qdrant import verify_collection


def find_source(config):
    candidates = []
    for path in Path(config["input_root"]).rglob("snapshot_manifest.json"):
        manifest = json.loads(path.read_text())
        if manifest.get("schema_version") != "vibiomir-qdrant-dense-v1":
            continue
        if manifest["signature"]["source_sha256"] != config["source_sha256"]:
            continue
        candidates.append((path, manifest))
    if len(candidates) != 1:
        raise ValueError(f"Attach exactly one original dense snapshot output; found {len(candidates)}")
    path, manifest = candidates[0]
    signature = manifest["signature"]
    if (manifest["points"] != config["expected_chunks"]
            or manifest["checkpoint"]["rows"] != config["expected_chunks"]
            or signature["profile_id"] != config["profile_id"]
            or signature["dimension"] != config["dimension"]
            or signature["hnsw_m"] != config["hnsw_m"]
            or signature["ef_construction"] != config["ef_construction"]
            or manifest["qdrant_version"] != runtime.QDRANT_VERSION
            or manifest["vector_schema"] != {"dense": "qwen3_dense", "dense_datatype": "float16"}
            or Path(manifest["snapshot_file"]).name != manifest["snapshot_file"]):
        raise ValueError("Snapshot does not match the full-corpus FP16 HNSW contract")
    snapshot = path.parent / manifest["snapshot_file"]
    if snapshot.suffix != ".snapshot" or snapshot.stat().st_size != manifest["raw_snapshot_bytes"]:
        raise ValueError("This bounded recheck expects the original raw .snapshot output")
    if manifest["snapshot_sha256"] != manifest["raw_snapshot_sha256"]:
        raise ValueError("Raw and exported snapshot hashes differ")
    samples = json.loads((path.parent / "verification_samples.json").read_text())
    if not samples:
        raise ValueError("Source verification samples are missing")
    return path, manifest, snapshot, samples


def stage_snapshot(source, destination, expected_hash):
    digest = hashlib.sha256()
    total = 0
    with Path(source).open("rb") as reader, Path(destination).open("wb") as writer:
        for block in iter(lambda: reader.read(8 * 1024**2), b""):
            digest.update(block)
            writer.write(block)
            total += len(block)
            if total % (1024**3) == 0:
                print(json.dumps({"stage": "staging_snapshot", "bytes": total}), flush=True)
    if digest.hexdigest() != expected_hash or runtime.checksum(destination) != expected_hash:
        raise ValueError("Source or staged snapshot SHA-256 mismatch")
    print(json.dumps({"stage": "snapshot_sha256_verified", "bytes": total,
                      "sha256": expected_hash}), flush=True)


def measured_search(config, sample, *, server_timeout=None, filtered=False, label="search"):
    query = {"query": sample["vector"], "using": "qwen3_dense", "limit": 10,
             "with_payload": True, "params": {"hnsw_ef": 128}}
    if filtered:
        query["filter"] = {"must": [{"key": "content_origin",
                                     "match": {"value": sample["payload"]["content_origin"]}}]}
    params = {"timeout": server_timeout} if server_timeout is not None else None
    started = time.monotonic()
    result = {"label": label, "server_timeout": server_timeout, "filtered": filtered,
              "sample_chunk_id": sample["payload"]["chunk_id"]}
    try:
        response = requests.post(f"{config['qdrant_url']}/collections/{config['collection']}/points/query",
                                 params=params, json=query, timeout=(server_timeout or 60) + 30)
        result["http_status"] = response.status_code
        if response.ok:
            hits = response.json()["result"]["points"]
            result.update(hits=len(hits), top_score=hits[0]["score"] if hits else None,
                          returned_ids=[str(hit["id"]) for hit in hits],
                          payload_present=all("content" in hit.get("payload", {})
                                              and "_embedding" in hit["payload"] for hit in hits))
            result["passed"] = bool(hits and hits[0]["score"] >= 0.99 and result["payload_present"])
            if filtered:
                result["passed"] = result["passed"] and all(
                    hit["payload"]["content_origin"] == sample["payload"]["content_origin"] for hit in hits)
        else:
            result.update(passed=False, error=response.text[:3000])
    except requests.RequestException as error:
        result.update(passed=False, error=str(error))
    result["elapsed_seconds"] = round(time.monotonic() - started, 4)
    print(json.dumps({"stage": "query_check", **result}), flush=True)
    return result


def run(config):
    output, state = Path(config["output"]), Path(config["state_dir"])
    output.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "stage": "preflight", "queries": [], "reingested": False,
              "reembedded": False, "source_kernel": config["source_kernel"]}
    process = log = None
    try:
        manifest_path, manifest, source, samples = find_source(config)
        if any(state.iterdir()):
            raise ValueError("Use a fresh empty state directory for the recheck")
        mounts = [m for m in psutil.disk_partitions(all=True)
                  if state.resolve().is_relative_to(Path(m.mountpoint))]
        kind = max(mounts, key=lambda m: len(m.mountpoint)).fstype if mounts else "unknown"
        if kind in {"tmpfs", "ramfs"}:
            raise RuntimeError(f"Restore state must be disk-backed, not {kind}")
        required = 3 * source.stat().st_size + 4 * 1024**3
        free = shutil.disk_usage(state).free
        if free < required:
            raise RuntimeError(f"Insufficient scratch disk: need {required}, free {free}")
        print(json.dumps({"stage": "preflight", "snapshot_bytes": source.stat().st_size,
                          "state_free_bytes": free, "required_state_bytes": required,
                          "memory_available_bytes": psutil.virtual_memory().available,
                          "filesystem": kind, "source_complete_flag": manifest["complete"]}), flush=True)
        runtime.write_json(output / "source_snapshot_manifest.json", manifest)
        runtime.write_json(output / "verification_samples.json", samples)
        runtime.write_json(output / "run_config.json", config)
        process, log = runtime.start_server(config)
        if runtime.api(config, "GET", "/collections")["collections"]:
            raise ValueError("Recheck server is not empty")
        raw = state / "snapshots" / "source.snapshot"
        report["stage"] = "staging_snapshot"
        runtime.write_json(output / "recheck_report.json", report)
        stage_snapshot(source, raw, manifest["raw_snapshot_sha256"])
        report["stage"] = "restoring"
        runtime.write_json(output / "recheck_report.json", report)
        print(json.dumps({"stage": "restoring", "collection": config["collection"]}), flush=True)
        restore_started = time.monotonic()
        runtime.api(config, "PUT", f"/collections/{config['collection']}/snapshots/recover?wait=true",
                    {"location": raw.resolve().as_uri(), "priority": "snapshot"}, timeout=7200)
        report["restore_seconds"] = round(time.monotonic() - restore_started, 3)
        info = runtime.api(config, "GET", f"/collections/{config['collection']}")
        runtime.write_json(output / "restored_collection_info.json", info)
        if (info["status"] != "green" or info["optimizer_status"] != "ok"
                or info.get("indexed_vectors_count") != config["expected_chunks"]):
            raise ValueError("Restored collection is not green and fully HNSW-indexed")
        report["stage"] = "checking_search"
        runtime.write_json(output / "recheck_report.json", report)
        print(json.dumps({"stage": "restored", "restore_seconds": report["restore_seconds"],
                          "status": info["status"], "indexed_vectors_count": info["indexed_vectors_count"]}), flush=True)
        # Test the original server default separately; an error here must not hide long-timeout results.
        report["queries"].append(measured_search(config, samples[0], label="first_query_default_60s"))
        runtime.write_json(output / "recheck_report.json", report)
        # Complete=True here describes the verification expectation, not a modification of the input manifest.
        expected = {**manifest, "complete": True}
        report["verification"] = verify_collection(config["qdrant_url"], expected, samples,
            collection=config["collection"], search_timeout=config["search_timeout_seconds"])
        print(json.dumps({"stage": "schema_payload_vector_lookup_verified", **report["verification"]}), flush=True)
        stride = max(1, len(samples) // 9)
        for index, sample in enumerate(samples[::stride][:9]):
            report["queries"].append(measured_search(config, sample,
                server_timeout=config["search_timeout_seconds"], label=f"explicit_timeout_{index}"))
            runtime.write_json(output / "recheck_report.json", report)
        for index, sample in enumerate(samples[::max(1, len(samples)//3)][:3]):
            report["queries"].append(measured_search(config, sample,
                server_timeout=config["search_timeout_seconds"], filtered=True, label=f"origin_filter_{index}"))
            runtime.write_json(output / "recheck_report.json", report)
        required_checks = report["queries"][1:]
        if not all(check["passed"] for check in required_checks):
            raise ValueError("One or more explicit-timeout dense/filter queries failed; see recheck_report.json")
        seconds = [check["elapsed_seconds"] for check in required_checks]
        report.update(passed=True, stage="verified", points=config["expected_chunks"],
                      source_snapshot_sha256=manifest["raw_snapshot_sha256"],
                      source_snapshot_file=manifest["snapshot_file"],
                      source_manifest_complete=manifest["complete"],
                      query_median_seconds=round(statistics.median(seconds), 4),
                      query_max_seconds=max(seconds), default_query_passed=report["queries"][0]["passed"],
                      note="Functional validation of stored-vector queries, not semantic retrieval quality evaluation.")
        certificate = {"validated": True, "source_kernel": config["source_kernel"],
                       "source_snapshot_file": manifest["snapshot_file"],
                       "source_snapshot_sha256": manifest["raw_snapshot_sha256"],
                       "points": config["expected_chunks"], "qdrant_version": runtime.QDRANT_VERSION,
                       "signature": manifest["signature"], "restore_verification": report["verification"],
                       "search_timeout_seconds": config["search_timeout_seconds"],
                       "original_complete_flag": manifest["complete"],
                       "note": "This certificate validates the referenced immutable recovery snapshot; original manifest remains unchanged."}
        runtime.write_json(output / "snapshot_validation.json", certificate)
        runtime.write_json(output / "recheck_report.json", report)
        print(json.dumps({"stage": "RECHECK_PASSED", "points": report["points"],
                          "default_query_passed": report["default_query_passed"],
                          "query_median_seconds": report["query_median_seconds"],
                          "query_max_seconds": report["query_max_seconds"]}), flush=True)
    except Exception as error:
        report.update(passed=False, error=str(error))
        runtime.write_json(output / "recheck_report.json", report)
        print(json.dumps({"stage": "RECHECK_FAILED", "error": str(error)}), flush=True)
        raise
    finally:
        if process is not None:
            runtime.stop_server(process, log)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.config.read_text()))
