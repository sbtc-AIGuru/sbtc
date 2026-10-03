"""Parquet input and incremental JSONL output for the crawler."""

from __future__ import annotations

import json
import fcntl
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, TextIO

import pyarrow.parquet as parquet


@dataclass(frozen=True)
class SourceRecord:
    row_index: int
    id: int
    url: str


def get_row_count(source: Path) -> int:
    """Return the number of Parquet records for CLI range validation."""
    return parquet.ParquetFile(source).metadata.num_rows


def load_url_range(
    source: Path, start: int, end: int, batch_size: int
) -> Iterator[list[SourceRecord]]:
    """Yield inclusive Parquet row ranges without loading the full dataset."""
    parquet_file = parquet.ParquetFile(source)
    columns = set(parquet_file.schema_arrow.names)
    if "url" not in columns:
        raise ValueError("Parquet is missing the inspected 'url' column")
    has_id = "id" in columns
    total_rows = parquet_file.metadata.num_rows
    if end >= total_rows:
        raise ValueError(f"--end must be less than {total_rows} (last index: {total_rows - 1})")

    pending: list[SourceRecord] = []
    group_start = 0
    selected_columns = ["id", "url"] if has_id else ["url"]
    for group_index in range(parquet_file.num_row_groups):
        group_rows = parquet_file.metadata.row_group(group_index).num_rows
        group_end = group_start + group_rows - 1
        if group_end < start:
            group_start += group_rows
            continue
        if group_start > end:
            break

        batch_start = group_start
        for arrow_batch in parquet_file.iter_batches(
            batch_size=batch_size,
            row_groups=[group_index],
            columns=selected_columns,
        ):
            if batch_start > end:
                break
            ids = arrow_batch.column(0).to_pylist() if has_id else None
            urls = arrow_batch.column(1 if has_id else 0).to_pylist()
            for offset, url in enumerate(urls):
                row_index = batch_start + offset
                if row_index < start or row_index > end:
                    continue
                source_id = ids[offset] if ids is not None else None
                pending.append(
                    SourceRecord(
                        row_index=row_index,
                        id=int(source_id) if source_id is not None else row_index,
                        url=url if isinstance(url, str) else "",
                    )
                )
                if len(pending) == batch_size:
                    yield pending
                    pending = []
            batch_start += arrow_batch.num_rows
        group_start += group_rows

    if pending:
        yield pending


def load_completed_ids(output: Path, repair_tail: bool = False) -> dict[int, str]:
    """Read successful IDs and their original URLs from an existing JSONL file."""
    completed: dict[int, str] = {}
    if not output.exists():
        return completed
    with output.open("rb") as handle:
        line_number = 0
        while line := handle.readline():
            line_number += 1
            line_start = handle.tell() - len(line)
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
                if record.get("success", True) and record.get("text"):
                    completed[int(record["id"])] = str(record["url"])
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                if repair_tail and not line.endswith(b"\n") and not handle.read(1):
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
                    backup = output.with_name(f"{output.name}.partial-{timestamp}")
                    backup.write_bytes(line)
                    with output.open("r+b") as writable:
                        writable.truncate(line_start)
                    print(f"[Resume] Preserved incomplete final line at {backup}", flush=True)
                    break
                raise ValueError(f"Invalid JSONL record at {output}:{line_number}") from error
    return completed


def save_results(output: Path, results: list[dict[str, object]]) -> None:
    """Append one finished batch as UTF-8 JSONL."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")


class JsonlWriter:
    """Hold a single writer lock and flush each completed result to JSONL."""

    def __init__(self, output: Path) -> None:
        self.output = output
        self.completed_ids: dict[int, str] = {}
        self._lock: TextIO | None = None
        self._handle: TextIO | None = None

    def __enter__(self) -> JsonlWriter:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.output.with_name(f"{self.output.name}.lock")
        self._lock = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.completed_ids = load_completed_ids(self.output, repair_tail=True)
            self._handle = self.output.open("a", encoding="utf-8", buffering=1)
        except (OSError, ValueError):
            self._lock.close()
            self._lock = None
            raise
        return self

    def write(self, result: dict[str, object]) -> None:
        """Append one complete UTF-8 line without retaining its text in memory."""
        if self._handle is None:
            raise RuntimeError("JSONL writer is not open")
        self._handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is not None:
            self._handle.close()
        if self._lock is not None:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
            self._lock.close()
