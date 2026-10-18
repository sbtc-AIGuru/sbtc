"""Small real Parquet/SQL round trips with mocked Qdrant REST and LLM transport."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Lock
from threading import Event
import time
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import requests
from sqlalchemy import create_engine, event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BackEnd.app import pipeline
from BackEnd.app.Database.postgre_db import PostgreManager
from BackEnd.app.Database.qdrant_db import QdrantManager
from BackEnd.app.LLM import llm_as_reranker


def write_queries(path, identifiers=(30, 10, 20), **changed):
    values = {"id": list(identifiers), "query": [f"VI {i}" for i in identifiers],
              "english": [f"EN {i}" for i in identifiers],
              "chinese": [f"中文 {i}" for i in identifiers]}
    values.update(changed)
    pq.write_table(pa.table(values), path)
    return path


def point(chunk_id, doc_id=1, text="Source text 中文。", **extra):
    return {"id": "uuid-is-not-a-chunk-id", "score": 0.8,
            "payload": {"chunk_id": chunk_id, "doc_id": doc_id, "chunk_text": text, **extra}}


class Response:
    def __init__(self, result):
        self.result = result

    def raise_for_status(self):
        pass

    def json(self):
        return {"result": self.result}


class Transport:
    def __init__(self, points, failures=()):
        self.points = points
        self.failures = set(failures)
        self.calls, self.completed = [], []
        self.closed = False
        self.lock = Lock()

    def request(self, method, url, **options):
        if method == "GET":
            return Response({"config": {"params": {
                "vectors": {"dense": {"size": 3}}, "sparse_vectors": {"bm25": {}},
            }}})
        body = deepcopy(options["json"])
        identifier = int(body["prefetch"][1]["query"]["text"].split()[-1])
        with self.lock:
            self.calls.append(body)
        if identifier in self.failures:
            raise requests.Timeout("private connection information must not reach the error file")
        # Deliberately finish the first input last.
        time.sleep(0.03 if identifier == 30 else 0.001)
        with self.lock:
            self.completed.append(identifier)
        return Response({"points": deepcopy(self.points.get(identifier, []))})

    def close(self):
        self.closed = True


def factory(transport, managers):
    def create(encoder):
        manager = QdrantManager("http://fixture", dense_encoder=encoder, session=transport)
        managers.append(manager)
        return manager
    return create


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(llm_as_reranker, "MODEL_NAME", "fixture-open-model")
    client = Mock()

    def complete(**options):
        request = json.loads(options["messages"][1]["content"])
        result = request["documents"]
        result["relevant_chunks"].reverse()
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                refusal=None, content=json.dumps(result, ensure_ascii=False),
            ),
        )])

    client.chat.completions.create.side_effect = complete
    return client


@pytest.fixture
def database():
    manager = PostgreManager(engine=create_engine("sqlite://"))
    manager.init_db()
    manager.add_document({
        "doc_id": 1, "url": "https://source.invalid/1", "status": "ok",
        "parents": [{"parent_id": "1:p:0", "start_char": 0, "end_char": 100}],
        "children": [{"chunk_id": "1:c:0", "doc_id": 1, "parent_id": "1:p:0",
                      "chunk_order": 0, "start_char": 0, "end_char": 20,
                      "chunk_text": "Original source\n中文。"}],
    })
    yield manager
    manager.close()


def arguments(transport, llm, **extra):
    return {"dense_encoder": lambda texts: [[1, 0, 0] for _ in texts],
            "qdrant_factory": factory(transport, []), "llm_client": llm, **extra}


def test_end_to_end_four_branches_hydration_order_rerank_json_zip(tmp_path, database, llm):
    path = write_queries(tmp_path / "translated.parquet")
    missing = point("1:c:0")
    del missing["payload"]["doc_id"]
    del missing["payload"]["chunk_text"]
    transport = Transport({30: [missing, point("2:c:1", 2, "Second source.")],
                           10: [missing], 20: []})
    output, archive = tmp_path / "submission.json", tmp_path / "submission.zip"
    encode_calls, sql_calls = [], []

    def encode(texts):
        encode_calls.append(texts)
        return [[1, 0, 0] for _ in texts]

    event.listen(database.engine, "before_cursor_execute",
                 lambda *args: sql_calls.append(args[2]))
    result = pipeline.run_pipeline(
        path, output, zip_path=archive, batch_size=3, workers=3, llm_workers=2,
        **arguments(transport, llm, dense_encoder=encode, postgres_manager=database),
    )
    assert encode_calls == [["VI 30", "VI 10", "VI 20"]]
    assert transport.completed[-1] == 30
    assert [item["id"] for item in result] == [30, 10, 20]
    assert result[0] == {
        "id": 30, "relevant_docs": ["1", "2"],
        "relevant_chunks": [{"doc_id": "2", "chunk_text": "Second source."},
                            {"doc_id": "1", "chunk_text": "Original source\n中文。"}],
    }
    assert result[2] == {"id": 20, "relevant_docs": [], "relevant_chunks": []}
    assert len(sql_calls) == 1
    assert llm.chat.completions.create.call_count == 2
    for body in transport.calls:
        assert len(body["prefetch"]) == 4
        assert body["prefetch"][0]["query"] == [1, 0, 0]
        assert [p["query"]["text"].split()[0] for p in body["prefetch"][1:]] == ["VI", "EN", "中文"]
        assert body["query"] == {"fusion": "rrf"} and body["limit"] == 100
        assert all(p["limit"] == 50 for p in body["prefetch"])
    assert json.loads(output.read_text()) == result
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.namelist() == ["submission.json"]
        assert json.loads(zipped.read("submission.json")) == result
    journal = [json.loads(line) for line in output.with_suffix(".checkpoint.jsonl").read_text().splitlines()]
    assert journal[1]["chunk_ids"] == ["2:c:1", "1:c:0"]
    assert json.loads(output.with_suffix(".errors.json").read_text()) == []
    # The injected manager still owns its engine and existing interface.
    assert database.get_chunk("1:c:0")["chunk_text"] == "Original source\n中文。"


def test_failures_continue_and_resume_only_failed_row(tmp_path, llm):
    path = write_queries(tmp_path / "queries.parquet")
    transport = Transport({i: [point(f"{i}:c:0", i)] for i in (30, 10, 20)}, failures={10})
    output = tmp_path / "submission.json"
    options = arguments(transport, llm, resume_tag="fixture-v1")
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, output, **options)
    assert error.value.failures == [{"row": 1, "id": 10, "stage": "retrieval", "error_type": "Timeout"}]
    assert not output.exists()
    errors = output.with_suffix(".errors.json").read_text()
    assert "private connection" not in errors
    assert len(transport.calls) == 3
    checkpoint = output.with_suffix(".checkpoint.jsonl")
    with checkpoint.open("ab") as stream:
        stream.write(b'{"row":')
    transport.failures.clear()
    result = pipeline.run_pipeline(path, output, resume=True, **options)
    assert [item["id"] for item in result] == [30, 10, 20]
    assert len(transport.calls) == 4
    assert llm.chat.completions.create.call_count == 3
    assert json.loads(output.with_suffix(".errors.json").read_text()) == []


@pytest.mark.parametrize("change", ["missing", "wrong_doc", "wrong_text"])
def test_missing_or_conflicting_database_records_do_not_make_predictions(tmp_path, database, llm, change):
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1,))
    bad = point("missing" if change == "missing" else "1:c:0", 2, None)
    if change == "wrong_text":
        bad["payload"].update(doc_id=None, chunk_text="Modified text")
    transport = Transport({1: [bad]})
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, **arguments(transport, llm, postgres_manager=database))
    assert error.value.failures[0]["stage"] == "hydration"
    llm.chat.completions.create.assert_not_called()


def test_llm_fabricated_ids_are_rejected_per_row(tmp_path, llm):
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1, 2))
    transport = Transport({1: [point("1:c:0")], 2: []})
    llm.chat.completions.create.side_effect = None
    llm.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(refusal=None, content=json.dumps({
            "id": 1, "relevant_docs": ["1"],
            "relevant_chunks": [{"doc_id": "999", "chunk_text": "Invented"}],
        })),
    )])
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, tmp_path / "result.json", **arguments(transport, llm))
    assert len(error.value.failures) == 1
    assert error.value.failures[0]["stage"] == "reranking"
    journal = (tmp_path / "result.checkpoint.jsonl").read_text()
    assert '"id": 2' in journal and '"id": 1' not in journal


def test_dedup_limits_and_original_identifiers(tmp_path, llm):
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1,))
    transport = Transport({1: [point("x", 7, "A &amp; B"), point("x", 7, "A &amp; B"),
                               point("y", 7, "a & B"), point("z", 8, "Other"),
                               point("empty", 9, "")]})
    result = pipeline.run_pipeline(path, top_k=250, branch_limit=100, max_docs=1, max_chunks=1,
                                   **arguments(transport, llm))
    assert result == [{"id": 1, "relevant_docs": ["7"],
                       "relevant_chunks": [{"doc_id": "8", "chunk_text": "Other"}]}]
    body = transport.calls[0]
    assert body["limit"] == 250 and all(p["limit"] == 100 for p in body["prefetch"])
    request = json.loads(llm.chat.completions.create.call_args.kwargs["messages"][1]["content"])
    assert len(request["documents"]["relevant_chunks"]) == 2


@pytest.mark.parametrize("bad_record", ["translation", "duplicate_id", "null_id", "empty_query"])
def test_invalid_records_fail_explicitly_without_discarding_other_queries(tmp_path, llm, bad_record):
    changed = {"translation": {"english": [None, "EN 2"]},
               "duplicate_id": {"id": [1, 1]}, "null_id": {"id": [None, 2]},
               "empty_query": {"query": ["", "VI 2"]}}[bad_record]
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1, 2), **changed)
    transport = Transport({})
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, **arguments(transport, llm))
    assert len(error.value.failures) == 1 and error.value.failures[0]["stage"] == "input"
    assert len(transport.calls) == 1


def test_schema_override_and_missing_translations(tmp_path, llm):
    path = tmp_path / "custom.parquet"
    pq.write_table(pa.table({"qid": [5], "vi": ["VI 5"], "en": ["EN 5"], "zh": ["中文 5"]}), path)
    transport = Transport({})
    result = pipeline.run_pipeline(path, columns={"id": "qid", "original_query": "vi",
                                                 "eng_query": "en", "chinese_query": "zh"},
                                   **arguments(transport, llm))
    assert result[0]["id"] == 5
    pq.write_table(pa.table({"id": [1], "query": ["VI 1"]}), path)
    with pytest.raises(ValueError, match="eng_query"):
        pipeline.run_pipeline(path, **arguments(transport, llm))


def test_resume_rejects_changed_configuration_and_input(tmp_path, llm):
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1,))
    transport = Transport({}, failures={1})
    output = tmp_path / "result.json"
    options = arguments(transport, llm, resume_tag="fixture-v1")
    with pytest.raises(pipeline.PipelineError):
        pipeline.run_pipeline(path, output, **options)
    with pytest.raises(ValueError, match="configuration changed"):
        pipeline.run_pipeline(path, output, resume=True, top_k=101, **options)
    write_queries(path, identifiers=(2,))
    with pytest.raises(ValueError, match="configuration changed"):
        pipeline.run_pipeline(path, output, resume=True, **options)


def test_output_safety_zero_rows_and_no_client_initialization(tmp_path, monkeypatch):
    path = tmp_path / "empty.parquet"
    pq.write_table(pa.table({"id": pa.array([], type=pa.int64()),
                            "query": pa.array([], type=pa.string()),
                            "english": pa.array([], type=pa.string()),
                            "chinese": pa.array([], type=pa.string())}), path)
    monkeypatch.setattr(pipeline, "load_dense_encoder", lambda **_: pytest.fail("No model needed"))
    output = tmp_path / "empty.json"
    assert pipeline.run_pipeline(path, output) == []
    with pytest.raises(FileExistsError):
        pipeline.run_pipeline(path, output)
    with pytest.raises(ValueError, match="must differ"):
        pipeline.run_pipeline(path, checkpoint_path=path)


def test_cli_entry_point_and_limit(tmp_path, monkeypatch):
    path = write_queries(tmp_path / "queries.parquet")
    output = tmp_path / "result.json"
    run = Mock(return_value=[])
    monkeypatch.setattr(pipeline, "run_pipeline", run)
    assert pipeline.main([str(path), "--output", str(output), "--limit", "2",
                          "--eng-query-column", "english"]) == 0
    assert run.call_args.kwargs["limit"] == 2
    assert run.call_args.kwargs["columns"] == {"eng_query": "english"}


def test_database_outage_only_fails_queries_requiring_hydration(tmp_path, llm):
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1, 2))
    transport = Transport({1: [point("missing", 1, None)], 2: [point("2:c:0", 2)]})
    database = Mock()
    database.get_submission_chunks.side_effect = RuntimeError("private database details")
    output = tmp_path / "result.json"
    with pytest.raises(pipeline.PipelineError) as error:
        pipeline.run_pipeline(path, output, **arguments(transport, llm, postgres_manager=database))
    assert error.value.failures == [{"row": 0, "id": 1, "stage": "hydration", "error_type": "RuntimeError"}]
    database.get_submission_chunks.assert_called_once_with(["missing"])
    database.close.assert_not_called()
    assert '"id": 2' in output.with_suffix(".checkpoint.jsonl").read_text()
    assert llm.chat.completions.create.call_count == 1


@pytest.mark.parametrize("hits", [
    [{"id": "uuid", "payload": {"doc_id": 1, "chunk_text": "source"}}],
    [point("same", 1, "a"), point("same", 1, "b")],
    [point("chunk", 1.5)], [point("chunk", True)], [point("chunk", "uuid")],
    [{"payload": None}],
])
def test_invalid_source_identity_and_payloads_are_explicit_failures(tmp_path, llm, hits):
    path = write_queries(tmp_path / "queries.parquet", identifiers=(1,))
    with pytest.raises(pipeline.PipelineError):
        pipeline.run_pipeline(path, **arguments(Transport({1: hits}), llm))
    llm.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("legacy_api",[True,False])
def test_cpu_encoder_uses_pinned_local_cls_and_existing_window_aggregation(monkeypatch,legacy_api):
    import numpy as np
    import torch
    import transformers
    from Scripts.Qdrant import build_gte_qdrant

    monkeypatch.setattr(pipeline, "GTE_CONFIG", {**pipeline.GTE_CONFIG, "dimension": 3, "max_length": 6})

    class Tokenizer:
        bos_token_id = 100
        eos_token_id = 101
        def __call__(self, texts, **options):
            assert options["truncation"] is False
            return {"input_ids": [[int(x) for x in text.split()] for text in texts]}

        def num_special_tokens_to_add(self, pair=False):
            return 2

        def build_inputs_with_special_tokens(self, ids):
            return [100, *ids, 101]

        def pad(self, windows, **options):
            # Encode the content sum in CLS for this tiny deterministic fake model.
            return {"input_ids": torch.tensor([[sum(w["input_ids"][1:-1])] for w in windows])}

    if not legacy_api:
        del Tokenizer.build_inputs_with_special_tokens

    model = Mock(spec=["embeddings","eval","to","dtype"])
    model.dtype = torch.float32
    model.side_effect = lambda input_ids: SimpleNamespace(last_hidden_state=torch.stack([
        torch.tensor([[float(row[0]), 1, 2], [999, 999, 999]]) for row in input_ids
    ]))
    config = SimpleNamespace(hidden_size=3, max_position_embeddings=6)
    tokenizer_loader = Mock(return_value=Tokenizer())
    config_loader = Mock(return_value=config)
    model_loader = Mock(return_value=model)
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", tokenizer_loader)
    monkeypatch.setattr(transformers.AutoConfig, "from_pretrained", config_loader)
    monkeypatch.setattr(transformers.AutoModel, "from_pretrained", model_loader)
    encode = pipeline.load_dense_encoder(device="cpu", batch_size=2)
    vectors = encode(["1 2 3 4 5 6", "9 10"])
    pieces = build_gte_qdrant.normalize_vectors(np.array([[10, 1, 2], [11, 1, 2], [19, 1, 2]]))
    expected = build_gte_qdrant.normalize_vectors(np.array([4 * pieces[0] + 2 * pieces[1], pieces[2]]))
    assert np.allclose(vectors, expected)
    assert vectors.dtype == np.float32
    for loader in (tokenizer_loader, config_loader, model_loader):
        assert loader.call_args.kwargs["local_files_only"] is True
        assert loader.call_args.kwargs["revision"] == pipeline.GTE_CONFIG["revision"]
    assert model_loader.call_args.kwargs["code_revision"] == pipeline.GTE_CONFIG["code_revision"]
    assert tokenizer_loader.call_args.kwargs["trust_remote_code"] is True
    assert tokenizer_loader.call_args.kwargs["code_revision"] == pipeline.GTE_CONFIG["code_revision"]
    assert model_loader.call_args.kwargs["torch_dtype"] == torch.float32
    model.eval.return_value.to.assert_called_once_with("cpu")
    mask = model.get_extended_attention_mask(torch.tensor([[1,1,0]]),(1,3))
    assert mask.shape == (1,1,1,3)
    assert mask[0,0,0,:2].tolist() == [0,0]
    assert mask[0,0,0,2] == torch.finfo(torch.float32).min


@pytest.mark.parametrize("bounds,expected", [
    ({}, [30,10,20]), ({"start":2}, [10,20]), ({"end":2}, [30,10]),
    ({"start":2,"end":2}, [10]), ({"start":2,"end":3,"limit":1}, [10]),
])
def test_inclusive_row_ranges_keep_ids_order_and_checkpoint_positions(tmp_path, llm, bounds, expected):
    path = write_queries(tmp_path / "queries.parquet")
    transport = Transport({})
    output = tmp_path / "output.json"
    progress = []
    results = pipeline.run_pipeline(path, output, batch_size=1, progress_callback=progress.append,
                                    **bounds, **arguments(transport, llm))
    assert [p["id"] for p in results] == expected
    assert len(transport.calls) == len(expected)
    records = [json.loads(line) for line in output.with_suffix(".checkpoint.jsonl").read_text().splitlines()][1:]
    assert [r["row"] for r in records] == [[30,10,20].index(i) for i in expected]
    assert progress[-1]["completed"] == progress[-1]["total"] == len(expected)


@pytest.mark.parametrize("bounds", [{"start":0},{"end":0},{"start":4},{"end":4},{"start":3,"end":2}])
def test_invalid_row_ranges_rejected_before_processing(tmp_path, llm, bounds):
    path = write_queries(tmp_path / "queries.parquet")
    transport = Transport({})
    with pytest.raises(ValueError):
        pipeline.run_pipeline(path, **bounds, **arguments(transport, llm))
    assert not transport.calls


def test_pause_at_durable_batch_boundary_and_resume(tmp_path, llm):
    path = write_queries(tmp_path / "queries.parquet")
    output = tmp_path / "output.json"
    transport = Transport({})
    stop = Event()

    def progress(values):
        if values["completed"] == 1:
            stop.set()

    options = arguments(transport, llm, resume_tag="range-fixture")
    with pytest.raises(pipeline.PipelinePaused):
        pipeline.run_pipeline(path, output, start=2, batch_size=1,
                              stop_event=stop, progress_callback=progress, **options)
    assert not output.exists() and len(transport.calls) == 1
    records = output.with_suffix(".checkpoint.jsonl").read_text().splitlines()
    assert len(records) == 2 and json.loads(records[1])["row"] == 1
    result = pipeline.run_pipeline(path, output, start=2, batch_size=1, resume=True, **options)
    assert [p["id"] for p in result] == [10,20]
    assert len(transport.calls) == 2


def test_model_cache_prefers_configured_or_downloaded_project_cache(tmp_path,monkeypatch):
    monkeypatch.delenv("PIPELINE_MODEL_CACHE",raising=False)
    monkeypatch.setattr(pipeline,"__file__",str(tmp_path / "BackEnd/app/pipeline.py"))
    assert pipeline._model_cache() is None
    cache = tmp_path / "artifacts/model-cache"
    (cache / "models--Alibaba-NLP--gte-multilingual-base/snapshots" / pipeline.GTE_CONFIG["revision"]).mkdir(parents=True)
    assert pipeline._model_cache() == str(cache)
    monkeypatch.setenv("PIPELINE_MODEL_CACHE",str(tmp_path / "configured"))
    assert pipeline._model_cache() == str(tmp_path / "configured")
    assert pipeline._model_cache(tmp_path / "explicit") == str(tmp_path / "explicit")


def test_missing_cached_encoder_has_actionable_safe_error(monkeypatch):
    import transformers
    loader = Mock(side_effect=OSError("private connection credentials must not leak"))
    monkeypatch.setattr(transformers.AutoTokenizer,"from_pretrained",loader)
    with pytest.raises(pipeline.PipelineSetupError) as error:
        pipeline.load_dense_encoder(cache_dir="artifacts/model-cache")
    assert error.value.code == "ENCODER_MODEL_UNAVAILABLE"
    assert error.value.stage == "encoding"
    assert "PIPELINE_MODEL_CACHE" in str(error.value)
    assert "private connection" not in str(error.value)
    assert loader.call_args.kwargs["cache_dir"] == "artifacts/model-cache"


@pytest.mark.parametrize("kind,code",[("missing","QDRANT_COLLECTION_MISSING"),
                                      ("timeout","QDRANT_UNAVAILABLE"),
                                      ("dense_only","QDRANT_HYBRID_REQUIRED")])
def test_qdrant_setup_checked_once_before_encoding_rows(tmp_path,monkeypatch,kind,code):
    path = write_queries(tmp_path / "queries.parquet")
    manager = QdrantManager("http://fixture",session=Mock())
    manager.refresh_collection = Mock(return_value={"config":{"params":{"sparse_vectors":{}}}})
    if kind == "missing":
        response = requests.Response()
        response.status_code = 404
        manager.refresh_collection.side_effect = requests.HTTPError("private details",response=response)
    elif kind == "timeout":
        manager.refresh_collection.side_effect = requests.Timeout("private details")
    monkeypatch.setattr(pipeline,"QdrantManager",lambda *args,**kwargs:manager)
    encode = Mock()
    monkeypatch.setattr(pipeline,"load_dense_encoder",encode)
    with pytest.raises(pipeline.PipelineSetupError) as error:
        pipeline.run_pipeline(path,batch_size=1)
    assert error.value.code == code
    assert "private details" not in str(error.value)
    manager.refresh_collection.assert_called_once()
    encode.assert_not_called()


def test_encoder_initialization_failure_is_not_repeated_per_batch(tmp_path,llm,monkeypatch):
    path = write_queries(tmp_path / "queries.parquet")
    transport = Transport({})
    loader = Mock(side_effect=pipeline.PipelineSetupError("encoding","ENCODER_MODEL_UNAVAILABLE","Model unavailable"))
    monkeypatch.setattr(pipeline,"load_dense_encoder",loader)
    options = arguments(transport,llm)
    options.pop("dense_encoder")
    with pytest.raises(pipeline.PipelineSetupError):
        pipeline.run_pipeline(path,tmp_path / "output.json",batch_size=1,**options)
    loader.assert_called_once()
    assert not transport.calls
    assert not (tmp_path / "output.errors.json").exists()
