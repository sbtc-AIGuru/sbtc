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
