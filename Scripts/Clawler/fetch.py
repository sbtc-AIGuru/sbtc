"""Fetch one source record with Crawl4AI HTTP and browser strategies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import random
import re
from time import monotonic, time
from urllib.parse import urlsplit, urlunsplit

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

from pagination import (
    MAX_ARTICLE_PAGES,
    wujue_first_page_url,
    wujue_page_links,
    wujue_page_markdown,
    wujue_page_number,
)
from quality import article_content_issue, article_metadata, http_article_error
from utils import SourceRecord
from verbatim import clean_to_verbatim
from fetch_policy import (
    DeferredRequest, active_controller, attempt_trace, classify_error,
    default_policy, error_status, record_attempt, retry_after_seconds,
)


MAX_BROWSER_RETRIES = 3
MAX_HTTP_RETRIES = 1
REQUEST_TIMEOUT_SECONDS = 45
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


def is_boilerplate_text(text: str, minimum_characters: int = 40) -> bool:
    """Determine whether cleaned text is empty, too short, or merely a boilerplate disclaimer/error."""
    stripped = text.strip()
    if len(stripped) < minimum_characters:
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


def page_error(text: str) -> str | None:
    """Recognize short browser challenge or application error pages."""
    content = text.lstrip("# \n").lower()
    if (
        content.startswith(("checking your browser", "this will only take a few seconds", "just a moment"))
        or "performing security verification" in content
        or "security service to protect against malicious bots" in content
        or "attention required! | cloudflare" in content
        or "verify you are human" in content
        or "请完成安全验证" in content
        or "访问过于频繁" in content
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
    parsed = urlsplit(record.url)
    if parsed.hostname == "ask.familydoctor.com.cn" and parsed.path.startswith("/q/"):
        # The legacy question host redirects to this public canonical host.
        return urlunsplit(("https", "www.familydoctor.com.cn", parsed.path, parsed.query, parsed.fragment))
    if record.url.startswith("http://"):
        host = (urlsplit(record.url).hostname or "").removeprefix("www.")
        if (
            host in {"cnkang.com", "120ask.com", "zhongyibaodian.net"}
            or host.endswith(".39.net")
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
    """Pace every actual request and avoid retrying source denials in a burst."""
    max_retries = MAX_HTTP_RETRIES if strategy == "http" else MAX_BROWSER_RETRIES
    controller = active_controller.get()
    if controller is not None:
        _, policy = controller.policy(record.url)
        max_retries = min(max_retries, policy.max_attempts - 1)
    error_message = "Unknown crawl error"
    attempts = 0
    for attempt in range(max_retries + 1):
        status: int | None = None
        retry_after = None
        final_url = request_url
        request_started = monotonic()
        requested = False
        try:
            admission = controller.request(record.url, semaphore) if controller else semaphore
            async with admission:
                request_started = monotonic()
                requested = True
                attempts += 1
                result = await asyncio.wait_for(
                    crawler.arun(url=request_url, config=config),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            status = getattr(result, "redirected_status_code", None) or getattr(result, "status_code", None)
            headers = getattr(result, "response_headers", None) or {}
            retry_after = next((str(value) for key, value in headers.items() if key.lower() == "retry-after"), None)
            final_url = getattr(result, "redirected_url", None) or request_url
            redirect_error = homepage_redirect_error(record.url, result)
            if redirect_error:
                error_message = redirect_error
                return None, error_message, attempts, None
            content_error = article_content_issue(domain, result, record.url) if status == 200 else None
            if getattr(result, "success", False) and (status is None or status < 400):
                for text in get_markdown_candidates(result) if content_error is None else ():
                    content_error = page_error(text)
                    if content_error is None:
                        content_error = http_article_error(domain, result, text)
                    if content_error is None:
                        error_message = ""
                        return text, "", attempts, result
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
            if classify_error(status, error_message) in {"unsupported_content", "robots_denied", "configuration_error"}:
                break
            if controller is not None and (status == 429 or retry_after is not None):
                break
        except DeferredRequest as error:
            error_message = f"DeferredRequest: {error}"
            break
        except Exception as error:
            error_message = f"{type(error).__name__}: {error}"
            status = getattr(error, "status_code", None) or _status_from_error(error_message)
            if is_browser_disconnected(error_message):
                break
            if not is_transient_status(status):
                break
            if classify_error(status, error_message) in {"unsupported_content", "robots_denied", "configuration_error"}:
                break
        finally:
            if requested:
                if controller is not None:
                    controller.observe(record.url, status, error_message, retry_after)
                record_attempt({
                    "row_index": record.row_index, "id": record.id,
                    "source_url": record.url,
                    "request_url": request_url, "final_url": final_url,
                    "mode": strategy, "status_code": status,
                    "error_kind": classify_error(status, error_message),
                    "error": error_message, "retry_after": retry_after,
                    "elapsed_seconds": monotonic() - request_started,
                    "finished_at": time(),
                })
        if attempt < max_retries:
            server_wait = retry_after_seconds(retry_after)
            await asyncio.sleep(max(server_wait or 0.0, 2**attempt * random.uniform(0.75, 1.25)))
    return None, error_message, attempts, None


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


async def _crawl_one(
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
        domain = (urlsplit(record.url).hostname or "").lower().removeprefix("www.")
    except ValueError as error:
        domain = ""
        validation_error = f"Invalid URL: {error}"
    else:
        validation_error = None if domain and record.url.startswith(("http://", "https://")) else "Missing or unsupported URL"
        parsed = urlsplit(record.url)
        if validation_error is None and not parsed.path.strip("/") and not parsed.query:
            validation_error = "Invalid URL: source points to a homepage, not an article"
    if validation_error:
        payload.update(success=False, error=validation_error)
        return CrawlOutcome(record, payload, "none", monotonic() - started, 0, False)

    config = domain_configs.get(domain)
    if domain == "nhathuoclongchau.com.vn" and urlsplit(record.url).path.startswith("/benh/"):
        config = domain_configs["nhathuoclongchau.com.vn/benh"]
    if config is None and domain.endswith(".39.net"):
        config = domain_configs["39.net"]
    if config is None and domain.endswith(".familydoctor.com.cn"):
        config = domain_configs.get("familydoctor.com.cn")
    config = config or run_config
    minimum_characters = 8 if domain == "ask.39.net" else 40

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
                    if is_boilerplate_text(verbatim_text, minimum_characters):
                        http_error = "Empty or boilerplate text after cleaning"
                    else:
                        payload.update(text=verbatim_text, success=True)
                        payload.update(article_metadata(domain, result))
                        return CrawlOutcome(
                            record, payload, "browser" if used_browser else "http",
                            monotonic() - started, attempts, used_browser,
                            "Wujue numbered page required Chromium" if used_browser else "",
                        )
        trace = attempt_trace.get() or []
        status = trace[-1]["status_code"] if trace else error_status(http_error)
        if fetch_mode == "http" or classify_error(status, http_error) in {
            "rate_limited", "access_denied", "challenge", "not_found", "deferred", "invalid_url", "robots_denied", "unsupported_content", "configuration_error", "server_error",
        }:
            payload.update(success=False, text="", error=http_error)
            return CrawlOutcome(record, payload, "http", monotonic() - started, attempts, False)

    if browser is None:
        payload.update(success=False, text="", error=http_error or "Browser is unavailable")
        return CrawlOutcome(record, payload, "none", monotonic() - started, attempts, False)
    if http_attempted and not http_error:
        http_error = "HTTP article validation failed"
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
                if not is_boilerplate_text(verbatim_text, minimum_characters):
                    payload.update(text=verbatim_text, success=True)
                    payload.update(article_metadata(domain, result))
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
    """Attach bounded request diagnostics to the final document outcome."""
    trace: list[dict[str, object]] = []
    token = attempt_trace.set(trace)
    try:
        if fetch_mode == "auto":
            controller = active_controller.get()
            try:
                host = (urlsplit(record.url).hostname or "").lower().removeprefix("www.")
            except ValueError:
                host = ""
            policy = controller.policy(record.url)[1] if controller is not None and host else default_policy(host)
            preferred = policy.fetch_mode if policy.fetch_mode != "auto" else default_policy(host).fetch_mode
            if preferred != "auto":
                fetch_mode = preferred
        outcome = await _crawl_one(
            record, browser, http, browser_semaphore, http_semaphore,
            run_config, domain_configs, fetch_mode,
        )
        payload = outcome.payload
        last = trace[-1] if trace else {}
        status = last.get("status_code") or error_status(str(payload.get("error", "")))
        kind = "success" if payload.get("success") else classify_error(status, str(payload.get("error", "")))
        payload.update(
            mode=outcome.mode, attempts=outcome.attempts,
            status_code=status, error_kind=kind,
            elapsed_seconds=outcome.elapsed_seconds,
            used_fallback=outcome.used_fallback,
            final_url=last.get("final_url", record.url),
        )
        controller = active_controller.get()
        if controller is not None and not payload.get("success"):
            payload["next_retry_at"] = max(time() + 60, controller.retry_at(record.url))
            state, _ = controller.state(record.url)
            payload["source_retry_at"] = controller.retry_at(record.url) if state.cooldown_until > monotonic() else 0
            payload["source_interval_seconds"] = state.interval
        return outcome
    finally:
        attempt_trace.reset(token)
