"""Prepare, run, inspect, and merge a campaign based only on its current baseline."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
from contextlib import AsyncExitStack, ExitStack, contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import monotonic, time
from typing import Iterator

from fetch_policy import FetchController, HostPolicy, active_controller, hostname, read_policies
from utils import SourceRecord, get_row_count, load_completed_ids, load_url_range
from verbatim import remove_link_targets


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = PROJECT_ROOT / "data/crawled_local_kaggle_success_unique_20261005.jsonl"
DEFAULT_SOURCE = PROJECT_ROOT / "data/links_corpus.parquet"
HOST_LOCK_DIRECTORY = PROJECT_ROOT / ".backfill/host_locks"


def fingerprint(path: Path) -> dict[str, object]:
    """Hash input contents and retain inexpensive change-detection metadata."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(),
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def source_records(source: Path, start: int, end: int) -> Iterator[SourceRecord]:
    for batch in load_url_range(source, start, end, 8192):
        yield from batch


@contextmanager
def connect(campaign: Path) -> Iterator[sqlite3.Connection]:
    database = sqlite3.connect(campaign / "state.sqlite3")
    database.row_factory = sqlite3.Row
    try:
        with database:
            yield database
    finally:
        database.close()


def read_manifest(campaign: Path) -> dict[str, object]:
    return json.loads((campaign / "manifest.json").read_text(encoding="utf-8"))


def verify_inputs(manifest: dict[str, object]) -> None:
    """Refuse changed source files; unchanged files need no second full scan."""
    for name in ("source", "baseline"):
        expected = manifest[name]
        path = Path(expected["path"])
        stat = path.stat()
        if stat.st_size != expected["size"] or stat.st_mtime_ns != expected["mtime_ns"]:
            if fingerprint(path)["sha256"] != expected["sha256"]:
                raise ValueError(f"Campaign {name} changed: {path}")


@contextmanager
def campaign_lock(campaign: Path):
    """Prevent simultaneous run, ingestion, or merge against one journal."""
    with (campaign / "campaign.lock").open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Campaign is already in use: {campaign}") from error
        yield


def prepare(
    source: Path, baseline: Path, campaign: Path, min_gap: int = 1001,
    max_index: int | None = None, policy_file: Path | None = None,
) -> dict[str, object]:
    """Validate the baseline once and select only genuinely missing ranges."""
    if min_gap < 1 or (max_index is not None and max_index < 0):
        raise ValueError("min_gap must be positive and max_index nonnegative")
    if campaign.exists():
        raise FileExistsError(f"Campaign already exists: {campaign}")
    policies = read_policies(policy_file)
    policy_controller = FetchController(policies)
    source_info = fingerprint(source)
    baseline_stat = baseline.stat()
    digest = hashlib.sha256()
    records = iter(source_records(source, 0, get_row_count(source) - 1))
    original = None
    previous = -1
    baseline_rows = 0
    gaps: list[tuple[int, int]] = []
    with baseline.open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            digest.update(line)
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Baseline record must be an object: line {line_number}")
            index = value.get("row_index")
            if type(index) is not int or index <= previous:
                raise ValueError(f"Baseline must have unique increasing row_index: line {line_number}")
            if value.get("success") is not True or not isinstance(value.get("text"), str) or not value["text"].strip():
                raise ValueError(f"Baseline must contain successful text: line {line_number}")
            while original is None or original.row_index < index:
                original = next(records, None)
                if original is None:
                    raise ValueError(f"Baseline row_index exceeds Parquet: {index}")
            if (value.get("id"), value.get("url")) != (original.id, original.url):
                raise ValueError(f"Baseline ID/URL mismatch at row {index}")
            if index > previous + 1:
                gaps.append((previous + 1, index - 1))
            previous = index
            baseline_rows += 1
            if baseline_rows % 100_000 == 0:
                print(f"[Prepare] Validated {baseline_rows} baseline rows", flush=True)
    if previous < 0:
        raise ValueError("Baseline is empty; cannot infer its maximum index")
    after = baseline.stat()
    if (after.st_size, after.st_mtime_ns) != (baseline_stat.st_size, baseline_stat.st_mtime_ns):
        raise ValueError("Baseline changed during preparation")
    upper = previous if max_index is None else max_index
    if upper > previous:
        raise ValueError("max_index must not exceed the current baseline maximum")
    gaps = [(start, min(end, upper)) for start, end in gaps if start <= upper]
    selected = [(start, end) for start, end in gaps if end - start + 1 >= min_gap]
    campaign.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="backfill-prepare-", dir=campaign.parent) as directory:
        temporary = Path(directory)
        with connect(temporary) as database:
            database.executescript("""
                CREATE TABLE targets (
                    row_index INTEGER PRIMARY KEY, id INTEGER NOT NULL, url TEXT NOT NULL,
                    host TEXT NOT NULL, group_key TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', rounds INTEGER NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
                    success_offset INTEGER
                );
                CREATE INDEX targets_ready ON targets(group_key, state, next_retry_at, row_index);
                CREATE INDEX targets_host ON targets(host, row_index);
                CREATE TABLE origins (group_key TEXT PRIMARY KEY, next_retry_at REAL NOT NULL DEFAULT 0,
                                      interval_seconds REAL NOT NULL DEFAULT 0);
                CREATE TABLE receipts (sha256 TEXT PRIMARY KEY, path TEXT NOT NULL);
            """)
            target_count = 0
            host_policies = {}
            if selected:
                range_index = 0
                pending = []
                for record in source_records(source, selected[0][0], selected[-1][1]):
                    while range_index < len(selected) and selected[range_index][1] < record.row_index:
                        range_index += 1
                    if range_index == len(selected):
                        break
                    if record.row_index < selected[range_index][0]:
                        continue
                    host = hostname(record.url)
                    _, policy = policy_controller.policy(record.url)
                    host_policies[host] = asdict(policy)
                    pending.append((record.row_index, record.id, record.url, host, policy.group or host))
                    target_count += 1
                    if len(pending) >= 8192:
                        database.executemany("INSERT INTO targets(row_index,id,url,host,group_key) VALUES(?,?,?,?,?)", pending)
                        pending.clear()
                database.executemany("INSERT INTO targets(row_index,id,url,host,group_key) VALUES(?,?,?,?,?)", pending)
            FetchController({host: HostPolicy(**value) for host, value in host_policies.items()})
            if target_count != sum(end - start + 1 for start, end in selected):
                raise ValueError("Incomplete mapping of selected ranges to Parquet")
            database.execute("INSERT INTO origins(group_key) SELECT DISTINCT group_key FROM targets")
            manifest = {
                "version": 1, "source": source_info,
                "baseline": {"path": str(baseline.resolve()), "sha256": digest.hexdigest(),
                             "size": baseline_stat.st_size, "mtime_ns": baseline_stat.st_mtime_ns},
                "baseline_rows": baseline_rows, "baseline_max_index": previous, "max_index": upper,
                "min_gap": min_gap, "missing_rows": sum(end - start + 1 for start, end in gaps),
                "missing_range_count": len(gaps), "target_rows": target_count,
                "ranges": selected, "policies": host_policies,
            }
            manifest["campaign_id"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
            (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if fingerprint(source)["sha256"] != source_info["sha256"]:
            raise ValueError("Parquet changed during preparation")
        temporary.rename(campaign)
    return manifest


def validate_result(database: sqlite3.Connection, value: dict[str, object]) -> sqlite3.Row:
    """Check result identity and usable text before it can enter the journal."""
    if not isinstance(value, dict) or type(value.get("row_index")) is not int or type(value.get("id")) is not int:
        raise ValueError("Result must have an integer row_index")
    target = database.execute("SELECT * FROM targets WHERE row_index=?", (value.get("row_index"),)).fetchone()
    if target is None or (value.get("id"), value.get("url")) != (target["id"], target["url"]):
        raise ValueError(f"Result is outside this campaign or has wrong ID/URL: {value.get('row_index')}")
    if not isinstance(value.get("text"), str) or type(value.get("success")) is not bool:
        raise ValueError("Result must have text and a boolean success flag")
    if value["success"] and not remove_link_targets(value["text"]).strip():
        raise ValueError("Successful result has no usable text")
    if not value["success"] and (value["text"] or not value.get("error")):
        raise ValueError("Failed result must have empty text and an error")
    for name in ("next_retry_at", "source_retry_at", "source_interval_seconds"):
        number = float(value.get(name, 0))
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    attempt = value.get("campaign_attempt", 1)
    if type(attempt) is not int or attempt < 0:
        raise ValueError("campaign_attempt must be a nonnegative integer")
    return target


def ingest_record(database: sqlite3.Connection, value: dict[str, object], offset: int) -> None:
    """Replay committed journal rows idempotently, retaining every good success."""
    target = validate_result(database, value)
    rounds = max(target["rounds"], int(value.get("campaign_attempt", 1)))
    if value["success"]:
        database.execute("UPDATE targets SET state='success', rounds=?, next_retry_at=0, last_error='', success_offset=? WHERE row_index=?",
                         (rounds, offset, target["row_index"]))
    elif target["state"] != "success":
        kind = value.get("error_kind", "transport")
        state = "permanent_failure" if kind in {"not_found", "invalid_url", "robots_denied", "unsupported_content"} else (
            "deferred" if kind in {"rate_limited", "access_denied", "challenge", "deferred"} else "retryable")
        database.execute("UPDATE targets SET state=?, rounds=?, next_retry_at=?, last_error=? WHERE row_index=?",
                         (state, rounds, float(value.get("next_retry_at", time() + 60)),
                          str(value["error"]), target["row_index"]))
    source_retry = float(value.get("source_retry_at", 0))
    if source_retry > 0:
        database.execute("UPDATE origins SET next_retry_at=MAX(next_retry_at,?), interval_seconds=MAX(interval_seconds,?) WHERE group_key=?",
                         (source_retry, float(value.get("source_interval_seconds", 0)), target["group_key"]))


def reconcile(database: sqlite3.Connection, campaign: Path) -> None:
    """Recover after append-before-commit or cancellation without losing success."""
    journal = campaign / "results.jsonl"
    if journal.exists():
        load_completed_ids(journal, repair_tail=True)
        with journal.open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                ingest_record(database, json.loads(line), offset)
    database.execute("UPDATE targets SET state='pending' WHERE state='running'")
    database.commit()


def campaign_report(database: sqlite3.Connection, campaign: Path | None = None, max_rounds: int = 3) -> dict[str, object]:
    """Report document coverage separately from job completion."""
    counts = dict(database.execute("SELECT state,COUNT(*) FROM targets GROUP BY state").fetchall())
    hosts = [dict(row) for row in database.execute(
        "SELECT host,group_key,COUNT(*) AS targets,SUM(state='success') AS success,"
        "SUM(state='permanent_failure') AS permanent_failure,MIN(CASE WHEN state!='success' THEN next_retry_at END) AS next_retry_at "
        "FROM targets GROUP BY host,group_key ORDER BY targets DESC")]
    exhausted = database.execute("SELECT COUNT(*) FROM targets WHERE state IN ('retryable','deferred') AND rounds>=?", (max_rounds,)).fetchone()[0]
    result = {"counts": counts, "remaining": sum(count for state, count in counts.items() if state != "success"),
              "retry_budget_exhausted": exhausted, "max_rounds": max_rounds, "hosts": hosts}
    if campaign is not None and (campaign / "attempts.jsonl").exists():
        metrics = {}
        with (campaign / "attempts.jsonl").open("rb") as handle:
            for line in handle:
                if not line.endswith(b"\n"):
                    break
                attempt = json.loads(line)
                host = hostname(attempt["request_url"])
                values = metrics.setdefault(host, {"attempts": 0, "errors": Counter(), "modes": Counter(), "latencies": deque(maxlen=500)})
                values["attempts"] += 1
                values["errors"][attempt["error_kind"]] += 1
                values["modes"][attempt["mode"]] += 1
                values["latencies"].append(float(attempt["elapsed_seconds"]))
        result["request_metrics"] = {}
        for host, values in metrics.items():
            latencies = sorted(values.pop("latencies"))
            values["p50_last500_seconds"] = latencies[math.ceil(len(latencies) * 0.5) - 1]
            values["p95_last500_seconds"] = latencies[math.ceil(len(latencies) * 0.95) - 1]
            result["request_metrics"][host] = values
    return result


def ingest_files(campaign: Path, database: sqlite3.Connection, manifest: dict[str, object], inputs: list[Path]) -> int:
    """Union explicitly supplied new delta files; importing a file twice is harmless."""
    journal_path = campaign / "results.jsonl"
    count = 0
    for path in inputs:
        if path.resolve() == journal_path.resolve():
            raise ValueError("Cannot ingest the journal into itself")
        info = fingerprint(path)
        if database.execute("SELECT 1 FROM receipts WHERE sha256=?", (info["sha256"],)).fetchone():
            continue
        # Snapshot validated records before appending: a changed external file
        # must never leave unvalidated records in the recoverable journal.
        with TemporaryDirectory(prefix="ingest-", dir=campaign) as directory:
            snapshot = Path(directory) / "validated.jsonl"
            digest = hashlib.sha256()
            with path.open("rb") as handle, snapshot.open("wb") as writer:
                for line in handle:
                    digest.update(line)
                    value = json.loads(line)
                    validate_result(database, value)
                    if value.get("campaign_id", manifest["campaign_id"]) != manifest["campaign_id"]:
                        raise ValueError("Delta belongs to a different campaign")
                    value["campaign_id"] = manifest["campaign_id"]
                    writer.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
                if digest.hexdigest() != info["sha256"]:
                    raise ValueError("Delta changed during validation")
            with snapshot.open("rb") as handle, journal_path.open("ab") as journal:
                for line in handle:
                    value = json.loads(line)
                    offset = journal.tell()
                    journal.write(line)
                    journal.flush()
                    ingest_record(database, value, offset)
                    count += 1
                journal.flush()
                os.fsync(journal.fileno())
        database.execute("INSERT INTO receipts VALUES(?,?)", (info["sha256"], info["path"]))
        database.commit()
    return count


async def run_campaign(args: argparse.Namespace, database: sqlite3.Connection, manifest: dict[str, object]) -> None:
    """Schedule independent ready origins without sleeping in a task-fill loop."""
    # Import only for run: prepare/report/merge need no browser dependencies.
    from crawl4ai import AsyncWebCrawler, BrowserConfig
    from http_strategy import create_http_strategy
    from fetch import crawl_one, is_browser_disconnected
    from site_configs import build_run_configs
    import psutil

    controller = FetchController({host: HostPolicy(**value) for host, value in manifest["policies"].items()})
    database.execute("CREATE INDEX IF NOT EXISTS targets_schedule ON targets(group_key,state,rounds,row_index)")
    database.execute("CREATE INDEX IF NOT EXISTS targets_host_schedule ON targets(host,state,rounds,row_index)")
    rows = database.execute("SELECT group_key,host,MIN(url) AS url,MIN(row_index) AS first_row "
                            "FROM targets GROUP BY group_key,host ORDER BY first_row").fetchall()
    urls = {row["group_key"]: row["url"] for row in rows}
    host_queues = {group: deque(row["host"] for row in rows if row["group_key"] == group) for group in urls}
    groups = sorted(urls)
    selected_hosts = getattr(args, "host", [])
    if selected_hosts:
        known_hosts = {row["host"] for row in rows}
        if set(selected_hosts) - known_hosts:
            raise ValueError(f"Unknown hosts: {sorted(set(selected_hosts) - known_hosts)}")
        host_queues = {group: deque(host for host in queue if host in selected_hosts)
                       for group, queue in host_queues.items()}
        groups = [group for group in groups if host_queues[group]]
    if args.group:
        unknown = set(args.group) - set(groups)
        if unknown:
            raise ValueError(f"Unknown source groups: {sorted(unknown)}")
        groups = [group for group in groups if group in args.group]
    if not groups:
        raise ValueError("No source groups match the requested host/group filters")
    if args.pilot_per_host:
        database.execute("CREATE TEMP TABLE pilot_targets(row_index INTEGER PRIMARY KEY)")
        database.execute("INSERT INTO pilot_targets SELECT MIN(row_index) FROM "
                         "(SELECT row_index,host,NTILE(?) OVER(PARTITION BY host ORDER BY row_index) AS bucket FROM targets) "
                         "GROUP BY host,bucket", (args.pilot_per_host,))
    pilot_clause = " AND row_index IN (SELECT row_index FROM pilot_targets)" if args.pilot_per_host else ""
    for origin in database.execute("SELECT * FROM origins"):
        state, policy = controller.state(urls[origin["group_key"]])
        state.cooldown_until = monotonic() + max(0, origin["next_retry_at"] - time())
        state.interval = max(policy.interval_seconds, origin["interval_seconds"])
    ready_groups = deque(groups)
    group_active = Counter()
    host_active = Counter()
    active = {}
    attempted = browser_count = browser_restarts = 0
    restart_requested = False
    initial_success = database.execute("SELECT COUNT(*) FROM targets WHERE state='success'").fetchone()[0]
    started = last_progress = monotonic()
    run_config, domain_configs = build_run_configs()
    http_semaphore = asyncio.Semaphore(args.http_concurrency)
    browser_semaphore = asyncio.Semaphore(args.browser_concurrency)
    browser_stack = AsyncExitStack()
    browser = None
    http = None
    async with AsyncExitStack() as stack:
        # Keep origin ownership for the full run; separate campaigns cannot double local load.
        HOST_LOCK_DIRECTORY.mkdir(parents=True, exist_ok=True)
        for group in groups:
            path = HOST_LOCK_DIRECTORY / (hashlib.sha256(group.encode()).hexdigest() + ".lock")
            handle = stack.enter_context(path.open("a", encoding="utf-8"))
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(f"Another local worker owns origin {group}") from error
        journal = stack.enter_context((args.campaign / "results.jsonl").open("ab"))
        attempts = stack.enter_context((args.campaign / "attempts.jsonl").open("a", encoding="utf-8", buffering=1))
        controller.attempt_sink = lambda value: attempts.write(json.dumps(value, ensure_ascii=False) + "\n")
        token = active_controller.set(controller)
        stack.callback(active_controller.reset, token)
        if args.fetch_mode != "browser":
            http = await stack.enter_async_context(AsyncWebCrawler(crawler_strategy=create_http_strategy(),
                                                                   base_directory=str(args.campaign / "runtime")))
        try:
            if args.fetch_mode != "http":
                browser = await browser_stack.enter_async_context(AsyncWebCrawler(config=BrowserConfig(headless=True, text_mode=True, verbose=False),
                                                                                 base_directory=str(args.campaign / "runtime")))
            while True:
                memory_low = args.min_free_memory_gb > 0 and psutil.virtual_memory().available < args.min_free_memory_gb * 1024**3
                recycle = browser is not None and (browser_count >= args.browser_recycle_after or memory_low)
                if recycle and not active:
                    await browser_stack.aclose()
                    if memory_low:
                        print("[Backfill] Paused: insufficient free RAM; resume after freeing memory", flush=True)
                        break
                    if restart_requested:
                        browser_restarts += 1
                        if browser_restarts > 3:
                            raise RuntimeError("Browser disconnected repeatedly; campaign remains resumable")
                    browser = await browser_stack.enter_async_context(AsyncWebCrawler(config=BrowserConfig(headless=True, text_mode=True, verbose=False),
                                                                                     base_directory=str(args.campaign / "runtime")))
                    browser_count = 0
                    restart_requested = False
                    recycle = False
                while not recycle and len(active) < args.max_in_flight and not (args.limit and attempted >= args.limit):
                    dispatched = False
                    for _ in range(len(ready_groups)):
                        if len(active) >= args.max_in_flight or (args.limit and attempted >= args.limit):
                            break
                        group = ready_groups.popleft()
                        ready_groups.append(group)
                        state, policy = controller.state(urls[group])
                        if group_active[group] >= policy.concurrency or state.cooldown_until > monotonic():
                            continue
                        row = None
                        for _host in range(len(host_queues[group])):
                            host = host_queues[group].popleft()
                            host_queues[group].append(host)
                            if host_active[host] >= (1 if policy.group else policy.concurrency):
                                continue
                            for status in ("pending", "retryable", "deferred"):
                                row = database.execute(
                                    "SELECT * FROM targets WHERE host=? AND state=? AND rounds<? AND next_retry_at<=?"
                                    + pilot_clause + " ORDER BY rounds,row_index LIMIT 1",
                                    (host, status, args.max_rounds, time()),
                                ).fetchone()
                                if row is not None:
                                    break
                            if row is not None:
                                break
                        if row is None:
                            continue
                        database.execute("UPDATE targets SET state='running' WHERE row_index=?", (row["row_index"],))
                        database.commit()
                        record = SourceRecord(row["row_index"], row["id"], row["url"])
                        task = asyncio.create_task(crawl_one(record, browser, http, browser_semaphore, http_semaphore,
                                                             run_config, domain_configs, args.fetch_mode))
                        active[task] = row
                        group_active[group] += 1
                        host_active[row["host"]] += 1
                        attempted += 1
                        dispatched = True
                    if not dispatched:
                        break
                if not active:
                    if args.wait_for_retries and not (args.limit and attempted >= args.limit):
                        placeholders = ",".join("?" for _ in groups)
                        next_row = database.execute(
                            "SELECT MIN(MAX(t.next_retry_at,o.next_retry_at)) FROM targets t JOIN origins o USING(group_key) "
                            f"WHERE group_key IN ({placeholders}) AND state IN ('pending','retryable','deferred') AND rounds<?"
                            + pilot_clause,
                            (*groups, args.max_rounds),
                        ).fetchone()
                        if next_row[0] is not None:
                            await asyncio.sleep(min(30.0, max(0.1, next_row[0] - time())))
                            continue
                    break
                done, _ = await asyncio.wait(active, timeout=1.0, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    row = active.pop(task)
                    group_active[row["group_key"]] -= 1
                    host_active[row["host"]] -= 1
                    outcome = task.result()
                    value = outcome.payload
                    if value.get("error_kind") == "configuration_error":
                        raise RuntimeError(f"Fetcher configuration error: {value.get('error')}")
                    if is_browser_disconnected(str(value.get("error", ""))):
                        restart_requested = True
                        browser_count = args.browser_recycle_after
                        database.execute("UPDATE targets SET state='pending' WHERE row_index=?", (row["row_index"],))
                        continue
                    if value.get("success") and outcome.mode == "browser":
                        browser_restarts = 0
                    value.update(campaign_id=manifest["campaign_id"],
                                 campaign_attempt=row["rounds"] + int(outcome.attempts > 0), completed_at=time())
                    offset = journal.tell()
                    journal.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
                    journal.flush()
                    os.fsync(journal.fileno())
                    ingest_record(database, value, offset)
                    browser_count += int(outcome.mode == "browser")
                database.commit()
                now = monotonic()
                if now - last_progress >= 30:
                    counts = dict(database.execute("SELECT state,COUNT(*) FROM targets GROUP BY state"))
                    print(f"[Backfill] attempted={attempted} in_flight={len(active)} states={counts}", flush=True)
                    last_progress = now
        finally:
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            database.execute("UPDATE targets SET state='pending' WHERE state='running'")
            database.commit()
            await browser_stack.aclose()
    elapsed = monotonic() - started
    new_success = database.execute("SELECT COUNT(*) FROM targets WHERE state='success'").fetchone()[0] - initial_success
    print(f"[Backfill] Finished this pass: attempted={attempted} new_success={new_success} "
          f"success_per_hour={new_success * 3600 / max(elapsed, 0.001):.1f} wall_seconds={elapsed:.1f}", flush=True)


def merge_campaign(campaign: Path, database: sqlite3.Connection, manifest: dict[str, object], output: Path) -> dict[str, object]:
    """Publish the baseline plus all validated sparse successes without replacing inputs."""
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    baseline = Path(manifest["baseline"]["path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    delta_rows = iter(database.execute("SELECT * FROM targets WHERE state='success' ORDER BY row_index"))
    next_delta = next(delta_rows, None)
    digest = hashlib.sha256()
    count = added = 0
    with TemporaryDirectory(prefix="backfill-merge-", dir=output.parent) as directory:
        temporary = Path(directory) / "corpus.jsonl"
        journal_path = campaign / "results.jsonl"
        with baseline.open("rb") as source, temporary.open("wb") as writer, ExitStack() as stack:
            journal = stack.enter_context(journal_path.open("rb")) if next_delta is not None else None

            def write_delta(row: sqlite3.Row) -> None:
                nonlocal count, added
                journal.seek(row["success_offset"])
                value = json.loads(journal.readline())
                if (value.get("row_index"), value.get("id"), value.get("url")) != (row["row_index"], row["id"], row["url"]) or value.get("success") is not True:
                    raise ValueError("Journal success offset is inconsistent")
                value["text"] = remove_link_targets(value["text"])
                if not value["text"].strip():
                    raise ValueError("Delta contains empty successful text")
                writer.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
                count += 1
                added += 1

            for line in source:
                digest.update(line)
                value = json.loads(line)
                while next_delta is not None and next_delta["row_index"] < value["row_index"]:
                    write_delta(next_delta)
                    next_delta = next(delta_rows, None)
                if next_delta is not None and next_delta["row_index"] == value["row_index"]:
                    raise ValueError("A target overlaps the baseline")
                writer.write(line if line.endswith(b"\n") else line + b"\n")
                count += 1
            while next_delta is not None:
                write_delta(next_delta)
                next_delta = next(delta_rows, None)
            if digest.hexdigest() != manifest["baseline"]["sha256"]:
                raise ValueError("Baseline content changed; refusing to publish")
            writer.flush()
            os.fsync(writer.fileno())
        os.link(temporary, output)
    return {"output": str(output), "rows": count, "new_successes": added,
            "coverage": campaign_report(database, campaign)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    preparation.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    preparation.add_argument("--campaign", type=Path, required=True)
    preparation.add_argument("--min-gap", type=int, default=1001)
    preparation.add_argument("--max-index", type=int)
    preparation.add_argument("--policy-file", type=Path)
    runner = commands.add_parser("run")
    runner.add_argument("--campaign", type=Path, required=True)
    runner.add_argument("--fetch-mode", choices=("auto", "http", "browser"), default="auto")
    runner.add_argument("--group", action="append", default=[])
    runner.add_argument("--host", action="append", default=[], help="Exact normalized host from report; shared group quota still applies")
    runner.add_argument("--max-in-flight", type=int, default=16)
    runner.add_argument("--http-concurrency", type=int, default=8)
    runner.add_argument("--browser-concurrency", type=int, default=2)
    runner.add_argument("--browser-recycle-after", type=int, default=300)
    runner.add_argument("--min-free-memory-gb", type=float, default=2.0)
    runner.add_argument("--max-rounds", type=int, default=3)
    runner.add_argument("--limit", type=int, default=0)
    runner.add_argument("--pilot-per-host", type=int, default=0)
    runner.add_argument("--wait-for-retries", action="store_true", help="Wait for scheduled retries; default returns at cooldown")
    report = commands.add_parser("report")
    report.add_argument("--campaign", type=Path, required=True)
    ingestion = commands.add_parser("ingest")
    ingestion.add_argument("--campaign", type=Path, required=True)
    ingestion.add_argument("--input", type=Path, nargs="+", required=True, help="New delta files for this manifest")
    merger = commands.add_parser("merge")
    merger.add_argument("--campaign", type=Path, required=True)
    merger.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            manifest = prepare(args.source, args.baseline, args.campaign, args.min_gap, args.max_index, args.policy_file)
            print(json.dumps({key: value for key, value in manifest.items() if key != "policies"}, indent=2))
            return
        if args.command == "run" and (min(args.max_in_flight, args.http_concurrency, args.browser_concurrency, args.browser_recycle_after, args.max_rounds) < 1 or min(args.limit, args.pilot_per_host, args.min_free_memory_gb) < 0):
            parser.error("Concurrency, recycle and rounds must be positive; limits and memory must be nonnegative")
        manifest = read_manifest(args.campaign)
        verify_inputs(manifest)
        with campaign_lock(args.campaign), connect(args.campaign) as database:
            reconcile(database, args.campaign)
            if args.command == "run":
                asyncio.run(run_campaign(args, database, manifest))
                report = campaign_report(database, args.campaign, args.max_rounds)
                print(json.dumps(report, indent=2))
                if report["remaining"] and not (args.limit or args.pilot_per_host or args.group or args.host):
                    parser.exit(3, f"{report['remaining']} targets remain; inspect cooldowns and retry budgets\n")
            elif args.command == "merge":
                print(json.dumps(merge_campaign(args.campaign, database, manifest, args.output), indent=2))
            elif args.command == "ingest":
                print(json.dumps({"ingested": ingest_files(args.campaign, database, manifest, args.input),
                                  "coverage": campaign_report(database, args.campaign)}, indent=2))
            else:
                print(json.dumps(campaign_report(database, args.campaign), indent=2))
    except (ValueError, OSError, RuntimeError, ModuleNotFoundError) as error:
        parser.exit(2, f"{type(error).__name__}: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Interrupted; resume the same campaign with run\n")


if __name__ == "__main__":
    main()
