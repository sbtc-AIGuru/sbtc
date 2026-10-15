"""Offline checks for the standalone Kaggle/Colab HNSW notebook."""

from __future__ import annotations

import ast
import gc
import io
import json
from pathlib import Path
from time import perf_counter
from types import MethodType, SimpleNamespace
from typing import Iterator, TextIO

import faiss
import nbformat
import numpy as np
import pytest
import torch


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "BackEnd/app/Database/FAISS_HSNW_index.ipynb"
)


@pytest.fixture
def notebook_namespace() -> dict:
    """Load functions without downloading GTE weights or accessing user datasets."""
    namespace = {
        "gc": gc, "json": json, "np": np, "faiss": faiss, "torch": torch,
        "MethodType": MethodType, "Iterator": Iterator, "TextIO": TextIO,
        "perf_counter": perf_counter,
        "notebook_started": perf_counter(), "setup_seconds": 0.0, "model_seconds": 0.0,
    }
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            functions = [
                node for node in ast.parse("".join(cell["source"])).body
                if isinstance(node, ast.FunctionDef)
            ]
            exec(compile(ast.Module(body=functions, type_ignores=[]), str(NOTEBOOK_PATH), "exec"), namespace)
    return namespace


def make_document(doc_id: int, texts: tuple[str, ...] = ("First chunk", "Tiếng Việt")) -> dict:
    return {
        "doc_id": doc_id, "status": "ok", "url": "https://example.test/article",
        "children": [
            {
                "doc_id": doc_id, "chunk_order": order,
                "start_char": 0, "end_char": len(text), "chunk_text": text,
                "chunk_id": f"{doc_id}:c:{order}", "parent_id": f"{doc_id}:p:0",
            }
            for order, text in enumerate(texts)
        ],
    }


def test_notebook_schema_and_cell_syntax() -> None:
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    nbformat.validate(notebook)
    for number, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"{NOTEBOOK_PATH}:cell{number}", "exec")
            assert "!pip" not in cell.source
            assert "json.load(" not in cell.source
            assert "index_cpu_to_gpu" not in cell.source
            assert "add_with_ids" not in cell.source
            assert cell.outputs == []


@pytest.mark.parametrize("read_size", [1, 7, 64 * 1024])
@pytest.mark.parametrize("indent", [None, 2])
def test_streaming_and_inclusive_unsorted_range(notebook_namespace, read_size, indent) -> None:
    documents = [make_document(11), make_document(7), make_document(9), make_document(8), make_document(1)]
    documents[3]["children"][0]["retrieval_eligible"] = False
    documents[3]["children"][1]["chunk_text"] = "  "
    source = "\ufeff" + json.dumps(documents, ensure_ascii=False, indent=indent)
    assert list(notebook_namespace["iter_merged_documents"](io.StringIO(source), read_size=read_size)) == documents
    records = list(notebook_namespace["iter_chunk_records"](io.StringIO(source), 7, 9))
    assert [record["doc_id"] for record in records] == [7, 7, 9, 9]
    assert records[0]["char_start"] == 0
    assert records[0]["char_end"] == len("First chunk")
    assert records[0]["url"] == documents[1]["url"]


@pytest.mark.parametrize("source", ["{}", "[1]", "[{", "[{},]", "[{} {}]", "[{}]garbage"])
def test_bad_json_and_bounded_read_ahead(notebook_namespace, source) -> None:
    with pytest.raises(ValueError):
        list(notebook_namespace["iter_merged_documents"](io.StringIO(source), read_size=3))
    huge_source = io.StringIO('[{"broken":' + "x" * 100_000)
    with pytest.raises(ValueError, match="max_document_chars"):
        list(notebook_namespace["iter_merged_documents"](huge_source, read_size=8, max_document_chars=64))
    assert huge_source.tell() <= 80


@pytest.mark.parametrize("start,end", [(True, 7), (0, 1.5), (-1, -1), (9, 7)])
def test_invalid_range(notebook_namespace, start, end) -> None:
    with pytest.raises(ValueError, match="doc_id range"):
        list(notebook_namespace["iter_chunk_records"](io.StringIO("[]"), start, end))


@pytest.mark.parametrize("field,value", [("doc_id", 99), ("chunk_order", -1), ("start_char", "0"),
                                        ("end_char", -1), ("chunk_id", ""), ("parent_id", None),
                                        ("chunk_text", None)])
def test_invalid_child_has_context(notebook_namespace, field, value) -> None:
    document = make_document(7)
    document["children"][0][field] = value
    with pytest.raises(ValueError, match="document 7, child 0"):
        list(notebook_namespace["iter_chunk_records"](io.StringIO(json.dumps([document]))))


@pytest.mark.parametrize("legacy_oom", [False, True])
def test_oom_retries_without_dropping_or_reordering(notebook_namespace, monkeypatch, legacy_oom) -> None:
    calls = []
    cleanups = []

    def embed(texts, mixed_precision):
        calls.append(len(texts))
        if len(texts) > 2:
            error_type = RuntimeError if legacy_oom else torch.cuda.OutOfMemoryError
            raise error_type("CUDA out of memory")
        return np.array([[float(text.split()[0]), 1] for text in texts], dtype=np.float32)

    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: cleanups.append(True))
    notebook_namespace.update(embed_once=embed, effective_batch_size=8, index=SimpleNamespace(d=2),
                              use_fp16=True, device=torch.device("cuda:0"))
    texts = [f"{number} " + "x" * (number + 1) for number in range(9)]
    vectors = notebook_namespace["encode_texts"](texts)
    assert vectors[:, 0].tolist() == list(range(9))
    assert calls[:3] == [8, 4, 2]
    assert len(cleanups) == 2
    assert notebook_namespace["effective_batch_size"] == 2


@pytest.mark.parametrize("message,expected", [
    ("CUDA out of memory", "batch size 1"),
    ("CUDA error: device-side assert triggered", "Restart the Kaggle/Colab runtime"),
    ("CUDA illegal memory access", "Restart the Kaggle/Colab runtime"),
    ("unrelated forward failure", "unrelated forward failure"),
])
def test_terminal_gpu_errors_do_not_skip_inputs(notebook_namespace, message, expected) -> None:
    def embed(*args):
        raise RuntimeError(message)

    notebook_namespace.update(embed_once=embed, effective_batch_size=1, index=SimpleNamespace(d=2),
                              use_fp16=True, device=torch.device("cuda:0"))
    with pytest.raises(RuntimeError, match=expected):
        notebook_namespace["encode_texts"](["input"])


def test_fp32_fallback_persists_across_add_batches(notebook_namespace) -> None:
    precision_modes = []

    def embed(texts, mixed_precision):
        precision_modes.append(mixed_precision)
        if mixed_precision:
            raise FloatingPointError("non-finite embedding")
        return np.ones((len(texts), 2), dtype=np.float32)

    notebook_namespace.update(embed_once=embed, effective_batch_size=2, index=SimpleNamespace(d=2),
                              use_fp16=True, device=torch.device("cuda:0"))
    for texts in (["a", "bb", "ccc"], ["next batch"]):
        result = notebook_namespace["encode_texts"](texts)
        assert result.shape == (len(texts), 2)
    assert precision_modes == [True, False, False, False]
    assert notebook_namespace["use_fp16"] is False


@pytest.mark.parametrize("ids,mask,expected", [
    ([[32]], [[1]], "vocabulary"),
    ([[-1]], [[1]], "vocabulary"),
    ([[1] * 9], [[1] * 9], "position limit"),
    ([[2, 3]], [[1]], "match input_ids"),
    ([[2]], [[0]], "unmasked"),
])
def test_invalid_tokens_fail_before_cuda(notebook_namespace, ids, mask, expected) -> None:
    auto_model = SimpleNamespace(
        config=SimpleNamespace(max_position_embeddings=8, type_vocab_size=1),
        get_input_embeddings=lambda: SimpleNamespace(num_embeddings=32),
    )
    with pytest.raises(ValueError, match=expected):
        notebook_namespace["validate_features"](
            {"input_ids": torch.tensor(ids), "attention_mask": torch.tensor(mask)}, auto_model,
        )


@pytest.mark.parametrize("vectors,expected", [
    ([[float("nan"), 1]], "non-finite"),
    ([[0, 0]], "zero embeddings"),
    ([[1, 2, 3]], "embedding shape"),
])
def test_invalid_embeddings_are_rejected(notebook_namespace, vectors, expected) -> None:
    class FakeModel:
        def tokenize(self, texts):
            return {"input_ids": torch.tensor([[1]]), "attention_mask": torch.tensor([[1]])}

        def __call__(self, features):
            return {"sentence_embedding": torch.tensor(vectors, dtype=torch.float32)}

    notebook_namespace.update(
        model=FakeModel(), device=torch.device("cpu"), index=SimpleNamespace(d=2),
        auto_model=SimpleNamespace(
            config=SimpleNamespace(max_position_embeddings=8, type_vocab_size=1),
            get_input_embeddings=lambda: SimpleNamespace(num_embeddings=32),
        ),
    )
    with pytest.raises((ValueError, FloatingPointError), match=expected):
        notebook_namespace["embed_once"](["input"], mixed_precision=False)


@pytest.fixture
def build_namespace(notebook_namespace, tmp_path):
    previous_threads = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(1)
    notebook_namespace.update(hnsw_m=8, hnsw_ef_construction=40, hnsw_ef_search=32)
    index = notebook_namespace["create_hnsw_index"](16)
    records = ["First chunk", "Tiếng Việt", "Third", "Fourth", "Fifth"]
    vectors = np.random.default_rng(42).normal(size=(len(records), 16)).astype(np.float32)
    faiss.normalize_L2(vectors)
    vector_by_text = dict(zip(records, vectors))

    def embed(texts):
        return np.ascontiguousarray([vector_by_text[text] for text in texts], dtype=np.float32)

    source = tmp_path / "merged.json"
    source.write_text(json.dumps([
        make_document(7), make_document(9, ("Third", "Fourth")), make_document(8, ("Fifth",)),
    ]), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    notebook_namespace.update(
        index=index, data_path=source, start_point=7, end_point=9, add_batch_size=3,
        effective_batch_size=2, encode_texts=embed, output_index=output / "index.faiss",
        output_metadata=output / "metadata.json", partial_index=output / "index.faiss.partial",
        partial_metadata=output / "metadata.json.partial", build_complete=False,
        verify_saved_index=False, expected_vectors=vectors,
    )
    try:
        yield notebook_namespace
    finally:
        faiss.omp_set_num_threads(previous_threads)


@pytest.mark.parametrize("verify_saved", [False, True])
def test_real_hnsw_round_trip_ids_scores_and_metadata(build_namespace, verify_saved) -> None:
    namespace = build_namespace
    count = namespace["build_chunk_index"]()
    assert count == 5
    assert not namespace["output_metadata"].exists()
    namespace.update(metadata_count=count, build_complete=True, verify_saved_index=verify_saved)
    namespace["save_chunk_index"]()
    metadata = json.loads(namespace["output_metadata"].read_text())
    assert list(metadata) == ["0", "1", "2", "3", "4"]
    assert [record["chunk_id"] for record in metadata.values()] == [
        "7:c:0", "7:c:1", "9:c:0", "9:c:1", "8:c:0",
    ]
    saved = faiss.read_index(str(namespace["output_index"]))
    assert isinstance(saved, faiss.IndexHNSWFlat)
    assert saved.metric_type == faiss.METRIC_INNER_PRODUCT
    assert saved.hnsw.efConstruction == 40
    assert saved.hnsw.efSearch == 32
    np.testing.assert_array_equal(saved.reconstruct_n(0, count), namespace["expected_vectors"])
    scores, ids = saved.search(namespace["expected_vectors"], 1)
    assert ids[:, 0].tolist() == list(range(count))
    np.testing.assert_allclose(scores[:, 0], 1, atol=1e-6)
    assert not namespace["partial_metadata"].exists()
    assert not namespace["partial_index"].exists()
    with pytest.raises(ValueError, match="empty HNSW"):
        namespace["build_chunk_index"]()
    assert namespace["build_complete"] is False


def test_default_save_does_not_allocate_a_second_index(build_namespace, monkeypatch) -> None:
    namespace = build_namespace
    count = namespace["build_chunk_index"]()
    namespace.update(metadata_count=count, build_complete=True)

    def no_read(*args):
        pytest.fail("Default save must not reload the full HNSW graph")

    monkeypatch.setattr(faiss, "read_index", no_read)
    namespace["save_chunk_index"]()
    assert namespace["output_index"].is_file()


def test_failed_build_cannot_publish_or_reuse_stale_success(build_namespace) -> None:
    namespace = build_namespace
    original_embed = namespace["encode_texts"]
    calls = 0

    def fail_second(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic embedding failure")
        return original_embed(texts)

    namespace.update(encode_texts=fail_second, build_complete=True)
    with pytest.raises(ValueError, match="synthetic embedding failure"):
        namespace["build_chunk_index"]()
    assert namespace["index"].ntotal == 3
    assert namespace["partial_metadata"].is_file()
    assert namespace["build_complete"] is False
    namespace["metadata_count"] = 3
    with pytest.raises(ValueError, match="build cell successfully"):
        namespace["save_chunk_index"]()
    assert not namespace["output_index"].exists()


@pytest.mark.parametrize("output_name", ["output_index", "output_metadata", "partial_index", "partial_metadata"])
def test_existing_output_is_preserved(build_namespace, output_name) -> None:
    namespace = build_namespace
    namespace[output_name].write_text("existing user data")
    with pytest.raises(FileExistsError):
        namespace["build_chunk_index"]()
    assert namespace[output_name].read_text() == "existing user data"
    assert namespace["index"].ntotal == 0


def test_empty_selection_round_trip(build_namespace) -> None:
    namespace = build_namespace
    namespace.update(start_point=999, end_point=-1)
    count = namespace["build_chunk_index"]()
    assert count == 0
    namespace.update(metadata_count=count, build_complete=True, verify_saved_index=True)
    namespace["save_chunk_index"]()
    assert json.loads(namespace["output_metadata"].read_text()) == {}
    assert faiss.read_index(str(namespace["output_index"])).ntotal == 0


def test_count_mismatch_cannot_be_published(build_namespace) -> None:
    namespace = build_namespace
    count = namespace["build_chunk_index"]()
    namespace.update(metadata_count=count - 1, build_complete=True)
    with pytest.raises(ValueError, match="build cell successfully"):
        namespace["save_chunk_index"]()
    assert namespace["partial_metadata"].exists()
    assert not namespace["output_index"].exists()


def test_failed_disk_write_keeps_partial_outputs(build_namespace, monkeypatch) -> None:
    namespace = build_namespace
    count = namespace["build_chunk_index"]()
    namespace.update(metadata_count=count, build_complete=True)

    def fail_write(*args):
        raise RuntimeError("synthetic disk full")

    monkeypatch.setattr(faiss, "write_index", fail_write)
    with pytest.raises(RuntimeError, match="disk full"):
        namespace["save_chunk_index"]()
    assert namespace["partial_metadata"].exists()
    assert namespace["partial_index"].exists()
    assert not namespace["output_index"].exists()
    assert not namespace["output_metadata"].exists()


def test_all_cells_run_with_offline_cpu_model(tmp_path, monkeypatch, capsys) -> None:
    """Exercise Run All, buffer repair, forward, normalization and real HNSW I/O."""
    class Embeddings(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.word_embeddings = torch.nn.Embedding(32, 768)
            self.register_buffer("position_ids", torch.full((8,), 999_999), persistent=False)

        def _init_rope(self, config):
            self.rotary_emb = torch.nn.Module()
            angles = torch.arange(config.max_position_embeddings).float()[:, None]
            self.rotary_emb.register_buffer("cos_cached", angles.cos(), persistent=False)
            self.rotary_emb.register_buffer("sin_cached", angles.sin(), persistent=False)

    class AutoModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(model_type="new", max_position_embeddings=8,
                                          type_vocab_size=1, is_decoder=False)
            self.embeddings = Embeddings()

        @property
        def dtype(self):
            return self.embeddings.word_embeddings.weight.dtype

        def get_input_embeddings(self):
            return self.embeddings.word_embeddings

    class OfflineModel(torch.nn.Module):
        max_seq_length = 8
        default_prompt_name = None

        def __init__(self, *args, **kwargs):
            super().__init__()
            assert kwargs["device"] == "cpu"
            self.encoder = AutoModel()

        def __getitem__(self, position):
            assert position == 0
            return SimpleNamespace(auto_model=self.encoder)

        def get_sentence_embedding_dimension(self):
            return 768

        def tokenize(self, texts):
            # Generate bounded token IDs without downloading a tokenizer.
            ids = torch.tensor([[ord(char) % 31 + 1 for char in text[:8].ljust(8)] for text in texts])
            return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

        def forward(self, features):
            assert not self.training
            assert torch.is_inference_mode_enabled()
            assert self.encoder.embeddings.position_ids.tolist() == list(range(8))
            assert torch.isfinite(self.encoder.embeddings.rotary_emb.cos_cached).all()
            assert features["position_ids"].shape == features["input_ids"].shape
            mask = self.encoder.get_extended_attention_mask(features["attention_mask"], features["input_ids"].shape)
            assert mask.shape == (features["input_ids"].shape[0], 1, 1, 8)
            return {"sentence_embedding": self.encoder.get_input_embeddings()(features["input_ids"]).mean(1)}

    import sentence_transformers

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", OfflineModel)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "false")
    monkeypatch.setenv("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    monkeypatch.setenv("HF_HUB_ETAG_TIMEOUT", "30")
    source_path = tmp_path / "merged.json"
    source_path.write_text(json.dumps([make_document(7)]), encoding="utf-8")
    namespace = {}
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    previous_faiss_threads = faiss.omp_get_max_threads()
    previous_torch_threads = torch.get_num_threads()
    try:
        with torch.random.fork_rng(devices=[]):
            for number, cell in enumerate(notebook.cells):
                if cell.cell_type == "code":
                    code = cell.source
                    if number == 2:
                        code = code.replace('data_path = input_dir / "merged.json"', f"data_path = Path({str(source_path)!r})")
                        code = code.replace('output_dir = runtime_dir / "faiss_hnsw"', f"output_dir = Path({str(tmp_path / 'faiss_hnsw')!r})")
                    exec(compile(code, f"{NOTEBOOK_PATH}:cell{number}", "exec"), namespace)
    finally:
        faiss.omp_set_num_threads(previous_faiss_threads)
        torch.set_num_threads(previous_torch_threads)
    saved = faiss.read_index(str(namespace["output_index"]))
    assert saved.ntotal == 2
    np.testing.assert_allclose(np.linalg.norm(saved.reconstruct_n(0, 2), axis=1), 1, atol=1e-6)
    assert list(json.loads(namespace["output_metadata"].read_text())) == ["0", "1"]
    for name in ("setup_seconds", "model_seconds", "build_seconds", "embedding_total_seconds",
                 "add_total_seconds", "save_seconds", "total_runtime_seconds"):
        assert namespace[name] >= 0
    assert namespace["build_seconds"] >= namespace["embedding_total_seconds"] + namespace["add_total_seconds"]
    assert namespace["total_runtime_seconds"] >= namespace["build_seconds"] + namespace["save_seconds"]
    output = capsys.readouterr().out
    assert "Runtime summary:" in output
    assert "Total notebook wall time:" in output
    assert "elapsed=" in output
