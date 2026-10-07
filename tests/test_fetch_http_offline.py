"""Offline tests for HTTP retry classification and browser fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
from time import monotonic
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))


@dataclass(frozen=True)
class SourceRecord:
    row_index: int
    id: int
    url: str


def load_fetch_module() -> ModuleType:
    """Load the real fetch module without Crawl4AI in the Conda environment."""
    modules = {name: ModuleType(name) for name in (
        "crawl4ai", "pagination", "quality", "utils", "verbatim"
    )}
    modules["crawl4ai"].AsyncWebCrawler = object
    modules["crawl4ai"].CrawlerRunConfig = object
    modules["pagination"].MAX_ARTICLE_PAGES = 40
    for name in (
        "wujue_first_page_url", "wujue_page_links", "wujue_page_markdown",
        "wujue_page_number",
    ):
        setattr(modules["pagination"], name, lambda *args, **kwargs: None)
    modules["quality"].ARTICLE_LAYOUTS = {}
    modules["quality"].http_article_error = lambda *args: None
    modules["quality"].article_metadata = lambda *args: {}
    modules["utils"].SourceRecord = SourceRecord
    modules["verbatim"].clean_to_verbatim = lambda text: text

    module_path = Path(__file__).resolve().parents[1] / "Scripts/Clawler/fetch.py"
    spec = importlib.util.spec_from_file_location("fetch_under_test", module_path)
    assert spec is not None and spec.loader is not None
    fetch = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**modules, "fetch_under_test": fetch}):
        spec.loader.exec_module(fetch)
    return fetch


def make_result(text: str, *, success: bool = True, error: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        success=success,
        error_message=error,
        status_code=None,
        redirected_url=None,
        html="<article>valid article</article>",
        markdown=SimpleNamespace(fit_markdown=text, raw_markdown=text),
    )


def test_permanent_http_status_in_wrapped_error_is_not_retried() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    for status in (403, 404):
        crawler = SimpleNamespace(arun=AsyncMock(return_value=make_result(
            "", success=False,
            error=f"Unexpected error in _crawl_web:\nError: HTTP {status}: Unexpected status code",
        )))
        with patch.object(fetch.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            text, error, count, result = asyncio.run(fetch._fetch_with_strategy(
                crawler, asyncio.Semaphore(1), record, record.url, "example.org",
                object(), "http",
            ))
        assert text is None and result is None
        assert f"HTTP {status}" in error
        assert count == 1
        crawler.arun.assert_awaited_once()
        sleep.assert_not_awaited()


def test_transient_http_status_is_retried_once() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    crawler = SimpleNamespace(arun=AsyncMock(return_value=make_result(
        "", success=False, error="Error: HTTP 429: Unexpected status code"
    )))
    with patch.object(fetch.asyncio, "sleep", new_callable=AsyncMock) as sleep, patch.object(fetch.random, "uniform", return_value=1):
        _, _, count, _ = asyncio.run(fetch._fetch_with_strategy(
            crawler, asyncio.Semaphore(1), record, record.url, "example.org",
            object(), "http",
        ))
    assert count == 2
    assert crawler.arun.await_count == 2
    sleep.assert_awaited_once_with(1)


def test_auto_tries_http_for_bachmai_before_browser() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://bachmai.gov.vn/bai-viet/article")
    valid_text = "Medical article content with enough words to pass validation. " * 3
    with patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as strategy:
        strategy.side_effect = [
            (None, "HTTP Markdown is missing the title", 1, None),
            (valid_text, "", 1, make_result(valid_text)),
        ]
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "auto",
        ))

    assert [call.args[-1] for call in strategy.await_args_list] == ["http", "browser"]
    assert outcome.payload["success"] is True
    assert outcome.used_fallback is True


def test_denials_and_missing_pages_do_not_fall_back_to_browser() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    for status in (401, 403, 404, 410, 429):
        with patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as strategy:
            strategy.return_value = (None, f"HTTP {status}", 1, None)
            outcome = asyncio.run(fetch.crawl_one(
                record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
                object(), {}, "auto",
            ))
        strategy.assert_awaited_once()
        assert outcome.payload["success"] is False
        assert outcome.payload["status_code"] == status


def test_rate_limit_headers_cool_down_the_group_without_immediate_retry() -> None:
    from fetch_policy import FetchController, active_controller
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://baby.39.net/article")
    response = make_result("", success=False, error="HTTP 429")
    response.status_code = 429
    response.response_headers = {"Retry-After": "7200"}
    crawler = SimpleNamespace(arun=AsyncMock(return_value=response))
    controller = FetchController()

    async def run():
        token = active_controller.set(controller)
        try:
            return await fetch._fetch_with_strategy(crawler, asyncio.Semaphore(1), record,
                                                     record.url, "baby.39.net", object(), "http")
        finally:
            active_controller.reset(token)

    _, _, count, _ = asyncio.run(run())
    assert count == 1 and crawler.arun.await_count == 1
    assert controller.state("https://ask.39.net/x")[0].cooldown_until > monotonic() + 7199


def test_long_challenge_is_not_accepted_as_article() -> None:
    fetch = load_fetch_module()
    assert fetch.page_error("Just a moment\n" + "Security verification in progress. " * 100)


def test_longchau_auto_uses_browser_profile_without_http_probe() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://nhathuoclongchau.com.vn/bai-viet/article.html")
    text = "Validated medical article content. " * 10
    with patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as strategy:
        strategy.return_value = (text, "", 1, make_result(text))
        outcome = asyncio.run(fetch.crawl_one(record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1), object(), {}, "auto"))
    strategy.assert_awaited_once()
    assert strategy.await_args.args[-1] == "browser"
    assert outcome.payload["success"] is True
    assert outcome.used_fallback is False


def test_http_status_on_exception_is_not_retried() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")

    class HTTPError(Exception):
        status_code = 404

    crawler = SimpleNamespace(arun=AsyncMock(side_effect=HTTPError("missing article")))
    with patch.object(fetch.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        _, error, count, _ = asyncio.run(fetch._fetch_with_strategy(
            crawler, asyncio.Semaphore(1), record, record.url, "example.org",
            object(), "http",
        ))
    assert count == 1
    assert error == "HTTPError: missing article"
    sleep.assert_not_awaited()


def test_pagination_failure_falls_back_to_browser_in_auto_mode() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://wujue.com/article.html")
    valid_text = "Valid article text " * 10
    with (
        patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy,
        patch.object(fetch, "_complete_wujue_article", new_callable=AsyncMock) as paginate,
    ):
        fetch_strategy.side_effect = [
            (valid_text, "", 1, make_result(valid_text)),
            (valid_text, "", 1, make_result(valid_text)),
        ]
        paginate.side_effect = [
            (None, "Article page 2 failed", 1, False, 1),
            (valid_text, "", 0, False, 2),
        ]
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "auto",
        ))
    assert outcome.payload["success"] is True
    assert outcome.payload["text"] == valid_text
    assert outcome.mode == "browser"
    assert outcome.attempts == 3
    assert outcome.used_fallback is True
    assert outcome.fallback_error == "Article page 2 failed"
    assert fetch_strategy.await_count == 2
    assert paginate.await_args_list[1].args[-1] == "browser"


def test_pagination_exception_falls_back_to_browser_in_auto_mode() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://wujue.com/article.html")
    valid_text = "Valid article text " * 10
    with (
        patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy,
        patch.object(fetch, "_complete_wujue_article", new_callable=AsyncMock) as paginate,
    ):
        fetch_strategy.side_effect = [
            (valid_text, "", 1, make_result(valid_text)),
            (valid_text, "", 1, make_result(valid_text)),
        ]
        paginate.side_effect = [
            ValueError("invalid pagination"),
            (valid_text, "", 0, False, 2),
        ]
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "auto",
        ))
    assert outcome.payload["success"] is True
    assert outcome.mode == "browser"
    assert outcome.used_fallback is True
    assert outcome.fallback_error == "Article pagination failed: ValueError: invalid pagination"


def test_cleaning_exception_falls_back_to_browser_in_auto_mode() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    valid_text = "Valid article text " * 10
    with (
        patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy,
        patch.object(fetch, "clean_to_verbatim") as clean,
    ):
        fetch_strategy.side_effect = [
            (valid_text, "", 1, make_result(valid_text)),
            (valid_text, "", 1, make_result(valid_text)),
        ]
        clean.side_effect = [ValueError("malformed text"), valid_text]
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "auto",
        ))
    assert outcome.payload["success"] is True
    assert outcome.mode == "browser"
    assert outcome.used_fallback is True
    assert outcome.fallback_error == "Text cleaning failed: ValueError: malformed text"


def test_boilerplate_http_content_falls_back_to_browser_in_auto_mode() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    valid_text = "Valid article text " * 10
    with (
        patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy,
        patch.object(fetch, "clean_to_verbatim") as clean,
    ):
        fetch_strategy.side_effect = [
            (valid_text, "", 1, make_result(valid_text)),
            (valid_text, "", 1, make_result(valid_text)),
        ]
        clean.side_effect = ["too short", valid_text]
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "auto",
        ))
    assert outcome.payload["success"] is True
    assert outcome.used_fallback is True
    assert outcome.fallback_error == "Empty or boilerplate text after cleaning"


def test_http_only_cleaning_failure_does_not_use_browser() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    valid_text = "Valid article text " * 10
    with (
        patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy,
        patch.object(fetch, "clean_to_verbatim", return_value="too short"),
    ):
        fetch_strategy.return_value = (valid_text, "", 1, make_result(valid_text))
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "http",
        ))
    assert outcome.payload["success"] is False
    assert outcome.payload["error"] == "Empty or boilerplate text after cleaning"
    assert outcome.mode == "http"
    assert outcome.used_fallback is False
    fetch_strategy.assert_awaited_once()


def test_browser_only_does_not_report_http_fallback() -> None:
    fetch = load_fetch_module()
    record = SourceRecord(0, 101, "https://example.org/article")
    valid_text = "Valid article text " * 10
    with patch.object(fetch, "_fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy:
        fetch_strategy.return_value = (valid_text, "", 1, make_result(valid_text))
        outcome = asyncio.run(fetch.crawl_one(
            record, object(), None, asyncio.Semaphore(1), asyncio.Semaphore(1),
            object(), {}, "browser",
        ))
    assert outcome.payload["success"] is True
    assert outcome.used_fallback is False
    assert outcome.fallback_error == ""


def load_tests(loader, tests, pattern):
    """Expose the function regressions to the project's unittest runner too."""
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            tests.addTest(unittest.FunctionTestCase(function))
    return tests


if __name__ == "__main__":
    unittest.main()
