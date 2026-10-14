"""Crawl4AI article selectors for known source websites."""

from __future__ import annotations

from crawl4ai import (
    CacheMode,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    PruningContentFilterLXML,
)


PAGE_TIMEOUT_MS = 30_000


def build_run_configs() -> tuple[CrawlerRunConfig, dict[str, CrawlerRunConfig]]:
    """Choose article extraction settings for known domains."""
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=PAGE_TIMEOUT_MS,
        verbose=False,
        exclude_all_images=True,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilterLXML(
                threshold=0.45,
                threshold_type="dynamic",
                min_word_threshold=5,
            )
        ),
    )
    # Keep complete article regions; pruning can drop short paragraphs or tables.
    domain_configs = {
        "bachmai.gov.vn": run_config.clone(
            target_elements=["#content-post"],
            excluded_selector=(
                "#content-post > #title-print, "
                "#content-post > .post-detail__content, "
                "#content-post > hr"
            ),
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baoangiang.com.vn": run_config.clone(
            target_elements=[".detail-title h1", ".detail-desc", "#newscontents"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baocantho.com.vn": run_config.clone(
            target_elements=["#colcate1 > h1", "#newscontents"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baodanang.vn": run_config.clone(
            target_elements=[".c-detail-head__title", ".entry"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baohaiphong.vn": run_config.clone(
            target_elements=[".c-detail-head__title", ".entry"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baonghean.vn": run_config.clone(
            target_elements=[".c-detail-head__title", ".entry"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "dantri.com.vn": run_config.clone(
            target_elements=["#articleContent"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "giadinhonline.vn": run_config.clone(
            target_elements=[".detail-content"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "hellobacsi.com": run_config.clone(
            target_elements=[
                "#article-page-container-wrapper h1",
                "#article-page-container-wrapper .unique-content-wrapper",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "laodong.vn": run_config.clone(
            target_elements=[
                "article.article-detail .wrapper-01 h1",
                "article.article-detail .art-info",
                "article.article-detail .chappeau",
                "article.article-detail .art-body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "medlatec.vn": run_config.clone(
            target_elements=[
                ".block-posts-single > h1",
                ".block-posts-single > .shortdescription",
                ".block-posts-single > .description",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "nhathuoclongchau.com.vn": run_config.clone(
            target_elements=['[class*="posts-detail_posts-detail-container"] .bg-white'],
            excluded_selector=(
                '[class*="posts-detail_posts-detail-container"] '
                '.flex.flex-col.items-center'
            ),
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "nhathuoclongchau.com.vn/benh": run_config.clone(
            target_elements=["div.relative.container-lite.flex.flex-col"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "phunusuckhoe.giadinhonline.vn": run_config.clone(
            target_elements=[
                ".single-post .post-title h1",
                ".single-post #article-body",
                ".single-post .author-description",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "qihuangzhishu.com": run_config.clone(
            target_elements=[".cbody > h1", ".cbody .spider"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "suckhoecongdongonline.vn": run_config.clone(
            target_elements=[
                ".article > .article__header",
                ".article > .article__sapo",
                ".article > .article__body",
            ],
            excluded_selector=".article__body > table.__mb_article_in_image",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "suckhoedoisong.vn": run_config.clone(
            target_elements=[
                "h1.detail-title, .detail-title, h1",
                ".detail-content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "suckhoecongdongonline.vn": run_config.clone(
            target_elements=[
                "h1.article__title, h1",
                ".article__sapo",
                ".article__body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "thanhnien.vn": run_config.clone(
            target_elements=[
                "h1.detail-title, article.detail__cmain > h1, h1",
                ".detail-sapo",
                ".detail-content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "tiemchunglongchau.com.vn": run_config.clone(
            target_elements=[
                ".background-white.relative > h1",
                ".background-white.relative > div.my-4",
                "#content-article",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "vietnamnet.vn": run_config.clone(
            target_elements=[".content-detail"],
            excluded_selector=".content-detail > .vnn-share-social",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "vinmec.com": run_config.clone(
            target_elements=[".post-detail .post-header h1", "#main-article"],
            excluded_selector="#toc-container",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "vov.vn": run_config.clone(
            target_elements=[
                "article.detail .article-title",
                "article.detail .article-summary",
                "article.detail .article-content",
                "article.detail .article-author",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "youmed.vn": run_config.clone(
            target_elements=[
                ".article-content > article > h1",
                ".article-content > article > .prose",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "39.net": run_config.clone(
            target_elements=[
                "h1.ask_tit",
                ".ask_tit",
                ".art_left > h1",
                "h1",
                ".ask_cont",
                ".all_answer",
                ".doc_ans",
                ".art_left > .art_summary",
                ".art_left > .art_content",
                ".art_content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "jbk.39.net": run_config.clone(
            target_elements=[
                "h1",
                ".information_box",
                ".disease_box",
                ".catalogItem",
                ".lbox",
                ".chi-cont",
                ".item-left",
                ".intro",
                ".des",
                ".text",
                ".disease_detail",
            ],
            excluded_selector=(
                ".disease_box.firend, .disease_box.hospital, "
                ".ad, .share, script, style"
            ),
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "familydoctor.com.cn": run_config.clone(
            target_elements=[
                ".art-title h1",
                ".title h1",
                "h1.title",
                "h1",
                "#viewContent",
                ".viewContent",
                ".endContent",
                ".art-content",
                ".content",
                "#content",
                ".q-content",
                ".ans-content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "youlai.cn": run_config.clone(
            target_elements=[
                '[class*="mainContent--"] > [class*="title--"]',
                '[class*="mainContent--"] [class*="textContent--"]',
                "h1.doc_title",
                "h1.title",
                "h1",
                ".doc_content",
                ".article_content",
                ".art_content",
                ".content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "zydcd.com": run_config.clone(
            target_elements=[
                ".panel.panel-danger > .panel-heading h1",
                ".panel.panel-danger > .panel-body.info_txt",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "120ask.com": run_config.clone(
            target_elements=[
                "#d_askH1",
                ".b_askbox h1",
                "h1",
                "#d_msCon",
                ".b_askbox",
                ".b_answerbox .b_answerli .b_anscont_cont",
                ".b_anscont",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "cnkang.com": run_config.clone(
            target_elements=[
                "title",
                ".detail h1.detaila",
                ".detail .detailc",
                ".endContent h1",
                "h1#h1title",
                "h1",
                "#endText",
                ".zh05b",
                ".main_content",
                ".article_content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "wujue.com": run_config.clone(
            target_elements=[
                "#article-main_left .main_articletitle h1",
                "#article-main_left .art-text",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baochinhphu.vn": run_config.clone(
            target_elements=[
                ".detail-mcontent > h1",
                ".detail-mcontent > .detail-sapo",
                ".detail-mcontent > .detail-content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baogialai.com.vn": run_config.clone(
            target_elements=[
                "div.article > h1",
                "div.article .article__header",
                "div.article .article__body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baolangson.vn": run_config.clone(
            target_elements=[
                ".content-article > h1",
                "#content-detail",
                ".content-article > .pen-name",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baoquangninh.vn": run_config.clone(
            target_elements=[".article > .article__header", ".article > .article__body"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baoquangtri.vn": run_config.clone(
            target_elements=["h2#title", ".td-post-content"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baovinhlong.com.vn": run_config.clone(
            target_elements=[".col11 > h1.head_title", ".col11 > #content"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "khoahocphothong.vn": run_config.clone(
            target_elements=[".c-detail-head__title", ".entry"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "nhandan.vn": run_config.clone(
            target_elements=[
                ".article > .article__header",
                ".article .article__avatar",
                ".article .article__body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "phuyen.baodaklak.vn": run_config.clone(
            target_elements=["#wrapperPostDetailMain"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "suckhoeviet.org.vn": run_config.clone(
            target_elements=[
                ".article-detail-body-right > h1",
                ".article-detail-body-right > .article-detail-desc",
                ".article-detail-body-right > .__MASTERCMS_CONTENT",
            ],
            excluded_selector=".__MASTERCMS_CONTENT > table.__mb_article_in_image",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "tamanhhospital.vn": run_config.clone(
            target_elements=[".post_info.box_detail_post"],
            excluded_selector=(
                ".post_info.box_detail_post .content_insert, "
                ".post_info.box_detail_post .div_over, "
                ".post_info.box_detail_post .mt_15"
            ),
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "tienphong.vn": run_config.clone(
            target_elements=[
                ".article > .article__header",
                ".article > .article__sapo",
                ".article > .article__body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "tuoitre.vn": run_config.clone(
            target_elements=[
                "#main-detail > h1",
                "#main-detail > .detail-sapo",
                "#main-detail > .detail-cmain",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "vnexpress.net": run_config.clone(
            target_elements=["article.fck_detail"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "vov2.vov.vn": run_config.clone(
            target_elements=[
                ".width-848 > .article-title",
                ".width-848 > .article-description",
                ".width-848 > .article-body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "qdnd.vn": run_config.clone(
            target_elements=[
                ".article-detail > h1",
                ".article-detail > .post-summary",
                ".article-detail > .post-content",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "vietnamplus.vn": run_config.clone(
            target_elements=[
                ".article > h1",
                ".article > .article__sapo",
                ".article .article__body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baophutho.vn": run_config.clone(
            target_elements=["#dcontent"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baotayninh.vn": run_config.clone(
            target_elements=[".content-article > h1", "#content-detail"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baothanhhoa.vn": run_config.clone(
            target_elements=[
                "div.article div.article > h1",
                "div.article div.article > .article__sapo",
                "div.article div.article > .article__body",
            ],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "benhviennhitrunguong.gov.vn": run_config.clone(
            target_elements=["#primary > .entry-title", "#primary > .entry-content"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "benhvienvietduc.org": run_config.clone(
            target_elements=[".news-primary-content"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "hanoimoi.vn": run_config.clone(
            target_elements=[".entry"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "health.people.com.cn": run_config.clone(
            target_elements=[".articleCont"],
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "a-hospital.com": run_config.clone(
            target_elements=["h1.firstHeading, h1#firstHeading, h1", "#bodyContent, #content"],
            excluded_selector="#toc, .printfooter, #catlinks, #siteSub, #contentSub, #jump-to-nav, .urllink",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "zhongyibaodian.net": run_config.clone(
            target_elements=["h1.firstHeading, h1#firstHeading, h1", "#bodyContent, #content"],
            excluded_selector="#toc, .toc, #jump-to-nav, #siteSub, #contentSub, .printfooter, #heading-search",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "baidu.com": run_config.clone(
            target_elements=[
                "title",
                "h1",
                ".health-dict__content",
                ".health-dict",
            ],
            excluded_selector="script, style, noscript, iframe, svg, nav, footer",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
        "zysjonline.com": run_config.clone(
            target_elements=[
                "article",
                "main .flex-1.min-w-0",
                "h1, .leading-8",
            ],
            excluded_selector="aside, nav, header, footer, dialog, script, style, .sticky",
            markdown_generator=DefaultMarkdownGenerator(),
        ),
    }
    return run_config, domain_configs
