"""Read-only integrity audit for paragraph chunk output against its input JSONL."""

from __future__ import annotations

import argparse
from itertools import zip_longest
import json
from pathlib import Path
from typing import Iterator

from sbtc.Scripts.Clawler.verbatim import CLEANER_VERSION, clean_with_report
from sbtc.Scripts.Preprocess.chunking import ChunkConfig, classify_document_details, count_units, extract_atoms
from sbtc.Scripts.Preprocess.format_profiles import PROFILE_VERSION, analyse_format
from sbtc.Scripts.Preprocess.chunk_cli import _config_fingerprint, _sha256_file, _format_code_fingerprint


def _format_analysis_issues(source: str, input_record: dict, output: dict, config: ChunkConfig) -> tuple[list[str], dict]:
    """Reconstruct rules from source; never accept submitted atom/protected metadata as evidence."""
    expected = analyse_format(source, input_record["url"])
    issues = []
    for key, value in expected["metadata"].items():
        if output.get(key) != value: issues.append(f"format metadata mismatch: {key}")
    if output.get("version") != PROFILE_VERSION: issues.append("format output version mismatch")
    if output.get("strategy") != "format": issues.append("format strategy mismatch")
    for key in ("title_spans", "heading_spans", "section_spans", "question_spans", "answer_spans", "content_language_spans", "protected_spans"):
        if output.get(key) != expected[key]: issues.append(f"format source spans mismatch: {key}")
    expected_atoms = [dict(start_char=a.start, end_char=a.end, role=a.role, boundary_type=a.boundary_type,
                           section_path=list(a.section_path), language=a.language, region=a.region, unit_count=a.units)
                      for a in expected["atoms"]]
    if output.get("atom_spans") != expected_atoms: issues.append("format atom metadata mismatch")
    expected_exclusions = [dict(s, doc_id=input_record["id"]) for s in expected["excluded_spans"]]
    if output.get("excluded_spans") != expected_exclusions: issues.append("format exclusion evidence mismatch")
    question = None
    if expected["question_spans"]:
        question = dict(start_char=expected["question_spans"][0]["start_char"], end_char=expected["question_spans"][-1]["end_char"])
    parents = {p["parent_id"]: p for p in output.get("parents", [])}
    for order, parent in enumerate(output.get("parents", [])):
        start, end = parent["start_char"], parent["end_char"]
        if parent.get("question_span") != question: issues.append("parent question source span mismatch")
        title = expected["title_spans"][0] if expected["title_spans"] else None
        if parent.get("title_span") != title: issues.append("parent title source span mismatch")
        expected_headings = [span for span in expected["heading_spans"] if start <= span["start_char"] < end]
        if parent.get("heading_spans") != expected_headings: issues.append("parent heading source span mismatch")
        paths = [[s["label"]] for s in expected["section_spans"] if max(start, s["start_char"]) < min(end, s["end_char"])]
        if parent.get("section_paths") != paths: issues.append("parent section paths mismatch")
        if parent.get("unit_count") != count_units(source[start:end]): issues.append("parent unit count mismatch")
        if parent["parent_id"] != f"{input_record['id']}:p:{order}:{start}:{end}:{PROFILE_VERSION}": issues.append("parent ID mismatch")
    for child in output.get("children", []):
        start, end = child["start_char"], child["end_char"]
        if any(s["start_char"] < boundary < s["end_char"]
               for s in expected["protected_spans"] for boundary in (start, end)):
            issues.append(f"child {child.get('chunk_order')} splits a protected source span")
        if any(max(start, s["start_char"]) < min(end, s["end_char"]) for s in expected["excluded_spans"]):
            issues.append("child indexes excluded source content")
        selected = [a for a in expected["atoms"] if start <= a.start and a.end <= end]
        if not selected or len({a.region for a in selected}) > 1:
            issues.append("child crosses semantic region or has no complete atom")
        if child.get("unit_count") != count_units(source[start:end]): issues.append("child unit count mismatch")
        for key, value in (("profile", expected["metadata"]["profile"]),
                           ("section_roles", sorted({a.role for a in selected})),
                           ("content_languages", sorted({a.language for a in selected}))):
            if child.get(key) != value: issues.append(f"child format metadata mismatch: {key}")
        paths = [[s["label"]] for s in expected["section_spans"] if max(start, s["start_char"]) < min(end, s["end_char"])]
        if child.get("section_paths") != paths: issues.append("child section paths mismatch")
        if child.get("boundary_reason") != "whole_source_atom": issues.append("child boundary reason mismatch")
        if child.get("protected_span_checks") != {"cuts": 0, "policy": "whole_sentence_and_structural_atoms"}:
            issues.append("child protected span checks mismatch")
        if selected and child.get("unit_count", 0) < 100:
            parent = parents.get(child.get("parent_id"))
            parent_units = count_units(source[parent["start_char"]:parent["end_char"]]) if parent else 0
            source_units = count_units(source)
            reason = ("short_document" if source_units < 100 else
                      "question_context" if all(a.role in ("title", "question") for a in selected) and expected["metadata"]["profile"] == "qa" else
                      "hard_boundary_region" if parent_units < 100 else "whole_atom_budget_remainder")
            evidence = dict(parent_units=parent_units, source_units=source_units, atom_units=[a.units for a in selected],
                            max_units=config.max_units, region=selected[0].region)
            if child.get("short_chunk_reason") != reason or child.get("short_reason_evidence") != evidence:
                issues.append("child short reason/evidence mismatch")
        if child.get("unit_count", 0) > config.max_units:
            reason = "oversized_structural_atom" if selected and selected[0].boundary_type in ("structural_atom", "list_entry", "must_link_atom") else "oversized_sentence"
            if len(selected) != 1 or child.get("oversized_reason") != reason: issues.append("invalid format oversized atom")
    return issues, expected


def _output_lines(directory: Path) -> Iterator[bytes]:
    for part in sorted(directory.glob("part-*.jsonl")):
        with part.open("rb") as stream:
            yield from stream


def _covered_count(source: str, intervals: list[tuple[int, int]]) -> int:
    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    covered = 0
    for start, end in merged:
        covered += sum(not char.isspace() for char in source[start:end])
    return covered


def _check_record(input_record: dict, output: dict, line_number: int, config: ChunkConfig) -> list[str]:
    issues = []
    raw = input_record.get("text")
    if output.get("input_line") != line_number:
        issues.append("input line mismatch")
    if output.get("doc_id") != input_record.get("id"):
        issues.append("doc_id mismatch")
    if type(output.get("doc_id")) is not int:
        issues.append("doc_id must be an original integer")
    if output.get("url") != input_record.get("url"):
        issues.append("url mismatch")
    if not isinstance(raw, str):
        return issues + ["input text is invalid"]
    if not input_record.get("success") or not raw.strip():
        if output.get("status") != "skipped" or output.get("parents") or output.get("children"):
            issues.append("failed crawl produced chunks")
        return issues
    cleaning = output.get("cleaning")
    if not isinstance(cleaning, dict) or cleaning.get("version") != CLEANER_VERSION:
        return issues + ["cleaner version missing or unsupported"]
    source, expected_cleaning = clean_with_report(raw)
    actions = cleaning.get("actions")
    warnings = cleaning.get("warnings")
    valid_types = (
        type(cleaning.get("input_chars")) is int and type(cleaning.get("output_chars")) is int
        and isinstance(actions, dict) and all(type(value) is int and value >= 0 for value in actions.values())
        and isinstance(warnings, list) and all(
            isinstance(item, dict) and isinstance(item.get("code"), str)
            and type(item.get("count")) is int and item["count"] > 0 for item in warnings
        )
    )
    if not valid_types or cleaning != expected_cleaning:
        issues.append("cleaning report mismatch")
    if output.get("raw_sha256") != expected_cleaning["input_sha256"]:
        issues.append("raw hash mismatch")
    if output.get("source_sha256") != expected_cleaning["output_sha256"]:
        issues.append("cleaned source hash mismatch")
    if not source:
        if output.get("status") != "skipped" or output.get("reason") != "empty_after_cleaning" or output.get("parents") or output.get("children"):
            issues.append("empty cleaned source was not skipped")
        return issues
    if output.get("status") != "ok":
        return issues + ["successful source was not chunked"]
    if output.get("source_length") != len(source):
        issues.append("source length mismatch")
    doc_type, reason, confidence = classify_document_details(source, input_record.get("url", ""))
    if (output.get("doc_type"), output.get("classification_reason"), output.get("classification_confidence")) != (doc_type, reason, confidence):
        issues.append("document classification metadata mismatch")
    format_run = output.get("strategy") == "format" or "profile_version" in output
    if format_run:
        format_issues, analysis = _format_analysis_issues(source, input_record, output, config)
        issues.extend(format_issues)
        atoms = analysis["atoms"]
    else:
        if output.get("version") != config.version: issues.append("chunk version mismatch")
        atoms = extract_atoms(source, config)
    starts = {atom.start for atom in atoms}
    ends = {atom.end for atom in atoms}
    excluded = output.get("excluded_spans", [])
    for span in excluded:
        start, end = span.get("start_char"), span.get("end_char")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(source)):
            issues.append("excluded span offsets out of range")
            continue
        if span.get("doc_id") != input_record.get("id") or span.get("retrieval_eligible") is not False:
            issues.append("excluded span provenance mismatch")
        if span.get("text") != source[start:end]:
            issues.append("excluded span is not an exact source slice")
        starts.add(end)
        ends.add(start)
    parents = {parent["parent_id"]: parent for parent in output.get("parents", [])}
    if len(parents) != len(output.get("parents", [])):
        issues.append("duplicate parent ID")
    children = output.get("children", [])
    if len({child["chunk_id"] for child in children}) != len(children):
        issues.append("duplicate child ID")
    intervals = []
    previous_by_parent = {}
    for order, child in enumerate(children):
        start, end = child["start_char"], child["end_char"]
        if not (0 <= start < end <= len(source)):
            issues.append(f"child {order} offsets out of range")
            continue
        if child["doc_id"] != input_record["id"] or child["chunk_order"] != order:
            issues.append(f"child {order} ID or order mismatch")
        version = PROFILE_VERSION if format_run else config.version
        if child.get("chunk_id") != f"{input_record['id']}:c:{order}:{start}:{end}:{version}":
            issues.append(f"child {order} chunk ID mismatch")
        if child["chunk_text"] != source[start:end]:
            issues.append(f"child {order} is not an exact source slice")
        if start not in starts or end not in ends:
            issues.append(f"child {order} splits a natural atom")
        parent = parents.get(child["parent_id"])
        if parent is None or not (parent["start_char"] <= start < end <= parent["end_char"]):
            issues.append(f"child {order} lies outside its parent")
        if child.get("unit_count", 0) < 100 and not child.get("short_chunk_reason"):
            issues.append(f"child {order} lacks a short-chunk reason")
        if not format_run and child.get("unit_count", 0) > config.max_units and child.get("oversized_reason") != "oversized_atom":
            issues.append(f"child {order} has an invalid oversized reason")
        previous = previous_by_parent.get(child.get("parent_id"))
        expected_overlap = 0
        if previous is not None:
            overlap_start = max(previous["start_char"], start)
            overlap_end = min(previous["end_char"], end)
            expected_overlap = count_units(source[overlap_start:overlap_end]) if overlap_start < overlap_end else 0
            if expected_overlap == 0 and not child.get("overlap_exception"):
                issues.append(f"child {order} has unexplained zero overlap")
        if child.get("overlap_units") != expected_overlap:
            issues.append(f"child {order} overlap metadata mismatch")
        previous_by_parent[child.get("parent_id")] = child
        intervals.append((start, end))
    total = sum(not char.isspace() for char in source)
    indexed = _covered_count(source, intervals)
    excluded_count = _covered_count(source, [(span["start_char"], span["end_char"]) for span in excluded])
    covered = _covered_count(source, intervals + [(span["start_char"], span["end_char"]) for span in excluded])
    expected_coverage = {
        "non_whitespace_total": total,
        "non_whitespace_covered": covered,
        "non_whitespace_indexed": indexed,
        "non_whitespace_excluded": excluded_count,
    }
    if covered != total or output.get("coverage") != expected_coverage:
        issues.append("source coverage mismatch")
    return issues


def audit_output(input_path: str | Path, output_dir: str | Path) -> dict:
    """Compare every output row against the corresponding original test input row."""
    source = Path(input_path)
    directory = Path(output_dir)
    report = {"records": 0, "checked": 0, "skipped": 0, "errors": 0, "examples": []}
    if not sorted(directory.glob("part-*.jsonl")):
        raise FileNotFoundError(f"No output shards in {directory}")
    checkpoint_path = directory / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.is_file() else {}
    if checkpoint_path.is_file() and checkpoint.get("cleaner_version") != CLEANER_VERSION:
        report["errors"] = 1
        report["examples"] = [{"issues": ["checkpoint cleaner version missing or unsupported; cannot reproduce this run"]}]
        return report
    if checkpoint.get("strategy") == "format" and checkpoint.get("profile_version") != PROFILE_VERSION:
        report["errors"] = 1
        report["examples"] = [{"issues": ["checkpoint profile version missing or unsupported"]}]
        return report
    if checkpoint.get("strategy") == "format" and checkpoint.get("format_code_sha256") != _format_code_fingerprint():
        report["errors"] = 1
        report["examples"] = [{"issues": ["checkpoint format code SHA-256 mismatch or missing"]}]
        return report
    config = ChunkConfig(**checkpoint.get("config", {}))
    if checkpoint_path.is_file():
        if checkpoint.get("input_sha256") != _sha256_file(source):
            report["errors"] = 1
            report["examples"] = [{"issues": ["checkpoint input SHA-256 mismatch"]}]
            return report
        shard_records = checkpoint.get("shard_records")
        if checkpoint.get("strategy") == "format" and type(shard_records) is not int:
            report["errors"] = 1
            report["examples"] = [{"issues": ["checkpoint shard size missing; cannot reproduce configuration"]}]
            return report
        if shard_records is not None and checkpoint.get("config_sha256") != _config_fingerprint(config, checkpoint.get("strategy", "hybrid"), shard_records):
            report["errors"] = 1
            report["examples"] = [{"issues": ["checkpoint configuration fingerprint mismatch"]}]
            return report
    with source.open("rb") as input_stream:
        for line_number, (raw, output_raw) in enumerate(zip_longest(input_stream, _output_lines(directory)), 1):
            report["records"] += 1
            try:
                if raw is None or output_raw is None:
                    raise ValueError("Input/output record count mismatch")
                input_record = json.loads(raw)
                output = json.loads(output_raw)
                issues = _check_record(input_record, output, line_number, config)
                if checkpoint_path.is_file() and output.get("status") == "ok" and output.get("strategy") != checkpoint.get("strategy"):
                    issues.append("record strategy differs from checkpoint")
                report["checked"] += output.get("status") == "ok"
                report["skipped"] += output.get("status") == "skipped"
            except (ValueError, TypeError, KeyError, IndexError, UnicodeDecodeError, json.JSONDecodeError) as error:
                issues = [f"audit parse/shape failure: {error}"]
            if issues:
                report["errors"] += len(issues)
                if len(report["examples"]) < 20:
                    report["examples"].append({"input_line": line_number, "issues": issues})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = audit_output(args.input, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
