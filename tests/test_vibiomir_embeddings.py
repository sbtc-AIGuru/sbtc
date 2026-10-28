import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest
import torch
import zstandard as zstd

from Scripts.Kaggle import import_vibiomir_qdrant as loader
from Scripts.Kaggle import vibiomir_embedding_runtime as runtime
from Scripts.Kaggle import read_vibiomir_outputs as reader


def config(part=1):
    return dict(part=part, model_id="Qwen/Qwen3-Embedding-0.6B", revision="fixed-revision",
                dimension=4, max_length=100, dtype="float16", pooling="last_token",
                normalize=True, document_prompt="", vector_name="qwen3_dense",
                max_batch_size=3, padded_token_budget=12, resume_roots=[])


def record(index):
    return dict(chunk_id=f"{index}:chunk:00001", doc_id=index, content=f"Nội dung 中文 {index}",
                token_count=7, content_origin="linked_pdf", extra={"recovery": True, "items": [1, None]})


def make_outputs(tmp_path):
    source = dict(source_file="original.jsonl", source_sha256="source-digest", total_rows=4)
    roots = []
    vector = np.array([[.5, .5, .5, .5]], dtype=np.float32)
    for part in (1, 2):
        folder = tmp_path / f"part-{part}"
        folder.mkdir()
        cfg = config(part)
        receipts = []
        for gpu in (0, 1):
            index = (part - 1) * 2 + gpu + 1
            path = folder / f"p{part}-gpu{gpu}-{index:09d}.parquet"
            receipts.append(runtime.write_shard(path, [(record(index), index, index * 500)],
                                               vector, [7], cfg, source, gpu))
        profile = runtime.encoder_profile(cfg)
        manifest = dict(complete=True, rows=2, expected_rows=2, part=part, source=source,
                        encoder=profile, profile_id=runtime.profile_id(profile), files=receipts)
        runtime.atomic_json(folder / "manifest.json", manifest)
        roots.append(folder)
    return roots, source


def test_payload_roundtrip_and_full_source_coverage(tmp_path):
    roots, source = make_outputs(tmp_path)
    manifest, files = loader.load_parts(roots[::-1])
    assert manifest["source"] == source
    assert len(files) == 4
    for index, (path, receipt) in enumerate(files, 1):
        ids, vectors, payloads = next(loader.iter_points(path, 4, 1, receipt))
        assert ids == [runtime.point_id(record(index)["chunk_id"])]
        payload = payloads[0]
        original = {key: value for key, value in payload.items() if key != "_embedding"}
        assert original == record(index)
        assert payload["_embedding"]["source_line"] == index
        assert payload["_embedding"]["source_byte"] == index * 500
        assert payload["_embedding"]["truncated"] is False
        np.testing.assert_allclose(vectors, [[.5] * 4])
        assert pq.ParquetFile(path).schema_arrow.field("vector").type.list_size == 4
    loader.import_parts(roots, None, None, "unused", tmp_path / "checkpoint", validate_only=True)
    assert not (tmp_path / "checkpoint").exists()


@pytest.mark.parametrize("fault", ["partial", "gap", "overlap", "different_encoder", "corrupt_file", "missing_file"])
def test_import_rejects_incomplete_or_incompatible_outputs(tmp_path, fault):
    roots, _ = make_outputs(tmp_path)
    path = roots[1] / "manifest.json"
    manifest = json.loads(path.read_text())
    if fault == "partial":
        manifest["complete"] = False
    elif fault == "gap":
        manifest["files"][0]["start_line"] += 1
    elif fault == "overlap":
        manifest["files"][0]["start_line"] -= 1
    elif fault == "different_encoder":
        manifest["encoder"]["revision"] = "another-revision"
    elif fault == "corrupt_file":
        (roots[1] / manifest["files"][0]["file"]).write_bytes(b"corrupt")
    elif fault == "missing_file":
        (roots[1] / manifest["files"][0]["file"]).unlink()
    runtime.atomic_json(path, manifest)
    with pytest.raises((ValueError, FileNotFoundError)):
        loader.load_parts(roots)


def test_resume_checks_checksum_and_encoder(tmp_path):
    roots, source = make_outputs(tmp_path)
    output = tmp_path / "resumed"
    output.mkdir()
    cfg = config()
    cfg["resume_roots"] = [str(roots[0])]
    shard = dict(start_line=1, end_line=1)
    receipts = runtime.restore_shards(output, shard, cfg, source, 0)
    assert sum(item["rows"] for item in receipts) == 1
    assert (output / receipts[0]["file"]).read_bytes() == (roots[0] / receipts[0]["file"]).read_bytes()
    cfg["revision"] = "changed"
    with pytest.raises(ValueError, match="configuration differs"):
        runtime.restore_shards(output, shard, cfg, source, 0)


def test_length_buckets_obey_batch_and_padding_budget():
    lengths = [10, 2, 3, 6, 8, 1, 4]
    batches = list(runtime.batches_by_length(lengths, 3, 12))
    assert sorted(index for batch in batches for index in batch) == list(range(len(lengths)))
    for batch in batches:
        assert len(batch) <= 3
        assert max(lengths[index] for index in batch) * len(batch) <= 12


def test_last_token_pooling_restores_order_without_truncation():
    cfg = config()
    cfg.update(max_length=10, max_batch_size=4, padded_token_budget=12)

    class Tokenizer:
        def __call__(self, texts, **kwargs):
            assert kwargs["truncation"] is False
            return {"input_ids": [[ord(char) for char in text] for text in texts],
                    "attention_mask": [[1] * len(text) for text in texts]}

        def pad(self, records, **kwargs):
            size = max(len(row["input_ids"]) for row in records)
            return {key: torch.tensor([[0] * (size - len(row[key])) + row[key] for row in records])
                    for key in ("input_ids", "attention_mask")}

    class Model:
        def __call__(self, input_ids, attention_mask, **kwargs):
            from types import SimpleNamespace
            values = input_ids.float()
            hidden = torch.stack([values, values + 1, values + 2, values + 3], dim=-1)
            return SimpleNamespace(last_hidden_state=hidden)

    texts = ["abcd", "z", "xy"]
    records = [(dict(content=text, chunk_id=str(index)), index, 0) for index, text in enumerate(texts)]
    vectors, lengths, oom = runtime.embed_records(records, Tokenizer(), Model(), cfg, "cpu")
    expected = np.array([[ord(text[-1]) + offset for offset in range(4)] for text in texts], dtype=np.float32)
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    np.testing.assert_allclose(vectors, expected, atol=1e-7)
    assert lengths == [4, 1, 2]
    assert oom == 0
    cfg["max_length"] = 2
    with pytest.raises(ValueError, match="no content was truncated"):
        runtime.embed_records(records, Tokenizer(), Model(), cfg, "cpu")


def test_compressed_source_retains_original_line_and_byte_offsets(tmp_path):
    data = b''.join((json.dumps(record(i), ensure_ascii=False) + '\n').encode() for i in (1, 2))
    path = tmp_path / "source.zst"
    path.write_bytes(zstd.ZstdCompressor().compress(data))
    shard = dict(start_line=8, start_byte=100, rows=2, end_byte=100 + len(data),
                 raw_sha256=hashlib.sha256(data).hexdigest())
    rows = list(runtime.source_records(path, shard))
    assert rows[0] == (record(1), 8, 100)
    assert rows[1] == (record(2), 9, 100 + len(data.splitlines(keepends=True)[0]))
    shard["raw_sha256"] = "incorrect"
    with pytest.raises(ValueError, match="source manifest"):
        list(runtime.source_records(path, shard))


def test_two_notebooks_are_standalone_and_use_two_gpu_workers():
    root = Path(__file__).resolve().parents[1]
    for part in (1, 2, 3):
        path = root / f"BackEnd/app/Database/Notebook/ViBioMIR_Qwen3_06B_Part{part}_T4x2.ipynb"
        notebook = json.loads(path.read_text())
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile(cell["source"], str(path), "exec")
        source = '\n'.join(cell["source"] for cell in notebook["cells"])
        assert "--nproc_per_node=2" in source
        assert "vibiomir_embedding_runtime.py" in source
        namespace = {}
        exec(notebook["cells"][1]["source"], namespace)
        assert namespace["CONFIG"]["part"] == part
        assert namespace["CONFIG"]["dimension"] == 1024
        assert namespace["CONFIG"]["max_hours"] < 12


def test_three_input_parts_cover_every_row_without_gaps_and_balance_tokens():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "artifacts/vibiomir-qwen3-3parts-20261024/dataset/source_manifest.json").read_text())
    assert manifest["num_parts"] == 3
    assert manifest["total_rows"] == 4_936_835
    assert manifest["unique_chunk_ids"] is True
    line, offset = 1, 0
    totals = []
    for part in (1, 2, 3):
        shards = [shard for shard in manifest["shards"] if shard["part"] == part]
        assert [shard["gpu"] for shard in shards] == [0, 1]
        totals.append(sum(shard["tokens"] for shard in shards))
        for shard in shards:
            assert shard["start_line"] == line
            assert shard["start_byte"] == offset
            assert shard["end_line"] - line + 1 == shard["rows"]
            line = shard["end_line"] + 1
            offset = shard["end_byte"]
    assert line == manifest["total_rows"] + 1
    assert offset == manifest["source_bytes"]
    assert max(totals) - min(totals) < 512


def test_shared_part3_has_no_owner_dependency_and_matches_existing_encoder():
    root = Path(__file__).resolve().parents[1]
    profiles = []
    for part in (1, 2, 3):
        path = root / f"BackEnd/app/Database/Notebook/ViBioMIR_Qwen3_06B_Part{part}_T4x2.ipynb"
        notebook = json.loads(path.read_text())
        namespace = {}
        exec(notebook["cells"][1]["source"], namespace)
        profiles.append(runtime.encoder_profile(namespace["CONFIG"]))
        if part == 3:
            assert notebook["metadata"]["kaggle"]["dataSources"] == []
            assert namespace["CONFIG"]["input_root"] == "/kaggle/input"
            assert "1626231" in notebook["cells"][0]["source"].replace(".", "")
    assert profiles[0] == profiles[1] == profiles[2]


@pytest.mark.parametrize("fault", [None, "missing_shard", "duplicate_manifest", "one_gpu"])
def test_shared_part3_preflight_works_with_another_accounts_dataset(tmp_path, monkeypatch, fault):
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / "BackEnd/app/Database/Notebook/ViBioMIR_Qwen3_06B_Part3_T4x2.ipynb").read_text())
    namespace = {}
    exec(notebook["cells"][1]["source"], namespace)
    namespace["CONFIG"]["input_root"] = str(tmp_path)
    dataset = tmp_path / "datasets" / "another-friend" / "my-custom-dataset" / "1"
    dataset.mkdir(parents=True)
    manifest = root / "artifacts/vibiomir-qwen3-3parts-20261024/dataset/source_manifest.json"
    (dataset / manifest.name).write_bytes(manifest.read_bytes())
    for name in ("chunks-04.jsonl.zst", "chunks-05.jsonl.zst"):
        (dataset / name).touch()
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1 if fault == "one_gpu" else 2)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda index: "Tesla T4")
    if fault == "missing_shard":
        (dataset / "chunks-05.jsonl.zst").unlink()
    if fault == "duplicate_manifest":
        (tmp_path / manifest.name).write_bytes(manifest.read_bytes())
    if fault:
        with pytest.raises((FileNotFoundError, RuntimeError, ValueError)):
            exec(notebook["cells"][2]["source"], namespace)
    else:
        exec(notebook["cells"][2]["source"], namespace)
        assert namespace["source_manifest_path"].parent == dataset
        assert sum(shard["rows"] for shard in namespace["part_shards"]) == 1_626_231


def reader_outputs(tmp_path):
    roots, source = make_outputs(tmp_path)
    source.update(num_parts=2, shards=[dict(part=part, gpu=gpu, rows=1,
                      start_line=(part - 1) * 2 + gpu + 1, end_line=(part - 1) * 2 + gpu + 1)
                      for part in (1, 2) for gpu in (0, 1)])
    for root in roots:
        path = root / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['schema_version'] = 'vibiomir-embedding-v1'
        manifest['source'] = source
        runtime.atomic_json(path, manifest)
    return roots


def test_manifest_reader_ignores_extra_files_and_streams_matching_metadata(tmp_path):
    reader_outputs(tmp_path)
    (tmp_path / 'unrelated.parquet').write_bytes(b'not parquet')
    catalog = reader.discover_outputs(tmp_path, required_parts=(1, 2))
    report = reader.verify_outputs(catalog)
    assert report['passed'] and report['vector_rows_checked'] == 4
    assert report['metadata_rows_sampled'] == 4
    assert report['all_file_checksums_verified']
    assert catalog['full_corpus']
    rows = [row for batch in reader.iter_embedding_batches(catalog, batch_size=1) for row in batch.to_pylist()]
    assert [row['doc_id'] for row in rows] == [1, 2, 3, 4]
    for row in rows:
        assert json.loads(row['payload_json'])['content'] == row['content']


def test_manifest_reader_rejects_missing_or_duplicate_input_parts(tmp_path):
    roots = reader_outputs(tmp_path)
    with pytest.raises(ValueError, match='Add Input'):
        reader.discover_outputs(tmp_path, required_parts=(1, 2, 3))
    duplicate = tmp_path / 'another-version'
    duplicate.mkdir()
    (duplicate / 'manifest.json').write_bytes((roots[0] / 'manifest.json').read_bytes())
    with pytest.raises(ValueError, match='more than once'):
        reader.discover_outputs(tmp_path, required_parts=(1, 2))
