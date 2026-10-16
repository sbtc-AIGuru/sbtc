"""Offline checks for the Colab API and standard-library local client."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient
import nbformat
import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "Scripts/Qwen_Colab/Qwen3_5_9B_Colab_API.ipynb"
CLIENT_PATH = ROOT / "Scripts/Qwen_Colab/test_local.py"
API_KEY = "offline-test-key-123456"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
MODEL_ID = "Qwen/Qwen3.5-9B"


@pytest.fixture
def notebook_module(monkeypatch):
    module = ModuleType("qwen_colab_notebook_test")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code" and set(cell.metadata.get("tags", [])) & {"engine", "api"}:
            exec(compile(cell.source, str(NOTEBOOK), "exec", dont_inherit=True), module.__dict__)
    return module


@pytest.fixture
def client_module():
    spec = importlib.util.spec_from_file_location("qwen_local_client", CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeEngine:
    model_id = MODEL_ID
    revision = "offline-revision"
    max_context = 4096

    def __init__(self):
        self.calls = []
        self.error = None

    def complete(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return {
            "content": "Xin chào từ model giả lập.",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        }


@pytest.fixture
def api(notebook_module):
    engine = FakeEngine()
    app = notebook_module.create_app(engine, API_KEY)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, engine=engine)


def payload(**overrides):
    return {"model": MODEL_ID, "messages": [{"role": "user", "content": "Xin chào"}], **overrides}


def test_notebook_schema_syntax_and_anonymous_download():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(notebook)
    sources = {}
    for number, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"cell{number}", "exec", dont_inherit=True)
            assert cell.execution_count is None
            assert cell.outputs == []
            sources[cell.metadata.tags[0]] = cell.source
    assert "HF_TOKEN" not in json.dumps(notebook)
    assert 'HfApi(token=False)' in sources["engine"]
    assert '"token": False' in sources["engine"]
    assert "INSTALL_PACKAGES = False" in sources["install"]
    assert "OPEN_PUBLIC_TUNNEL = False" in sources["tunnel"]
    assert "STOP_SERVER = False" in sources["stop"]


@pytest.mark.parametrize("path,method", [
    ("/health", "get"), ("/v1/models", "get"), ("/v1/chat/completions", "post"),
])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-key"}, {"Authorization": "Basic abc"}])
def test_authentication_on_every_endpoint(api, path, method, headers):
    kwargs = {"json": payload()} if method == "post" else {}
    response = getattr(api.client, method)(path, headers=headers, **kwargs)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert api.engine.calls == []


def test_health_models_and_chat(api):
    assert api.client.get("/health", headers=AUTH).json()["revision"] == "offline-revision"
    assert api.client.get("/v1/models", headers=AUTH).json()["data"][0]["id"] == MODEL_ID
    response = api.client.post("/v1/chat/completions", headers=AUTH, json=payload())
    assert response.status_code == 200
    result = response.json()
    assert result["choices"][0]["message"]["content"] == "Xin chào từ model giả lập."
    assert result["usage"]["total_tokens"] == 18
    assert result["id"].startswith("chatcmpl-")
    assert api.engine.calls[0][1:] == (256, 0.7, 0.8, False)


@pytest.mark.parametrize("change", [
    {"messages": []}, {"messages": [{"role": "user", "content": "   "}]},
    {"messages": [{"role": "assistant", "content": "hello"}]},
    {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]},
    {"messages": [{"role": "user", "content": "a"}, {"role": "system", "content": "b"}]},
    {"messages": [{"role": "user", "content": "a" * 16001}]},
    {"messages": [{"role": "user", "content": "a" * 16000}] * 5},
    {"messages": [{"role": "user", "content": "x"}] * 33},
    {"max_tokens": 0}, {"max_tokens": 1025}, {"max_tokens": True},
    {"temperature": -1}, {"temperature": 3}, {"top_p": 0},
    {"stream": True}, {"tools": []},
])
def test_reject_invalid_or_unsupported_requests(api, change):
    response = api.client.post("/v1/chat/completions", headers=AUTH, json=payload(**change))
    assert response.status_code == 422
    assert api.engine.calls == []


def test_unknown_model_and_busy_gpu_do_not_generate(api):
    assert api.client.post("/v1/chat/completions", headers=AUTH, json=payload(model="other")).status_code == 404
    api.app.state.generation_lock.acquire()
    try:
        response = api.client.post("/v1/chat/completions", headers=AUTH, json=payload())
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert api.client.get("/health", headers=AUTH).json()["busy"] is True
        assert api.engine.calls == []
    finally:
        api.app.state.generation_lock.release()


@pytest.mark.parametrize("error,status", [
    (ValueError("context budget exceeded"), 400),
    (MemoryError("internal allocation detail"), 503),
    (RuntimeError("private internal failure"), 500),
])
def test_failures_release_lock_and_hide_internal_errors(api, error, status):
    api.engine.error = error
    response = api.client.post("/v1/chat/completions", headers=AUTH, json=payload())
    assert response.status_code == status
    assert not api.app.state.generation_lock.locked()
    if status != 400:
        assert str(error) not in response.text
    api.engine.error = None
    assert api.client.post("/v1/chat/completions", headers=AUTH, json=payload()).status_code == 200


class FakeBatch(dict):
    def to(self, device):
        return self


@pytest.fixture
def engine(notebook_module):
    engine = notebook_module.QwenEngine.__new__(notebook_module.QwenEngine)
    engine.torch = torch
    engine.max_context = 16
    engine.device = torch.device("cpu")
    engine.settings = None

    def generate(**settings):
        assert not torch.is_grad_enabled()
        engine.settings = settings
        return torch.tensor([[7, 8, 9, 10, 20, 21, 2]])

    class Tokenizer:
        pad_token_id = 2

        def apply_chat_template(self, messages, **kwargs):
            engine.template_options = kwargs
            return "formatted prompt"

        def __call__(self, text, **kwargs):
            assert kwargs["add_special_tokens"] is False
            return FakeBatch(input_ids=torch.tensor([[7, 8, 9, 10]]))

        @staticmethod
        def decode(ids, **kwargs):
            assert ids.tolist() == [20, 21, 2]
            return "Xin chào"

    engine.tokenizer = Tokenizer()
    engine.model = SimpleNamespace(generate=generate, generation_config=SimpleNamespace(eos_token_id=[2]))
    return engine


def test_engine_budget_and_generated_token_slice(engine):
    with pytest.raises(ValueError, match="context budget"):
        engine.complete([], 13, 0, 0.8, False)
    assert engine.settings is None
    result = engine.complete([], 12, 0, 0.8, False)
    assert result["content"] == "Xin chào"
    assert result["usage"] == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}
    assert result["finish_reason"] == "stop"
    assert engine.template_options["enable_thinking"] is False
    assert engine.settings["do_sample"] is False
    assert engine.settings["logits_to_keep"] == 1
    engine.complete([], 12, 0.7, 0.8, True)
    assert engine.settings["do_sample"] is True
    assert engine.settings["top_p"] == 0.8
    assert engine.template_options["enable_thinking"] is True


def test_engine_oom_is_reported(engine):
    def fail(**kwargs):
        raise torch.cuda.OutOfMemoryError("test allocation")
    engine.model.generate = fail
    with pytest.raises(MemoryError, match="CUDA ran out of memory"):
        engine.complete([], 12, 0, 0.8, False)


@pytest.mark.parametrize("value", ["https://example.test", "https://example.test/", "https://example.test/v1/"])
def test_client_url_normalization(client_module, value):
    assert client_module.normalize_base_url(value) == "https://example.test"


@pytest.mark.parametrize("value", [
    "http://example.test", "https://user:password@example.test", "https://example.test/api",
    "https://example.test?a=b", "https://example.test/#x", "file:///tmp/secret", "",
])
def test_client_rejects_unsafe_urls(client_module, value):
    with pytest.raises(ValueError):
        client_module.normalize_base_url(value)


def test_client_to_api_round_trip_without_network(client_module, api, monkeypatch, capsys):
    class Opener:
        def open(self, request, timeout):
            headers = dict(request.header_items())
            assert headers["Authorization"] == AUTH["Authorization"]
            assert headers["Ngrok-skip-browser-warning"] == "true"
            body = json.loads(request.data) if request.data else None
            response = api.client.request(request.method, request.full_url, headers=headers, json=body)
            assert response.status_code == 200
            return io.BytesIO(response.content)

    monkeypatch.setattr(client_module, "build_opener", lambda *args: Opener())
    monkeypatch.setenv("QWEN_API_KEY", API_KEY)
    assert client_module.main(["--base-url", "https://testserver/v1", "--prompt", "Xin chào"]) == 0
    captured = capsys.readouterr()
    assert "Xin chào từ model giả lập." in captured.out
    assert API_KEY not in captured.out + captured.err
    assert api.engine.calls[0][0][-1]["content"] == "Xin chào"


@pytest.mark.parametrize("error,message", [
    (HTTPError("https://testserver", 401, "Unauthorized", {}, io.BytesIO(b"bad key")), "HTTP 401"),
    (URLError("offline"), "Connection failed"),
])
def test_client_reports_connection_and_http_errors(client_module, monkeypatch, error, message):
    def fail(request, timeout):
        raise error
    monkeypatch.setattr(client_module, "build_opener", lambda *args: SimpleNamespace(open=fail))
    with pytest.raises(RuntimeError, match=message):
        client_module.request_json("https://testserver", "/health", API_KEY)


def test_client_rejects_redirect(client_module):
    with pytest.raises(RuntimeError, match="redirected"):
        client_module.RejectRedirects().redirect_request(None, None, 302, "", {}, "https://other.test")


def test_notebook_server_start_smoke_and_local_client(notebook_module, client_module, monkeypatch):
    """Run the actual notebook bootstrap against a fake engine on loopback."""
    with socket.socket() as available_port:
        available_port.bind(("127.0.0.1", 0))
        port = available_port.getsockname()[1]
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    sources = {
        cell.metadata.tags[0]: cell.source
        for cell in notebook.cells if cell.cell_type == "code"
    }
    namespace = notebook_module.__dict__
    namespace.update(engine=FakeEngine(), API_KEY=API_KEY, MODEL_ID=MODEL_ID, PORT=port)
    monkeypatch.setenv("QWEN_API_KEY", API_KEY)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    try:
        exec(compile(sources["start"], "start", "exec", dont_inherit=True), namespace)
        exec(compile(sources["smoke"], "smoke", "exec", dont_inherit=True), namespace)
        assert namespace["smoke_test_passed"] is True
        assert client_module.main(["--base-url", f"http://127.0.0.1:{port}"]) == 0
    finally:
        if namespace.get("server"):
            namespace["server"].should_exit = True
        if namespace.get("server_thread"):
            namespace["server_thread"].join(timeout=10)
            assert not namespace["server_thread"].is_alive()
