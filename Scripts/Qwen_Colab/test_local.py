"""Call the Qwen Colab text API using only the Python standard library."""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import socket
import sys
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MODEL_ID = "Qwen/Qwen3.5-9B"


class RejectRedirects(HTTPRedirectHandler):
    """Keep the bearer key from being forwarded to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("The API redirected the request; check the Colab URL.")


def normalize_base_url(value: str) -> str:
    """Accept the tunnel root or its /v1 API path."""
    parsed = urlsplit(value.strip())
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Base URL must have a hostname and no credentials.")
    if parsed.query or parsed.fragment or parsed.path.rstrip("/") not in ("", "/v1"):
        raise ValueError("Use the tunnel root or its /v1 path, without query/fragment.")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("HTTPS is required except for loopback smoke tests.")
    _ = parsed.port
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def request_json(
    base_url: str,
    path: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Send one authenticated request and report actionable HTTP failures."""
    request = Request(
        normalize_base_url(base_url) + path,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "ngrok-skip-browser-warning": "true",
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with build_opener(RejectRedirects()).open(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        hints = {
            401: "Check QWEN_API_KEY against the Colab QWEN_API_KEY secret.",
            404: "Check the URL/model ID and whether the Colab session is running.",
            422: "Check message and generation parameters.",
            429: "The GPU is busy; wait for the current generation to finish.",
            503: "The GPU ran out of memory; reduce context/output or use a larger GPU.",
        }
        raise RuntimeError(
            f"HTTP {exc.code}: {hints.get(exc.code, 'Check the Colab server.')} {detail}"
        ) from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(
            "Connection failed or timed out. Keep Colab connected, copy its current "
            "HTTPS URL, and increase --timeout for slow generation."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("The endpoint returned non-JSON data; check the ngrok URL.") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Expected a JSON object from the API.")
    return result


def main(argv: list[str] | None = None) -> int:
    """Check readiness, list models, and request a Vietnamese completion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("QWEN_BASE_URL"))
    parser.add_argument("--prompt", default="Giải thích RAG bằng tiếng Việt trong 3 câu.")
    parser.add_argument("--system", default="You are a helpful assistant. Respond in Vietnamese.")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--thinking", action="store_true", help="Enable thinking; output includes its raw text.")
    parser.add_argument("--json", action="store_true", help="Print the full completion response.")
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("Provide --base-url or set QWEN_BASE_URL to the Colab HTTPS URL.")
    if not 1 <= args.max_tokens <= 1024:
        parser.error("--max-tokens must be between 1 and 1024.")
    if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
        parser.error("--temperature must be finite and between 0 and 2.")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive.")
    try:
        base_url = normalize_base_url(args.base_url)
        api_key = os.getenv("QWEN_API_KEY") or getpass.getpass("QWEN_API_KEY: ")
        if not api_key.strip():
            raise ValueError("API key is required.")
        health = request_json(base_url, "/health", api_key, timeout=args.timeout)
        if health.get("status") != "ok" or health.get("model") != MODEL_ID:
            raise RuntimeError("The endpoint did not report the expected ready model.")
        models = request_json(base_url, "/v1/models", api_key, timeout=args.timeout)
        if not any(model.get("id") == MODEL_ID for model in models.get("data", [])):
            raise RuntimeError(f"The endpoint does not advertise {MODEL_ID}.")
        started = perf_counter()
        response = request_json(
            base_url,
            "/v1/chat/completions",
            api_key,
            payload={
                "model": MODEL_ID,
                "messages": [
                    {"role": "system", "content": args.system},
                    {"role": "user", "content": args.prompt},
                ],
                "max_tokens": args.max_tokens,
                "temperature": args.temperature,
                "enable_thinking": args.thinking,
                "stream": False,
            },
            timeout=args.timeout,
        )
        try:
            content = response["choices"][0]["message"]["content"]
            finish_reason = response["choices"][0]["finish_reason"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Malformed chat completion response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("The model returned no text; check Colab and the output budget.")
        print(json.dumps(response, ensure_ascii=False, indent=2) if args.json else content)
        print(
            f"\nElapsed: {perf_counter() - started:.1f}s | "
            f"Usage: {response.get('usage', {})} | Finish: {finish_reason}",
            file=sys.stderr,
        )
        return 0
    except (RuntimeError, ValueError, EOFError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
