"""Focused offline checks and optional real Qdrant snapshot/restore integration."""

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace
import uuid

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import requests

from Scripts.Kaggle import prepare_vibiomir_qdrant as package
from Scripts.Kaggle import vibiomir_qdrant_runtime as runner
from Scripts.Kaggle import restore_vibiomir_qdrant as restore
from Scripts.Kaggle import check_vibiomir_snapshot as recheck


@pytest.fixture
def fixture(tmp_path, request):
    dimension = getattr(request, "param", 4)
    source = {"source_sha256": "source-sha", "total_rows": 12, "num_parts": 3,
              "shards": [{"part": p, "gpu": g, "rows": 2, "start_line": (p-1)*4+g*2+1,
                          "end_line": (p-1)*4+g*2+2} for p in (1, 2, 3) for g in (0, 1)]}
    encoder = {"dimension": dimension, "vector_name": "qwen3_dense", "model_id": "fixture-model",
               "revision": "fixed", "pooling": "last_token", "normalize": True, "output_dtype": "float32"}
    profile = hashlib.sha256(json.dumps(encoder, sort_keys=True).encode()).hexdigest()
    inputs = tmp_path / "input"
    payloads = []
    for part in (1, 2, 3):
        folder = inputs / f"part-{part}"
        folder.mkdir(parents=True)
        receipts = []
        for gpu in (0, 1):
            start = (part-1)*4+gpu*2+1
            records = []
            for line in (start, start+1):
                payload = {"chunk_id": f"chunk-{line}", "doc_id": line//3, "content": f"Nội dung 中文 English {line}",
                           "content_origin": ["hf_sqlite", "postgresql_sbtc", "linked_pdf"][line%3], "token_count": 7,
                           "extra_source_metadata": {"retain": [True, None, "đúng"]}}
                content_hash = hashlib.sha256(payload["content"].encode()).hexdigest()
                payload["_embedding"] = {"source_sha256": source["source_sha256"], "profile_id": profile,
                                         "source_line": line, "source_byte": line*200, "content_sha256": content_hash,
                                         "part": part, "gpu": gpu, "input_token_count": 9, "truncated": False}
                payloads.append(payload)
                vector = np.random.default_rng(line).normal(size=dimension).astype(np.float32)
                vector /= np.linalg.norm(vector)
                records.append({"point_id": str(uuid.uuid5(runner.NAMESPACE, payload["chunk_id"])),
                                **{k: payload[k] for k in ("chunk_id", "doc_id", "content", "content_origin", "token_count")},
                                "source_line": line, "source_byte": line*200, "input_token_count": 9,
                                "content_sha256": content_hash, "payload_json": json.dumps(payload, ensure_ascii=False),
                                "vector": vector.tolist()})
            table = pa.Table.from_pylist(records)
            idx = table.schema.get_field_index("vector")
            table = table.set_column(idx, "vector", pa.array([r["vector"] for r in records], pa.list_(pa.float32(), dimension)))
            table = table.replace_schema_metadata({b"vibiomir_embedding": json.dumps({
                "profile_id": profile, "source_sha256": source["source_sha256"]}).encode()})
            path = folder / f"p{part}-g{gpu}.parquet"
            pq.write_table(table, path)
            receipts.append({"file": path.name, "part": part, "gpu": gpu, "rows": 2,
                             "start_line": start, "end_line": start+1, "profile_id": profile,
                             "source_sha256": source["source_sha256"], "sha256": runner.checksum(path)})
        (folder / "manifest.json").write_text(json.dumps({"schema_version": "vibiomir-embedding-v1", "part": part,
            "complete": True, "rows": 4, "expected_rows": 4, "source": source,
            "encoder": encoder, "profile_id": profile, "files": receipts}))
    config = {**package.CONFIG, "input_root": str(inputs), "expected_chunks": 12, "dimension": dimension,
              "source_sha256": source["source_sha256"], "profile_id": profile, "batch_size": 1,
              "state_dir": str(tmp_path / "state"), "output": str(tmp_path / "output"),
              "output_budget_root": str(tmp_path / "output"), "output_limit_bytes": 128*1024**2,
              "hnsw_m": 8, "ef_construction": 32, "indexing_threshold_kb": 1,
              "index_timeout_seconds": 90, "index_poll_seconds": 0.1}
    Path(config["state_dir"]).mkdir()
    Path(config["output"]).mkdir()
    return config, payloads


def test_all_three_parts_and_opaque_ids_preserve_complete_payload(fixture):
    config, payloads = fixture
    catalog = runner.load_catalog(config)
    assert catalog["rows"] == 12 and catalog["parts"] == [1, 2, 3]
    points = [p for item in catalog["files"] for batch, _ in runner.iter_points(
        item["path"], item["receipt"], 4, 1) for p in batch]
    assert [p["payload"] for p in points] == payloads
    assert len({p["id"] for p in points}) == 12
    assert all(set(p["vector"]) == {"qwen3_dense"} for p in points)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "incomplete", "checksum", "profile", "gap"])
def test_invalid_inputs_stop_before_ingest(fixture, fault):
    config, _ = fixture
    root = Path(config["input_root"])
    path = root / "part-3/manifest.json"
    data = json.loads(path.read_text())
    if fault == "missing":
        path.unlink()
    elif fault == "duplicate":
        duplicate = root / "duplicate"
        duplicate.mkdir()
        (duplicate / "manifest.json").write_text(json.dumps(data))
    else:
        if fault == "incomplete": data["complete"] = False
        if fault == "checksum": data["files"][0]["sha256"] = "wrong"
        if fault == "profile": data["profile_id"] = "wrong"
        if fault == "gap": data["files"][0]["start_line"] += 1
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, FileNotFoundError)):
        runner.load_catalog(config)


@pytest.mark.parametrize("field", ["point_id", "source_byte", "content_sha256", "input_token_count"])
def test_corrupt_row_mapping_is_rejected(fixture, field):
    config, _ = fixture
    catalog = runner.load_catalog(config)
    item = catalog["files"][0]
    path = Path(item["path"])
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0][field] = "wrong" if isinstance(rows[0][field], str) else 999
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    with pytest.raises(ValueError, match="mismatch"):
        list(runner.iter_points(path, item["receipt"], 4, 2))


def test_same_ids_replayed_after_lost_upsert_response(fixture, monkeypatch):
    config, _ = fixture
    catalog = runner.load_catalog(config)
    item = catalog["files"][0]
    points, _ = next(runner.iter_points(item["path"], item["receipt"], 4, 2))
    stored, calls = {}, []
    class Session:
        def put(self, url, json, timeout):
            calls.append(json)
            stored.update({p["id"]: p for p in json["points"]})
            if len(calls) == 1:
                raise requests.Timeout("response lost after commit")
            return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                   json=lambda: {"result": {"status": "completed"}})
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    runner.upsert(config, points, Session())
    assert len(stored) == 2 and calls[0] == calls[1]


def test_resume_replays_batch_after_checkpoint_write_failure(fixture, monkeypatch):
    config, _ = fixture
    catalog = runner.load_catalog(config)
    identity = runner.signature(config, catalog)
    state = {"identity": identity, "rows": 0, "file_index": 0, "file_rows": 0, "phase": "new"}
    runner.write_json(runner.checkpoint_path(config), state)
    stored = {}
    monkeypatch.setattr(runner, "upsert", lambda config, points, session: stored.update({p["id"]: p for p in points}))
    monkeypatch.setattr(runner, "count_points", lambda config: len(stored))
    original_write = runner.write_json
    failed = False
    def interrupted(path, value):
        nonlocal failed
        if Path(path) == runner.checkpoint_path(config) and not failed:
            failed = True
            raise OSError("simulated checkpoint interruption")
        original_write(path, value)
    monkeypatch.setattr(runner, "write_json", interrupted)
    with pytest.raises(OSError): runner.ingest(config, catalog, state, runner.time.monotonic())
    assert len(stored) == 1
    state = json.loads(runner.checkpoint_path(config).read_text())
    runner.ingest(config, catalog, state, runner.time.monotonic())
    assert len(stored) == 12 and state["rows"] == 12 and state["file_index"] == 6


def test_resume_uses_snapshot_checkpoint_and_rejects_changed_identity(fixture):
    config, _ = fixture
    catalog = runner.load_catalog(config)
    identity = runner.signature(config, catalog)
    folder = Path(config["output"]) / "attached"
    folder.mkdir()
    manifest = {"signature": {**identity, "dense_datatype": "float32"}, "qdrant_version": runner.QDRANT_VERSION}
    (folder / "snapshot_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="different input"):
        runner.restore_for_resume({**config, "resume_from": str(folder)}, identity)


def test_resource_guard_rejects_ramdisk_state(fixture, monkeypatch):
    config, _ = fixture
    catalog = runner.load_catalog(config)
    monkeypatch.setattr(runner.psutil, "disk_partitions", lambda all: [SimpleNamespace(mountpoint="/", fstype="tmpfs")])
    with pytest.raises(RuntimeError, match="must use disk"):
        runner.check_resources(config, catalog)


def test_embedded_notebook_matches_sources_and_cpu_only():
    path = package.ROOT / "BackEnd/app/Database/Notebook" / package.NOTEBOOK_NAME
    notebook = json.loads(path.read_text())
    assert notebook["metadata"]["kaggle"]["isGpuEnabled"] is False
    embedded = None
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code": continue
        assert cell["execution_count"] is None and cell["outputs"] == []
        source = "".join(cell["source"])
        compile(source, "notebook", "exec")
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MODULES" for t in node.targets):
                embedded = ast.literal_eval(node.value)
    assert embedded
    for name, source in embedded.items():
        assert source == (package.ROOT / "Scripts/Kaggle" / name).read_text()
        compile(source, name, "exec")
    assert "import torch" not in embedded["vibiomir_qdrant_runtime.py"]
    assert "sparse_vectors\": {" not in embedded["vibiomir_qdrant_runtime.py"]
    assert len(package.SOURCES) == 3 and package.CONFIG["hnsw_m"] == 32


@pytest.mark.skipif(not os.getenv("QDRANT_TEST_BINARY"), reason="Set QDRANT_TEST_BINARY for real server integration")
def test_real_fp16_ingest_snapshot_restore_and_resume(fixture, monkeypatch):
    config, _ = fixture
    config["binary"] = os.environ["QDRANT_TEST_BINARY"]
    config["ingest_stop_seconds"] = 300
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config.update(port=port, qdrant_url=f"http://127.0.0.1:{port}")
    # Fixture intentionally uses only 12 vectors; production resource bounds do not apply.
    monkeypatch.setattr(runner, "check_resources", lambda *args: None)
    runner.run_pipeline(config)
    folder = Path(config["output"])
    manifest, _ = restore.unpack(folder)
    assert manifest["complete"] and manifest["points"] == 12
    assert manifest["restore_verification"]["verified"]
    checkpoint = copy.deepcopy(manifest["checkpoint"])
    # Deliberately newer standalone checkpoint must not override snapshot-bound progress.
    (folder / "ingestion_checkpoint.json").write_text(json.dumps({"rows": 999}))
    resumed = {**config, "resume_from": str(folder), "state_dir": str(folder.parent / "resumed-state"),
               "output": str(folder.parent / "resumed-output"), "output_budget_root": str(folder.parent / "resumed-output")}
    runner.run_pipeline(resumed)
    final = json.loads((Path(resumed["output"]) / "snapshot_manifest.json").read_text())
    assert final["points"] == 12 and final["checkpoint"]["rows"] == checkpoint["rows"]


@pytest.mark.skipif(not os.getenv("QDRANT_TEST_BINARY"), reason="Set QDRANT_TEST_BINARY for real server integration")
def test_real_interruption_exports_recovery_and_resumes_remaining_rows(fixture, monkeypatch):
    config, _ = fixture
    config["binary"] = os.environ["QDRANT_TEST_BINARY"]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config.update(port=port, qdrant_url=f"http://127.0.0.1:{port}")
    monkeypatch.setattr(runner, "check_resources", lambda *args: None)
    original_upsert = runner.upsert
    calls = 0
    def interrupt(config, points, session):
        nonlocal calls
        if not config["collection"].endswith("_preflight"):
            calls += 1
            if calls == 3:
                raise TimeoutError("controlled interruption during ingest")
        return original_upsert(config, points, session)
    monkeypatch.setattr(runner, "upsert", interrupt)
    with pytest.raises(TimeoutError, match="controlled interruption"):
        runner.run_pipeline(config)
    folder = Path(config["output"])
    recovery = json.loads((folder / "snapshot_manifest.json").read_text())
    assert not recovery["complete"] and recovery["points"] == 2
    assert recovery["restore_verification"]["verified"]
    assert json.loads((folder / "pipeline_status.json").read_text())["recovery_exported"]
    monkeypatch.setattr(runner, "upsert", original_upsert)
    resumed = {**config, "resume_from": str(folder), "state_dir": str(folder.parent / "resumed-state"),
               "output": str(folder.parent / "resumed-output"), "output_budget_root": str(folder.parent / "resumed-output")}
    runner.run_pipeline(resumed)
    complete = json.loads((Path(resumed["output"]) / "snapshot_manifest.json").read_text())
    assert complete["complete"] and complete["points"] == 12


def test_search_timeout_is_sent_to_qdrant_server(monkeypatch):
    calls = []
    class Session:
        def request(self, method, url, json, timeout):
            calls.append((url, timeout))
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {"result": {"points": []}})
        def close(self): pass
    monkeypatch.setattr(restore.requests, "Session", Session)
    default = restore.QdrantDenseClient("http://localhost:6333", "test")
    default.search_dense([1.0])
    timed = restore.QdrantDenseClient("http://localhost:6333", "test", search_timeout=300, request_timeout=330)
    timed.search_dense([1.0])
    assert calls == [("http://localhost:6333/collections/test/points/query", 300),
                     ("http://localhost:6333/collections/test/points/query?timeout=300", 330)]


def test_staging_snapshot_checks_source_and_staged_sha(tmp_path):
    source, target = tmp_path / "source.snapshot", tmp_path / "staged.snapshot"
    source.write_bytes(b"existing snapshot content")
    recheck.stage_snapshot(source, target, runner.checksum(source))
    assert target.read_bytes() == source.read_bytes()
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        recheck.stage_snapshot(source, target, "wrong")


@pytest.mark.skipif(not os.getenv("QDRANT_TEST_BINARY"), reason="Set QDRANT_TEST_BINARY for real server integration")
@pytest.mark.parametrize("fixture", [512], indirect=True)
def test_real_snapshot_recheck_without_reingest_or_changing_source_manifest(fixture, monkeypatch):
    config, _ = fixture
    config["binary"] = os.environ["QDRANT_TEST_BINARY"]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config.update(port=port, qdrant_url=f"http://127.0.0.1:{port}")
    monkeypatch.setattr(runner, "check_resources", lambda *args: None)
    runner.run_pipeline(config)
    original_folder = Path(config["output"])
    source_manifest = original_folder / "snapshot_manifest.json"
    data = json.loads(source_manifest.read_text())
    data["complete"] = False
    source_manifest.write_text(json.dumps(data))
    original_text = source_manifest.read_text()
    check_config = {**config, "input_root": str(original_folder), "source_kernel": "test/snapshot/1",
                    "state_dir": str(original_folder.parent / "check-state"),
                    "output": str(original_folder.parent / "check-output"), "search_timeout_seconds": 10}
    monkeypatch.setattr(recheck.psutil, "disk_partitions", lambda all: [SimpleNamespace(mountpoint="/", fstype="ext4")])
    recheck.run(check_config)
    report = json.loads((Path(check_config["output"]) / "recheck_report.json").read_text())
    assert report["passed"] and report["points"] == 12
    assert not report["reingested"] and not report["reembedded"]
    assert report["source_manifest_complete"] is False
    assert all(check["passed"] for check in report["queries"])
    assert source_manifest.read_text() == original_text
