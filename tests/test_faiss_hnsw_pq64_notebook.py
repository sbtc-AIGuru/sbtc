"""Offline regression checks for the standalone HNSW-PQ64 notebook."""
from __future__ import annotations

import ast
import gc
import json
from pathlib import Path
from time import perf_counter
from types import MethodType
from typing import Iterator, TextIO

import faiss
import nbformat
import numpy as np
import pytest
import torch


NOTEBOOK_PATH = Path(__file__).resolve().parents[1] / "BackEnd/app/Database/FAISS_HSNW_PQ64_index.ipynb"
ORIGINAL_PATH = NOTEBOOK_PATH.with_name("FAISS_HSNW_index.ipynb")


def notebook_functions(path: Path) -> dict:
    """Extract executable function definitions without running setup or downloading models."""
    result = {}
    notebook = json.loads(path.read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            for node in ast.parse("".join(cell["source"])).body:
                if isinstance(node, ast.FunctionDef):
                    result[node.name] = node
    return result


@pytest.fixture
def namespace(tmp_path):
    previous_threads = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(1)
    result = {
        "gc": gc, "json": json, "np": np, "faiss": faiss, "torch": torch,
        "MethodType": MethodType, "Iterator": Iterator, "TextIO": TextIO,
        "perf_counter": perf_counter, "notebook_started": perf_counter(),
        "setup_seconds": 0.0, "model_seconds": 0.0, "pq_subquantizers": 64,
        "pq_bits": 8, "pq_train_iterations": 3, "training_seed": 42,
        "hnsw_m": 8, "hnsw_ef_construction": 40, "hnsw_ef_search": 32,
        "train_sample_size": 512, "start_point": 7, "end_point": 9,
        "add_batch_size": 128, "effective_batch_size": 16, "verify_saved_index": False,
        "build_complete": False,
    }
    functions = list(notebook_functions(NOTEBOOK_PATH).values())
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(NOTEBOOK_PATH), "exec"), result)
    result["index"] = result["create_hnsw_pq_index"](768)
    # Tiny synthetic training sets are sufficient for functional checks, not recall claims.
    faiss.downcast_index(result["index"].storage).pq.cp.min_points_per_centroid = 1
    vectors = np.random.default_rng(7).normal(size=(600, 768)).astype(np.float32)
    faiss.normalize_L2(vectors)
    documents = []
    for doc_number, doc_id in enumerate((7, 9, 8)):
        documents.append({
            "doc_id": doc_id, "status": "ok", "url": "https://example.test/article",
            "children": [
                {"doc_id": doc_id, "chunk_order": order, "start_char": 0,
                 "end_char": len(str(position)), "chunk_text": str(position),
                 "chunk_id": f"{doc_id}:c:{order}", "parent_id": f"{doc_id}:p:0"}
                for order, position in enumerate(range(doc_number * 200, (doc_number + 1) * 200))
            ],
        })
    data_path = tmp_path / "merged.json"
    data_path.write_text(json.dumps(documents), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    result.update(
        data_path=data_path, vectors=vectors,
        encode_texts=lambda texts: np.ascontiguousarray(vectors[[int(text) for text in texts]]),
        output_index=output / "index.faiss", output_metadata=output / "metadata.json",
        partial_index=output / "index.faiss.partial", partial_metadata=output / "metadata.json.partial",
    )
    try:
        yield result
    finally:
        faiss.omp_set_num_threads(previous_threads)


def test_schema_syntax_and_preserved_gpu_safety() -> None:
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, str(NOTEBOOK_PATH), "exec")
            assert "!pip" not in cell.source and "json.load(" not in cell.source
            assert "index_cpu_to_gpu" not in cell.source
            assert not cell.outputs and cell.execution_count is None
    original = notebook_functions(ORIGINAL_PATH)
    compressed = notebook_functions(NOTEBOOK_PATH)
    for name in ("prepare_gte_model", "validate_features", "embed_once", "encode_texts",
                 "iter_merged_documents", "iter_chunk_records", "add_batch"):
        # Changed graph type in comments does not affect the parsed implementation.
        assert ast.dump(original[name]) == ast.dump(compressed[name])


def test_configuration_runs_without_dependency_cell(tmp_path, monkeypatch) -> None:
    """Reproduce running only the configuration cell in a fresh notebook namespace."""
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    code = notebook.cells[2].source
    data_path = tmp_path / "merged.json"
    data_path.write_text("[]")
    output_dir = tmp_path / "output"
    code = code.replace('data_path = input_dir / "merged.json"', f"data_path = Path({str(data_path)!r})")
    code = code.replace('output_dir = runtime_dir / "faiss_hnsw_pq64"', f"output_dir = Path({str(output_dir)!r})")
    monkeypatch.setenv("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    monkeypatch.setenv("HF_HUB_ETAG_TIMEOUT", "30")
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "false")
    previous_faiss_threads = faiss.omp_get_max_threads()
    previous_torch_threads = torch.get_num_threads()
    fresh_namespace = {}
    try:
        exec(compile(code, str(NOTEBOOK_PATH), "exec"), fresh_namespace)
        first_start = fresh_namespace["notebook_started"]
        assert first_start > 0 and fresh_namespace["setup_seconds"] >= 0
        # Running configuration again must start a new timing window.
        fresh_namespace["notebook_started"] = -1
        exec(compile(code, str(NOTEBOOK_PATH), "exec"), fresh_namespace)
        assert fresh_namespace["notebook_started"] >= first_start
    finally:
        faiss.omp_set_num_threads(previous_faiss_threads)
        torch.set_num_threads(previous_torch_threads)


def test_pq64_constructor_preserves_inner_product(namespace) -> None:
    index = namespace["index"]
    storage = faiss.downcast_index(index.storage)
    assert isinstance(index, faiss.IndexHNSWPQ) and not index.is_trained
    assert index.metric_type == storage.metric_type == faiss.METRIC_INNER_PRODUCT
    assert storage.pq.M == 64 and storage.pq.nbits == 8 and storage.code_size == 64


def test_old_faiss_constructor_fails_explicitly(namespace, monkeypatch) -> None:
    def old_constructor(*args):
        raise TypeError("old constructor")

    monkeypatch.setattr(faiss, "IndexHNSWPQ", old_constructor)
    with pytest.raises(RuntimeError, match="metric-aware"):
        namespace["create_hnsw_pq_index"](768)


def test_reservoir_is_bounded_reproducible_and_uses_entire_selected_range(namespace) -> None:
    namespace.update(start_point=8, end_point=9, train_sample_size=256)
    first, count = namespace["sample_training_texts"]()
    repeated, repeated_count = namespace["sample_training_texts"]()
    assert count == repeated_count == 400
    assert first == repeated and len(first) == len(set(first)) == 256
    assert min(int(text) for text in first) >= 200
    assert any(int(text) >= 456 for text in first)
    namespace["training_seed"] = 43
    different, _ = namespace["sample_training_texts"]()
    assert different != first


def test_too_few_training_chunks_fail_before_embedding_or_metadata(namespace) -> None:
    namespace["end_point"] = 7

    def forbidden_encode(texts):
        pytest.fail("Not enough training data should fail before embedding")

    namespace["encode_texts"] = forbidden_encode
    with pytest.raises(ValueError, match="200 eligible chunks.*at least 256"):
        namespace["train_pq_index"]()
    assert not namespace["index"].is_trained
    assert not namespace["partial_metadata"].exists()


def test_untrained_index_cannot_build(namespace) -> None:
    with pytest.raises(ValueError, match="PQ training cell"):
        namespace["build_chunk_index"]()
    assert not namespace["partial_metadata"].exists()


@pytest.mark.parametrize("verify_saved", [False, True])
def test_train_build_save_actual_pq64_codes_and_metadata(namespace, verify_saved) -> None:
    namespace["train_pq_index"]()
    assert namespace["index"].is_trained and namespace["index"].ntotal == 0
    with pytest.raises(ValueError, match="new untrained"):
        namespace["train_pq_index"]()
    count = namespace["build_chunk_index"]()
    assert count == 600
    namespace.update(metadata_count=count, build_complete=True, verify_saved_index=verify_saved)
    namespace["save_chunk_index"]()
    saved = faiss.read_index(str(namespace["output_index"]))
    metadata = json.loads(namespace["output_metadata"].read_text())
    assert list(metadata) == [str(i) for i in range(count)]
    assert [int(record["chunk_text"]) for record in metadata.values()] == list(range(count))
    storage = faiss.downcast_index(saved.storage)
    codes = faiss.vector_to_array(storage.codes).reshape(count, 64)
    np.testing.assert_array_equal(codes, storage.sa_encode(namespace["vectors"]))
    scores, ids = saved.search(namespace["vectors"][:10], 5)
    assert np.isfinite(scores).all() and np.all((ids >= 0) & (ids < count))
    assert saved.metric_type == storage.metric_type == faiss.METRIC_INNER_PRODUCT
    assert saved.is_trained and saved.ntotal == count
    assert saved.hnsw.efConstruction == 40 and saved.hnsw.efSearch == 32
    assert not namespace["partial_metadata"].exists() and not namespace["partial_index"].exists()
    assert namespace["train_seconds"] >= namespace["train_embedding_seconds"] + namespace["pq_training_seconds"]


def test_failed_embedding_keeps_partial_and_cannot_publish(namespace) -> None:
    namespace["train_pq_index"]()
    original_encode = namespace["encode_texts"]
    calls = 0

    def fail_second_batch(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic embedding failure")
        return original_encode(texts)

    namespace["encode_texts"] = fail_second_batch
    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        namespace["build_chunk_index"]()
    assert namespace["index"].ntotal == 128 and namespace["partial_metadata"].exists()
    namespace["metadata_count"] = 128
    with pytest.raises(ValueError, match="build cell successfully"):
        namespace["save_chunk_index"]()
    assert not namespace["output_index"].exists()


def test_existing_outputs_are_preserved(namespace) -> None:
    namespace["train_pq_index"]()
    namespace["output_metadata"].write_text("existing user metadata")
    with pytest.raises(FileExistsError):
        namespace["build_chunk_index"]()
    assert namespace["index"].ntotal == 0
    assert namespace["output_metadata"].read_text() == "existing user metadata"
