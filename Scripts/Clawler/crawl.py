"""Concurrent Crawl4AI CLI for a selected inclusive Parquet row range."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
from contextlib import AsyncExitStack
from pathlib import Path

import psutil
from crawl4ai import AsyncWebCrawler, BrowserConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy

from fetch import CrawlOutcome, crawl_one, is_browser_disconnected
from site_configs import build_run_configs
from utils import JsonlWriter, SourceRecord, get_row_count, load_url_range


MAX_BROWSER_RESTARTS = 3
DEFAULT_RECYCLE_AFTER = 5_000
DEFAULT_MIN_FREE_MEMORY_GB = 2.0
METRICS_INTERVAL = 1_000


def failed_outcome(record: SourceRecord, error: Exception) -> CrawlOutcome:
    """Turn an unexpected task error into an ordinary per-URL failure."""
    return CrawlOutcome(
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


async def run_job(args: argparse.Namespace, output: Path) -> None:
    """Keep a bounded task window full and write each completed URL immediately."""
    total = args.end - args.start + 1
    success = failed = skipped = 0
    last_progress = browser_restarts = completed_since_restart = 0
    mode_success: Counter[str] = Counter()
    fallback_count = attempts = 0
    elapsed_seconds = 0.0
    print(f"[Crawl] {args.start}-{args.end}", flush=True)

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        light_mode=args.light_browser,
        avoid_ads=args.avoid_ads,
    )
    run_config, domain_configs = build_run_configs()
    batches = iter(load_url_range(args.input, args.start, args.end, args.batch_size))
    waiting: deque[SourceRecord] = deque()
    source_finished = False
    in_flight_limit = max(args.batch_size, args.concurrency + args.http_concurrency)
    min_free_bytes = int(args.min_free_memory_gb * 1024**3)

    with JsonlWriter(output) as writer:
        completed = writer.completed_ids
        while True:
            while len(waiting) < in_flight_limit and not source_finished:
                batch = next(batches, None)
                if batch is None:
                    source_finished = True
                    break
                print(f"[Batch] {batch[0].row_index}-{batch[-1].row_index}", flush=True)
                for record in batch:
                    if completed.get(record.id) == record.url:
                        skipped += 1
                    else:
                        waiting.append(record)
            if source_finished and not waiting:
                break

            active: dict[asyncio.Task[CrawlOutcome], SourceRecord] = {}
            started_in_cycle = 0
            recycle_requested = restart_requested = False
            try:
                async with AsyncExitStack() as stack:
                    http = None
                    browser = None
                    if args.fetch_mode != "browser":
                        http = await stack.enter_async_context(
                            AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy())
                        )
                    if args.fetch_mode != "http":
                        browser = await stack.enter_async_context(
                            AsyncWebCrawler(config=browser_config)
                        )
                    browser_semaphore = asyncio.Semaphore(args.concurrency)
                    http_semaphore = asyncio.Semaphore(args.http_concurrency)

                    while True:
                        while (
                            len(active) < in_flight_limit
                            and started_in_cycle < args.browser_recycle_after
                            and not recycle_requested
                        ):
                            if not waiting and not source_finished:
                                batch = next(batches, None)
                                if batch is None:
                                    source_finished = True
                                else:
                                    print(
                                        f"[Batch] {batch[0].row_index}-{batch[-1].row_index}",
                                        flush=True,
                                    )
                                    waiting.extend(batch)
                            if not waiting:
                                break
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
                            started_in_cycle += 1

                        processed = success + failed + skipped
                        if processed - last_progress >= args.batch_size:
                            print(f"[Progress] {processed}/{total}", flush=True)
                            last_progress = processed
                        if not active:
                            break

                        done, _ = await asyncio.wait(
                            active, return_when=asyncio.FIRST_COMPLETED
                        )
                        retry_after_restart: list[SourceRecord] = []
                        for task in done:
                            record = active.pop(task)
                            try:
                                outcome = task.result()
                            except Exception as error:
                                outcome = failed_outcome(record, error)
                            result = outcome.payload
                            if is_browser_disconnected(str(result.get("error", ""))):
                                retry_after_restart.append(record)
                                continue

                            writer.write(result)
                            attempts += outcome.attempts
                            elapsed_seconds += outcome.elapsed_seconds
                            fallback_count += outcome.used_fallback
                            if outcome.used_fallback:
                                print(
                                    f"[Fallback] id={record.id} "
                                    f"reason={outcome.fallback_error.splitlines()[0]}",
                                    flush=True,
                                )
                            completed_since_restart += 1
                            if result.get("success"):
                                success += 1
                                completed[record.id] = record.url
                                mode_success[outcome.mode] += 1
                                print(
                                    f"[OK] id={record.id} url={record.url} "
                                    f"mode={outcome.mode} seconds={outcome.elapsed_seconds:.2f}",
                                    flush=True,
                                )
                            else:
                                failed += 1
                                reason = str(result["error"]).splitlines()[0]
                                print(
                                    f"[FAILED] id={record.id} url={record.url}: {reason}",
                                    flush=True,
                                )

                        if retry_after_restart:
                            pending_tasks = list(active)
                            retry_after_restart.extend(active.values())
                            for task in pending_tasks:
                                task.cancel()
                            await asyncio.gather(*pending_tasks, return_exceptions=True)
                            active.clear()
                            waiting.extendleft(reversed(retry_after_restart))
                            restart_requested = True
                            break

                        processed = success + failed + skipped
                        if processed - last_progress >= args.batch_size:
                            print(f"[Progress] {processed}/{total}", flush=True)
                            last_progress = processed
                        if processed and processed % METRICS_INTERVAL < len(done):
                            print(
                                f"[Metrics] http={mode_success['http']} "
                                f"browser={mode_success['browser']} "
                                f"fallback={fallback_count} attempts={attempts} "
                                f"mean_seconds={elapsed_seconds / max(success + failed, 1):.2f}",
                                flush=True,
                            )
                        if (
                            min_free_bytes
                            and completed_since_restart >= args.batch_size
                            and psutil.virtual_memory().available < min_free_bytes
                        ):
                            recycle_requested = True

            except Exception as error:
                if not is_browser_disconnected(str(error)):
                    raise
                restart_requested = True

            if restart_requested:
                if completed_since_restart >= args.batch_size:
                    browser_restarts = 0
                completed_since_restart = 0
                browser_restarts += 1
                if browser_restarts > MAX_BROWSER_RESTARTS:
                    raise RuntimeError(
                        f"Browser disconnected {browser_restarts} times without "
                        f"a completed batch near row {waiting[0].row_index if waiting else 'end'}"
                    )
                print(
                    f"[Browser] Disconnected; resuming unfinished URLs "
                    f"with a new browser ({browser_restarts}/{MAX_BROWSER_RESTARTS})",
                    flush=True,
                )
                continue

            if source_finished and not waiting:
                break
            if recycle_requested:
                print("[Browser] Recycling because available memory is low", flush=True)
            else:
                print("[Browser] Recycling after bounded requests", flush=True)
            completed_since_restart = browser_restarts = 0

    print(f"[Progress] {success + failed + skipped}/{total}", flush=True)
    print(
        f"Total: {total}\nSuccess: {success}\nFailed: {failed}"
        f"\nSkipped: {skipped}\nOutput: {output}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True, help="First Parquet row index")
    parser.add_argument("--end", type=int, required=True, help="Last Parquet row index (inclusive)")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=8, help="Maximum browser requests")
    parser.add_argument("--http-concurrency", type=int, default=8)
    parser.add_argument("--fetch-mode", choices=("auto", "browser", "http"), default="auto")
    parser.add_argument("--light-browser", action="store_true")
    parser.add_argument("--avoid-ads", action="store_true")
    parser.add_argument("--browser-recycle-after", type=int, default=DEFAULT_RECYCLE_AFTER)
    parser.add_argument("--min-free-memory-gb", type=float, default=DEFAULT_MIN_FREE_MEMORY_GB)
    parser.add_argument("--input", type=Path, default=Path("data/links_corpus.parquet"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start:
        parser.error("require 0 <= --start <= --end")
    if min(args.batch_size, args.concurrency, args.http_concurrency, args.browser_recycle_after) < 1:
        parser.error("batch size and concurrency limits must be positive")
    if args.min_free_memory_gb < 0:
        parser.error("--min-free-memory-gb must be nonnegative")
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
    except KeyboardInterrupt:
        print(f"[Stopped] Resume with the same command. Output: {output}", flush=True)


if __name__ == "__main__":
    main()
