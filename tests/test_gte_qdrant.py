"""Small offline checks plus real snapshot/restore when QDRANT_TEST_BINARY is set."""

import ast
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tarfile
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import requests
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Scripts.Qdrant import build_gte_qdrant as runner
from Scripts.Qdrant import restore_qdrant_snapshot as restore
from BackEnd.app.Database.qdrant_db import QdrantManager

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
        } for offset in range(3)], "parents": [{"parent_id": f"{number}:p0"}]})
    source.write_text("".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in documents))
    state, output = tmp_path / "state", tmp_path / "output"
    state.mkdir()
    output.mkdir()
    return {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "expected_documents": 100, "expected_chunks": 300, "dimension": 16,
            "model": "Alibaba-NLP/gte-multilingual-base", "revision": "model-revision",
            "code_revision": "code-revision", "max_length": 8192,
            "collection": "sbtc_test", "qdrant_url": "http://127.0.0.1:6333",
            "state_dir": str(state), "output": str(output),
            "bm25_options": runner.BM25_OPTIONS,
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
    assert all(row["parent_id"] == f"{row['doc_id']}:p0" for row in rows)
    assert all(row["url"] and row["source_language"] == "vi" for row in rows)
    with pytest.raises(ValueError, match="SHA-256"):
        runner.validate_source({**config, "source_sha256": "wrong"})
    with pytest.raises(ValueError, match="counts"):
        runner.validate_source({**config, "expected_chunks": 301})


def test_source_rejects_unknown_parent_before_gpu(config):
    path = Path(config["source"])
    documents = [json.loads(line) for line in path.read_text().splitlines()]
    documents[0]["children"][0]["parent_id"] = "not-a-source-parent"
    path.write_text("\n".join(json.dumps(doc) for doc in documents))
    with pytest.raises(ValueError, match="Unknown parent_id"):
        runner.validate_source(config)


@pytest.mark.parametrize("field,value", [("chunk_id", ""), ("parent_id", None), ("doc_id", 999)])
def test_source_id_contract(config, field, value):
    document = json.loads(Path(config["source"]).read_text().splitlines()[0])
    child = {**document["children"][0], field: value}
    with pytest.raises(ValueError, match=field):
        runner.make_record(document, child, 1)


def test_real_dataset_ids_are_kept_verbatim():
    path = ROOT / "datav2/merged.jsonl"
    if not path.exists():
        pytest.skip("Local datav2 source not available")
    with path.open() as stream:
        document = json.loads(next(stream))
    parent_ids = {parent["parent_id"] for parent in document["parents"]}
    for child in document["children"]:
        payload = runner.make_record(document, child, 1)
        assert payload["chunk_id"] == child["chunk_id"]
        assert payload["parent_id"] == child["parent_id"] in parent_ids
        assert payload["doc_id"] == child["doc_id"] == document["doc_id"]


def test_collection_has_disk_sparse_idf_and_keyword_indexes(config, monkeypatch):
    monkeypatch.setattr(runner.requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=404))
    calls = []
    monkeypatch.setattr(runner, "api", lambda config, method, path, body: calls.append((path, body)))
    runner.create_collection(config)
    body = calls[0][1]
    assert body["vectors"]["dense"]["size"] == 16
    assert body["sparse_vectors"]["bm25"] == {"modifier": "idf", "index": {"on_disk": True}}
    assert {call[1]["field_name"] for call in calls[1:]} == {"chunk_id", "parent_id"}
    assert all(call[1]["field_schema"] == {"type": "keyword", "on_disk": True} for call in calls[1:])


def test_resume_signature_includes_bm25_and_rejects_old_dense_manifest(config, tmp_path):
    changed = {**config, "bm25_options": {**config["bm25_options"], "ascii_folding": True}}
    assert runner.signature(config) != runner.signature(changed)
    legacy = runner.signature(config)
    del legacy["vector_schema"]
    (tmp_path / "snapshot_manifest.json").write_text(json.dumps({
        "signature": legacy, "qdrant_version": runner.QDRANT_VERSION,
    }))
    with pytest.raises(ValueError, match="does not match"):
        runner.restore_for_resume({**config, "resume_from": str(tmp_path)})


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
    assert all(set(point["vector"]) == {"dense", "bm25"} for point in points.values())
    for point in points.values():
        assert point["vector"]["bm25"]["text"] == point["payload"]["chunk_text"]
        assert point["vector"]["bm25"]["options"] == runner.BM25_OPTIONS


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


def test_restore_validation_failure_cannot_publish_complete_manifest(config, monkeypatch):
    folder = Path(config["state_dir"]) / "snapshots" / config["collection"]
    folder.mkdir(parents=True)
    snapshot = folder / "test.snapshot"
    with tarfile.open(snapshot, "w") as archive:
        item = tarfile.TarInfo("test.bin")
        item.size = 1
        archive.addfile(item, io.BytesIO(b"x"))
    monkeypatch.setattr(runner, "count_points", lambda config: 1)
    monkeypatch.setattr(runner, "api", lambda *args, **kwargs: {"name": snapshot.name})

    def fail(*args):
        raise ValueError("Hybrid restore failed")

    monkeypatch.setattr(runner, "verify_snapshot_restore", fail)
    with pytest.raises(ValueError, match="Hybrid restore failed"):
        runner.export_snapshot(config, complete=True)
    assert not (Path(config["output"]) / "snapshot_manifest.json").exists()


@pytest.fixture
def notebook_sources():
    tree = ast.parse("".join(json.loads(NOTEBOOK.read_text())["cells"][6]["source"]))
    return {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)}


@pytest.fixture
def notebook_runner(notebook_sources):
    module = ModuleType("qwen3_notebook_test")
    exec(compile(notebook_sources["runner_source"], "<qwen3_notebook_runner>", "exec"), module.__dict__)
    return module


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
    # The notebook uses Qwen3/float16 storage; the standalone GTE runner stays intact.
    changed_functions = {"vector_schema", "encode_records", "load_encoder", "signature",
                         "check_resources", "create_collection", "wait_for_index",
                         "export_snapshot", "run_pipeline"}
    original = {node.name: ast.dump(node) for node in ast.parse(Path(runner.__file__).read_text()).body
                if isinstance(node, ast.FunctionDef)}
    for node in ast.parse(embedded["runner_source"]).body:
        if isinstance(node, ast.FunctionDef) and node.name not in changed_functions:
            assert ast.dump(node) == original[node.name], node.name
    assert embedded["restore_source"] == Path(restore.__file__).read_text()
    client = (ROOT / "BackEnd/app/Database/qdrant_db.py").read_text()
    client = client.replace('"sbtc_gte_multilingual"', '"sbtc_qwen3_embedding_0_6b_1024"')
    client = client.replace("same GTE encoder", "same Qwen3 encoder")
    client = client.replace("snapshot's GTE model/revision and CLS\n        pooling",
        "snapshot's Qwen3 model/revision and last-token\n        pooling with left padding, L2 normalization and the documented query instruction")
    assert embedded["client_source"] == client


def test_notebook_qwen3_float32_inference_and_empty_long_chunks(notebook_runner, monkeypatch):
    from tokenizers import Tokenizer, models, pre_tokenizers
    import transformers

    backend = Tokenizer(models.WordLevel(
        {"[UNK]": 0, "[PAD]": 1, "[EOS]": 2, "one": 3, "two": 4}, unk_token="[UNK]"))
    backend.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token="[UNK]", pad_token="[PAD]", eos_token="[EOS]",
        model_input_names=["input_ids", "attention_mask"])
    model = transformers.Qwen3Model(transformers.Qwen3Config(
        vocab_size=5, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=16, pad_token_id=1,
        max_position_embeddings=64, attn_implementation="sdpa"))
    loaded = {}

    def load_tokenizer(*args, **kwargs):
        tokenizer.padding_side = kwargs["padding_side"]
        return tokenizer

    def load_model(*args, **kwargs):
        loaded.update(kwargs)
        return model.to(dtype=kwargs["torch_dtype"])

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", load_tokenizer)
    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", load_model)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device: None)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda rank: "CPU test")
    cpu = torch.device("cpu")
    monkeypatch.setattr(torch, "device", lambda name: cpu)
    config = {"model": "Qwen/Qwen3-Embedding-0.6B", "revision": "test", "dimension": 32,
              "rank": 0, "batch_size": 8, "max_length": 3, "token_budget": 24}
    previous_threads = torch.get_num_threads()
    try:
        _, forward = notebook_runner.load_encoder(config)
        assert loaded["torch_dtype"] == torch.float32
        assert next(model.parameters()).dtype == torch.float32
        assert tokenizer.padding_side == "left" and model.config.use_cache is False
        records = [{"text": text} for text in ("", "one two one two", "two")]
        vectors, long_count = notebook_runner.encode_records(records, tokenizer, forward, config)
        pieces = []
        for ids in ([2], [3, 4, 3], [4]):
            with torch.inference_mode():
                pieces.append(model(input_ids=torch.tensor([ids]), use_cache=False)
                              .last_hidden_state[0, -1].numpy())
        pieces = notebook_runner.normalize_vectors(np.array(pieces))
        expected = notebook_runner.normalize_vectors(np.array([
            pieces[0], 3 * pieces[1] + pieces[2], pieces[2]]))
        np.testing.assert_allclose(vectors, expected, atol=1e-5)
        assert long_count == 1 and vectors.dtype == np.float32
    finally:
        torch.set_num_threads(previous_threads)


def test_notebook_stores_1024_float16_and_keeps_bm25_payload(config, notebook_runner, monkeypatch):
    config = {**config, "dimension": 1024}
    monkeypatch.setattr(notebook_runner.requests, "get",
                        lambda *args, **kwargs: SimpleNamespace(status_code=404))
    calls = []
    monkeypatch.setattr(notebook_runner, "api",
                        lambda config, method, path, body: calls.append((path, body)))
    notebook_runner.create_collection(config)
    body = calls[0][1]
    assert body["vectors"]["dense"] == {
        "size": 1024, "distance": "Cosine", "on_disk": True, "datatype": "float16"}
    assert body["sparse_vectors"]["bm25"] == {"modifier": "idf", "index": {"on_disk": True}}
    assert body["on_disk_payload"] is True
    assert {call[1]["field_name"] for call in calls[1:]} == {"chunk_id", "parent_id"}
    assert notebook_runner.signature(config)["vector_schema"]["dense_datatype"] == "float16"


def test_notebook_rejects_existing_float32_collection(config, notebook_runner, monkeypatch):
    params = {"vectors": {"dense": {"size": 1024, "distance": "Cosine", "datatype": "float32"}},
              "sparse_vectors": {"bm25": {"modifier": "idf"}}}
    monkeypatch.setattr(notebook_runner.requests, "get", lambda *args, **kwargs: SimpleNamespace(
        status_code=200, raise_for_status=lambda: None,
        json=lambda: {"result": {"config": {"params": params}}}))
    with pytest.raises(ValueError, match="use new state"):
        notebook_runner.create_collection({**config, "dimension": 1024})


def test_notebook_resource_budget_uses_float16(config, notebook_runner, monkeypatch):
    config = {**config, "dimension": 1024, "expected_chunks": 4_342_218,
              "output_limit_bytes": 10 * 1024**3, "hnsw_m": 32}
    monkeypatch.setattr(notebook_runner.psutil, "disk_partitions",
                        lambda **kwargs: [SimpleNamespace(mountpoint="/", fstype="ext4")])
    monkeypatch.setattr(notebook_runner.shutil, "disk_usage", lambda path: SimpleNamespace(
        free=(1000 if Path(path) == Path(config["state_dir"]) else 20) * 1024**3))
    notebook_runner.check_resources(config, {"payload_bytes": 0, "gzip_payload_bytes": 0})


def test_notebook_manifest_separates_inference_and_storage(config, notebook_runner, monkeypatch):
    folder = Path(config["state_dir"]) / "snapshots" / config["collection"]
    folder.mkdir(parents=True)
    with tarfile.open(folder / "test.snapshot", "w") as archive:
        item = tarfile.TarInfo("test.bin")
        item.size = 4
        archive.addfile(item, io.BytesIO(b"test"))
    monkeypatch.setattr(notebook_runner, "count_points", lambda config: 1)
    monkeypatch.setattr(notebook_runner, "api", lambda *args, **kwargs: {"name": "test.snapshot"})
    manifest = notebook_runner.export_snapshot(config, complete=False)
    assert manifest["embedding"]["inference"] == "float32"
    assert manifest["embedding"]["storage"] == "float16"
    assert manifest["embedding"]["pooling"] == "last_token"
    assert manifest["vector_schema"]["dense_datatype"] == "float16"


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
        assert all(len(point["vector"]["dense"]) == 16 and "bm25" in point["vector"] for point in points)
        assert all(point["payload"]["parent_id"] == f"{point['payload']['doc_id']}:p0" for point in points)
        assert manifest["restore_verification"]["verified"]
        assert manifest["restore_verification"]["search"]["hybrid"]
        assert restore.verify(Path(config["output"]), restored["qdrant_url"])["hybrid"]
        sample = next(point for point in points if point["vector"]["bm25"]["indices"])
        payload = sample["payload"]
        with QdrantManager.from_manifest(
            Path(config["output"]) / "snapshot_manifest.json", url=restored["qdrant_url"],
            dense_encoder=lambda texts: [sample["vector"]["dense"] for _ in texts],
        ) as client:
            hits = client.search_text(sample["vector"]["dense"], payload["chunk_text"],
                query_filter={"must": [
                    {"key": field, "match": {"value": payload[field]}}
                    for field in ("chunk_id", "parent_id")
                ]})
            assert len(hits) == 1 and hits[0]["id"] == sample["id"]
            assert hits[0]["payload"] == payload
            query = {"original_query": payload["chunk_text"],
                     "eng_query": "English", "chinese_query": "中文"}
            query_filter = {"must": [
                {"key": field, "match": {"value": payload[field]}}
                for field in ("chunk_id", "parent_id")
            ]}
            for method in (client.query_original_dense, client.query_multilingual_dense):
                hits = method(query, query_filter=query_filter)
                assert len(hits) == 1 and hits[0]["id"] == sample["id"]
                assert hits[0]["payload"] == payload
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
