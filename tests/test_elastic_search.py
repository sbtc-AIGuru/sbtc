import json
import os
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from elastic_transport import ApiResponseMeta, NodeConfig, ObjectApiResponse
from elasticsearch import Elasticsearch

from BackEnd.app.Database import elastic_search as es


def write_records(path, records):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    return path


def record(doc_id, language="en", content="No diabetes without insulin deficiency."):
    return {"doc_id": doc_id, "chunk_id": f"{doc_id}:chunk:00000", "language": language,
            "content": content, "token_count": 8, "content_origin": "hf_sqlite"}


def test_reader_is_lazy_and_stops_before_invalid_tail(tmp_path):
    path = write_records(tmp_path / "sample.jsonl", [record(1)])
    with path.open("a") as source:
        source.write("\n{broken\n")
    assert list(es.read_jsonl(path, limit=1)) == [record(1)]
    with pytest.raises(ValueError, match=r"sample.jsonl:3"):
        list(es.read_jsonl(path))
    with pytest.raises(ValueError, match="limit"):
        list(es.read_jsonl(path, 0))


@pytest.mark.parametrize("bad", [{"language": "fr"}, {"content": " "}, {"chunk_id": ""}])
def test_reader_rejects_bad_records(tmp_path, bad):
    path = write_records(tmp_path / "bad.jsonl", [{**record(1), **bad}])
    with pytest.raises(ValueError, match=r"bad.jsonl:1"):
        list(es.read_jsonl(path))


def test_actions_keep_original_route_language_and_have_stable_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "prepare_text", lambda text, lang: f"prepared-{lang}")
    rows = [record(7, lang, f"original {lang}") for lang in es.LANGUAGES]
    # Distinct chunks within one document must never overwrite each other.
    for lang, row in zip(es.LANGUAGES, rows):
        row["chunk_id"] += lang
    path = write_records(tmp_path / "multi.jsonl", rows)
    actions = list(es.iter_actions(path, "test"))
    assert actions == list(es.iter_actions(path, "test"))
    assert len({item["_id"] for item in actions}) == 3
    for row, action in zip(rows, actions):
        payload = action["_source"]
        assert action["_op_type"] == "index"
        assert action["_index"] == "test"
        assert payload["doc_id"] == "7"
        assert payload["content"] == row["content"]
        assert payload["content_origin"] == row["content_origin"]
        assert payload["language"] == payload["lang"] == row["language"]
        assert [key for key in payload if key.startswith("content_") and key != "content_origin"] == [
            f"content_{row['language']}"
        ]
        assert payload[f"content_{row['language']}"] == f"prepared-{row['language']}"
    changed = record(8)
    changed["chunk_id"] = rows[0]["chunk_id"]
    path = write_records(path, [changed])
    assert next(es.iter_actions(path))["_id"] != actions[0]["_id"]


def test_create_index_never_modifies_existing_index():
    indices = Mock()
    indices.exists.return_value = False
    es.create_index(SimpleNamespace(indices=indices), "test")
    indices.create.assert_called_once_with(index="test", **es.index_definition())
    indices.reset_mock()
    indices.exists.return_value = True
    mapping = es.index_definition()["mappings"]
    indices.get_mapping.return_value = {"test": {"mappings": mapping}}
    es.create_index(SimpleNamespace(indices=indices), "test")
    indices.create.assert_not_called()
    indices.delete.assert_not_called()
    mapping["properties"]["lang"]["type"] = "text"
    with pytest.raises(ValueError, match="Incompatible mapping"):
        es.create_index(SimpleNamespace(indices=indices), "test")
    indices.delete.assert_not_called()


def test_streaming_bulk_batches_retries_429_and_reports_failure(tmp_path, monkeypatch, capsys):
    path = write_records(tmp_path / "bulk.jsonl", [record(i) for i in range(3)])
    calls = []
    sleeps = []

    def fake_bulk(self, *, operations, **kwargs):
        headers = [json.loads(line)["index"] for line in operations[::2]]
        calls.append(headers)
        statuses = [429, 400] if len(calls) == 1 else [201] * len(headers)
        items = []
        for header, status in zip(headers, statuses):
            result = {"_id": header["_id"], "status": status}
            if status >= 400:
                result["error"] = {"type": "temporary" if status == 429 else "bad_record"}
            items.append({"index": result})
        meta = ApiResponseMeta(status=200, http_version="1.1", headers={}, duration=0,
                               node=NodeConfig("http", "localhost", 9200))
        return ObjectApiResponse(body={"items": items}, meta=meta)

    monkeypatch.setattr(Elasticsearch, "bulk", fake_bulk)
    monkeypatch.setattr("elasticsearch.helpers.actions.time.sleep", sleeps.append)
    with Elasticsearch("http://localhost:9200") as client:
        assert es.bulk_index(client, path, batch_size=2) == (2, 1)
    assert [len(batch) for batch in calls] == [2, 1, 1]
    assert calls[1][0]["_id"] == calls[0][0]["_id"]
    assert sleeps == [2]
    output = capsys.readouterr()
    assert "success=2 failed=1" in output.out
    assert "docs/s" in output.out
    assert "status=400 type=bad_record" in output.err


def test_search_uses_same_preprocessing_and_language_filter(monkeypatch):
    prepare = Mock(return_value="suy_thận")
    monkeypatch.setattr(es, "prepare_text", prepare)
    client = Mock()
    client.search.return_value = {"hits": {"hits": [{"_id": "found"}]}}
    assert es.search_bm25("suy thận", "vi", 3, client=client, index="test") == [{"_id": "found"}]
    prepare.assert_called_once_with("suy thận", "vi")
    request = client.search.call_args.kwargs
    assert request["size"] == 3
    assert request["query"]["bool"]["must"] == [{"match": {"content_vi": "suy_thận"}}]
    assert request["query"]["bool"]["filter"] == [{"term": {"lang": "vi"}}]


def test_actual_vietnamese_and_chinese_preprocessing():
    pytest.importorskip("pyvi")
    pytest.importorskip("opencc")
    text = es.prepare_text("Bệnh nhân không bị suy thận.", "vi")
    assert "_" in text
    assert "không" in text
    assert es.prepare_text("醫生檢查腎功能", "zh") == "医生检查肾功能"
    assert es.prepare_text("No diabetes without insulin.", "en") == "No diabetes without insulin."


def test_parallel_preprocessing_matches_sequential_and_respects_limit(tmp_path):
    rows = [record(1, 'vi', 'Bệnh nhân không bị suy thận.'),
            record(2), record(3, 'zh', '醫生檢查腎功能。')]
    path = write_records(tmp_path / 'parallel.jsonl', rows)
    with path.open('a') as source:
        source.write('{invalid tail\n')
    sequential = list(es.iter_actions(path, 'test', limit=3))
    assert list(es.iter_actions(path, 'test', limit=3, workers=2)) == sequential


def test_source_sample_uses_observed_schema():
    if not es.DATA_PATH.is_file():
        pytest.skip("Local ViBioMIR corpus is unavailable")
    actions = list(es.iter_actions(es.DATA_PATH, limit=3))
    assert len(actions) == 3
    assert all(action["_source"]["lang"] == "en" for action in actions)
    assert all(action["_source"]["content_en"] == action["_source"]["content"] for action in actions)


@pytest.mark.skipif(not os.getenv("ELASTICSEARCH_TEST_URL"), reason="No dedicated test Elasticsearch URL configured")
def test_live_analyzers_indexing_retrieval_and_rerun(tmp_path, monkeypatch):
    pytest.importorskip("pyvi")
    pytest.importorskip("opencc")
    monkeypatch.setenv("ELASTICSEARCH_URL", os.environ["ELASTICSEARCH_TEST_URL"])
    index = f"vibiomir-test-{uuid4().hex}"
    rows = [
        record(1, "vi", "Bệnh nhân không bị suy thận, cần xét nghiệm chức năng thận."),
        record(2, "en", "No diabetes without insulin deficiency."),
        record(3, "zh", "医生检查肾功能，患者没有糖尿病。"),
        record(4, "zh", "醫生檢查腎功能，患者沒有糖尿病。"),
    ]
    path = write_records(tmp_path / "sample.jsonl", rows)
    with es.connect_elasticsearch() as client:
        es.create_index(client, index)
        tokens = es.check_analyzers(client, index)
        print(json.dumps(tokens, ensure_ascii=False))
        assert es.bulk_index(client, path, index=index, batch_size=2, workers=2) == (4, 0)
        es.create_index(client, index)
        assert es.bulk_index(client, path, index=index, batch_size=2) == (4, 0)
        client.indices.refresh(index=index)
        assert client.count(index=index)["count"] == 4
        for lang, query in [("vi", "suy thận"), ("en", "insulin deficiency"), ("zh", "腎功能")]:
            hits = es.search_bm25(query, lang, client=client, index=index)
            assert hits
            assert all(hit["_source"]["lang"] == lang for hit in hits)
            if lang == "zh":
                assert {hit["_source"]["doc_id"] for hit in hits} == {"3", "4"}
    # Leave the tiny, uniquely named index for inspection; never delete an existing index.
