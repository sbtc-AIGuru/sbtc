"""Offline checks for domain-aware Kaggle scheduling."""

from __future__ import annotations

import argparse
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

import krun_sources


class TestKrunSources(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source.parquet"
        pq.write_table(
            pa.table({
                "id": [100, 101, 102, 103, 104],
                "url": [
                    "https://a.test/0", "https://a.test/1", "https://b.test/2",
                    "https://c.test/3", "https://c.test/4",
                ],
            }),
            self.source,
        )
        for name, value in (
            ("INPUT", self.source),
            ("PROJECT_ROOT", self.root),
            ("JOB_DIR", self.root / ".krun/jobs"),
        ):
            patcher = patch.object(krun_sources, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_source_ranges_split_on_hostname(self) -> None:
        self.assertEqual(
            krun_sources.source_ranges(1, 4),
            [(1, 1, "a.test"), (2, 2, "b.test"), (3, 4, "c.test")],
        )

    def test_quality_hold_defers_source_and_continues(self) -> None:
        args = argparse.Namespace(start=0, end=4, poll_seconds=1)

        def run_cycle(source_args: argparse.Namespace, _validated: Path) -> bool:
            if source_args.start == 2:
                raise krun_sources.QualityHold("blocked")
            return True

        with patch.object(krun_sources, "run_cycle", side_effect=run_cycle) as runner:
            deferred = krun_sources.run_sources(args)

        self.assertEqual(runner.call_count, 3)
        self.assertEqual(deferred["2-2"], {"domain": "b.test", "reason": "blocked"})
        manifest = self.root / ".krun/crawl_sources_0_4_deferred.json"
        self.assertEqual(json.loads(manifest.read_text()), deferred)


if __name__ == "__main__":
    unittest.main()
