"""Unit tests for Universal Quality Gatekeeper (Scripts/Clawler/quality.py).
Tests DOM Purification, Interior Statistical Sampling, and Universal Auto-Discovery.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from quality import http_article_error


class MockResult:
    def __init__(self, html: str):
        self.html = html


class TestQualityUniversal(unittest.TestCase):
    """Test suite for universal content validation and auto-discovery."""

    def test_tc01_real_article_with_breadcrumbs_and_footer(self):
        """TC-01: An article with breadcrumbs at start and footer at end should pass."""
        html = (
            "<html><body>"
            "<div class='detail__contenent-main'>"
            "<header><h1>Tiêu đề bài viết y tế phòng ngừa ung thư</h1></header>"
            "<div class='detail-content'>"
            "<div class='breadcrumb'>Trang chủ > Sức khỏe > Ung bướu</div>"
            "<p>Đoạn mở đầu: Ung thư dạ dày là một trong những bệnh lý phổ biến nhất hiện nay.</p>"
            "<p>Đoạn thân bài: Chế độ ăn uống nhiều muối, thực phẩm lên men và thói quen hút thuốc là nguy cơ hàng đầu.</p>"
            "<p>Đoạn hướng dẫn: Khuyến cáo khám sức khỏe định kỳ và nội soi dạ dày khi có triệu chứng đau thượng vị kéo dài.</p>"
            "<p>Đoạn kết luận: Phát hiện sớm ở giai đoạn đầu giúp tỷ lệ điều trị thành công đạt trên chín mươi phần trăm.</p>"
            "<div class='footer-tags'>Chuyên mục: Ung bướu, Dạ dày, Tiêu hóa. Bản quyền bài viết thuộc về tòa soạn.</div>"
            "</div></div></body></html>"
        )
        # Markdown extracted by clean crawler (noise stripped)
        markdown = (
            "Tiêu đề bài viết y tế phòng ngừa ung thư\n\n"
            "Đoạn mở đầu: Ung thư dạ dày là một trong những bệnh lý phổ biến nhất hiện nay.\n\n"
            "Đoạn thân bài: Chế độ ăn uống nhiều muối, thực phẩm lên men và thói quen hút thuốc là nguy cơ hàng đầu.\n\n"
            "Đoạn hướng dẫn: Khuyến cáo khám sức khỏe định kỳ và nội soi dạ dày khi có triệu chứng đau thượng vị kéo dài.\n\n"
            "Đoạn kết luận: Phát hiện sớm ở giai đoạn đầu giúp tỷ lệ điều trị thành công đạt trên chín mươi phần trăm."
        )
        result = MockResult(html)
        error = http_article_error("suckhoedoisong.vn", result, markdown)
        self.assertIsNone(error, f"Expected None but got: {error}")

    def test_tc02_truncated_article_fails(self):
        """TC-02: An HTTP article truncated midway (missing 60% of body) should fail and trigger browser fallback."""
        html = (
            "<html><body>"
            "<div class='detail__contenent-main'>"
            "<header><h1>Bệnh viêm gan siêu vi B và phác đồ điều trị</h1></header>"
            "<div class='detail-content'>"
            "<p>Phần 1: Giới thiệu chung về virus HBV và đường lây truyền qua máu, tình dục và từ mẹ sang con.</p>"
            "<p>Phần 2: Triệu chứng lâm sàng gồm mệt mỏi, chán ăn, vàng da, vàng mắt và nước tiểu sẫm màu.</p>"
            "<p>Phần 3: Các xét nghiệm chẩn đoán bao gồm HBsAg, HBeAg, tải lượng HBV-DNA và men gan AST/ALT.</p>"
            "<p>Phần 4: Phác đồ dùng thuốc kháng virus Tenofovir hoặc Entecavir kéo dài suốt đời để ức chế sao chép.</p>"
            "<p>Phần 5: Theo dõi xơ gan và tầm soát định kỳ ung thư biểu mô tế bào gan bằng siêu âm và AFP mỗi 6 tháng.</p>"
            "</div></div></body></html>"
        )
        # Truncated markdown containing only Part 1
        truncated_markdown = (
            "Bệnh viêm gan siêu vi B và phác đồ điều trị\n\n"
            "Phần 1: Giới thiệu chung về virus HBV và đường lây truyền qua máu, tình dục và từ mẹ sang con."
        )
        result = MockResult(html)
        error = http_article_error("suckhoedoisong.vn", result, truncated_markdown)
        self.assertIsNotNone(error, "Truncated article should be rejected")

    def test_tc03_missing_or_wrong_title_fails(self):
        """TC-03: Missing or mismatched title should be rejected."""
        html = (
            "<html><body>"
            "<div class='detail__contenent-main'>"
            "<header><h1>Tiêu đề thực sự trong bài viết gốc</h1></header>"
            "<div class='detail-content'>"
            "<p>Nội dung chi tiết bài viết y khoa hướng dẫn điều trị bệnh và phòng ngừa biến chứng nguy hiểm.</p>"
            "</div></div></body></html>"
        )
        mismatched_markdown = (
            "Tiêu đề hoàn toàn khác không liên quan\n\n"
            "Nội dung chi tiết bài viết y khoa hướng dẫn điều trị bệnh và phòng ngừa biến chứng nguy hiểm."
        )
        result = MockResult(html)
        error = http_article_error("suckhoedoisong.vn", result, mismatched_markdown)
        self.assertIsNotNone(error, "Mismatched title should be rejected")

    def test_tc04_short_error_page_fails(self):
        """TC-04: Short or error page (< 80 chars) should be rejected."""
        html = "<html><body><h1>Lỗi 404</h1><p>Bài viết không tìm thấy</p></body></html>"
        result = MockResult(html)
        error = http_article_error("dantri.com.vn", result, "Lỗi 404: Bài viết không tìm thấy")
        self.assertIsNotNone(error, "Short error page should be rejected")

    def test_tc05_mediawiki_structure_passes(self):
        """TC-05: Real MediaWiki articles (a-hospital.com, zhongyibaodian.net) with sub-navigation should pass."""
        html = (
            "<html><body>"
            "<div id='content'>"
            "<h1 id='firstHeading' class='firstHeading'>地中海贫血</h1>"
            "<div id='bodyContent'>"
            "<div id='siteSub'>来自A+医学百科</div>"
            "<div id='contentSub'>重定向自α地中海贫血</div>"
            "<div id='toc'><h2>目录</h2><ul><li>1 简介</li></ul></div>"
            "<p>地中海贫血是一组遗传性溶血性贫血疾病。由于珠蛋白基因缺陷使血红蛋白中的珠蛋白肽链合成减少或不能合成。</p>"
            "<p>临床表现根据病情轻重可分为轻型、中间型和重型。重型患者出生数日即出现贫血、肝脾肿大及黄疸。</p>"
            "<p>实验室检查可见红细胞渗透脆性降低，血红蛋白电泳异常。治疗方案包括终身输血及除铁治疗。</p>"
            "<div id='catlinks'>分类: 血液内科疾病 | 遗传病</div>"
            "</div></div></body></html>"
        )
        markdown = (
            "地中海贫血\n\n"
            "地中海贫血是一组遗传性溶血性贫血疾病。由于珠蛋白基因缺陷使血红蛋白中的珠蛋白肽链合成减少或不能合成。\n\n"
            "临床表现根据病情轻重可分为轻型、中间型和重型。重型患者出生数日即出现贫血、肝脾肿大及黄疸。\n\n"
            "实验室检查可见红细胞渗透脆性降低，血红蛋白电泳异常。治疗方案包括终身输血及除铁治疗。"
        )
        result = MockResult(html)
        error = http_article_error("a-hospital.com", result, markdown)
        self.assertIsNone(error, f"MediaWiki article should pass HTTP validation, got error: {error}")

    def test_tc06_universal_autodiscovery_passes(self):
        """TC-06: Unconfigured new domain with standard HTML article should pass via Auto-Discovery."""
        html = (
            "<html><body>"
            "<header><h1>Hướng dẫn dinh dưỡng cho người bệnh tiểu đường type 2</h1></header>"
            "<main><article>"
            "<p>Nguyên tắc dinh dưỡng cơ bản cho người đái tháo đường là kiểm soát lượng carbohydrate nạp vào hàng ngày.</p>"
            "<p>Nên ưu tiên các loại ngũ cốc nguyên hạt, rau xanh nhiều chất xơ hòa tan và hạn chế đường đơn tinh luyện.</p>"
            "<p>Chia nhỏ các bữa ăn và duy trì vận động thể chất ít nhất ba mươi phút mỗi ngày giúp ổn định đường huyết.</p>"
            "</article></main>"
            "</body></html>"
        )
        markdown = (
            "Hướng dẫn dinh dưỡng cho người bệnh tiểu đường type 2\n\n"
            "Nguyên tắc dinh dưỡng cơ bản cho người đái tháo đường là kiểm soát lượng carbohydrate nạp vào hàng ngày.\n\n"
            "Nên ưu tiên các loại ngũ cốc nguyên hạt, rau xanh nhiều chất xơ hòa tan và hạn chế đường đơn tinh luyện.\n\n"
            "Chia nhỏ các bữa ăn và duy trì vận động thể chất ít nhất ba mươi phút mỗi ngày giúp ổn định đường huyết."
        )
        result = MockResult(html)
        # Domain NOT in ARTICLE_LAYOUTS
        error = http_article_error("tapchiyhoctphcm.vn", result, markdown)
        self.assertIsNone(error, f"Universal Auto-Discovery should pass standard article, got: {error}")

    def test_tc07_universal_autodiscovery_spa_fallback(self):
        """TC-07: Unconfigured domain that is an empty SPA shell should be rejected for browser fallback."""
        html = "<html><body><div id='root'></div><script src='/bundle.js'></script></body></html>"
        result = MockResult(html)
        error = http_article_error("unconfigured-spa-domain.com", result, "")
        self.assertIsNotNone(error, "Empty SPA shell must be rejected to trigger browser fallback")


if __name__ == "__main__":
    unittest.main()
