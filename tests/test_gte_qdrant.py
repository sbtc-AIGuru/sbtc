"""Small offline checks plus real snapshot/restore when QDRANT_TEST_BINARY is set."""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tarfile
from types import SimpleNamespace

import numpy as np
import pytest
import requests
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Scripts.Qdrant import build_gte_qdrant as runner
from Scripts.Qdrant import restore_qdrant_snapshot as restore

NOTEBOOK = ROOT / "BackEnd/app/Database/Notebook/Qdrant_GTE_Snapshot_2GPU.ipynb"


@pytest.fixture
def config(tmp_path):
    source = tmp_path / "merged.jsonl"
    documents = []
    for number in range(100):
        documents.append({"doc_id": number, "url": f"https://example.org/{number}",
                          "source_language": "vi", "children": [{
            "chunk_id": f"{number}:c{offset}", "parent_id": f"{number}:p0",
            "chunk_order": offset, "start_char": 0, "end_char": 20,
            "chunk_text": "" if number % 11 == 0 else f"English / tiếng Việt / 中文 {number} {offset}",
            "retrieval_eligible": number % 2 == 0,
        } for offset in range(3)]})
    source.write_text("".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in documents))
    state, output = tmp_path / "state", tmp_path / "output"
    state.mkdir()
    output.mkdir()
    return {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "expected_documents": 100, "expected_chunks": 300, "dimension": 16,
            "model": "Alibaba-NLP/gte-multilingual-base", "revision": "model-revision",
            "code_revision": "code-revision", "max_length": 8192,
            "collection": "sbtc_test", "state_dir": str(state), "output": str(output),
            "output_budget_root": str(output), "output_limit_bytes": 1024**3,
            "binary": os.environ.get("QDRANT_TEST_BINARY", "/not-installed/qdrant"),
            "hnsw_m": 8, "ef_construction": 32, "indexing_threshold_kb": 1,
            "index_timeout_seconds": 90, "index_poll_seconds": 0.1,
            "buffer_size": 16, "upsert_batch_size": 8, "shards": [150, 150]}


def fake_encoder(monkeypatch):
    monkeypatch.setattr(runner, "load_encoder", lambda config: (None, None))

    def encode(records, tokenizer, forward, config):
        vectors = []
        for record in records:
            seed = int.from_bytes(hashlib.sha256(record["text"].encode()).digest()[:8])
            vectors.append(np.random.default_rng(seed).normal(size=config["dimension"]))
        return runner.normalize_vectors(np.array(vectors)), 0

    monkeypatch.setattr(runner, "encode_records", encode)


def test_source_shards_payload_and_checksum(config):
    source = runner.validate_source(config)
    assert source["chunks"] == 300 and source["shards"] == [150, 150]
    assert 0 < source["gzip_payload_bytes"] < source["payload_bytes"]
    rows = [row for rank in range(2) for row in runner.iter_records(Path(config["source"]), rank)]
    assert len({row["chunk_id"] for row in rows}) == 300
    assert any(row["empty_text"] and row["chunk_text"] == "" for row in rows)
    assert any(row["retrieval_eligible"] is False for row in rows)
    assert all(row["url"] and row["source_language"] == "vi" for row in rows)
    with pytest.raises(ValueError, match="SHA-256"):
        runner.validate_source({**config, "source_sha256": "wrong"})
    with pytest.raises(ValueError, match="counts"):
        runner.validate_source({**config, "expected_chunks": 301})


def test_upsert_retries_acknowledgement_loss_with_same_ids(config, monkeypatch):
    rows = list(runner.iter_records(Path(config["source"]), 0))[:2]
    points, calls = {}, []

    def api(config, method, path, body, **kwargs):
        calls.append(body)
        points.update({point["id"]: point for point in body["points"]})
        if len(calls) == 1:
            raise requests.Timeout("Response lost after commit")
        return {"status": "completed"}

    monkeypatch.setattr(runner, "api", api)
    monkeypatch.setattr(runner.time, "sleep", lambda delay: None)
    vectors = runner.normalize_vectors(np.ones((2, 16)))
    runner.upsert_batch(config, rows, vectors, None)
    assert calls[0] == calls[1] and len(points) == 2
    assert {point["payload"]["chunk_id"] for point in points.values()} == {row["chunk_id"] for row in rows}


def test_interrupted_worker_replays_uncommitted_batch_without_duplicate_points(config, monkeypatch):
    fake_encoder(monkeypatch)
    points = {}

    def upsert(config, records, vectors, session):
        points.update({runner.point_id(row["chunk_id"]): row for row in records})

    original_write = runner.write_json
    first = True

    def interrupted(path, value):
        nonlocal first
        if path.name == "gpu0.progress.json" and first:
            first = False
            raise RuntimeError("Interrupted after server commit")
        original_write(path, value)

    monkeypatch.setattr(runner, "upsert_batch", upsert)
    monkeypatch.setattr(runner, "write_json", interrupted)
    with pytest.raises(RuntimeError, match="Interrupted"):
        runner.run_worker(config, 0)
    assert len(points) == config["buffer_size"]
    runner.run_worker(config, 0)
    assert len(points) == 150
    assert json.loads(runner.progress_path(config, 0).read_text())["chunks"] == 150


@pytest.mark.parametrize("count", [0, 1])
def test_never_falls_back_from_two_gpus(config, monkeypatch, count):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: count > 0)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: count)
    with pytest.raises(RuntimeError, match="two CUDA GPUs"):
        runner.embed_two_gpus(config, Path("not-used.json"))


def test_output_budget_accounts_for_other_files_and_physical_space(config, monkeypatch):
    root = Path(config["output_budget_root"])
    (root / "existing.bin").write_bytes(b"x" * 20)
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=2 * 1024**3))
    assert runner.output_budget(config) == 1024**3 - 20
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=100))
    assert runner.output_budget(config) == 0


def test_resource_guard_uses_state_disk_separately_from_kaggle_output(config, monkeypatch):
    config = {**config, "expected_chunks": 4_342_218, "dimension": 768,
              "output_limit_bytes": 18 * 1024**3, "hnsw_m": 32}
    monkeypatch.setattr(runner.psutil, "disk_partitions", lambda **kwargs: [SimpleNamespace(mountpoint="/", fstype="ext4")])
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(
        free=int((1069.7 if Path(path) == Path(config["state_dir"]) else 19.5) * 1024**3)))
    source = {"payload_bytes": 4 * 1024**3, "gzip_payload_bytes": 512 * 1024**2}
    runner.check_resources(config, source)
    monkeypatch.setattr(runner.psutil, "disk_partitions", lambda **kwargs: [SimpleNamespace(mountpoint="/", fstype="tmpfs")])
    with pytest.raises(RuntimeError, match="must be on disk"):
        runner.check_resources(config, source)


@pytest.mark.parametrize("compressed", [False, True])
def test_restore_helper_checks_checksums_and_unpacks(tmp_path, compressed):
    data = b"test snapshot content" * 200
    raw_sha256 = hashlib.sha256(data).hexdigest()
    name = "test.snapshot.gz" if compressed else "test.snapshot"
    target = tmp_path / name
    target.write_bytes(gzip.compress(data) if compressed else data)
    manifest = {"snapshot_file": name, "snapshot_sha256": runner.checksum(target),
                "raw_snapshot_sha256": raw_sha256, "raw_snapshot_bytes": len(data)}
    (tmp_path / "snapshot_manifest.json").write_text(json.dumps(manifest))
    _, raw = restore.unpack(tmp_path)
    assert raw.read_bytes() == data
    target.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        restore.unpack(tmp_path)


def test_failed_optimization_never_reports_success(config, monkeypatch):
    monkeypatch.setattr(runner, "api", lambda *args, **kwargs: {
        "status": "red", "optimizer_status": {"error": "Disk full"},
    })
    with pytest.raises(RuntimeError, match="optimizer error"):
        runner.wait_for_index(config)


def test_recovery_snapshot_waits_for_in_flight_point_count_to_settle(config, monkeypatch):
    snapshot_dir = Path(config["state_dir"]) / "snapshots" / config["collection"]
    snapshot_dir.mkdir(parents=True)
    snapshot = snapshot_dir / "test.snapshot"
    with tarfile.open(snapshot, "w") as archive:
        item = tarfile.TarInfo("test.bin")
        item.size = 10
        archive.addfile(item, io.BytesIO(b"x" * 10))
    counts = iter([1, 2, 2, 2])
    calls = []
    monkeypatch.setattr(runner, "count_points", lambda config: next(counts))

    def create_snapshot(*args, **kwargs):
        calls.append(True)
        return {"name": snapshot.name}

    monkeypatch.setattr(runner, "api", create_snapshot)
    manifest = runner.export_snapshot(config, complete=False)
    assert len(calls) == 2 and manifest["points"] == 2


def test_notebook_is_standalone_and_matches_sources():
    notebook = json.loads(NOTEBOOK.read_text())
    assert notebook["metadata"]["kaggle"]["isGpuEnabled"]
    assert notebook["metadata"]["kaggle"]["accelerator"] == "nvidiaTeslaT4"
    embedded = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            source = "".join(cell["source"])
            compile(source, str(NOTEBOOK), "exec")
            assert cell["execution_count"] is None and cell["outputs"] == []
            if source.startswith("runner_source ="):
                exec(source.split("runner_path.write_text")[0], embedded)
    assert embedded["runner_source"] == Path(runner.__file__).read_text()
    assert embedded["restore_source"] == Path(restore.__file__).read_text()


def unused_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


@pytest.mark.skipif(not os.environ.get("QDRANT_TEST_BINARY"), reason="Set QDRANT_TEST_BINARY for the real-server snapshot test")
@pytest.mark.parametrize("compressed", [False, True])
def test_real_qdrant_snapshot_restores_vectors_text_and_progress(config, tmp_path, monkeypatch, compressed):
    fake_encoder(monkeypatch)
    config = {**config, "port": unused_port()}
    config["qdrant_url"] = f"http://127.0.0.1:{config['port']}"
    process, log = runner.start_server(config)
    try:
        runner.create_collection(config)
        runner.run_worker(config, 0)
        runner.run_worker(config, 1)
        assert runner.count_points(config) == 300
        runner.wait_for_index(config)
        runner.check_search(config)
        if compressed:
            probe = runner.api(config, "POST", f"/collections/{config['collection']}/snapshots?wait=true")
            probe_path = Path(config["state_dir"]) / "snapshots" / config["collection"] / probe["name"]
            monkeypatch.setattr(runner, "output_budget", lambda config: probe_path.stat().st_size // 2)
        manifest = runner.export_snapshot(config, complete=True)
        raw = Path(config["output"]) / manifest["snapshot_file"]
        assert raw.suffix == (".gz" if compressed else ".snapshot")
        assert tarfile.is_tarfile(raw)
    finally:
        runner.stop_server(process, log)
    Path(config["source"]).rename(tmp_path / "source-not-needed-after-restore.jsonl")
    state, output = tmp_path / "restored-state", tmp_path / "restored-output"
    state.mkdir()
    output.mkdir()
    restored = {**config, "state_dir": str(state), "output": str(output),
                "resume_from": config["output"], "port": unused_port()}
    restored["qdrant_url"] = f"http://127.0.0.1:{restored['port']}"
    process, log = runner.start_server(restored)
    try:
        runner.restore_for_resume(restored)
        assert runner.count_points(restored) == 300
        runner.check_search(restored)
        points = runner.api(restored, "POST", f"/collections/{restored['collection']}/points/scroll",
                            {"limit": 1000, "with_payload": True, "with_vector": True})["points"]
        assert len(points) == 300
        assert any(point["payload"]["empty_text"] for point in points)
        assert any("中文" in point["payload"]["chunk_text"] for point in points)
        assert all(len(point["vector"]) == 16 for point in points)
        monkeypatch.setattr(runner, "load_encoder", lambda config: pytest.fail("Completed shards must not load the model"))
        runner.run_worker(restored, 0)
        runner.run_worker(restored, 1)
    finally:
        runner.stop_server(process, log)


@pytest.mark.skipif(not os.environ.get("QDRANT_TEST_BINARY"), reason="Set QDRANT_TEST_BINARY for the real-server recovery test")
def test_failed_pipeline_exports_recovery_then_resumes_to_complete(config, tmp_path, monkeypatch):
    fake_encoder(monkeypatch)
    config = {**config, "port": unused_port()}
    config["qdrant_url"] = f"http://127.0.0.1:{config['port']}"
    config_path = tmp_path / "config.json"
    # This small integration fixture intentionally uses /tmp on a RAM-backed
    # developer machine; production resource checks are covered separately.
    monkeypatch.setattr(runner, "check_resources", lambda *args: None)

    def interrupted(config, path):
        runner.run_worker(config, 0)
        raise RuntimeError("Synthetic GPU worker failure")

    monkeypatch.setattr(runner, "embed_two_gpus", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic"):
        runner.run_pipeline(config, config_path)
    output = Path(config["output"])
    partial = json.loads((output / "snapshot_manifest.json").read_text())
    assert partial["complete"] is False and partial["points"] == 150
    assert partial["progress"]["0"]["chunks"] == 150
    assert partial["progress"]["1"]["chunks"] == 0
    assert json.loads((output / "pipeline_status.json").read_text())["success"] is False

    def finish(config, path):
        runner.run_worker(config, 0)
        runner.run_worker(config, 1)

    monkeypatch.setattr(runner, "embed_two_gpus", finish)
    resumed = {**config, "state_dir": str(tmp_path / "resume-state"),
               "output": str(tmp_path / "resume-output"), "resume_from": str(output),
               "port": unused_port()}
    resumed["qdrant_url"] = f"http://127.0.0.1:{resumed['port']}"
    runner.run_pipeline(resumed, tmp_path / "resume-config.json")
    complete = json.loads((Path(resumed["output"]) / "snapshot_manifest.json").read_text())
    assert complete["complete"] and complete["points"] == 300
    assert json.loads((Path(resumed["output"]) / "pipeline_status.json").read_text())["success"] is True
