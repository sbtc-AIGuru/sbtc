"""Offline tests for shared quotas, cancellation, and cooldown semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import sys
from time import monotonic, time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))
from fetch_policy import DeferredRequest, FetchController, HostPolicy, retry_after_seconds


class TestPolicy(unittest.IsolatedAsyncioTestCase):
    def test_stale_interval_recovers_after_twenty_healthy_responses(self) -> None:
        controller = FetchController({"a.test": HostPolicy(interval_seconds=1)})
        state, _ = controller.state("https://a.test/article")
        state.interval = 60
        for _ in range(20):
            controller.observe("https://a.test/article", 200, "", None)
        self.assertEqual(state.interval, 48)
        for _ in range(500):
            controller.observe("https://a.test/article", 200, "", None)
        self.assertEqual(state.interval, 1)

    def test_adaptive_ramp_has_a_floor_and_denial_restores_slow_start(self) -> None:
        policy = HostPolicy(interval_seconds=1.5, minimum_interval_seconds=0.3)
        controller = FetchController({"a.test": policy})
        state, _ = controller.state("https://a.test/article")
        for _ in range(200):
            controller.observe("https://a.test/article", 200, "", None)
        self.assertEqual(state.interval, 0.3)
        controller.observe("https://a.test/article", 429, "HTTP 429", "7200")
        self.assertEqual(state.interval, 3)
        self.assertGreaterEqual(controller.retry_at("https://a.test/article") - time(), 7199)

    def test_invalid_content_does_not_advance_healthy_recovery(self) -> None:
        controller = FetchController({"a.test": HostPolicy(interval_seconds=1)})
        state, _ = controller.state("https://a.test/article")
        state.interval = 60
        for _ in range(19):
            controller.observe("https://a.test/article", 200, "", None)
        controller.observe("https://a.test/article", 200, "Empty Markdown", None)
        controller.observe("https://a.test/article", 200, "", None)
        self.assertEqual(state.interval, 60)
        self.assertEqual(state.healthy, 1)

    def test_invalid_ramp_policy_is_rejected(self) -> None:
        for value in (-1, 2, float("nan"), "fast", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HostPolicy(interval_seconds=1, minimum_interval_seconds=value)
        with self.assertRaises(ValueError):
            HostPolicy(recovery_successes=0)

    def test_retry_after_both_formats_and_invalid_value(self) -> None:
        self.assertEqual(retry_after_seconds("7200", now=1000), 7200)
        date = format_datetime(datetime.fromtimestamp(8200, timezone.utc), usegmt=True)
        self.assertEqual(retry_after_seconds(date, now=1000), 7200)
        self.assertIsNone(retry_after_seconds("not a date"))

    async def test_subdomains_share_spacing_and_host_slots(self) -> None:
        policy = HostPolicy(2, 0.03, 0, "39.net")
        controller = FetchController({"baby.39.net": policy, "ask.39.net": policy})
        starts = []
        host_active = {}
        peak = 0

        async def request(url):
            nonlocal peak
            async with controller.request(url):
                starts.append(monotonic())
                host_active[url] = host_active.get(url, 0) + 1
                peak = max(peak, host_active[url])
                await asyncio.sleep(0.04)
                host_active[url] -= 1

        with patch("fetch_policy.random.uniform", return_value=1):
            await asyncio.gather(request("https://baby.39.net/a"), request("https://baby.39.net/a"), request("https://ask.39.net/a"))
        self.assertEqual(peak, 1)
        self.assertTrue(all(b - a >= 0.025 for a, b in zip(starts, starts[1:])))

    async def test_cooldown_rejects_same_group_but_allows_other_host(self) -> None:
        controller = FetchController()
        controller.observe("https://baby.39.net/a", 429, "HTTP 429", "7200")
        self.assertGreaterEqual(controller.retry_at("https://ask.39.net/a") - time(), 7199)
        with self.assertRaises(DeferredRequest):
            async with controller.request("https://ask.39.net/a"):
                self.fail("Cooling source must not be fetched")
        async with controller.request("https://other.test/a"):
            pass

    async def test_cancellation_releases_admission_slot(self) -> None:
        controller = FetchController({"a.test": HostPolicy(1, 0, 0)})
        entered = asyncio.Event()

        async def request():
            async with controller.request("https://a.test/a"):
                entered.set()
                await asyncio.sleep(100)

        task = asyncio.create_task(request())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async with controller.request("https://a.test/b"):
            pass

    async def test_pacing_wait_does_not_occupy_global_slot(self) -> None:
        controller = FetchController({"a.test": HostPolicy(1, 0, 0)})
        semaphore = asyncio.Semaphore(1)
        state, _ = controller.state("https://a.test/a")
        state.next_start = monotonic() + 10

        async def waiting_request():
            async with controller.request("https://a.test/a", semaphore):
                self.fail("Paced request must still be waiting")

        task = asyncio.create_task(waiting_request())
        await asyncio.sleep(0.01)
        async with asyncio.timeout(0.5):
            async with controller.request("https://b.test/a", semaphore):
                self.assertTrue(semaphore.locked())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(semaphore.locked())
        self.assertEqual(state.active, 0)

    async def test_global_slot_is_released_on_cancellation(self) -> None:
        controller = FetchController({"a.test": HostPolicy(1, 0, 0)})
        semaphore = asyncio.Semaphore(1)
        entered = asyncio.Event()

        async def request():
            async with controller.request("https://a.test/a", semaphore):
                entered.set()
                await asyncio.sleep(100)

        task = asyncio.create_task(request())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(semaphore.locked())
        self.assertEqual(controller.state("https://a.test/a")[0].active, 0)

    def test_conflicting_group_overrides_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FetchController({"baby.39.net": HostPolicy(group="39.net"), "ask.39.net": HostPolicy(1, group="39.net")})

    def test_repeated_server_errors_pause_the_source(self) -> None:
        controller = FetchController()
        for _ in range(3):
            controller.observe("https://article.iiyi.com/a", 521, "Origin unavailable", None)
        self.assertGreater(controller.state("https://article.iiyi.com/b")[0].cooldown_until, monotonic() + 449)

    def test_repeated_transport_timeouts_pause_only_that_source(self) -> None:
        controller = FetchController()
        for _ in range(3):
            controller.observe("https://a.test/article", None, "TimeoutError", None)
        self.assertGreater(controller.retry_at("https://a.test/other") - time(), 299)
        self.assertLess(controller.retry_at("https://b.test/other") - time(), 1)

    def test_denial_backoff_grows_without_shortening_retry_after(self) -> None:
        controller = FetchController({"a.test": HostPolicy(cooldown_seconds=10)})
        with patch("fetch_policy.monotonic", return_value=100):
            for expected in (110, 120, 140, 180, 260, 260):
                controller.observe("https://a.test/article", 403, "HTTP 403", None)
                self.assertEqual(controller.state("https://a.test/article")[0].cooldown_until, expected)
            controller.observe("https://a.test/article", 429, "HTTP 429", "7200")
            self.assertGreaterEqual(controller.state("https://a.test/article")[0].cooldown_until, 7300)


if __name__ == "__main__":
    unittest.main()
