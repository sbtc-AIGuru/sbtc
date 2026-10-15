"""Shared file contracts and deterministic identities for the data pipeline."""

from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import unicodedata


PIPELINE_VERSION = "1.0.0"


def normalize_text(text: str) -> str:
    """Normalize only for matching; preserve original passages in exports."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def text_hash(text: str) -> str:
    """Return a stable hash without exposing text in identifiers."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Read JSONL strictly and report the failing line."""
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at {path}:{number}") from error
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{number}")
            yield value


def write_json(path: Path, value: Any) -> None:
    """Atomically update an artifact owned by the pipeline."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: Any) -> int:
    temporary = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    temporary.replace(path)
    return count


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    positive_integer_fields = (
        "documents_per_source", "max_corpus_chunks", "query_passages",
        "max_query_passages_per_document", "questions_per_passage",
        "max_passage_tokens", "max_query_tokens", "generation_batch_size",
        "generation_max_new_tokens", "generation_max_input_tokens", "judge_batch_size",
        "encoding_batch_size", "reranking_batch_size", "retrieval_candidates",
        "rerank_candidates", "negative_judge_candidates", "negative_count", "workers",
    )
    for name in positive_integer_fields:
        if not isinstance(config[name], int) or isinstance(config[name], bool) or config[name] <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not 0 < config["validation_fraction"] + config["test_fraction"] < 1:
        raise ValueError("Validation/test fractions must leave training documents")
    if any(config[name] < 0 for name in ("validation_fraction", "test_fraction")):
        raise ValueError("Split fractions must be nonnegative")
    weights = config["query_language_weights"]
    if set(weights) != {"vi", "zh"} or any(value <= 0 for value in weights.values()):
        raise ValueError("Positive vi/zh query-language weights are required")
    if not math.isclose(sum(weights.values()), 1.0):
        raise ValueError("Query-language weights must sum to one")
    if not 0 <= config["vietnamese_queries_for_chinese"] <= 1:
        raise ValueError("Cross-language query fraction must be in [0, 1]")
    if config["negative_judge_candidates"] < config["negative_count"]:
        raise ValueError("The judge candidate count must cover the negative count")
    for name in ("minimum_positive_probability", "maximum_negative_probability"):
        if not 0 < config[name] < 1:
            raise ValueError(f"{name} must be in (0, 1)")
    return config


def load_manifest(work: Path) -> dict[str, Any]:
    return json.loads((work / "manifest.json").read_text(encoding="utf-8"))


def record_stage(work: Path, stage: str, report: dict[str, Any]) -> None:
    manifest = load_manifest(work)
    manifest.setdefault("stages", {})[stage] = report
    write_json(work / "manifest.json", manifest)


def parse_model_json(content: str) -> dict[str, Any]:
    """Accept a JSON object with optional surrounding model formatting."""
    decoder = json.JSONDecoder()
    for offset, character in enumerate(content):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(content[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Model response did not contain a JSON object")


def unique_rows(paths: list[Path], key: str) -> dict[str, dict[str, Any]]:
    result = {}
    for path in sorted(paths):
        for row in read_jsonl(path):
            identity = str(row[key])
            if identity in result and result[identity] != row:
                raise ValueError(f"Conflicting checkpoint record: {identity}")
            result[identity] = row
    return result
