"""Verify and unpack a notebook export; print commands to restore with Docker."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import shutil


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
    args = parser.parse_args()
    folder = args.folder.resolve()
    manifest, raw = unpack(folder)
    name, version = manifest["collection"], manifest["qdrant_version"]
    if not manifest["complete"]:
        print("RECOVERY SNAPSHOT: partial ingestion/indexing; use resume_from in the notebook to finish.")
    print(f"Verified: {raw}; {manifest['points']:,} points. Keep the snapshot and restored storage on disk during recovery.")
    print("Run these commands with Docker and curl installed. Use an empty qdrant_storage directory.")
    print("docker run -d --name sbtc-qdrant -p 127.0.0.1:6333:6333 "
          f"-v {shlex.quote(str(folder / 'qdrant_storage') + ':/qdrant/storage')} "
          f"-v {shlex.quote(str(folder) + ':/qdrant/snapshots:ro')} qdrant/qdrant:v{version}")
    print("# Wait until curl --fail http://127.0.0.1:6333/readyz succeeds, then:")
    body = json.dumps({"location": f"file:///qdrant/snapshots/{raw.name}", "priority": "snapshot"})
    print(f"curl --fail -X PUT 'http://127.0.0.1:6333/collections/{name}/snapshots/recover?wait=true' "
          f"-H 'Content-Type: application/json' --data {shlex.quote(body)}")
    print(f"curl --fail -X POST http://127.0.0.1:6333/collections/{name}/points/count "
          "-H 'Content-Type: application/json' --data '{\"exact\":true}'")


if __name__ == "__main__":
    main()
