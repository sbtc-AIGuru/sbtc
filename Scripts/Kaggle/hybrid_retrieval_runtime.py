"""Kaggle service adapters for the unchanged Qwen3/Elasticsearch retrieval pipeline."""

from copy import deepcopy
from collections import Counter
import hashlib
import json
import logging
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import tarfile
import time
import zipfile

import requests

from BackEnd.app.Database.qdrant_db import QdrantManager
from BackEnd.app.Database.elastic_search import (
    PIPELINE, bulk_index, check_analyzers, connect_elasticsearch, create_index,
)
from BackEnd.app.Retrieval.utils import atomic_json, sha_file, source_id

LOGGER = logging.getLogger(__name__)
QDRANT_VERSION = "1.19.2"
QDRANT_SHA256 = "50b253243309ed0ae50a19f678f0d0adcc4f0b567b3bd2c5c0c7e02fa8404bb6"
ES_VERSION = "9.5.1"
ES_SHA512 = "c86ee0b98c1b6a2da46292522b0470dc21e075cc5140fe6038784fcbc55b74b57c5d8ec8c4389451b684088891fce9162873ed0087578f384386d62c91f0cb2b"
SMARTCN_SHA512 = "33d9abce16c5e111dffaff093c4d919be6ff3e10d2fd73f35cdc5401a6b124f28a6493f59bfb267ec30ea45500eb67709f8248124256687aeca89d65301b1628"


def checksum(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url, path, expected, *, algorithm="sha256"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and checksum(path, algorithm) == expected:
        return path
    partial = path.with_suffix(path.suffix + ".partial")
    with requests.get(url, stream=True, timeout=(30, 180)) as response:
        response.raise_for_status()
        with partial.open("wb") as stream:
            for block in response.iter_content(8 * 1024**2):
                stream.write(block)
    if checksum(partial, algorithm) != expected:
        raise ValueError(f"Download checksum mismatch: {path.name}")
    partial.replace(path)
    return path


def find_input(root, name):
    matches = sorted(Path(root).rglob(name))
    if len(matches) != 1:
        raise ValueError(f"Attach exactly one {name}; found {len(matches)}")
    return matches[0]


def verify_snapshot_inputs(input_root, expected):
    manifest_path = find_input(input_root, "snapshot_manifest.json")
    certificate_path = find_input(input_root, "snapshot_validation.json")
    manifest = json.loads(manifest_path.read_text())
    certificate = json.loads(certificate_path.read_text())
    if (not certificate.get("validated") or
            certificate.get("source_kernel") != expected["snapshot_kernel"] or
            certificate.get("source_snapshot_sha256") != expected["snapshot_sha256"] or
            certificate.get("signature") != manifest.get("signature") or
            certificate.get("source_snapshot_file") != manifest.get("snapshot_file") or
            manifest.get("snapshot_sha256") != expected["snapshot_sha256"] or
            manifest.get("raw_snapshot_sha256") != expected["snapshot_sha256"] or
            manifest.get("points") != expected["points"] or
            certificate.get("points") != expected["points"] or
            manifest.get("qdrant_version") != QDRANT_VERSION or
            certificate.get("qdrant_version") != QDRANT_VERSION or
            manifest.get("signature", {}).get("source_sha256") != expected["source_sha256"] or
            not certificate.get("restore_verification", {}).get("verified")):
        raise ValueError("Snapshot/certificate does not match the pinned full-corpus export")
    name = manifest["snapshot_file"]
    if Path(name).name != name:
        raise ValueError("Snapshot filename must be a basename")
    snapshot = manifest_path.parent / name
    if snapshot.stat().st_size != manifest["raw_snapshot_bytes"]:
        raise ValueError("Snapshot size differs from manifest")
    # The immutable recovery manifest is never edited. The hash-bound recheck
    # certificate authorizes this separate runtime manifest for read-only queries.
    effective = {**manifest, "complete": True,
                 "validation_certificate_sha256": sha_file(certificate_path)}
    return manifest_path, snapshot, effective


def download_chunks(url, destination, expected_sha, expected_bytes):
    import gdown

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size != expected_bytes or checksum(destination) != expected_sha:
            raise ValueError("Existing corpus differs from the snapshot source")
        return destination
    partial = destination.with_suffix(destination.suffix + ".partial")
    result = gdown.download(url=url, output=str(partial), quiet=False, resume=True, fuzzy=True)
    if result is None or partial.stat().st_size != expected_bytes or checksum(partial) != expected_sha:
        raise ValueError("Drive download is incomplete or differs from the embedding source SHA-256")
    partial.replace(destination)
    return destination


def prepare_languages(source, destination, *, source_sha256, labeled_sha256, labels_sha256, expected_counts):
    """Reproduce the local language-enriched corpus without changing original fields."""
    import orjson
    from Scripts.LanguageLabeling.label_chunks import detect_language

    source, destination = Path(source), Path(destination)
    if destination.exists():
        if checksum(destination) != labeled_sha256:
            raise ValueError("Existing labeled corpus differs from the verified local corpus")
        return {"rows": sum(expected_counts.values()), "counts": expected_counts, "sha256": labeled_sha256}
    partial = destination.with_suffix(destination.suffix + ".partial")
    original_hash, output_hash, labels_hash = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    counts, rows = Counter(), 0
    with source.open("rb") as reader, partial.open("wb") as writer:
        for raw in reader:
            row = orjson.loads(raw)
            if "language" in row:
                raise ValueError("Expected the original unlabeled snapshot corpus")
            language = detect_language(row["content"])
            labels = {"doc_id": row["doc_id"], "chunk_id": row["chunk_id"], "language": language}
            labels_hash.update(orjson.dumps(labels) + b"\n")
            original_hash.update(raw)
            row["language"] = language
            enriched = orjson.dumps(row) + b"\n"
            writer.write(enriched)
            output_hash.update(enriched)
            counts[language] += 1
            rows += 1
            if rows % 500_000 == 0:
                print(f"Language preparation: {rows:,} chunks", flush=True)
    if (original_hash.hexdigest() != source_sha256 or output_hash.hexdigest() != labeled_sha256 or
            labels_hash.hexdigest() != labels_sha256 or dict(counts) != expected_counts):
        raise ValueError("Language enrichment differs from the verified local source/labels/counts")
    partial.replace(destination)
    return {"rows": rows, "counts": dict(counts), "sha256": labeled_sha256,
            "source_sha256": source_sha256, "labels_sha256": labels_sha256}


def ensure_free_disk(root, needed_bytes):
    free = shutil.disk_usage(root).free
    if free < needed_bytes:
        raise RuntimeError(f"Insufficient scratch disk: need {needed_bytes / 1024**3:.1f} GiB, free {free / 1024**3:.1f} GiB")
    return {"required_bytes": needed_bytes, "free_bytes": free}


def check_port(port):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} already in use; stop the previous notebook service first")


def stop_service(process, log):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    log.close()


def wait_service(process, log_path, url, timeout):
    started, last_report = time.monotonic(), 0
    while time.monotonic() - started < timeout:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited; inspect {log_path}:\n{Path(log_path).read_text()[-5000:]}")
        try:
            response = requests.get(url, timeout=3)
            if response.ok:
                return time.monotonic() - started
        except requests.RequestException:
            pass
        elapsed = time.monotonic() - started
        if elapsed - last_report >= 30:
            print(f"Waiting for {url}: {elapsed:.0f}s", flush=True)
            last_report = elapsed
        time.sleep(2)
    raise TimeoutError(f"Service startup exceeded {timeout}s; inspect {log_path}")


def install_elasticsearch(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    home = root / f"elasticsearch-{ES_VERSION}"
    ready = root / "installation.json"
    identity = {"version": ES_VERSION, "archive_sha512": ES_SHA512, "smartcn_sha512": SMARTCN_SHA512}
    if ready.exists():
        if json.loads(ready.read_text()) != identity:
            raise ValueError("Existing Elasticsearch installation belongs to another release")
        return home
    archive = download_verified(
        f"https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-{ES_VERSION}-linux-x86_64.tar.gz",
        root / "elasticsearch.tar.gz", ES_SHA512, algorithm="sha512")
    with tarfile.open(archive) as bundle:
        bundle.extractall(root, filter="data")
    plugin = download_verified(
        f"https://artifacts.elastic.co/downloads/elasticsearch-plugins/analysis-smartcn/analysis-smartcn-{ES_VERSION}.zip",
        root / "analysis-smartcn.zip", SMARTCN_SHA512, algorithm="sha512")
    if not (home / "plugins/analysis-smartcn/plugin-descriptor.properties").exists():
        subprocess.run([str(home / "bin/elasticsearch-plugin"), "install", "--batch", plugin.resolve().as_uri()], check=True)
    atomic_json(ready, identity)
    return home


def start_elasticsearch(home, *, port=9200, heap_gb=2, processors=2, timeout=180):
    home = Path(home).resolve()
    check_port(port)
    for name in ("data", "logs", "tmp"):
        (home / name).mkdir(exist_ok=True)
    settings = {"cluster.name": "sbtc-kaggle", "node.name": "retrieval",
                "network.host": "127.0.0.1", "http.port": port, "transport.port": port + 100,
                "discovery.type": "single-node", "xpack.security.enabled": False,
                "xpack.ml.enabled": False, "ingest.geoip.downloader.enabled": False,
                "node.processors": processors, "path.data": str(home / "data"),
                "path.logs": str(home / "logs")}
    (home / "config/elasticsearch.yml").write_text(json.dumps(settings))
    environment = {**os.environ, "ES_JAVA_OPTS": f"-Xms{heap_gb}g -Xmx{heap_gb}g",
                   "ES_TMPDIR": str(home / "tmp")}
    credentials = {}
    if os.geteuid() == 0:
        # Kaggle's notebook kernel is root; Elasticsearch must use a non-root uid.
        account = pwd.getpwnam("nobody")
        for path in (home, *home.rglob("*")):
            if not path.is_symlink():
                os.chown(path, account.pw_uid, account.pw_gid)
        credentials = {"user": account.pw_uid, "group": account.pw_gid, "extra_groups": []}
    log_path = home / "service.log"
    log = log_path.open("a")
    process = subprocess.Popen([str(home / "bin/elasticsearch")], cwd=home,
                               env=environment, stdout=log, stderr=subprocess.STDOUT, **credentials)
    try:
        seconds = wait_service(process, log_path, f"http://127.0.0.1:{port}", timeout)
        return process, log, {"version": ES_VERSION, "seconds": seconds, "log": str(log_path)}
    except BaseException:
        stop_service(process, log)
        raise


def build_bm25(source, index, receipt_path, *, source_sha256, expected_count, batch_size=1000):
    identity = {"source_sha256": source_sha256, "index": index, "count": expected_count,
                "preprocessing": PIPELINE, "elasticsearch_version": ES_VERSION}
    receipt_path = Path(receipt_path)
    with connect_elasticsearch() as client:
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != identity:
                raise ValueError("BM25 receipt differs from source/configuration")
            create_index(client, index)
            if client.count(index=index)["count"] == expected_count:
                return identity
            raise ValueError("BM25 count changed after a successful import")
        create_index(client, index)
        client.indices.put_settings(index=index, settings={"index": {"number_of_replicas": 0, "refresh_interval": "-1"}})
        check_analyzers(client, index)
        ok, failed = bulk_index(client, source, index=index, limit=None, batch_size=batch_size, workers=1)
        client.indices.put_settings(index=index, settings={"index": {"refresh_interval": "1s"}})
        client.indices.refresh(index=index)
        count = client.count(index=index)["count"]
        if failed or ok != expected_count or count != expected_count:
            raise ValueError(f"Incomplete BM25 index: success={ok}, failed={failed}, count={count}")
        atomic_json(receipt_path, identity)
    return identity


def restore_qdrant(snapshot, manifest, state, *, search_threads=2, timeout=7200):
    state = Path(state).resolve()
    state.mkdir(parents=True, exist_ok=True)
    if any(state.iterdir()):
        raise ValueError("Use empty Qdrant state for a fresh restore")
    check_port(6333)
    for name in ("storage/collections", "snapshots", "snapshot_temp", "bin"):
        (state / name).mkdir(parents=True, exist_ok=True)
    raw = state / "snapshots/restore.snapshot"
    digest = hashlib.sha256()
    with Path(snapshot).open("rb") as source, raw.open("wb") as target:
        for block in iter(lambda: source.read(8 * 1024**2), b""):
            digest.update(block)
            target.write(block)
    if digest.hexdigest() != manifest["raw_snapshot_sha256"]:
        raise ValueError("Staged snapshot SHA-256 mismatch")
    archive = download_verified(
        f"https://github.com/qdrant/qdrant/releases/download/v{QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz",
        state / "bin/qdrant.tar.gz", QDRANT_SHA256)
    binary = state / "bin/qdrant"
    with tarfile.open(archive) as bundle:
        member = next(item for item in bundle.getmembers() if Path(item.name).name == "qdrant" and item.isfile())
        with bundle.extractfile(member) as source, binary.open("wb") as target:
            shutil.copyfileobj(source, target)
    binary.chmod(0o755)
    settings = {"log_level": "WARN", "telemetry_disabled": True,
                "storage": {"storage_path": str(state / "storage"),
                            "snapshots_path": str(state / "snapshots"),
                            "temp_path": str(state / "snapshot_temp"), "on_disk_payload": True,
                            "low_memory_mode": "no_populate",
                            "optimizers_overwrite": {"max_optimization_threads": 0},
                            "performance": {"max_search_threads": search_threads, "optimizer_cpu_budget": 1}},
                "service": {"host": "127.0.0.1", "http_port": 6333, "grpc_port": None, "max_workers": 2}}
    config = state / "qdrant.yaml"
    config.write_text(json.dumps(settings))
    log_path = state / "qdrant.log"
    log = log_path.open("a")
    process = subprocess.Popen([str(binary), "--config-path", str(config), "--disable-telemetry",
                                "--snapshot", f"{raw}:{manifest['collection']}"],
                               cwd=state, stdout=log, stderr=subprocess.STDOUT)
    try:
        seconds = wait_service(process, log_path, "http://127.0.0.1:6333/readyz", timeout)
        with QdrantManager("http://127.0.0.1:6333", collection=manifest["collection"]) as manager:
            info = manager.refresh_collection()
        vector = info["config"]["params"]["vectors"].get("qwen3_dense", {})
        if (info.get("indexed_vectors_count") != manifest["points"] or
                info.get("optimizer_status") != "ok" or info.get("status") != "green" or
                vector.get("size") != 1024 or vector.get("datatype") != "float16" or
                info["config"]["params"].get("sparse_vectors")):
            raise ValueError("Restored collection is not the certified complete dense FP16 index")
        raw.unlink()
        return process, log, {"seconds": seconds, "points": info["points_count"], "log": str(log_path)}
    except BaseException:
        stop_service(process, log)
        raise


class NotebookQdrant(QdrantManager):
    def __init__(self, *args, hnsw_ef=None, exact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.hnsw_ef, self.exact = hnsw_ef, exact

    def _request(self, method, path, body=None):
        search = path.endswith("/points/query")
        if search:
            body = deepcopy(body)
            if self.hnsw_ef is not None:
                body.setdefault("params", {}).setdefault("hnsw_ef", self.hnsw_ef)
            if self.exact:
                body.setdefault("params", {})["exact"] = True
            path += f"?timeout={max(1, int(self.timeout) - 10)}"
        started = time.monotonic()
        result = super()._request(method, path, body)
        if search:
            LOGGER.info("Qdrant dense: hits=%d limit=%d ef=%s exact=%s %.3fs",
                        len(result["points"]), body["limit"], body.get("params", {}).get("hnsw_ef"),
                        self.exact, time.monotonic() - started)
        return result


def validate_results(output, archive, checkpoint, expected_ids, *, client=None, index=None, qdrant=None):
    """Validate durable rows and source text in bounded per-query batches."""
    if (client is None) == (qdrant is None):
        raise ValueError("Provide one source lookup backend: Elasticsearch or Qdrant")
    expected_ids = list(expected_ids)
    seen, chunk_count = {}, 0
    with Path(checkpoint).open() as stream:
        next(stream)
        for line in stream:
            item = json.loads(line)
            prediction, chunk_ids = item["prediction"], item["chunk_ids"]
            identifier = source_id(prediction["id"])
            if identifier in seen:
                raise ValueError("Duplicate checkpoint query")
            seen[identifier] = item["row"]
            for doc in prediction["relevant_docs"]:
                source_id(doc)
            chunks = prediction["relevant_chunks"]
            if len(chunk_ids) != len(chunks):
                raise ValueError("Output chunk identity count differs")
            ids = []
            for chunk_id, chunk in zip(chunk_ids, chunks, strict=True):
                doc = source_id(chunk["doc_id"])
                if not isinstance(chunk["chunk_text"], str) or not chunk["chunk_text"].strip():
                    raise ValueError("Invalid output chunk text")
                identity = json.dumps([str(doc), chunk_id], ensure_ascii=False)
                ids.append(hashlib.sha256(identity.encode()).hexdigest())
            if ids:
                if qdrant is not None:
                    points = qdrant._request("POST", qdrant._path + "/points/scroll", {
                        "filter": {"must": [{"key": "chunk_id", "match": {"any": chunk_ids}}]},
                        "limit": len(chunk_ids), "with_payload": ["doc_id", "chunk_id", "content", "chunk_text"],
                        "with_vector": False,
                    })["points"]
                    sources = {point["payload"]["chunk_id"]: point["payload"] for point in points}
                    docs = [{"found": chunk_id in sources, "_source": sources.get(chunk_id, {})}
                            for chunk_id in chunk_ids]
                else:
                    docs = client.mget(index=index, ids=ids, source_includes=["doc_id", "chunk_id", "content"])["docs"]
                if len(docs) != len(chunks):
                    raise ValueError("Source lookup count differs")
                for doc, chunk_id, chunk in zip(docs, chunk_ids, chunks, strict=True):
                    source = doc.get("_source", {})
                    if (not doc.get("found") or source.get("chunk_id") != chunk_id or
                            str(source.get("doc_id")) != str(chunk["doc_id"]) or
                            source.get("chunk_text", source.get("content")) != chunk["chunk_text"]):
                        raise ValueError("Output text differs from original source content")
            chunk_count += len(chunks)
    if sorted(seen, key=seen.get) != expected_ids:
        raise ValueError("Checkpoint IDs/order differ from selected query rows")
    digest = hashlib.sha256()
    with zipfile.ZipFile(archive) as zipped:
        if zipped.namelist() != [Path(output).name]:
            raise ValueError("ZIP must contain only the output JSON")
        with zipped.open(Path(output).name) as source:
            for block in iter(lambda: source.read(1024**2), b""):
                digest.update(block)
    if digest.hexdigest() != sha_file(Path(output)):
        raise ValueError("ZIP content differs from the final JSON")
    return {"queries": len(seen), "chunks_verified": chunk_count, "zip_verified": True}
