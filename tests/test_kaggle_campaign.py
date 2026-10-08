"""Sparse Kaggle export identity, isolation and checkpoint regressions."""

import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))

from backfill import connect, initialize_campaign_database
from kaggle_campaign import (
    balanced_host_partition, initialize_worker, load_shard, prepare_export, verify_source_rows,
)
from test_backfill import BackfillFixture


class TestHostPartition(unittest.TestCase):
    def test_equal_shards_have_disjoint_hosts_and_complete_coverage(self):
        rows = [{"row_index": i, "host": host} for i, host in enumerate(
            ["a.test"] * 4 + ["b.test"] * 3 + ["c.test"] * 2 + ["d.test"])]
        a, b = balanced_host_partition(rows)
        self.assertEqual((len(a), len(b)), (5, 5))
        self.assertFalse({r["host"] for r in a} & {r["host"] for r in b})
        self.assertEqual({r["row_index"] for r in a + b}, set(range(10)))

    def test_impossible_exact_host_split_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "disjoint hostnames"):
            balanced_host_partition([{"host": "a.test"}] * 6)


class TestExport(BackfillFixture, unittest.TestCase):
    def test_export_is_exact_tail_private_and_does_not_modify_parent(self):
        for index in range(5, 9):
            self.urls[index] = f"https://{index}.test/{index}"
        pq.write_table(pa.table({"id": self.ids, "url": self.urls}), self.source, row_group_size=3)
        self.prepare(present=(9,))
        output = self.root / "export"
        with connect(self.campaign) as db:
            db.execute("UPDATE targets SET state='success' WHERE row_index=4")
            db.execute("UPDATE targets SET state='running' WHERE row_index=5")
        before = (self.campaign / "state.sqlite3").read_bytes()
        export = prepare_export(self.campaign, output, "testowner", count=4)
        self.assertEqual(export["selected_count"], 4)
        selected = []
        for shard in export["shards"]:
            metadata, definition, rows = load_shard(output / "dataset", shard["shard_id"])
            selected.extend(rows)
            self.assertEqual(len(rows), 2)
            kernel = json.loads((output / f"notebook-{shard['shard_id']}/kernel-metadata.json").read_text())
            self.assertEqual(kernel["kernel_type"], "notebook")
            self.assertTrue(kernel["is_private"])
            self.assertTrue(kernel["enable_internet"])
            self.assertEqual(kernel["dataset_sources"], [export["dataset"]])
        self.assertEqual(sorted(r["row_index"] for r in selected), [5, 6, 7, 8])
        self.assertEqual((self.campaign / "state.sqlite3").read_bytes(), before)
        self.assertFalse((output / "dataset" / "baseline.jsonl").exists())

    def test_source_verification_rejects_wrong_global_mapping(self):
        self.prepare()
        rows = [{"row_index": 1, "id": self.ids[1], "url": self.urls[1]},
                {"row_index": 8, "id": self.ids[8], "url": self.urls[8]}]
        verify_source_rows(self.source, rows)
        rows[1]["url"] = "https://wrong.test/article"
        with self.assertRaisesRegex(ValueError, "mapping mismatch"):
            verify_source_rows(self.source, rows)

    def test_worker_skips_local_completed_rows_preserves_indices_and_resumes(self):
        self.prepare(present=(9,))
        # Select two a.test and two b.test slots so host-disjoint halves exist.
        with connect(self.campaign) as db:
            db.execute("DELETE FROM targets WHERE row_index IN (4,5,6)")
            db.execute("UPDATE targets SET state='success' WHERE row_index=7")
            db.execute("UPDATE targets SET state='permanent_failure' WHERE row_index=8")
        output = self.root / "export"
        export = prepare_export(self.campaign, output, "testowner", count=4)
        for shard in export["shards"]:
            work = self.root / f"work-{shard['shard_id']}"
            manifest = initialize_worker(output / "dataset", shard["shard_id"], work)
            with connect(work) as db:
                indices = [r[0] for r in db.execute("SELECT row_index FROM targets ORDER BY row_index")]
                states = dict(db.execute("SELECT state,COUNT(*) FROM targets GROUP BY state"))
                self.assertEqual(len(indices), 2)
                if indices == [7, 8]:
                    self.assertEqual(states, {"local_permanent_failure": 1, "local_success": 1})
                self.assertEqual(manifest, initialize_worker(output / "dataset", shard["shard_id"], work))
            if indices == [7, 8]:
                self.assertEqual(manifest["policies"]["b.test"]["concurrency"], 1)
        bundle = output / "dataset"
        shard = export["shards"][0]
        (bundle / shard["file"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_shard(bundle, shard["shard_id"])


if __name__ == "__main__":
    unittest.main()
