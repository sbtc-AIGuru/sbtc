"""Real loopback HTTP checks for status/header retention and browser validation."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic
import unittest

from aiohttp import web
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts/Clawler"))
from fetch import crawl_one
from fetch_policy import FetchController, HostPolicy, active_controller
from http_strategy import USER_AGENT, create_http_strategy
from utils import SourceRecord


class TestHTTPStrategy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.calls = 0

        async def denied(_request):
            self.calls += 1
            return web.Response(status=429, text="Too many requests", headers={"Retry-After": "7200"})

        async def missing(_request):
            self.calls += 1
            return web.Response(status=404, text="Missing")

        async def dynamic(_request):
            return web.Response(text="""<html><body><main id='content'></main><script>
                document.getElementById('content').innerHTML = '<h1>Medical information</h1><article>' +
                'A complete medical article explains treatment options and appropriate follow-up care. '.repeat(5) + '</article>';
                </script></body></html>""", content_type="text/html")

        app = web.Application()
        app.router.add_get("/rate", denied)
        app.router.add_get("/gone", missing)
        app.router.add_get("/dynamic", dynamic)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.addAsyncCleanup(self.runner.cleanup)

    async def test_real_429_preserves_header_and_does_not_use_browser(self) -> None:
        controller = FetchController({"127.0.0.1": HostPolicy(1, 0, 0)})
        token = active_controller.set(controller)
        self.addCleanup(active_controller.reset, token)
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False, user_agent=USER_AGENT)
        url = self.base_url + "/rate"
        async with AsyncWebCrawler(crawler_strategy=create_http_strategy(), base_directory=self.temporary.name) as http:
            result = await crawl_one(SourceRecord(0, 101, url), None, http,
                                     asyncio.Semaphore(1), asyncio.Semaphore(1), config, {}, "auto")
        self.assertFalse(result.payload["success"])
        self.assertEqual(result.payload["status_code"], 429)
        self.assertEqual(result.payload["error_kind"], "rate_limited")
        self.assertEqual(self.calls, 1)
        self.assertFalse(result.used_fallback)
        self.assertGreater(controller.state(url)[0].cooldown_until, monotonic() + 7199)

    async def test_real_404_is_terminal(self) -> None:
        url = self.base_url + "/gone"
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False, user_agent=USER_AGENT)
        async with AsyncWebCrawler(crawler_strategy=create_http_strategy(), base_directory=self.temporary.name) as http:
            result = await crawl_one(SourceRecord(0, 101, url), None, http,
                                     asyncio.Semaphore(1), asyncio.Semaphore(1), config, {}, "auto")
        self.assertEqual(result.payload["error_kind"], "not_found")
        self.assertEqual(self.calls, 1)

    async def test_dynamic_article_uses_browser_and_passes_shared_validation(self) -> None:
        url = self.base_url + "/dynamic"
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False,
                                  wait_for="css:#content h1", page_timeout=10000, user_agent=USER_AGENT)
        async with AsyncWebCrawler(crawler_strategy=create_http_strategy(), base_directory=self.temporary.name) as http:
            async with AsyncWebCrawler(config=BrowserConfig(headless=True, text_mode=True, verbose=False), base_directory=self.temporary.name) as browser:
                result = await crawl_one(SourceRecord(0, 101, url), browser, http,
                                         asyncio.Semaphore(1), asyncio.Semaphore(1), config, {}, "auto")
        self.assertTrue(result.payload["success"], result.payload.get("error"))
        self.assertEqual(result.mode, "browser")
        self.assertIn("appropriate follow-up care", result.payload["text"])


if __name__ == "__main__":
    unittest.main()
