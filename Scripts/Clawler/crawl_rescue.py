"""Rescue crawler for targeted URL subsets (e.g. Phase 1 Selector fixes)."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
from contextlib import AsyncExitStack
import json
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import pyarrow.parquet as pq
from crawl4ai import AsyncWebCrawler, BrowserConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy, HTTPCrawlerConfig

from fetch import CrawlOutcome, crawl_one
from site_configs import build_run_configs
from utils import JsonlWriter, SourceRecord


DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def load_rescue_records(
    parquet_path: Path,
    ids_json_path: Path,
    limit: int | None = None,
) -> list[SourceRecord]:
    """Load SourceRecords corresponding to the specified row indices."""
    with open(ids_json_path, "r", encoding="utf-8") as f:
        target_row_ids: list[int] = json.load(f)

    if limit is not None and limit > 0:
        target_row_ids = target_row_ids[:limit]

    table = pq.read_table(parquet_path, columns=["id", "url"])
    ids_col = table.column("id")
    urls_col = table.column("url")

    records: list[SourceRecord] = []
    for row_id in target_row_ids:
        records.append(
            SourceRecord(
                row_index=row_id,
                id=ids_col[row_id].as_py(),
                url=urls_col[row_id].as_py(),
            )
        )
    return records


async def run_rescue(args: argparse.Namespace) -> None:
    parquet_path = Path(args.parquet)
    ids_path = Path(args.input_ids)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[Rescue] Loading target row IDs from {ids_path}...", flush=True)
    records = load_rescue_records(parquet_path, ids_path, args.limit)
    total = len(records)
    print(f"[Rescue] Total targets to process: {total}", flush=True)

    run_config, domain_configs = build_run_configs()
    browser_config = BrowserConfig(headless=True, verbose=False, text_mode=True)

    waiting: deque[SourceRecord] = deque()
    success = failed = skipped = 0
    attempts = 0
    elapsed_seconds = 0.0
    mode_success: Counter[str] = Counter()
    started = monotonic()
    last_progress = 0
    last_progress_at = started

    with JsonlWriter(output_path, skip_failed_on_resume=args.skip_failed_on_resume) as writer:
        completed = writer.completed_ids
        for rec in records:
            if completed.get(rec.id) == rec.url:
                skipped += 1
            else:
                waiting.append(rec)

        print(
            f"[Rescue] Completed in output: {len(completed)}, to crawl: {len(waiting)}, skipped: {skipped}",
            flush=True,
        )

        in_flight_limit = args.concurrency * 2
        active: dict[asyncio.Task[CrawlOutcome], SourceRecord] = {}

        async with AsyncExitStack() as stack:
            http = None
            browser = None
            if args.fetch_mode != "browser":
                http_cfg = HTTPCrawlerConfig(headers=DEFAULT_BROWSER_HEADERS)
                http = await stack.enter_async_context(
                    AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy(browser_config=http_cfg))
                )
            if args.fetch_mode != "http":
                browser = await stack.enter_async_context(
                    AsyncWebCrawler(config=browser_config)
                )

            http_semaphore = asyncio.Semaphore(args.concurrency)
            browser_semaphore = asyncio.Semaphore(max(1, args.concurrency // 4))

            while waiting or active:
                while waiting and len(active) < in_flight_limit:
                    record = waiting.popleft()
                    if completed.get(record.id) == record.url:
                        skipped += 1
                        continue
                    task = asyncio.create_task(
                        crawl_one(
                            record,
                            browser,
                            http,
                            browser_semaphore,
                            http_semaphore,
                            run_config,
                            domain_configs,
                            args.fetch_mode,
                        )
                    )
                    active[task] = record
                    if args.request_interval > 0:
                        await asyncio.sleep(args.request_interval)

                if not active:
                    break

                done, _ = await asyncio.wait(
                    active,
                    timeout=5.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    record = active.pop(task)
                    try:
                        outcome = task.result()
                    except Exception as error:
                        outcome = CrawlOutcome(
                            record=record,
                            payload={
                                "row_index": record.row_index,
                                "id": record.id,
                                "url": record.url,
                                "text": "",
                                "success": False,
                                "error": f"{type(error).__name__}: {error}",
                            },
                            mode="none",
                            elapsed_seconds=0.0,
                            attempts=0,
                            used_fallback=False,
                        )
                    result = outcome.payload
                    writer.write(result)
                    attempts += outcome.attempts
                    elapsed_seconds += outcome.elapsed_seconds

                    if result.get("success"):
                        success += 1
                        completed[record.id] = record.url
                        mode_success[outcome.mode] += 1
                        if args.verbose:
                            print(
                                f"[OK] id={record.id} row={record.row_index} "
                                f"len={len(str(result.get('text', '')))} "
                                f"time={outcome.elapsed_seconds:.2f}s",
                                flush=True,
                            )
                    else:
                        failed += 1
                        if args.verbose:
                            reason = str(result.get("error", "")).splitlines()[0]
                            print(
                                f"[FAIL] id={record.id} row={record.row_index} error={reason}",
                                flush=True,
                            )

                processed = success + failed + skipped
                now = monotonic()
                if (processed - last_progress >= 50) or (now - last_progress_at >= 10.0):
                    speed = (success + failed) / max(now - started, 0.001)
                    print(
                        f"[Rescue Progress] {processed}/{total} "
                        f"success={success} failed={failed} skipped={skipped} "
                        f"rate={speed:.1f} urls/s",
                        flush=True,
                    )
                    last_progress = processed
                    last_progress_at = now

    wall_seconds = monotonic() - started
    success_rate = (success / max(success + failed, 1)) * 100.0
    print("\n=== RESCUE RUN FINISHED ===", flush=True)
    print(f"Total: {total}", flush=True)
    print(f"Success: {success} ({success_rate:.1f}%)", flush=True)
    print(f"Failed: {failed}", flush=True)
    print(f"Skipped: {skipped}", flush=True)
    print(f"Wall time: {wall_seconds:.2f}s", flush=True)
    print(f"Output: {output_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-ids",
        default="datacrawl/phase1_row_ids.json",
        help="Path to JSON file containing list of row IDs to rescue",
    )
    parser.add_argument(
        "--parquet",
        default="sbtc/data/links_corpus.parquet",
        help="Path to links_corpus.parquet",
    )
    parser.add_argument(
        "--output",
        default="datacrawl/derived/crawled_phase1_rescue.jsonl",
        help="Output JSONL path for rescued crawl data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of URLs to process (e.g. for testing)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=24,
        help="Concurrency limit for HTTP crawler",
    )
    parser.add_argument(
        "--fetch-mode",
        choices=("http", "auto", "browser"),
        default="http",
        help="Fetching strategy (default: http)",
    )
    parser.add_argument(
        "--skip-failed-on-resume",
        action="store_true",
        help="Skip previously failed URLs in the output file on resume",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.0,
        help="Optional delay in seconds between launching request tasks",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose status for each URL",
    )
    args = parser.parse_args()
    asyncio.run(run_rescue(args))


if __name__ == "__main__":
    main()
