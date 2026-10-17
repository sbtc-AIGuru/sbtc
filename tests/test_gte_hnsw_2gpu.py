"""Offline checks for full-corpus sharding, pooling, FAISS and ID mapping."""

from copy import deepcopy
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import faiss
import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Scripts.FAISS import build_gte_hnsw as runner

NOTEBOOK = ROOT / "BackEnd/app/Database/Notebook/FAISS_GTE_HNSW_Flat_2GPU.ipynb"


def test_standalone_notebook_syntax_and_embedded_runner() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["kaggle"]["isGpuEnabled"]
    namespace = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            source = "".join(cell["source"])
            compile(source, str(NOTEBOOK), "exec")
            assert cell["outputs"] == [] and cell["execution_count"] is None
            if source.startswith("runner_source ="):
                exec(source.split("runner_path.write_text")[0], namespace)
    assert namespace["runner_source"] == Path(runner.__file__).read_text()


def write_source(tmp_path: Path) -> tuple[Path, list[dict]]:
    documents = []
    for doc_id in range(4):
        documents.append({
            "doc_id": doc_id, "status": "ok" if doc_id != 1 else "skipped",
            "children": [{
                "chunk_id": f"{doc_id}:c0", "doc_id": doc_id,
                "parent_id": f"{doc_id}:p0", "chunk_order": 0,
                "start_char": 0, "end_char": 12,
                "chunk_text": "" if doc_id == 2 else "Tiếng Việt / 中文 / English",
                "retrieval_eligible": doc_id % 2 == 0,
            }],
        })
    path = tmp_path / "merged.jsonl"
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in documents) + "\n")
    return path, documents


def test_two_shards_cover_every_chunk_including_empty_and_ineligible(tmp_path: Path) -> None:
    source, documents = write_source(tmp_path)
    shards = [list(runner.iter_chunks(source, rank)) for rank in range(2)]
    assert [record["doc_id"] for record in shards[0]] == [0, 2]
    assert [record["doc_id"] for record in shards[1]] == [1, 3]
    ids = [record["chunk_id"] for shard in shards for record in shard]
    assert len(ids) == len(set(ids)) == 4
    assert set(ids) == {doc["children"][0]["chunk_id"] for doc in documents}
    assert shards[0][1]["text"] == "" and shards[0][1]["empty_text"]
    assert shards[1][0]["retrieval_eligible"] is False


def test_source_checksum_and_counts(tmp_path: Path) -> None:
    source, _ = write_source(tmp_path)
    config = {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "expected_documents": 4, "expected_chunks": 4}
    assert runner.prepare_source(config)["chunks"] == 4
    for key, value in [("source_sha256", "wrong"), ("expected_chunks", 5), ("expected_documents", 3)]:
        with pytest.raises(ValueError):
            runner.prepare_source({**config, key: value})


@pytest.mark.parametrize("available,count", [(False, 0), (True, 1)])
def test_two_cuda_gpus_are_required(monkeypatch, available: bool, count: int) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: count)
    with pytest.raises(RuntimeError, match="two CUDA GPUs"):
        runner.embed_two_gpus({}, Path("unused.json"))


def test_token_budget_limits_padding_without_losing_windows() -> None:
    lengths = [2, 4, 9, 1, 4]
    order = sorted(range(len(lengths)), key=lengths.__getitem__, reverse=True)
    batches = list(runner.padded_batches(order, lengths, batch_size=3, token_budget=12))
    assert [position for batch in batches for position in batch] == order
    assert all(len(batch) <= 3 for batch in batches)
    assert all(len(batch) * max(lengths[i] for i in batch) <= 12 for batch in batches)


class FakeTokenizer:
    def __call__(self, texts, **kwargs):
        assert kwargs["truncation"] is False
        return {"input_ids": [[int(value) for value in text.split()] for text in texts]}

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def build_inputs_with_special_tokens(self, ids):
        return [100, *ids, 101]


def test_long_chunk_windows_are_weighted_and_restored_to_chunk_order() -> None:
    records = [{"text": "1 2 3 4 5 6"}, {"text": ""}, {"text": "9 10"}]
    snapshot = deepcopy(records)
    seen = []

    def forward(windows):
        seen.extend(window["input_ids"][1:-1] for window in windows)
        return runner.normalize_vectors(np.array([
            [sum(window["input_ids"][1:-1]), 1, 2] for window in windows
        ]))

    vectors, long_count = runner.encode_records(
        records, FakeTokenizer(), forward,
        {"max_length": 6, "batch_size": 2, "token_budget": 12, "dimension": 3},
    )
    pieces = runner.normalize_vectors(np.array([[10, 1, 2], [11, 1, 2], [0, 1, 2], [19, 1, 2]]))
    expected = runner.normalize_vectors(np.array([4 * pieces[0] + 2 * pieces[1], pieces[2], pieces[3]]))
    assert np.allclose(vectors, expected)
    assert long_count == 1
    assert records == snapshot
    assert sorted(token for window in seen for token in window) == [1, 2, 3, 4, 5, 6, 9, 10]
    assert [] in seen
    assert vectors.dtype == np.float32


@pytest.mark.parametrize("vectors", [[[0, 0]], [[float("nan"), 1]], [[float("inf"), 1]]])
def test_bad_embeddings_are_rejected(vectors) -> None:
    with pytest.raises(ValueError, match="zero embedding"):
        runner.normalize_vectors(np.array(vectors))


@pytest.fixture
def synthetic_shards(tmp_path: Path, monkeypatch):
    scratch, output = tmp_path / "scratch", tmp_path / "output"
    scratch.mkdir()
    config = {
        "source": "unused", "source_sha256": "example", "expected_documents": 4,
        "model": "test-model", "revision": "test-revision", "code_revision": "test-code",
        "max_length": 8192,
        "expected_chunks": 4, "dimension": 8, "hnsw_m": 4, "ef_construction": 20,
        "ef_search": 16, "faiss_threads": 1, "add_batch_size": 1,
        "scratch": str(scratch), "output": str(output),
    }
    (scratch / "config.json").write_text(json.dumps(runner.embedding_signature(config)))
    vectors = runner.normalize_vectors(np.random.default_rng(42).normal(size=(4, 8)))
    records = [{"chunk_id": f"chunk-{i}", "doc_id": i, "parent_id": f"parent-{i}",
                "chunk_order": 0, "start_char": 0, "end_char": 10, "source_line": i + 1,
                "empty_text": i == 2, "retrieval_eligible": i % 2 == 0} for i in range(4)]
    for rank in range(2):
        vectors[rank * 2:rank * 2 + 2].tofile(scratch / f"gpu{rank}.f32")
        (scratch / f"gpu{rank}.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records[rank * 2:rank * 2 + 2]) + "\n",
        )
        (scratch / f"gpu{rank}.done.json").write_text(json.dumps({"chunks": 2}))
    monkeypatch.setattr(runner, "memory_snapshot", lambda: {"available": 8 * 1024**3})
    previous_threads = faiss.omp_get_max_threads()
    yield config, vectors, records
    faiss.omp_set_num_threads(previous_threads)


def test_real_hnsw_flat_file_and_sqlite_ids(synthetic_shards) -> None:
    config, vectors, records = synthetic_shards
    runner.build_index(config)
    output = Path(config["output"])
    index = faiss.read_index(str(output / "gte_multilingual_hnsw_flat.faiss"))
    assert isinstance(index, faiss.IndexHNSWFlat)
    assert index.metric_type == faiss.METRIC_INNER_PRODUCT
    assert index.d == 8 and index.ntotal == 4
    for position in range(4):
        assert np.allclose(index.reconstruct(position), vectors[position])
    scores, ids = index.search(vectors[2:3], 1)
    assert ids.tolist() == [[2]]
    assert scores[0, 0] == pytest.approx(1, abs=1e-6)
    with sqlite3.connect(output / "chunk_mapping.sqlite") as database:
        assert database.execute("SELECT chunk_id FROM chunks ORDER BY vector_id").fetchall() == [
            (record["chunk_id"],) for record in records
        ]
        assert database.execute("SELECT chunk_id FROM chunks WHERE vector_id=?", (int(ids[0, 0]),)).fetchone() == ("chunk-2",)
    assert json.loads((output / "build_manifest.json").read_text())["chunks"] == 4
    assert not list(output.glob("*.partial"))
    with pytest.raises(FileExistsError):
        runner.build_index(config)


@pytest.mark.parametrize("corruption", ["duplicate_id", "nan", "short_vectors", "extra_metadata", "low_ram"])
def test_corrupt_shards_never_publish_index(synthetic_shards, monkeypatch, corruption) -> None:
    config, vectors, records = synthetic_shards
    scratch, output = Path(config["scratch"]), Path(config["output"])
    if corruption == "duplicate_id":
        rows = (scratch / "gpu1.jsonl").read_text().splitlines()
        row = json.loads(rows[0])
        row["chunk_id"] = records[0]["chunk_id"]
        rows[0] = json.dumps(row)
        (scratch / "gpu1.jsonl").write_text("\n".join(rows) + "\n")
    elif corruption == "nan":
        np.full((2, 8), np.nan, dtype=np.float32).tofile(scratch / "gpu1.f32")
    elif corruption == "short_vectors":
        vectors[:1].tofile(scratch / "gpu1.f32")
    elif corruption == "extra_metadata":
        with (scratch / "gpu1.jsonl").open("a") as stream:
            stream.write("{}\n")
    else:
        monkeypatch.setattr(runner, "memory_snapshot", lambda: {"available": 1})
    with pytest.raises((ValueError, RuntimeError, sqlite3.IntegrityError)):
        runner.build_index(config)
    assert not (output / "gte_multilingual_hnsw_flat.faiss").exists()
    assert not (output / "build_manifest.json").exists()


def test_can_reuse_embeddings_with_new_hnsw_settings(synthetic_shards) -> None:
    config, _, _ = synthetic_shards
    modified = {**config, "hnsw_m": 6, "output": config["output"] + "-new"}
    runner.build_index(modified)
    index = faiss.read_index(str(Path(modified["output"]) / "gte_multilingual_hnsw_flat.faiss"))
    assert index.ntotal == 4
    assert index.hnsw.nb_neighbors(0) == 12


def test_cannot_reuse_embeddings_with_different_model(synthetic_shards) -> None:
    config, _, _ = synthetic_shards
    with pytest.raises(ValueError, match="configuration"):
        runner.build_index({**config, "revision": "different-weights"})


@pytest.mark.parametrize("shmem,dirty,expected", [(0, 0, 22), (20, 0, 4), (0, 8, 16)])
def test_cgroup_cache_is_reclaimable_but_not_tmpfs_or_dirty_pages(tmp_path, monkeypatch, shmem, dirty, expected):
    gib = 1024**3
    (tmp_path / "memory.max").write_text(str(30 * gib))
    (tmp_path / "memory.current").write_text(str(28 * gib))
    (tmp_path / "memory.stat").write_text(
        f"inactive_file {20 * gib}\nfile {22 * gib}\nshmem {shmem * gib}\nfile_dirty {dirty * gib}\n",
    )
    monkeypatch.setattr(runner, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(runner.psutil, "virtual_memory", lambda: SimpleNamespace(total=64 * gib, available=26 * gib))
    assert runner.memory_snapshot()["available"] == expected * gib


def test_unlimited_cgroup_and_host_limit(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text("max")
    (tmp_path / "memory.current").write_text("1000")
    monkeypatch.setattr(runner, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(runner.psutil, "virtual_memory", lambda: SimpleNamespace(total=8000, available=4000))
    assert runner.available_memory() == 4000


def test_clean_active_file_cache_is_reclaimable_after_repeated_reads(tmp_path, monkeypatch):
    gib = 1024**3
    (tmp_path / "memory.max").write_text(str(30 * gib))
    (tmp_path / "memory.current").write_text(str(28 * gib))
    (tmp_path / "memory.stat").write_text(
        f"inactive_file {2 * gib}\nactive_file {18 * gib}\nfile {22 * gib}\nshmem {gib}\n",
    )
    monkeypatch.setattr(runner, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(runner.psutil, "virtual_memory", lambda: SimpleNamespace(total=64 * gib, available=26 * gib))
    assert runner.memory_snapshot()["available"] == 22 * gib


def preflight_config(config: dict, tmp_path: Path) -> dict:
    return {**config, "build_temp": str(tmp_path / "build-temp"),
            "checkpoint_archive": str(tmp_path / "archive")}


def test_preflight_allocates_index_before_embedding(synthetic_shards, tmp_path, monkeypatch):
    config, _, _ = synthetic_shards
    config = preflight_config(config, tmp_path)
    monkeypatch.setattr(runner, "filesystem_type", lambda path: "ext4")
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=100 * 1024**3))
    runner.preflight(config)
    assert (Path(config["output"]) / "preflight.json").exists()
    assert not (Path(config["output"]) / "gte_multilingual_hnsw_flat.faiss").exists()


@pytest.mark.parametrize("separate_devices,working_free,temp_free,existing_gib,passes", [
    (True, 19.5, 1069.7, 0, True),  # Actual Kaggle v3 storage layout.
    (False, 19.5, 19.5, 0, False),
    (True, 12, 1069.7, 0, False),
    (True, 19.5, 20, 0, False),  # Archive copy must coexist with the partial index.
    (True, 6, 1069.7, 12.42, True),  # Build starts with checkpoints already on disk.
])
def test_kaggle_storage_budget_uses_peak_per_filesystem(
    synthetic_shards, tmp_path, monkeypatch,
    separate_devices, working_free, temp_free, existing_gib, passes,
):
    config, _, _ = synthetic_shards
    config = preflight_config({**config, "expected_chunks": 4_342_218,
                              "dimension": 768, "hnsw_m": 32}, tmp_path)
    scratch, output = Path(config["scratch"]), Path(config["output"])
    temporary = Path(config["build_temp"])
    output.mkdir()
    temporary.mkdir()
    original_stat = Path.stat

    def storage_stat(path, *args, **kwargs):
        values = list(original_stat(path, *args, **kwargs))
        values[2] = 1 if path in (scratch, output) or not separate_devices else 2
        if path == scratch / "gpu0.f32" and existing_gib:
            values[6] = int(existing_gib * 1024**3)
        return os.stat_result(values)

    monkeypatch.setattr(Path, "stat", storage_stat)
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(
        free=int((working_free if path.stat().st_dev == 1 else temp_free) * 1024**3),
    ))
    monkeypatch.setattr(runner, "filesystem_type", lambda path: "ext4")
    monkeypatch.setattr(runner, "memory_snapshot", lambda: {"available": 29 * 1024**3})
    allocated = []
    monkeypatch.setattr(runner, "create_index", lambda *args: allocated.append(True))
    if passes:
        runner.preflight(config)
        assert allocated == [True]
    else:
        with pytest.raises(RuntimeError, match="disk space"):
            runner.preflight(config)
        assert allocated == []


@pytest.mark.parametrize("failure", ["low_ram", "ram_disk"])
def test_preflight_rejects_bad_resources_before_allocating(synthetic_shards, tmp_path, monkeypatch, failure):
    config, _, _ = synthetic_shards
    config = preflight_config(config, tmp_path)
    monkeypatch.setattr(runner, "filesystem_type", lambda path: "tmpfs" if failure == "ram_disk" else "ext4")
    if failure == "low_ram":
        monkeypatch.setattr(runner, "memory_snapshot", lambda: {"available": 1})
    monkeypatch.setattr(runner, "create_index", lambda *args: pytest.fail("Index allocation must not run"))
    with pytest.raises(RuntimeError):
        runner.preflight(config)


def test_checkpoint_moves_out_of_output_only_after_success(synthetic_shards, tmp_path):
    config, _, _ = synthetic_shards
    config = preflight_config(config, tmp_path)
    runner.build_index(config)
    assert not Path(config["scratch"]).exists()
    assert (Path(config["checkpoint_archive"]) / "gpu0.f32").exists()
    assert (Path(config["output"]) / "gte_multilingual_hnsw_flat.faiss").exists()


def test_failed_build_keeps_all_recovery_files(synthetic_shards, tmp_path, monkeypatch):
    config, _, _ = synthetic_shards
    config = preflight_config(config, tmp_path)
    before = {p.name: p.read_bytes() for p in Path(config["scratch"]).iterdir()}
    monkeypatch.setattr(runner.faiss, "write_index", lambda *args: (_ for _ in ()).throw(OSError("Disk write failed")))
    with pytest.raises(OSError, match="Disk write failed"):
        runner.build_index(config)
    assert {p.name: p.read_bytes() for p in Path(config["scratch"]).iterdir()} == before
    assert not Path(config["checkpoint_archive"]).exists()
    assert not (Path(config["output"]) / "gte_multilingual_hnsw_flat.faiss").exists()


def test_interrupted_worker_resumes_without_duplicate_or_lost_vectors(tmp_path, monkeypatch):
    source, _ = write_source(tmp_path)
    scratch = tmp_path / "checkpoints"
    scratch.mkdir()
    config = {"scratch": str(scratch), "source": str(source), "dimension": 3, "buffer_size": 1}
    monkeypatch.setattr(runner, "load_encoder", lambda config: (None, None))

    def encode(records, *args):
        vectors = [[len(record["text"]), sum(map(ord, record["text"])) % 7, 1] for record in records]
        return runner.normalize_vectors(np.array(vectors)), 0

    def interrupted(records, *args):
        if records[0].get("chunk_id") == "2:c0":
            raise RuntimeError("Interrupted")
        return encode(records)

    monkeypatch.setattr(runner, "encode_records", interrupted)
    with pytest.raises(RuntimeError, match="Interrupted"):
        runner.run_worker(config, 0)
    assert json.loads((scratch / "gpu0.progress.json").read_text())["chunks"] == 1
    for name in ("gpu0.f32", "gpu0.jsonl"):
        with (scratch / name).open("ab") as stream:
            stream.write(b"uncommitted data")
    monkeypatch.setattr(runner, "encode_records", encode)
    runner.run_worker(config, 0)
    assert json.loads((scratch / "gpu0.done.json").read_text())["chunks"] == 2
    assert [json.loads(line)["chunk_id"] for line in (scratch / "gpu0.jsonl").read_text().splitlines()] == ["0:c0", "2:c0"]
    vectors = np.fromfile(scratch / "gpu0.f32", dtype=np.float32).reshape(2, 3)
    expected, _ = encode(list(runner.iter_chunks(source, 0)))
    assert np.array_equal(vectors, expected)
    assert not list(scratch.glob("*.tmp"))


def test_resume_from_attached_output_preserves_input(synthetic_shards, tmp_path, monkeypatch):
    config, _, _ = synthetic_shards
    previous = Path(config["scratch"])
    original = {p.name: p.read_bytes() for p in previous.iterdir()}
    config = preflight_config({**config, "scratch": str(tmp_path / "working-copy"),
                               "resume_from": str(previous)}, tmp_path)
    monkeypatch.setattr(runner, "filesystem_type", lambda path: "ext4")
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=100 * 1024**3))
    monkeypatch.setattr(runner, "load_encoder", lambda config: pytest.fail("Completed shards must not load the model"))
    runner.preflight(config)
    runner.run_worker(config, 0)
    runner.run_worker(config, 1)
    assert {p.name: p.read_bytes() for p in previous.iterdir()} == original
    assert (Path(config["scratch"]) / "gpu0.f32").read_bytes() == original["gpu0.f32"]


def test_notebook_records_failure_without_aborting_checkpoint_export(tmp_path):
    notebook = json.loads(NOTEBOOK.read_text())
    namespace = {"subprocess": SimpleNamespace(run=lambda *args: SimpleNamespace(returncode=-9)),
                 "Path": Path, "json": json, "sys": sys, "runner_path": Path("runner.py"),
                 "config_path": Path("config.json"), "config": {"output": str(tmp_path)}}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            nodes = [node for node in ast.parse("".join(cell["source"])).body
                     if isinstance(node, ast.FunctionDef) and node.name == "run_stage"]
            if nodes:
                exec(compile(ast.Module(body=nodes, type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
    assert namespace["run_stage"]("build") is False
    status = json.loads((tmp_path / "pipeline_status.json").read_text())
    assert status == {"stage": "build", "return_code": -9, "success": False}
