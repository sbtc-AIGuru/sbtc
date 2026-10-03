"""Checks that HTTP-fetched pages contain the complete configured article."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from pagination import remove_wujue_pager


ARTICLE_LAYOUTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "120ask.com": (("#d_askH1", ("#d_msCon", ".b_answerbox .b_answerli .b_anscont_cont")),),
    "cnkang.com": (
        (".detail h1.detaila", (".detail .detailc",)),
        ("#wleft .endContent h1", ("#endText",)),
    ),
    "wujue.com": (("#article-main_left .main_articletitle h1", ("#article-main_left .art-text",)),),
    "baocantho.com.vn": (("#colcate1 > h1", ("#newscontents",)),),
}
MIN_BODY_CHARACTERS = 40
EXCERPT_CHARACTERS = 30


def normalized_text(value: str) -> str:
    """Remove markup punctuation and whitespace for HTML/Markdown comparison."""
    return "".join(character.lower() for character in value if character.isalnum())


def _content_in_markdown(element: Tag, markdown: str) -> bool:
    source = normalized_text(element.get_text(" ", strip=True))
    if not source:
        return False
    if len(source) <= EXCERPT_CHARACTERS:
        return source in markdown
    last_start = len(source) - EXCERPT_CHARACTERS
    positions = sorted({0, last_start, *(last_start * step // 4 for step in range(1, 4))})
    present = [
        source[position : position + EXCERPT_CHARACTERS] in markdown
        for position in positions
    ]
    return (
        present[0]
        and present[-1]
        and sum(present) >= min(4, len(present))
        and len(markdown) >= len(source) * 0.8
    )


def http_article_error(domain: str, result: object, text: str) -> str | None:
    """Reject incomplete HTTP articles so the browser can retry that URL."""
    layouts = ARTICLE_LAYOUTS.get(domain)
    if layouts is None:
        return f"HTTP article layout is not configured for {domain}"
    html = getattr(result, "html", None)
    if not isinstance(html, str) or not html:
        return "HTTP response has no HTML"
    markdown = normalized_text(text)
    if len(markdown) < MIN_BODY_CHARACTERS:
        return "HTTP Markdown is too short for an article"

    soup = BeautifulSoup(html, "lxml")
    if domain == "wujue.com":
        for body in soup.select("#article-main_left .art-text"):
            remove_wujue_pager(body)
    for title_selector, body_selectors in layouts:
        title = soup.select_one(title_selector)
        if title is None:
            continue
        title_text = normalized_text(title.get_text(" ", strip=True))
        if not title_text or title_text not in markdown:
            continue
        bodies = [soup.select(selector) for selector in body_selectors]
        if any(not elements for elements in bodies):
            continue
        if all(
            _content_in_markdown(element, markdown)
            for elements in bodies
            for element in elements
        ):
            return None
    return "HTTP Markdown is missing the title or part of the article body"
