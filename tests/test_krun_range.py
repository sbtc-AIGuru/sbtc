"""Offline validation of unordered and retried Kaggle crawl shards."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

import krun_range


class TestKrunRange(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data").mkdir()
        self.jobs = self.root / "jobs"
        self.source = self.root / "source.parquet"
        pq.write_table(
            pa.table(
                {
                    "id": [100, 101, 102, 103],
                    "url": [f"https://example.test/{index}" for index in range(4)],
                }
            ),
            self.source,
        )
        for name, value in (
            ("PROJECT_ROOT", self.root),
            ("JOB_DIR", self.jobs),
            ("INPUT", self.source),
        ):
            patcher = patch.object(krun_range, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_job(self, job_id: str, start: int, end: int, rows: list[dict]) -> krun_range.Job:
        job = krun_range.Job(job_id, start, end, "complete", "")
        job.output_path.parent.mkdir(parents=True)
        with job.output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return job

    @staticmethod
    def row(index: int, *, success: bool = True, text: str = "article") -> dict:
        value = {
            "row_index": index,
            "id": index + 100,
            "url": f"https://example.test/{index}",
            "success": success,
            "text": text if success else "",
        }
        if not success:
            value["error"] = "temporary failure"
        return value

    def test_validate_and_merge_unordered_shards_with_retries(self) -> None:
        first = self.make_job(
            "first", 0, 1,
            [self.row(1, success=False), self.row(0), self.row(1, text="recovered")],
        )
        second = self.make_job("second", 2, 3, [self.row(3, success=False), self.row(2)])

        self.assertEqual(krun_range.validate_output(first), (2, 0))
        self.assertEqual(krun_range.validate_output(second), (1, 1))
        merged = krun_range.merge_outputs(0, 3, {(2, 3): second, (0, 1): first})
        rows = [json.loads(line) for line in merged.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([row["row_index"] for row in rows], [0, 1, 2, 3])
        self.assertEqual(rows[1]["text"], "recovered")
        self.assertFalse(rows[3]["success"])

    def test_merge_removes_image_targets_from_existing_shards(self) -> None:
        first = self.make_job(
            "with-image", 0, 1,
            [
                self.row(0, text="Triệu chứng ![mẩn đỏ](https://cdn.example.test/photo.jpg) rõ."),
                self.row(1, text="Điều trị [tham khảo](https://example.test/guide)."),
            ],
        )
        merged = krun_range.merge_outputs(0, 1, {(0, 1): first})
        rows = [json.loads(line) for line in merged.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["text"], "Triệu chứng mẩn đỏ rõ.")
        self.assertEqual(rows[1]["text"], "Điều trị tham khảo.")
        self.assertEqual(rows[0]["url"], "https://example.test/0")

    def test_image_only_result_becomes_failure_after_cleaning(self) -> None:
        job = self.make_job(
            "image-only", 0, 1,
            [self.row(0, text="![](https://cdn.example.test/photo.jpg)"), self.row(1)],
        )
        self.assertEqual(krun_range.validate_output(job), (1, 1))
        merged = krun_range.merge_outputs(0, 1, {(0, 1): job})
        first = json.loads(merged.read_text(encoding="utf-8").splitlines()[0])
        self.assertFalse(first["success"])
        self.assertEqual(first["text"], "")

    def test_validate_rejects_wrong_source_mapping(self) -> None:
        wrong = self.row(0)
        wrong["id"] = 999
        job = self.make_job("wrong", 0, 1, [wrong, self.row(1)])
        with self.assertRaisesRegex(ValueError, "ID/URL mismatch"):
            krun_range.validate_output(job)

    def test_validate_rejects_missing_row(self) -> None:
        job = self.make_job("missing", 0, 1, [self.row(0)])
        with self.assertRaisesRegex(ValueError, "Missing crawl result"):
            krun_range.validate_output(job)

    def test_validate_rejects_failure_without_error(self) -> None:
        invalid = self.row(1, success=False)
        del invalid["error"]
        job = self.make_job("no-error", 0, 1, [self.row(0), invalid])
        with self.assertRaisesRegex(ValueError, "Invalid failure record"):
            krun_range.validate_output(job)

    def test_validate_rejects_empty_success(self) -> None:
        for job_id, has_success_field in (("empty-true", True), ("empty-legacy", False)):
            with self.subTest(job_id=job_id):
                invalid = self.row(1, text="")
                if not has_success_field:
                    del invalid["success"]
                job = self.make_job(job_id, 0, 1, [self.row(0), invalid])
                with self.assertRaisesRegex(ValueError, "Empty successful record"):
                    krun_range.validate_output(job)

    def test_validate_rejects_non_boolean_success(self) -> None:
        invalid = self.row(1)
        invalid["success"] = 0
        job = self.make_job("non-boolean", 0, 1, [self.row(0), invalid])
        with self.assertRaisesRegex(ValueError, "Invalid success flag"):
            krun_range.validate_output(job)

    def test_merge_does_not_publish_empty_success(self) -> None:
        job = self.make_job("invalid-merge", 0, 1, [self.row(0), self.row(1, text="")])
        final = self.root / "data/crawled_0_1.jsonl"

        with self.assertRaisesRegex(ValueError, "Empty successful record"):
            krun_range.merge_outputs(0, 1, {(0, 1): job})

        self.assertFalse(final.exists())

    def test_submit_job_forwards_http_concurrency(self) -> None:
        with patch.object(krun_range, "run_krun", return_value="Job ID: test-job\n") as run_krun:
            job = krun_range.submit_job(0, 1, 50, 4, 12)

        self.assertEqual(job.job_id, "test-job")
        arguments = run_krun.call_args.args
        position = arguments.index("--http-concurrency")
        self.assertEqual(arguments[position + 1], "12")

    def test_submit_job_forwards_browser_tuning(self) -> None:
        with patch.object(krun_range, "run_krun", return_value="Job ID: tuned-job\n") as run_krun:
            krun_range.submit_job(
                0, 1, 1, 1, 1,
                max_in_flight=1, browser_recycle_after=1,
                request_interval_seconds=2.5,
            )
        arguments = run_krun.call_args.args
        for option, expected in (
            ("--max-in-flight", "1"),
            ("--browser-recycle-after", "1"),
            ("--request-interval-seconds", "2.5"),
        ):
            self.assertEqual(arguments[arguments.index(option) + 1], expected)

    def test_invalid_completed_shard_is_retried(self) -> None:
        bad_job = self.make_job("bad", 0, 1, [self.row(0)])
        args = type("Args", (), {
            "start": 0, "end": 1, "max_active": 1, "shard_size": 2,
            "batch_size": 50, "concurrency": 4, "http_concurrency": 8,
        })()
        with (
            patch.object(krun_range, "discover_jobs", return_value=[bad_job]),
            patch.object(krun_range, "submit_job") as submit,
        ):
            complete = krun_range.run_cycle(args, self.root / "validated.json")

        self.assertFalse(complete)
        submit.assert_called_once_with(0, 1, 50, 4, 8)
        rejected = json.loads((self.root / "validated_rejected.json").read_text())
        self.assertIn("bad", rejected)

    def test_stale_missing_kaggle_job_is_resubmitted(self) -> None:
        missing = krun_range.Job("missing", 0, 1, "submitted", "2020-01-01T00:00:00+00:00")
        args = type("Args", (), {
            "start": 0, "end": 1, "max_active": 1, "shard_size": 2,
            "batch_size": 50, "concurrency": 4, "http_concurrency": 8,
        })()
        with (
            patch.object(krun_range, "discover_jobs", return_value=[missing]),
            patch.object(
                krun_range, "refresh_job",
                side_effect=RuntimeError("404 Client Error: Not Found"),
            ),
            patch.object(krun_range, "submit_job") as submit,
        ):
            self.assertFalse(krun_range.run_cycle(args, self.root / "validated.json"))
        submit.assert_called_once_with(0, 1, 50, 4, 8)
        rejected = json.loads((self.root / "validated_rejected.json").read_text())
        self.assertIn("missing", rejected)

    def test_completed_shard_prefers_more_text_and_ignores_rejected_job(self) -> None:
        low = self.make_job("low", 0, 1, [self.row(0), self.row(1, success=False)])
        high = self.make_job("high", 0, 1, [self.row(0), self.row(1)])
        validated = {"low": [1, 1], "high": [2, 0]}
        selected = krun_range.complete_segments([high, low], validated)
        self.assertEqual(selected[(0, 1)].job_id, "high")
        rejected = krun_range.Job("high", 0, 1, "invalid", "")
        selected = krun_range.complete_segments([rejected, low], validated)
        self.assertEqual(selected[(0, 1)].job_id, "low")

    def test_low_success_shard_stops_new_submissions(self) -> None:
        poor = self.make_job(
            "poor", 0, 1, [self.row(0), self.row(1, success=False)]
        )
        args = type("Args", (), {
            "start": 0, "end": 3, "max_active": 1, "shard_size": 2,
            "batch_size": 50, "concurrency": 4, "http_concurrency": 8,
            "min_success_rate": 0.75,
        })()
        with (
            patch.object(krun_range, "discover_jobs", return_value=[poor]),
            patch.object(krun_range, "submit_job") as submit,
        ):
            with self.assertRaisesRegex(krun_range.QualityHold, "1/2"):
                krun_range.run_cycle(args, self.root / "validated.json")
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
