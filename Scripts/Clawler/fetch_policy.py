"""Shared request admission, cooldowns, and diagnostics for crawl workers."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import random
import re
from time import monotonic, time
from typing import AsyncIterator
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HostPolicy:
    """Bound all strategies together within a hostname or explicit host group."""

    concurrency: int = 2
    interval_seconds: float = 1.0
    cooldown_seconds: float = 600.0
    group: str = ""
    max_attempts: int = 3
    fetch_mode: str = "auto"
    minimum_interval_seconds: float | None = None
    recovery_successes: int = 20

    def __post_init__(self) -> None:
        if type(self.concurrency) is not int or type(self.max_attempts) is not int or self.concurrency < 1 or self.max_attempts < 1:
            raise ValueError("Policy concurrency and max_attempts must be positive")
        for value in (self.interval_seconds, self.cooldown_seconds):
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise ValueError("Policy delays must be finite and nonnegative")
        if not isinstance(self.group, str):
            raise ValueError("Policy group must be a string")
        if self.fetch_mode not in {"auto", "http", "browser"}:
            raise ValueError("Policy fetch_mode must be auto, http, or browser")
        if self.minimum_interval_seconds is not None and (
            type(self.minimum_interval_seconds) not in {int, float}
            or not math.isfinite(self.minimum_interval_seconds)
            or not 0 <= self.minimum_interval_seconds <= self.interval_seconds
        ):
            raise ValueError("Minimum interval must be between zero and the starting interval")
        if type(self.recovery_successes) is not int or self.recovery_successes < 1:
            raise ValueError("Recovery successes must be a positive integer")


def hostname(url: str) -> str:
    """Normalize hostnames without merging unrelated suffixes."""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def default_policy(host: str) -> HostPolicy:
    if host == "39.net" or host.endswith(".39.net"):
        return HostPolicy(2, 3.0, 900.0, "39.net")
    if host == "nhathuoclongchau.com.vn":
        return HostPolicy(1, 2.5, 900.0, fetch_mode="browser")
    if host in {"pmc-ecm-healthblog.beta.pharmacity.io", "article.iiyi.com"}:
        return HostPolicy(1, 3.0, 900.0)
    return HostPolicy()


def read_policies(path: Path | None) -> dict[str, HostPolicy]:
    """Load optional exact-host overrides from a JSON object."""
    if path is None:
        return {}
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Host policy file must contain an object")
    return {host: HostPolicy(**value) for host, value in values.items()}


def retry_after_seconds(value: str | None, now: float | None = None) -> float | None:
    """Parse both Retry-After formats; never shorten a server-requested wait."""
    if not value:
        return None
    now = time() if now is None else now
    try:
        if value.strip().isdigit():
            return float(int(value.strip()))
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, date.timestamp() - now)
    except (TypeError, ValueError, OverflowError):
        return None


def classify_error(status: int | None, error: str) -> str:
    """Distinguish source denials from transport and article extraction errors."""
    lowered = error.lower()
    if any(value in lowered for value in ("object has no attribute", "unexpected keyword argument", "modulenotfounderror", "importerror")):
        return "configuration_error"
    if "deferredrequest" in lowered:
        return "deferred"
    if "robots.txt" in lowered and any(value in lowered for value in ("disallow", "denied", "not allowed", "blocked")):
        return "robots_denied"
    if "unsupported content type" in lowered or "response exceeds" in lowered:
        return "unsupported_content"
    if status == 429:
        return "rate_limited"
    if any(value in lowered for value in (
        "verification page", "verify you are human", "just a moment",
        "security verification", "captcha", "cloudflare",
    )):
        return "challenge"
    if status in {401, 403}:
        return "access_denied"
    if status in {404, 410}:
        return "not_found"
    if status is not None and status >= 500:
        return "server_error"
    if "browser" in lowered and any(value in lowered for value in ("closed", "disconnected")):
        return "browser_disconnected"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "invalid url" in lowered or "unsupported url" in lowered:
        return "invalid_url"
    if any(value in lowered for value in ("markdown", "article", "boilerplate", "cleaning")):
        return "incomplete_content"
    return "transport" if error else "success"


def error_status(error: str) -> int | None:
    match = re.search(r"\bHTTP\s+([1-5]\d{2})\b", error, re.IGNORECASE)
    return int(match.group(1)) if match else None


class DeferredRequest(RuntimeError):
    """Return control to the campaign while this source is cooling down."""


@dataclass
class HostState:
    active: int = 0
    next_start: float = 0.0
    cooldown_until: float = 0.0
    interval: float = 0.0
    blocked_streak: int = 0
    recent_blocks: deque[bool] = field(default_factory=lambda: deque(maxlen=50))
    healthy: int = 0
    server_error_streak: int = 0
    transport_error_streak: int = 0


class FetchController:
    """Coordinate HTTP, browser, retries, and pagination within one worker."""

    def __init__(self, policies: dict[str, HostPolicy] | None = None) -> None:
        self.policies = policies or {}
        self.states: dict[str, HostState] = {}
        self._lock = asyncio.Lock()
        self.host_active: dict[str, int] = {}
        self.attempt_sink = None
        # Policies sharing a group must agree, or admission would depend on order.
        grouped: dict[str, HostPolicy] = {}
        for policy in self.policies.values():
            if policy.group:
                previous = grouped.setdefault(policy.group, policy)
                if previous != policy:
                    raise ValueError(f"Conflicting policies for group {policy.group}")
        self.group_policies = grouped

    def policy(self, url: str) -> tuple[str, HostPolicy]:
        host = hostname(url)
        policy = self.policies.get(host, default_policy(host))
        if policy.group:
            policy = self.group_policies.get(policy.group, policy)
        return policy.group or host, policy

    def state(self, url: str) -> tuple[HostState, HostPolicy]:
        key, policy = self.policy(url)
        return self.states.setdefault(key, HostState(interval=policy.interval_seconds)), policy

    def retry_at(self, url: str) -> float:
        state, _ = self.state(url)
        return time() + max(0.0, state.cooldown_until - monotonic())

    @asynccontextmanager
    async def request(self, url: str, semaphore: asyncio.Semaphore | None = None) -> AsyncIterator[None]:
        """Reserve source and global capacity together immediately before arun."""
        state, policy = self.state(url)
        host = hostname(url)
        host_limit = 1 if policy.group else policy.concurrency
        while True:
            async with self._lock:
                now = monotonic()
                if state.cooldown_until > now:
                    raise DeferredRequest(f"Source cooldown until {self.retry_at(url):.0f}")
                if (state.active < policy.concurrency
                        and self.host_active.get(host, 0) < host_limit
                        and state.next_start <= now
                        and (semaphore is None or not semaphore.locked())):
                    # acquire() cannot suspend when capacity is available. Keep
                    # pacing waiters from occupying another source's HTTP/browser slot.
                    if semaphore is not None:
                        await semaphore.acquire()
                    state.active += 1
                    self.host_active[host] = self.host_active.get(host, 0) + 1
                    state.next_start = now + state.interval * random.uniform(1.0, 1.2)
                    break
                wait = max(0.01, min(0.2, state.next_start - now))
            await asyncio.sleep(wait)
        try:
            yield
        finally:
            state.active -= 1
            self.host_active[host] -= 1
            if semaphore is not None:
                semaphore.release()

    def observe(self, url: str, status: int | None, error: str, retry_after: str | None) -> None:
        state, policy = self.state(url)
        kind = classify_error(status, error)
        blocked = kind in {"rate_limited", "access_denied", "challenge"}
        state.recent_blocks.append(blocked)
        state.blocked_streak = state.blocked_streak + 1 if blocked else 0
        server_wait = retry_after_seconds(retry_after)
        state.server_error_streak = state.server_error_streak + 1 if status is not None and status >= 500 else 0
        state.transport_error_streak = state.transport_error_streak + 1 if kind in {"timeout", "transport"} else 0
        if blocked or (status == 503 and server_wait is not None):
            # Cool down on the first denial; other sources remain runnable.
            wait = max(policy.cooldown_seconds, server_wait or 0.0)
            wait *= 2 ** min(max(0, state.blocked_streak - 1), 4)
            if state.blocked_streak < 2 and (
                len(state.recent_blocks) >= 20 and sum(state.recent_blocks) / len(state.recent_blocks) >= 0.05
            ):
                wait *= 2
            state.cooldown_until = max(state.cooldown_until, monotonic() + wait)
            state.interval = min(max(policy.interval_seconds, state.interval) * 2, max(60.0, policy.interval_seconds * 16))
            state.healthy = 0
        elif max(state.server_error_streak, state.transport_error_streak) >= 3:
            streak = max(state.server_error_streak, state.transport_error_streak)
            wait = max(60.0, policy.cooldown_seconds / 2) * 2 ** min(streak - 3, 3)
            state.cooldown_until = max(state.cooldown_until, monotonic() + wait)
            state.interval = min(max(policy.interval_seconds, state.interval) * 2, max(60.0, policy.interval_seconds * 16))
            state.healthy = 0
        elif kind == "success":
            state.healthy += 1
            if state.healthy >= policy.recovery_successes:
                floor = policy.interval_seconds if policy.minimum_interval_seconds is None else policy.minimum_interval_seconds
                state.interval = max(floor, state.interval * 0.8)
                state.healthy = 0
        else:
            state.healthy = 0


active_controller: ContextVar[FetchController | None] = ContextVar("fetch_controller", default=None)
attempt_trace: ContextVar[list[dict[str, object]] | None] = ContextVar("attempt_trace", default=None)


def record_attempt(value: dict[str, object]) -> None:
    """Retain per-document diagnostics and optionally stream each real attempt."""
    trace = attempt_trace.get()
    if trace is not None:
        trace.append(value)
    controller = active_controller.get()
    if controller is not None and controller.attempt_sink is not None:
        controller.attempt_sink(value)
