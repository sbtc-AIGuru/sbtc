"""Clean children[*].chunk_text in a JSONL file or JSON array, in batches."""

import argparse
from collections.abc import Iterator
from itertools import islice
import json
import os
from pathlib import Path
import stat
import tempfile
from time import monotonic
from typing import TextIO

if __package__:
    from .data_preprocess import ETL
else:
    from data_preprocess import ETL


def iter_documents(source: TextIO, is_array: bool) -> Iterator[dict]:
    """Stream documents without loading the whole file, including pretty JSON."""
    if not is_array:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at line {line_number}") from error
            if not isinstance(document, dict):
                raise ValueError(f"Expected a document object at line {line_number}")
            yield document
        return

    decoder = json.JSONDecoder()
    buffer = ""
    eof = False

    def fill_buffer() -> None:
        nonlocal buffer, eof
        block = source.read(1024 * 1024)
        eof = not block
        buffer += block

    def next_character() -> str:
        nonlocal buffer
        buffer = buffer.lstrip()
        while not buffer and not eof:
            fill_buffer()
            buffer = buffer.lstrip()
        return buffer[:1]

    if next_character() != "[":
        raise ValueError("Expected a JSON array")
    buffer = buffer[1:]
    if next_character() != "]":
        while True:
            while True:
                try:
                    document, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise
                    fill_buffer()
            if not isinstance(document, dict):
                raise ValueError("Expected a document object in the JSON array")
            buffer = buffer[end:]
            yield document
            separator = next_character()
            if separator == "]":
                break
            if separator != ",":
                raise ValueError("Expected ',' or ']' after a document")
            buffer = buffer[1:]
            next_character()
    buffer = buffer[1:]
    if next_character():
        raise ValueError("Unexpected content after the JSON array")


def run_etl(path: Path, batch_size: int = 100) -> tuple[int, int, int]:
    """Replace the input only after every batch has been written successfully.

    Only chunk_text changes. Offsets and hashes still describe the source text.
    The temporary output needs free disk space comparable to the input size.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    path = path.resolve(strict=True)
    etl = ETL()
    documents_count = chunks_count = changed_count = 0
    started = monotonic()

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".etl.tmp", delete=False,
    ) as output:
        temporary_path = Path(output.name)
        try:
            with path.open(encoding="utf-8-sig") as source:
                first_character = source.read(1)
                while first_character and first_character.isspace():
                    first_character = source.read(1)
                is_array = first_character == "["
                source.seek(0)
                documents = iter_documents(source, is_array)
                if is_array:
                    output.write("[\n")
                while batch := list(islice(documents, batch_size)):
                    lines = []
                    for document in batch:
                        for child in document.get("children", []):
                            original = child["chunk_text"]
                            cleaned = etl.ETL_Pipeline(original)
                            child["chunk_text"] = cleaned
                            chunks_count += 1
                            changed_count += cleaned != original
                        lines.append(json.dumps(
                            document, ensure_ascii=False, separators=(",", ":"),
                            allow_nan=False,
                        ))
                    if is_array:
                        if documents_count:
                            output.write(",\n")
                        output.write(",\n".join(lines))
                    else:
                        output.write("\n".join(lines) + "\n")
                    documents_count += len(batch)
                    output.flush()
                    print(
                        f"Documents={documents_count:,}; chunks={chunks_count:,}; "
                        f"changed={changed_count:,}; elapsed={monotonic() - started:.1f}s",
                        flush=True,
                    )
                if is_array:
                    output.write("\n]\n")
            output.flush()
            os.fsync(output.fileno())
            os.chmod(temporary_path, stat.S_IMODE(path.stat().st_mode))
            output.close()
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return documents_count, chunks_count, changed_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-path", type=Path,
        default=Path(__file__).resolve().parents[2] / "datav2" / "merged.jsonl",
        help="JSONL file or JSON array to update in place",
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Documents per batch")
    args = parser.parse_args()
    if not args.data_path.is_file():
        parser.error(f"File not found: {args.data_path}")
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    documents, chunks, changed = run_etl(args.data_path, args.batch_size)
    print(f"Complete: documents={documents:,}; chunks={chunks:,}; changed={changed:,}")


if __name__ == "__main__":
    main()
