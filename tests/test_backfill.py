"""Offline coverage, identity, recovery, and source scheduling regression tests."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))
import backfill
from compact import compact
from fetch_policy import active_controller


class BackfillFixture:
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.parquet"
        self.baseline = self.root / "baseline.jsonl"
        self.campaign = self.root / "campaign"
        self.urls = [f"https://{'a' if i < 4 else 'b'}.test/{i}" for i in range(10)]
        # A repeated ID must not cause another row to be skipped.
        self.ids = [101, 101, *range(103, 111)]
        pq.write_table(pa.table({"id": self.ids, "url": self.urls}), self.source, row_group_size=3)

    def result(self, index: int, success: bool = True, **extra: object) -> dict[str, object]:
        value = {"row_index": index, "id": self.ids[index], "url": self.urls[index],
                 "text": f"Complete medical article number {index}" if success else "",
                 "success": success}
        if not success:
            value.update(error="HTTP 429", error_kind="rate_limited", next_retry_at=time() + 3600)
        return value | extra

    def prepare(self, present: tuple[int, ...] = (2, 9), min_gap: int = 1) -> dict[str, object]:
        self.baseline.write_text("".join(json.dumps(self.result(i)) + "\n" for i in present), encoding="utf-8")
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({host: {"concurrency": 1, "interval_seconds": 0, "cooldown_seconds": 60}
                                      for host in ("a.test", "b.test")}), encoding="utf-8")
        return backfill.prepare(self.source, self.baseline, self.campaign, min_gap, policy_file=policy)


class TestBackfill(BackfillFixture, unittest.TestCase):
    def test_select_only_large_gaps_across_parquet_groups(self) -> None:
        manifest = self.prepare(min_gap=3)
        self.assertEqual(manifest["ranges"], [(3, 8)])
        self.assertEqual(manifest["target_rows"], 6)
        self.assertEqual(manifest["missing_rows"], 8)
        with backfill.connect(self.campaign) as database:
            self.assertEqual([row[0] for row in database.execute("SELECT row_index FROM targets ORDER BY row_index")], list(range(3, 9)))

    def test_duplicate_ids_keep_independent_row_targets(self) -> None:
        self.prepare(present=(0, 9))
        with backfill.connect(self.campaign) as database:
            self.assertEqual(database.execute("SELECT id FROM targets WHERE row_index=1").fetchone()[0], 101)

    def test_wrong_mapping_and_unordered_baseline_are_rejected(self) -> None:
        for records in ([self.result(9, id=-1)], [self.result(9), self.result(2)]):
            self.baseline.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            with self.assertRaises(ValueError):
                backfill.prepare(self.source, self.baseline, self.campaign, 1)
            self.assertFalse(self.campaign.exists())

    def test_changed_inputs_are_rejected(self) -> None:
        manifest = self.prepare()
        self.baseline.write_text(json.dumps(self.result(8)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "baseline changed"):
            backfill.verify_inputs(manifest)

    def test_replay_preserves_success_after_failure_and_merge_is_sorted(self) -> None:
        manifest = self.prepare()
        baseline_before = self.baseline.read_bytes()
        journal = self.campaign / "results.jsonl"
        journal.write_text("".join(json.dumps(value) + "\n" for value in (
            self.result(8), self.result(1), self.result(1, False))), encoding="utf-8")
        with backfill.connect(self.campaign) as database:
            database.execute("UPDATE targets SET state='running' WHERE row_index=0")
            database.commit()
            backfill.reconcile(database, self.campaign)
            self.assertEqual(database.execute("SELECT state FROM targets WHERE row_index=0").fetchone()[0], "pending")
            self.assertEqual(database.execute("SELECT state FROM targets WHERE row_index=1").fetchone()[0], "success")
            backfill.reconcile(database, self.campaign)
            output = self.root / "merged.jsonl"
            stats = backfill.merge_campaign(self.campaign, database, manifest, output)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([row["row_index"] for row in rows], [1, 2, 8, 9])
            self.assertEqual(stats["new_successes"], 2)
            with self.assertRaises(FileExistsError):
                backfill.merge_campaign(self.campaign, database, manifest, output)
        self.assertEqual(self.baseline.read_bytes(), baseline_before)

    def test_ingest_unions_files_and_is_idempotent(self) -> None:
        manifest = self.prepare()
        files = []
        for index in (1, 8):
            path = self.root / f"delta-{index}.jsonl"
            path.write_text(json.dumps(self.result(index)) + "\n", encoding="utf-8")
            files.append(path)
        with backfill.connect(self.campaign) as database:
            self.assertEqual(backfill.ingest_files(self.campaign, database, manifest, files), 2)
            self.assertEqual(backfill.ingest_files(self.campaign, database, manifest, files), 0)
            self.assertEqual(backfill.campaign_report(database)["counts"]["success"], 2)

    def test_reject_outside_targets_wrong_identity_and_empty_success(self) -> None:
        self.prepare()
        with backfill.connect(self.campaign) as database:
            for value in (self.result(2), self.result(1, id=-1), self.result(1, text="![ ](https://image.test/x)")):
                with self.assertRaises(ValueError):
                    backfill.ingest_record(database, value, 0)

    def test_invalid_delta_does_not_append_partial_ingestion(self) -> None:
        manifest = self.prepare()
        path = self.root / "invalid.jsonl"
        path.write_text(json.dumps(self.result(1)) + "\n" + json.dumps(self.result(2)) + "\n")
        with backfill.connect(self.campaign) as database:
            with self.assertRaises(ValueError):
                backfill.ingest_files(self.campaign, database, manifest, [path])
            self.assertFalse((self.campaign / "results.jsonl").exists())
            self.assertEqual(backfill.campaign_report(database)["counts"], {"pending": 8})

    def test_unfetched_deferred_document_does_not_consume_round_budget(self) -> None:
        self.prepare()
        value = self.result(1, False, error_kind="deferred", campaign_attempt=0, attempts=0)
        with backfill.connect(self.campaign) as database:
            backfill.ingest_record(database, value, 0)
            self.assertEqual(database.execute("SELECT rounds FROM targets WHERE row_index=1").fetchone()[0], 0)

    def test_compact_does_not_replace_good_success_with_empty_cleaned_text(self) -> None:
        raw = self.root / "raw.jsonl"
        raw.write_text(json.dumps(self.result(0)) + "\n" + json.dumps(self.result(0, text="![](https://image.test/x)")) + "\n")
        output = self.root / "canonical.jsonl"
        _, success, failed = compact(self.source, raw, output, 0, 0)
        self.assertEqual((success, failed), (1, 0))
        self.assertEqual(json.loads(output.read_text())["text"], self.result(0)["text"])


class TestCampaignScheduler(BackfillFixture, unittest.IsolatedAsyncioTestCase):
    def runner_args(self, fetch_mode: str = "http") -> argparse.Namespace:
        return argparse.Namespace(campaign=self.campaign, group=[], pilot_per_host=0,
                                  http_concurrency=2, browser_concurrency=2, fetch_mode=fetch_mode,
                                  max_in_flight=4, max_rounds=3, limit=0,
                                  min_free_memory_gb=0, browser_recycle_after=300, wait_for_retries=False)

    async def test_blocked_host_does_not_stop_another_host(self) -> None:
        manifest = self.prepare(present=(9,))
        attempted = []

        class FakeCrawler:
            def __init__(self, **kwargs: object) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args: object):
                pass

        async def crawl(record, *_args):
            attempted.append(record.row_index)
            await asyncio.sleep(0)
            if record.row_index < 4:
                controller = active_controller.get()
                controller.observe(record.url, 429, "HTTP 429", "3600")
                value = self.result(record.row_index, False, source_retry_at=controller.retry_at(record.url))
            else:
                value = self.result(record.row_index)
            return SimpleNamespace(payload=value, mode="http", attempts=1)

        args = argparse.Namespace(campaign=self.campaign, group=[], pilot_per_host=0,
                                  http_concurrency=2, browser_concurrency=1, fetch_mode="http",
                                  max_in_flight=4, max_rounds=3, limit=0,
                                  min_free_memory_gb=0, browser_recycle_after=300, wait_for_retries=False)
        with backfill.connect(self.campaign) as database, patch("crawl4ai.AsyncWebCrawler", FakeCrawler), patch("fetch.crawl_one", crawl), patch("http_strategy.create_http_strategy", return_value=object()), patch.object(backfill, "HOST_LOCK_DIRECTORY", self.root / "locks"):
            await backfill.run_campaign(args, database, manifest)
            self.assertEqual([i for i in attempted if i < 4], [0])
            self.assertEqual(sorted(i for i in attempted if i >= 4), list(range(4, 9)))
            self.assertEqual(backfill.campaign_report(database)["counts"]["success"], 5)
            self.assertEqual(database.execute("SELECT state FROM targets WHERE row_index=1").fetchone()[0], "pending")

    async def test_single_host_fills_its_concurrency_budget(self) -> None:
        manifest = self.prepare(present=(9,))
        manifest["policies"]["a.test"]["concurrency"] = 2
        running = peak = 0

        class FakeCrawler:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

        async def crawl(record, *_args):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return SimpleNamespace(payload=self.result(record.row_index), mode="http", attempts=1)

        args = self.runner_args()
        args.group = ["a.test"]
        with backfill.connect(self.campaign) as database, patch("crawl4ai.AsyncWebCrawler", FakeCrawler), patch("fetch.crawl_one", crawl), patch("http_strategy.create_http_strategy", return_value=object()), patch.object(backfill, "HOST_LOCK_DIRECTORY", self.root / "locks"):
            await backfill.run_campaign(args, database, manifest)
            self.assertEqual(peak, 2)

    async def test_browser_recovery_keeps_http_pool_and_unfinished_rows(self) -> None:
        manifest = self.prepare(present=(9,))
        crawlers = []

        class FakeCrawler:
            def __init__(self, **kwargs):
                self.kind = "http" if "crawler_strategy" in kwargs else "browser"
                self.generation = 1 + sum(c.kind == self.kind for c in crawlers)
                crawlers.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

        async def crawl(record, browser, *_args):
            await asyncio.sleep(0)
            if browser.generation == 1:
                value = self.result(record.row_index, False, error="BrowserContext.new_page: Connection closed")
            else:
                value = self.result(record.row_index)
            return SimpleNamespace(payload=value, mode="browser", attempts=1)

        with backfill.connect(self.campaign) as database, patch("crawl4ai.AsyncWebCrawler", FakeCrawler), patch("fetch.crawl_one", crawl), patch("http_strategy.create_http_strategy", return_value=object()), patch.object(backfill, "HOST_LOCK_DIRECTORY", self.root / "locks"):
            await backfill.run_campaign(self.runner_args("auto"), database, manifest)
            self.assertEqual(sum(c.kind == "http" for c in crawlers), 1)
            self.assertEqual(sum(c.kind == "browser" for c in crawlers), 2)
            self.assertEqual(backfill.campaign_report(database)["counts"], {"success": 9})

    async def test_host_rotation_within_shared_group(self) -> None:
        self.urls = [f"https://{('baby', 'care', 'ask')[min(i // 3, 2)]}.39.net/{i}" for i in range(10)]
        pq.write_table(pa.table({"id": self.ids, "url": self.urls}), self.source)
        manifest = self.prepare(present=(9,))
        hosts = []

        class FakeCrawler:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

        async def crawl(record, *_args):
            hosts.append(backfill.hostname(record.url))
            await asyncio.sleep(0)
            return SimpleNamespace(payload=self.result(record.row_index), mode="http", attempts=1)

        args = self.runner_args()
        args.limit = 3
        with backfill.connect(self.campaign) as database, patch("crawl4ai.AsyncWebCrawler", FakeCrawler), patch("fetch.crawl_one", crawl), patch("http_strategy.create_http_strategy", return_value=object()), patch.object(backfill, "HOST_LOCK_DIRECTORY", self.root / "locks"):
            await backfill.run_campaign(args, database, manifest)
            self.assertEqual(set(hosts), {"baby.39.net", "care.39.net", "ask.39.net"})

    async def test_host_filter_preserves_unselected_rows(self) -> None:
        manifest = self.prepare(present=(9,))
        requested = []

        class FakeCrawler:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

        async def crawl(record, *_args):
            requested.append(record.row_index)
            return SimpleNamespace(payload=self.result(record.row_index), mode="http", attempts=1)

        args = self.runner_args()
        args.host = ["b.test"]
        args.limit = 2
        with backfill.connect(self.campaign) as database, patch("crawl4ai.AsyncWebCrawler", FakeCrawler), patch("fetch.crawl_one", crawl), patch("http_strategy.create_http_strategy", return_value=object()), patch.object(backfill, "HOST_LOCK_DIRECTORY", self.root / "locks"):
            await backfill.run_campaign(args, database, manifest)
            self.assertEqual(requested, [4, 5])


if __name__ == "__main__":
    unittest.main()
