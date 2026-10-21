"""Offline request contracts for dense-only snapshots and native hybrid search."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BackEnd.app.Database.qdrant_db import QdrantManager


class Response:
    def __init__(self, result, status=200):
        self.result, self.status = result, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"HTTP {self.status}")

    def json(self):
        return {"result": self.result, "status": "ok"}


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, deepcopy(kwargs)))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def schema(*, sparse=True, named=False):
    vectors = {"size": 3, "distance": "Cosine", "on_disk": True}
    params = {"vectors": {"gte": vectors} if named else vectors}
    if sparse:
        params["sparse_vectors"] = {"bm25": {"modifier": "idf"}}
    return Response({"config": {"params": params}})


@pytest.fixture(autouse=True)
def clear_configuration(monkeypatch):
    for key in ("QDRANT_URL", "QDRANT_COLLECTION", "QDRANT_API_KEY",
                "QDRANT_DENSE_VECTOR_NAME", "QDRANT_SPARSE_VECTOR_NAME"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def multilingual_query():
    return {
        "original_query": "Điều trị đái tháo đường bằng metformin 500 mg",
        "eng_query": "Treating diabetes with metformin 500 mg",
        "chinese_query": "使用二甲双胍 500 mg 治疗糖尿病",
    }


@pytest.mark.parametrize("method,dense_count", [
    ("query_original_dense", 1), ("query_multilingual_dense", 3),
])
@pytest.mark.parametrize("filtered", [False, True])
def test_multilingual_query_routes_texts_and_keeps_50_per_branch(
    multilingual_query, method, dense_count, filtered,
):
    texts = list(multilingual_query.values())
    embeddings = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    encoded = []

    def encode(batch):
        encoded.append(list(batch))
        return embeddings[:len(batch)]

    points = [{"id": str(i), "score": 1 / (i + 2),
               "payload": {"chunk_id": f"{i}:c:0", "chunk_text": "nguyên văn 中文"}}
              for i in range(100)]
    session = Session(schema(named=True), Response({"points": points}))
    manager = QdrantManager(dense_vector_name="gte", dense_encoder=encode, session=session)
    query_filter = {"must": [{"key": "parent_id", "match": {"value": "7:p:0"}}]} if filtered else None
    with_payload = ["chunk_id", "chunk_text"] if filtered else True
    original = deepcopy((multilingual_query, embeddings, query_filter, manager.bm25_options))

    hits = getattr(manager, method)(multilingual_query, query_filter=query_filter, with_payload=with_payload)

    assert hits == points
    assert encoded == [texts[:dense_count]]
    assert [call[0] for call in session.calls] == ["GET", "POST"]
    assert session.calls[-1][1].endswith("/points/query")
    body = session.calls[-1][2]["json"]
    assert body["query"] == {"rrf": {"k": 2, "weights": [0.5 / dense_count] * dense_count + [0.5 / 3] * 3}}
    assert body["limit"] == 100 and body["with_vector"] is False
    assert body["with_payload"] == with_payload
    branches = body["prefetch"]
    assert len(branches) == dense_count + 3
    assert all(branch["limit"] == 50 for branch in branches)
    assert [branch["query"] for branch in branches[:dense_count]] == embeddings[:dense_count]
    assert all(branch["using"] == "gte" for branch in branches[:dense_count])
    assert [branch["query"]["text"] for branch in branches[dense_count:]] == texts
    assert all(branch["using"] == "bm25" and branch["query"]["model"] == "qdrant/bm25"
               and branch["query"]["options"] == manager.bm25_options for branch in branches[dense_count:])
    if filtered:
        assert body["filter"] == query_filter
        assert all(branch["filter"] == query_filter for branch in branches)
    else:
        assert "filter" not in body and all("filter" not in branch for branch in branches)
    assert (multilingual_query, embeddings, query_filter, manager.bm25_options) == original


@pytest.mark.parametrize("method", ["query_original_dense", "query_multilingual_dense"])
@pytest.mark.parametrize("field,value", [
    ("original_query", None), ("eng_query", ""), ("chinese_query", "  "), ("eng_query", 123),
])
def test_multilingual_query_rejects_missing_or_invalid_text_before_encoding(
    multilingual_query, method, field, value,
):
    if value is None:
        del multilingual_query[field]
    else:
        multilingual_query[field] = value
    session = Session()
    manager = QdrantManager(session=session, dense_encoder=lambda _: pytest.fail("Must not encode invalid input"))
    with pytest.raises(ValueError, match="original_query, eng_query and chinese_query"):
        getattr(manager, method)(multilingual_query)
    assert session.calls == []


def test_multilingual_query_requires_configured_encoder(multilingual_query):
    session = Session()
    with pytest.raises(ValueError, match="Configure dense_encoder"):
        QdrantManager(session=session).query_original_dense(multilingual_query)
    assert session.calls == []


@pytest.mark.parametrize('method,dense_count', [('query_original_dense', 1), ('query_multilingual_dense', 3)])
@pytest.mark.parametrize('weight', [0, 0.2, 0.6, 1])
def test_adaptive_rrf_weights_follow_group_and_prefetch_order(multilingual_query, method, dense_count, weight):
    encoded = []

    def encode(texts):
        encoded.append(texts)
        return [[1, 0, 0]] * len(texts)

    session = Session(schema(named=True), Response({'points': []}))
    manager = QdrantManager(session=session, dense_vector_name='gte', dense_encoder=encode)
    getattr(manager, method)(multilingual_query, dense_weight=weight)
    request = session.calls[-1][2]['json']
    weights = request['query']['rrf']['weights']
    dense = [branch for branch in request['prefetch'] if branch['using'] == 'gte']
    lexical = [branch for branch in request['prefetch'] if branch['using'] == 'bm25']
    assert len(dense) == (dense_count if weight > 0 else 0)
    assert len(lexical) == (3 if weight < 1 else 0)
    assert weights == pytest.approx([weight / dense_count] * len(dense) + [(1 - weight) / 3] * len(lexical))
    assert sum(weights[:len(dense)]) == pytest.approx(weight)
    assert sum(weights[len(dense):]) == pytest.approx(1 - weight)
    assert len(encoded) == int(weight > 0)


def test_pure_lexical_query_does_not_need_dense_lookup(multilingual_query):
    session = Session(schema(), Response({'points': []}))
    QdrantManager(session=session).query_original_dense(multilingual_query, dense_weight=0)
    assert len(session.calls[-1][2]['json']['prefetch']) == 3


@pytest.mark.parametrize('method,dense_count', [('query_original_dense', 1), ('query_multilingual_dense', 3)])
@pytest.mark.parametrize('weight', [0, 0.6, 1])
@pytest.mark.parametrize('top_k', [2, 100])
def test_fusion_returns_top_k_independently_of_branch_budgets(multilingual_query, method, dense_count, weight, top_k):
    points = [{'id': number, 'payload': {'doc_id': number}} for number in range(10)]
    session = Session(schema(), Response({'points': points}))
    manager = QdrantManager(session=session, dense_encoder=lambda texts: [[1, 0, 0]] * len(texts))
    result = getattr(manager, method)(multilingual_query, top_k=top_k, branch_limit=7,
                                     dense_weight=weight)
    assert result == points
    body = session.calls[-1][2]['json']
    assert body['limit'] == top_k
    assert all(branch['limit'] == 7 for branch in body['prefetch'])


@pytest.mark.parametrize('weight', [-0.1, 1.1, float('inf'), float('-inf'), 'bad', True])
def test_invalid_adaptive_weight_rejected_before_service_call(multilingual_query, weight):
    session = Session()
    with pytest.raises(ValueError, match='dense_weight'):
        QdrantManager(session=session).query_original_dense(multilingual_query, dense_weight=weight)
    assert not session.calls


def test_multilingual_query_checks_sparse_index_before_encoding(multilingual_query):
    session = Session(schema(sparse=False))
    manager = QdrantManager(session=session, dense_encoder=lambda _: pytest.fail("Must not encode without BM25"))
    with pytest.raises(RuntimeError, match="dense-only"):
        manager.query_multilingual_dense(multilingual_query)
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize("vectors", [[], [[1, 0, 0]], [[1, 0], [1, 0], [1, 0]]])
def test_multilingual_query_rejects_encoder_count_or_dimension_mismatch(multilingual_query, vectors):
    session = Session(schema())
    manager = QdrantManager(session=session, dense_encoder=lambda _: vectors)
    with pytest.raises(ValueError):
        manager.query_multilingual_dense(multilingual_query)
    assert [call[0] for call in session.calls] == ["GET"]


def test_hybrid_uses_unnamed_dense_and_preserves_payload_and_filter():
    points = [{"id": "point-1", "score": 0.75,
               "payload": {"chunk_id": "7:c:0", "doc_id": 7, "chunk_text": "nguồn 中文"}}]
    session = Session(schema(), Response({"points": points}))
    manager = QdrantManager(session=session)
    dense, sparse = [1, 0, 0], {"indices": [7, 42], "values": [1, 0.5]}
    query_filter = {"must": [{"key": "source_language", "match": {"value": "vi"}}]}
    original = deepcopy((dense, sparse, query_filter))

    assert manager.search(dense, sparse, top_k=2, query_filter=query_filter) == points
    method, url, options = session.calls[-1]
    assert method == "POST" and url.endswith("/sbtc_gte_multilingual/points/query")
    body = options["json"]
    assert body["query"] == {"fusion": "rrf"}
    assert body["limit"] == 2 and body["with_payload"] is True
    assert body["with_vector"] is False
    assert "using" not in body["prefetch"][0]
    assert body["prefetch"][0]["query"] == dense
    assert body["prefetch"][1]["using"] == "bm25"
    assert body["prefetch"][1]["query"] == sparse
    assert body["filter"] == query_filter
    assert all(branch["filter"] == query_filter and branch["limit"] == 100
               for branch in body["prefetch"])
    assert (dense, sparse, query_filter) == original


def test_named_vectors_dbsf_and_large_candidate_budget():
    session = Session(schema(named=True), Response({"points": []}))
    manager = QdrantManager(session=session, dense_vector_name="gte")
    manager.search([1, 0, 0], {"indices": [1], "values": [1]}, top_k=1000,
                   fusion="dbsf", with_payload=["chunk_id", "chunk_text"])
    body = session.calls[-1][2]["json"]
    assert body["query"] == {"fusion": "dbsf"}
    assert body["prefetch"][0]["using"] == "gte"
    assert all(branch["limit"] == 1000 for branch in body["prefetch"])
    assert body["with_payload"] == ["chunk_id", "chunk_text"]


def test_notebook_named_dense_is_detected_without_breaking_legacy_snapshot():
    params = schema(named=True)
    params.result["config"]["params"]["vectors"]["dense"] = params.result["config"]["params"]["vectors"].pop("gte")
    session = Session(params, Response({"points": []}))
    manager = QdrantManager(session=session)
    manager.search_dense([1, 0, 0])
    assert session.calls[-1][2]["json"]["using"] == "dense"


def test_manifest_native_bm25_text_uses_exported_options(tmp_path):
    manifest = {"complete": True, "collection": "restored_hybrid", "vector_schema": {
        "dense": "gte", "sparse": "bm25", "bm25_options": {"tokenizer": "multilingual", "stopwords": {}},
    }}
    path = tmp_path / "snapshot_manifest.json"
    path.write_text(json.dumps(manifest))
    session = Session(schema(named=True), Response({"points": []}))
    with QdrantManager.from_manifest(path, session=session) as manager:
        assert manager.search_text([1, 0, 0], "Không sốt 中文 metformin") == []
    body = session.calls[-1][2]["json"]
    assert "/restored_hybrid/" in session.calls[-1][1]
    assert body["prefetch"][1]["query"] == {
        "text": "Không sốt 中文 metformin", "model": "qdrant/bm25",
        "options": manifest["vector_schema"]["bm25_options"],
    }
    manifest["complete"] = False
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="incomplete"):
        QdrantManager.from_manifest(path, session=session)


def test_dense_snapshot_works_and_hybrid_never_silently_falls_back():
    session = Session(schema(sparse=False), Response({"points": []}), Response({"points": []}))
    manager = QdrantManager(session=session)
    assert manager.search_dense([1, 0, 0]) == []
    with pytest.raises(RuntimeError, match="dense-only"):
        manager.search([1, 0, 0], {"indices": [1], "values": [1]})
    assert manager.search_dense([1, 0, 0]) == []
    assert [call[0] for call in session.calls] == ["GET", "POST", "POST"]
    assert "prefetch" not in session.calls[-1][2]["json"]


def test_refresh_detects_new_sparse_schema():
    session = Session(schema(sparse=False), schema(), Response({"points": []}))
    manager = QdrantManager(session=session)
    with pytest.raises(RuntimeError, match="sparse"):
        manager.search([1, 0, 0])
    manager.refresh_collection()
    assert manager.search([1, 0, 0], {"indices": [1], "values": [1]}) == []


@pytest.mark.parametrize("vector", [[1, 0], [float("nan"), 0, 1], [float("inf"), 0, 1], [0, 0, 0]])
def test_invalid_dense_vector_does_not_reach_query_endpoint(vector):
    session = Session(schema())
    manager = QdrantManager(session=session)
    with pytest.raises(ValueError):
        manager.search_dense(vector)
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize("vector", [
    None,
    {"indices": [], "values": []},
    {"indices": [1, 2], "values": [1]},
    {"indices": [1, 1], "values": [1, 2]},
    {"indices": [-1], "values": [1]},
    {"indices": [2**32], "values": [1]},
    {"indices": [1.5], "values": [1]},
    {"indices": [1], "values": [float("nan")]},
    {"indices": [1], "values": [0]},
])
def test_invalid_sparse_vector_is_not_sent(vector):
    session = Session(schema())
    manager = QdrantManager(session=session)
    with pytest.raises(ValueError):
        manager.search([1, 0, 0], vector)
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize("options", [{"top_k": 0}, {"top_k": 10, "prefetch_limit": 5}, {"fusion": "sum"}])
def test_invalid_search_options_do_not_connect(options):
    session = Session()
    manager = QdrantManager(session=session)
    with pytest.raises(ValueError):
        manager.search([1, 0, 0], {"indices": [1], "values": [1]}, **options)
    assert session.calls == []


def test_missing_named_vector_configuration_is_reported():
    manager = QdrantManager(session=Session(schema(named=True)))
    with pytest.raises(ValueError, match="named vectors"):
        manager.search_dense([1, 0, 0])
    manager = QdrantManager(session=Session(schema()), dense_vector_name="wrong")
    with pytest.raises(ValueError, match="not configured"):
        manager.search_dense([1, 0, 0])


def test_http_failure_is_propagated_instead_of_returning_empty_hits():
    session = Session(schema(), Response(None, status=503))
    manager = QdrantManager(session=session)
    with pytest.raises(requests.HTTPError, match="503"):
        manager.search_dense([1, 0, 0])


def test_environment_timeout_auth_and_session_ownership(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:16333/")
    monkeypatch.setenv("QDRANT_COLLECTION", "collection name")
    monkeypatch.setenv("QDRANT_API_KEY", "test-placeholder")
    session = Session(schema(sparse=False), Response({"points": []}))
    with QdrantManager(session=session, timeout=7) as manager:
        assert session.calls == []
        manager.search_dense([1, 0, 0], with_payload=False)
    assert not session.closed
    assert session.calls[0][1] == "http://127.0.0.1:16333/collections/collection%20name"
    assert session.calls[0][2]["headers"] == {"api-key": "test-placeholder"}
    assert session.calls[0][2]["timeout"] == 7
    owned = Session()
    monkeypatch.setattr(requests, "Session", lambda: owned)
    with QdrantManager():
        pass
    assert owned.closed and owned.calls == []
