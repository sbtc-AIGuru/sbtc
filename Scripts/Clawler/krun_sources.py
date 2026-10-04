"""Run bounded Kaggle crawl shards one source domain at a time."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from krun_range import (
    INPUT, JOB_DIR, PROJECT_ROOT, JobAttemptsExhausted, QualityHold,
    run_cycle,
)
from utils import get_row_count, load_url_range


def source_ranges(start: int, end: int) -> list[tuple[int, int, str]]:
    """Find contiguous hostname ranges without loading all URLs into memory."""
    ranges: list[tuple[int, int, str]] = []
    current_domain: str | None = None
    range_start = start
    for batch in load_url_range(INPUT, start, end, 8_192):
        for record in batch:
            try:
                domain = (urlsplit(record.url).hostname or "").removeprefix("www.")
            except ValueError:
                domain = ""
            if current_domain is None:
                current_domain = domain
            elif domain != current_domain:
                ranges.append((range_start, record.row_index - 1, current_domain))
                range_start = record.row_index
                current_domain = domain
    if current_domain is not None:
        ranges.append((range_start, end, current_domain))
    return ranges


def save_deferred(path: Path, deferred: dict[str, dict[str, str]]) -> None:
    """Record blocked sources atomically so a restart can skip them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(deferred, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def run_sources(args: argparse.Namespace) -> dict[str, dict[str, str]]:
    """Continue after a blocked domain while retaining every incomplete range."""
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    deferred_path = JOB_DIR.parent / f"crawl_sources_{args.start}_{args.end}_deferred.json"
    deferred = json.loads(deferred_path.read_text()) if deferred_path.is_file() else {}
    ranges = source_ranges(args.start, args.end)
    print(f"[Sources] {len(ranges)} ranges for {args.start}-{args.end}", flush=True)
    for start, end, domain in ranges:
        key = f"{start}-{end}"
        final = PROJECT_ROOT / f"data/crawled_{key}.jsonl"
        if final.is_file():
            print(f"[Reuse] {key} source={domain}", flush=True)
            continue
        if key in deferred:
            print(f"[Deferred] {key} source={domain}: {deferred[key]['reason']}", flush=True)
            continue
        source_args = argparse.Namespace(**(vars(args) | {"start": start, "end": end}))
        validated_path = JOB_DIR.parent / f"crawl_{key}_validated.json"
        print(f"[Source] {key} source={domain}", flush=True)
        while True:
            try:
                complete = run_cycle(source_args, validated_path)
            except (QualityHold, JobAttemptsExhausted) as error:
                deferred[key] = {"domain": domain, "reason": str(error)}
                save_deferred(deferred_path, deferred)
                print(f"[Deferred] {key} source={domain}: {error}", flush=True)
                break
            if complete:
                break
            time.sleep(args.poll_seconds)
    print(f"[Sources done] deferred={len(deferred)}", flush=True)
    return deferred


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--shard-size", type=int, default=10_000)
    parser.add_argument("--max-active", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--http-concurrency", type=int, default=8)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--browser-recycle-after", type=int)
    parser.add_argument("--request-interval-seconds", type=float)
    parser.add_argument("--max-consecutive-blocked", type=int, default=5)
    parser.add_argument("--min-success-rate", type=float, default=0.5)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--ignore-job", action="append", default=[])
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start or args.end >= get_row_count(INPUT):
        parser.error("require 0 <= --start <= --end < Parquet row count")
    if min(
        args.shard_size, args.max_active, args.batch_size, args.concurrency,
        args.http_concurrency, args.poll_seconds, args.max_consecutive_blocked,
    ) < 1:
        parser.error("size, concurrency, polling and blocked limits must be positive")
    if not 0 <= args.min_success_rate <= 1:
        parser.error("--min-success-rate must be between 0 and 1")
    if args.max_in_flight is not None and args.max_in_flight < 1:
        parser.error("--max-in-flight must be positive")
    if args.browser_recycle_after is not None and args.browser_recycle_after < 1:
        parser.error("--browser-recycle-after must be positive")
    if args.request_interval_seconds is not None and args.request_interval_seconds < 0:
        parser.error("--request-interval-seconds must be nonnegative")
    run_sources(args)


if __name__ == "__main__":
    main()
