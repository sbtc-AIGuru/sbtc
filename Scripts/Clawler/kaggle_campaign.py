"""Export sparse campaign tails to two private Kaggle notebooks and run them."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from time import time
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from backfill import (
    campaign_report, connect, fingerprint, ingest_files, validate_result,
    initialize_campaign_database, read_manifest, reconcile, run_campaign, verify_inputs,
)
from fetch_policy import HostPolicy


CODE_FILES = (
    "backfill.py", "compact.py", "fetch.py", "fetch_policy.py", "http_strategy.py",
    "kaggle_campaign.py", "pagination.py", "quality.py", "site_configs.py",
    "utils.py", "verbatim.py",
)
SKIP_STATES = {"success", "permanent_failure", "running"}


def remote_policy(host: str, original: HostPolicy, peers: int, local_active: bool) -> HostPolicy:
    """Ramp up validated HTTP sources within a shared family request budget."""
    divisor = peers + int(local_active)
    if original.group == "39.net":
        return replace(original, concurrency=max(1, 12 // divisor),
                       interval_seconds=0.5 * divisor, minimum_interval_seconds=0.1 * divisor,
                       recovery_successes=20, max_attempts=1)
    if host == "nhathuoclongchau.com.vn":
        return replace(original, concurrency=1, interval_seconds=2.5 * divisor,
                       minimum_interval_seconds=2.5, max_attempts=1, fetch_mode="browser")
    if host in {"article.iiyi.com", "pmc-ecm-healthblog.beta.pharmacity.io"}:
        return replace(original, concurrency=1, interval_seconds=3.0 * divisor,
                       minimum_interval_seconds=3.0, max_attempts=1)
    if host not in {"qihuangzhishu.com", "suckhoeviet.org.vn", "health.people.com.cn"}:
        return replace(original, concurrency=max(1, original.concurrency // divisor),
                       interval_seconds=original.interval_seconds * divisor,
                       minimum_interval_seconds=(original.minimum_interval_seconds * divisor
                                                 if original.minimum_interval_seconds is not None else None))
    return replace(original, concurrency=max(1, 6 // divisor), interval_seconds=0.5 * divisor,
                   minimum_interval_seconds=0.2 * divisor, recovery_successes=20, max_attempts=1)


def balanced_host_partition(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Split equal row counts without duplicating a hostname across notebooks."""
    if len(rows) % 2:
        raise ValueError("The selected row count must be even")
    target = len(rows) // 2
    counts = Counter(str(row["host"]) for row in rows)
    hosts = sorted(counts, key=lambda host: (-counts[host], host))
    mask = (1 << (target + 1)) - 1
    reachable = 1
    history = []
    for host in hosts:
        history.append(reachable)
        reachable = (reachable | (reachable << counts[host])) & mask
    if not (reachable >> target) & 1:
        raise ValueError("Cannot make two equal shards with disjoint hostnames")
    first_hosts = set()
    remaining = target
    for host, before in reversed(list(zip(hosts, history))):
        if not (before >> remaining) & 1:
            first_hosts.add(host)
            remaining -= counts[host]
    first = [row for row in rows if row["host"] in first_hosts]
    second = [row for row in rows if row["host"] not in first_hosts]
    if remaining or len(first) != target or len(second) != target:
        raise ValueError("Host partition failed its coverage invariant")
    return first, second


def verify_source_rows(source: Path, rows: list[dict[str, object]]) -> None:
    """Compare every exported ID/URL with its original global Parquet row."""
    parquet = pq.ParquetFile(source)
    cursor = offset = 0
    for group in range(parquet.num_row_groups):
        count = parquet.metadata.row_group(group).num_rows
        if cursor == len(rows):
            break
        if int(rows[cursor]["row_index"]) >= offset + count:
            offset += count
            continue
        for batch in parquet.iter_batches(batch_size=8192, row_groups=[group], columns=["id", "url"]):
            positions = []
            selected = []
            while cursor < len(rows) and int(rows[cursor]["row_index"]) < offset + batch.num_rows:
                row = rows[cursor]
                positions.append(int(row["row_index"]) - offset)
                selected.append(row)
                cursor += 1
            if positions:
                values = pa.Table.from_batches([batch]).take(pa.array(positions)).to_pylist()
                for row, value in zip(selected, values):
                    if (row["id"], row["url"]) != (value["id"], value["url"]):
                        raise ValueError(f"Source mapping mismatch: row {row['row_index']}")
            offset += batch.num_rows
    if cursor != len(rows):
        raise ValueError("Source Parquet does not cover all selected rows")


def notebook_document(shard_id: int, dataset_slug: str, export_id: str,
                      wall_hours: float = 11.0) -> dict[str, object]:
    """Build an actual ipynb using only its private immutable input bundle."""
    setup = f'''from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, zipfile

BUNDLE = Path("/kaggle/input/{dataset_slug}")
if not (BUNDLE / "export.json").exists():
    BUNDLE = next(path.parent for path in Path("/kaggle/input").rglob("export.json")
                  if json.loads(path.read_text()).get("export_id") == {export_id!r})
WORK = Path("/kaggle/working/backfill-shard-{shard_id}")
PROJECT = Path("/tmp/crawler-project-{shard_id}")
VENV = Path("/tmp/crawler-venv-{shard_id}")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/tmp/sbtc-browser-cache"
WORK.mkdir(parents=True, exist_ok=True)
PROJECT.mkdir(parents=True, exist_ok=True)
metadata = json.loads((BUNDLE / "export.json").read_text())
assert metadata["export_id"] == {export_id!r}, "Unexpected export bundle"
print("Export:", metadata["export_id"], "shard:", {shard_id}, flush=True)
subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", "--without-pip", str(VENV)], check=True)
PYTHON = VENV / "bin/python"
subprocess.run([sys.executable, "-m", "pip", "--python", str(PYTHON), "install", "-r", str(BUNDLE / "requirements.txt")], check=True)
subprocess.run([str(PYTHON), "-m", "playwright", "install", "--with-deps", "chromium"], check=True)
if (BUNDLE / "crawler-code.zip").exists():
    with zipfile.ZipFile(BUNDLE / "crawler-code.zip") as archive:
        archive.extractall(PROJECT)
else:
    shutil.copytree(BUNDLE / "crawler-code", PROJECT, dirs_exist_ok=True)
for name, expected in metadata["code_hashes"].items():
    actual = hashlib.sha256((PROJECT / "Scripts/Clawler" / name).read_bytes()).hexdigest()
    assert actual == expected, f"Crawler code checksum changed: {{name}}"
print("Runtime ready; exact crawler code extracted", flush=True)
'''
    run = f'''import subprocess, os
environment = dict(os.environ, PYTHONUNBUFFERED="1", CRAWL4_AI_BASE_DIRECTORY=str(WORK))
command = [
    str(PYTHON), str(PROJECT / "Scripts/Clawler/kaggle_campaign.py"), "worker",
    "--bundle", str(BUNDLE), "--shard", "{shard_id}", "--work", str(WORK),
    "--max-rounds", "8",
]
# The pilot uses the production ledger, so its successful URLs are retained.
subprocess.run(command + ["--wall-hours", "0.15", "--pilot-per-host", "3", "--limit", "60"],
               env=environment, check=True)
pilot = json.loads((WORK / "report.json").read_text())
(WORK / "preflight-report.json").write_text(json.dumps(pilot, ensure_ascii=False, indent=2))
print("Preflight:", pilot["new_success"], "new successes;", pilot["remaining_remote"], "remaining", flush=True)
subprocess.run(command + ["--wall-hours", {str(wall_hours)!r}], env=environment, check=True)
report = json.loads((WORK / "report.json").read_text())
print("COVERAGE:", "COMPLETE" if report["coverage_complete"] else "PARTIAL",
      "successes:", report["counts"].get("success", 0),
      "remaining:", report["remaining_remote"], "stop:", report["stop_reason"], flush=True)
'''
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                     "language_info": {"name": "python"},
                     "kaggle": {"isInternetEnabled": True, "isGpuEnabled": False, "sourceType": "notebook"}},
        "cells": [
            {"cell_type": "markdown", "id": "description", "metadata": {}, "source":
             f"# Current campaign tail — shard {shard_id}\n\n"
             "100,000 planned URL slots. Rows already completed, permanently failed or in flight locally "
             "at export are skipped. Outputs are written after 50 results or 5 seconds. "
             f"An {wall_hours:g}-hour pass preserves prior journals and saves a resumable checkpoint. "
             "The final COVERAGE line reports actual successful coverage."},
            *[{"cell_type": "code", "id": cell_id, "metadata": {}, "execution_count": None,
               "outputs": [], "source": code} for cell_id, code in (("setup", setup), ("crawl", run))],
        ],
    }


def prepare_export(campaign: Path, output: Path, owner: str, count: int = 200_000,
                   local_worker_active: bool = True, resume_from: Path | None = None,
                   resume_outputs: Path | None = None, wall_hours: float = 11.0) -> dict[str, object]:
    """Snapshot exactly the highest campaign row indices without changing local state."""
    if output.exists():
        raise FileExistsError(f"Export directory already exists: {output}")
    if count < 2 or count % 2:
        raise ValueError("Tail count must be positive and even")
    parent = read_manifest(campaign)
    verify_inputs(parent)
    database = sqlite3.connect(f"file:{(campaign / 'state.sqlite3').resolve()}?mode=ro", uri=True)
    database.row_factory = sqlite3.Row
    try:
        database.execute("BEGIN")
        rows = [dict(row) for row in database.execute(
            "SELECT row_index,id,url,host,group_key,state,rounds,next_retry_at,last_error "
            "FROM targets ORDER BY row_index DESC LIMIT ?", (count,))]
        origins = [dict(row) for row in database.execute("SELECT * FROM origins")]
    finally:
        database.close()
    if len(rows) != count:
        raise ValueError(f"Campaign contains fewer than {count} targets")
    rows.reverse()
    verify_source_rows(Path(parent["source"]["path"]), rows)
    shards = balanced_host_partition(rows)
    previous = None
    resume_hashes = {}
    if (resume_from is None) != (resume_outputs is None):
        raise ValueError("Resume export and downloaded journals must be supplied together")
    if resume_from is not None:
        previous = json.loads((resume_from / "export.json").read_text())
        if previous["campaign_id"] != parent["campaign_id"]:
            raise ValueError("Resume export belongs to a different campaign")
        for shard_id, shard_rows in enumerate(shards, 1):
            _, _, old_rows = load_shard(resume_from / "dataset", shard_id)
            identity = lambda values: [(r["row_index"], r["id"], r["url"]) for r in values]
            if identity(old_rows) != identity(shard_rows):
                raise ValueError("Relaunch changed the original shard scope")
            for name in ("results.jsonl", "attempts.jsonl"):
                path = resume_outputs / f"part-{shard_id}" / name
                resume_hashes[f"{shard_id}-{name}"] = fingerprint(path)["sha256"]
    logical_digest = hashlib.sha256(json.dumps(
        {"rows": [(row["row_index"], row["id"], row["url"], row["state"], row["rounds"]) for row in rows],
         "resume_hashes": resume_hashes, "runtime_profile": "adaptive_http_v2", "wall_hours": wall_hours,
         "source_export_id": previous["export_id"] if previous else None},
        ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    export_id = f"{parent['campaign_id']}-tail{count}-{logical_digest[:12]}"
    dataset_slug = f"sbtc-backfill-{parent['campaign_id'][:8]}-tail{count}-{logical_digest[:8]}"
    owners = Counter(group for shard in shards for group in {str(row["group_key"]) for row in shard})
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="kaggle-export-", dir=output.parent) as temporary_dir:
        temporary = Path(temporary_dir)
        bundle = temporary / "dataset"
        bundle.mkdir()
        metadata = {
            "version": 2, "campaign_id": parent["campaign_id"], "export_id": export_id,
            "source_export_id": previous["export_id"] if previous else None,
            "source_export_ids": list(dict.fromkeys(
                [previous["export_id"], *previous.get("source_export_ids", []),
                 *([previous["source_export_id"]] if previous.get("source_export_id") else [])]
            )) if previous else [],
            "runtime_profile": "adaptive_http_v2", "wall_hours": wall_hours, "max_rounds": 8,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parent_campaign": str(campaign.resolve()), "source": parent["source"],
            "baseline": parent["baseline"], "selected_count": count,
            "selection": "highest row_index among all original campaign targets",
            "minimum_row_index": rows[0]["row_index"], "maximum_row_index": rows[-1]["row_index"],
            "dataset": f"{owner}/{dataset_slug}", "local_worker_active": local_worker_active,
            "origin_notebook_count": dict(owners), "origins": origins, "policies": parent["policies"],
            "shards": [], "code_hashes": {},
        }
        for shard_id, shard_rows in enumerate(shards, 1):
            path = bundle / f"shard-{shard_id}.parquet"
            pq.write_table(pa.Table.from_pylist(shard_rows), path, compression="zstd")
            skipped = Counter(str(row["state"]) for row in shard_rows if row["state"] in SKIP_STATES)
            kernel_slug = f"sbtc-backfill-{parent['campaign_id'][:8]}-tail{count}-part-{shard_id}"
            shard = {"shard_id": shard_id, "file": path.name,
                     "sha256": fingerprint(path)["sha256"], "selected_count": len(shard_rows),
                     "skip_snapshot_states": dict(skipped),
                     "runnable_count": len(shard_rows) - sum(skipped.values()),
                     "hosts": sorted({str(row["host"]) for row in shard_rows}),
                     "kernel": f"{owner}/{kernel_slug}"}
            if previous:
                shard["resume_files"] = []
                for name in ("results.jsonl", "attempts.jsonl"):
                    relative = f"resume-{shard_id}-{name}"
                    shutil.copyfile(resume_outputs / f"part-{shard_id}" / name, bundle / relative)
                    shard["resume_files"].append({"file": relative, "role": name,
                                                "sha256": resume_hashes[f"{shard_id}-{name}"]})
            metadata["shards"].append(shard)
            notebook_dir = temporary / f"notebook-{shard_id}"
            notebook_dir.mkdir()
            (notebook_dir / "notebook.ipynb").write_text(json.dumps(
                notebook_document(shard_id, dataset_slug, export_id, wall_hours), ensure_ascii=False, indent=2) + "\n")
            (notebook_dir / "kernel-metadata.json").write_text(json.dumps({
                "id": shard["kernel"], "title": kernel_slug.replace("-", " "),
                "code_file": "notebook.ipynb", "language": "python", "kernel_type": "notebook",
                "is_private": True, "enable_gpu": False, "enable_tpu": False,
                "enable_internet": True, "dataset_sources": [metadata["dataset"]],
                "competition_sources": [], "kernel_sources": [], "model_sources": [],
            }, indent=2) + "\n")
        with zipfile.ZipFile(bundle / "crawler-code.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in CODE_FILES:
                path = Path(__file__).parent / name
                metadata["code_hashes"][name] = fingerprint(path)["sha256"]
                archive.write(path, f"Scripts/Clawler/{name}")
        (bundle / "requirements.txt").write_text("crawl4ai==0.9.4\npyarrow==25.0.1\nplaywright==1.63.0\n")
        (bundle / "export.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        (bundle / "dataset-metadata.json").write_text(json.dumps({
            "id": metadata["dataset"], "title": dataset_slug,
            "licenses": [{"name": "other"}],
            "description": "Private current-campaign sparse crawl plan and exact crawler code. Original source licenses remain applicable.",
        }, indent=2) + "\n")
        (temporary / "export.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        shutil.move(str(temporary), str(output))
    return metadata


def load_shard(bundle: Path, shard_id: int) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Validate the immutable shard before making requests or trusting a checkpoint."""
    metadata = json.loads((bundle / "export.json").read_text())
    shard = next((item for item in metadata["shards"] if item["shard_id"] == shard_id), None)
    if shard is None:
        raise ValueError("Unknown shard")
    path = bundle / shard["file"]
    if fingerprint(path)["sha256"] != shard["sha256"]:
        raise ValueError("Shard checksum changed")
    rows = pq.read_table(path).to_pylist()
    if len(rows) != shard["selected_count"] or len({row["row_index"] for row in rows}) != len(rows):
        raise ValueError("Incomplete or duplicate shard rows")
    return metadata, shard, rows


def restore_journals(bundle: Path, work: Path, database: sqlite3.Connection,
                     metadata: dict[str, object], shard: dict[str, object]) -> int:
    """Validate and replay exact prior shard outputs without importing other data."""
    entries = shard.get("resume_files", [])
    roles = [entry["role"] for entry in entries]
    if entries and sorted(roles) != ["attempts.jsonl", "results.jsonl"]:
        raise ValueError("Resume must contain exactly the two shard journals")
    for entry in entries:
        path = bundle / entry["file"]
        if path.name != entry["file"] or fingerprint(path)["sha256"] != entry["sha256"]:
            raise ValueError("Resume journal checksum or path changed")
        with path.open("rb") as handle:
            for line in handle:
                if not line.endswith(b"\n"):
                    raise ValueError("Resume journal has an incomplete final line")
                value = json.loads(line)
                if entry["role"] == "results.jsonl":
                    validate_result(database, value)
                    allowed = metadata.get("source_export_ids", [metadata["source_export_id"]])
                    if (value.get("campaign_id"), value.get("shard_id")) != (
                        metadata["campaign_id"], shard["shard_id"]
                    ) or value.get("export_id") not in allowed:
                        raise ValueError("Resume result belongs to a different export/shard")
                else:
                    target = database.execute("SELECT id,url FROM targets WHERE row_index=?",
                                              (value["row_index"],)).fetchone()
                    if target is None or (value.get("id"), value.get("source_url")) != (target["id"], target["url"]):
                        raise ValueError("Resume attempt has wrong source identity")
    result_files = [bundle / entry["file"] for entry in entries if entry["role"] == "results.jsonl"]
    restored = ingest_files(work, database, metadata, result_files)
    for entry in entries:
        if entry["role"] == "attempts.jsonl":
            shutil.copyfile(bundle / entry["file"], work / "attempts.jsonl")
    return restored


def initialize_worker(bundle: Path, shard_id: int, work: Path) -> dict[str, object]:
    """Create or validate a resumable sparse ledger with original global row indices."""
    metadata, shard, rows = load_shard(bundle, shard_id)
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = work / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get("export_id"), manifest.get("shard_id"), manifest.get("shard_sha256")) != (
            metadata["export_id"], shard_id, shard["sha256"]
        ):
            raise ValueError("Checkpoint belongs to a different export/shard")
        return manifest
    policies = {}
    for host in shard["hosts"]:
        policy = HostPolicy(**metadata["policies"][host])
        group = policy.group or host
        peers = metadata["origin_notebook_count"][group]
        if metadata.get("runtime_profile") == "adaptive_http_v2":
            policies[host] = asdict(remote_policy(host, policy, peers, metadata["local_worker_active"]))
        else:
            divisor = peers + int(metadata["local_worker_active"])
            policies[host] = asdict(replace(policy, concurrency=max(1, policy.concurrency // divisor),
                                           interval_seconds=policy.interval_seconds * divisor))
    manifest = {"campaign_id": metadata["campaign_id"], "export_id": metadata["export_id"],
                "shard_id": shard_id, "target_rows": len(rows), "policies": policies,
                "snapshot_skip_states": shard["skip_snapshot_states"], "shard_sha256": shard["sha256"],
                "pacing_scope": "session" if metadata.get("runtime_profile") == "adaptive_http_v2" else "persistent"}
    with connect(work) as database:
        initialize_campaign_database(database)
        database.executemany(
            "INSERT INTO targets(row_index,id,url,host,group_key,state,rounds,next_retry_at,last_error) VALUES(?,?,?,?,?,?,?,?,?)",
            [(row["row_index"], row["id"], row["url"], row["host"], row["group_key"],
              f"local_{row['state']}" if row["state"] in SKIP_STATES else row["state"],
              row["rounds"], row["next_retry_at"], row["last_error"]) for row in rows],
        )
        groups = {row["group_key"] for row in rows}
        database.executemany("INSERT INTO origins VALUES(?,?,?)",
                             [(row["group_key"], row["next_retry_at"], row["interval_seconds"])
                              for row in metadata["origins"] if row["group_key"] in groups])
        manifest["resumed_records"] = restore_journals(bundle, work, database, metadata, shard)
        # A failed remote attempt cannot remove a newer local terminal/in-flight
        # state. Good remote text remains available even when local also succeeded.
        database.executemany("UPDATE targets SET state=? WHERE row_index=? AND state!='success'",
                             [(f"local_{row['state']}", row["row_index"])
                              for row in rows if row["state"] in SKIP_STATES])
        manifest["resumed_success"] = database.execute("SELECT COUNT(*) FROM targets WHERE state='success'").fetchone()[0]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


async def run_worker(args: argparse.Namespace) -> None:
    """Run one bounded session and publish explicit coverage plus a checkpoint."""
    manifest = initialize_worker(args.bundle, args.shard, args.work)
    run_args = argparse.Namespace(
        campaign=args.work, group=[], host=[], fetch_mode="auto", max_in_flight=48,
        http_concurrency=24, browser_concurrency=4, browser_recycle_after=500,
        min_free_memory_gb=2.0, max_rounds=args.max_rounds,
        limit=getattr(args, "limit", 0), pilot_per_host=getattr(args, "pilot_per_host", 0),
        retry_only=False, wait_for_retries=not (getattr(args, "pilot_per_host", 0) or getattr(args, "limit", 0)),
        write_batch_size=50, write_interval_seconds=5.0,
    )
    reason = "ready_work_exhausted"
    started = time()
    with connect(args.work) as database:
        reconcile(database, args.work)
        initial_success = database.execute("SELECT COUNT(*) FROM targets WHERE state='success'").fetchone()[0]
        print(f"[Kaggle] Starting export={manifest['export_id']} shard={args.shard} planned={manifest['target_rows']}", flush=True)
        try:
            await asyncio.wait_for(run_campaign(run_args, database, manifest), timeout=args.wall_hours * 3600)
        except TimeoutError:
            reason = "session_time_limit"
        except asyncio.CancelledError:
            reason = "interrupted"
            raise
        except Exception:
            reason = "worker_error"
            raise
        finally:
            report = campaign_report(database, args.work, args.max_rounds)
            states = report["counts"]
            skipped = sum(n for state, n in states.items() if state.startswith("local_"))
            report.update(export_id=manifest["export_id"], shard_id=args.shard,
                          planned=manifest["target_rows"], skipped_snapshot=skipped,
                          remaining_remote=sum(n for state, n in states.items()
                                               if state not in {"success"} and not state.startswith("local_")),
                          stop_reason=reason, wall_seconds=round(time() - started, 1))
            report.update(coverage_complete=report["remaining_remote"] == 0,
                          resumed_success=initial_success, new_success=states.get("success", 0) - initial_success,
                          success_per_hour=round((states.get("success", 0) - initial_success) * 3600 / max(time() - started, 0.001), 1))
            (args.work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            with zipfile.ZipFile(args.work / "checkpoint.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in ("manifest.json", "state.sqlite3", "results.jsonl", "attempts.jsonl", "report.json"):
                    path = args.work / name
                    if path.exists():
                        archive.write(path, name)
            print(f"[Kaggle] Pass ended: {json.dumps({key: report[key] for key in ['planned', 'skipped_snapshot', 'remaining_remote', 'stop_reason']})}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--campaign", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--owner", required=True)
    prepare.add_argument("--tail-count", type=int, default=200_000)
    prepare.add_argument("--resume-from", type=Path)
    prepare.add_argument("--resume-outputs", type=Path)
    prepare.add_argument("--wall-hours", type=float, default=11.0)
    worker = commands.add_parser("worker")
    worker.add_argument("--bundle", type=Path, required=True)
    worker.add_argument("--shard", type=int, choices=[1, 2], required=True)
    worker.add_argument("--work", type=Path, required=True)
    worker.add_argument("--wall-hours", type=float, default=11.0)
    worker.add_argument("--max-rounds", type=int, default=8)
    worker.add_argument("--limit", type=int, default=0)
    worker.add_argument("--pilot-per-host", type=int, default=0)
    args = parser.parse_args()
    if args.command == "prepare":
        if not 0 < args.wall_hours <= 11:
            parser.error("Wall hours must be positive and at most 11")
        metadata = prepare_export(args.campaign, args.output, args.owner, args.tail_count,
                                  resume_from=args.resume_from, resume_outputs=args.resume_outputs,
                                  wall_hours=args.wall_hours)
        print(json.dumps({key: metadata[key] for key in ['export_id', 'dataset', 'selected_count', 'minimum_row_index', 'maximum_row_index', 'shards']}, indent=2))
    else:
        if args.wall_hours <= 0 or args.max_rounds < 1 or min(args.limit, args.pilot_per_host) < 0:
            parser.error("Wall time and rounds must be positive")
        asyncio.run(run_worker(args))


if __name__ == "__main__":
    main()
