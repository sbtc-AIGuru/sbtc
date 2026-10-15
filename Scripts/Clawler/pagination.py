"""Collect all pages of a Wujue article without retaining navigation links."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag


MAX_ARTICLE_PAGES = 40
PAGE_SUFFIX_RE = re.compile(r"(?:_\d+)?\.html$", re.IGNORECASE)


def _article_path(url: str) -> str | None:
    path = urlsplit(url).path
    if not PAGE_SUFFIX_RE.search(path):
        return None
    return PAGE_SUFFIX_RE.sub("", path)


def wujue_page_number(url: str) -> int:
    """Return 1 for the canonical URL or its numbered suffix."""
    match = re.search(r"_(\d+)\.html$", urlsplit(url).path, re.IGNORECASE)
    return int(match.group(1)) if match else 1


def wujue_first_page_url(url: str) -> str:
    """Map an article subpage back to its first page."""
    parsed = urlsplit(url)
    stem = _article_path(url)
    if stem is None:
        return url
    return urlunsplit((parsed.scheme, parsed.netloc, f"{stem}.html", "", ""))


def wujue_page_links(url: str, html: str) -> dict[int, str]:
    """Find numbered links belonging to the same article, including later groups."""
    stem = _article_path(url)
    if stem is None:
        return {}
    pattern = re.compile(rf"^{re.escape(stem)}_(\d+)\.html$", re.IGNORECASE)
    hostname = urlsplit(url).hostname
    soup = BeautifulSoup(html, "lxml")
    links: dict[int, str] = {}
    for anchor in soup.select("#article-main_left .art-text a[href]"):
        target = urljoin(url, str(anchor["href"]))
        parsed = urlsplit(target)
        match = pattern.fullmatch(parsed.path)
        if parsed.hostname == hostname and match is not None:
            page_number = int(match.group(1))
            if page_number > 1:
                links[page_number] = target
    return links


def remove_wujue_pager(body: Tag) -> None:
    """Drop the numbered next/previous-page control from an article body."""
    for paragraph in body.select("p"):
        anchors = paragraph.select("a[href]")
        if not anchors:
            continue
        label = paragraph.get_text(" ", strip=True)
        if (
            any("下一页" in anchor.get_text() or "上一页" in anchor.get_text() for anchor in anchors)
            or (len(anchors) >= 2 and re.search(r"\[\d+\]", label))
        ) and any(re.search(r"_\d+\.html", str(anchor.get("href", ""))) for anchor in anchors):
            paragraph.decompose()


def wujue_page_markdown(url: str, html: str, include_title: bool) -> str:
    """Convert the selected article region through Crawl4AI's Markdown generator."""
    from crawl4ai import DefaultMarkdownGenerator

    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one("#article-main_left .main_articletitle h1")
    body = soup.select_one("#article-main_left .art-text")
    if title is None or body is None:
        raise ValueError(f"Missing Wujue article region on {url}")
    remove_wujue_pager(body)
    article_html = (str(title) if include_title else "") + str(body)
    generated = DefaultMarkdownGenerator().generate_markdown(
        article_html, base_url=url, citations=False
    )
    return generated.raw_markdown.strip()
