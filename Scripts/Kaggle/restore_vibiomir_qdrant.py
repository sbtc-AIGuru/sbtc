"""Verify, unpack and query the standalone ViBioMIR dense snapshot."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import shutil
from urllib.parse import quote

import numpy as np
import requests


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


class QdrantDenseClient:
    def __init__(self, url, collection, vector_name="qwen3_dense", api_key=None,
                 search_timeout=None, request_timeout=300):
        self.url = url.rstrip("/")
        self.collection = collection
        self.vector_name = vector_name
        self.search_timeout = search_timeout
        self.request_timeout = request_timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers["api-key"] = api_key

    @classmethod
    def from_manifest(cls, path, url="http://127.0.0.1:6333", api_key=None):
        manifest = json.loads(Path(path).read_text())
        if not manifest["complete"]:
            raise ValueError("Recovery snapshot: resume the notebook before production search")
        return cls(url, manifest["collection"], manifest["vector_schema"]["dense"], api_key)

    def request(self, method, suffix="", body=None):
        name = quote(self.collection, safe="")
        if suffix == "/points/query" and self.search_timeout is not None:
            suffix += f"?timeout={self.search_timeout}"
        response = self.session.request(method, f"{self.url}/collections/{name}{suffix}",
                                        json=body, timeout=self.request_timeout)
        response.raise_for_status()
        return response.json()["result"]

    def search_dense(self, query_vector, top_k=10, filters=None, hnsw_ef=128):
        body = {"query": list(query_vector), "using": self.vector_name, "limit": top_k,
                "with_payload": True, "params": {"hnsw_ef": hnsw_ef}}
        if filters is not None:
            body["filter"] = filters
        return self.request("POST", "/points/query", body)["points"]

    def get_points(self, ids, with_vectors=False):
        return self.request("POST", "/points", {"ids": ids, "with_payload": True,
                                                "with_vector": with_vectors})

    def lookup_chunk(self, chunk_id):
        result = self.request("POST", "/points/scroll", {
            "limit": 1, "with_payload": True,
            "filter": {"must": [{"key": "chunk_id", "match": {"value": chunk_id}}]},
        })
        return result["points"]

    def scroll_document(self, doc_id, limit=100, offset=None):
        body = {"limit": limit, "with_payload": True,
                "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}}
        if offset is not None:
            body["offset"] = offset
        return self.request("POST", "/points/scroll", body)

    def close(self):
        self.session.close()


def verify_collection(url, manifest, samples, collection=None, api_key=None, search_timeout=None):
    client = QdrantDenseClient(url, collection or manifest["collection"],
                               manifest["vector_schema"]["dense"], api_key,
                               search_timeout=search_timeout,
                               request_timeout=max(300, (search_timeout or 0) + 30))
    try:
        count = client.request("POST", "/points/count", {"exact": True})["count"]
        if count != manifest["points"]:
            raise ValueError("Exact point count differs from the snapshot manifest")
        info = client.request("GET")
        params = info["config"]["params"]
        vectors = params["vectors"]
        expected = {"size": manifest["signature"]["dimension"], "distance": "Cosine",
                    "datatype": "float16", "on_disk": True}
        if (set(vectors) != {client.vector_name} or params.get("sparse_vectors")
                or any(vectors[client.vector_name].get(k) != v for k, v in expected.items())
                or not params.get("on_disk_payload")):
            raise ValueError("Collection is not the expected disk-backed FP16 dense schema")
        for field, kind in manifest["payload_indexes"].items():
            if info["payload_schema"].get(field, {}).get("data_type") != kind:
                raise ValueError(f"Missing or different payload index: {field}")
        hnsw = info["config"]["hnsw_config"]
        if manifest["complete"] and (hnsw["m"] != manifest["signature"]["hnsw_m"]
                or hnsw["ef_construct"] != manifest["signature"]["ef_construction"]):
            raise ValueError("Restored HNSW configuration differs")
        if not samples:
            raise ValueError("No source samples available to verify payload/vector preservation")
        points = {str(p["id"]): p for p in client.get_points([s["id"] for s in samples], True)}
        for sample in samples:
            point = points.get(sample["id"])
            if point is None or point["payload"] != sample["payload"]:
                raise ValueError("Restored source payload does not round-trip exactly")
            original = np.asarray(sample["vector"], dtype=np.float32)
            stored = np.asarray(point["vector"][client.vector_name], dtype=np.float32)
            if (original.shape != stored.shape or not np.isfinite(stored).all()
                    or not np.allclose(original, stored, rtol=0.003, atol=0.0005)):
                raise ValueError("Restored FP16 vector differs beyond the allowed rounding tolerance")
        for sample in samples[:3]:
            payload = sample["payload"]
            hits = client.search_dense(sample["vector"], top_k=3)
            if not hits or hits[0]["score"] < 0.99:
                raise ValueError("Dense stored-vector similarity check failed")
            found = client.lookup_chunk(payload["chunk_id"])
            if not found or found[0]["payload"] != payload:
                raise ValueError("chunk_id lookup lost the original payload")
            docs = client.scroll_document(payload["doc_id"], limit=3)["points"]
            if not docs or any(p["payload"]["doc_id"] != payload["doc_id"] for p in docs):
                raise ValueError("doc_id lookup failed")
        return {"verified": True, "points": count, "payload_samples": len(samples),
                "dense": True, "fp16": True, "payload_lookup": True,
                "status": info["status"], "indexed_vectors_count": info.get("indexed_vectors_count", 0)}
    finally:
        client.close()


def unpack(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "snapshot_manifest.json").read_text())
    snapshot = folder / manifest["snapshot_file"]
    if checksum(snapshot) != manifest["snapshot_sha256"]:
        raise ValueError("Snapshot checksum mismatch")
    raw = snapshot.with_suffix("") if snapshot.suffix == ".gz" else snapshot
    if snapshot.suffix == ".gz" and not raw.exists():
        if shutil.disk_usage(folder).free < manifest["raw_snapshot_bytes"] + 1024**3:
            raise RuntimeError("Not enough disk space to unpack the snapshot")
        partial = raw.with_suffix(raw.suffix + ".partial")
        with gzip.open(snapshot, "rb") as source, partial.open("wb") as destination:
            shutil.copyfileobj(source, destination, 8 * 1024**2)
        if checksum(partial) != manifest["raw_snapshot_sha256"]:
            raise ValueError("Unpacked snapshot checksum mismatch")
        partial.replace(raw)
    if checksum(raw) != manifest["raw_snapshot_sha256"]:
        raise ValueError("Raw snapshot checksum mismatch")
    return manifest, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path.cwd())
    parser.add_argument("--verify-url")
    args = parser.parse_args()
    folder = args.folder.resolve()
    if args.verify_url:
        manifest = json.loads((folder / "snapshot_manifest.json").read_text())
        if not manifest["complete"]:
            raise ValueError("Recovery snapshot is incomplete; resume the notebook first")
        samples = json.loads((folder / "verification_samples.json").read_text())
        print(json.dumps(verify_collection(args.verify_url, manifest, samples), indent=2))
        return
    manifest, raw = unpack(folder)
    name = quote(manifest["collection"], safe="")
    version = manifest["qdrant_version"]
    if not manifest["complete"]:
        print("RECOVERY ONLY: attach this export to the notebook and set resume_from.")
    print("Use empty qdrant_storage; keep the snapshot and storage on disk during recovery.")
    print("docker run -d --name vibiomir-qdrant -p 127.0.0.1:6333:6333 "
          "-e QDRANT__STORAGE__LOW_MEMORY_MODE=no_populate "
          "-e QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots "
          f"-v {shlex.quote(str(folder / 'qdrant_storage') + ':/qdrant/storage')} "
          f"-v {shlex.quote(str(folder) + ':/qdrant/import:ro')} qdrant/qdrant:v{version}")
    print("# Wait until curl --fail http://127.0.0.1:6333/readyz succeeds, then:")
    print("docker exec vibiomir-qdrant mkdir -p /qdrant/storage/snapshots")
    print(f"docker exec vibiomir-qdrant cp --reflink=auto {shlex.quote('/qdrant/import/' + raw.name)} /qdrant/storage/snapshots/")
    body = json.dumps({"location": f"file:///qdrant/storage/snapshots/{raw.name}", "priority": "snapshot"})
    print(f"curl --fail -X PUT 'http://127.0.0.1:6333/collections/{name}/snapshots/recover?wait=true' "
          f"-H 'Content-Type: application/json' --data {shlex.quote(body)}")
    print(f"python restore_qdrant_snapshot.py --folder {shlex.quote(str(folder))} --verify-url http://127.0.0.1:6333")


if __name__ == "__main__":
    main()
