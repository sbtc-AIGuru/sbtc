"""Check final corpus coverage and source identity before large merges."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import pyarrow as pa
import pyarrow.parquet as pq


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))

from merge_corpus import merge_corpus


class TestMergeCorpus(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source.parquet"
        pq.write_table(
            pa.table({
                "id": [100, 101, 102, 103, 104, 105],
                "url": [f"https://example.org/{row}" for row in range(6)],
            }),
            self.source,
        )
        self.output = self.root / "merged.jsonl"

    def write_rows(self, name: str, rows: list[int], *, wrong_id: bool = False) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                success = row != 2
                handle.write(json.dumps({
                    "row_index": row,
                    "id": 999 if wrong_id else 100 + row,
                    "url": f"https://example.org/{row}",
                    "success": success,
                    "text": f"Article {row}" if success else "",
                    "error": "Unavailable" if not success else None,
                }) + "\n")
        return path

    def test_merge_preserves_failures_and_only_skips_allowed_gap(self) -> None:
        first = self.write_rows("first.jsonl", [0, 1, 2])
        second = self.write_rows("second.jsonl", [4, 5])
        manifest = merge_corpus(
            self.source, [second, first], self.output, 5, 105, [(3, 4)]
        )
        rows = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual([row["row_index"] for row in rows], [0, 1, 2, 4, 5])
        self.assertFalse(rows[2]["success"])
        self.assertEqual((manifest["rows"], manifest["failed"], manifest["omitted"]), (5, 1, 1))
        self.assertTrue(self.output.with_suffix(".manifest.json").is_file())

    def test_missing_required_row_leaves_no_output(self) -> None:
        source = self.write_rows("partial.jsonl", [0, 1, 3, 4, 5])
        with self.assertRaisesRegex(ValueError, "Missing required Parquet row 2"):
            merge_corpus(self.source, [source], self.output, 5, 105, [(4, 4)])
        self.assertFalse(self.output.exists())

    def test_wrong_source_id_leaves_no_output(self) -> None:
        source = self.write_rows("wrong.jsonl", [0, 1, 2, 3, 4, 5], wrong_id=True)
        with self.assertRaisesRegex(ValueError, "ID/URL mismatch"):
            merge_corpus(self.source, [source], self.output, 5, 105, [])
        self.assertFalse(self.output.exists())

    def test_duplicate_row_leaves_no_output(self) -> None:
        first = self.write_rows("first.jsonl", [0, 1, 2, 3])
        second = self.write_rows("second.jsonl", [3, 4, 5])
        with self.assertRaisesRegex(ValueError, "Duplicate or unexpected row 3"):
            merge_corpus(self.source, [first, second], self.output, 5, 105, [])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
