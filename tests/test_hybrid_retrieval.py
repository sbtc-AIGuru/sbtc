import io
import json
from unittest.mock import Mock

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from BackEnd.app import pipeline
from BackEnd.app.api.main import create_app
from BackEnd.app.Database.elastic_search import index_definition
from BackEnd.app.Retrieval.hybrid import HybridRetriever, elastic_filter, normalize_hit, weighted_rrf
from BackEnd.app.Retrieval.query_inputs import QWEN_CONFIG, combine_query_files
from BackEnd.app.Retrieval.utils import sha_file
from test_api import wait_status


def hit(chunk, doc=1, text="source", elastic=False):
    payload = {"chunk_id": chunk, "doc_id": str(doc) if elastic else doc, "content": text}
    return normalize_hit({"_id": "sha-" + chunk, "_source": payload} if elastic else
                         {"id": "uuid-" + chunk, "payload": payload}, elastic=elastic)


def test_rrf_preserves_native_rank_weights_and_joins_chunk_ids():
    a, b, c = hit("a"), hit("b", 2), hit("c", 3)
    result = weighted_rrf([[a, b], [hit("b", 2, elastic=True), c]], [.75, .25], 3)
    assert [row["payload"]["chunk_id"] for row in result] == ["b", "a", "c"]
    expected = np.float32(np.float32(1) / (np.float32(2) / np.float32(.75) + np.float32(1)) +
                          np.float32(1) / (np.float32(1) / np.float32(.25) + np.float32(1)))
    assert result[0]["score"] == float(expected)
    assert result[0]["payload"]["chunk_text"] == "source"
    assert len(weighted_rrf([[a], [b]], [1, 0], 10)) == 1
    with pytest.raises(ValueError, match="Conflicting"):
        weighted_rrf([[a], [hit("a", 9)]], [.5, .5], 10)


@pytest.mark.parametrize("multilingual,dense_count", [(False, 1), (True, 3)])
@pytest.mark.parametrize("weight", [0, .35, 1])
def test_split_backends_languages_limits_and_zero_weight(monkeypatch, multilingual, dense_count, weight):
    qdrant, elastic = Mock(), Mock()
    qdrant.dense_encoder.side_effect = lambda texts: [[1., 0.] for text in texts]
    qdrant.search_dense.return_value = [{"id": "uuid", "payload": {"chunk_id": "a", "doc_id": 1, "content": "source"}}]
    searches = Mock(return_value=[{"_id": "sha", "_source": {"chunk_id": "a", "doc_id": "1", "content": "source"}}])
    fusion = Mock(wraps=weighted_rrf)
    monkeypatch.setattr("BackEnd.app.Retrieval.hybrid.weighted_rrf", fusion)
    monkeypatch.setattr("BackEnd.app.Retrieval.hybrid.search_bm25", searches)
    query = dict(zip(("original_query", "eng_query", "chinese_query"), ("VI", "EN", "ZH")))
    result = HybridRetriever(qdrant, elastic, "test").query(query, multilingual_dense=multilingual,
        top_k=2, branch_limit=7, dense_weight=weight)
    assert len(result) == 1
    assert fusion.call_args.args[1] == pytest.approx(
        ([weight / dense_count] * dense_count if weight else []) +
        ([(1 - weight) / 3] * 3 if weight < 1 else []))
    assert qdrant.search_dense.call_count == (dense_count if weight else 0)
    assert searches.call_count == (3 if weight < 1 else 0)
    assert [call.args[:3] for call in searches.call_args_list] == (
        [("VI", "vi", 7), ("EN", "en", 7), ("ZH", "zh", 7)] if weight < 1 else [])
    for call in qdrant.search_dense.call_args_list:
        assert call.kwargs["top_k"] == 7
    if weight:
        assert qdrant.dense_encoder.call_args.args[0] == (["VI", "EN", "ZH"] if multilingual else ["VI"])


def test_filters_preserve_boolean_semantics_and_reject_unindexed_fields():
    result = elastic_filter({"must": [{"key": "doc_id", "match": {"any": [7, 8]}}],
                             "should": [{"key": "lang", "match": {"value": "vi"}}]})
    assert result["bool"]["must"] == [{"terms": {"doc_id": ["7", "8"]}}]
    assert result["bool"]["minimum_should_match"] == 1
    with pytest.raises(ValueError, match="supports match"):
        elastic_filter({"must": [{"key": "content_origin", "match": {"value": "source"}}]})


@pytest.mark.parametrize("weight", [0, .2, .85, 1, "ignored"])
def test_dense_only_fuses_three_languages_equally_without_elasticsearch(monkeypatch, weight):
    qdrant = Mock()
    qdrant.dense_encoder.return_value = [[1, 0], [0, 1], [.5, .5]]
    qdrant.search_dense.side_effect = [
        [{"id": "vi", "payload": {"chunk_id": "vi", "doc_id": 1, "content": "VI"}}],
        [{"id": "en", "payload": {"chunk_id": "en", "doc_id": 2, "content": "EN"}}],
        [{"id": "zh", "payload": {"chunk_id": "zh", "doc_id": 3, "content": "ZH"}}],
    ]
    search = Mock(side_effect=AssertionError("Dense-only must not search BM25"))
    monkeypatch.setattr("BackEnd.app.Retrieval.hybrid.search_bm25", search)
    query_filter = {"has_id": ["vi", "en", "zh"]}  # Qdrant-only filter must not pass through ES translation.
    result = HybridRetriever(qdrant, None, "unused").query(
        dict(zip(("original_query", "eng_query", "chinese_query"), ("VI", "EN", "ZH"))),
        multilingual_dense=True, include_bm25=False, top_k=200, branch_limit=100,
        dense_weight=weight, query_filter=query_filter)
    assert [item["payload"]["chunk_id"] for item in result] == ["vi", "en", "zh"]
    assert [item["score"] for item in result] == pytest.approx([.25] * 3)
    qdrant.dense_encoder.assert_called_once_with(["VI", "EN", "ZH"])
    assert qdrant.search_dense.call_count == 3
    assert all(call.kwargs["query_filter"] == query_filter for call in qdrant.search_dense.call_args_list)
    search.assert_not_called()


def qwen_files(tmp_path):
    text = tmp_path / "text.parquet"
    pq.write_table(pa.table({"id": [9, 2], "query": ["suy thận", "đái tháo đường"],
        "english": ["kidney failure", "diabetes"], "chinese": ["肾功能", "糖尿病"],
        "dense_weight": [.35, .75]}), text)
    table = pq.read_table(text)
    for column in ("query", "english", "chinese"):
        table = table.set_column(table.schema.get_field_index(column), column,
                                pa.array([[1.] + [0.] * 1023] * 2, type=pa.list_(pa.float16(), 1024)))
    meta = {"encoder": QWEN_CONFIG, "replaced_columns": ["query", "english", "chinese"],
            "rows": 2, "source_sha256": sha_file(text)}
    vectors = tmp_path / "vectors.parquet"
    pq.write_table(table.replace_schema_metadata({b"query_embedding": json.dumps(meta).encode()}), vectors)
    return vectors, text


def test_qwen_join_retains_text_vectors_weights_and_rejects_wrong_source(tmp_path):
    vectors, text = qwen_files(tmp_path)
    combined = combine_query_files(vectors, text, tmp_path / "combined.parquet")
    table = pq.read_table(combined)
    assert table["id"].to_pylist() == [9, 2]
    assert table["dense_weight"].to_pylist() == [.35, .75]
    assert table["query"].equals(pq.read_table(text)["query"])
    assert pipeline._embedding_columns(table.schema) == [*pipeline.VECTOR_COLUMNS.values(), "query_sha256"]
    pq.write_table(pq.read_table(text).slice(1), tmp_path / "wrong.parquet")
    with pytest.raises(ValueError, match="source_sha256"):
        combine_query_files(vectors, tmp_path / "wrong.parquet", tmp_path / "bad.parquet")
    assert not (tmp_path / "bad.parquet").exists()


@pytest.mark.parametrize("search_mode", ["3-branch", "6-branch"])
def test_qwen_multipart_api_runs_real_pipeline_and_downloads_zip(tmp_path, search_mode):
    import zipfile
    vectors, text = qwen_files(tmp_path)
    elastic = Mock()
    elastic.indices.get_mapping.return_value = {"test": {"mappings": index_definition()["mappings"]}}
    elastic.search.return_value = {"hits": {"hits": [{"_id": "sha", "_source": {
        "chunk_id": "a", "doc_id": "7", "content": "Original source"}}]}}
    managers = []

    def factory(encoder):
        manager = Mock(dense_encoder=encoder)
        manager.search_dense.return_value = [{"id": "uuid", "payload": {
            "chunk_id": "a", "doc_id": 7, "content": "Original source"}}]
        managers.append(manager)
        return manager

    elastic_factory = Mock(return_value=elastic)
    if search_mode == "3-branch":
        elastic_factory.side_effect = AssertionError("Elasticsearch must not be connected")
    options = {"qdrant_factory": factory, "elasticsearch_factory": elastic_factory, "resume_tag": "qwen-v1"}
    with TestClient(create_app(jobs_dir=tmp_path / "jobs", pipeline_options=options)) as client:
        files = {"file": ("vectors.parquet", vectors.read_bytes()), "query_file": ("text.parquet", text.read_bytes())}
        response = client.post("/api/jobs", files=files, data={"search_mode": search_mode, "rerank": "false"})
        assert response.status_code == 202, response.text
        job = wait_status(client, response.json()["id"], {"completed", "failed"})
        assert job["status"] == "completed", job
        with zipfile.ZipFile(io.BytesIO(client.get(job["download_url"]).content)) as archive:
            rows = json.loads(archive.read("output.json"))
        assert [row["id"] for row in rows] == [9, 2]
        assert all(row["relevant_docs"] == [7] for row in rows)
        assert elastic.search.call_count == (0 if search_mode == "3-branch" else 6)
        if search_mode == "3-branch":
            elastic_factory.assert_not_called()
        assert sum(manager.search_dense.call_count for manager in managers) == 6
