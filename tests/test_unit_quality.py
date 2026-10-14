"""Unit tests for quality check module (Scripts/Clawler/quality.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from quality import ARTICLE_LAYOUTS, http_article_error


class MockResult:
    def __init__(self, html: str):
        self.html = html


class TestQualityModule(unittest.TestCase):
    """Test ARTICLE_LAYOUTS configurations and validation logic."""

    def test_39_net_subdomain_uses_shared_article_layout(self):
        """Question pages on ask.39.net can pass the configured HTTP gate."""
        title = "Question about treatment options"
        body = (
            "The doctor explains the symptoms, recommended tests, treatment "
            "options, and follow-up care for this condition."
        )
        html = f"<h1 class='ask_tit'>{title}</h1><div class='ask_cont'>{body}</div>"
        self.assertIsNone(
            http_article_error("ask.39.net", MockResult(html), f"{title}\n{body}")
        )

    def test_live_news_layouts_validate_article_body(self):
        """Known news layouts pass complete articles and reject missing body text."""
        title = "How doctors recommend preventing seasonal illness"
        body = (
            "Doctors explain the symptoms, treatment choices, and practical "
            "steps for preventing this illness."
        )
        cases = (
            (
                "baohaiphong.vn",
                "<h1 class='c-detail-head__title'>{title}</h1>"
                "<div class='entry'>{body}</div>",
            ),
            (
                "phunusuckhoe.giadinhonline.vn",
                "<div class='single-post'><div class='post-title'><h1>{title}</h1>"
                "</div><div id='article-body'>{body}</div></div>",
            ),
        )
        for domain, template in cases:
            with self.subTest(domain=domain):
                result = MockResult(template.format(title=title, body=body))
                self.assertIsNone(http_article_error(domain, result, f"{title}\n{body}"))
                self.assertIsNotNone(http_article_error(domain, result, title))

    def test_first_crawl_domains_accept_complete_http_articles(self):
        """Match the source-specific article regions before using Chromium."""
        title = "Doctors explain how to prevent illness and recover safely"
        summary = (
            "The article introduces symptoms, prevention measures, and when "
            "patients should seek medical care."
        )
        body = (
            "Doctors describe the recommended treatment, practical steps at "
            "home, and follow-up care for patients with persistent symptoms."
        )
        cases = (
            (
                "bachmai.gov.vn",
                "<div id='content-post'><h3 class='h3'>{title}</h3>"
                "<div class='content-editor'><p>{body}</p></div></div>",
                f"{title}\n{body}",
                title,
            ),
            (
                "baoangiang.com.vn",
                "<div class='detail-title'><h1>{title}</h1></div>"
                "<div id='newscontents'><p>{body}</p></div>",
                f"{title}\n{body}",
                title,
            ),
            (
                "suckhoeviet.org.vn",
                "<div class='article-detail-body-right'><h1>{title}</h1>"
                "<div class='article-detail-desc'>{summary}</div>"
                "<div class='__MASTERCMS_CONTENT'><p>{body}</p></div></div>",
                f"{title}\n{summary}\n{body}",
                f"{title}\n{summary}",
            ),
            (
                "tamanhhospital.vn",
                "<div class='post_info box_detail_post'>"
                "<div class='title'>{title}</div></div>"
                "<div class='post_info box_detail_post'><p>{body}</p></div>",
                f"{title}\n{body}",
                title,
            ),
        )
        for domain, template, complete, truncated in cases:
            with self.subTest(domain=domain):
                result = MockResult(template.format(
                    title=title, summary=summary, body=body
                ))
                self.assertIsNone(http_article_error(domain, result, complete))
                self.assertIsNotNone(http_article_error(domain, result, truncated))

    def test_youlai_current_layout_validates_title_and_body(self):
        title = "Can regular treatment reduce the risk of illness?"
        body = (
            "The article explains the risk factors, treatment options, "
            "and follow-up steps for the patient."
        )
        html = (
            f'<div class="mainContent--KSDkL"><div class="title--OslK-">{title}</div>'
            f'<div class="textContent--1jgN9">{body}</div></div>'
        )
        result = MockResult(html)
        self.assertIsNone(http_article_error("youlai.cn", result, f"{title}\n{body}"))
        self.assertIsNotNone(http_article_error("youlai.cn", result, title))

    def test_vietnamnet_and_zydcd_current_article_layouts(self):
        title = "Doctors explain a complete treatment plan"
        body = (
            "The article describes symptoms, treatment choices, follow-up care, "
            "and practical steps for patients and their families."
        )
        cases = (
            (
                "vietnamnet.vn",
                f"<div class='content-detail'><h1>{title}</h1>"
                f"<div class='main-content'><p>{body}</p></div></div>",
            ),
            (
                "zydcd.com",
                "<div class='panel panel-danger'>"
                f"<div class='panel-heading'><h1>{title}</h1></div>"
                f"<div class='panel-body info_txt'><p>{body}</p></div></div>"
                "<div class='panel panel-danger'><div class='panel-body info_txt'></div></div>"
                "<div class='panel panel-success'>Recommended content</div>",
            ),
            (
                "vinmec.com",
                "<div class='post-detail'><div class='post-header'>"
                f"<h1>{title}</h1></div></div>"
                f"<div id='main-article'><p>{body}</p></div>",
            ),
        )
        for domain, html in cases:
            with self.subTest(domain=domain):
                result = MockResult(html)
                self.assertIsNone(http_article_error(domain, result, f"{title}\n{body}"))
                self.assertIsNotNone(http_article_error(domain, result, title))

    def test_configured_domains_present(self):
        """Verify baseline and newly added static domains are in ARTICLE_LAYOUTS."""
        expected_domains = [
            "120ask.com",
            "bachmai.gov.vn",
            "baoangiang.com.vn",
            "cnkang.com",
            "wujue.com",
            "baocantho.com.vn",
            "suckhoedoisong.vn",
            "suckhoeviet.org.vn",
            "tamanhhospital.vn",
            "a-hospital.com",
            "zhongyibaodian.net",
            "sggp.org.vn",
            "dantri.com.vn",
            "baidu.com",
            "jbk.39.net",
        ]
        for domain in expected_domains:
            with self.subTest(domain=domain):
                self.assertIn(domain, ARTICLE_LAYOUTS, f"{domain} missing from ARTICLE_LAYOUTS")
        
    def test_valid_article_passes(self):
        """A complete article matching title and body layout should pass with None error."""
        html = (
            "<html><body>"
            "<div class='detail__contenent-main'>"
            "<header><h1>Tiêu đề bài viết y khoa chuyên sâu</h1></header>"
            "<div class='detail-content'>"
            "<p>Nội dung chi tiết bài viết y khoa hướng dẫn điều trị bệnh và phòng ngừa biến chứng.</p>"
            "</div>"
            "</div></body></html>"
        )
        text = "Tiêu đề bài viết y khoa chuyên sâu\n\nNội dung chi tiết bài viết y khoa hướng dẫn điều trị bệnh và phòng ngừa biến chứng."
        result = MockResult(html)
        error = http_article_error("suckhoedoisong.vn", result, text)
        self.assertIsNone(error, f"Expected None but got: {error}")

    def test_phase1_rescue_cases(self):
        """Verify Phase 1 rescue site layouts: 120ask, jbk.39.net, cnkang, baidu, a-hospital."""
        # 1. 120ask without answers (only question)
        q_title = "医生你好，请问急性胃炎吃什么药好？"
        q_desc = "健康咨询描述：昨晚吃辣后突然胃痛反酸，目前感觉胃部灼热恶心，想知道如何缓解。"
        html_120 = f"<h1 id='d_askH1'>{q_title}</h1><div id='d_msCon'>{q_desc}</div>"
        text_120 = f"{q_title}\n{q_desc}"
        self.assertIsNone(http_article_error("120ask.com", MockResult(html_120), text_120))

        # 2. jbk.39.net disease page
        jbk_title = "阿米巴性阴道炎"
        jbk_body = "阿米巴性阴道炎多由阿米巴原虫侵入阴道黏膜引起炎症，主要表现为阴道分泌物增多伴瘙痒疼痛。"
        html_jbk = f"<h1>{jbk_title}</h1><div class='disease_box'>{jbk_body}</div>"
        text_jbk = f"{jbk_title}\n{jbk_body}"
        self.assertIsNone(http_article_error("jbk.39.net", MockResult(html_jbk), text_jbk))

        # 3. cnkang main_content layout
        cnkang_title = "跌打损伤常用外敷药酒"
        cnkang_body = "本药酒主要适用于跌打损伤、局部肿痛及筋骨扭伤，每日涂抹患处两至三次即可见效。"
        html_cnkang = f"<div class='main_content'><h1>{cnkang_title}</h1><p>{cnkang_body}</p></div>"
        text_cnkang = f"{cnkang_title}\n{cnkang_body}"
        self.assertIsNone(http_article_error("cnkang.com", MockResult(html_cnkang), text_cnkang))

        # 4. baidu health encyclopedia layout
        baidu_title = "白斑病"
        baidu_body = (
            "主要特点为皮肤上出现界限清楚的白斑，疾病发生与遗传及自身免疫等因素密切相关。"
            "根据病情进展分为进展期、稳定期和消退期，根据病期及白斑部位选择合适的治疗方案。"
        )
        html_baidu = f"<title>{baidu_title}</title><div class='health-dict__content'><h2>{baidu_title}</h2><p>{baidu_body}</p></div>"
        text_baidu = f"{baidu_title}\n{baidu_body}"
        self.assertIsNone(http_article_error("baidu.com", MockResult(html_baidu), text_baidu))

        # 5. a-hospital mediawiki dictionary stub with URL stripping
        wiki_title = "丁疮"
        wiki_body = "丁疮，病名。出诸病源候论卷三十二。即疔疮，见该条。出自A+医学百科 http://www.a-hospital.com/w/dingchuang 转载请保留。"
        html_wiki = f"<h1 class='firstHeading'>{wiki_title}</h1><div id='bodyContent'>{wiki_body}</div>"
        text_wiki = f"{wiki_title}\n丁疮，病名。出诸病源候论卷三十二。即疔疮，见该条。"
        self.assertIsNone(http_article_error("a-hospital.com", MockResult(html_wiki), text_wiki))

    def test_missing_title_rejected(self):
        """If title is missing, http_article_error should return descriptive error."""
        html = (
            "<html><body>"
            "<div class='detail__contenent-main'>"
            "<div class='detail-content'>"
            "<p>Chỉ có nội dung thân bài mà không hề có phần tiêu đề bài viết.</p>"
            "</div>"
            "</div></body></html>"
        )
        text = "Chỉ có nội dung thân bài mà không hề có phần tiêu đề bài viết."
        result = MockResult(html)
        error = http_article_error("suckhoedoisong.vn", result, text)
        self.assertIsNotNone(error)
        self.assertIn("missing", error.lower())

    def test_too_short_rejected(self):
        """Content shorter than MIN_BODY_CHARACTERS should be rejected."""
        html = (
            "<html><body>"
            "<div class='detail__contenent-main'>"
            "<header><h1>Tiêu đề</h1></header>"
            "<div class='detail-content'><p>Ngắn</p></div>"
            "</div></body></html>"
        )
        text = "Ngắn"
        result = MockResult(html)
        error = http_article_error("suckhoedoisong.vn", result, text)
        self.assertIsNotNone(error)
        self.assertIn("too short", error.lower())

    def test_unconfigured_domain_rejected(self):
        """Unconfigured domain should be rejected so crawler can fall back to browser."""
        result = MockResult("<html><body>Hello</body></html>")
        error = http_article_error("random-unknown-domain.com", result, "Some text content here")
        self.assertIsNotNone(error)
        self.assertIn("not configured", error)


if __name__ == "__main__":
    unittest.main()
