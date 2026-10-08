"""Unit tests for quality check module (Scripts/Clawler/quality.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from quality import ARTICLE_LAYOUTS, article_content_issue, article_metadata, http_article_error


class MockResult:
    def __init__(self, html: str):
        self.html = html


class TestQualityModule(unittest.TestCase):
    """Test ARTICLE_LAYOUTS configurations and validation logic."""

    def test_short_chinese_heading_and_legacy_article_layouts(self):
        body = "Clinical content describes symptoms, treatment and follow-up examinations. " * 4
        cases = {
            "qihuangzhishu.com": '<div class="cbody"><h1>2.1 引言</h1><div class="spider">{body}</div></div>',
            "gan.39.net": '<h1>2.1 引言</h1><div class="artCon">{body}</div>',
            "wei.39.net": '<div class="artbox"><h1>2.1 引言</h1><div class="article">{body}</div></div>',
            "woman.39.net": '<p class="article_title">2.1 引言</p><div class="article_cur">{body}</div>',
            "yanglao.familydoctor.com.cn": '<div class="article-titile"><h1>2.1 引言</h1></div><div id="viewContent">{body}</div>',
        }
        for host, template in cases.items():
            with self.subTest(host=host):
                result = MockResult(template.format(body=body))
                self.assertIsNone(http_article_error(host, result, f"2.1 引言\n{body}"))
                self.assertIsNotNone(http_article_error(host, result, "2.1 引言"))

    def test_redirected_and_magazine_layouts_keep_complete_text(self):
        title = "Complete article about appropriate medical care"
        body = "The article explains symptoms, treatment options and follow-up examinations for patients. " * 3
        cases = {
            "baochinhphu.vn": '<h1 class="title">{title}</h1><div class="detail-content">{body}</div>',
            "baocantho.com.vn": '<div class="noidungbai"><h1 class="h1magazine">{title}</h1><p>{body}</p></div>',
            "dantri.com.vn": '<article class="e-magazine"><h1>{title}</h1><div class="e-magazine__body">{body}</div></article>',
            "suckhoeviet.org.vn": '<article class="mastercms-emag-article"><h1 class="mastercms-emag-title">{title}</h1><p>{body}</p></article>',
            "baophutho.vn": '<div id="dcontent"><h1 class="pTitle">{title}</h1><p>{body}</p></div>',
        }
        for host, template in cases.items():
            with self.subTest(host=host):
                result = MockResult(template.format(title=title, body=body))
                self.assertIsNone(http_article_error(host, result, f"{title}\n{body}"))
                self.assertIsNotNone(http_article_error(host, result, title))

    def test_long_chau_ignores_nested_empty_product_cards(self):
        title = "Complete medical article"
        body = "The article explains symptoms, treatment options and follow-up examinations for patients. " * 4
        html = (f'<div class="posts-detail_posts-detail-container__hash"><div class="bg-white"><h1>{title}</h1>'
                f'<p>{body}</p></div><section><div class="bg-white"></div></section></div>')
        self.assertIsNone(http_article_error("nhathuoclongchau.com.vn", MockResult(html), f"{title}\n{body}"))

    def test_media_only_articles_require_ocr_or_transcription(self):
        cases = {
            "baocantho.com.vn": '<div class="noidungbai"><h1 class="h1magazine">Infographic</h1><p><img src="chart.png"/></p></div>',
            "benhviennhitrunguong.gov.vn": '<div id="primary"><div class="entry-title"><h1>Medical video</h1></div><div class="entry-content"><div class="rll-youtube-player"></div></div></div>',
        }
        for host, html in cases.items():
            with self.subTest(host=host):
                self.assertIn("Unsupported content type", article_content_issue(host, MockResult(html), "https://example.test/article"))
        body = "An actual medical article explains symptoms and appropriate follow-up care. " * 10
        html = f'<div class="noidungbai"><h1 class="h1magazine">Medical article</h1><p>{body}</p><img src="illustration.png"/></div>'
        self.assertIsNone(article_content_issue("baocantho.com.vn", MockResult(html), "https://example.test/article"))

    def test_external_link_without_article_text_requires_separate_extraction(self):
        html = ('<div id="primary"><div class="entry-title"><h1>Medical information</h1></div>'
                '<div class="entry-content"><div class="entry-post_info">2018</div>'
                '<a href="https://video.test/story">https://video.test/story</a></div></div>')
        self.assertIn("external resource", article_content_issue("benhviennhitrunguong.gov.vn", MockResult(html), "https://example.test/article"))

    def test_campaign_news_layouts_keep_title_and_complete_body(self):
        title = "Doctors explain prevention and treatment choices"
        body = "Patients should discuss symptoms and appropriate tests with their doctor before receiving treatment."
        templates = {
            "bachmai.gov.vn": '<div id="content-post"><h3>{title}</h3><div class="content-editor">{body}</div></div>',
            "baoangiang.com.vn": '<div class="detail-title"><h1>{title}</h1></div><div id="newscontents">{body}</div>',
            "baogialai.com.vn": '<h1 class="article__title">{title}</h1><div class="article__body">{body}</div>',
            "baothanhhoa.vn": '<h1 class="article__title">{title}</h1><div class="article__body">{body}</div>',
            "baoquangninh.vn": '<h1 class="article__title">{title}</h1><div class="article__body">{body}</div>',
            "baotayninh.vn": '<div class="content-article"><h1>{title}</h1><div id="content-detail">{body}</div></div>',
            "health.people.com.cn": '<div class="articleCont"><div class="title">{title}</div><div class="artDet">{body}</div></div>',
        }
        for domain, template in templates.items():
            with self.subTest(domain=domain):
                result = MockResult(template.format(title=title, body=body))
                self.assertIsNone(http_article_error(domain, result, f"{title}\n{body}"))
                self.assertIsNotNone(http_article_error(domain, result, title))
                self.assertIsNotNone(http_article_error(domain, result, body))

    def test_tam_anh_tool_widget_does_not_mask_article_body(self):
        title = "A complete article about medical treatment"
        body = "The article explains symptoms, treatment options and appropriate follow-up examinations for patients."
        html = (f'<div class="post_info box_detail_post"><h1>{title}</h1>'
                '<div class="div_tool">Date and search preference widget text</div></div>'
                f'<div class="post_info box_detail_post"><p>{body}</p></div>')
        self.assertIsNone(http_article_error("tamanhhospital.vn", MockResult(html), f"{title}\n{body}"))
        self.assertIsNotNone(http_article_error("tamanhhospital.vn", MockResult(html), title))

    def test_39_net_subdomain_uses_shared_article_layout(self):
        """Question pages on ask.39.net can pass the configured HTTP gate."""
        title = "Question about treatment options"
        body = (
            "The doctor explains the symptoms, recommended tests, treatment "
            "options, and follow-up care for this condition."
        )
        html = f"<h1 class='ask_tit'>{title}</h1><div class='ask_cont'>{body}</div><div class='doc_ans'>{body}</div>"
        self.assertIsNone(
            http_article_error("ask.39.net", MockResult(html), f"{title}\n{body}")
        )

    def test_39_question_without_answer_is_incomplete(self):
        title = "What treatment should a patient receive?"
        question = "The question describes symptoms but there is no doctor answer on the page."
        html = f"<h1 class='ask_tit'>{title}</h1><div class='ask_cont'>{question}</div>"
        self.assertIsNotNone(http_article_error("ask.39.net", MockResult(html), f"{title}\n{question}"))

    def test_modern_39_question_only_layout_excludes_related_disease_widgets(self):
        title = "Question about symptoms"
        question = "Symptoms started several days ago and the patient asks how to seek care."
        html = (f"<div class='ask_cont'><h1 class='ask_tit'>{title}</h1>"
                f"<div class='ask_hid'><p class='txt_ms'>{question}</p></div>"
                "<section class='sys-box'>Related disease recommendations and consultation links</section></div>")
        result = MockResult(html)
        self.assertIsNone(http_article_error("ask.39.net", result, f"{title}\n{question}"))
        self.assertEqual(article_metadata("ask.39.net", result), {"document_type": "question", "has_answer": False})

    def test_modern_39_layout_does_not_drop_existing_answer(self):
        title = "Question about symptoms"
        question = "The patient describes recent symptoms and asks for advice."
        answer = "The doctor explains which tests and follow-up examinations are appropriate."
        html = (f"<h1 class='ask_tit'>{title}</h1><div class='ask_hid'><p class='txt_ms'>{question}</p></div>"
                f"<div class='doc_ans'>{answer}</div>")
        self.assertIsNotNone(http_article_error("ask.39.net", MockResult(html), f"{title}\n{question}"))
        self.assertIsNone(http_article_error("ask.39.net", MockResult(html), f"{title}\n{question}\n{answer}"))

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

    def test_configured_domains_present(self):
        """Verify baseline and newly added static domains are in ARTICLE_LAYOUTS."""
        expected_domains = [
            "120ask.com",
            "cnkang.com",
            "wujue.com",
            "baocantho.com.vn",
            "suckhoedoisong.vn",
            "a-hospital.com",
            "zhongyibaodian.net",
            "sggp.org.vn",
            "dantri.com.vn",
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
