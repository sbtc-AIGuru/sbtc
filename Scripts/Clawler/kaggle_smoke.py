"""Run a bounded Crawl4AI quality and throughput check on Kaggle."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic

from crawl import run_job
from kaggle_run import ensure_source
from utils import SourceRecord, load_url_range


CASES = (
    ("120ask_auto", 1_000_001, 1_000_050, "auto"),
    ("cnkang_auto", 1_378_922, 1_378_971, "auto"),
    ("wujue_auto", 1_973_214, 1_973_223, "auto"),
    ("120ask_browser", 1_000_001, 1_000_010, "browser"),
    ("cnkang_browser", 1_378_922, 1_378_931, "browser"),
)
REPORT = Path("data/benchmark_kaggle_report.json")


def validate_case(output: Path, start: int, end: int) -> tuple[int, int, int]:
    """Check every row against the original Parquet record despite completion order."""
    expected = {
        record.row_index: record
        for batch in load_url_range(Path("data/links_corpus.parquet"), start, end, 50)
        for record in batch
    }
    seen: dict[int, dict[str, object]] = {}
    success = failed = 0
    with output.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            row_index = value["row_index"]
            source: SourceRecord = expected[row_index]
            if row_index in seen or value["id"] != source.id or value["url"] != source.url:
                raise ValueError(f"Wrong or duplicate ID/URL at row {row_index}")
            text = value.get("text")
            if not isinstance(text, str):
                raise ValueError(f"Missing text at row {row_index}")
            if value.get("success"):
                if not text.strip():
                    raise ValueError(f"Empty successful article at row {row_index}")
                success += 1
            else:
                if text or not value.get("error"):
                    raise ValueError(f"Invalid failure record at row {row_index}")
                failed += 1
            seen[row_index] = value
    if set(seen) != set(expected):
        raise ValueError(f"Missing source rows in {output}")
    multipage = sum(int(value.get("page_count", 1)) > 1 for value in seen.values())
    return success, failed, multipage


async def main() -> None:
    ensure_source()
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
        check=True,
    )
    report = []
    for name, start, end, mode in CASES:
        output = Path(f"data/benchmark_kaggle_{name}.jsonl")
        args = argparse.Namespace(
            start=start,
            end=end,
            batch_size=50,
            concurrency=4,
            http_concurrency=8,
            fetch_mode=mode,
            light_browser=False,
            avoid_ads=False,
            browser_recycle_after=5_000,
            min_free_memory_gb=2.0,
            input=Path("data/links_corpus.parquet"),
            output=output,
        )
        started = monotonic()
        await run_job(args, output)
        elapsed = monotonic() - started
        success, failed, multipage = validate_case(output, start, end)
        item = {
            "case": name,
            "start": start,
            "end": end,
            "seconds": round(elapsed, 2),
            "rows_per_hour": round((end - start + 1) * 3600 / elapsed),
            "success": success,
            "failed": failed,
            "multipage": multipage,
            "output": str(output),
        }
        report.append(item)
        print(f"[Benchmark] {json.dumps(item, ensure_ascii=False)}", flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[Report] {REPORT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
