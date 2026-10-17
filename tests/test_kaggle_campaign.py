"""Sparse Kaggle export identity, isolation and checkpoint regressions."""

import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))

from backfill import connect, reconcile
from fetch_policy import HostPolicy
from kaggle_campaign import (
    balanced_host_partition, initialize_worker, load_shard, notebook_document,
    prepare_export, remote_policy, run_worker, verify_source_rows,
)
from test_backfill import BackfillFixture


class TestHostPartition(unittest.TestCase):
    def test_shared_remote_budget_and_browser_sources(self):
        policy = remote_policy("baby.39.net", HostPolicy(2, 3, 900, "39.net"), 2, True)
        self.assertEqual(policy.concurrency, 4)
        self.assertEqual(policy.interval_seconds, 1.5)
        self.assertAlmostEqual(policy.minimum_interval_seconds, 0.3)
        self.assertEqual(policy.max_attempts, 1)
        self.assertEqual(policy, remote_policy("ask.39.net", HostPolicy(2, 3, 900, "39.net"), 2, True))
        longchau = remote_policy("nhathuoclongchau.com.vn", HostPolicy(), 1, True)
        self.assertEqual(longchau.fetch_mode, "browser")
        self.assertEqual(longchau.concurrency, 1)

    def test_notebook_uses_eleven_hours_retained_pilot_and_temporary_environment(self):
        doc = notebook_document(2, "dataset", "export")
        setup, run = [cell["source"] for cell in doc["cells"] if cell["cell_type"] == "code"]
        self.assertIn('/tmp/crawler-venv-2', setup)
        self.assertIn('--without-pip', setup)
        self.assertIn('--pilot-per-host', run)
        self.assertIn("'11.0'", run)
        self.assertIn('coverage_complete', run)
        for cell in doc['cells']:
            if cell['cell_type'] == 'code':
                compile(cell['source'], 'notebook', 'exec')

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
    def test_relaunch_retains_progress_and_newer_local_success(self):
        self.urls[5:9] = ['https://a.test/5', 'https://a.test/6', 'https://b.test/7', 'https://b.test/8']
        pq.write_table(pa.table({'id': self.ids, 'url': self.urls}), self.source)
        self.prepare(present=(9,))
        old = self.root / 'old'
        previous = prepare_export(self.campaign, old, 'owner', count=4)
        journals = self.root / 'journals'
        for part, index, success in ((1, 5, True), (2, 7, False)):
            destination = journals / f'part-{part}'
            destination.mkdir(parents=True)
            value = self.result(index, success, campaign_id=previous['campaign_id'],
                                export_id=previous['export_id'], shard_id=part, campaign_attempt=1)
            (destination / 'results.jsonl').write_text(json.dumps(value) + '\n')
            attempt = {'row_index': index, 'id': self.ids[index], 'source_url': self.urls[index],
                       'request_url': self.urls[index], 'elapsed_seconds': 1, 'mode': 'http',
                       'error_kind': 'success' if success else 'rate_limited'}
            (destination / 'attempts.jsonl').write_text(json.dumps(attempt) + '\n')
        with connect(self.campaign) as db:
            db.execute("UPDATE targets SET state='success' WHERE row_index=7")
            db.execute("UPDATE targets SET state='running' WHERE row_index=8")
        output = self.root / 'relaunch'
        metadata = prepare_export(self.campaign, output, 'owner', count=4,
                                  resume_from=old, resume_outputs=journals)
        self.assertEqual(metadata['source_export_id'], previous['export_id'])
        self.assertNotEqual(metadata['export_id'], previous['export_id'])
        for part in (1, 2):
            work = self.root / f'work-{part}'
            manifest = initialize_worker(output / 'dataset', part, work)
            self.assertEqual(manifest['resumed_records'], 1)
            self.assertEqual(manifest['pacing_scope'], 'session')
            with connect(work) as db:
                reconcile(db, work)
                states = dict(db.execute('SELECT row_index,state FROM targets'))
            if part == 1:
                self.assertEqual(states[5], 'success')
                self.assertEqual(manifest['resumed_success'], 1)
            else:
                self.assertEqual(states[7], 'local_success')
                self.assertEqual(states[8], 'local_running')
            journal = (work / 'results.jsonl').read_bytes()
            initialize_worker(output / 'dataset', part, work)
            self.assertEqual((work / 'results.jsonl').read_bytes(), journal)
        # Another relaunch accepts both inherited and newly appended records,
        # while still validating exact row identities and export ancestry.
        next_journals = self.root / 'next-journals'
        for part in (1, 2):
            destination = next_journals / f'part-{part}'
            destination.mkdir(parents=True)
            for name in ('results.jsonl', 'attempts.jsonl'):
                (destination / name).write_bytes((self.root / f'work-{part}' / name).read_bytes())
        value = self.result(6, True, campaign_id=metadata['campaign_id'],
                            export_id=metadata['export_id'], shard_id=1, campaign_attempt=1)
        with (next_journals / 'part-1/results.jsonl').open('a') as handle:
            handle.write(json.dumps(value) + '\n')
        next_output = self.root / 'next-relaunch'
        next_metadata = prepare_export(self.campaign, next_output, 'owner', count=4,
                                       resume_from=output, resume_outputs=next_journals)
        self.assertEqual(set(next_metadata['source_export_ids']), {previous['export_id'], metadata['export_id']})
        manifest = initialize_worker(next_output / 'dataset', 1, self.root / 'next-worker')
        self.assertEqual(manifest['resumed_success'], 2)

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


class TestSessionCheckpoint(BackfillFixture, unittest.IsolatedAsyncioTestCase):
    async def test_timeout_preserves_checkpoint_and_reports_partial_coverage(self):
        self.prepare(present=(9,))
        with connect(self.campaign) as db:
            db.execute('DELETE FROM targets WHERE row_index IN (4,5,6)')
        output = self.root / 'export'
        prepare_export(self.campaign, output, 'owner', count=4)
        args = argparse.Namespace(bundle=output / 'dataset', shard=1, work=self.root / 'worker',
                                  max_rounds=4, wall_hours=0.00001, limit=0, pilot_per_host=0)

        async def slow_run(*_args):
            await asyncio.sleep(60)

        with patch('kaggle_campaign.run_campaign', slow_run):
            await run_worker(args)
        report = json.loads((args.work / 'report.json').read_text())
        self.assertEqual(report['stop_reason'], 'session_time_limit')
        self.assertFalse(report['coverage_complete'])
        self.assertEqual(report['remaining_remote'], 2)
        self.assertEqual(report['new_success'], 0)
        with zipfile.ZipFile(args.work / 'checkpoint.zip') as archive:
            self.assertIn('state.sqlite3', archive.namelist())
            self.assertEqual(json.loads(archive.read('report.json')), report)


if __name__ == "__main__":
    unittest.main()
