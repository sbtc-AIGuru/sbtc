"""Checks that HTTP-fetched pages contain the complete configured article."""

from __future__ import annotations

from copy import copy
from bs4 import BeautifulSoup, Tag

from pagination import remove_wujue_pager
from verbatim import clean_to_verbatim


ARTICLE_LAYOUTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "bachmai.gov.vn": (("#content-post > h3, #content-post > h1", ("#content-post .content-editor",)),),
    "baoangiang.com.vn": ((".detail-title h1", ("#newscontents",)),),
    "baogialai.com.vn": (("h1.article__title", (".article__body",)),),
    "baotayninh.vn": ((".content-article > h1", ("#content-detail",)),),
    "baothanhhoa.vn": (("h1.article__title", (".article__body",)),),
    "baoquangninh.vn": (("h1.article__title", (".article__body",)),),
    "health.people.com.cn": (
        (".articleCont .title", (".articleCont .artDet",)),
        (".rm_txt .col-1 > h1", ("#rm_txt_zw",)),
    ),
    "qihuangzhishu.com": ((".cbody > h1", (".cbody .spider",)),),
    "baophutho.vn": (("#dcontent h1.pTitle", ("#dcontent",)),),
    "baochinhphu.vn": (
        (".detail-mcontent > h1", (".detail-mcontent > .detail-content",)),
        ("h1.title", (".detail-content",)),
    ),
    "benhviennhitrunguong.gov.vn": (("#primary .entry-title h1", ("#primary .entry-content",)),),
    "benhvienvietduc.org": ((".news-primary-content h1, .news-primary-content h2", (".news-primary-content",)),),
    "baoquangtri.vn": (("h2#title", (".td-post-content",)),),
    "baovinhlong.com.vn": (("h1.head_title", ("#content",)),),
    "ask.familydoctor.com.cn": ((".quest-title", (".quest-info .illness-pics", ".answer-words")),),
    "120ask.com": (("#d_askH1", ("#d_msCon", ".b_answerbox .b_answerli .b_anscont_cont")),),
    "bachmai.gov.vn": (("#content-post > h3.h3", ("#content-post > .content-editor",)),),
    "baoangiang.com.vn": ((".detail-title h1", ("#newscontents",)),),
    "cnkang.com": (
        (".detail h1.detaila", (".detail .detailc",)),
        (".endContent h1, h1#h1title, h1", ("#endText",)),
    ),
    "wujue.com": (("#article-main_left .main_articletitle h1", ("#article-main_left .art-text",)),),
    "baocantho.com.vn": (
        ("#colcate1 > h1", ("#newscontents",)),
        ("h1.h1magazine", (".noidungbai",)),
    ),
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
        ("article.e-magazine h1", (".e-magazine__body",)),
    ),
    "39.net": (
        ("h1.ask_tit, .ask_tit, .art_left > h1, h1", (".ask_cont, .all_answer, .doc_ans, .art_left > .art_content, .art_content",)),
        ("h1", (".artCon",)),
        (".artbox h1, h1", (".artbox .article",)),
        (".article_title", (".article_cur",)),
    ),
    "ask.39.net": (
        ("h1.ask_tit, .ask_tit, h1", (".ask_hid .txt_ms, .ask_hid .txt_bc",)),
        ("h1.ask_tit, .ask_tit, h1", (".ask_cont", ".all_answer, .doc_ans")),
    ),
    "nhathuoclongchau.com.vn": (
        ("h1", ('[class*="posts-detail_posts-detail-container"] > .bg-white',)),
        ("h1", ("div.relative.container-lite.flex.flex-col",)),
    ),
    "youmed.vn": (
        (".article-content > article > h1", (".article-content > article > .prose",)),
    ),
    "suckhoeviet.org.vn": (
        (".article-detail-body-right > h1", (".article-detail-body-right > .__MASTERCMS_CONTENT",)),
        ("h1.mastercms-emag-title", ("article.mastercms-emag-article",)),
    ),
    "tamanhhospital.vn": (
        ("h1", (".post_info.box_detail_post",)),
    ),
    "familydoctor.com.cn": (
        (".art-title h1, .title h1, h1.title, h1", (".art-content, .content, #content, .q-content",)),
        (".article-titile h1", ("#viewContent",)),
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


def minimum_article_characters(domain: str) -> int:
    """Allow complete short questions and Chinese book verses in known layouts."""
    return {"ask.39.net": 8, "qihuangzhishu.com": 12}.get(domain, MIN_BODY_CHARACTERS)

UNIVERSAL_NOISE_SELECTORS = (
    "script, style, noscript, iframe, svg, nav, footer, aside, "
    ".breadcrumb, .breadcrumbs, .share, .social-share, .comment, .comments, "
    "#toc, .toc, .printfooter, #catlinks, #siteSub, #contentSub, #jump-to-nav, "
    ".related, .recommend, .ad, .ads, .detail-share, .detail-relate"
)


def normalized_text(value: str) -> str:
    """Remove markup punctuation and whitespace for HTML/Markdown comparison."""
    return "".join(character.lower() for character in value if character.isalnum())


def article_content_issue(domain: str, result: object, url: str) -> str | None:
    """Identify known article bodies requiring OCR or transcription, without guessing text."""
    layouts = ARTICLE_LAYOUTS.get(domain)
    html = getattr(result, "html", "")
    if not layouts or not html:
        return None
    if domain not in {"baocantho.com.vn", "baoquangtri.vn", "baovinhlong.com.vn",
                      "benhviennhitrunguong.gov.vn", "suckhoeviet.org.vn"}:
        return None
    soup = BeautifulSoup(html, "lxml")
    for title_selector, body_selectors in layouts:
        title = soup.select_one(title_selector)
        if title is None:
            continue
        for selector in body_selectors:
            for element in soup.select(selector):
                has_image = bool(element.select("img"))
                has_video = bool(element.select("iframe, video, .rll-youtube-player, .wp-video"))
                body = copy(element)
                purify_body(body)
                for noise in body.select("h1, h2#title, .entry-post_info, .article-info, .author-post"):
                    noise.decompose()
                external_reference = False
                for link in body.select('a[href^="http"]'):
                    if link.get_text(strip=True).rstrip("/") == link["href"].rstrip("/"):
                        external_reference = True
                        link.decompose()
                length = len(normalized_text(body.get_text(" ", strip=True)))
                infographic = "infograph" in (url + " " + title.get_text()).lower()
                if not (has_image or has_video or external_reference):
                    continue
                if length < MIN_BODY_CHARACTERS or (has_image and infographic and length < 400):
                    kind = "video-only article requires transcription" if has_video else "image-only article requires OCR"
                    if not (has_image or has_video):
                        kind = "article only links to an external resource"
                    return f"Unsupported content type: {kind}"
    return None


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
    if layouts is None and domain.endswith(".familydoctor.com.cn"):
        layouts = ARTICLE_LAYOUTS["familydoctor.com.cn"]
    minimum_characters = minimum_article_characters(domain)
    if layouts is None and len(markdown) < minimum_characters:
        return f"HTTP article layout is not configured for {domain}"
    if len(markdown) < minimum_characters:
        return "HTTP Markdown is too short for an article"

    soup = BeautifulSoup(html, "lxml")
    if domain == "tamanhhospital.vn":
        for noise in soup.select(".post_info.box_detail_post .content_insert, .post_info.box_detail_post .div_over, .post_info.box_detail_post .mt_15, .post_info.box_detail_post .div_tool"):
            noise.decompose()
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
            if domain == "ask.39.net":
                answers = soup.select(".all_answer, .doc_ans")
                if answers:
                    bodies.append(answers)
            if any(not elements for elements in bodies):
                continue
            if domain == "qihuangzhishu.com":
                # Medical book verses can be shorter than forty characters.
                # Accept these only when the entire source body is present.
                short_bodies = [normalized_text(element.get_text(" ", strip=True))
                                for elements in bodies for element in elements
                                if len(normalized_text(element.get_text(" ", strip=True))) < MIN_BODY_CHARACTERS]
                if any(len(body) < minimum_characters or body not in markdown for body in short_bodies):
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


def article_metadata(domain: str, result: object) -> dict[str, object]:
    """Identify question-only documents without inventing absent medical answers."""
    if domain != "ask.39.net":
        return {}
    soup = BeautifulSoup(getattr(result, "html", "") or "", "lxml")
    return {"document_type": "question", "has_answer": bool(soup.select(".all_answer, .doc_ans"))}
