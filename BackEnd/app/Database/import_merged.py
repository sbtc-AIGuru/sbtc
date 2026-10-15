"""Stream JSONL or line-oriented JSON arrays into Document and individual Chunk rows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .postgre_db import PostgreManager


def iter_jsonl_documents(path: Path) -> Iterator[dict[str, Any]]:
    """Read one document per nonempty line without loading the complete dataset."""
    with path.open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid document JSON at {path}:{line_number}",
                ) from error
            if not isinstance(record, dict):
                raise ValueError(f"Expected document object at {path}:{line_number}")
            yield record


def iter_merged_documents(path: Path) -> Iterator[dict[str, Any]]:
    """Read JSONL/NDJSON or the original JSON array with one document per line."""
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        yield from iter_jsonl_documents(path)
        return
    with path.open(encoding="utf-8") as source:
        if source.readline().strip() != "[":
            raise ValueError("Expected '[' on the first line of merged.json")
        seen_document = False
        previous_comma = True
        for line_number, line in enumerate(source, start=2):
            raw = line.strip()
            if not raw:
                continue
            if raw == "]":
                if seen_document and previous_comma:
                    raise ValueError("Trailing comma in merged.json")
                if any(line.strip() for line in source):
                    raise ValueError("Unexpected content after merged.json array")
                return
            if not previous_comma:
                raise ValueError(f"Missing separator at line {line_number}")
            previous_comma = raw.endswith(",")
            if previous_comma:
                raw = raw[:-1]
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid document JSON at line {line_number}") from error
            if not isinstance(record, dict):
                raise ValueError(f"Expected document object at line {line_number}")
            seen_document = True
            yield record
        raise ValueError("Missing closing ']' in merged.json")


def import_documents(
    manager: PostgreManager, path: Path, *, batch_documents: int = 100,
    max_batch_chunks: int = 5_000, limit: int | None = None,
) -> tuple[int, int]:
    """Commit complete documents per batch, including skipped/ineligible records."""
    if batch_documents <= 0 or max_batch_chunks <= 0 or (limit is not None and limit <= 0):
        raise ValueError("Batch sizes and limit must be positive")
    batch = []
    batch_chunks = 0
    documents_imported = chunks_imported = 0
    for record in iter_merged_documents(path):
        batch.append(record)
        batch_chunks += len(record.get("children", []))
        reached_limit = limit is not None and documents_imported + len(batch) >= limit
        if len(batch) >= batch_documents or batch_chunks >= max_batch_chunks or reached_limit:
            documents, chunks = manager.add_documents(batch)
            documents_imported += documents
            chunks_imported += chunks
            print(f"Imported documents={documents_imported:,}; chunks={chunks_imported:,}", flush=True)
            batch.clear()
            batch_chunks = 0
        if reached_limit:
            break
    if batch:
        documents, chunks = manager.add_documents(batch)
        documents_imported += documents
        chunks_imported += chunks
    return documents_imported, chunks_imported


def main() -> None:
    """Create the schema and import the requested file using DATABASE_URL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-path", type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "merged.json",
        help="Input .jsonl/.ndjson file or original line-oriented .json array",
    )
    parser.add_argument("--batch-documents", type=int, default=100)
    parser.add_argument("--max-batch-chunks", type=int, default=5_000)
    parser.add_argument("--limit", type=int, help="Import only this many documents")
    args = parser.parse_args()
    if not args.data_path.is_file():
        parser.error(f"Input file not found: {args.data_path}")
    if args.batch_documents <= 0 or args.max_batch_chunks <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error("Batch sizes and limit must be positive")
    manager = PostgreManager()
    try:
        manager.init_db()
        documents, chunks = import_documents(
            manager, args.data_path, batch_documents=args.batch_documents,
            max_batch_chunks=args.max_batch_chunks, limit=args.limit,
        )
        print(f"Complete: documents={documents:,}; chunks={chunks:,}")
    finally:
        manager.close()


if __name__ == "__main__":
    main()
