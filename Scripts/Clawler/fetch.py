"""Fetch one source record with Crawl4AI HTTP and browser strategies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from time import monotonic
from urllib.parse import urlsplit

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

from pagination import (
    MAX_ARTICLE_PAGES,
    wujue_first_page_url,
    wujue_page_links,
    wujue_page_markdown,
    wujue_page_number,
)
from quality import ARTICLE_LAYOUTS, http_article_error
from utils import SourceRecord
from verbatim import clean_to_verbatim


MAX_BROWSER_RETRIES = 1
MAX_HTTP_RETRIES = 1
HTTP_REQUEST_TIMEOUT_SECONDS = 15
BROWSER_REQUEST_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 30
TRANSIENT_STATUS_CODES = {408, 425, 429}
HTTP_STATUS_RE = re.compile(r"\bHTTP\s+([1-5]\d{2})\b", re.IGNORECASE)
INLINE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(data:image/[^)\s]+\)", re.IGNORECASE)
BROWSER_DISCONNECT_MESSAGES = (
    "Connection closed while reading from the driver",
    "BrowserContext.new_page: Connection closed",
    "Target page, context or browser has been closed",
)
BOILERPLATE_PATTERNS = (
    re.compile(r"copyright\s*©.*(?:all\s+rights\s+reserved|版权所有)", re.IGNORECASE),
    re.compile(r"^(?:出错提示|页面不存在|404\s+not\s+found|403\s+forbidden)", re.IGNORECASE),
    re.compile(r"抱歉[，,]\s*您(?:访问|查看)的页面(?:不存在|已删除)", re.IGNORECASE),
    re.compile(r"^(?:bài\s+viết|trang)\s+(?:không\s+tồn\s+tại|đã\s+bị\s+xóa)", re.IGNORECASE),
    re.compile(r"(?:performing security verification|security service to protect against malicious bots|attention required! \| cloudflare)", re.IGNORECASE),
)


def is_boilerplate_text(text: str) -> bool:
    """Determine whether cleaned text is empty, too short, or merely a boilerplate disclaimer/error."""
    stripped = text.strip()
    if len(stripped) < 40:
        return True
    if len(stripped) < 250:
        for pat in BOILERPLATE_PATTERNS:
            if pat.search(stripped):
                return True
    return False


@dataclass(frozen=True)
class CrawlOutcome:
    """Keep the source record attached to an asynchronously completed result."""

    record: SourceRecord
    payload: dict[str, object]
    mode: str
    elapsed_seconds: float
    attempts: int
    used_fallback: bool
    fallback_error: str = ""


def get_markdown_candidates(result: object) -> list[str]:
    """Return cleaned Markdown first and raw Markdown when available."""
    markdown = getattr(result, "markdown", None)
    fit = getattr(markdown, "fit_markdown", None)
    raw = getattr(markdown, "raw_markdown", None)
    candidates = []
    for value in (fit, raw):
        if not isinstance(value, str):
            continue
        text = INLINE_IMAGE_RE.sub(lambda match: match.group(1).strip(), value).strip()
        if text and not text.startswith("Error generating fit markdown:") and text not in candidates:
            candidates.append(text)
    return candidates


def is_transient_status(status: int | None) -> bool:
    return status is None or status in TRANSIENT_STATUS_CODES or status >= 500


def _status_from_error(error_message: str) -> int | None:
    """Recover status codes that Crawl4AI includes only in its error message."""
    match = HTTP_STATUS_RE.search(error_message)
    return int(match.group(1)) if match else None


def is_browser_disconnected(error: str) -> bool:
    """Identify a dead Playwright browser rather than a per-URL failure."""
    return any(message in error for message in BROWSER_DISCONNECT_MESSAGES)


def is_unreachable_error(error: str) -> bool:
    """Identify network failures where Chromium on the same IP is guaranteed to fail as well."""
    err_lower = error.lower()
    return any(
        needle in err_lower
        for needle in (
            "timeouterror",
            "timed out",
            "connection refused",
            "cannot connect to host",
            "name or service not known",
            "getaddrinfo failed",
            "network is unreachable",
            "http 404",
            "http 410",
            "http 428",
        )
    )


def page_error(text: str) -> str | None:
    """Recognize short browser challenge or application error pages."""
    if len(text) > 600:
        return None
    content = text.lstrip("# \n").lower()
    if (
        content.startswith(("checking your browser", "this will only take a few seconds", "just a moment"))
        or "performing security verification" in content
        or "security service to protect against malicious bots" in content
        or "attention required! | cloudflare" in content
        or "verify you are human" in content
    ):
        return "Browser verification page instead of article content"
    if content.startswith("application error:"):
        return "Website application error instead of article content"
    return None


def homepage_redirect_error(url: str, result: object) -> str | None:
    """Reject article URLs that resolve to a site's homepage."""
    redirected_url = getattr(result, "redirected_url", None)
    if not isinstance(redirected_url, str):
        return None
    try:
        if urlsplit(url).path.strip("/") and not urlsplit(redirected_url).path.strip("/"):
            return f"Article redirected to homepage: {redirected_url}"
    except ValueError:
        return None
    return None


def http_fetch_url(record: SourceRecord) -> str:
    """Avoid slower HTTP-to-HTTPS redirects while preserving the source URL."""
    if record.url.startswith("http://"):
        host = (urlsplit(record.url).hostname or "").removeprefix("www.")
        if (
            host in {"cnkang.com", "familydoctor.com.cn", "120ask.com", "zhongyibaodian.net"}
            or host.endswith(".39.net")
            or host.endswith(".familydoctor.com.cn")
            or host.endswith(".120ask.com")
        ):
            return "https://" + record.url[len("http://") :]
    return record.url


async def _fetch_with_strategy(
    crawler: AsyncWebCrawler,
    semaphore: asyncio.Semaphore,
    record: SourceRecord,
    request_url: str,
    domain: str,
    config: CrawlerRunConfig,
    strategy: str,
) -> tuple[str | None, str, int, object | None]:
    """Retry one strategy without occupying a concurrency slot during backoff."""
    max_retries = MAX_HTTP_RETRIES if strategy == "http" else MAX_BROWSER_RETRIES
    timeout = HTTP_REQUEST_TIMEOUT_SECONDS if strategy == "http" else BROWSER_REQUEST_TIMEOUT_SECONDS
    error_message = "Unknown crawl error"
    for attempt in range(max_retries + 1):
        status: int | None = None
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    crawler.arun(url=request_url, config=config),
                    timeout=timeout,
                )
            status = getattr(result, "status_code", None)
            redirect_error = homepage_redirect_error(record.url, result)
            if redirect_error:
                return None, redirect_error, attempt + 1, None
            content_error = None
            if getattr(result, "success", False):
                for text in get_markdown_candidates(result):
                    content_error = page_error(text)
                    if content_error is None and strategy == "http":
                        content_error = http_article_error(domain, result, text)
                    if content_error is None:
                        return text, "", attempt + 1, result
            error_message = content_error or str(getattr(result, "error_message", "") or "")
            if not error_message:
                error_message = "Empty Markdown" if getattr(result, "success", False) else f"HTTP {status or 'unknown'}"
            if status is None:
                status = _status_from_error(error_message)
            if is_browser_disconnected(error_message):
                break
            if getattr(result, "success", False) and content_error:
                break
            if not is_transient_status(status):
                break
        except Exception as error:
            error_message = f"{type(error).__name__}: {error}"
            status = getattr(error, "status_code", None) or _status_from_error(error_message)
            if is_browser_disconnected(error_message):
                break
            if isinstance(error, asyncio.TimeoutError) or "timeouterror" in error_message.lower():
                break
            if not is_transient_status(status):
                break
        if attempt < max_retries:
            await asyncio.sleep(2**attempt)
    return None, error_message, attempt + 1, None


async def _fetch_wujue_subpage(
    record: SourceRecord,
    url: str,
    http: AsyncWebCrawler | None,
    browser: AsyncWebCrawler | None,
    http_semaphore: asyncio.Semaphore,
    browser_semaphore: asyncio.Semaphore,
    config: CrawlerRunConfig,
    fetch_mode: str,
) -> tuple[str | None, str, int, bool]:
    """Fetch a numbered article page, falling back to Chromium when needed."""
    attempts = 0
    http_error = ""
    if fetch_mode != "browser" and http is not None:
        _, http_error, count, result = await _fetch_with_strategy(
            http, http_semaphore, record, url, "wujue.com", config, "http"
        )
        attempts += count
        if result is not None:
            return str(getattr(result, "html", "")), "", attempts, False
    if fetch_mode != "http" and browser is not None:
        _, browser_error, count, result = await _fetch_with_strategy(
            browser, browser_semaphore, record, url, "wujue.com", config, "browser"
        )
        attempts += count
        if result is not None:
            return str(getattr(result, "html", "")), "", attempts, True
        error = f"HTTP: {http_error}; Browser: {browser_error}" if http_error else browser_error
        return None, error, attempts, True
    return None, http_error or "No available crawler for article subpage", attempts, False


async def _complete_wujue_article(
    record: SourceRecord,
    initial_result: object,
    http: AsyncWebCrawler | None,
    browser: AsyncWebCrawler | None,
    http_semaphore: asyncio.Semaphore,
    browser_semaphore: asyncio.Semaphore,
    config: CrawlerRunConfig,
    fetch_mode: str,
) -> tuple[str | None, str, int, bool, int]:
    """Discover and combine all numbered pages of one Wujue article."""
    initial_html = getattr(initial_result, "html", None)
    if not isinstance(initial_html, str) or not initial_html:
        return None, "Article HTML is unavailable for pagination", 0, False, 0
    initial_page = wujue_page_number(record.url)
    pages = {initial_page: (record.url, initial_html)}
    discovered = {1: wujue_first_page_url(record.url), initial_page: record.url}
    discovered.update(wujue_page_links(record.url, initial_html))
    attempts = 0
    used_browser = False

    while pending := [page for page in sorted(discovered) if page not in pages]:
        if len(discovered) > MAX_ARTICLE_PAGES:
            return None, f"Article exceeds {MAX_ARTICLE_PAGES} pages", attempts, used_browser, len(pages)
        group = pending[:10]
        results = await asyncio.gather(
            *(
                _fetch_wujue_subpage(
                    record,
                    discovered[page],
                    http,
                    browser,
                    http_semaphore,
                    browser_semaphore,
                    config,
                    fetch_mode,
                )
                for page in group
            )
        )
        for page, (html, error, count, browser_fallback) in zip(group, results, strict=True):
            attempts += count
            used_browser = used_browser or browser_fallback
            if html is None:
                return None, f"Article page {page} failed: {error}", attempts, used_browser, len(pages)
            page_url = discovered[page]
            pages[page] = (page_url, html)
            discovered.update(wujue_page_links(page_url, html))

    if len(pages) > MAX_ARTICLE_PAGES:
        return None, f"Article exceeds {MAX_ARTICLE_PAGES} pages", attempts, used_browser, len(pages)
    if set(pages) != set(range(1, max(pages) + 1)):
        return None, "Article pagination has missing page numbers", attempts, used_browser, len(pages)
    try:
        parts = [
            wujue_page_markdown(*pages[page], include_title=page == 1)
            for page in sorted(pages)
        ]
    except ValueError as error:
        return None, str(error), attempts, used_browser, len(pages)
    if any(not part for part in parts):
        return None, "Article has an empty numbered page", attempts, used_browser, len(pages)
    return "\n\n".join(parts), "", attempts, used_browser, len(pages)


async def crawl_one(
    record: SourceRecord,
    browser: AsyncWebCrawler | None,
    http: AsyncWebCrawler | None,
    browser_semaphore: asyncio.Semaphore,
    http_semaphore: asyncio.Semaphore,
    run_config: CrawlerRunConfig,
    domain_configs: dict[str, CrawlerRunConfig],
    fetch_mode: str,
) -> CrawlOutcome:
    """Crawl one original ID/URL, using Chromium if validated HTTP is insufficient."""
    started = monotonic()
    payload: dict[str, object] = {
        "row_index": record.row_index,
        "id": record.id,
        "url": record.url,
        "text": "",
    }
    try:
        domain = (urlsplit(record.url).hostname or "").removeprefix("www.")
    except ValueError as error:
        domain = ""
        validation_error = f"Invalid URL: {error}"
    else:
        validation_error = None if record.url.startswith(("http://", "https://")) else "Missing or unsupported URL"
    if validation_error:
        payload.update(success=False, error=validation_error)
        return CrawlOutcome(record, payload, "none", monotonic() - started, 0, False)

    config = domain_configs.get(domain)
    if domain == "nhathuoclongchau.com.vn" and urlsplit(record.url).path.startswith("/benh/"):
        config = domain_configs["nhathuoclongchau.com.vn/benh"]
    if config is None and domain.endswith(".39.net"):
        config = domain_configs["39.net"]
    config = config or run_config

    attempts = 0
    http_error = ""
    http_attempted = False
    wujue_http_pagination_failed = False
    try_http = fetch_mode in ("auto", "http")
    if try_http and http is not None:
        http_attempted = True
        text, http_error, count, result = await _fetch_with_strategy(
            http, http_semaphore, record, http_fetch_url(record), domain, config, "http"
        )
        attempts += count
        if text is not None:
            used_browser = False
            if domain == "wujue.com":
                try:
                    text, pagination_error, count, used_browser, page_count = await _complete_wujue_article(
                        record, result, http, browser, http_semaphore, browser_semaphore,
                        config, fetch_mode,
                    )
                except Exception as error:
                    text = None
                    http_error = f"Article pagination failed: {type(error).__name__}: {error}"
                    wujue_http_pagination_failed = True
                else:
                    attempts += count
                    if text is None:
                        http_error = pagination_error
                        wujue_http_pagination_failed = True
                    else:
                        payload["page_count"] = page_count
            if text is not None:
                try:
                    verbatim_text = clean_to_verbatim(text)
                except Exception as error:
                    http_error = f"Text cleaning failed: {type(error).__name__}: {error}"
                else:
                    if is_boilerplate_text(verbatim_text):
                        http_error = "Empty or boilerplate text after cleaning"
                    else:
                        payload.update(text=verbatim_text, success=True)
                        return CrawlOutcome(
                            record, payload, "browser" if used_browser else "http",
                            monotonic() - started, attempts, used_browser,
                            "Wujue numbered page required Chromium" if used_browser else "",
                        )
        if fetch_mode == "http":
            payload.update(success=False, text="", error=http_error)
            return CrawlOutcome(record, payload, "http", monotonic() - started, attempts, False)

    if browser is None:
        payload.update(success=False, text="", error=http_error or "Browser is unavailable")
        return CrawlOutcome(record, payload, "none", monotonic() - started, attempts, False)
    if http_attempted and not http_error:
        http_error = "HTTP article validation failed"
    if http_attempted and is_unreachable_error(http_error):
        payload.update(success=False, text="", error=http_error)
        return CrawlOutcome(record, payload, "http", monotonic() - started, attempts, False)
    text, browser_error, count, result = await _fetch_with_strategy(
        browser, browser_semaphore, record, record.url, domain, config, "browser"
    )
    attempts += count
    if text is not None:
        if domain == "wujue.com":
            text, pagination_error, count, _, page_count = await _complete_wujue_article(
                record, result, http, browser, http_semaphore, browser_semaphore,
                config, "browser" if wujue_http_pagination_failed else fetch_mode,
            )
            attempts += count
            if text is None:
                browser_error = pagination_error
            else:
                payload["page_count"] = page_count
        if text is not None:
            try:
                verbatim_text = clean_to_verbatim(text)
            except Exception as error:
                browser_error = f"Text cleaning failed: {type(error).__name__}: {error}"
                text = None
            else:
                if not is_boilerplate_text(verbatim_text):
                    payload.update(text=verbatim_text, success=True)
                else:
                    browser_error = "Empty or boilerplate text after cleaning"
                    text = None
    if text is None:
        error_message = f"HTTP: {http_error}; Browser: {browser_error}" if http_error else browser_error
        payload.update(success=False, text="", error=error_message)
    return CrawlOutcome(
        record, payload, "browser", monotonic() - started, attempts,
        http_attempted, http_error,
    )
