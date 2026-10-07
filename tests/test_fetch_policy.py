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

    def test_conflicting_group_overrides_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FetchController({"baby.39.net": HostPolicy(group="39.net"), "ask.39.net": HostPolicy(1, group="39.net")})

    def test_repeated_server_errors_pause_the_source(self) -> None:
        controller = FetchController()
        for _ in range(3):
            controller.observe("https://article.iiyi.com/a", 521, "Origin unavailable", None)
        self.assertGreater(controller.state("https://article.iiyi.com/b")[0].cooldown_until, monotonic() + 449)


if __name__ == "__main__":
    unittest.main()
