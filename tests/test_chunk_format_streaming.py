"""Format CLI integration checks using only derived test_20k.jsonl records."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sbtc.Scripts.Clawler.verbatim import CLEANER_VERSION
from sbtc.Scripts.Preprocess.chunk_audit import audit_output
from sbtc.Scripts.Preprocess.chunk_cli import run_chunking
from sbtc.Scripts.Preprocess.chunking import ChunkConfig
from sbtc.tests.test_chunk_formats import DATASET, review_records


def encoded_record(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


def output_rows(directory: Path) -> list[dict]:
    rows = []
    for shard in sorted(directory.glob("part-*.jsonl")):
        with shard.open(encoding="utf-8") as stream:
            rows.extend(json.loads(raw) for raw in stream)
    return rows


def output_snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


class FormatStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = review_records()
        selected = [cls.records[doc_id] for doc_id in (
            6954391, 6333519, 2335124, 7156587, 6248072, 4265827, 211401, 1128713,
        )]
        with DATASET.open("rb") as stream:
            for raw in stream:
                failed = json.loads(raw)
                if failed["success"] is False:
                    selected.append(failed)
                    break
            else:
                raise AssertionError("Approved test sample lacks a failed crawl")
        cls.lines = [encoded_record(record) for record in selected]

    def run_format(self, source: Path, output: Path, config: ChunkConfig | None = None, **kwargs) -> dict:
        return run_chunking(
            source, output, config or ChunkConfig(), strategy="format",
            progress_every=0, **kwargs,
        )

    def test_resume_and_parallel_workers_match_uninterrupted_serial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            partial = self.run_format(source, root / "resumed", shard_records=2, max_shards=1)
            self.assertFalse(partial["done"])
            resumed = self.run_format(source, root / "resumed", shard_records=2, workers=2, resume=True)
            serial = self.run_format(source, root / "serial", shard_records=2, workers=1)
            parallel = self.run_format(source, root / "parallel", shard_records=2, workers=2)
            self.assertTrue(resumed["done"])
            self.assertEqual(resumed["records"], len(self.lines))
            self.assertEqual(resumed["reason_counts"].get("crawl_failed"), 1)
            self.assertEqual(resumed["errors"], 0)
            self.assertEqual(output_rows(root / "resumed"), output_rows(root / "serial"))
            self.assertEqual(output_rows(root / "serial"), output_rows(root / "parallel"))
            for report in (resumed, serial, parallel):
                self.assertEqual(report["profile_version"], "format-v3")
                self.assertEqual(report["source_non_whitespace"], report["covered_non_whitespace"])
            self.assertEqual(audit_output(source, root / "resumed")["errors"], 0)

    def test_checkpoint_pins_profile_and_cleaner_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(self.lines[0])
            self.run_format(source, root / "out")
            checkpoint = json.loads((root / "out/checkpoint.json").read_text())
            self.assertEqual(checkpoint["profile_version"], "format-v3")
            self.assertEqual(checkpoint["cleaner_version"], CLEANER_VERSION)
            self.assertEqual(checkpoint["strategy"], "format")

    def test_checkpoint_pins_format_implementation_code_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(self.lines[0])
            self.run_format(source, root / "out")
            checkpoint = json.loads((root / "out/checkpoint.json").read_text())
            self.assertRegex(checkpoint["format_code_sha256"], r"^[0-9a-f]{64}$")

    def test_changed_or_missing_format_code_hash_rejects_resume_and_audit_before_recovery(self) -> None:
        for code_hash in (None, "0" * 64):
            with self.subTest(code_hash=code_hash), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "test.jsonl"
                source.write_bytes(b"".join(self.lines))
                output = root / "out"
                self.run_format(source, output, shard_records=2, max_shards=1)
                checkpoint_path = output / "checkpoint.json"
                checkpoint = json.loads(checkpoint_path.read_text())
                if code_hash is None:
                    checkpoint.pop("format_code_sha256", None)
                else:
                    checkpoint["format_code_sha256"] = code_hash
                part = output / "part-000000.jsonl"
                checkpoint["pending"] = {
                    "index": 0, "sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
                    "end_offset": checkpoint["next_offset"], "end_line": checkpoint["last_line"],
                    "summary_after": checkpoint["summary"],
                }
                checkpoint_path.write_text(json.dumps(checkpoint))
                before = output_snapshot(output)
                with self.assertRaisesRegex(ValueError, "[Cc]ode|implementation|[Ff]ormat"):
                    self.run_format(source, output, shard_records=2, resume=True)
                self.assertEqual(before, output_snapshot(output))
                self.assertGreater(audit_output(source, output)["errors"], 0)
                self.assertEqual(before, output_snapshot(output))

    def test_resume_rejects_missing_or_changed_profile_before_pending_recovery(self) -> None:
        for version in (None, "unrecognised-format"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "test.jsonl"
                source.write_bytes(b"".join(self.lines))
                output = root / "out"
                self.run_format(source, output, shard_records=2, max_shards=1)
                checkpoint_path = output / "checkpoint.json"
                checkpoint = json.loads(checkpoint_path.read_text())
                if version is None:
                    checkpoint.pop("profile_version", None)
                else:
                    checkpoint["profile_version"] = version
                part = output / "part-000000.jsonl"
                checkpoint["pending"] = {
                    "index": 0, "sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
                    "end_offset": checkpoint["next_offset"], "end_line": checkpoint["last_line"],
                    "summary_after": checkpoint["summary"],
                }
                checkpoint_path.write_text(json.dumps(checkpoint))
                before = output_snapshot(output)
                with self.assertRaisesRegex(ValueError, "[Pp]rofile|[Ff]ormat"):
                    self.run_format(source, output, shard_records=2, resume=True)
                self.assertEqual(before, output_snapshot(output))
                self.assertGreater(audit_output(source, output)["errors"], 0)

    def test_resume_rejects_changed_cleaner_without_modifying_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            output = root / "out"
            self.run_format(source, output, shard_records=2, max_shards=1)
            checkpoint_path = output / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            checkpoint["cleaner_version"] = "unknown-cleaner"
            checkpoint_path.write_text(json.dumps(checkpoint))
            before = output_snapshot(output)
            with self.assertRaisesRegex(ValueError, "Cleaner version"):
                self.run_format(source, output, shard_records=2, resume=True)
            self.assertEqual(before, output_snapshot(output))

    def test_interrupted_pending_shard_recovers_without_duplicates(self) -> None:
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
                    raise RuntimeError("simulated interruption during format shard commit")
                real_replace(src, dst)

            with patch("sbtc.Scripts.Preprocess.chunk_cli.os.replace", side_effect=interrupt_once):
                with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                    self.run_format(source, output, shard_records=2)
            checkpoint = json.loads((output / "checkpoint.json").read_text())
            self.assertIn("pending", checkpoint)
            self.assertEqual(checkpoint["profile_version"], "format-v3")
            report = self.run_format(source, output, shard_records=2, resume=True)
            self.run_format(source, root / "reference", shard_records=2)
            self.assertTrue(report["done"])
            self.assertEqual(report["records"], len(self.lines))
            self.assertEqual(output_rows(output), output_rows(root / "reference"))
            self.assertEqual(audit_output(source, output)["errors"], 0)

    def test_pending_shard_checksum_failure_is_not_silently_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            output = root / "out"
            self.run_format(source, output, shard_records=2, max_shards=1)
            checkpoint_path = output / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            checkpoint["pending"] = {
                "index": 0, "sha256": "0" * 64,
                "end_offset": checkpoint["next_offset"], "end_line": checkpoint["last_line"],
                "summary_after": checkpoint["summary"],
            }
            checkpoint_path.write_text(json.dumps(checkpoint))
            before = output_snapshot(output)
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                self.run_format(source, output, shard_records=2, resume=True)
            self.assertEqual(before, output_snapshot(output))

    def test_zero_overlap_config_never_repeats_medical_sentence_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(encoded_record(self.records[6333519]))
            config = ChunkConfig(overlap_units=0)
            self.run_format(source, root / "out", config)
            result = output_rows(root / "out")[0]
            self.assertGreater(len(result["children"]), 1)
            self.assertTrue(all(child["overlap_units"] == 0 for child in result["children"]))
            for previous, child in zip(result["children"], result["children"][1:]):
                self.assertLessEqual(previous["end_char"], child["start_char"])
            self.assertEqual(audit_output(source, root / "out")["errors"], 0)

    def test_custom_small_budget_keeps_oversized_sentences_and_audits_its_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(encoded_record(self.records[6333519]))
            config = ChunkConfig(min_units=30, target_units=45, max_units=60, overlap_units=10)
            self.run_format(source, root / "out", config)
            result = output_rows(root / "out")[0]
            self.assertGreater(len(result["children"]), 1)
            oversized = [child for child in result["children"] if child["unit_count"] > config.max_units]
            self.assertTrue(oversized, "Real long randomisation sentence must not be split to meet 60 units")
            for child in oversized:
                self.assertIn(child["oversized_reason"], ("oversized_sentence", "oversized_structural_atom", "oversized_unresolved"))
            self.assertEqual(audit_output(source, root / "out")["errors"], 0)

    def test_empty_input_produces_completed_zero_record_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"")
            report = self.run_format(source, root / "out")
            self.assertTrue(report["done"])
            self.assertEqual(report["records"], 0)
            self.assertEqual(report["chunks"], 0)
            self.assertEqual(report["profile_version"], "format-v3")
            self.assertEqual(output_rows(root / "out"), [])
            resumed = self.run_format(source, root / "out", resume=True)
            self.assertTrue(resumed["done"])
            self.assertEqual(resumed["records"], 0)

    def test_empty_record_is_skipped_and_invalid_schema_does_not_stop_later_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            empty = dict(self.records[1128713], text="")
            invalid = dict(self.records[6954391], id=True)
            source.write_bytes(encoded_record(empty) + encoded_record(invalid) + encoded_record(self.records[6333519]))
            report = self.run_format(source, root / "out", shard_records=1)
            rows = output_rows(root / "out")
            self.assertEqual(report["records"], 3)
            self.assertEqual(report["skipped"], 1)
            self.assertEqual(report["errors"], 1)
            self.assertEqual(rows[0]["reason"], "empty_text")
            self.assertEqual(rows[1]["status"], "error")
            self.assertEqual(rows[1]["error_type"], "ValueError")
            self.assertEqual(rows[2]["doc_id"], 6333519)
            self.assertEqual([row["input_line"] for row in rows], [1, 2, 3])

    def test_malformed_json_reports_exact_line_and_keeps_following_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            malformed = self.lines[0][:-4] + b"\n"
            source.write_bytes(self.lines[0] + malformed + self.lines[1])
            report = self.run_format(source, root / "out", shard_records=2)
            rows = output_rows(root / "out")
            self.assertEqual(report["records"], 3)
            self.assertEqual(report["reason_counts"].get("JSONDecodeError"), 1)
            self.assertEqual(rows[1]["status"], "error")
            self.assertEqual(rows[1]["input_line"], 2)
            self.assertEqual(rows[2]["doc_id"], 6333519)

    def test_existing_output_and_changed_configuration_are_rejected_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            output = root / "out"
            self.run_format(source, output, shard_records=2, max_shards=1)
            before = output_snapshot(output)
            with self.assertRaises(FileExistsError):
                self.run_format(source, output, shard_records=2)
            with self.assertRaisesRegex(ValueError, "configuration"):
                self.run_format(source, output, ChunkConfig(target_units=230), shard_records=2, resume=True)
            with self.assertRaisesRegex(ValueError, "configuration"):
                run_chunking(source, output, strategy="hybrid", shard_records=2, resume=True, progress_every=0)
            self.assertEqual(before, output_snapshot(output))

    def test_source_change_is_rejected_on_resume_without_changing_committed_shards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(b"".join(self.lines))
            output = root / "out"
            self.run_format(source, output, shard_records=2, max_shards=1)
            before = output_snapshot(output)
            source.write_bytes(source.read_bytes() + self.lines[0])
            with self.assertRaisesRegex(ValueError, "Input"):
                self.run_format(source, output, shard_records=2, resume=True)
            self.assertEqual(before, output_snapshot(output))

    def test_invalid_streaming_options_are_rejected_before_creating_output(self) -> None:
        for options in ({"workers": 0}, {"shard_records": 0}, {"max_shards": 0}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "test.jsonl"
                source.write_bytes(self.lines[0])
                output = root / "out"
                with self.assertRaises(ValueError):
                    self.run_format(source, output, **options)
                self.assertFalse(output.exists())

    def test_audit_rejects_changed_checkpoint_source_or_configuration_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.jsonl"
            source.write_bytes(self.lines[0])
            output = root / "out"
            self.run_format(source, output)
            checkpoint_path = output / "checkpoint.json"
            original = json.loads(checkpoint_path.read_text())
            self.assertEqual(audit_output(source, output)["errors"], 0)
            for field in ("input_sha256", "config_sha256", "config"):
                with self.subTest(field=field):
                    checkpoint = dict(original)
                    if field == "config":
                        checkpoint[field] = dict(original[field], target_units=230)
                    else:
                        checkpoint[field] = "0" * 64
                    checkpoint_path.write_text(json.dumps(checkpoint))
                    before = output_snapshot(output)
                    self.assertGreater(audit_output(source, output)["errors"], 0,
                                       f"Auditor trusted changed checkpoint {field}")
                    self.assertEqual(before, output_snapshot(output))


if __name__ == "__main__":
    unittest.main()
