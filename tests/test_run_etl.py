"""Check batched in-place ETL and preservation of the original on failure."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Scripts.ETL_Pipeline.data_preprocess import ETL
from Scripts.ETL_Pipeline import run_etl as runner
from Scripts.ETL_Pipeline.run_etl import run_etl


def sample_documents() -> list[dict]:
    return [
        {
            "doc_id": 1, "status": "ok", "title": None,
            "source_sha256": "original-hash", "source_length": 100,
            "parents": [{"parent_id": "p1", "start_char": 0, "end_char": 100}],
            "title_spans": [{"start_char": 0, "end_char": 15}],
            "future_field": {"values": [None, True, 12345678901234567890]},
            "children": [
                {"chunk_id": "c2", "chunk_order": 1, "start_char": 20,
                 "end_char": 90, "chunk_text": "Bệnh nhân  uống 5 mg/kg. 🚀",
                 "retrieval_eligible": True},
                {"chunk_id": "c1", "chunk_order": 0, "start_char": 0,
                 "end_char": 40, "chunk_text": "患者体温 ≥ 38°C。\n（图片来源：医院）",
                 "retrieval_eligible": False},
            ],
        },
        {"doc_id": 2, "status": "skipped", "children": []},
        {"doc_id": 3, "children": [{"chunk_text": "English  text. (Photo: Example)"}]},
        {"doc_id": 4, "extra": "Document without a children field"},
    ]


@pytest.mark.parametrize("format_name", ["jsonl", "array", "pretty_array", "compact_array"])
@pytest.mark.parametrize("batch_size", [1, 3, 100])
def test_only_chunk_text_changes(tmp_path: Path, format_name: str, batch_size: int) -> None:
    documents = sample_documents()
    if format_name == "jsonl":
        # Detect content even when a JSONL file is named merged.json.
        source = "\n".join(json.dumps(doc, ensure_ascii=False) for doc in documents)
    else:
        indent = 2 if format_name == "pretty_array" else None
        source = json.dumps(documents, ensure_ascii=False, indent=indent)
        if format_name == "array":
            source = "[\n" + ",\n".join(json.dumps(doc) for doc in documents) + "\n]"
    path = tmp_path / "merged.json"
    path.write_text("\ufeff\n " + source, encoding="utf-8")
    path.chmod(0o640)

    assert run_etl(path, batch_size=batch_size) == (4, 3, 3)

    output = path.read_text(encoding="utf-8")
    result = [json.loads(line) for line in output.splitlines()] if format_name == "jsonl" else json.loads(output)
    expected = deepcopy(documents)
    for document in expected:
        for child in document.get("children", []):
            child["chunk_text"] = ETL().ETL_Pipeline(child["chunk_text"])
    assert result == expected
    assert path.stat().st_mode & 0o777 == 0o640
    assert not list(tmp_path.glob("*.etl.tmp"))
    assert run_etl(path, batch_size=batch_size) == (4, 3, 0)


@pytest.mark.parametrize("source", ["", "\n\t", "[]", "[\n\n]"])
def test_empty_input(tmp_path: Path, source: str) -> None:
    path = tmp_path / "merged.json"
    path.write_text(source, encoding="utf-8")
    assert run_etl(path, batch_size=2) == (0, 0, 0)
    output = path.read_text(encoding="utf-8")
    assert json.loads(output) == [] if source.strip().startswith("[") else output == ""


@pytest.mark.parametrize("suffix", [
    "\nnot-json", "\n[]", '\n{"children":[{"chunk_text":null}]}',
])
def test_late_jsonl_failure_keeps_original(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / "merged.jsonl"
    path.write_text(json.dumps(sample_documents()[0]) + suffix, encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        run_etl(path, batch_size=1)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.etl.tmp"))


@pytest.mark.parametrize("source", [
    "[", "[{}", "[{},]", "[{} {}]", "[{}]extra", "[[]]", '[{}, {"children":',
])
def test_invalid_arrays_keep_original(tmp_path: Path, source: str) -> None:
    path = tmp_path / "merged.json"
    path.write_text(source, encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        run_etl(path, batch_size=1)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.etl.tmp"))


def test_array_document_crosses_read_buffer_boundary(tmp_path: Path) -> None:
    documents = [{"padding": "x" * (1024 * 1024 + 10)}, *sample_documents()]
    path = tmp_path / "merged.json"
    path.write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")
    assert run_etl(path, batch_size=2) == (5, 3, 3)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result[0] == documents[0]
    assert len(result) == len(documents)


def test_invalid_batch_size_does_not_modify_file(tmp_path: Path) -> None:
    path = tmp_path / "merged.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="positive"):
        run_etl(path, batch_size=0)
    assert path.read_text(encoding="utf-8") == "{}\n"


def test_replace_failure_keeps_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "merged.jsonl"
    path.write_text(json.dumps(sample_documents()[0]), encoding="utf-8")
    original = path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("Simulated replace failure")

    monkeypatch.setattr(runner.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Simulated replace failure"):
        run_etl(path, batch_size=1)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.etl.tmp"))
