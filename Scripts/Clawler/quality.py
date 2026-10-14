"""Checks that HTTP-fetched pages contain the complete configured article."""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup, Tag

from pagination import remove_wujue_pager
from verbatim import clean_to_verbatim


ARTICLE_LAYOUTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "120ask.com": (
        ("#d_askH1, .b_askbox h1, h1", ("#d_msCon, .b_askbox", ".b_answerbox .b_answerli .b_anscont_cont")),
        ("#d_askH1, .b_askbox h1, h1", ("#d_msCon, .b_askbox",)),
    ),
    "bachmai.gov.vn": (("#content-post > h3.h3", ("#content-post > .content-editor",)),),
    "baoangiang.com.vn": ((".detail-title h1", ("#newscontents",)),),
    "cnkang.com": (
        (".detail h1.detaila", (".detail .detailc",)),
        (".endContent h1, h1#h1title, h1", ("#endText",)),
        ("h1, .main_content h1", (".main_content, .article_content",)),
        ("title, h1", (".zh05b",)),
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
        ("h1.firstHeading, h1#firstHeading, h1", ("#bodyContent",)),
        ("h1.firstHeading, h1#firstHeading, h1", ("#content",)),
    ),
    "zhongyibaodian.net": (
        ("h1.firstHeading, h1#firstHeading, h1", ("#bodyContent",)),
        ("h1.firstHeading, h1#firstHeading, h1", ("#content",)),
    ),
    "baidu.com": (
        ("title, h1, h2", (".health-dict__content, .health-dict",)),
    ),
    "jbk.39.net": (
        ("h1, .disease_box h1", (".information_box",)),
        ("h1", (".lbox, .des, .text",)),
        ("h1", (".intro, .des, .lbox, .catalogItem",)),
        ("h1", (".container",)),
        ("h1", (".disease_box",)),
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
        (".art-title h1, .title h1, h1.title, h1", ("#viewContent, .viewContent, .endContent",)),
        (".art-title h1, .title h1, h1.title, h1", (".art-content, .content, #content, .q-content",)),
    ),
    "zysjonline.com": (
        ("article h1, h1", ("article .leading-8, article .space-y-4", "article")),
        ("h1", ("main .flex-1.min-w-0", ".flex-1")),
        ("h1, title", ("article, main .flex-1",)),
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
    raw_text = element.get_text(" ", strip=True)
    # Strip URL addresses that verbatim cleaner stripped from markdown
    stripped_urls = html.unescape(re.sub(r"https?://\S+", "", raw_text))
    source = normalized_text(stripped_urls)
    if not source:
        return False
    if len(source) <= EXCERPT_CHARACTERS:
        return source in markdown or markdown in source

    # For short entries (< 100 characters like dictionary stubs), check matching prefix/substring
    if len(source) < 100:
        sample_len = min(15, len(source))
        return (source[:sample_len] in markdown) or (len(markdown) >= 15 and markdown[:15] in source)

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
        layouts = ARTICLE_LAYOUTS.get("jbk.39.net") if domain == "jbk.39.net" else ARTICLE_LAYOUTS["39.net"]
    if layouts is None and (domain.endswith(".familydoctor.com.cn") or domain == "familydoctor.cn"):
        layouts = ARTICLE_LAYOUTS["familydoctor.com.cn"]

    min_len = 15 if domain in ("a-hospital.com", "zhongyibaodian.net") else MIN_BODY_CHARACTERS
    if layouts is None and len(markdown) < min_len:
        return f"HTTP article layout is not configured for {domain}"
    if len(markdown) < min_len:
        return "HTTP Markdown is too short for an article"

    soup = BeautifulSoup(html, "lxml")
    if domain == "wujue.com":
        for body in soup.select("#article-main_left .art-text"):
            remove_wujue_pager(body)

    if layouts is not None:
        for title_selector, body_selectors in layouts:
            title_matched = False
            for title_elem in soup.select(title_selector):
                title_text = normalized_text(title_elem.get_text(" ", strip=True))
                if title_text and title_text in markdown:
                    title_matched = True
                    break
            if not title_matched:
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

    # Universal Auto-Discovery fallback
    title_candidates = soup.select("h1, .article-title, .entry-title, .title, header h1, title, h2")
    valid_title = False
    for cand in title_candidates:
        cand_text = normalized_text(cand.get_text(" ", strip=True))
        if len(cand_text) >= 4 and cand_text in markdown:
            valid_title = True
            break
    if not valid_title:
        return (
            "HTTP Markdown is missing the title or part of the article body"
            if layouts is not None
            else f"HTTP article layout is not configured for {domain} (no valid title found in markdown)"
        )

    body_candidates = soup.select(
        "article, main, #content, .content, .post-content, .detail-content, .entry-content, #bodyContent, .main_content, .container"
    )
    if not body_candidates:
        return (
            "HTTP Markdown is missing the title or part of the article body"
            if layouts is not None
            else f"HTTP article layout is not configured for {domain} (no standard body container)"
        )

    for cand_body in body_candidates:
        if _content_in_markdown(cand_body, markdown):
            return None

    return (
        "HTTP Markdown is missing the title or part of the article body"
        if layouts is not None
        else f"HTTP article layout is not configured for {domain} (body content did not match markdown)"
    )
