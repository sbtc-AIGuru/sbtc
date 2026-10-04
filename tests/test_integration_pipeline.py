"""Integration tests for the crawl and compaction pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from utils import JsonlWriter, SourceRecord, load_completed_ids
from compact import compact


class TestIntegrationPipeline(unittest.TestCase):
    """Test JsonlWriter, append/resume, and compact.py workflow."""

    def test_resume_adds_separator_after_complete_final_record(self):
        """A crash after JSON bytes but before newline must not corrupt the next row."""
        with TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test_crawl.jsonl"
            original = {"id": 583, "url": "https://a.com", "text": "Article", "success": True}
            following = {"id": 584, "url": "https://b.com", "text": "Next", "success": True}
            out_file.write_text(json.dumps(original), encoding="utf-8")

            with JsonlWriter(out_file) as writer:
                self.assertEqual(writer.completed_ids, {583: "https://a.com"})
                writer.write(following)

            lines = out_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(line) for line in lines], [original, following])

    def test_jsonl_writer_and_resume(self):
        """Test JsonlWriter writes records with file lock and recovers completed IDs."""
        with TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test_crawl.jsonl"
            
            # Step 1: Write 3 records
            with JsonlWriter(out_file) as writer:
                writer.write({"row_index": 0, "id": 583, "url": "https://a.com", "text": "Text 0", "success": True})
                writer.write({"row_index": 1, "id": 584, "url": "https://b.com", "text": "Text 1", "success": True})
                writer.write({"row_index": 2, "id": 585, "url": "https://c.com", "text": "", "success": False, "error": "Timeout"})

            completed = load_completed_ids(out_file)
            self.assertEqual(len(completed), 2)
            self.assertIn(583, completed)
            self.assertIn(584, completed)
            self.assertNotIn(585, completed)  # Failed record is not completed

            # Step 2: Resume with JsonlWriter and retry failed record
            with JsonlWriter(out_file) as writer:
                writer.write({"row_index": 2, "id": 585, "url": "https://c.com", "text": "Text 2 recovered", "success": True})

            completed_after = load_completed_ids(out_file)
            self.assertEqual(len(completed_after), 3)
            self.assertIn(585, completed_after)

    def test_compact_canonical_order(self):
        """Test compact.py orders shuffled/retried JSONL into strict Parquet sequence."""
        source_path = PROJECT_ROOT / "data/links_corpus.parquet"
        if not source_path.exists():
            self.skipTest("links_corpus.parquet not available")

        table = pq.read_table(source_path)
        url_0 = table["url"][0].as_py()
        id_0 = table["id"][0].as_py()
        url_1 = table["url"][1].as_py()
        id_1 = table["id"][1].as_py()

        with TemporaryDirectory() as tmp_dir:
            raw_file = Path(tmp_dir) / "raw.jsonl"
            canonical_file = Path(tmp_dir) / "canonical.jsonl"

            # Write out of order and with duplicate
            records = [
                {"row_index": 1, "id": id_1, "url": url_1, "text": "Text row 1", "success": True},
                {"row_index": 0, "id": id_0, "url": url_0, "text": "", "success": False, "error": "HTTP 404"},
                {"row_index": 0, "id": id_0, "url": url_0, "text": "Text row 0 recovered", "success": True},
            ]
            with raw_file.open("w", encoding="utf-8") as h:
                for r in records:
                    h.write(json.dumps(r, ensure_ascii=False) + "\n")

            raw_lines, success, failed = compact(
                source=source_path, raw=raw_file, output=canonical_file, start=0, end=1
            )
            self.assertEqual(raw_lines, 3)
            self.assertEqual(success, 2)
            self.assertEqual(failed, 0)

            # Check lines in canonical output
            lines = [json.loads(line) for line in canonical_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(lines), 2)
            # Row 0 must be first, with recovered success
            self.assertEqual(lines[0]["row_index"], 0)
            self.assertEqual(lines[0]["id"], 583)
            self.assertEqual(lines[0]["text"], "Text row 0 recovered")
            # Row 1 must be second
            self.assertEqual(lines[1]["row_index"], 1)
            self.assertEqual(lines[1]["id"], 584)


if __name__ == "__main__":
    unittest.main()
