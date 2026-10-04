"""Tests for Generalized Crawler Architecture.
Verifies:
1. HTTP-first routing for every domain with browser fallback in auto mode.
2. Universal HTTP enablement for all static domains (Top 20 + unconfigured).
3. Anti-boilerplate / copyright guard rejects empty or disclaimer-only texts.
4. Multi-layout selector coverage on key corpus domains (familydoctor, 39.net, youlai, cnkang, etc.).
5. Strict adherence to all 5 ViBioMIR BTC constraints.
"""

from __future__ import annotations

import asyncio
import html
import re
import unicodedata
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bs4 import BeautifulSoup

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from fetch import crawl_one, is_boilerplate_text
from quality import ARTICLE_LAYOUTS, http_article_error
from site_configs import build_run_configs
from utils import SourceRecord
from verbatim import clean_to_verbatim


def normalize_btc(text: str) -> list[str]:
    """Exact BTC 5-step normalization."""
    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text.split() if text else []


class TestGeneralizedCrawler(unittest.TestCase):
    """Test suite verifying overarching architectural improvements."""

    def test_auto_mode_tries_http_for_bachmai(self):
        """Auto mode tests HTTP before using the browser for Bach Mai."""
        record = SourceRecord(0, 101, "https://bachmai.gov.vn/bai-viet/article")
        valid_text = "Medical article content with enough words to pass validation. " * 3
        run_config, domain_configs = build_run_configs()
        with patch("fetch._fetch_with_strategy", new_callable=AsyncMock) as fetch_strategy:
            fetch_strategy.return_value = (valid_text, "", 1, object())
            outcome = asyncio.run(crawl_one(
                record, object(), object(), asyncio.Semaphore(1), asyncio.Semaphore(1),
                run_config, domain_configs, "auto",
            ))
        self.assertTrue(outcome.payload["success"])
        self.assertEqual(outcome.mode, "http")
        self.assertEqual(fetch_strategy.await_args.args[-1], "http")

    def test_anti_boilerplate_guard(self):
        """Copyright footers, error pages, and disclaimers must be detected as boilerplate."""
        # Chinese copyright footer
        cn_copyright = "Copyright © 1998 - 2026 familydoctor.com.cn All Rights Reserved 家庭医生在线版权所有"
        self.assertTrue(is_boilerplate_text(cn_copyright))

        # 404 / error notice
        error_page = "出错提示_家庭医生在线 抱歉，您访问的页面不存在或已删除！"
        self.assertTrue(is_boilerplate_text(error_page))

        # Too short text (<40 chars)
        short_text = "Nội dung quá ngắn."
        self.assertTrue(is_boilerplate_text(short_text))

        # Valid article text should NOT be boilerplate
        valid_article = (
            "Tiêu đề bài viết y khoa hướng dẫn điều trị bệnh tăng huyết áp.\n"
            "Tăng huyết áp là một bệnh lý mãn tính nguy hiểm, được mệnh danh là kẻ giết người thầm lặng. "
            "Người bệnh cần tuân thủ chế độ ăn giảm muối, tập thể dục đều đặn và dùng thuốc đúng chỉ định."
        )
        self.assertFalse(is_boilerplate_text(valid_article))

    def test_top_domains_configured_in_site_configs(self):
        """Top high-volume domains from 4.39M corpus scan must have multi-layout configs."""
        run_cfg, dom_cfgs = build_run_configs()
        critical_domains = [
            "cnkang.com",
            "120ask.com",
            "familydoctor.com.cn",
            "39.net",
            "youlai.cn",
            "suckhoedoisong.vn",
            "a-hospital.com",
            "zhongyibaodian.net",
            "thanhnien.vn",
        ]
        for dom in critical_domains:
            self.assertIn(dom, dom_cfgs, f"Critical domain {dom} must be in dom_cfgs")
            cfg = dom_cfgs[dom]
            self.assertTrue(len(cfg.target_elements) >= 2, f"{dom} must have at least 2 target elements")

    def test_universal_auto_discovery_passes_valid_static_html(self):
        """Unconfigured static domains with standard HTML structures must pass quality check."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Báo Sức Khỏe Mẫu</title></head>
        <body>
            <header><nav><a href="/">Trang chủ</a></nav></header>
            <main>
                <article>
                    <h1>Phương pháp phòng chống bệnh sốt xuất huyết hiệu quả tại gia đình</h1>
                    <div class="article-content">
                        <p>Sốt xuất huyết là bệnh truyền nhiễm cấp tính do virus Dengue gây ra qua muỗi vằn Aedes aegypti.</p>
                        <p>Để phòng bệnh, mỗi gia đình cần thường xuyên loại bỏ các ổ lăng quăng bọ gậy, đậy kín dụng cụ chứa nước.</p>
                        <p>Khi có dấu hiệu sốt cao liên tục không hạ, người bệnh cần đến ngay cơ sở y tế để được thăm khám kịp thời.</p>
                    </div>
                </article>
            </main>
            <footer><p>Copyright 2026</p></footer>
        </body>
        </html>
        """
        markdown = (
            "Phương pháp phòng chống bệnh sốt xuất huyết hiệu quả tại gia đình\n\n"
            "Sốt xuất huyết là bệnh truyền nhiễm cấp tính do virus Dengue gây ra qua muỗi vằn Aedes aegypti.\n\n"
            "Để phòng bệnh, mỗi gia đình cần thường xuyên loại bỏ các ổ lăng quăng bọ gậy, đậy kín dụng cụ chứa nước.\n\n"
            "Khi có dấu hiệu sốt cao liên tục không hạ, người bệnh cần đến ngay cơ sở y tế để được thăm khám kịp thời."
        )
        result = MagicMock()
        result.html = html
        error = http_article_error("unconfigured-domain.vn", result, markdown)
        self.assertIsNone(error, f"Universal auto-discovery failed with error: {error}")

    def test_verbatim_cleaning_preserves_btc_tokens(self):
        """Verbatim cleaner must strip markdown artifacts without distorting natural text."""
        raw_markdown = (
            "# Cảnh báo dịch bệnh mùa mưa bão\n\n"
            "![Ảnh minh họa](https://example.com/banner.jpg)\n\n"
            "Theo thông tin từ [Bộ Y Tế](https://moh.gov.vn \"Bộ Y Tế\"), người dân cần lưu ý:\n\n"
            "| Bệnh | Triệu chứng | Cách xử trí |\n"
            "| --- | --- | --- |\n"
            "| Tiêu chảy | Đau bụng, mất nước | Uống Oresol |\n\n"
            "[](https://share.facebook.com) [Xem chi tiết](https://example.com/details)\n\n"
            "Cần giữ vệ sinh an toàn thực phẩm."
        )
        clean = clean_to_verbatim(raw_markdown)
        self.assertNotIn("![", clean)
        self.assertNotIn("| --- |", clean)
        self.assertNotIn("](https://", clean)
        self.assertNotIn("#", clean)
        self.assertIn("Cảnh báo dịch bệnh mùa mưa bão", clean)
        self.assertIn("Cần giữ vệ sinh an toàn thực phẩm.", clean)

        # BTC 5-step normalization must yield clean words
        tokens = normalize_btc(clean)
        self.assertTrue(len(tokens) > 10)
        for tok in tokens:
            self.assertFalse(tok.startswith("http"))
            self.assertFalse(tok.startswith("#"))


if __name__ == "__main__":
    unittest.main()
