"""Offline regression checks for the Kaggle/Colab chunk-index notebook."""

from __future__ import annotations

import ast
import gc
import io
import json
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Iterator, TextIO

import faiss
import nbformat
import numpy as np
import pytest
import torch


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "BackEnd/app/Database/FAISS_index_chunks.ipynb"
)


@pytest.fixture
def notebook_namespace() -> dict:
    """Execute the notebook's functions without downloading weights or using user data."""
    namespace = {
        "gc": gc, "json": json, "np": np, "faiss": faiss, "torch": torch,
        "MethodType": MethodType, "Iterator": Iterator, "TextIO": TextIO,
    }
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(NOTEBOOK_PATH), "exec"), namespace)
    return namespace


def make_document(doc_id: int = 7, texts: tuple[str, ...] = ("First chunk", "Tiếng Việt")) -> dict:
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


def test_notebook_schema_syntax_and_no_automatic_installs() -> None:
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    nbformat.validate(notebook)
    for number, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"{NOTEBOOK_PATH}:cell{number}", "exec")
            assert "!pip" not in cell.source
            assert "json.load(" not in cell.source


@pytest.mark.parametrize("indent", [None, 2])
@pytest.mark.parametrize("read_size", [1, 7, 64 * 1024])
def test_streaming_handles_formatting_and_block_boundaries(notebook_namespace, indent, read_size) -> None:
    documents = [make_document(), make_document(8, ('Escaped quote: " and } ] ,',))]
    source = "\ufeff \n" + json.dumps(documents, ensure_ascii=False, indent=indent) + "\n"
    result = list(notebook_namespace["iter_merged_documents"](io.StringIO(source), read_size=read_size))
    assert result == documents


@pytest.mark.parametrize("source", ["[]", " [\n ] \n", "\ufeff[]"])
def test_empty_array(notebook_namespace, source) -> None:
    assert list(notebook_namespace["iter_merged_documents"](io.StringIO(source), read_size=1)) == []


@pytest.mark.parametrize("source", [
    "", "{}", "[1]", "[{}", "[{", "[{},]", "[{} {}]", "[{}]garbage", "[\n",
])
def test_invalid_json_is_rejected(notebook_namespace, source) -> None:
    with pytest.raises(ValueError):
        list(notebook_namespace["iter_merged_documents"](io.StringIO(source), read_size=3))


def test_malformed_document_has_bounded_read_ahead(notebook_namespace) -> None:
    source = io.StringIO('[{"broken":' + "x" * 100_000)
    with pytest.raises(ValueError, match="max_document_chars"):
        list(notebook_namespace["iter_merged_documents"](source, read_size=8, max_document_chars=64))
    assert source.tell() <= 80


def test_filtering_and_metadata_fields(notebook_namespace) -> None:
    document = make_document(texts=("Keep me", "  ", "Not eligible"))
    document["children"][2]["retrieval_eligible"] = False
    failed = {"doc_id": 8, "status": "error"}
    source = json.dumps([make_document(1), document, failed, make_document(9)])
    records = list(notebook_namespace["iter_chunk_records"](io.StringIO(source), 7, 8))
    assert len(records) == 1
    assert records[0] == {
        "doc_id": 7, "chunk_order": 0, "char_start": 0, "char_end": 7,
        "chunk_text": "Keep me", "chunk_id": "7:c:0", "parent_id": "7:p:0",
        "url": "https://example.test/article",
    }


@pytest.mark.parametrize("field,value,expected", [
    ("doc_id", 99, "doc_id"), ("chunk_text", None, "chunk_text"),
    ("chunk_order", -1, "chunk_order"), ("start_char", "0", "start_char"),
    ("end_char", -2, "end_char"), ("chunk_id", "", "chunk_id"),
    ("parent_id", None, "parent_id"),
])
def test_invalid_child_has_context(notebook_namespace, field, value, expected) -> None:
    document = make_document()
    document["children"][0][field] = value
    with pytest.raises(ValueError, match=expected) as error:
        list(notebook_namespace["iter_chunk_records"](io.StringIO(json.dumps([document]))))
    assert "document 7, child 0" in str(error.value)


def make_auto_model() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(max_position_embeddings=8, type_vocab_size=1),
        get_input_embeddings=lambda: SimpleNamespace(num_embeddings=32),
    )


def test_buffer_repair_preserves_weights_and_supplies_legacy_mask(notebook_namespace) -> None:
    class Embeddings(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.word_embeddings = torch.nn.Embedding(32, 8)
            self.register_buffer("position_ids", torch.full((8,), 999_999), persistent=False)
            self.rotary_emb = torch.nn.Module()
            self.rotary_emb.register_buffer("cos_cached", torch.full((8, 4), float("nan")))

        def _init_rope(self, config):
            self.rotary_emb = torch.nn.Module()
            angles = torch.arange(config.max_position_embeddings).float()[:, None].expand(-1, 4)
            self.rotary_emb.register_buffer("cos_cached", angles.cos(), persistent=False)
            self.rotary_emb.register_buffer("sin_cached", angles.sin(), persistent=False)

    model = SimpleNamespace(
        config=SimpleNamespace(model_type="new", max_position_embeddings=8, is_decoder=False),
        embeddings=Embeddings(), dtype=torch.float32,
    )
    original_weights = model.embeddings.word_embeddings.weight.detach().clone()
    notebook_namespace["prepare_gte_model"](model)
    assert model.embeddings.position_ids.tolist() == list(range(8))
    assert torch.isfinite(model.embeddings.rotary_emb.cos_cached).all()
    assert torch.equal(original_weights, model.embeddings.word_embeddings.weight)
    mask = model.get_extended_attention_mask(torch.tensor([[1, 0]]), (1, 2))
    assert mask.shape == (1, 1, 1, 2)
    assert mask[0, 0, 0, 0].item() == 0
    assert mask[0, 0, 0, 1].item() == torch.finfo(torch.float32).min
    with pytest.raises(ValueError, match="Unsupported attention mask"):
        model.get_extended_attention_mask(torch.ones(2), (1, 2))


def test_cpu_feature_validation_provides_safe_positions(notebook_namespace) -> None:
    features = {"input_ids": torch.tensor([[2, 3, 1], [4, 1, 1]]),
                "attention_mask": torch.tensor([[1, 1, 0], [1, 0, 0]])}
    notebook_namespace["validate_features"](features, make_auto_model())
    assert features["position_ids"].tolist() == [[0, 1, 2], [0, 1, 2]]
    assert not features["token_type_ids"].any()


@pytest.mark.parametrize("ids,mask,message", [
    ([[32]], [[1]], "vocabulary"), ([[-1]], [[1]], "vocabulary"),
    ([[1] * 9], [[1] * 9], "position limit"),
    ([[2, 3]], [[1]], "match input_ids"),
    ([[2]], [[0]], "unmasked"), ([[2]], [[2]], "unmasked"),
])
def test_invalid_indices_fail_on_cpu(notebook_namespace, ids, mask, message) -> None:
    with pytest.raises(ValueError, match=message):
        notebook_namespace["validate_features"](
            {"input_ids": torch.tensor(ids), "attention_mask": torch.tensor(mask)}, make_auto_model(),
        )


def test_adaptive_oom_keeps_order_and_every_record(notebook_namespace, monkeypatch) -> None:
    calls = []
    cleanups = []

    def embed(texts, mixed_precision):
        calls.append(len(texts))
        if len(texts) > 2:
            raise torch.cuda.OutOfMemoryError("synthetic OOM")
        return np.array([[float(text.split()[0]), 1] for text in texts], dtype=np.float32)

    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: cleanups.append(True))
    notebook_namespace.update(
        embed_once=embed, effective_batch_size=8, index=SimpleNamespace(d=2),
        use_fp16=True, device=torch.device("cuda:0"),
    )
    texts = [f"{number} " + "x" * (number + 1) for number in range(9)]
    vectors = notebook_namespace["encode_texts"](texts)
    assert vectors[:, 0].tolist() == list(range(9))
    assert calls[:3] == [8, 4, 2]
    assert len(cleanups) == 2
    assert notebook_namespace["effective_batch_size"] == 2


def test_single_record_oom_stops_without_skipping(notebook_namespace, monkeypatch) -> None:
    def embed(*args):
        raise torch.cuda.OutOfMemoryError("synthetic OOM")

    notebook_namespace.update(embed_once=embed, effective_batch_size=1, index=SimpleNamespace(d=2),
                              use_fp16=True, device=torch.device("cuda:0"))
    with pytest.raises(RuntimeError, match="batch size 1"):
        notebook_namespace["encode_texts"](["input"])


def test_fp16_failure_retries_fp32(notebook_namespace) -> None:
    precision_modes = []

    def embed(texts, mixed_precision):
        precision_modes.append(mixed_precision)
        if mixed_precision:
            raise FloatingPointError("synthetic non-finite embedding")
        return np.ones((len(texts), 2), dtype=np.float32)

    notebook_namespace.update(embed_once=embed, effective_batch_size=2, index=SimpleNamespace(d=2),
                              use_fp16=True, device=torch.device("cuda:0"))
    result = notebook_namespace["encode_texts"](["a", "bb", "ccc"])
    assert precision_modes == [True, False, False]
    assert result.shape == (3, 2)


def test_cuda_assert_requires_restart(notebook_namespace) -> None:
    def embed(*args):
        raise RuntimeError("CUDA error: device-side assert triggered")

    notebook_namespace.update(embed_once=embed, effective_batch_size=2, index=SimpleNamespace(d=2),
                              use_fp16=True, device=torch.device("cuda:0"))
    with pytest.raises(RuntimeError, match="Restart the Kaggle/Colab runtime"):
        notebook_namespace["encode_texts"](["input"])


@pytest.fixture
def build_namespace(notebook_namespace, tmp_path) -> dict:
    previous_threads = faiss.omp_get_max_threads()
    faiss.omp_set_num_threads(1)
    rng = np.random.default_rng(42)
    training_vectors = rng.standard_normal((256, 16)).astype(np.float32)
    faiss.normalize_L2(training_vectors)
    index = faiss.IndexIVFPQ(faiss.IndexFlatIP(16), 16, 4, 4, 2, faiss.METRIC_INNER_PRODUCT)
    index.train(training_vectors)

    def embed(texts):
        vectors = training_vectors[:len(texts)].copy()
        return np.ascontiguousarray(vectors)

    source = tmp_path / "merged.json"
    source.write_text(json.dumps([make_document(), make_document(8)]), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    notebook_namespace.update(
        index=index, data_path=source, start_point=0, end_point=-1, add_batch_size=3,
        encode_texts=embed, output_index=output / "index.faiss",
        output_metadata=output / "metadata.json", partial_index=output / "index.faiss.partial",
        partial_metadata=output / "metadata.json.partial", build_complete=False, faiss_on_gpu=False,
    )
    try:
        yield notebook_namespace
    finally:
        faiss.omp_set_num_threads(previous_threads)


def test_real_ivfpq_build_save_ids_and_metadata(build_namespace) -> None:
    namespace = build_namespace
    count = namespace["build_chunk_index"]()
    assert count == 4
    assert namespace["partial_metadata"].exists()
    assert not namespace["output_metadata"].exists()
    namespace.update(metadata_count=count, build_complete=True)
    namespace["save_chunk_index"]()
    metadata = json.loads(namespace["output_metadata"].read_text())
    assert list(metadata) == ["0", "1", "2", "3"]
    assert [record["chunk_id"] for record in metadata.values()] == ["7:c:0", "7:c:1", "8:c:0", "8:c:1"]
    saved = faiss.read_index(str(namespace["output_index"]))
    stored_ids = []
    for list_id in range(saved.nlist):
        size = saved.invlists.list_size(list_id)
        stored_ids.extend(faiss.rev_swig_ptr(saved.invlists.get_ids(list_id), size).tolist())
    assert sorted(stored_ids) == [0, 1, 2, 3]
    assert saved.ntotal == count
    assert not namespace["partial_metadata"].exists()
    assert not namespace["partial_index"].exists()
    with pytest.raises(ValueError, match="Reload an empty"):
        namespace["build_chunk_index"]()


def test_failed_build_keeps_partial_and_cannot_publish(build_namespace) -> None:
    namespace = build_namespace
    calls = 0
    original_embed = namespace["encode_texts"]

    def fail_second_batch(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic embedding failure")
        return original_embed(texts)

    namespace["encode_texts"] = fail_second_batch
    with pytest.raises(ValueError, match="synthetic embedding failure"):
        namespace["build_chunk_index"]()
    assert namespace["index"].ntotal == 3
    assert namespace["partial_metadata"].exists()
    namespace["metadata_count"] = 3
    with pytest.raises(ValueError, match="build cell successfully"):
        namespace["save_chunk_index"]()
    assert not namespace["output_index"].exists()
    assert not namespace["output_metadata"].exists()


def test_existing_output_is_preserved(build_namespace) -> None:
    namespace = build_namespace
    namespace["output_metadata"].write_text("existing user data")
    with pytest.raises(FileExistsError):
        namespace["build_chunk_index"]()
    assert namespace["output_metadata"].read_text() == "existing user data"
    assert namespace["index"].ntotal == 0


def test_empty_selection_can_be_saved(build_namespace) -> None:
    namespace = build_namespace
    namespace["start_point"] = 999
    count = namespace["build_chunk_index"]()
    assert count == 0
    namespace.update(metadata_count=count, build_complete=True)
    namespace["save_chunk_index"]()
    assert json.loads(namespace["output_metadata"].read_text()) == {}
    assert faiss.read_index(str(namespace["output_index"])).ntotal == 0


def test_count_mismatch_cannot_be_published(build_namespace) -> None:
    namespace = build_namespace
    count = namespace["build_chunk_index"]()
    namespace.update(metadata_count=count - 1, build_complete=True)
    with pytest.raises(ValueError, match="build cell successfully"):
        namespace["save_chunk_index"]()
    assert not namespace["output_index"].exists()
    assert namespace["partial_metadata"].exists()
