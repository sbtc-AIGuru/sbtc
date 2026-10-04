"""Concurrent Crawl4AI CLI for a selected inclusive Parquet row range."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
from contextlib import AsyncExitStack
from pathlib import Path
import re
from time import monotonic

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
PROGRESS_INTERVAL_SECONDS = 30
BLOCKED_STATUS_RE = re.compile(r"\bHTTP\s+(?:403|429)\b", re.IGNORECASE)


def is_source_blocked(error: str) -> bool:
    """Recognize repeated source denials after all fetch strategies fail."""
    return bool(BLOCKED_STATUS_RE.search(error)) or "Browser verification page" in error


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


async def cancel_active_tasks(
    active: dict[asyncio.Task[CrawlOutcome], SourceRecord],
    waiting: deque[SourceRecord],
) -> None:
    """Preserve unfinished URLs before their crawler contexts are closed."""
    if not active:
        return
    tasks = list(active)
    waiting.extendleft(reversed(active.values()))
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    active.clear()


async def run_job(args: argparse.Namespace, output: Path) -> None:
    """Keep a bounded task window full and write each completed URL immediately."""
    started = monotonic()
    total = args.end - args.start + 1
    success = failed = skipped = 0
    last_progress = browser_restarts = completed_since_restart = 0
    last_progress_at = started
    mode_success: Counter[str] = Counter()
    fallback_count = attempts = 0
    blocked_streak = 0
    elapsed_seconds = 0.0
    verbose_records = getattr(args, "verbose_records", False)
    print(f"[Crawl] {args.start}-{args.end}", flush=True)

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        text_mode=True,
        light_mode=args.light_browser,
        avoid_ads=args.avoid_ads,
    )
    run_config, domain_configs = build_run_configs()
    batches = iter(load_url_range(args.input, args.start, args.end, args.batch_size))
    waiting: deque[SourceRecord] = deque()
    source_finished = False
    in_flight_limit = getattr(args, "max_in_flight", None) or max(
        args.batch_size, args.concurrency + args.http_concurrency
    )
    request_interval = getattr(args, "request_interval_seconds", 0.0)
    next_request_at = started
    min_free_bytes = int(args.min_free_memory_gb * 1024**3)
    recycle_limit = args.browser_recycle_after if args.fetch_mode != "http" else None

    with JsonlWriter(output) as writer:
        completed = writer.completed_ids
        while True:
            while len(waiting) < in_flight_limit and not source_finished:
                batch = next(batches, None)
                if batch is None:
                    source_finished = True
                    break
                if verbose_records:
                    print(f"[Batch] {batch[0].row_index}-{batch[-1].row_index}", flush=True)
                for record in batch:
                    if completed.get(record.id) == record.url:
                        skipped += 1
                    else:
                        waiting.append(record)
            if source_finished and not waiting:
                break

            active: dict[asyncio.Task[CrawlOutcome], SourceRecord] = {}
            browser_outcomes_in_cycle = 0
            recycle_requested = restart_requested = memory_recycle_requested = False
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
                    stack.push_async_callback(cancel_active_tasks, active, waiting)
                    browser_semaphore = asyncio.Semaphore(args.concurrency)
                    http_semaphore = asyncio.Semaphore(args.http_concurrency)

                    while True:
                        while (
                            len(active) < in_flight_limit
                            and not recycle_requested
                        ):
                            if not waiting and not source_finished:
                                batch = next(batches, None)
                                if batch is None:
                                    source_finished = True
                                else:
                                    if verbose_records:
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
                            if request_interval:
                                delay = next_request_at - monotonic()
                                if delay > 0:
                                    await asyncio.sleep(delay)
                                next_request_at = monotonic() + request_interval
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
                        processed = success + failed + skipped
                        if not active:
                            break

                        done, _ = await asyncio.wait(
                            active,
                            timeout=PROGRESS_INTERVAL_SECONDS,
                            return_when=asyncio.FIRST_COMPLETED,
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
                            if outcome.mode == "browser":
                                browser_outcomes_in_cycle += 1
                            if verbose_records and outcome.used_fallback:
                                print(
                                    f"[Fallback] id={record.id} "
                                    f"reason={(outcome.fallback_error or 'Unknown HTTP failure').splitlines()[0]}",
                                    flush=True,
                                )
                            completed_since_restart += 1
                            if result.get("success"):
                                success += 1
                                blocked_streak = 0
                                completed[record.id] = record.url
                                mode_success[outcome.mode] += 1
                                if verbose_records:
                                    print(
                                        f"[OK] id={record.id} url={record.url} "
                                        f"mode={outcome.mode} seconds={outcome.elapsed_seconds:.2f}",
                                        flush=True,
                                    )
                            else:
                                failed += 1
                                blocked_streak = blocked_streak + 1 if is_source_blocked(
                                    str(result.get("error", ""))
                                ) else 0
                                if verbose_records:
                                    reason = str(result["error"]).splitlines()[0]
                                    print(
                                        f"[FAILED] id={record.id} url={record.url}: {reason}",
                                        flush=True,
                                    )
                                blocked_limit = getattr(args, "max_consecutive_blocked", 0)
                                if blocked_limit and blocked_streak >= blocked_limit:
                                    raise RuntimeError(
                                        f"Source returned {blocked_streak} consecutive "
                                        f"HTTP 403/429 or verification pages near row "
                                        f"{record.row_index}; stopping this shard"
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
                        now = monotonic()
                        if (
                            processed - last_progress >= METRICS_INTERVAL
                            or now - last_progress_at >= PROGRESS_INTERVAL_SECONDS
                        ):
                            print(
                                f"[Progress] {processed}/{total} "
                                f"http={mode_success['http']} "
                                f"browser={mode_success['browser']} "
                                f"failed={failed} fallback={fallback_count} "
                                f"attempts={attempts} in_flight={len(active)} "
                                f"mean_seconds={elapsed_seconds / max(success + failed, 1):.2f}",
                                flush=True,
                            )
                            last_progress = processed
                            last_progress_at = now
                        if recycle_limit is not None and browser_outcomes_in_cycle >= recycle_limit:
                            recycle_requested = True
                        if (
                            min_free_bytes
                            and browser is not None
                            and completed_since_restart >= args.batch_size
                            and psutil.virtual_memory().available < min_free_bytes
                        ):
                            recycle_requested = True
                            memory_recycle_requested = True

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
            if memory_recycle_requested:
                print("[Browser] Recycling because available memory is low", flush=True)
            else:
                print("[Browser] Recycling after bounded requests", flush=True)
            completed_since_restart = browser_restarts = 0

    wall_seconds = monotonic() - started
    fresh_rows_per_hour = (success + failed) * 3600 / wall_seconds if wall_seconds else 0.0
    print(f"[Progress] {success + failed + skipped}/{total}", flush=True)
    print(
        f"Total: {total}\nSuccess: {success}\nFailed: {failed}"
        f"\nSkipped: {skipped}\nWall seconds: {wall_seconds:.2f}"
        f"\nFresh rows/hour: {fresh_rows_per_hour:.1f}\nOutput: {output}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True, help="First Parquet row index")
    parser.add_argument("--end", type=int, required=True, help="Last Parquet row index (inclusive)")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=8, help="Maximum browser requests")
    parser.add_argument("--http-concurrency", type=int, default=8)
    parser.add_argument(
        "--max-in-flight", type=int,
        help="Maximum URLs processed at once, including HTTP and browser fallback",
    )
    parser.add_argument(
        "--request-interval-seconds", type=float, default=0.0,
        help="Minimum time between starting URLs; useful for rate-limited sources",
    )
    parser.add_argument("--fetch-mode", choices=("auto", "browser", "http"), default="auto")
    parser.add_argument(
        "--max-consecutive-blocked", type=int, default=0,
        help="Stop after this many consecutive blocked URLs; 0 disables the guard",
    )
    parser.add_argument("--verbose-records", action="store_true", help="Log every URL result")
    parser.add_argument("--light-browser", action="store_true")
    parser.add_argument("--avoid-ads", action="store_true")
    parser.add_argument(
        "--browser-recycle-after", type=int, default=DEFAULT_RECYCLE_AFTER,
        help="Completed browser URLs before restarting Chromium",
    )
    parser.add_argument("--min-free-memory-gb", type=float, default=DEFAULT_MIN_FREE_MEMORY_GB)
    parser.add_argument("--input", type=Path, default=Path("data/links_corpus.parquet"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start:
        parser.error("require 0 <= --start <= --end")
    if min(args.batch_size, args.concurrency, args.http_concurrency, args.browser_recycle_after) < 1:
        parser.error("batch size and concurrency limits must be positive")
    if args.max_in_flight is not None and args.max_in_flight < 1:
        parser.error("--max-in-flight must be positive")
    if args.max_consecutive_blocked < 0:
        parser.error("--max-consecutive-blocked must be nonnegative")
    if args.request_interval_seconds < 0:
        parser.error("--request-interval-seconds must be nonnegative")
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
