"""Offline checks without downloading weights, reading the corpus, or using CUDA."""

import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import faiss
import numpy as np
import pytest
import torch
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3Model


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "BackEnd/app/Database/Notebook/FAISS_Qwen3_Embedding_0.6B_1024_HNSW_Flat_2GPU.ipynb"
)


@pytest.fixture
def notebook():
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def config(notebook):
    tree = ast.parse("".join(notebook["cells"][3]["source"]))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "config"
    )
    return eval(
        compile(ast.Expression(assignment.value), str(NOTEBOOK_PATH), "eval"),
        {"DATA_PATH": Path("/unused/merged.jsonl"), "os": os},
    )


@pytest.fixture
def runner(notebook):
    tree = ast.parse("".join(notebook["cells"][5]["source"]))
    source = ast.literal_eval(tree.body[0].value)
    namespace = {"__name__": "notebook_test", "torch": torch}
    exec(compile(source, str(NOTEBOOK_PATH), "exec"), namespace)
    namespace["source_tree"] = ast.parse(source)
    return namespace


@pytest.fixture
def encoder(runner):
    backend = Tokenizer(models.WordLevel(
        {"[UNK]": 0, "[PAD]": 1, "[EOS]": 2, "one": 3, "two": 4, "three": 5},
        unk_token="[UNK]",
    ))
    backend.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token="[UNK]", pad_token="[PAD]",
        eos_token="[EOS]", padding_side="left", model_input_names=["input_ids", "attention_mask"],
    )
    model = Qwen3Model(Qwen3Config(
        vocab_size=6, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=16,
        max_position_embeddings=64, pad_token_id=1, use_cache=False,
        attn_implementation="sdpa",
    )).eval()
    loader = next(node for node in runner["source_tree"].body
                  if isinstance(node, ast.FunctionDef) and node.name == "load_encoder")
    forward = next(node for node in loader.body
                   if isinstance(node, ast.FunctionDef) and node.name == "forward")
    namespace = {**runner, "tokenizer": tokenizer, "model": model,
                 "device": torch.device("cpu"), "config": {"rank": 0, "batch_size": 64}}
    exec(compile(ast.Module(body=[forward], type_ignores=[]), str(NOTEBOOK_PATH), "exec"), namespace)
    return tokenizer, model, namespace


def test_cells_and_embedded_runner_compile(notebook, runner, config):
    assert notebook["nbformat"] == 4
    assert config["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert config["dimension"] == 1024
    assert len(config["revision"]) == 40
    for number, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"cell{number}", "exec")
            assert cell["outputs"] == []
            assert cell["execution_count"] is None


def test_embedding_and_index_parameters_match_original(notebook, runner, config):
    original = json.loads(NOTEBOOK_PATH.with_name("FAISS_GTE_HNSW_Flat_2GPU.ipynb").read_text())
    original_source = ast.literal_eval(ast.parse("".join(original["cells"][5]["source"])).body[0].value)
    original_functions = {
        node.name: ast.dump(node) for node in ast.parse(original_source).body
        if isinstance(node, ast.FunctionDef)
    }
    changed_functions = {
        "encode_records", "load_encoder", "run_worker", "embedding_signature", "build_index",
        "embed_two_gpus", "preflight", "check_disk_space", "measure_storage", "check_publish_space",
    }
    for node in runner["source_tree"].body:
        if isinstance(node, ast.FunctionDef) and node.name not in changed_functions:
            assert ast.dump(node) == original_functions[node.name], node.name
    for index in (1, 7, 9, 11):
        assert notebook["cells"][index]["source"] == original["cells"][index]["source"]
    assert config["expected_documents"] == 1_220_598
    assert config["expected_chunks"] == 4_342_218
    assert config["max_length"] == 8192
    assert (config["hnsw_m"], config["ef_construction"], config["ef_search"]) == (32, 80, 64)


def test_last_token_pooling_matches_individual_qwen_forwards(encoder):
    tokenizer, model, namespace = encoder
    windows = [{"input_ids": ids} for ids in ([3, 4, 5], [4], [5, 3])]
    vectors = namespace["forward"](windows)
    expected = []
    for window in windows:
        with torch.inference_mode():
            output = model(input_ids=torch.tensor([window["input_ids"]]), use_cache=False)
        assert output.past_key_values is None
        expected.append(output.last_hidden_state[0, -1].numpy())
    np.testing.assert_allclose(
        vectors, namespace["normalize_vectors"](np.array(expected)), atol=1e-5,
    )
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)


def test_empty_and_long_chunks_preserve_order_and_weighting(encoder):
    tokenizer, _, namespace = encoder
    records = [{"text": text} for text in ("", "one two three one two", "  ", "two")]
    config = {"max_length": 3, "dimension": 32, "batch_size": 8, "token_budget": 24}
    vectors, long_count = namespace["encode_records"](
        records, tokenizer, namespace["forward"], config,
    )
    windows = [{"input_ids": ids} for ids in ([2], [3, 4, 5], [3, 4], [4])]
    parts = namespace["forward"](windows)
    expected = namespace["normalize_vectors"](np.array([
        parts[0], 3 * parts[1] + 2 * parts[2], parts[0], parts[3],
    ]))
    assert long_count == 1
    assert vectors.dtype == np.float32
    assert vectors.shape == (4, 32)
    np.testing.assert_allclose(vectors, expected, atol=1e-5)


def test_oom_retry_keeps_all_windows_in_order(encoder, monkeypatch):
    _, model, namespace = encoder
    windows = [{"input_ids": [3, 4]}, {"input_ids": [5]}, {"input_ids": [4, 3, 5]}]
    expected = namespace["forward"](windows)
    calls = []

    def limited_model(**features):
        calls.append(features["input_ids"].shape[0])
        if calls[-1] > 1:
            raise torch.cuda.OutOfMemoryError("synthetic OOM")
        return model(**features)

    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    namespace["model"] = limited_model
    np.testing.assert_allclose(namespace["forward"](windows), expected, atol=1e-5)
    assert calls == [3, 1, 2, 1, 1]


@pytest.fixture
def storage_config(config, tmp_path):
    config.update(
        expected_documents=2, expected_chunks=4, scratch=str(tmp_path / "checkpoints"),
        output=str(tmp_path / "output"), build_temp=str(tmp_path / "build"),
        checkpoint_archive=str(tmp_path / "archive"), faiss_threads=1,
    )
    documents = [
        {"doc_id": rank, "children": [
            {"chunk_id": f"{rank}:{i}", "parent_id": f"{rank}:p", "chunk_order": i,
             "start_char": 0, "end_char": len(text), "chunk_text": text,
             "retrieval_eligible": bool(i)}
            for i, text in enumerate(("Kiểm tra", ""))
        ]}
        for rank in range(2)
    ]
    source = tmp_path / "source.jsonl"
    source.write_text("".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in documents))
    config.update(source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    for key in ("scratch", "output", "build_temp"):
        Path(config[key]).mkdir()
    return config


def test_storage_measurement_uses_real_metadata_and_cleans_probe(runner, storage_config):
    config = storage_config
    plan = runner["measure_storage"](config)
    expected_jsonl = 0
    for rank in range(2):
        for record in runner["iter_chunks"](Path(config["source"]), rank):
            record.pop("text")
            expected_jsonl += len((json.dumps(record, ensure_ascii=False) + "\n").encode())
    assert plan["jsonl_bytes"] == expected_jsonl
    assert plan["checkpoint_bytes"] == 4 * 1024 * 4 + expected_jsonl
    assert plan["sqlite_bytes"] >= 4096
    assert plan["output_bytes"] == runner["index_bytes"](config) + plan["sqlite_bytes"]
    assert list(Path(config["build_temp"]).iterdir()) == []
    assert list(Path(config["scratch"]).iterdir()) == []


@pytest.mark.parametrize("sqlite_gib,free_gib,passes", [(0.75, 19.5, True), (2, 19.5, False)])
def test_kaggle_19_5_gib_limit_uses_measured_sizes(
    runner, storage_config, monkeypatch, sqlite_gib, free_gib, passes,
):
    config = storage_config
    config.update(expected_chunks=4_342_218, expected_documents=1_220_598)
    gib = 1024**3
    plan = {
        "signature": runner["embedding_signature"](config), "hnsw_m": config["hnsw_m"],
        "checkpoint_bytes": config["expected_chunks"] * 1024 * 4 + int(1.1 * gib),
        "output_bytes": runner["index_bytes"](config) + int(sqlite_gib * gib),
    }
    (Path(config["output"]) / "storage_plan.json").write_text(json.dumps(plan))
    original_stat = Path.stat
    working_paths = {Path(config["scratch"]), Path(config["output"])}

    def device_stat(path, *args, **kwargs):
        result = list(original_stat(path, *args, **kwargs))
        result[2] = 100 if path in working_paths else 200
        return os.stat_result(result)

    monkeypatch.setattr(Path, "stat", device_stat)
    monkeypatch.setattr(runner["shutil"], "disk_usage", lambda path: SimpleNamespace(
        free=int((free_gib if path in working_paths else 1000) * gib),
    ))
    assert runner["index_bytes"](config) + config["expected_chunks"] * 512 + gib > int(19.5 * gib)
    if passes:
        runner["check_disk_space"](config)
    else:
        with pytest.raises(RuntimeError, match="Not enough disk space"):
            runner["check_disk_space"](config)


def test_publish_guard_keeps_checkpoints_if_actual_files_do_not_fit(runner, storage_config, monkeypatch):
    config = storage_config
    checkpoint = Path(config["scratch"]) / "gpu0.f32"
    checkpoint.write_bytes(b"committed checkpoint")
    partial = Path(config["build_temp"]) / "index.faiss.partial"
    partial.write_bytes(b"index")
    monkeypatch.setattr(runner["shutil"], "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(RuntimeError, match="checkpoints have not been moved"):
        runner["check_publish_space"](config, (partial,))
    assert checkpoint.read_bytes() == b"committed checkpoint"
    assert not Path(config["checkpoint_archive"]).exists()


def test_storage_plan_requires_matching_configuration(runner, storage_config):
    config = storage_config
    with pytest.raises(RuntimeError, match="Run preflight"):
        runner["check_disk_space"](config)
    plan = runner["measure_storage"](config)
    (Path(config["output"]) / "storage_plan.json").write_text(json.dumps(plan))
    config["dimension"] = 768
    with pytest.raises(ValueError, match="different source/model/index settings"):
        runner["check_disk_space"](config)


def test_publish_guard_counts_space_freed_only_on_cross_device_archive(
    runner, storage_config, monkeypatch,
):
    config = storage_config
    checkpoint = Path(config["scratch"]) / "gpu0.f32"
    checkpoint.write_bytes(b"committed checkpoint")
    partial = Path(config["build_temp"]) / "index.faiss.partial"
    partial.write_bytes(b"indexdata")
    available = runner["DISK_HEADROOM"] + partial.stat().st_size - checkpoint.stat().st_size
    original_stat = Path.stat
    working_paths = {Path(config["scratch"]), Path(config["output"])}

    def device_stat(path, *args, **kwargs):
        result = list(original_stat(path, *args, **kwargs))
        result[2] = 100 if path in working_paths else 200
        return os.stat_result(result)

    monkeypatch.setattr(Path, "stat", device_stat)
    monkeypatch.setattr(runner["shutil"], "disk_usage", lambda path: SimpleNamespace(free=available))
    runner["check_publish_space"](config, (partial,))
    config["checkpoint_archive"] = str(Path(config["output"]) / "archive")
    with pytest.raises(RuntimeError, match="checkpoints have not been moved"):
        runner["check_publish_space"](config, (partial,))
    assert checkpoint.exists()


@pytest.mark.parametrize("add_batch_size", [1, 3])
def test_full_width_faiss_sqlite_and_manifest_round_trip(runner, storage_config, add_batch_size):
    config = storage_config
    config["add_batch_size"] = add_batch_size
    scratch = Path(config["scratch"])
    plan = runner["measure_storage"](config)
    (Path(config["output"]) / "storage_plan.json").write_text(json.dumps(plan))
    (scratch / "config.json").write_text(json.dumps(runner["embedding_signature"](config)))
    vectors = runner["normalize_vectors"](
        np.random.default_rng(42).normal(size=(4, 1024)).astype(np.float32),
    )
    for rank in range(2):
        vectors[rank * 2:rank * 2 + 2].tofile(scratch / f"gpu{rank}.f32")
        (scratch / f"gpu{rank}.done.json").write_text(json.dumps({"chunks": 2}))
        records = list(runner["iter_chunks"](Path(config["source"]), rank))
        for record in records:
            record.pop("text")
        (scratch / f"gpu{rank}.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records),
        )
    previous_threads = faiss.omp_get_max_threads()
    try:
        runner["build_index"](config)
    finally:
        faiss.omp_set_num_threads(previous_threads)
    output = Path(config["output"])
    assert (output / "chunk_mapping.sqlite").stat().st_size == plan["sqlite_bytes"]
    index = faiss.read_index(str(output / "qwen3_embedding_0_6b_1024_hnsw_flat.faiss"))
    assert index.d == 1024 and index.ntotal == 4
    scores, ids = index.search(vectors, 1)
    np.testing.assert_array_equal(ids[:, 0], np.arange(4))
    np.testing.assert_allclose(scores[:, 0], 1, atol=1e-5)
    with sqlite3.connect(output / "chunk_mapping.sqlite") as database:
        assert database.execute("SELECT chunk_id FROM chunks ORDER BY vector_id").fetchall() == [
            ("0:0",), ("0:1",), ("1:0",), ("1:1",),
        ]
    manifest = json.loads((output / "build_manifest.json").read_text())
    assert manifest["pooling"] == "last_token"
    assert manifest["dimension"] == 1024
    assert manifest["normalized"] is True
    assert not scratch.exists()
    assert (Path(config["checkpoint_archive"]) / "config.json").exists()
