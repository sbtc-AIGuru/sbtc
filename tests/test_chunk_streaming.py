"""Streaming and resume checks derived only from datacrawl/test.jsonl."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sbtc.Scripts.Preprocess.chunk_cli import run_chunking
from sbtc.Scripts.Preprocess.chunk_audit import audit_output
from sbtc.Scripts.Preprocess.chunking import ChunkConfig


DATASET = Path(__file__).resolve().parents[2] / "datacrawl/test.jsonl"


def dataset_lines() -> list[bytes]:
    selected: list[bytes] = []
    successful = 0
    failed = False
    with DATASET.open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            if not row["success"] and not failed:
                selected.append(line)
                failed = True
            elif row["success"] and successful < 5:
                selected.append(line)
                successful += 1
            if successful == 5 and failed:
                break
    if len(selected) != 6:
        raise AssertionError("test.jsonl lacks the expected success/failure samples")
    return selected


def output_rows(directory: Path) -> list[dict]:
    rows = []
    for shard in sorted(directory.glob("part-*.jsonl")):
        with shard.open(encoding="utf-8") as stream:
            rows.extend(json.loads(line) for line in stream)
    return rows


def boilerplate_lines() -> list[bytes]:
    wanted = {103925, 2443608, 2991145, 942223}
    selected = []
    with DATASET.open("rb") as stream:
        for line in stream:
            if json.loads(line)["id"] in wanted:
                selected.append(line)
            if len(selected) == len(wanted):
                break
    if len(selected) != len(wanted):
        raise AssertionError("test.jsonl lacks boilerplate regression records")
    return selected


def record_line(doc_id: int) -> bytes:
    with DATASET.open("rb") as stream:
        for line in stream:
            if json.loads(line)["id"] == doc_id:
                return line
    raise AssertionError(f"test.jsonl lacks regression record {doc_id}")


class ChunkStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lines = dataset_lines()

    def test_streaming_resume_matches_uninterrupted_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            resumed, complete = root / "resumed", root / "complete"
            partial_report = run_chunking(source, resumed, ChunkConfig(), shard_records=2, max_shards=1)
            self.assertFalse(partial_report["done"])
            report = run_chunking(source, resumed, ChunkConfig(), shard_records=2, resume=True)
            reference = run_chunking(source, complete, ChunkConfig(), shard_records=2, workers=2)
            self.assertTrue(report["done"])
            self.assertEqual(report["records"], len(self.lines))
            self.assertEqual(report["reason_counts"].get("crawl_failed"), 1)
            self.assertEqual(report["records"], reference["records"])
            self.assertIn("eligible_overlap_rate", reference)
            self.assertIn("short_chunk_reason_counts", reference)
            self.assertIn("excluded_rule_counts", reference)
            self.assertEqual(output_rows(resumed), output_rows(complete))
            self.assertEqual(audit_output(source, resumed)["errors"], 0)

    def test_resume_rejects_missing_or_changed_cleaner_before_recovery(self) -> None:
        for version in (None, "unknown-cleaner"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "test.jsonl"
                source.write_bytes(b"".join(self.lines))
                output = root / "output"
                run_chunking(source, output, shard_records=2, max_shards=1)
                checkpoint_path = output / "checkpoint.json"
                checkpoint = json.loads(checkpoint_path.read_text())
                if version is None:
                    checkpoint.pop("cleaner_version", None)
                else:
                    checkpoint["cleaner_version"] = version
                part = output / "part-000000.jsonl"
                checkpoint["pending"] = {
                    "index": 0, "sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
                    "end_offset": checkpoint["next_offset"], "end_line": checkpoint["last_line"],
                    "summary_after": checkpoint["summary"],
                }
                checkpoint_path.write_text(json.dumps(checkpoint))
                before = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
                with self.assertRaisesRegex(ValueError, "Cleaner version"):
                    run_chunking(source, output, shard_records=2, resume=True)
                self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()})
                self.assertGreater(audit_output(source, output)["errors"], 0)

    def test_v3_audit_covers_indexed_and_excluded_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(boilerplate_lines()))
            output = root / "out"
            report = run_chunking(source, output, ChunkConfig(), shard_records=2)
            audit = audit_output(source, output)
            self.assertEqual(report["excluded_spans"], 4)
            self.assertGreater(report["excluded_non_whitespace"], 0)
            self.assertEqual(audit["records"], 4)
            self.assertEqual(audit["errors"], 0)

    def test_audit_uses_the_chunk_run_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(record_line(1429888))
            output = root / "out"
            config = ChunkConfig(min_units=300, target_units=400, max_units=500, overlap_units=40)
            run_chunking(source, output, config)
            rows = output_rows(output)
            self.assertTrue(any(300 < child["unit_count"] <= 500 for child in rows[0]["children"]))
            self.assertEqual(audit_output(source, output)["errors"], 0)

    def test_malformed_line_is_reported_and_later_records_continue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(self.lines[0] + self.lines[1][:-3] + b"\n" + self.lines[2])
            report = run_chunking(source, root / "out", ChunkConfig(), shard_records=2)
            rows = output_rows(root / "out")
            self.assertEqual(report["records"], 3)
            self.assertEqual(report["reason_counts"].get("JSONDecodeError"), 1)
            self.assertEqual(rows[1]["status"], "error")
            self.assertEqual(rows[1]["input_line"], 2)
            self.assertEqual(rows[2]["input_line"], 3)

    def test_rejects_existing_output_and_changed_config_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            output = root / "out"
            run_chunking(source, output, ChunkConfig(), shard_records=2, max_shards=1)
            with self.assertRaises(FileExistsError):
                run_chunking(source, output, ChunkConfig(), shard_records=2)
            with self.assertRaises(ValueError):
                run_chunking(source, output, ChunkConfig(target_units=230), shard_records=2, resume=True)

    def test_resume_completes_a_shard_interrupted_after_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            output = root / "out"
            real_replace = os.replace
            interrupted = False

            def interrupt_once(src: str | Path, dst: str | Path) -> None:
                nonlocal interrupted
                if not interrupted and str(dst).endswith("part-000000.jsonl"):
                    interrupted = True
                    raise RuntimeError("simulated interruption during shard commit")
                real_replace(src, dst)

            with patch("sbtc.Scripts.Preprocess.chunk_cli.os.replace", side_effect=interrupt_once):
                with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                    run_chunking(source, output, ChunkConfig(), shard_records=2)
            report = run_chunking(source, output, ChunkConfig(), shard_records=2, resume=True)
            self.assertTrue(report["done"])
            self.assertEqual(report["records"], len(self.lines))
            self.assertEqual(audit_output(source, output)["errors"], 0)


if __name__ == "__main__":
    unittest.main()
