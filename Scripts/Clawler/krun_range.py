"""Continue a large crawl through bounded Kaggle KRun jobs."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

from compact import compact


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = "Scripts/Clawler/kaggle_run.py"
INPUT = PROJECT_ROOT / "data/links_corpus.parquet"
JOB_DIR = PROJECT_ROOT / ".krun/jobs"
MAX_JOB_ATTEMPTS = 3
STATUS_PATTERN = re.compile(r"^Status: ([A-Z_]+)$", re.MULTILINE)
JOB_ID_PATTERN = re.compile(r"^Job ID: (\S+)$", re.MULTILINE)
ARGUMENTS_PATTERN = re.compile(r"^ARGUMENTS = (.+)$", re.MULTILINE)
TERMINAL_ERRORS = {
    "error", "cancelled", "failed", "preparation_error", "package_upload_error",
    "invalid",
}


class QualityHold(Exception):
    """Stop scheduling when a completed shard yields too little source text."""


@dataclass(frozen=True)
class Job:
    job_id: str
    start: int
    end: int
    status: str
    submitted_at: str

    @property
    def output_name(self) -> str:
        return f"crawled_{self.start}_{self.end}.jsonl"

    @property
    def output_path(self) -> Path:
        return JOB_DIR / self.job_id / "output/krun_outputs/data" / self.output_name


def run_krun(*arguments: str, timeout: int = 180) -> str:
    """Run KRun once and retain its diagnostics on failure."""
    command = ["krun", *arguments]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"KRun {' '.join(arguments[:2])} failed: {detail[-1000:]}")
    return result.stdout


def runner_arguments(path: Path) -> list[str]:
    """Read the exact CLI range recorded in a KRun runner."""
    match = ARGUMENTS_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Missing runner arguments: {path}")
    return json.loads(ast.literal_eval(match.group(1)))


def option_value(arguments: list[str], option: str) -> str:
    position = arguments.index(option)
    return arguments[position + 1]


def discover_jobs(start: int, end: int) -> list[Job]:
    """Adopt existing matching jobs, including ones submitted before a restart."""
    jobs = []
    for metadata_path in JOB_DIR.glob("*/metadata.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("entrypoint") != RUNNER:
            continue
        runner = metadata_path.parent / "workspace/runner.py"
        if not runner.is_file():
            continue
        arguments = runner_arguments(runner)
        try:
            job_start = int(option_value(arguments, "--start"))
            job_end = int(option_value(arguments, "--end"))
            output = option_value(arguments, "--output")
        except (IndexError, ValueError):
            continue
        if not (start <= job_start <= job_end <= end):
            continue
        if output != f"data/crawled_{job_start}_{job_end}.jsonl":
            continue
        jobs.append(
            Job(
                job_id=metadata["job_id"],
                start=job_start,
                end=job_end,
                status=metadata["status"],
                submitted_at=metadata["submitted_at"],
            )
        )
    return jobs


def refresh_job(job: Job) -> Job:
    """Read authoritative Kaggle state for a job that is still active."""
    if job.status == "complete" or job.status in TERMINAL_ERRORS:
        return job
    output = run_krun("status", job.job_id, "--project", str(PROJECT_ROOT))
    match = STATUS_PATTERN.search(output)
    if match is None:
        raise RuntimeError(f"Could not parse KRun status for {job.job_id}: {output}")
    return Job(job.job_id, job.start, job.end, match.group(1).lower(), job.submitted_at)


def validate_canonical(canonical: Path) -> None:
    """Check the success and failure fields of each compacted row."""
    with canonical.open("r", encoding="utf-8") as handle:
        for offset, line in enumerate(handle):
            record = json.loads(line)
            if "success" in record and not isinstance(record["success"], bool):
                raise ValueError(f"Invalid success flag at offset {offset}")
            if record.get("success") is False:
                if record["text"] or not record.get("error"):
                    raise ValueError(f"Invalid failure record at offset {offset}")
            elif not record["text"].strip():
                raise ValueError(f"Empty successful record at offset {offset}")


def validate_output(job: Job) -> tuple[int, int]:
    """Validate and deduplicate a shard regardless of completion order."""
    if not job.output_path.is_file():
        run_krun("output", job.job_id, "--project", str(PROJECT_ROOT), timeout=900)
    with TemporaryDirectory(prefix="crawl-validate-", dir=job.output_path.parent) as directory:
        canonical = Path(directory) / job.output_name
        _, success, failed = compact(INPUT, job.output_path, canonical, job.start, job.end)
        validate_canonical(canonical)
    return success, failed


def load_validated(path: Path) -> dict[str, list[int]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_validated(path: Path, validated: dict[str, list[int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(validated, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def submit_job(
    start: int, end: int, batch_size: int, concurrency: int, http_concurrency: int = 8,
    *, max_in_flight: int | None = None, browser_recycle_after: int | None = None,
    request_interval_seconds: float | None = None,
    max_consecutive_blocked: int | None = None,
) -> Job:
    output = f"data/crawled_{start}_{end}.jsonl"
    tuning = []
    if max_in_flight is not None:
        tuning.extend(("--max-in-flight", str(max_in_flight)))
    if browser_recycle_after is not None:
        tuning.extend(("--browser-recycle-after", str(browser_recycle_after)))
    if request_interval_seconds is not None:
        tuning.extend(("--request-interval-seconds", str(request_interval_seconds)))
    if max_consecutive_blocked is not None:
        tuning.extend(("--max-consecutive-blocked", str(max_consecutive_blocked)))
    response = run_krun(
        "run",
        RUNNER,
        "--project",
        str(PROJECT_ROOT),
        "--output",
        output,
        "--internet",
        "--detach",
        "--",
        "--start",
        str(start),
        "--end",
        str(end),
        "--batch-size",
        str(batch_size),
        "--concurrency",
        str(concurrency),
        "--http-concurrency",
        str(http_concurrency),
        *tuning,
        "--output",
        output,
    )
    match = JOB_ID_PATTERN.search(response)
    if match is None:
        raise RuntimeError(f"KRun submission did not return a job ID: {response}")
    print(f"[Submitted] {start}-{end} job={match.group(1)}", flush=True)
    return Job(match.group(1), start, end, "submitted", "")


def complete_segments(
    jobs: list[Job], validated: dict[str, list[int]]
) -> dict[tuple[int, int], Job]:
    completed: dict[tuple[int, int], Job] = {}
    for job in jobs:
        if job.status == "invalid" or job.job_id not in validated or not job.output_path.is_file():
            continue
        segment = (job.start, job.end)
        previous = completed.get(segment)
        if previous is None or (
            validated[job.job_id][0], job.submitted_at, job.job_id
        ) > (
            validated[previous.job_id][0], previous.submitted_at, previous.job_id
        ):
            completed[segment] = job
    return completed


def first_unassigned(start: int, end: int, ranges: list[tuple[int, int]]) -> int:
    cursor = start
    for range_start, range_end in sorted(ranges):
        if range_start > cursor:
            break
        cursor = max(cursor, range_end + 1)
    return min(cursor, end + 1)


def merge_outputs(
    start: int, end: int, completed: dict[tuple[int, int], Job]
) -> Path:
    """Canonicalize each shard and merge it in Parquet row order."""
    final = PROJECT_ROOT / f"data/crawled_{start}_{end}.jsonl"
    if final.exists():
        raise FileExistsError(f"Final output already exists; inspect it before merging: {final}")
    row_count = 0
    with TemporaryDirectory(prefix="crawl-merge-", dir=final.parent) as directory:
        temporary = Path(directory) / final.name
        with temporary.open("wb") as destination:
            for (range_start, range_end), job in sorted(completed.items()):
                if range_start != start + row_count:
                    raise ValueError(f"Missing rows before {range_start}")
                canonical = Path(directory) / f"canonical_{range_start}_{range_end}.jsonl"
                compact(INPUT, job.output_path, canonical, range_start, range_end)
                validate_canonical(canonical)
                with canonical.open("rb") as source:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                canonical.unlink()
                row_count += range_end - range_start + 1
            destination.flush()
            os.fsync(destination.fileno())
        if row_count != end - start + 1:
            raise ValueError(f"Final row count {row_count} does not match {end - start + 1}")
        temporary.rename(final)
    return final


def run_cycle(args: argparse.Namespace, validated_path: Path) -> bool:
    rejected_path = validated_path.with_name(f"{validated_path.stem}_rejected.json")
    rejected = load_validated(rejected_path)
    ignored = set(getattr(args, "ignore_job", ()))
    jobs = [job for job in discover_jobs(args.start, args.end) if job.job_id not in ignored]
    jobs = [
        Job(job.job_id, job.start, job.end, "invalid", job.submitted_at)
        if job.job_id in rejected else job
        for job in jobs
    ]
    validated = load_validated(validated_path)
    refreshed = []
    for job in jobs:
        try:
            refreshed.append(refresh_job(job))
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"[Status retry] job={job.job_id}: {error}", flush=True)
            refreshed.append(job)
    jobs = refreshed

    for index, job in enumerate(jobs):
        if job.status == "complete" and (
            job.job_id not in validated or not job.output_path.is_file()
        ):
            try:
                success, failed = validate_output(job)
            except ValueError as error:
                rejected[job.job_id] = str(error)
                save_validated(rejected_path, rejected)
                jobs[index] = Job(job.job_id, job.start, job.end, "invalid", job.submitted_at)
                print(f"[Rejected] job={job.job_id}: {error}", flush=True)
                continue
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f"[Output retry] job={job.job_id}: {error}", flush=True)
                continue
            validated[job.job_id] = [success, failed]
            save_validated(validated_path, validated)
            print(
                f"[Verified] {job.start}-{job.end} success={success} failed={failed}",
                flush=True,
            )

    completed = complete_segments(jobs, validated)
    minimum_success_rate = getattr(args, "min_success_rate", 0.0)
    for segment, job in completed.items():
        success, failed = validated[job.job_id]
        if success / (success + failed) < minimum_success_rate:
            raise QualityHold(
                f"Shard {segment} has {success}/{success + failed} successful texts "
                f"(< {minimum_success_rate:.0%}); inspect source errors before continuing"
            )
    groups: dict[tuple[int, int], list[Job]] = {}
    for job in jobs:
        groups.setdefault((job.start, job.end), []).append(job)
    active = sum(
        1
        for segment, attempts in groups.items()
        if segment not in completed
        and any(job.status not in TERMINAL_ERRORS | {"complete"} for job in attempts)
    )
    cursor = first_unassigned(args.start, args.end, list(groups))

    tuning = {}
    for name in (
        "max_in_flight", "browser_recycle_after", "request_interval_seconds",
        "max_consecutive_blocked",
    ):
        value = getattr(args, name, None)
        if value is not None:
            tuning[name] = value

    if cursor > args.end and len(completed) == len(groups):
        final = merge_outputs(args.start, args.end, completed)
        total_success = sum(validated[job.job_id][0] for job in completed.values())
        total_failed = sum(validated[job.job_id][1] for job in completed.values())
        print(
            f"[Complete] success={total_success} failed={total_failed} output={final}",
            flush=True,
        )
        return True

    for segment, attempts in sorted(groups.items()):
        if active >= args.max_active:
            break
        if segment in completed:
            continue
        if any(job.status not in TERMINAL_ERRORS | {"complete"} for job in attempts):
            continue
        if len(attempts) >= MAX_JOB_ATTEMPTS:
            raise RuntimeError(f"Shard {segment} failed {len(attempts)} times")
        if any(job.status == "complete" for job in attempts):
            continue
        submit_job(*segment, args.batch_size, args.concurrency, args.http_concurrency, **tuning)
        active += 1

    while active < args.max_active and cursor <= args.end:
        next_start = min((a for a, _ in groups if a > cursor), default=args.end + 1)
        shard_end = min(cursor + args.shard_size - 1, next_start - 1, args.end)
        submit_job(
            cursor, shard_end, args.batch_size, args.concurrency,
            args.http_concurrency, **tuning,
        )
        active += 1
        cursor = shard_end + 1

    verified_rows = sum(job.end - job.start + 1 for job in completed.values())
    print(
        f"[Progress] verified={verified_rows}/{args.end - args.start + 1} active={active}",
        flush=True,
    )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--shard-size", type=int, default=10_000)
    parser.add_argument("--max-active", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--http-concurrency", type=int, default=8)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--browser-recycle-after", type=int)
    parser.add_argument("--request-interval-seconds", type=float)
    parser.add_argument("--max-consecutive-blocked", type=int)
    parser.add_argument("--ignore-job", action="append", default=[])
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument(
        "--min-success-rate", type=float, default=0.0,
        help="Stop scheduling if a verified shard has a lower text success rate",
    )
    parser.add_argument("--once", action="store_true", help="Run one scheduling cycle")
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start:
        parser.error("require 0 <= --start <= --end")
    if min(
        args.shard_size, args.max_active, args.batch_size, args.concurrency,
        args.http_concurrency, args.poll_seconds,
    ) < 1:
        parser.error("all size, concurrency and polling options must be positive")
    if not 0 <= args.min_success_rate <= 1:
        parser.error("--min-success-rate must be between 0 and 1")
    if args.max_in_flight is not None and args.max_in_flight < 1:
        parser.error("--max-in-flight must be positive")
    if args.browser_recycle_after is not None and args.browser_recycle_after < 1:
        parser.error("--browser-recycle-after must be positive")
    if args.request_interval_seconds is not None and args.request_interval_seconds < 0:
        parser.error("--request-interval-seconds must be nonnegative")
    if args.max_consecutive_blocked is not None and args.max_consecutive_blocked < 1:
        parser.error("--max-consecutive-blocked must be positive")

    JOB_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = JOB_DIR.parent / f"crawl_{args.start}_{args.end}.lock"
    validated_path = JOB_DIR.parent / f"crawl_{args.start}_{args.end}_validated.json"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit("Another KRun range controller is already running") from error
        while True:
            try:
                complete = run_cycle(args, validated_path)
            except QualityHold as error:
                print(f"[Quality hold] {error}", flush=True)
                break
            if complete or args.once:
                break
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
