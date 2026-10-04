"""Resume small local crawl shards for sources blocked from Kaggle IPs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from compact import compact
from krun_range import validate_canonical
from utils import get_row_count


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "data/links_corpus.parquet"
CRAWLER = PROJECT_ROOT / "Scripts/Clawler/crawl.py"


def shard_path(start: int, end: int) -> Path:
    return PROJECT_ROOT / f"data/crawled_local_{start}_{end}.jsonl"


def inspect_shard(raw: Path, start: int, end: int) -> tuple[int, int] | None:
    """Return verified text/failure counts, or None for an incomplete shard."""
    if not raw.is_file():
        return None
    with TemporaryDirectory(prefix="crawl-local-check-", dir=raw.parent) as directory:
        canonical = Path(directory) / raw.name
        try:
            _, success, failed = compact(SOURCE, raw, canonical, start, end)
            validate_canonical(canonical)
        except ValueError as error:
            print(f"[Incomplete] {start}-{end}: {error}", flush=True)
            return None
    return success, failed


def run_shard(
    start: int, end: int, max_attempts: int, request_interval_seconds: float,
) -> tuple[int, int]:
    """Resume a shard, retry its failed rows, and verify canonical IDs."""
    output = shard_path(start, end)
    counts = inspect_shard(output, start, end)
    if counts == (end - start + 1, 0):
        print(f"[Reuse] {start}-{end} success={counts[0]}", flush=True)
        return counts

    for attempt in range(1, max_attempts + 1):
        command = [
            sys.executable, str(CRAWLER),
            "--start", str(start), "--end", str(end),
            "--batch-size", "1", "--concurrency", "1", "--http-concurrency", "1",
            "--max-in-flight", "1", "--browser-recycle-after", "1",
            "--max-consecutive-blocked", "5",
            "--request-interval-seconds", str(request_interval_seconds),
            "--fetch-mode", "auto", "--min-free-memory-gb", "0",
            "--input", str(SOURCE), "--output", str(output),
        ]
        print(f"[Crawl shard] {start}-{end} attempt={attempt}", flush=True)
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
        counts = inspect_shard(output, start, end)
        if counts is None:
            raise ValueError(f"Shard {start}-{end} did not produce every Parquet row")
        print(
            f"[Verified] {start}-{end} success={counts[0]} failed={counts[1]}",
            flush=True,
        )
        if counts[1] == 0:
            break
    assert counts is not None
    return counts


def merge_shards(start: int, end: int, shard_size: int) -> Path:
    """Publish one fully checked file without replacing an existing result."""
    final = PROJECT_ROOT / f"data/crawled_{start}_{end}.jsonl"
    if final.exists():
        raise FileExistsError(f"Final output already exists: {final}")
    with TemporaryDirectory(prefix="crawl-local-merge-", dir=final.parent) as directory:
        temporary = Path(directory) / final.name
        with temporary.open("wb") as destination:
            for shard_start in range(start, end + 1, shard_size):
                shard_end = min(shard_start + shard_size - 1, end)
                raw = shard_path(shard_start, shard_end)
                canonical = Path(directory) / f"canonical_{shard_start}_{shard_end}.jsonl"
                compact(SOURCE, raw, canonical, shard_start, shard_end)
                validate_canonical(canonical)
                with canonical.open("rb") as source:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                canonical.unlink()
            destination.flush()
            os.fsync(destination.fileno())
        temporary.rename(final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--shard-size", type=int, default=1_000)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--min-success-rate", type=float, default=0.9)
    parser.add_argument("--request-interval-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start or args.end >= get_row_count(SOURCE):
        parser.error("require 0 <= --start <= --end < Parquet row count")
    if min(args.shard_size, args.max_attempts) < 1:
        parser.error("shard size and attempts must be positive")
    if not 0 <= args.min_success_rate <= 1 or args.request_interval_seconds < 0:
        parser.error("success rate must be 0-1 and request interval nonnegative")

    for shard_start in range(args.start, args.end + 1, args.shard_size):
        shard_end = min(shard_start + args.shard_size - 1, args.end)
        success, failed = run_shard(
            shard_start, shard_end, args.max_attempts, args.request_interval_seconds,
        )
        if success / (success + failed) < args.min_success_rate:
            raise RuntimeError(
                f"Shard {shard_start}-{shard_end} has {success}/{success + failed} "
                "successful texts; inspect source errors before continuing"
            )

    final = merge_shards(args.start, args.end, args.shard_size)
    print(f"[Complete] {args.start}-{args.end} output={final}", flush=True)


if __name__ == "__main__":
    main()
