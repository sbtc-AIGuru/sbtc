import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest

from Scripts.Kaggle import hybrid_retrieval_runtime as runtime
from Scripts.Kaggle import prepare_hybrid_retrieval_notebook as package
from Scripts.Kaggle import publish_hybrid_retrieval_notebook as publish


def test_package_has_one_described_module_per_cell_and_exact_private_inputs(tmp_path, monkeypatch):
    text, vectors = tmp_path / "query_rewritten_weighted.parquet", tmp_path / "query_rewritten_weighted_qwen3_1024_fp16.parquet"
    text.write_bytes(b"original private text file")
    vectors.write_bytes(b"original private vector file")
    notebook = package.prepare(tmp_path / "package", text, vectors, write_notebook=False)
    assert len({cell["id"] for cell in notebook["cells"]}) == len(notebook["cells"])
    code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(code) == 18
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile(cell["source"], cell["id"], "exec")
            assert notebook["cells"][index - 1]["cell_type"] == "markdown"
            assert not cell["outputs"] and cell["execution_count"] is None
    assert "RUN_PIPELINE = False" in code[0]["source"]
    assert "HNSW_EF = 512" in code[0]["source"] and "TOP_K = 200" in code[0]["source"]
    assert package.INPUT_KERNELS == [
        "nhminh107/vibiomir-qdrant-snapshot-recheck-20261025/1",
        "nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025/1"]
    root = tmp_path / "package"
    monkeypatch.setattr(publish, "OUTPUT", root)
    publish.check_package()
    metadata = json.loads((root / "kernel/kernel-metadata.json").read_text())
    assert metadata["is_private"] and not metadata["enable_gpu"]
    assert (root / "queries" / text.name).read_bytes() == text.read_bytes()
    assert (root / "queries" / vectors.name).read_bytes() == vectors.read_bytes()
    manifest = json.loads((root / "queries/source-manifest.json").read_text())
    with zipfile.ZipFile(root / "queries/pipeline_source.zip") as archive:
        assert set(archive.namelist()) == set(package.SOURCES)
        assert not any(Path(name).name == ".env" for name in archive.namelist())
        for name in archive.namelist():
            assert archive.read(name) == (package.ROOT / name).read_bytes()
            assert hashlib.sha256(archive.read(name)).hexdigest() == manifest["sources"][name]
    metadata["is_private"] = False
    (root / "kernel/kernel-metadata.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="private package"):
        publish.check_package()


def test_full_run_requires_explicit_launch_flag_and_uses_separate_ef_checkpoint(tmp_path, monkeypatch):
    text, vectors = tmp_path / "text.parquet", tmp_path / "vectors.parquet"
    text.write_bytes(b"text")
    vectors.write_bytes(b"vectors")
    root = tmp_path / "package"
    notebook = package.prepare(root, text, vectors, write_notebook=False, run_full=True, hnsw_ef=256)
    monkeypatch.setattr(publish, "OUTPUT", root)
    with pytest.raises(ValueError, match="explicit --run-full"):
        publish.check_package()
    manifest, _ = publish.check_package(allow_full=True)
    assert manifest["default_run_pipeline"] is True and manifest["hnsw_ef"] == 256
    source = next(item["source"] for item in notebook["cells"] if item["id"] == "configuration")
    namespace = {}
    exec(source, namespace)
    assert namespace["RUN_PIPELINE"] and namespace["HNSW_EF"] == 256
    assert namespace["OUTPUT_NAME"] == "submission_ef256"
    assert namespace["TEMP_ROOT"].endswith("-ef256")
    assert namespace["LIMIT"] is None and namespace["BRANCH_LIMIT"] == 100 and namespace["TOP_K"] == 200
    assert not namespace["RERANK"] and not namespace["EXACT_SEARCH"]


def test_dense_only_notebook_skips_all_corpus_and_elasticsearch_modules():
    notebook = package.notebook_document({})
    code = {cell["id"]: cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"}
    namespace = {}
    exec(code["configuration"], namespace)
    namespace.update(RUN_PIPELINE=True, SEARCH_MODE="3-branch")
    # None makes accidental runtime calls fail immediately.
    namespace["runtime"] = None
    for name in ("chunk-download", "language-preparation", "elasticsearch-install", "elasticsearch-service", "bm25-index"):
        exec(code[name], namespace)
    assert "qdrant=manager" in code["output-validation"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_dense_only_output_validation_looks_up_original_payloads_without_elasticsearch(tmp_path, corrupt):
    output, archive, checkpoint = tmp_path / "out.json", tmp_path / "out.zip", tmp_path / "out.checkpoint.jsonl"
    prediction = {"id": 1, "relevant_docs": [10,20], "relevant_chunks": [
        {"doc_id":10, "chunk_text":"Original VI"}, {"doc_id":20, "chunk_text":"Original EN"}]}
    output.write_text(json.dumps([prediction]))
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(output, output.name)
    checkpoint.write_text(json.dumps({"version":1,"signature":"fixture"}) + "\n" +
                          json.dumps({"row":0,"prediction":prediction,"chunk_ids":["vi","en"]}) + "\n")
    manager = Mock()
    manager._path = "/collections/test"
    manager._request.return_value = {"points":[
        {"id":"b", "payload":{"chunk_id":"en","doc_id":20,"content":"Original EN"}},
        {"id":"a", "payload":{"chunk_id":"vi","doc_id":10,"content":"changed" if corrupt else "Original VI"}},
    ]}
    if corrupt:
        with pytest.raises(ValueError, match="differs from original source"):
            runtime.validate_results(output, archive, checkpoint, [1], qdrant=manager)
    else:
        result = runtime.validate_results(output, archive, checkpoint, [1], qdrant=manager)
        assert result == {"queries":1,"chunks_verified":2,"zip_verified":True}
    assert manager._request.call_args.args[:2] == ("POST", "/collections/test/points/scroll")
    assert manager._request.call_args.args[2]["filter"]["must"] == [{"key":"chunk_id","match":{"any":["vi","en"]}}]


def snapshot_fixture(tmp_path):
    original = tmp_path / "snapshot"
    recheck = tmp_path / "recheck"
    original.mkdir()
    recheck.mkdir()
    raw = original / "RECOVERY.snapshot"
    raw.write_bytes(b"snapshot fixture")
    snapshot_sha = runtime.checksum(raw)
    expected = {"snapshot_kernel": "owner/source/1", "snapshot_sha256": snapshot_sha,
                "points": 4, "source_sha256": "corpus-sha"}
    manifest = {"complete": False, "signature": {"source_sha256": "corpus-sha"},
                "points": 4, "qdrant_version": runtime.QDRANT_VERSION,
                "snapshot_file": raw.name, "raw_snapshot_bytes": raw.stat().st_size,
                "snapshot_sha256": snapshot_sha, "raw_snapshot_sha256": snapshot_sha}
    certificate = {"validated": True, "source_kernel": "owner/source/1", "points": 4,
                   "qdrant_version": runtime.QDRANT_VERSION, "signature": manifest["signature"],
                   "source_snapshot_file": raw.name, "source_snapshot_sha256": snapshot_sha,
                   "restore_verification": {"verified": True}}
    path = original / "snapshot_manifest.json"
    path.write_text(json.dumps(manifest))
    certificate_path = recheck / "snapshot_validation.json"
    certificate_path.write_text(json.dumps(certificate))
    return path, certificate_path, expected


def test_hash_bound_certificate_authorizes_copy_without_modifying_recovery_manifest(tmp_path):
    original, _, expected = snapshot_fixture(tmp_path)
    before = original.read_bytes()
    manifest_path, snapshot, effective = runtime.verify_snapshot_inputs(tmp_path, expected)
    assert effective["complete"] is True
    assert original.read_bytes() == before and not json.loads(before)["complete"]
    assert manifest_path == original and snapshot.is_file()


def test_notebook_bootstrap_and_query_cells_accept_kaggle_expanded_archive(tmp_path):
    from test_hybrid_retrieval import qwen_files

    vectors, text = qwen_files(tmp_path)
    canonical_text = tmp_path / "query_rewritten_weighted.parquet"
    canonical_vectors = tmp_path / "query_rewritten_weighted_qwen3_1024_fp16.parquet"
    text.rename(canonical_text)
    vectors.rename(canonical_vectors)
    notebook = package.prepare(tmp_path / "package", canonical_text, canonical_vectors, write_notebook=False)
    inputs = tmp_path / "input"
    inputs.mkdir()
    for name in (canonical_text.name, canonical_vectors.name, "source-manifest.json"):
        shutil.copy2(tmp_path / "package/queries" / name, inputs / name)
    with zipfile.ZipFile(tmp_path / "package/queries/pipeline_source.zip") as archive:
        archive.extractall(inputs / "pipeline_source")
    assert not (inputs / "pipeline_source.zip").exists()
    code = {cell["id"]: cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"}
    temporary, output = tmp_path / "temp", tmp_path / "output"
    temporary.mkdir()
    output.mkdir()
    namespace = {"Path": Path, "hashlib": hashlib, "json": json, "sys": sys, "TEMP": temporary, "OUT": output}
    original_path = sys.path[:]
    try:
        exec(code["configuration"], namespace)
        bootstrap = code["source-code"].replace('INPUT = Path("/kaggle/input")', f"INPUT = Path({str(inputs)!r})")
        exec(bootstrap, namespace)
        exec(code["query-input"], namespace)
        exec(code["rrf-self-check"], namespace)
        assert namespace["REPORT"]["query_rows"] == 2
        assert namespace["REPORT"]["rrf_self_check"] == "passed"
    finally:
        sys.path[:] = original_path


@pytest.mark.parametrize("field,value", [("validated", False), ("source_snapshot_sha256", "wrong"),
                                         ("source_kernel", "owner/other/1"), ("points", 3)])
def test_certificate_faults_stop_before_restore(tmp_path, field, value):
    _, path, expected = snapshot_fixture(tmp_path)
    certificate = json.loads(path.read_text())
    certificate[field] = value
    path.write_text(json.dumps(certificate))
    with pytest.raises(ValueError, match="Snapshot/certificate"):
        runtime.verify_snapshot_inputs(tmp_path, expected)


@pytest.mark.parametrize("ef,exact", [(None, False), (256, False), (512, True)])
def test_notebook_adapter_only_changes_requested_search_params_and_server_deadline(ef, exact):
    session = Mock()
    session.request.return_value.json.return_value = {"result": {"points": []}}
    manager = runtime.NotebookQdrant("http://fixture", "test", session=session, timeout=300,
                                     hnsw_ef=ef, exact=exact)
    manager._config = {"vectors": {"qwen3_dense": {"size": 2}}}
    manager.search_dense([1, 0], top_k=100)
    request = session.request.call_args
    assert request.args[1].endswith("/points/query?timeout=290")
    body = request.kwargs["json"]
    assert body["limit"] == 100 and body["query"] == [1., 0.]
    assert "prefetch" not in body
    expected = {}
    if ef is not None:
        expected["hnsw_ef"] = ef
    if exact:
        expected["exact"] = True
    assert body.get("params", {}) == expected


def test_notebook_adapter_respects_explicit_pipeline_ef():
    session = Mock()
    session.request.return_value.json.return_value = {'result': {'points': []}}
    manager = runtime.NotebookQdrant('http://fixture', 'test', session=session, hnsw_ef=256)
    manager._config = {'vectors': {'qwen3_dense': {'size': 2}}}
    manager.search_dense([1, 0], hnsw_ef=512)
    assert session.request.call_args.kwargs['json']['params'] == {'hnsw_ef': 512}


def test_bm25_streams_with_current_preprocessing_and_reuses_verified_receipt(tmp_path, monkeypatch):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.count.return_value = {"count": 4}
    monkeypatch.setattr(runtime, "connect_elasticsearch", lambda: client)
    create, analyze = Mock(), Mock()
    bulk = Mock(return_value=(4, 0))
    monkeypatch.setattr(runtime, "create_index", create)
    monkeypatch.setattr(runtime, "check_analyzers", analyze)
    monkeypatch.setattr(runtime, "bulk_index", bulk)
    receipt = tmp_path / "receipt.json"
    runtime.build_bm25(tmp_path / "source.jsonl", "test", receipt, source_sha256="source", expected_count=4)
    assert bulk.call_args.kwargs == {"index": "test", "limit": None, "batch_size": 1000, "workers": 1}
    assert analyze.call_count == 1
    runtime.build_bm25(tmp_path / "source.jsonl", "test", receipt, source_sha256="source", expected_count=4)
    assert bulk.call_count == 1
    client.count.return_value = {"count": 3}
    with pytest.raises(ValueError, match="count changed"):
        runtime.build_bm25(tmp_path / "source.jsonl", "test", receipt, source_sha256="source", expected_count=4)


def test_elasticsearch_drops_root_for_service_without_changing_kernel_user(tmp_path, monkeypatch):
    home = tmp_path / "elasticsearch"
    (home / "config").mkdir(parents=True)
    monkeypatch.setattr(runtime, "check_port", lambda port: None)
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=65534, pw_gid=65534))
    chown = Mock()
    monkeypatch.setattr(runtime.os, "chown", chown)
    launch = Mock()
    monkeypatch.setattr(runtime.subprocess, "Popen", launch)
    monkeypatch.setattr(runtime, "wait_service", lambda *args: 1.0)
    process, log, _ = runtime.start_elasticsearch(home)
    try:
        assert process is launch.return_value
        kwargs = launch.call_args.kwargs
        assert kwargs["user"] == kwargs["group"] == 65534 and kwargs["extra_groups"] == []
        assert kwargs["env"]["ES_JAVA_OPTS"] == "-Xms2g -Xmx2g"
        assert all(Path(call.args[0]).is_relative_to(home) for call in chown.call_args_list)
    finally:
        log.close()


def test_verified_download_never_accepts_wrong_bytes(tmp_path, monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = iter([b"incorrect bytes"])
    monkeypatch.setattr(runtime.requests, "get", lambda *args, **kwargs: response)
    destination = tmp_path / "binary.tar.gz"
    with pytest.raises(ValueError, match="checksum mismatch"):
        runtime.download_verified("https://example.test/binary", destination, "wrong")
    assert not destination.exists()


@pytest.mark.parametrize("corrupt_labels", [False, True])
def test_language_preparation_reuses_local_rule_preserves_fields_and_checks_all_hashes(tmp_path, corrupt_labels):
    import orjson
    rows = [{"doc_id": 1, "chunk_id": "vi", "content": "Bệnh thận", "extra": [True, None]},
            {"doc_id": 2, "chunk_id": "en", "content": "Insulin deficiency"},
            {"doc_id": 3, "chunk_id": "zh", "content": "医学检查"}]
    source, destination = tmp_path / "raw.jsonl", tmp_path / "labeled.jsonl"
    original = b"".join(orjson.dumps(row) + b"\n" for row in rows)
    source.write_bytes(original)
    enriched, labels = [], []
    for row, language in zip(rows, ("vi", "en", "zh")):
        enriched.append(orjson.dumps({**row, "language": language}) + b"\n")
        labels.append(orjson.dumps({"doc_id": row["doc_id"], "chunk_id": row["chunk_id"], "language": language}) + b"\n")
    options = {"source_sha256": hashlib.sha256(original).hexdigest(),
               "labeled_sha256": hashlib.sha256(b"".join(enriched)).hexdigest(),
               "labels_sha256": "wrong" if corrupt_labels else hashlib.sha256(b"".join(labels)).hexdigest(),
               "expected_counts": {"vi": 1, "en": 1, "zh": 1}}
    if corrupt_labels:
        with pytest.raises(ValueError, match="Language enrichment differs"):
            runtime.prepare_languages(source, destination, **options)
        assert not destination.exists()
    else:
        report = runtime.prepare_languages(source, destination, **options)
        assert report["rows"] == 3 and report["counts"] == options["expected_counts"]
        assert destination.read_bytes() == b"".join(enriched)
        assert runtime.prepare_languages(source, destination, **options)["rows"] == 3
    assert source.read_bytes() == original
