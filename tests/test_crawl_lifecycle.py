"""Offline regression tests for crawler task and HTTP session lifecycles."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
from dataclasses import dataclass
import importlib.util
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


CRAWL_PATH = Path(__file__).resolve().parents[1] / "Scripts/Clawler/crawl.py"
DISCONNECT_ERROR = "BrowserContext.new_page: Connection closed"


@dataclass(frozen=True)
class SourceRecord:
    row_index: int
    id: int
    url: str


@dataclass(frozen=True)
class CrawlOutcome:
    record: SourceRecord
    payload: dict[str, object]
    mode: str
    elapsed_seconds: float = 0.0
    attempts: int = 1
    used_fallback: bool = False
    fallback_error: str = ""


class FakeWriter:
    def __init__(self) -> None:
        self.completed_ids: dict[int, str] = {}
        self.rows: list[dict[str, object]] = []

    def __enter__(self) -> FakeWriter:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, row: dict[str, object]) -> None:
        self.rows.append(row)


def load_crawl_module(
    records: list[SourceRecord],
) -> tuple[ModuleType, FakeWriter, list[object]]:
    """Import crawl.py against small in-memory substitutes for external services."""
    crawlers: list[object] = []
    writer = FakeWriter()

    class FakeCrawler:
        def __init__(self, **kwargs: object) -> None:
            self.kind = "http" if "crawler_strategy" in kwargs else "browser"
            self.generation = 1 + sum(
                crawler.kind == self.kind for crawler in crawlers
            )
            crawlers.append(self)

        async def __aenter__(self) -> FakeCrawler:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    crawl4ai = ModuleType("crawl4ai")
    crawl4ai.AsyncWebCrawler = FakeCrawler
    crawl4ai.BrowserConfig = lambda **kwargs: SimpleNamespace(**kwargs)

    strategy = ModuleType("crawl4ai.async_crawler_strategy")
    strategy.AsyncHTTPCrawlerStrategy = lambda: object()

    fetch = ModuleType("fetch")
    fetch.CrawlOutcome = CrawlOutcome
    fetch.crawl_one = lambda *_args: None
    fetch.is_browser_disconnected = lambda error: DISCONNECT_ERROR in error

    site_configs = ModuleType("site_configs")
    site_configs.build_run_configs = lambda: (object(), {})

    utils = ModuleType("utils")
    utils.JsonlWriter = lambda _output, **_kwargs: writer
    utils.SourceRecord = SourceRecord
    utils.get_row_count = lambda _source: len(records)
    utils.load_url_range = lambda *_args: iter([records])

    psutil = ModuleType("psutil")
    psutil.virtual_memory = lambda: SimpleNamespace(available=10**12)

    stubs = {
        "crawl4ai": crawl4ai,
        "crawl4ai.async_crawler_strategy": strategy,
        "fetch": fetch,
        "site_configs": site_configs,
        "utils": utils,
        "psutil": psutil,
    }
    spec = importlib.util.spec_from_file_location("crawl_lifecycle_subject", CRAWL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import crawler from {CRAWL_PATH}")
    subject = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(subject)
    return subject, writer, crawlers


def make_args(
    records: list[SourceRecord], fetch_mode: str, recycle_after: int = 1
) -> argparse.Namespace:
    return argparse.Namespace(
        start=records[0].row_index,
        end=records[-1].row_index,
        batch_size=len(records),
        concurrency=2,
        http_concurrency=2,
        fetch_mode=fetch_mode,
        light_browser=False,
        avoid_ads=False,
        browser_recycle_after=recycle_after,
        min_free_memory_gb=0.0,
        input=Path("unused.parquet"),
    )


def successful_outcome(record: SourceRecord, mode: str) -> CrawlOutcome:
    return CrawlOutcome(
        record=record,
        payload={
            "row_index": record.row_index,
            "id": record.id,
            "url": record.url,
            "text": "Article body",
            "success": True,
        },
        mode=mode,
    )


class TestCrawlLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_rate_limits_stop_before_rest_of_shard(self) -> None:
        records = [
            SourceRecord(index, 583 + index, f"https://example.test/{index}")
            for index in range(6)
        ]
        subject, writer, _ = load_crawl_module(records)
        args = make_args(records, "auto", recycle_after=10)
        args.max_in_flight = 1
        args.max_consecutive_blocked = 3
        attempted: list[int] = []

        async def crawl_one(record: SourceRecord, *_args: object) -> CrawlOutcome:
            attempted.append(record.row_index)
            return CrawlOutcome(
                record=record,
                payload={
                    "row_index": record.row_index,
                    "id": record.id,
                    "url": record.url,
                    "text": "",
                    "success": False,
                    "error": "HTTP request failed: HTTP 429",
                },
                mode="none",
            )

        subject.crawl_one = crawl_one
        with self.assertRaisesRegex(RuntimeError, "3 consecutive HTTP 403/429"):
            await subject.run_job(args, Path("unused.jsonl"))
        self.assertEqual(attempted, [0, 1, 2])
        self.assertEqual(len(writer.rows), 3)

    async def test_max_in_flight_one_processes_urls_serially(self) -> None:
        records = [
            SourceRecord(index, 583 + index, f"https://example.test/{index}")
            for index in range(3)
        ]
        subject, writer, _ = load_crawl_module(records)
        args = make_args(records, "auto", recycle_after=10)
        args.max_in_flight = 1
        running = peak = 0

        async def crawl_one(record: SourceRecord, *_args: object) -> CrawlOutcome:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return successful_outcome(record, "http")

        subject.crawl_one = crawl_one
        await subject.run_job(args, Path("unused.jsonl"))
        self.assertEqual(peak, 1)
        self.assertEqual(len(writer.rows), 3)

    async def test_empty_fallback_reason_does_not_abort_job(self) -> None:
        record = SourceRecord(0, 583, "https://example.test/first")
        subject, writer, _ = load_crawl_module([record])

        async def crawl_one(*_args: object) -> CrawlOutcome:
            outcome = successful_outcome(record, "browser")
            return CrawlOutcome(
                record=outcome.record,
                payload=outcome.payload,
                mode=outcome.mode,
                used_fallback=True,
            )

        subject.crawl_one = crawl_one
        await subject.run_job(make_args([record], "auto", recycle_after=10), Path("unused.jsonl"))
        self.assertEqual(len(writer.rows), 1)

    async def test_disconnect_cancels_and_requeues_active_tasks(self) -> None:
        records = [
            SourceRecord(0, 583, "https://example.test/first"),
            SourceRecord(1, 584, "https://example.test/second"),
        ]
        subject, writer, crawlers = load_crawl_module(records)
        active_tasks: list[asyncio.Task[CrawlOutcome]] = []
        cancelled_rows: list[int] = []
        retried_rows: list[int] = []

        async def crawl_one(record: SourceRecord, browser: object, *_args: object) -> CrawlOutcome:
            if browser.generation == 1:
                active_tasks.append(asyncio.current_task())
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled_rows.append(record.row_index)
                    raise
            retried_rows.append(record.row_index)
            return successful_outcome(record, "browser")

        original_wait = asyncio.wait
        raised = False

        async def disconnect_once(
            tasks: object, *, timeout: float | None = None, return_when: object
        ) -> object:
            nonlocal raised
            if not raised:
                raised = True
                await asyncio.sleep(0)
                raise RuntimeError(DISCONNECT_ERROR)
            return await original_wait(tasks, timeout=timeout, return_when=return_when)

        class AsyncioProxy:
            wait = staticmethod(disconnect_once)

            def __getattr__(self, name: str) -> object:
                return getattr(asyncio, name)

        subject.crawl_one = crawl_one
        subject.asyncio = AsyncioProxy()
        try:
            await asyncio.wait_for(
                subject.run_job(
                    make_args(records, "browser", recycle_after=10),
                    Path("unused.jsonl"),
                ),
                timeout=2,
            )
            self.assertTrue(raised)
            self.assertEqual(sorted(cancelled_rows), [0, 1])
            self.assertEqual(sorted(retried_rows), [0, 1])
            self.assertEqual(sorted(row["row_index"] for row in writer.rows), [0, 1])
            self.assertEqual(sum(crawler.kind == "browser" for crawler in crawlers), 2)
        finally:
            for task in active_tasks:
                if not task.done():
                    task.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)

    async def test_http_mode_does_not_recycle_browser_lifecycle(self) -> None:
        records = [
            SourceRecord(index, 583 + index, f"https://example.test/{index}")
            for index in range(3)
        ]
        subject, writer, crawlers = load_crawl_module(records)

        async def crawl_one(
            record: SourceRecord, browser: object, http: object, *_args: object
        ) -> CrawlOutcome:
            self.assertIsNone(browser)
            self.assertIsNotNone(http)
            return successful_outcome(record, "http")

        subject.crawl_one = crawl_one
        await asyncio.wait_for(
            subject.run_job(make_args(records, "http"), Path("unused.jsonl")),
            timeout=2,
        )
        self.assertEqual(sorted(row["row_index"] for row in writer.rows), [0, 1, 2])
        self.assertEqual(sum(crawler.kind == "http" for crawler in crawlers), 1)
        self.assertFalse(any(crawler.kind == "browser" for crawler in crawlers))

    async def test_auto_http_successes_do_not_recycle_browser(self) -> None:
        records = [
            SourceRecord(index, 583 + index, f"https://example.test/{index}")
            for index in range(5)
        ]
        subject, writer, crawlers = load_crawl_module(records)

        async def crawl_one(record: SourceRecord, *_args: object) -> CrawlOutcome:
            return successful_outcome(record, "http")

        subject.crawl_one = crawl_one
        await asyncio.wait_for(
            subject.run_job(make_args(records, "auto", recycle_after=1), Path("unused.jsonl")),
            timeout=2,
        )
        self.assertEqual(len(writer.rows), len(records))
        self.assertEqual(sum(crawler.kind == "http" for crawler in crawlers), 1)
        self.assertEqual(sum(crawler.kind == "browser" for crawler in crawlers), 1)

    async def test_progress_reports_when_requests_have_not_finished(self) -> None:
        record = SourceRecord(0, 583, "https://example.test/slow")
        subject, writer, _ = load_crawl_module([record])
        subject.PROGRESS_INTERVAL_SECONDS = 0.01

        async def crawl_one(*_args: object) -> CrawlOutcome:
            await asyncio.sleep(0.04)
            return successful_outcome(record, "http")

        subject.crawl_one = crawl_one
        output = StringIO()
        with redirect_stdout(output):
            await subject.run_job(make_args([record], "auto"), Path("unused.jsonl"))
        self.assertIn("[Progress] 0/1", output.getvalue())
        self.assertEqual(len(writer.rows), 1)


if __name__ == "__main__":
    unittest.main()
