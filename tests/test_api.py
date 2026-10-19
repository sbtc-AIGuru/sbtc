"""HTTP upload/download tests using the real pipeline and mocked model/service transports."""

import io
import json
from pathlib import Path
import sys
from threading import Event
import time
from uuid import uuid4
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BackEnd.app.api.main import create_app
from BackEnd.app.pipeline import PipelineSetupError, run_pipeline
from BackEnd.app.Retrieval.utils import atomic_json
from test_pipeline import Transport, arguments, reranker, point, write_queries


def wait_status(client, identifier, states):
    for _ in range(300):
        response = client.get(f"/api/jobs/{identifier}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in states:
            return job
        time.sleep(.01)
    pytest.fail(f"Job did not reach {states}; last status: {job}")


def upload(client, path, data=None, filename="queries.parquet"):
    return client.post("/api/jobs", files={"file":(filename,path.read_bytes(),"application/octet-stream")}, data=data or {})


def test_upload_range_real_pipeline_status_zip_and_static_ui(tmp_path, reranker):
    path = write_queries(tmp_path / "queries.parquet")
    transport = Transport({10:[point("10:c:0",10)],20:[point("20:c:0",20)]})
    root = tmp_path / "jobs"
    options = arguments(transport,reranker,resume_tag="api-v1")
    options.pop("rerank")
    application = create_app(jobs_dir=root, pipeline_options=options)
    with TestClient(application) as client:
        assert client.get("/").status_code == 200
        assert "Truy hồi y khoa" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/styles.css").status_code == 200
        assert client.get("/api/health").json() == {"status":"ok"}
        response = upload(client,path,{"start":"2","end":"3","batch_size":"1"},"../../queries.parquet")
        assert response.status_code == 202
        identifier = response.json()["id"]
        job = wait_status(client,identifier,{"completed","failed"})
        assert job["status"] == "completed", job
        assert (job["start"],job["end"],job["total"],job["completed"]) == (2,3,2,2)
        assert job["filename"] == "queries.parquet"
        result = client.get(job["download_url"])
        assert result.status_code == 200 and "output.zip" in result.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert archive.namelist() == ["output.json"]
            assert [r["id"] for r in json.loads(archive.read("output.json"))] == [10,20]
        records = (root / identifier / "output.checkpoint.jsonl").read_text().splitlines()
        assert [json.loads(r)["row"] for r in records[1:]] == [1,2]
        assert len(transport.calls) == 2
        assert len(client.get("/api/jobs").json()) == 1
        assert client.post(f"/api/jobs/{identifier}/resume").status_code == 409
        assert client.post(f"/api/jobs/{identifier}/pause").status_code == 409
        reranker.score.assert_not_called()


def test_blank_bounds_run_every_row_and_persist_after_restart(tmp_path,reranker):
    path = write_queries(tmp_path / "queries.parquet")
    root = tmp_path / "jobs"
    transport = Transport({})
    options = arguments(transport,reranker,resume_tag="api-v1")
    with TestClient(create_app(jobs_dir=root,pipeline_options=options)) as client:
        response = upload(client,path,{"start":"","end":""})
        assert response.status_code == 202
        identifier = response.json()["id"]
        job = wait_status(client,identifier,{"completed","failed"})
        assert job["status"] == "completed"
        assert (job["start"],job["end"],job["completed"]) == (1,3,3)
    with TestClient(create_app(jobs_dir=root,pipeline_options=options)) as client:
        assert client.get("/api/jobs").json()[0]["id"] == identifier
        assert client.get(f"/api/jobs/{identifier}/download").status_code == 200
    assert len(transport.calls) == 3


def test_failure_report_and_resume_only_missing_rows_after_restart(tmp_path,reranker):
    path = write_queries(tmp_path / "queries.parquet")
    root = tmp_path / "jobs"
    transport = Transport({},failures={10})
    options = arguments(transport,reranker,resume_tag="api-v1")
    with TestClient(create_app(jobs_dir=root,pipeline_options=options)) as client:
        identifier = upload(client,path).json()["id"]
        job = wait_status(client,identifier,{"failed"})
        assert job["completed"] == 2 and job["failed"] == 1
        assert job["download_url"] is None
        assert client.get(f"/api/jobs/{identifier}/download").status_code == 409
        error = client.get(job["errors_url"]).json()[0]
        assert error == {"row":1,"id":10,"stage":"retrieval","error_type":"Timeout"}
    state_path = root / identifier / "state.json"
    state = json.loads(state_path.read_text())
    state["status"] = "running"  # Simulate an abrupt previous process exit.
    atomic_json(state_path,state)
    transport.failures.clear()
    with TestClient(create_app(jobs_dir=root,pipeline_options=options)) as client:
        job = client.get(f"/api/jobs/{identifier}").json()
        assert job["status"] == "paused" and job["error"]["type"] == "ServerRestart"
        assert client.post(f"/api/jobs/{identifier}/resume").status_code == 202
        job = wait_status(client,identifier,{"completed","failed"})
        assert job["status"] == "completed", job
        assert job["attempts"] == 2 and job["completed"] == 3
    assert len(transport.calls) == 4


def test_pause_waits_for_batch_and_resume_keeps_saved_rows(tmp_path,reranker):
    path = write_queries(tmp_path / "queries.parquet")
    root = tmp_path / "jobs"
    transport = Transport({})
    saved, release = Event(), Event()
    blocked_once = False

    def runner(*args,**kwargs):
        progress = kwargs["progress_callback"]

        def on_progress(values):
            nonlocal blocked_once
            progress(values)
            if values["completed"] == 1 and not blocked_once:
                blocked_once = True
                saved.set()
                assert release.wait(5)

        kwargs["progress_callback"] = on_progress
        return run_pipeline(*args,**kwargs)

    application = create_app(jobs_dir=root,runner=runner,pipeline_options=arguments(transport,reranker,resume_tag="api-v1"))
    with TestClient(application) as client:
        identifier = upload(client,path,{"batch_size":"1"}).json()["id"]
        try:
            assert saved.wait(5)
            assert client.post(f"/api/jobs/{identifier}/resume").status_code == 409
            response = client.post(f"/api/jobs/{identifier}/pause")
            assert response.status_code == 202 and response.json()["status"] == "pausing"
        finally:
            release.set()
        job = wait_status(client,identifier,{"paused","failed"})
        assert job["status"] == "paused" and job["completed"] == 1
        assert len(transport.calls) == 1
        assert client.post(f"/api/jobs/{identifier}/resume").status_code == 202
        job = wait_status(client,identifier,{"completed","failed"})
        assert job["status"] == "completed",job
    assert len(transport.calls) == 3


@pytest.mark.parametrize("data", [{"start":"0"},{"end":"0"},{"start":"3","end":"2"},
                                  {"end":"4"},{"start":"4"},{"batch_size":"0"}])
def test_invalid_ranges_or_batch_rejected_without_creating_jobs(tmp_path,data):
    path = write_queries(tmp_path / "queries.parquet")
    with TestClient(create_app(jobs_dir=tmp_path / "jobs")) as client:
        assert upload(client,path,data).status_code == 422
        assert client.get("/api/jobs").json() == []


def test_invalid_upload_size_schema_and_job_paths(tmp_path):
    path = write_queries(tmp_path / "queries.parquet")
    root = tmp_path / "jobs"
    with TestClient(create_app(jobs_dir=root,max_upload_bytes=100)) as client:
        assert upload(client,path).status_code == 413
        assert upload(client,path,filename="x.txt").status_code == 400
        assert client.post("/api/jobs",files={"file":("bad.parquet",b"invalid")}).status_code == 400
        assert client.get("/api/jobs").json() == []
        assert client.get(f"/api/jobs/{uuid4().hex}").status_code == 404
        assert client.get("/api/jobs/not-a-uuid/download").status_code == 422
        assert not list(root.glob("*/input.parquet"))
    pq.write_table(pa.table({"id":[1],"query":["only VI"]}),path)
    with TestClient(create_app(jobs_dir=root)) as client:
        assert upload(client,path).status_code == 400


def test_recover_final_json_before_zip_and_status_update(tmp_path,reranker):
    path = write_queries(tmp_path / "queries.parquet",identifiers=(1,))
    root = tmp_path / "jobs"
    transport = Transport({})
    options = arguments(transport,reranker,resume_tag="api-v1")
    with TestClient(create_app(jobs_dir=root,pipeline_options=options)) as client:
        identifier = upload(client,path).json()["id"]
        assert wait_status(client,identifier,{"completed","failed"})["status"] == "completed"
    state_path = root / identifier / "state.json"
    state = json.loads(state_path.read_text())
    state["status"] = "running"
    atomic_json(state_path,state)
    (root / identifier / "output.zip").unlink()
    with TestClient(create_app(jobs_dir=root,pipeline_options=options)) as client:
        assert client.post(f"/api/jobs/{identifier}/resume").status_code == 202
        assert wait_status(client,identifier,{"completed","failed"})["status"] == "completed"
        assert client.get(f"/api/jobs/{identifier}/download").status_code == 200
    assert len(transport.calls) == 1


def test_jobs_queue_serially_and_queued_job_can_pause_and_resume(tmp_path,reranker):
    path = write_queries(tmp_path / "queries.parquet",identifiers=(1,))
    transport = Transport({})
    entered, release = Event(), Event()
    running, maximum = 0, 0

    def runner(*args,**kwargs):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum,running)
        entered.set()
        try:
            assert release.wait(5)
            return run_pipeline(*args,**kwargs)
        finally:
            running -= 1

    application = create_app(jobs_dir=tmp_path / "jobs",runner=runner,
                             pipeline_options=arguments(transport,reranker,resume_tag="api-v1"))
    with TestClient(application) as client:
        first = upload(client,path).json()["id"]
        try:
            assert entered.wait(5)
            second = upload(client,path).json()["id"]
            assert client.get(f"/api/jobs/{second}").json()["status"] == "queued"
            assert client.post(f"/api/jobs/{second}/pause").json()["status"] == "paused"
            assert client.post(f"/api/jobs/{second}/resume").status_code == 202
        finally:
            release.set()
        assert wait_status(client,first,{"completed","failed"})["status"] == "completed"
        assert wait_status(client,second,{"completed","failed"})["status"] == "completed"
    assert maximum == 1 and len(transport.calls) == 2


@pytest.mark.parametrize("stage,code", [("encoding", "ENCODER_MODEL_UNAVAILABLE"),
                                        ("reranking", "RERANKER_MODEL_UNAVAILABLE")])
def test_setup_error_shown_actionably_without_marking_input_rows_bad(tmp_path, stage, code):
    path = write_queries(tmp_path / "queries.parquet")

    def runner(*args,**kwargs):
        raise PipelineSetupError(stage,code,"Cần tải model đúng revision.")

    with TestClient(create_app(jobs_dir=tmp_path / "jobs",runner=runner)) as client:
        identifier = upload(client,path).json()["id"]
        job = wait_status(client,identifier,{"failed"})
        assert job["completed"] == 0 and job["failed"] == 0
        assert job["error"] == {"stage":stage,"type":code,"message":"Cần tải model đúng revision."}
        assert job["download_url"] is None and job["errors_url"] is None


def test_server_reads_local_reranker_configuration(tmp_path, monkeypatch):
    for name, value in {"DEVICE": "cpu", "TOP_K": "400", "BRANCH_LIMIT": "200",
                        "MAX_CHUNKS": "25", "RERANK": "1", "RERANKER_DEVICE": "cuda:0",
                        "RERANKER_BATCH_SIZE": "2", "RERANKER_MAX_LENGTH": "4096",
                        "RERANKER_TOKEN_BUDGET": "8192"}.items():
        monkeypatch.setenv("PIPELINE_" + name, value)
    app = create_app(jobs_dir=tmp_path / "jobs")
    with TestClient(app):
        options = app.state.jobs.options
        assert options["device"] == "cpu" and options["reranker_device"] == "cuda:0"
        assert options["max_chunks"] == 25
        assert options["rerank"] is True
        assert options["top_k"] == 400 and options["branch_limit"] == 200
        assert options["reranker_batch_size"] == 2
        assert options["reranker_max_length"] == 4096
        assert options["reranker_token_budget"] == 8192
        assert not any("llm" in key for key in options)


def test_server_defaults_disable_reranking_and_keep_all_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv("PIPELINE_MAX_CHUNKS", raising=False)
    monkeypatch.delenv("PIPELINE_RERANK", raising=False)
    monkeypatch.delenv("PIPELINE_TOP_K", raising=False)
    monkeypatch.delenv("PIPELINE_BRANCH_LIMIT", raising=False)
    app = create_app(jobs_dir=tmp_path / "jobs")
    with TestClient(app):
        assert app.state.jobs.options["max_chunks"] is None
        assert app.state.jobs.options["rerank"] is False
        assert app.state.jobs.options["top_k"] == 200
        assert app.state.jobs.options["branch_limit"] == 100
