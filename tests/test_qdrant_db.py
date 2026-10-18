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
