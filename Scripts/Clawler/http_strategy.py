"""Keep denial status and Retry-After headers that upstream HTTP exceptions lose."""

from __future__ import annotations

import asyncio

from aiohttp import ClientTimeout
import chardet
from crawl4ai import CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.models import AsyncCrawlResponse


MAX_RESPONSE_BYTES = 10 * 1024 * 1024
USER_AGENT = "SBTCResearchCrawler/1.0"


class HeaderAwareHTTPStrategy(AsyncHTTPCrawlerStrategy):
    """Reuse Crawl4AI's HTTP session and return headers for non-2xx responses."""

    def update_user_agent(self, user_agent: str) -> None:
        """Support AsyncWebCrawler's per-run identity override for HTTP too."""
        self.browser_config.headers = dict(self.browser_config.headers or {}) | {"User-Agent": user_agent}

    async def _handle_http(self, url: str, config: CrawlerRunConfig) -> AsyncCrawlResponse:
        async with self._session_context() as session:
            request_kwargs = {
                "timeout": ClientTimeout(total=(config.page_timeout or 30_000) / 1000,
                                         connect=10, sock_read=30),
                "allow_redirects": self.browser_config.follow_redirects,
                "max_redirects": 5,
                "ssl": self.browser_config.verify_ssl,
                "headers": dict(self._BASE_HEADERS) | dict(self.browser_config.headers or {}),
            }
            if config.proxy_config:
                request_kwargs["proxy"] = self._format_proxy_url(config.proxy_config)
            await self.hooks["before_request"](url, request_kwargs)
            try:
                async with session.request("GET", url, **request_kwargs) as response:
                    chunks = []
                    size = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise ValueError(f"Response exceeds {MAX_RESPONSE_BYTES} bytes")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    content_type = response.content_type.lower()
                    if 200 <= response.status < 300 and content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                        raise ValueError(f"Unsupported content type: {content_type}")
                    encoding = response.charset
                    if not encoding:
                        encoding = (await asyncio.to_thread(chardet.detect, raw[:65536])).get("encoding") or "utf-8"
                    try:
                        html = raw.decode(encoding, errors="replace")
                    except LookupError:
                        html = raw.decode("utf-8", errors="replace")
                    result = AsyncCrawlResponse(
                        html=html, response_headers=dict(response.headers),
                        status_code=response.status, redirected_url=str(response.url),
                    )
                    await self.hooks["after_request"](result)
                    return result
            except Exception as error:
                await self.hooks["on_error"](error)
                raise


def create_http_strategy() -> HeaderAwareHTTPStrategy:
    """Use a stable identity for HTTP and browser requests alike."""
    return HeaderAwareHTTPStrategy(browser_config=HTTPCrawlerConfig(headers={"User-Agent": USER_AGENT}))
