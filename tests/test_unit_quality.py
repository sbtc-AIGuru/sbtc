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
        
        from fetch import BROWSER_ONLY_DOMAINS
        self.assertIn("bachmai.gov.vn", BROWSER_ONLY_DOMAINS)

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
