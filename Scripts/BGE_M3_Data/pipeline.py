"""CLI orchestration for local preparation and a complete Kaggle GPU run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .common import load_config, load_manifest, read_jsonl, record_stage, unique_rows, write_json, write_jsonl
from .corpus import prepare


def default_holdouts() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    paths = [root / "BackEnd/tests/hnsw_queries_50.json", root / "BackEnd/tests/ivfpq_queries_50_set2.json"]
    return [path for path in paths if path.is_file()]


def run_workers(stage: str, work: Path, config_path: Path, workers: int,
                limit_tasks: int | None = None) -> None:
    processes = []
    environment = dict(os.environ, PYTHONUNBUFFERED="1", TOKENIZERS_PARALLELISM="false")
    for worker in range(workers):
        command = [sys.executable, "-m", "Scripts.BGE_M3_Data.pipeline", stage,
                   "--work", str(work), "--config", str(config_path),
                   "--worker", str(worker), "--workers", str(workers), "--device", f"cuda:{worker}"]
        if limit_tasks is not None:
            command.extend(["--limit-tasks", str(limit_tasks)])
        processes.append(subprocess.Popen(command, env=environment))
    failures = []
    for worker, process in enumerate(processes):
        code = process.wait()
        if code:
            failures.append((worker, code))
    if failures:
        raise RuntimeError(f"{stage} workers failed: {failures}; checkpoints were preserved")


def probe_pipeline(work: Path, config: dict[str, Any], config_path: Path,
                   workers: int) -> dict[str, Any]:
    """Exercise real model mining/judging on an isolated, bounded warmup corpus."""
    import torch
    from .export import export_dataset
    from .mining import encode_corpus
    report_path = work / "warmup" / "probe-report.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    tasks = list(read_jsonl(work / "tasks.jsonl"))[:12]
    task_ids = {task["task_id"] for task in tasks}
    queries = [row for row in unique_rows(list(work.glob("queries-*.jsonl")), "query_id").values()
               if row["task_id"] in task_ids]
    required = {identity for row in queries for identity in row["positive_chunk_ids"]}
    corpus = list(read_jsonl(work / "corpus.jsonl"))
    sample = [row for row in corpus if row["chunk_id"] in required]
    sample.extend(row for row in corpus if row["chunk_id"] not in required)
    sample = sample[:max(5000, len(required))]
    probe = work / "warmup"
    probe.mkdir(exist_ok=True)
    write_json(probe / "manifest.json", {"configuration": config, "stages": {}, "warmup_mode": True,
                                         "source_sha256": load_manifest(work)["source_sha256"]})
    write_jsonl(probe / "corpus.jsonl", sample)
    write_jsonl(probe / "tasks.jsonl", tasks)
    write_jsonl(probe / "queries-0.jsonl", queries)
    write_jsonl(probe / "generation-ledger-0.jsonl", (
        row for row in unique_rows(list(work.glob("generation-ledger-*.jsonl")), "task_id").values()
        if row["task_id"] in task_ids))
    encode_corpus(probe, config, "cuda:0")
    torch.cuda.empty_cache()
    run_workers("mine", probe, config_path, workers)
    mined = unique_rows(list(probe.glob("mined-*.jsonl")), "query_id")
    write_jsonl(probe / "mined.jsonl", (mined[key] for key in sorted(mined)))
    run_workers("judge-negatives", probe, config_path, workers)
    exported = export_dataset(probe, config, allow_small=True)
    report = {"tested_queries": len(queries), "verified_triplets": exported["exported_queries"],
              "minimum_verified_triplets": min(4, len(queries)), "probe_corpus_chunks": len(sample),
              "complete": exported["exported_queries"] >= min(4, len(queries))}
    write_json(report_path, report)
    return report


def run_all(args: argparse.Namespace, config: dict[str, Any]) -> None:
    import torch
    from .export import export_dataset
    from .mining import encode_corpus
    from .models import preflight
    capabilities = preflight()
    capabilities["code_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in Path(__file__).parent.glob("*.py")}
    print(json.dumps({"runtime": capabilities}), flush=True)
    prepare(args.input, args.work, config, args.holdout_queries or default_holdouts(), args.expected_sha256)
    record_stage(args.work, "runtime", capabilities)
    workers = min(config["workers"], torch.cuda.device_count())
    # Fail early on actual generation quality before the longer embedding/mining pass.
    run_workers("generate", args.work, args.config, workers, limit_tasks=12)
    tasks = list(unique_rows([args.work / "tasks.jsonl"], "task_id").values())[:12]
    journal = unique_rows(list(args.work.glob("generation-ledger-*.jsonl")), "task_id")
    warmup_count = sum(journal.get(task["task_id"], {}).get("accepted_queries", 0) for task in tasks)
    minimum_warmup = min(8, len(tasks))
    record_stage(args.work, "warmup", {"tasks": len(tasks), "accepted_queries": warmup_count,
                                       "minimum_queries": minimum_warmup, "complete": warmup_count >= minimum_warmup})
    if warmup_count < minimum_warmup:
        raise RuntimeError("Warmup produced too few grounded questions; full generation was stopped. Inspect generation journals.")
    probe = probe_pipeline(args.work, config, args.config, workers)
    record_stage(args.work, "model_probe", probe)
    if not probe["complete"]:
        raise RuntimeError("Warmup mining/judging produced too few verified triplets; the full GPU run was stopped")
    run_workers("generate", args.work, args.config, workers)
    generated = unique_rows(list(args.work.glob("queries-*.jsonl")), "query_id")
    record_stage(args.work, "generate", {"queries": len(generated), "complete": True})
    encoding = encode_corpus(args.work, config, "cuda:0")
    record_stage(args.work, "encode", encoding)
    # Release the parent allocator before child workers load their own GPU models.
    torch.cuda.empty_cache()
    run_workers("mine", args.work, args.config, workers)
    mined = unique_rows(list(args.work.glob("mined-*.jsonl")), "query_id")
    write_jsonl(args.work / "mined.jsonl", (mined[identity] for identity in sorted(mined)))
    record_stage(args.work, "mine", {"accepted_queries": len(mined), "complete": True})
    run_workers("judge-negatives", args.work, args.config, workers)
    record_stage(args.work, "judge_negatives", {"queries": len(unique_rows(list(args.work.glob("negative-judgments-*.jsonl")), "query_id")), "complete": True})
    export_dataset(args.work, config, args.allow_small)


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    for stage in ("prepare", "generate", "encode", "mine", "judge-negatives", "export", "all"):
        command = subparsers.add_parser(stage)
        command.add_argument("--work", type=Path, required=True)
        command.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
        if stage in ("prepare", "all"):
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--holdout-queries", type=Path, action="append")
            command.add_argument("--expected-sha256")
        if stage in ("generate", "mine", "judge-negatives"):
            command.add_argument("--worker", type=int, default=0)
            command.add_argument("--workers", type=int, default=1)
            command.add_argument("--limit-tasks", type=int)
        if stage in ("generate", "encode", "mine", "judge-negatives"):
            command.add_argument("--device", default="cuda:0")
        if stage in ("export", "all"):
            command.add_argument("--allow-small", action="store_true")
    return parser


def main() -> None:
    args = argument_parser().parse_args()
    config = load_config(args.config)
    if args.stage == "prepare":
        prepare(args.input, args.work, config, args.holdout_queries or default_holdouts(), args.expected_sha256)
    elif args.stage == "all":
        run_all(args, config)
    else:
        manifest = load_manifest(args.work)
        if manifest["configuration"] != config:
            raise ValueError("Configuration differs from the prepared run")
        if hasattr(args, "worker") and not 0 <= args.worker < args.workers:
            raise ValueError("Worker index must be inside the worker count")
        if args.stage == "generate":
            from .generation import generate_worker
            generate_worker(args.work, config, args.worker, args.workers, args.device, args.limit_tasks)
        elif args.stage == "encode":
            from .mining import encode_corpus
            record_stage(args.work, "encode", encode_corpus(args.work, config, args.device))
        elif args.stage == "mine":
            from .mining import mine_worker
            mine_worker(args.work, config, args.worker, args.workers, args.device)
        elif args.stage == "judge-negatives":
            from .generation import judge_negative_worker
            judge_negative_worker(args.work, config, args.worker, args.workers, args.device)
        elif args.stage == "export":
            from .export import export_dataset
            export_dataset(args.work, config, args.allow_small)


if __name__ == "__main__":
    main()
