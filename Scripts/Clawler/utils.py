"""Parquet input and incremental JSONL output for the crawler."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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


def load_completed_ids(output: Path) -> dict[int, str]:
    """Read successful IDs and their original URLs from an existing JSONL file."""
    completed: dict[int, str] = {}
    if not output.exists():
        return completed
    with output.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("success", True) and record.get("text"):
                    completed[int(record["id"])] = str(record["url"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid JSONL record at {output}:{line_number}") from error
    return completed


def save_results(output: Path, results: list[dict[str, object]]) -> None:
    """Append one finished batch as UTF-8 JSONL."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
