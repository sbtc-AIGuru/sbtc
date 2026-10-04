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


if __name__ == "__main__":
    unittest.main()
