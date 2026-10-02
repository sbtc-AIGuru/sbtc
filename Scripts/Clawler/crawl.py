"""Concurrent Crawl4AI CLI for a selected inclusive Parquet row range."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from utils import (
    SourceRecord,
    get_row_count,
    load_completed_ids,
    load_url_range,
    save_results,
)


MAX_RETRIES = 3
PAGE_TIMEOUT_MS = 30_000
REQUEST_TIMEOUT_SECONDS = 45
TRANSIENT_STATUS_CODES = {408, 425, 429}


def get_markdown_text(result: object) -> str:
    """Prefer filtered Markdown and fall back to raw Markdown."""
    markdown = getattr(result, "markdown", None)
    fit = getattr(markdown, "fit_markdown", None)
    raw = getattr(markdown, "raw_markdown", None)
    return (fit if isinstance(fit, str) and fit.strip() else raw or "").strip()


def is_transient_status(status: int | None) -> bool:
    return status is None or status in TRANSIENT_STATUS_CODES or status >= 500


def page_error(text: str) -> str | None:
    """Recognize short browser challenge or application error pages."""
    if len(text) > 500:
        return None
    content = text.lstrip("# \n").lower()
    if content.startswith("checking your browser"):
        return "Browser verification page instead of article content"
    if content.startswith("application error:"):
        return "Website application error instead of article content"
    return None


async def crawl_one(
    crawler: AsyncWebCrawler,
    record: SourceRecord,
    semaphore: asyncio.Semaphore,
    run_config: CrawlerRunConfig,
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
    async with semaphore:
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    crawler.arun(url=record.url, config=run_config),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                text = get_markdown_text(result) if result.success else ""
                content_error = page_error(text) if text else None
                if result.success and text and not content_error:
                    return {"id": record.id, "url": record.url, "text": text}
                status = getattr(result, "status_code", None)
                error_message = content_error or result.error_message or (
                    "Empty Markdown" if result.success else f"HTTP {status or 'unknown'}"
                )
                if not result.success and not is_transient_status(status):
                    break
            except Exception as error:
                error_message = f"{type(error).__name__}: {error}"
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
) -> list[dict[str, object]]:
    """Run a bounded number of Crawl4AI requests concurrently."""
    semaphore = asyncio.Semaphore(concurrency)
    return await asyncio.gather(
        *(crawl_one(crawler, record, semaphore, run_config) for record in records)
    )


async def run_job(args: argparse.Namespace, output: Path) -> None:
    completed = load_completed_ids(output)
    total = args.end - args.start + 1
    success = failed = skipped = 0
    print(f"[Crawl] {args.start}-{args.end}", flush=True)

    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=PAGE_TIMEOUT_MS,
    )
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for batch in load_url_range(args.input, args.start, args.end, args.batch_size):
            print(f"[Batch] {batch[0].row_index}-{batch[-1].row_index}", flush=True)
            pending = []
            for record in batch:
                if completed.get(record.id) == record.url:
                    skipped += 1
                else:
                    pending.append(record)

            results = await crawl_batch(crawler, pending, args.concurrency, run_config)
            save_results(output, results)
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
