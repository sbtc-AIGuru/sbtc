"""Concurrent Crawl4AI CLI for a selected inclusive Parquet row range."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
from urllib.parse import urlsplit

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
)

from site_configs import build_run_configs

from utils import (
    SourceRecord,
    get_row_count,
    load_completed_ids,
    load_url_range,
    save_results,
)


MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 45
TRANSIENT_STATUS_CODES = {408, 425, 429}
INLINE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(data:image/[^)\s]+\)", re.IGNORECASE)
MAX_BATCHES_PER_BROWSER = 100
MAX_BROWSER_RESTARTS = 3
BROWSER_DISCONNECT_MESSAGES = (
    "Connection closed while reading from the driver",
    "BrowserContext.new_page: Connection closed",
    "Target page, context or browser has been closed",
)


def get_markdown_text(result: object) -> str:
    """Prefer filtered Markdown and fall back to raw Markdown."""
    markdown = getattr(result, "markdown", None)
    fit = getattr(markdown, "fit_markdown", None)
    raw = getattr(markdown, "raw_markdown", None)
    fit_text = fit.strip() if isinstance(fit, str) else ""
    if fit_text and not fit_text.startswith("Error generating fit markdown:"):
        text = fit_text
    else:
        text = raw if isinstance(raw, str) else ""
    return INLINE_IMAGE_RE.sub(lambda match: match.group(1).strip(), text).strip()


def is_transient_status(status: int | None) -> bool:
    return status is None or status in TRANSIENT_STATUS_CODES or status >= 500


def is_browser_disconnected(error: str) -> bool:
    """Identify a dead Playwright browser rather than a per-URL failure."""
    return any(message in error for message in BROWSER_DISCONNECT_MESSAGES)


def page_error(text: str) -> str | None:
    """Recognize short browser challenge or application error pages."""
    if len(text) > 500:
        return None
    content = text.lstrip("# \n").lower()
    if content.startswith(("checking your browser", "this will only take a few seconds")):
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


async def crawl_one(
    crawler: AsyncWebCrawler,
    record: SourceRecord,
    semaphore: asyncio.Semaphore,
    run_config: CrawlerRunConfig,
    domain_configs: dict[str, CrawlerRunConfig],
) -> dict[str, object]:
    """Crawl and retry one record while retaining its original ID and URL."""
    if not record.url.startswith(("http://", "https://")):
        return {
            "id": record.id,
            "url": record.url,
            "text": "",
            "success": False,
            "error": "Missing or unsupported URL",
        }

    error_message = "Unknown crawl error"
    try:
        hostname = urlsplit(record.url).hostname or ""
    except ValueError as error:
        return {
            "id": record.id,
            "url": record.url,
            "text": "",
            "success": False,
            "error": f"Invalid URL: {error}",
        }
    hostname = hostname.removeprefix("www.")
    config = domain_configs.get(hostname)
    if hostname == "nhathuoclongchau.com.vn" and urlsplit(record.url).path.startswith("/benh/"):
        config = domain_configs["nhathuoclongchau.com.vn/benh"]
    if config is None and hostname.endswith(".39.net"):
        config = domain_configs["39.net"]
    config = config or run_config
    async with semaphore:
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    crawler.arun(url=record.url, config=config),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                redirect_error = homepage_redirect_error(record.url, result)
                if redirect_error:
                    return {
                        "id": record.id,
                        "url": record.url,
                        "text": "",
                        "success": False,
                        "error": redirect_error,
                    }
                text = get_markdown_text(result) if result.success else ""
                content_error = page_error(text) if text else None
                if result.success and text and not content_error:
                    return {"id": record.id, "url": record.url, "text": text}
                status = getattr(result, "status_code", None)
                error_message = content_error or result.error_message or (
                    "Empty Markdown" if result.success else f"HTTP {status or 'unknown'}"
                )
                if is_browser_disconnected(error_message):
                    break
                if not result.success and not is_transient_status(status):
                    break
            except Exception as error:
                error_message = f"{type(error).__name__}: {error}"
                if is_browser_disconnected(error_message):
                    break
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2**attempt)

    return {
        "id": record.id,
        "url": record.url,
        "text": "",
        "success": False,
        "error": error_message,
    }


async def crawl_batch(
    crawler: AsyncWebCrawler,
    records: list[SourceRecord],
    concurrency: int,
    run_config: CrawlerRunConfig,
    domain_configs: dict[str, CrawlerRunConfig],
) -> list[dict[str, object]]:
    """Run a bounded number of Crawl4AI requests concurrently."""
    semaphore = asyncio.Semaphore(concurrency)
    return await asyncio.gather(
        *(
            crawl_one(crawler, record, semaphore, run_config, domain_configs)
            for record in records
        )
    )


async def run_job(args: argparse.Namespace, output: Path) -> None:
    completed = load_completed_ids(output)
    total = args.end - args.start + 1
    success = failed = skipped = 0
    print(f"[Crawl] {args.start}-{args.end}", flush=True)

    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config, domain_configs = build_run_configs()
    batches = iter(load_url_range(args.input, args.start, args.end, args.batch_size))
    batch = next(batches, None)
    browser_restarts = 0
    while batch is not None:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for _ in range(MAX_BATCHES_PER_BROWSER):
                if batch is None:
                    break
                print(f"[Batch] {batch[0].row_index}-{batch[-1].row_index}", flush=True)
                pending = [
                    record for record in batch if completed.get(record.id) != record.url
                ]
                results = await crawl_batch(
                    crawler, pending, args.concurrency, run_config, domain_configs
                )
                if any(
                    is_browser_disconnected(str(result.get("error", "")))
                    for result in results
                ):
                    browser_restarts += 1
                    if browser_restarts > MAX_BROWSER_RESTARTS:
                        raise RuntimeError(
                            f"Browser disconnected {browser_restarts} times at "
                            f"batch {batch[0].row_index}-{batch[-1].row_index}"
                        )
                    print(
                        f"[Browser] Disconnected; restarting and retrying batch "
                        f"{batch[0].row_index}-{batch[-1].row_index} "
                        f"({browser_restarts}/{MAX_BROWSER_RESTARTS})",
                        flush=True,
                    )
                    break

                save_results(output, results)
                skipped += len(batch) - len(pending)
                for record, result in zip(pending, results, strict=True):
                    if result.get("success", True):
                        success += 1
                        completed[record.id] = record.url
                        print(f"[OK] id={record.id} url={record.url}", flush=True)
                    else:
                        failed += 1
                        reason = str(result["error"]).splitlines()[0]
                        print(f"[FAILED] id={record.id} url={record.url}: {reason}", flush=True)
                print(f"[Progress] {success + failed + skipped}/{total}", flush=True)
                browser_restarts = 0
                batch = next(batches, None)
            else:
                print("[Browser] Recycling after bounded batches", flush=True)

    print(f"Total: {total}\nSuccess: {success}\nFailed: {failed}\nSkipped: {skipped}\nOutput: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True, help="First Parquet row index")
    parser.add_argument("--end", type=int, required=True, help="Last Parquet row index (inclusive)")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--input", type=Path, default=Path("data/links_corpus.parquet"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start:
        parser.error("require 0 <= --start <= --end")
    if args.batch_size < 1 or args.concurrency < 1:
        parser.error("--batch-size and --concurrency must be positive")
    if not args.input.is_file():
        parser.error(f"input Parquet file not found: {args.input}")
    row_count = get_row_count(args.input)
    if args.end >= row_count:
        parser.error(f"--end must be less than {row_count} (last index: {row_count - 1})")
    output = args.output or Path(f"data/crawled_{args.start}_{args.end}.jsonl")
    try:
        asyncio.run(run_job(args, output))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
