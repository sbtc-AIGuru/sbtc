"""Compare four paragraph chunking strategies on one JSONL sample."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from sbtc.Scripts.Preprocess.chunking import ChunkConfig, STRATEGIES


def benchmark(input_path: Path, output_root: Path, config: ChunkConfig, shard_records: int = 1000) -> dict:
    source = input_path.resolve(strict=True)
    root = output_root.resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Benchmark output directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    results = {}
    for strategy in STRATEGIES:
        command = [
            sys.executable, "-m", "sbtc.Scripts.Preprocess.chunk_cli",
            str(source), str(root / strategy), "--strategy", strategy,
            "--min-units", str(config.min_units), "--target-units", str(config.target_units),
            "--max-units", str(config.max_units), "--overlap-units", str(config.overlap_units),
            "--parent-max-units", str(config.parent_max_units), "--shard-records", str(shard_records),
            "--workers", "1",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        report = json.loads(completed.stdout)
        if not report["done"] or report["covered_non_whitespace"] != report["source_non_whitespace"]:
            raise ValueError(f"Incomplete chunking or source coverage for {strategy}")
        results[strategy] = {
            "records": report["records"], "ok": report["ok"], "skipped": report["skipped"],
            "errors": report["errors"], "parents": report["parents"], "chunks": report["chunks"],
            "records_per_second": report["records_per_second"], "peak_rss_kb": report["peak_rss_kb"],
            "mean_chunk_units": report["mean_chunk_units"], "min_chunk_units": report["unit_min"],
            "max_chunk_units": report["unit_max"], "chunk_size_distribution": report["chunk_size_distribution"],
            "oversized_chunks": report["oversized_chunks"],
            "document_overlap_rate": report["document_overlap_rate"],
            "eligible_overlap_rate": report["eligible_overlap_rate"],
            "overlap_30_50_rate": report["overlap_30_50_rate"],
            "short_chunk_reason_counts": report["short_chunk_reason_counts"],
            "excluded_spans": report["excluded_spans"],
            "excluded_rule_counts": report["excluded_rule_counts"],
            "excluded_non_whitespace": report["excluded_non_whitespace"],
            "structural_boundary_rate": report["structural_boundary_rate"],
            "source_span_coverage": report["covered_non_whitespace"] / report["source_non_whitespace"] if report["source_non_whitespace"] else 1.0,
            "parent_child_integrity": "passed" if report["errors"] == 0 else "inspect errors",
            "output_bytes": sum(path.stat().st_size for path in (root / strategy).glob("part-*.jsonl")),
        }
    comparison = {"input": str(source), "config": asdict(config), "strategies": results}
    (root / "benchmark.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--shard-records", type=int, default=1000)
    args = parser.parse_args()
    result = benchmark(args.input, args.output, ChunkConfig(), args.shard_records)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
