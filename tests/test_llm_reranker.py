import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from BackEnd.app.LLM import llm_as_reranker


@pytest.fixture
def candidates():
    return {
        "id": 7,
        "relevant_docs": ["001", "2"],
        "relevant_chunks": [
            {"doc_id": "001", "chunk_text": "Nguồn gốc\n中文。"},
            {"doc_id": "2", "chunk_text": "Text with \"quotes\" and \\slashes."},
        ],
    }


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setattr(llm_as_reranker, "MODEL_NAME", "test-reranker")


def make_client(content, *, finish_reason="stop", refusal=None):
    client = Mock()
    message = SimpleNamespace(content=content, refusal=refusal)
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
    )
    return client


@pytest.mark.parametrize("as_json", [False, True])
def test_preserves_model_ranking_and_source_text(candidates, as_json):
    original = deepcopy(candidates)
    ranked = deepcopy(candidates)
    ranked["relevant_chunks"].reverse()
    client = make_client(json.dumps(ranked, ensure_ascii=False))
    documents = json.dumps(candidates) if as_json else candidates

    assert llm_as_reranker.rerank("Câu hỏi", documents, client=client) == ranked
    assert candidates == original
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "test-reranker"
    assert request["messages"][0] == {"role": "system", "content": llm_as_reranker.SYSTEM_PROMPT}
    assert json.loads(request["messages"][1]["content"]) == {
        "query": "Câu hỏi", "documents": candidates,
    }


@pytest.mark.parametrize("content", [
    "```json\n{}\n```", "Here is the result: {}", "{} extra", "{", "{}", "[]",
    '{"id":true,"relevant_docs":[],"relevant_chunks":[]}',
    '{"id":7,"relevant_docs":[],"relevant_chunks":[],"score":1}',
])
def test_rejects_prose_and_wrong_schema(candidates, content):
    with pytest.raises(ValueError, match="only JSON"):
        llm_as_reranker.rerank("query", candidates, client=make_client(content))


@pytest.mark.parametrize("change", [
    "record_id", "missing_record", "extra_doc", "missing_doc", "duplicate_doc",
    "numeric_doc_id", "changed_text", "changed_chunk_doc", "missing_chunk", "extra_chunk",
])
def test_rejects_changed_candidates(candidates, change):
    ranked = deepcopy(candidates)
    item = ranked
    if change == "record_id":
        item["id"] = 8
    elif change == "missing_record":
        ranked.clear()
    elif change == "extra_doc":
        item["relevant_docs"].append("unknown")
    elif change == "missing_doc":
        item["relevant_docs"].pop()
    elif change == "duplicate_doc":
        item["relevant_docs"] = ["001", "001"]
    elif change == "numeric_doc_id":
        item["relevant_docs"][0] = 1
    elif change == "changed_text":
        item["relevant_chunks"][0]["chunk_text"] += "changed"
    elif change == "changed_chunk_doc":
        item["relevant_chunks"][0]["doc_id"] = "2"
    elif change == "missing_chunk":
        item["relevant_chunks"].pop()
    else:
        item["relevant_chunks"].append(deepcopy(item["relevant_chunks"][0]))
    with pytest.raises(ValueError):
        llm_as_reranker.rerank("query", candidates, client=make_client(json.dumps(ranked)))


def test_rejects_reordered_documents(candidates):
    ranked = deepcopy(candidates)
    ranked["relevant_docs"].reverse()
    with pytest.raises(ValueError, match="id or relevant_docs"):
        llm_as_reranker.rerank("query", candidates, client=make_client(json.dumps(ranked)))


@pytest.mark.parametrize("content,finish_reason,refusal", [
    (None, "stop", None), ("", "stop", None), ("[]", "length", None),
    ("[]", "content_filter", None), ("[]", "stop", "refused"),
])
def test_rejects_incomplete_or_refused_response(candidates, content, finish_reason, refusal):
    client = make_client(content, finish_reason=finish_reason, refusal=refusal)
    with pytest.raises(ValueError, match="complete JSON"):
        llm_as_reranker.rerank("query", candidates, client=client)


@pytest.mark.parametrize("documents", [
    {"id": 1, "relevant_docs": [], "relevant_chunks": []},
    {"id": 1, "relevant_docs": ["doc_id1"], "relevant_chunks": []},
])
def test_empty_candidates_do_not_call_model(documents):
    client = Mock()
    assert llm_as_reranker.rerank("query", documents, client=client) == documents
    client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("documents", ["invalid", {}, [], [{"id": "1"}], None])
def test_rejects_bad_input_before_calling_model(documents):
    client = Mock()
    with pytest.raises(ValueError, match="documents must be"):
        llm_as_reranker.rerank("query", documents, client=client)
    client.chat.completions.create.assert_not_called()


def test_ranks_chunks_across_documents_and_preserves_duplicate_occurrences(candidates):
    candidates["relevant_chunks"].append({"doc_id": "001", "chunk_text": "Another chunk"})
    candidates["relevant_chunks"].append(deepcopy(candidates["relevant_chunks"][0]))
    ranked = deepcopy(candidates)
    ranked["relevant_chunks"] = [candidates["relevant_chunks"][i] for i in [1, 3, 2, 0]]
    assert llm_as_reranker.rerank("query", candidates, client=make_client(json.dumps(ranked))) == ranked


@pytest.mark.parametrize("query", ["", "  ", None])
def test_rejects_empty_query(candidates, query):
    with pytest.raises(ValueError, match="query must be"):
        llm_as_reranker.rerank(query, candidates, client=Mock())


def test_uses_environment_configuration_and_closes_owned_client(candidates, monkeypatch):
    monkeypatch.setattr(llm_as_reranker, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_as_reranker, "LLM_BASE_URL", "http://localhost:8000/v1")
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=make_client(json.dumps(candidates)))
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(llm_as_reranker, "OpenAI", factory)

    assert llm_as_reranker.rerank("query", candidates) == candidates
    factory.assert_called_once_with(
        api_key="test-key", base_url="http://localhost:8000/v1", timeout=120.0,
    )
    factory.return_value.__exit__.assert_called_once()


def test_missing_configuration(candidates, monkeypatch):
    monkeypatch.setattr(llm_as_reranker, "MODEL_NAME", None)
    with pytest.raises(ValueError, match="MODEL_NAME"):
        llm_as_reranker.rerank("query", candidates, client=Mock())
    monkeypatch.setattr(llm_as_reranker, "MODEL_NAME", "test-reranker")
    monkeypatch.setattr(llm_as_reranker, "LLM_API_KEY", None)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        llm_as_reranker.rerank("query", candidates)
