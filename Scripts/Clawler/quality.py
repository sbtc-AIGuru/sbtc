"""Checks that HTTP-fetched pages contain the complete configured article."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from pagination import remove_wujue_pager
from verbatim import clean_to_verbatim


ARTICLE_LAYOUTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "120ask.com": (("#d_askH1", ("#d_msCon", ".b_answerbox .b_answerli .b_anscont_cont")),),
    "bachmai.gov.vn": (("#content-post > h3.h3", ("#content-post > .content-editor",)),),
    "baoangiang.com.vn": ((".detail-title h1", ("#newscontents",)),),
    "cnkang.com": (
        (".detail h1.detaila", (".detail .detailc",)),
        (".endContent h1, h1#h1title, h1", ("#endText",)),
    ),
    "wujue.com": (("#article-main_left .main_articletitle h1", ("#article-main_left .art-text",)),),
    "baocantho.com.vn": (("#colcate1 > h1", ("#newscontents",)),),
    "suckhoedoisong.vn": (
        ("h1.detail-title, .detail-title, h1", (".detail-content",)),
    ),
    "suckhoeviet.org.vn": ((
        ".article-detail-body-right > h1",
        (".article-detail-body-right > .article-detail-desc",
         ".article-detail-body-right > .__MASTERCMS_CONTENT"),
    ),),
    "tamanhhospital.vn": ((
        ".post_info.box_detail_post .title",
        (".post_info.box_detail_post:has(> p)",),
    ),),
    "a-hospital.com": (
        ("h1.firstHeading, h1", ("#bodyContent",)),
        ("h1.firstHeading, h1", ("#content",)),
    ),
    "zhongyibaodian.net": (
        ("h1.firstHeading, h1", ("#bodyContent",)),
        ("h1.firstHeading, h1", ("#content",)),
    ),
    "suckhoecongdongonline.vn": (
        ("h1.article__title, h1", (".article__body, .cms-body",)),
    ),
    "phunusuckhoe.giadinhonline.vn": (
        (".single-post .post-title h1", ("#article-body",)),
    ),
    "baohaiphong.vn": (
        ("h1.c-detail-head__title", (".entry",)),
    ),
    "sggp.org.vn": (
        ("h1.article__title, h1", (".article__body",)),
    ),
    "dantri.com.vn": (
        (".title-page, h1", ("#articleContent",)),
    ),
    "39.net": (
        ("h1.ask_tit, .ask_tit, .art_left > h1, h1", (".ask_cont, .all_answer, .doc_ans, .art_left > .art_content, .art_content",)),
    ),
    "familydoctor.com.cn": (
        (".art-title h1, .title h1, h1.title, h1", (".art-content, .content, #content, .q-content",)),
    ),
    "youlai.cn": (
        (
            '[class*="mainContent--"] > [class*="title--"]',
            ('[class*="mainContent--"] [class*="textContent--"]',),
        ),
        ("h1.doc_title, h1.title, h1", (".doc_content, .article_content, .art_content, .content",)),
    ),
    "thanhnien.vn": (
        ("h1.detail-title, h1", (".detail-content, .detail-cmain",)),
    ),
    "vietnamnet.vn": (
        (".content-detail h1", (".content-detail .main-content",)),
    ),
    "vinmec.com": (
        (".post-detail .post-header h1", ("#main-article",)),
    ),
    "zydcd.com": (
        (".panel.panel-danger > .panel-heading h1", (".panel.panel-danger > .panel-body.info_txt:not(:empty)",)),
    ),
}
MIN_BODY_CHARACTERS = 40
EXCERPT_CHARACTERS = 25

UNIVERSAL_NOISE_SELECTORS = (
    "script, style, noscript, iframe, svg, nav, footer, aside, "
    ".breadcrumb, .breadcrumbs, .share, .social-share, .comment, .comments, "
    "#toc, .toc, .printfooter, #catlinks, #siteSub, #contentSub, #jump-to-nav, "
    ".related, .recommend, .ad, .ads, .detail-share, .detail-relate"
)


def normalized_text(value: str) -> str:
    """Remove markup punctuation and whitespace for HTML/Markdown comparison."""
    return "".join(character.lower() for character in value if character.isalnum())


def purify_body(element: Tag) -> None:
    """Decompose non-editorial noise tags like scripts, ads, breadcrumbs, footers."""
    for noise in element.select(UNIVERSAL_NOISE_SELECTORS):
        noise.decompose()


def _content_in_markdown(element: Tag, markdown: str) -> bool:
    """Validate that the core article body is substantially present in the markdown."""
    purify_body(element)
    source = normalized_text(element.get_text(" ", strip=True))
    if not source:
        return False
    if len(source) <= EXCERPT_CHARACTERS:
        return source in markdown

    # Interior statistical sampling: check 5 evenly spaced interior checkpoints
    # (15%, 35%, 50%, 65%, 85%) avoiding fragile edge noise (position 0 and last)
    ratios = (0.15, 0.35, 0.50, 0.65, 0.85)
    max_start = len(source) - EXCERPT_CHARACTERS
    positions = sorted({int(max_start * r) for r in ratios})

    present = [
        source[position : position + EXCERPT_CHARACTERS] in markdown
        for position in positions
    ]
    match_count = sum(present)
    match_ratio = match_count / len(present) if present else 0.0

    return match_ratio >= 0.60 and len(markdown) >= len(source) * 0.40


def http_article_error(domain: str, result: object, text: str) -> str | None:
    """Reject incomplete HTTP articles so the browser can retry that URL."""
    html = getattr(result, "html", None)
    if not isinstance(html, str) or not html:
        return "HTTP response has no HTML"
    markdown = normalized_text(clean_to_verbatim(text))
    layouts = ARTICLE_LAYOUTS.get(domain)
    if layouts is None and domain.endswith(".39.net"):
        layouts = ARTICLE_LAYOUTS["39.net"]
    if layouts is None and len(markdown) < MIN_BODY_CHARACTERS:
        return f"HTTP article layout is not configured for {domain}"
    if len(markdown) < MIN_BODY_CHARACTERS:
        return "HTTP Markdown is too short for an article"

    soup = BeautifulSoup(html, "lxml")
    if domain == "wujue.com":
        for body in soup.select("#article-main_left .art-text"):
            remove_wujue_pager(body)

    if layouts is not None:
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

    # Universal Auto-Discovery for domains without explicit layout:
    title_candidates = soup.select("h1, .article-title, .entry-title, .title, header h1")
    valid_title = False
    for cand in title_candidates:
        cand_text = normalized_text(cand.get_text(" ", strip=True))
        if len(cand_text) >= 6 and cand_text in markdown:
            valid_title = True
            break
    if not valid_title:
        return f"HTTP article layout is not configured for {domain} (no valid title found in markdown)"

    body_candidates = soup.select(
        "article, main, #content, .content, .post-content, .detail-content, .entry-content, #bodyContent"
    )
    if not body_candidates:
        return f"HTTP article layout is not configured for {domain} (no standard body container)"

    for cand_body in body_candidates:
        if _content_in_markdown(cand_body, markdown):
            return None

    return f"HTTP article layout is not configured for {domain} (body content did not match markdown)"
