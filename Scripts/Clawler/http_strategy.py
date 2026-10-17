"""Keep denial status and Retry-After headers that upstream HTTP exceptions lose."""

from __future__ import annotations

import asyncio
from html import escape
import re

from aiohttp import ClientTimeout
from bs4 import BeautifulSoup
import chardet
from crawl4ai import CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.models import AsyncCrawlResponse


MAX_RESPONSE_BYTES = 10 * 1024 * 1024
USER_AGENT = "SBTCResearchCrawler/1.0"
XML_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
IMAGE_HEADING_PATTERN = re.compile(r"(<h1\b[^>]*>)\s*(<img\b[^>]*>)\s*(</h1>)", re.IGNORECASE)


def repair_empty_html_root(html: str) -> str:
    """Repair a premature empty root before head without altering article content."""
    # Some Tay Ninh responses close an empty html element before the real
    # head/body. lxml then discards the article; browsers repair this markup.
    return re.sub(r"(\A\s*(?:<!DOCTYPE[^>]*>\s*)?<html\b[^>]*>\s*)</html>(?=\s*<head\b)", r"\1", html,
                  count=1, flags=re.IGNORECASE)


def normalize_response_html(html: str) -> str:
    """Repair parser hazards and retain source image-alt titles as visible text."""
    def restore_heading(match: re.Match[str]) -> str:
        tag = BeautifulSoup(match[2], "lxml").find("img")
        alt = tag.get("alt", "") if tag is not None else ""
        if not alt.strip():
            return match[0]
        return match[1] + escape(alt) + match[3]

    html = repair_empty_html_root(XML_CONTROL_PATTERN.sub("", html))
    return IMAGE_HEADING_PATTERN.sub(restore_heading, html)


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
                    html = normalize_response_html(html)
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
