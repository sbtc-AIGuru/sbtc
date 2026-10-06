"""Merge verified crawl ranges while allowing explicitly skipped source rows."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import heapq
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

from utils import get_row_count, load_url_range


def read_record(
    handle: BinaryIO, path: Path, previous_row: int,
) -> tuple[int, bytes, dict[str, object]] | None:
    """Read one JSONL record and enforce ascending row order per input."""
    line = handle.readline()
    if not line:
        return None
    try:
        value = json.loads(line)
        row = value["row_index"]
        if not isinstance(row, int) or row <= previous_row:
            raise ValueError(f"Rows are not strictly increasing after {previous_row}")
        if not isinstance(value.get("success"), bool):
            raise ValueError("Missing or invalid success flag")
        text = value.get("text")
        if not isinstance(text, str):
            raise ValueError("Missing or invalid text")
        if value["success"] and not text.strip():
            raise ValueError("Successful record has empty text")
        if not value["success"] and (text or not value.get("error")):
            raise ValueError("Failed record has text or lacks an error")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid record in {path} after row {previous_row}: {error}") from error
    return row, line if line.endswith(b"\n") else line + b"\n", value


def merge_corpus(
    source: Path,
    inputs: list[Path],
    output: Path,
    end_row: int,
    target_id: int,
    allowed_missing: list[tuple[int, int]],
) -> dict[str, object]:
    """Write a new sorted corpus only when all required Parquet rows are present."""
    if output.exists():
        raise FileExistsError(f"Refusing to replace existing output: {output}")
    if not inputs or len({path.resolve() for path in inputs}) != len(inputs):
        raise ValueError("Inputs must be a nonempty list of distinct files")
    if output.resolve() in {path.resolve() for path in inputs}:
        raise ValueError("Output must differ from every input")
    if end_row < 0 or end_row >= get_row_count(source):
        raise ValueError("End row is outside the source Parquet")
    for start, end in allowed_missing:
        if not 0 <= start <= end <= end_row:
            raise ValueError(f"Invalid allowed-missing range: {start}:{end}")

    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = success = failed = omitted = 0
    last_id = None
    with ExitStack() as stack, TemporaryDirectory(
        prefix="crawl-final-", dir=output.parent
    ) as directory:
        handles = [stack.enter_context(path.open("rb")) for path in inputs]
        previous = [-1] * len(inputs)
        heap: list[tuple[int, int, bytes, dict[str, object]]] = []

        def advance(index: int) -> None:
            item = read_record(handles[index], inputs[index], previous[index])
            if item is not None:
                row, line, value = item
                previous[index] = row
                heapq.heappush(heap, (row, index, line, value))

        for index in range(len(inputs)):
            advance(index)

        temporary = Path(directory) / output.name
        with temporary.open("wb") as writer:
            for batch in load_url_range(source, 0, end_row, 8192):
                for original in batch:
                    if heap and heap[0][0] < original.row_index:
                        raise ValueError(f"Duplicate or unexpected row {heap[0][0]}")
                    if not heap or heap[0][0] != original.row_index:
                        if any(start <= original.row_index <= end for start, end in allowed_missing):
                            omitted += 1
                            continue
                        raise ValueError(f"Missing required Parquet row {original.row_index}")
                    row, index, line, value = heapq.heappop(heap)
                    if value.get("id") != original.id or value.get("url") != original.url:
                        raise ValueError(f"ID/URL mismatch at Parquet row {row}")
                    writer.write(line)
                    digest.update(line)
                    written += 1
                    success += bool(value["success"])
                    failed += not value["success"]
                    last_id = original.id
                    advance(index)
            if heap:
                raise ValueError(f"Input contains a row beyond the target: {heap[0][0]}")
            writer.flush()
            os.fsync(writer.fileno())
        if last_id != target_id:
            raise ValueError(f"Target ID mismatch at row {end_row}: {last_id} != {target_id}")

        manifest: dict[str, object] = {
            "source": str(source.resolve()),
            "inputs": [str(path.resolve()) for path in inputs],
            "output": str(output.resolve()),
            "end_row": end_row,
            "target_id": target_id,
            "rows": written,
            "success": success,
            "failed": failed,
            "allowed_missing": [list(item) for item in allowed_missing],
            "omitted": omitted,
            "sha256": digest.hexdigest(),
            "bytes": temporary.stat().st_size,
        }
        manifest_path = output.with_suffix(".manifest.json")
        if manifest_path.exists():
            raise FileExistsError(f"Refusing to replace existing manifest: {manifest_path}")
        temporary.replace(output)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/links_corpus.parquet"))
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-row", type=int, required=True)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--allow-missing", action="append", default=[], metavar="START:END")
    args = parser.parse_args()
    try:
        allowed_missing = [tuple(map(int, item.split(":"))) for item in args.allow_missing]
        if any(len(item) != 2 for item in allowed_missing):
            raise ValueError("Allowed-missing ranges must be START:END")
        manifest = merge_corpus(
            args.source, args.input, args.output, args.end_row,
            args.target_id, allowed_missing,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
