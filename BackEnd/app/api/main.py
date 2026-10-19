"""Serve the local UI and durable, resumable Parquet retrieval jobs."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
from threading import Event, RLock
from typing import Annotated, Literal
from uuid import UUID, uuid4
import zipfile

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pyarrow.parquet as pq

from ..pipeline import (
    DEFAULT_BRANCH_LIMIT, DEFAULT_TOP_K, SEARCH_METHODS,
    PipelineError, PipelinePaused, PipelineSetupError, _columns, run_pipeline,
)
from ..Retrieval.utils import atomic_json, job_lock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = PROJECT_ROOT / "FrontEnd"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Jobs:
    """One background pipeline at a time; state and checkpoints live on disk."""

    def __init__(self, root, runner, options):
        self.root, self.runner, self.options = root, runner, options
        self.lock = RLock()
        self.events = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retrieval-job")

    def read(self, identifier):
        with self.lock:
            path = self.root / identifier / "state.json"
            if not path.is_file():
                raise HTTPException(404, "Không tìm thấy tác vụ.")
            return json.loads(path.read_text(encoding="utf-8"))

    def update(self, identifier, **changes):
        with self.lock:
            state = self.read(identifier)
            state.update(changes, updated_at=timestamp())
            atomic_json(self.root / identifier / "state.json", state)
            return state

    def public(self, state):
        directory = self.root / state["id"]
        return {**state,
                "download_url": f"/api/jobs/{state['id']}/download"
                if state["status"] == "completed" and (directory / "output.zip").is_file() else None,
                "errors_url": f"/api/jobs/{state['id']}/errors"
                if (directory / "output.errors.json").is_file() and state["failed"] else None}

    def enqueue(self, identifier):
        with self.lock:
            state = self.read(identifier)
            if state["status"] not in {"uploaded", "paused", "failed"}:
                raise HTTPException(409, "Tác vụ đang chạy hoặc đã hoàn tất.")
            event = Event()
            self.events[identifier] = event
            self.update(identifier, status="queued", failed=0, error=None,
                        attempts=state["attempts"] + 1)
            self.pool.submit(self.run, identifier, event)

    def pause(self, identifier):
        with self.lock:
            state = self.read(identifier)
            if state["status"] not in {"queued", "running", "pausing"}:
                raise HTTPException(409, "Tác vụ hiện không chạy.")
            self.events[identifier].set()
            return self.update(identifier, status="paused" if state["status"] == "queued" else "pausing")

    def run(self, identifier, event):
        with self.lock:
            if event.is_set() or self.events.get(identifier) is not event:
                return
            state = self.update(identifier, status="running", error=None)
        directory = self.root / identifier
        output, archive = directory / "output.json", directory / "output.zip"

        def progress(values):
            self.update(identifier, completed=values["completed"], failed=values["failed"])

        try:
            # Atomic JSON exists only after every selected row succeeded. Recover
            # a process exit between JSON/ZIP creation and the final state update.
            if output.is_file():
                predictions = json.loads(output.read_text(encoding="utf-8"))
                if len(predictions) != state["total"]:
                    raise ValueError("Saved prediction count differs from selected rows")
                if not archive.is_file():
                    temporary = directory / "output.zip.partial"
                    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target:
                        target.write(output, arcname="output.json")
                    temporary.replace(archive)
            else:
                self.runner(
                    directory / "input.parquet", output, zip_path=archive,
                    start=state["start"], end=state["end"], batch_size=state["batch_size"],
                    resume=(directory / "output.checkpoint.jsonl").exists(),
                    progress_callback=progress, stop_event=event,
                    **{**self.options, **state.get("pipeline_config", {})},
                )
            if not output.is_file() or not archive.is_file():
                raise RuntimeError("Pipeline did not produce its output artifacts")
            self.update(identifier, status="completed", completed=state["total"], failed=0, error=None)
        except PipelinePaused:
            self.update(identifier, status="paused")
        except PipelineSetupError as exc:
            self.update(identifier, status="failed", error={
                "type": exc.code, "stage": exc.stage, "message": str(exc),
            })
        except PipelineError as exc:
            self.update(identifier, status="failed", failed=len(exc.failures), error={
                "type": "PipelineError", "message": "Một số dòng bị lỗi. Các dòng thành công đã được lưu; có thể tiếp tục.",
            })
        except Exception as exc:
            # Never expose raw SQL/client exceptions or connection configuration.
            self.update(identifier, status="failed", error={
                "type": type(exc).__name__,
                "message": "Không thể hoàn tất. Kiểm tra cấu hình dịch vụ, model hoặc checkpoint rồi chọn Tiếp tục.",
            })

    async def close(self):
        with self.lock:
            for event in self.events.values():
                event.set()
        await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)


def create_app(*, jobs_dir=None, runner=run_pipeline, pipeline_options=None, max_upload_bytes=None):
    root = Path(jobs_dir or os.getenv("PIPELINE_JOBS_DIR", PROJECT_ROOT / "artifacts/api-jobs")).resolve()
    upload_limit = max_upload_bytes or int(os.getenv("PIPELINE_MAX_UPLOAD_BYTES", 128 * 1024**2))
    options = pipeline_options if pipeline_options is not None else {
        "manifest_path": os.getenv("PIPELINE_MANIFEST_PATH") or None,
        "device": os.getenv("PIPELINE_DEVICE", "cpu"),
        "top_k": int(os.getenv("PIPELINE_TOP_K", str(DEFAULT_TOP_K))),
        "branch_limit": int(os.getenv("PIPELINE_BRANCH_LIMIT", str(DEFAULT_BRANCH_LIMIT))),
        "search_mode": os.getenv("PIPELINE_SEARCH_MODE", "4-branch"),
        "max_chunks": int(os.environ["PIPELINE_MAX_CHUNKS"]) if os.getenv("PIPELINE_MAX_CHUNKS") else None,
        "rerank": os.getenv("PIPELINE_RERANK", "0").lower() in {"1", "true", "yes"},
        "reranker_device": os.getenv("PIPELINE_RERANKER_DEVICE") or None,
        "reranker_batch_size": int(os.getenv("PIPELINE_RERANKER_BATCH_SIZE", "4")),
        "reranker_max_length": int(os.getenv("PIPELINE_RERANKER_MAX_LENGTH", "8192")),
        "reranker_token_budget": int(os.getenv("PIPELINE_RERANKER_TOKEN_BUDGET", "8192")),
        "model_cache": os.getenv("PIPELINE_MODEL_CACHE") or None,
        "resume_tag": os.getenv("PIPELINE_RESUME_TAG", ""),
    }
    job_defaults = {
        "search_mode": options.get("search_mode", "4-branch"),
        "rerank": options.get("rerank", False),
        "top_k": options.get("top_k", DEFAULT_TOP_K),
        "branch_limit": options.get("branch_limit", DEFAULT_BRANCH_LIMIT),
        "max_chunks": options.get("max_chunks"),
    }
    if job_defaults["search_mode"] not in SEARCH_METHODS:
        raise ValueError("PIPELINE_SEARCH_MODE must be '4-branch' or '6-branch'")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(application):
        # Avoid two API processes sharing a job directory and resuming the same job.
        with job_lock(root):
            jobs = Jobs(root, runner, options)
            application.state.jobs = jobs
            for path in root.glob("*/state.json"):
                state = json.loads(path.read_text(encoding="utf-8"))
                if state["status"] in {"uploaded", "queued", "running", "pausing"}:
                    jobs.update(state["id"], status="paused", error={
                        "type": "ServerRestart", "message": "Server đã khởi động lại. Chọn Tiếp tục để dùng checkpoint đã lưu.",
                    })
            try:
                yield
            finally:
                await jobs.close()

    application = FastAPI(title="SBTC · Medical Retrieval", lifespan=lifespan)

    @application.post("/api/jobs", status_code=202)
    def upload(
        file: UploadFile,
        start: Annotated[int | None, Form(ge=1)] = None,
        end: Annotated[int | None, Form(ge=1)] = None,
        batch_size: Annotated[int, Form(ge=1, le=256)] = 16,
        search_mode: Annotated[Literal["4-branch", "6-branch"] | None, Form()] = None,
        rerank: Annotated[bool | None, Form()] = None,
        top_k: Annotated[int | None, Form(ge=1)] = None,
        branch_limit: Annotated[int | None, Form(ge=1)] = None,
        max_chunks: Annotated[str | None, Form(pattern=r"^(all|[0-9]+)$")] = None,
    ):
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not filename.lower().endswith(".parquet"):
            raise HTTPException(400, "Vui lòng chọn file .parquet.")
        identifier = uuid4().hex
        directory = root / identifier
        directory.mkdir()
        try:
            size = 0
            with (directory / "input.parquet").open("xb") as stream:
                while block := file.file.read(1024 * 1024):
                    size += len(block)
                    if size > upload_limit:
                        raise HTTPException(413, "File vượt giới hạn dung lượng upload.")
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                with pq.ParquetFile(directory / "input.parquet") as parquet:
                    mapping = _columns(parquet.schema_arrow, None)
                    rows = parquet.metadata.num_rows
            except (ValueError, OSError) as exc:
                raise HTTPException(400, "Parquet không hợp lệ hoặc thiếu cột id/query/english/chinese.") from exc
            first, last = start or 1, end if end is not None else rows
            if not rows or first > last or last > rows:
                raise HTTPException(422, "Khoảng start–end không hợp lệ hoặc vượt số dòng trong file.")
            config = dict(job_defaults)
            for key, value in {"search_mode": search_mode, "rerank": rerank,
                               "top_k": top_k, "branch_limit": branch_limit}.items():
                if value is not None:
                    config[key] = value
            if max_chunks is not None:
                config["max_chunks"] = None if max_chunks == "all" else int(max_chunks)
            state = {
                "id": identifier, "filename": filename, "size": size, "rows": rows,
                "start": first, "end": last, "total": last - first + 1,
                "batch_size": batch_size, "columns": mapping, "status": "uploaded",
                "pipeline_config": config,
                "completed": 0, "failed": 0, "attempts": 0, "error": None,
                "created_at": timestamp(), "updated_at": timestamp(),
            }
            atomic_json(directory / "state.json", state)
        except Exception:
            shutil.rmtree(directory)
            raise
        application.state.jobs.enqueue(identifier)
        return application.state.jobs.public(application.state.jobs.read(identifier))

    @application.get("/api/jobs")
    def list_jobs():
        jobs = application.state.jobs
        with jobs.lock:
            states = [json.loads(path.read_text(encoding="utf-8")) for path in root.glob("*/state.json")]
        return [jobs.public(state) for state in sorted(states, key=lambda s: s["created_at"], reverse=True)]

    @application.get("/api/jobs/{job_id}")
    def get_job(job_id: UUID):
        jobs = application.state.jobs
        return jobs.public(jobs.read(job_id.hex))

    @application.post("/api/jobs/{job_id}/pause", status_code=202)
    def pause_job(job_id: UUID):
        jobs = application.state.jobs
        return jobs.public(jobs.pause(job_id.hex))

    @application.post("/api/jobs/{job_id}/resume", status_code=202)
    def resume_job(job_id: UUID):
        jobs = application.state.jobs
        jobs.enqueue(job_id.hex)
        return jobs.public(jobs.read(job_id.hex))

    @application.get("/api/jobs/{job_id}/download")
    def download(job_id: UUID):
        jobs = application.state.jobs
        state = jobs.read(job_id.hex)
        path = root / job_id.hex / "output.zip"
        if state["status"] != "completed" or not path.is_file():
            raise HTTPException(409, "Tác vụ chưa hoàn tất; output.zip chưa sẵn sàng.")
        return FileResponse(path, media_type="application/zip", filename="output.zip")

    @application.get("/api/jobs/{job_id}/errors")
    def errors(job_id: UUID):
        application.state.jobs.read(job_id.hex)
        path = root / job_id.hex / "output.errors.json"
        if not path.is_file():
            raise HTTPException(404, "Chưa có báo cáo lỗi.")
        return FileResponse(path, media_type="application/json", filename="errors.json")

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    @application.get("/api/config")
    def configuration():
        return {"search_modes": list(SEARCH_METHODS), "defaults": job_defaults}

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND / "index.html")

    application.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")
    return application


app = create_app()
