"""Collect and verify the two requested Kaggle crawl jobs."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import time

from krun_range import (
    JOB_DIR,
    TERMINAL_ERRORS,
    Job,
    load_validated,
    merge_outputs,
    refresh_job,
    save_validated,
    validate_output,
)


JOBS = (
    Job("20261003-104024-d86d25", 1_000_001, 1_500_000, "submitted", ""),
    Job("20261003-104039-d39e70", 1_500_001, 2_000_000, "submitted", ""),
)
VALIDATED_PATH = JOB_DIR.parent / "crawl_1000001_2000000_two_validated.json"


def collect_once(validated_path: Path) -> bool:
    """Download finished jobs, validate their rows, and merge both outputs."""
    validated = load_validated(validated_path)
    for job in JOBS:
        if job.job_id in validated and job.output_path.is_file():
            continue
        try:
            current = refresh_job(job)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"[Status retry] job={job.job_id}: {error}", flush=True)
            continue
        if current.status in TERMINAL_ERRORS:
            raise RuntimeError(f"Kaggle job {job.job_id} ended with {current.status}")
        if current.status != "complete":
            print(f"[Running] {job.start}-{job.end}: {current.status}", flush=True)
            continue
        try:
            success, failed = validate_output(current)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"[Output retry] job={job.job_id}: {error}", flush=True)
            continue
        validated[job.job_id] = [success, failed]
        save_validated(validated_path, validated)
        print(
            f"[Verified] {job.start}-{job.end} success={success} failed={failed}",
            flush=True,
        )

    if not all(job.job_id in validated and job.output_path.is_file() for job in JOBS):
        return False
    completed = {(job.start, job.end): job for job in JOBS}
    final = merge_outputs(JOBS[0].start, JOBS[-1].end, completed)
    success = sum(validated[job.job_id][0] for job in JOBS)
    failed = sum(validated[job.job_id][1] for job in JOBS)
    print(f"[Complete] success={success} failed={failed} output={final}", flush=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be positive")
    while not collect_once(VALIDATED_PATH):
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
