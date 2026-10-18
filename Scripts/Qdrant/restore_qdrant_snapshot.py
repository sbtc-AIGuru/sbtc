"""Verify and unpack a notebook export; print commands to restore with Docker."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import shutil
from urllib.parse import quote
from urllib.request import Request, urlopen


def verify(folder: Path, url: str) -> dict:
    manifest = json.loads((folder / "snapshot_manifest.json").read_text())
    if not manifest["complete"]:
        raise ValueError("Recovery snapshot is incomplete; resume the notebook before final verification")
    name = quote(manifest["collection"], safe="")

    def request(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url.rstrip("/") + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=300) as response:
            return json.load(response)["result"]

    count = request("POST", f"/collections/{name}/points/count", {"exact": True})["count"]
    if count != manifest["points"]:
        raise ValueError("Restored exact point count differs from manifest")
    schema = manifest.get("vector_schema")
    if not schema:
        return {"points": count, "hybrid": False, "reason": "Legacy dense-only manifest"}
    info = request("GET", f"/collections/{name}")
    for field in ("chunk_id", "parent_id"):
        if field not in info["payload_schema"]:
            raise ValueError(f"Missing restored {field} keyword index")
    points = request("POST", f"/collections/{name}/points/scroll", {
        "limit": 64, "with_vector": True, "with_payload": True,
    })["points"]
    point = next((p for p in points if p["vector"].get(schema["sparse"], {}).get("indices")), None)
    if point is None:
        raise ValueError("No indexed BM25 sample found after restore")
    payload = point["payload"]
    query = {"prefetch": [
        {"query": point["vector"][schema["dense"]], "using": schema["dense"], "limit": 20},
        {"query": {"text": payload["chunk_text"], "model": schema["bm25_model"],
                   "options": schema["bm25_options"]}, "using": schema["sparse"], "limit": 20},
    ], "query": {"fusion": "rrf"}, "limit": 3, "with_payload": True}
    dense = request("POST", f"/collections/{name}/points/query", {
        **query["prefetch"][0], "limit": 3,
    })["points"]
    lexical = request("POST", f"/collections/{name}/points/query", {
        **query["prefetch"][1], "limit": 3,
    })["points"]
    if not dense or dense[0]["score"] < 0.99 or not lexical:
        raise ValueError("Restored dense or BM25 search failed")
    hits = request("POST", f"/collections/{name}/points/query", query)["points"]
    if not hits or any(not all(k in hit["payload"] for k in ("chunk_id", "parent_id", "chunk_text")) for hit in hits):
        raise ValueError("Hybrid query or chunk/parent metadata verification failed")
    return {"points": count, "dense": True, "bm25": True, "hybrid": True, "sample_chunk_id": payload["chunk_id"],
            "sample_parent_id": payload["parent_id"]}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def unpack(folder: Path) -> tuple[dict, Path]:
    manifest = json.loads((folder / "snapshot_manifest.json").read_text())
    snapshot = folder / manifest["snapshot_file"]
    if checksum(snapshot) != manifest["snapshot_sha256"]:
        raise ValueError("Snapshot checksum differs from the manifest")
    raw = snapshot.with_suffix("") if snapshot.suffix == ".gz" else snapshot
    if snapshot.suffix == ".gz" and not raw.exists():
        partial = raw.with_suffix(raw.suffix + ".partial")
        if shutil.disk_usage(folder).free < manifest["raw_snapshot_bytes"] + 1024**3:
            raise RuntimeError("Not enough disk space to unpack the snapshot")
        with gzip.open(snapshot, "rb") as source, partial.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=8 * 1024**2)
        if checksum(partial) != manifest["raw_snapshot_sha256"]:
            raise ValueError("Unpacked snapshot checksum mismatch")
        partial.replace(raw)
    if checksum(raw) != manifest["raw_snapshot_sha256"]:
        raise ValueError("Raw snapshot checksum mismatch")
    return manifest, raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path.cwd())
    parser.add_argument("--verify-url", help="Verify an already restored server (does not restore or unpack)")
    args = parser.parse_args()
    folder = args.folder.resolve()
    if args.verify_url:
        print(json.dumps(verify(folder, args.verify_url), ensure_ascii=False, indent=2))
        return
    manifest, raw = unpack(folder)
    name, version = manifest["collection"], manifest["qdrant_version"]
    if not manifest["complete"]:
        print("RECOVERY SNAPSHOT: partial ingestion/indexing; use resume_from in the notebook to finish.")
    print(f"Verified: {raw}; {manifest['points']:,} points. Keep the snapshot and restored storage on disk during recovery.")
    print("Run these commands with Docker and curl installed. Use an empty qdrant_storage directory.")
    print("docker run -d --name sbtc-qdrant -p 127.0.0.1:6333:6333 "
          "-e QDRANT__STORAGE__LOW_MEMORY_MODE=no_populate "
          "-e QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots "
          f"-v {shlex.quote(str(folder / 'qdrant_storage') + ':/qdrant/storage')} "
          f"-v {shlex.quote(str(folder) + ':/qdrant/import:ro')} qdrant/qdrant:v{version}")
    print("# Wait until curl --fail http://127.0.0.1:6333/readyz succeeds, then:")
    print("docker exec sbtc-qdrant mkdir -p /qdrant/storage/snapshots")
    print(f"docker exec sbtc-qdrant cp --reflink=auto {shlex.quote('/qdrant/import/' + raw.name)} /qdrant/storage/snapshots/")
    body = json.dumps({"location": f"file:///qdrant/storage/snapshots/{raw.name}", "priority": "snapshot"})
    print(f"curl --fail -X PUT 'http://127.0.0.1:6333/collections/{name}/snapshots/recover?wait=true' "
          f"-H 'Content-Type: application/json' --data {shlex.quote(body)}")
    print(f"curl --fail -X POST http://127.0.0.1:6333/collections/{name}/points/count "
          "-H 'Content-Type: application/json' --data '{\"exact\":true}'")
    print(f"python restore_qdrant_snapshot.py --folder {shlex.quote(str(folder))} --verify-url http://127.0.0.1:6333")


if __name__ == "__main__":
    main()
