"""Bounded JSONL chunking with atomic shards and resumable checkpoints."""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sys
import time
from typing import BinaryIO, Iterator

from sbtc.Scripts.Clawler.verbatim import CLEANER_VERSION
from sbtc.Scripts.Preprocess.chunking import ChunkConfig, STRATEGIES, chunk_document
from sbtc.Scripts.Preprocess.format_profiles import PROFILE_VERSION


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _config_fingerprint(config: ChunkConfig, strategy: str, shard_records: int) -> str:
    data = {"config": asdict(config), "strategy": strategy, "shard_records": shard_records, "cleaner_version": CLEANER_VERSION}
    if strategy == "format": data["profile_version"] = PROFILE_VERSION
    payload = json.dumps(data, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_summary() -> dict:
    return {
        "records": 0, "ok": 0, "skipped": 0, "errors": 0,
        "cleaned_records": 0, "cleaning_actions": {}, "cleaning_warnings": {},
        "parents": 0, "chunks": 0, "oversized_chunks": 0,
        "source_non_whitespace": 0, "covered_non_whitespace": 0,
        "indexed_non_whitespace": 0, "excluded_non_whitespace": 0,
        "excluded_spans": 0,
        "structural_intact_chunks": 0, "unit_sum": 0,
        "document_nonfirst_children": 0, "document_overlap_positive": 0,
        "eligible_overlap_transitions": 0, "eligible_overlap_positive": 0,
        "overlap_30_50": 0,
        "unit_min": None, "unit_max": None,
        "reason_counts": {},
        "short_chunk_reason_counts": {}, "overlap_exception_counts": {},
        "excluded_rule_counts": {},
        "profile_counts": {}, "format_warning_counts": {}, "content_language_counts": {},
        "chunk_size_distribution": {key: 0 for key in ("0-49", "50-99", "100-149", "150-219", "220-300", ">300")},
    }


def _size_bucket(units: int) -> str:
    if units < 50:
        return "0-49"
    if units < 100:
        return "50-99"
    if units < 150:
        return "100-149"
    if units < 220:
        return "150-219"
    if units <= 300:
        return "220-300"
    return ">300"


def _add_result(summary: dict, result: dict) -> None:
    summary["records"] += 1
    cleaning = result.get("cleaning")
    if cleaning:
        summary["cleaned_records"] += 1
        for action, count in cleaning["actions"].items():
            summary["cleaning_actions"][action] = summary["cleaning_actions"].get(action, 0) + count
        for warning in cleaning["warnings"]:
            code = warning["code"]
            summary["cleaning_warnings"][code] = summary["cleaning_warnings"].get(code, 0) + warning["count"]
    status = result["status"]
    summary["ok" if status == "ok" else "skipped" if status == "skipped" else "errors"] += 1
    if status != "ok":
        reason = result.get("reason") or result.get("error_type") or "unknown"
        summary["reason_counts"][reason] = summary["reason_counts"].get(reason, 0) + 1
        return
    if result.get("profile"):
        profile = result["profile"]
        counts = summary.setdefault("profile_counts", {})
        counts[profile] = counts.get(profile, 0) + 1
        for warning in result.get("format_warnings", []):
            counts = summary.setdefault("format_warning_counts", {})
            counts[warning["code"]] = counts.get(warning["code"], 0) + warning["count"]
        for language in {s["language"] for s in result.get("content_language_spans", [])}:
            counts = summary.setdefault("content_language_counts", {})
            counts[language] = counts.get(language, 0) + 1
    summary["parents"] += len(result["parents"])
    summary["chunks"] += len(result["children"])
    summary["source_non_whitespace"] += result["coverage"]["non_whitespace_total"]
    summary["covered_non_whitespace"] += result["coverage"]["non_whitespace_covered"]
    summary["indexed_non_whitespace"] += result["coverage"].get("non_whitespace_indexed", result["coverage"]["non_whitespace_covered"])
    summary["excluded_non_whitespace"] += result["coverage"].get("non_whitespace_excluded", 0)
    summary["excluded_spans"] += len(result.get("excluded_spans", []))
    summary["structural_intact_chunks"] += round(result["structural_boundary_rate"] * len(result["children"]))
    seen_parents = set()
    for index, child in enumerate(result["children"]):
        units = child["unit_count"]
        summary["unit_sum"] += units
        summary["unit_min"] = units if summary["unit_min"] is None else min(summary["unit_min"], units)
        summary["unit_max"] = units if summary["unit_max"] is None else max(summary["unit_max"], units)
        summary["chunk_size_distribution"][_size_bucket(units)] += 1
        summary["oversized_chunks"] += bool(child["oversized_reason"])
        short_reason = child.get("short_chunk_reason")
        if short_reason:
            summary["short_chunk_reason_counts"][short_reason] = summary["short_chunk_reason_counts"].get(short_reason, 0) + 1
        exception = child.get("overlap_exception")
        if exception:
            summary["overlap_exception_counts"][exception] = summary["overlap_exception_counts"].get(exception, 0) + 1
        if index:
            summary["document_nonfirst_children"] += 1
            summary["document_overlap_positive"] += child.get("overlap_units", 0) > 0
        if child["parent_id"] in seen_parents:
            summary["eligible_overlap_transitions"] += 1
            summary["eligible_overlap_positive"] += child.get("overlap_units", 0) > 0
            summary["overlap_30_50"] += 30 <= child.get("overlap_units", 0) <= 50
        seen_parents.add(child["parent_id"])
    for span in result.get("excluded_spans", []):
        rule = span["rule_id"]
        summary["excluded_rule_counts"][rule] = summary["excluded_rule_counts"].get(rule, 0) + 1


def _tasks(stream: BinaryIO, start_line: int, config: ChunkConfig, strategy: str) -> Iterator[tuple[int, int, bytes, ChunkConfig, str]]:
    line_number = start_line
    while line := stream.readline():
        line_number += 1
        yield line_number, stream.tell(), line, config, strategy


def _process_line(task: tuple[int, int, bytes, ChunkConfig, str]) -> tuple[int, int, dict]:
    line_number, next_offset, raw, config, strategy = task
    try:
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError("JSON line must contain an object")
        result = chunk_document(record, config, strategy=strategy)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, AssertionError, TypeError) as error:
        result = {"status": "error", "error_type": type(error).__name__, "error": str(error), "parents": [], "children": []}
    result["input_line"] = line_number
    return line_number, next_offset, result


def _checkpoint_path(directory: Path) -> Path:
    return directory / "checkpoint.json"


def _part_name(index: int) -> str:
    return f"part-{index:06d}.jsonl"


def _recover_pending(directory: Path, checkpoint: dict) -> None:
    pending = checkpoint.get("pending")
    if not pending:
        return
    final = directory / _part_name(pending["index"])
    temporary = directory / (_part_name(pending["index"]) + ".tmp")
    candidate = final if final.exists() else temporary
    if candidate.exists():
        if _sha256_file(candidate) != pending["sha256"]:
            raise ValueError(f"Pending shard checksum mismatch: {candidate}")
        if candidate == temporary:
            os.replace(temporary, final)
        checkpoint["next_offset"] = pending["end_offset"]
        checkpoint["last_line"] = pending["end_line"]
        checkpoint["next_shard"] = pending["index"] + 1
        checkpoint["summary"] = pending["summary_after"]
    checkpoint.pop("pending")
    _atomic_json(_checkpoint_path(directory), checkpoint)


def _validate_output_parts(directory: Path, next_shard: int) -> None:
    expected = {_part_name(index) for index in range(next_shard)}
    actual = {path.name for path in directory.glob("part-*.jsonl")}
    if actual != expected:
        raise ValueError(f"Output shard set differs from checkpoint: {sorted(actual ^ expected)}")
    stale = [path for path in directory.glob("part-*.jsonl.tmp") if path.name != _part_name(next_shard) + ".tmp"]
    if stale:
        raise ValueError(f"Unexpected temporary shards: {stale}")


def _finalize_shard(directory: Path, checkpoint: dict, temporary: Path, digest: hashlib._Hash, end_offset: int, end_line: int, summary_after: dict) -> None:
    index = checkpoint["next_shard"]
    final = directory / _part_name(index)
    if final.exists():
        raise FileExistsError(final)
    checkpoint["pending"] = {
        "index": index, "sha256": digest.hexdigest(), "end_offset": end_offset,
        "end_line": end_line, "summary_after": summary_after,
    }
    _atomic_json(_checkpoint_path(directory), checkpoint)
    os.replace(temporary, final)
    checkpoint["next_offset"] = end_offset
    checkpoint["last_line"] = end_line
    checkpoint["next_shard"] = index + 1
    checkpoint["summary"] = summary_after
    checkpoint.pop("pending")
    _atomic_json(_checkpoint_path(directory), checkpoint)


def run_chunking(
    input_path: str | Path,
    output_dir: str | Path,
    config: ChunkConfig | None = None,
    *,
    strategy: str = "hybrid",
    shard_records: int = 1000,
    workers: int = 1,
    resume: bool = False,
    max_shards: int | None = None,
    progress_every: int = 1000,
) -> dict:
    """Stream input into atomic output shards; resume from the last committed byte."""
    config = config or ChunkConfig()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    if shard_records < 1 or workers < 1 or progress_every < 0 or (max_shards is not None and max_shards < 1):
        raise ValueError("shard_records, workers, and max_shards must be positive; progress_every must be nonnegative")
    source = Path(input_path).resolve(strict=True)
    directory = Path(output_dir).resolve()
    if source == directory or source in directory.parents or directory == source.parent:
        raise ValueError("Output directory must be separate from the source file and directory")
    started = time.perf_counter()
    input_sha256 = _sha256_file(source)
    fingerprint = _config_fingerprint(config, strategy, shard_records)
    checkpoint_file = _checkpoint_path(directory)
    if resume:
        if not checkpoint_file.is_file():
            raise FileNotFoundError(f"No checkpoint to resume: {checkpoint_file}")
        checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        if checkpoint.get("cleaner_version") != CLEANER_VERSION:
            raise ValueError("Cleaner version differs or is missing from checkpoint; use a new output directory")
        if strategy == "format" and checkpoint.get("profile_version") != PROFILE_VERSION:
            raise ValueError("Profile version differs or is missing from checkpoint; use a new output directory")
        if checkpoint["input_sha256"] != input_sha256 or checkpoint["config_sha256"] != fingerprint:
            raise ValueError("Input or configuration differs from checkpoint")
        _recover_pending(directory, checkpoint)
        _validate_output_parts(directory, checkpoint["next_shard"])
    else:
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f"Output directory is not empty: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "input_sha256": input_sha256, "config_sha256": fingerprint,
            "cleaner_version": CLEANER_VERSION,
            "profile_version": PROFILE_VERSION if strategy == "format" else None,
            "config": asdict(config), "strategy": strategy,
            "shard_records": shard_records,
            "next_offset": 0, "last_line": 0, "next_shard": 0,
            "summary": _empty_summary(), "done": False,
        }
        _atomic_json(checkpoint_file, checkpoint)
    initial_records = checkpoint["summary"]["records"]
    initial_shards = checkpoint["next_shard"]
    if not checkpoint["done"]:
        with source.open("rb") as stream:
            stream.seek(checkpoint["next_offset"])
            tasks = _tasks(stream, checkpoint["last_line"], config, strategy)
            context = multiprocessing.get_context("fork") if "fork" in multiprocessing.get_all_start_methods() else None
            executor = ProcessPoolExecutor(max_workers=workers, mp_context=context) if workers > 1 else None
            try:
                results = executor.map(_process_line, tasks, chunksize=1, buffersize=workers * 2) if executor else map(_process_line, tasks)
                writer = None
                digest = hashlib.sha256()
                shard_count = 0
                summary_after = copy.deepcopy(checkpoint["summary"])
                end_offset = checkpoint["next_offset"]
                end_line = checkpoint["last_line"]
                for line_number, next_offset, result in results:
                    if writer is None:
                        temporary = directory / (_part_name(checkpoint["next_shard"]) + ".tmp")
                        writer = temporary.open("wb")
                        digest = hashlib.sha256()
                    encoded = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                    writer.write(encoded)
                    digest.update(encoded)
                    _add_result(summary_after, result)
                    if progress_every and summary_after["records"] % progress_every == 0:
                        print(
                            f"processed={summary_after['records']} ok={summary_after['ok']} "
                            f"skipped={summary_after['skipped']} errors={summary_after['errors']}",
                            file=sys.stderr, flush=True,
                        )
                    shard_count += 1
                    end_offset, end_line = next_offset, line_number
                    if shard_count == shard_records:
                        writer.flush()
                        os.fsync(writer.fileno())
                        writer.close()
                        _finalize_shard(directory, checkpoint, temporary, digest, end_offset, end_line, summary_after)
                        writer = None
                        shard_count = 0
                        summary_after = copy.deepcopy(checkpoint["summary"])
                        if max_shards is not None and checkpoint["next_shard"] - initial_shards >= max_shards:
                            break
                else:
                    if writer is not None:
                        writer.flush()
                        os.fsync(writer.fileno())
                        writer.close()
                        _finalize_shard(directory, checkpoint, temporary, digest, end_offset, end_line, summary_after)
                    checkpoint["done"] = True
                    _atomic_json(checkpoint_file, checkpoint)
            finally:
                if executor:
                    executor.shutdown(wait=True, cancel_futures=True)
    summary = dict(checkpoint["summary"])
    duration = time.perf_counter() - started
    processed_now = summary["records"] - initial_records
    summary.update(
        done=checkpoint["done"], strategy=strategy, shards=checkpoint["next_shard"],
        cleaner_version=CLEANER_VERSION,
        profile_version=PROFILE_VERSION if strategy == "format" else None,
        input_sha256=input_sha256, elapsed_seconds=duration,
        records_per_second=processed_now / duration if duration else 0.0,
        peak_rss_kb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        mean_chunk_units=summary["unit_sum"] / summary["chunks"] if summary["chunks"] else 0.0,
        structural_boundary_rate=summary["structural_intact_chunks"] / summary["chunks"] if summary["chunks"] else 1.0,
        document_overlap_rate=summary["document_overlap_positive"] / summary["document_nonfirst_children"] if summary["document_nonfirst_children"] else 1.0,
        eligible_overlap_rate=summary["eligible_overlap_positive"] / summary["eligible_overlap_transitions"] if summary["eligible_overlap_transitions"] else 1.0,
        overlap_30_50_rate=summary["overlap_30_50"] / summary["eligible_overlap_transitions"] if summary["eligible_overlap_transitions"] else 1.0,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--strategy", choices=STRATEGIES, default="hybrid")
    parser.add_argument("--min-units", type=int, default=150)
    parser.add_argument("--target-units", type=int, default=220)
    parser.add_argument("--max-units", type=int, default=300)
    parser.add_argument("--overlap-units", type=int, default=40)
    parser.add_argument("--parent-max-units", type=int, default=1200)
    parser.add_argument("--shard-records", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    config = ChunkConfig(args.min_units, args.target_units, args.max_units, args.overlap_units, args.parent_max_units)
    report = run_chunking(args.input, args.output, config, strategy=args.strategy, shard_records=args.shard_records, workers=args.workers, resume=args.resume, progress_every=args.progress_every)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
