"""Offline checks for resumable local shards and their final merge."""

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

import local_range


class TestLocalRange(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data").mkdir()
        self.source = self.root / "data/source.parquet"
        pq.write_table(
            pa.table({
                "id": [501, 502, 503],
                "url": [f"https://example.test/{index}" for index in range(3)],
            }),
            self.source,
        )
        for name, value in (("PROJECT_ROOT", self.root), ("SOURCE", self.source)):
            patcher = patch.object(local_range, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_shard(self, start: int, end: int) -> Path:
        path = local_range.shard_path(start, end)
        with path.open("w", encoding="utf-8") as handle:
            for index in range(start, end + 1):
                handle.write(json.dumps({
                    "row_index": index,
                    "id": index + 501,
                    "url": f"https://example.test/{index}",
                    "text": f"Article {index} ![image](https://cdn.example.test/pic.jpg)",
                    "success": True,
                }) + "\n")
        return path

    def test_inspect_and_merge_preserve_canonical_ids_without_image_links(self) -> None:
        first = self.write_shard(0, 1)
        self.write_shard(2, 2)
        self.assertEqual(local_range.inspect_shard(first, 0, 1), (2, 0))

        merged = local_range.merge_shards(0, 2, 2)
        rows = [json.loads(line) for line in merged.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["id"] for row in rows], [501, 502, 503])
        self.assertEqual([row["row_index"] for row in rows], [0, 1, 2])
        self.assertTrue(all("https://cdn" not in row["text"] for row in rows))

    def test_incomplete_shard_is_not_accepted(self) -> None:
        path = self.write_shard(0, 0)
        self.assertIsNone(local_range.inspect_shard(path, 0, 1))


if __name__ == "__main__":
    unittest.main()
