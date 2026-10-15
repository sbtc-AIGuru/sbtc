"""Write one validated JSONL result per Parquet row from an append-only crawl log."""

from __future__ import annotations

import argparse
from contextlib import closing
from itertools import chain
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from utils import SourceRecord, get_row_count, load_url_range
from verbatim import remove_link_targets


def source_rows(source: Path, start: int, end: int):
    """Stream the inclusive source range without materializing article text."""
    return chain.from_iterable(load_url_range(source, start, end, 5_000))


def create_index(database: sqlite3.Connection, source: Path, start: int, end: int) -> None:
    """Keep source mapping and selected JSONL byte offsets on disk."""
    database.execute(
        "CREATE TABLE source (row_index INTEGER PRIMARY KEY, id INTEGER NOT NULL, url TEXT NOT NULL)"
    )
    database.execute("CREATE INDEX source_id_url ON source (id, url)")
    database.execute(
        "CREATE TABLE best (row_index INTEGER PRIMARY KEY, offset INTEGER NOT NULL, success INTEGER NOT NULL)"
    )
    database.executemany(
        "INSERT INTO source VALUES (?, ?, ?)",
        ((record.row_index, record.id, record.url) for record in source_rows(source, start, end)),
    )
    database.commit()


def find_row_index(database: sqlite3.Connection, value: dict[str, object]) -> int | None:
    """Resolve legacy lines lacking row_index only when ID and URL are unambiguous."""
    record_id = int(value["id"])
    url = str(value["url"])
    if "row_index" in value:
        row_index = int(value["row_index"])
        original = database.execute(
            "SELECT id, url FROM source WHERE row_index = ?", (row_index,)
        ).fetchone()
        if original is None:
            return None
        if original != (record_id, url):
            raise ValueError(f"ID/URL mismatch at Parquet row {row_index}")
        return row_index
    rows = database.execute(
        "SELECT row_index FROM source WHERE id = ? AND url = ? LIMIT 2", (record_id, url)
    ).fetchall()
    if len(rows) == 0:
        return None
    if len(rows) != 1:
        raise ValueError(f"Legacy result has missing or ambiguous ID/URL: {record_id}")
    return int(rows[0][0])


def index_results(database: sqlite3.Connection, raw: Path) -> int:
    """Choose the latest success, or the latest failure if none succeeded."""
    lines = 0
    with raw.open("rb") as handle:
        while line := handle.readline():
            lines += 1
            offset = handle.tell() - len(line)
            try:
                value = json.loads(line.decode("utf-8"))
                if not isinstance(value, dict) or not isinstance(value.get("text"), str):
                    raise ValueError("Missing text field")
                if "success" in value and not isinstance(value["success"], bool):
                    raise ValueError("Invalid success flag")
                if value.get("success", True) and not value["text"].strip():
                    raise ValueError("Empty successful record")
                if value.get("success") is False and (value["text"] or not value.get("error")):
                    raise ValueError("Invalid failure record")
                row_index = find_row_index(database, value)
                success = int(value.get("success", True) is not False and bool(remove_link_targets(value["text"]).strip()))
                if value.get("success") is False and value["text"]:
                    raise ValueError("Failure has nonempty text")
                database.execute(
                    "INSERT INTO best VALUES (?, ?, ?) "
                    "ON CONFLICT(row_index) DO UPDATE SET "
                    "offset = excluded.offset, success = excluded.success "
                    "WHERE excluded.success >= best.success",
                    (row_index, offset, success),
                )
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid crawl result at {raw}:{lines}: {error}") from error
            if lines % 10_000 == 0:
                database.commit()
    database.commit()
    return lines


def write_canonical(
    database: sqlite3.Connection, raw: Path, source: Path, start: int, end: int,
    output: Path,
) -> tuple[int, int]:
    """Emit rows in Parquet order with bounded memory and exact ID/URL checks."""
    success = failed = 0
    with raw.open("rb") as input_handle, output.open("w", encoding="utf-8") as writer:
        for record in source_rows(source, start, end):
            assert isinstance(record, SourceRecord)
            indexed = database.execute(
                "SELECT offset, success FROM best WHERE row_index = ?", (record.row_index,)
            ).fetchone()
            if indexed is None:
                raise ValueError(f"Missing crawl result for Parquet row {record.row_index}")
            input_handle.seek(indexed[0])
            value = json.loads(input_handle.readline().decode("utf-8"))
            if value["id"] != record.id or value["url"] != record.url:
                raise ValueError(f"ID/URL mismatch at Parquet row {record.row_index}")
            value["row_index"] = record.row_index
            value["text"] = remove_link_targets(value["text"])
            row_success = bool(indexed[1])
            if row_success and not value["text"].strip():
                value.update(
                    success=False,
                    text="",
                    error="No article text after removing link targets",
                )
                row_success = False
            value["success"] = row_success
            if not row_success:
                value["text"] = ""
                if not value.get("error"):
                    value["error"] = "No article text after removing link targets"
            writer.write(json.dumps(value, ensure_ascii=False) + "\n")
            if row_success:
                success += 1
            else:
                failed += 1
    return success, failed


def compact(source: Path, raw: Path, output: Path, start: int, end: int) -> tuple[int, int, int]:
    """Create a new canonical file without modifying the append-only input."""
    if source.resolve() == output.resolve() or raw.resolve() == output.resolve():
        raise ValueError("Canonical output must differ from source and raw input")
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="crawl-compact-", dir=output.parent) as directory:
        temporary = Path(directory)
        with closing(sqlite3.connect(temporary / "index.sqlite3")) as database, database:
            create_index(database, source, start, end)
            raw_lines = index_results(database, raw)
            success, failed = write_canonical(
                database, raw, source, start, end, temporary / "canonical.jsonl"
            )
        (temporary / "canonical.jsonl").replace(output)
    return raw_lines, success, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--input", type=Path, required=True, help="Append-only JSONL")
    parser.add_argument("--source", type=Path, default=Path("data/links_corpus.parquet"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.start < 0 or args.end < args.start or args.end >= get_row_count(args.source):
        parser.error("require 0 <= --start <= --end < Parquet row count")
    if not args.input.is_file():
        parser.error(f"crawl JSONL not found: {args.input}")
    raw_lines, success, failed = compact(
        args.source, args.input, args.output, args.start, args.end
    )
    print(
        f"Raw lines: {raw_lines}\nCanonical rows: {success + failed}"
        f"\nSuccess: {success}\nFailed: {failed}\nOutput: {args.output}"
    )


if __name__ == "__main__":
    main()
