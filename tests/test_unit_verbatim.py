"""Unit tests for the verbatim text cleaner module (Scripts/Clawler/verbatim.py)."""

from __future__ import annotations

import html
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))


class TestVerbatimCleaner(unittest.TestCase):
    """Test every transformation rule in verbatim cleaning."""

    def setUp(self):
        # We will import clean_to_verbatim from verbatim.py once implemented.
        # If verbatim.py is not yet implemented, import will raise ImportError.
        try:
            from verbatim import clean_to_verbatim
            self.clean = clean_to_verbatim
        except ImportError:
            self.clean = None

    def _clean(self, text: str) -> str:
        if self.clean is None:
            self.fail("verbatim.py is not implemented yet")
        return self.clean(text)

    def test_empty_and_whitespace(self):
        """Test handling of empty or whitespace-only inputs."""
        self.assertEqual(self._clean(""), "")
        self.assertEqual(self._clean("   \n\t  \n  "), "")

    def test_markdown_links(self):
        """Markdown links must be stripped to display anchor text only, or dropped if empty []."""
        sample = 'Sử dụng [thuốc Paracetamol](https://example.com/thuoc "Hạ sốt") liều 500mg.'
        expected = "Sử dụng thuốc Paracetamol liều 500mg."
        self.assertEqual(self._clean(sample), expected)

        sample_empty = 'Sử dụng [](https://example.com/thuoc "Không text") liều 500mg.'
        expected_empty = "Sử dụng liều 500mg."
        self.assertEqual(self._clean(sample_empty), expected_empty)

    def test_markdown_images(self):
        """Markdown images must retain alt text or be removed."""
        sample = 'Triệu chứng: ![vết loét da](https://example.com/anh.jpg) đỏ tấy.'
        expected = "Triệu chứng: vết loét da đỏ tấy."
        self.assertEqual(self._clean(sample), expected)

        sample_no_alt = 'Triệu chứng: ![](https://example.com/anh.jpg) đỏ tấy.'
        expected_no_alt = "Triệu chứng: đỏ tấy."
        self.assertEqual(self._clean(sample_no_alt), expected_no_alt)

    def test_image_links_and_bare_urls_are_removed(self):
        sample = (
            "Dấu hiệu: ![ảnh tổn thương](https://cdn.example.com/image_(1).jpg) "
            "[điều trị](https://example.com/guide) và "
            "https://cdn.example.com/second.webp?width=400"
        )
        result = self._clean(sample)
        self.assertIn("ảnh tổn thương", result)
        self.assertIn("điều trị", result)
        self.assertNotIn("http", result)
        self.assertNotIn("![", result)

    def test_reference_image_keeps_alt_without_url(self):
        sample = "Triệu chứng ![sưng đỏ][figure]\n[figure]: https://cdn.example.com/one.png"
        self.assertEqual(self._clean(sample), "Triệu chứng sưng đỏ")

    def test_inline_image_data_is_not_kept(self):
        sample = "Dấu hiệu sưng đỏ ![](data:image/png;base64,AAABBB) rõ rệt."
        self.assertEqual(self._clean(sample), "Dấu hiệu sưng đỏ rõ rệt.")

    def test_headers(self):
        """Header hashes (#, ##, ...) at line beginnings must be stripped."""
        sample = "# Tiêu đề 1\n## Tiêu đề 2\n###### Tiêu đề 6\nNội dung bài viết."
        expected = "Tiêu đề 1\nTiêu đề 2\nTiêu đề 6\nNội dung bài viết."
        self.assertEqual(self._clean(sample), expected)

    def test_nested_bold_and_italics(self):
        """Nested formatting markers like _**word**_ must be stripped without dropping words."""
        sample = "_**Từ đầu năm đến nay**_, nước ta ghi nhận **82 ca *nhiễm khuẩn***."
        expected = "Từ đầu năm đến nay, nước ta ghi nhận 82 ca nhiễm khuẩn."
        self.assertEqual(self._clean(sample), expected)

    def test_markdown_tables(self):
        """Table separators must be stripped and cell delimiters replaced with space."""
        sample = (
            "| Lịch tiêm | Ghi chú |\n"
            "| :--- | ---: |\n"
            "| Mũi 1 | 2 tháng tuổi |"
        )
        result = self._clean(sample)
        self.assertNotIn("|", result)
        self.assertNotIn("---", result)
        self.assertIn("Lịch tiêm Ghi chú", result)
        self.assertIn("Mũi 1 2 tháng tuổi", result)

    def test_escaped_characters(self):
        r"""Backslash escapes like \*, \[, \], \" must be restored."""
        sample = r'Chỉ số \*SCC\* \[dưới 1.5\] và \"bình thường\".'
        expected = 'Chỉ số *SCC* [dưới 1.5] và "bình thường".'
        self.assertEqual(self._clean(sample), expected)

    def test_broken_html_tags(self):
        """Old Chinese forum tags like <br抑郁症 and <br/> must be cleaned."""
        sample = "Trước đó bị sốt.<br抑郁症的自我疗法<br/>Khỏi bệnh."
        result = self._clean(sample)
        self.assertNotIn("<br", result)
        self.assertIn("抑郁症的自我疗法", result)
        self.assertIn("Khỏi bệnh", result)

    def test_html_entities(self):
        """HTML entities like &amp;, &quot;, &lt;, &gt;, &#39; must be unescaped."""
        sample = "Bệnh nhân &quot;A&quot; có chỉ số &lt; 0.10 U/L &amp; âm tính."
        expected = 'Bệnh nhân "A" có chỉ số < 0.10 U/L & âm tính.'
        self.assertEqual(self._clean(sample), expected)

    def test_medical_comparisons_do_not_remove_intervening_paragraphs(self):
        sample = (
            "Liều dùng cho trẻ <5 tuổi cần được bác sĩ chỉ định.\n\n"
            "Theo dõi huyết áp <90/60 mmHg và các triệu chứng liên quan.\n\n"
            "Nhóm >65 tuổi cần theo dõi định kỳ. <strong>Giữ nguyên lời khuyên.</strong>"
        )
        cleaned = self._clean(sample)
        self.assertIn("<5 tuổi", cleaned)
        self.assertIn("<90/60 mmHg", cleaned)
        self.assertIn(">65 tuổi", cleaned)
        self.assertIn("các triệu chứng liên quan", cleaned)
        self.assertIn("Giữ nguyên lời khuyên.", cleaned)
        self.assertNotIn("<strong>", cleaned)

    def test_paragraph_structure_preserved(self):
        """Paragraph breaks (\n\n) must be preserved while intra-line spaces are collapsed."""
        sample = "Đoạn 1 chứa   nhiều    khoảng trắng.\n\n\n\nĐoạn 2 sau khoảng cách."
        expected = "Đoạn 1 chứa nhiều khoảng trắng.\n\nĐoạn 2 sau khoảng cách."
        self.assertEqual(self._clean(sample), expected)

    def test_preserve_medical_identifiers_with_underscores(self):
        """Medical gene, protein, and lab identifiers with underscores must not be stripped."""
        sample = "Bệnh nhân có chỉ số TNF_alpha, IL_6 và anti_HCV âm tính. Gen miR_126 bình thường."
        expected = "Bệnh nhân có chỉ số TNF_alpha, IL_6 và anti_HCV âm tính. Gen miR_126 bình thường."
        self.assertEqual(self._clean(sample), expected)

    def test_preserve_medical_dosage_with_tilde(self):
        """Medical dosage ranges and approximation tildes must be preserved."""
        sample = "Dùng 3~5 ngày hoặc liều 500~1000mg/ngày, nhiệt độ ~37 độ C."
        expected = "Dùng 3~5 ngày hoặc liều 500~1000mg/ngày, nhiệt độ ~37 độ C."
        self.assertEqual(self._clean(sample), expected)

    def test_strikethrough_markdown_removal(self):
        """Double-tilde markdown strikethrough ~~text~~ must be stripped while keeping text."""
        sample = "~~Thuốc cũ không dùng~~ thay bằng Paracetamol 500mg."
        expected = "Thuốc cũ không dùng thay bằng Paracetamol 500mg."
        self.assertEqual(self._clean(sample), expected)

    def test_blockquote_vs_math_comparison(self):
        """Markdown blockquote > at line start must be stripped, while math > is preserved."""
        sample = "> Lưu ý: Uống thuốc sau ăn.\nChỉ số pH > 7.0 là môi trường kiềm."
        expected = "Lưu ý: Uống thuốc sau ăn.\nChỉ số pH > 7.0 là môi trường kiềm."
        self.assertEqual(self._clean(sample), expected)

    def test_unicode_nfkc_and_spaces(self):
        """Unicode space normalization unifies non-breaking spaces and fullwidth spaces to standard spaces."""
        sample = "Uống&nbsp;1/2&nbsp;viên hoặc ½ viên\u3000(hàng ngày)."
        expected = "Uống 1/2 viên hoặc ½ viên (hàng ngày)."
        self.assertEqual(self._clean(sample), expected)

    def test_script_style_comment_removal(self):
        """Script tags, style tags, and HTML comments must be completely removed."""
        sample = "Triệu chứng sốt.<script>var a = 1;</script><!-- ghi chú --> Cần nhập viện.<style>.red {color:red;}</style>"
        expected = "Triệu chứng sốt. Cần nhập viện."
        self.assertEqual(self._clean(sample), expected)

    def test_ui_noise_longchau(self):
        """Long Chau UI button noise blocks must be removed."""
        sample = "15 thực phẩm giảm cân\nKích thước chữ\nMặc định\nLớn hơn\nNội dung bài viết."
        expected = "15 thực phẩm giảm cân\nNội dung bài viết."
        self.assertEqual(self._clean(sample), expected)

    def test_diverse_biomedical_identifiers(self):
        """Ensure diverse genetic, viral, and biochemical identifiers with underscores are preserved."""
        samples = [
            ("Gen SARS_CoV_2 và BRCA1_2 có đột biến.", "Gen SARS_CoV_2 và BRCA1_2 có đột biến."),
            ("Kết quả HBeAg_positive và miR_21_5p tăng cao.", "Kết quả HBeAg_positive và miR_21_5p tăng cao."),
            ("Đo lường CYP2C19_2 và anti_HAV_IgM trong huyết thanh.", "Đo lường CYP2C19_2 và anti_HAV_IgM trong huyết thanh."),
            ("Chỉ số (anti_HBs_positive) và [TNF_alpha] được ghi nhận.", "Chỉ số (anti_HBs_positive) và [TNF_alpha] được ghi nhận."),
            ("Đánh giá **chỉ số TNF_alpha** trong máu.", "Đánh giá chỉ số TNF_alpha trong máu."),
            ("Xem bài về [xét nghiệm anti_HCV](https://example.com/hcv).", "Xem bài về xét nghiệm anti_HCV."),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_complex_dosage_and_ranges(self):
        """Ensure single-tilde medical dosages and tildes inside strikethrough are handled accurately."""
        samples = [
            ("Liều 0.5~1.0 mg/kg, uống 2~3 lần/ngày trong 7~10 ngày.", "Liều 0.5~1.0 mg/kg, uống 2~3 lần/ngày trong 7~10 ngày."),
            ("Dung tích 10~20ml, nhiệt độ 38.5~39°C, chiếm ~20%.", "Dung tích 10~20ml, nhiệt độ 38.5~39°C, chiếm ~20%."),
            ("Cần khoảng ~5 người, uống 1~2 viên/lần.", "Cần khoảng ~5 người, uống 1~2 viên/lần."),
            ("~~Dùng 10~15 ngày~~ Dùng 3~5 ngày.", "Dùng 10~15 ngày Dùng 3~5 ngày."),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_deeply_nested_emphasis_combinations(self):
        """Ensure multi-level and chained markdown emphasis delimiters are cleanly stripped."""
        samples = [
            ("***rất quan trọng*** đối với sức khỏe.", "rất quan trọng đối với sức khỏe."),
            ("**bệnh nhân *sốt cao* liên tục** cần nhập viện.", "bệnh nhân sốt cao liên tục cần nhập viện."),
            ("*bệnh nhân **sốt cao** liên tục* cần nhập viện.", "bệnh nhân sốt cao liên tục cần nhập viện."),
            ("*Thuốc A* và **Thuốc B** cùng ***Thuốc C*** phối hợp.", "Thuốc A và Thuốc B cùng Thuốc C phối hợp."),
            ("_triệu chứng:_ đau ngực, _nguyên nhân:_ sốt cao.", "triệu chứng: đau ngực, nguyên nhân: sốt cao."),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_complex_markdown_links_and_images(self):
        """Ensure markdown links with titles, nested formatting, brackets, or empty anchors are parsed cleanly."""
        samples = [
            ('[thuốc A](http://link.com "tiêu đề bài viết") dùng hạ sốt.', "thuốc A dùng hạ sốt."),
            ("[**thuốc A** và *thuốc B*](http://link.com) hiệu quả.", "thuốc A và thuốc B hiệu quả."),
            ("[vitamin B1 (thiamin)](http://link.com) bổ sung dinh dưỡng.", "vitamin B1 (thiamin) bổ sung dinh dưỡng."),
            ("Uống [](http://empty.com) liều 500mg.", "Uống liều 500mg."),
            ("Xem chi tiết tại https://example.com/article?id=10&ref=med ngay.", "Xem chi tiết tại ngay."),
            ("![biểu đồ nhịp tim (ECG)](http://img.com/ecg.png) đo được.", "biểu đồ nhịp tim (ECG) đo được."),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_mathematical_comparisons_mixed_with_html(self):
        """Ensure mathematical comparison operators (<, >) are preserved while HTML tags are stripped."""
        samples = [
            ("<p>Chỉ số p < 0.05 và OR > 1.5 có ý nghĩa thống kê.</p>", "Chỉ số p < 0.05 và OR > 1.5 có ý nghĩa thống kê."),
            ("Khoảng biến thiên 0 < x < 10.", "Khoảng biến thiên 0 < x < 10."),
            ("Giữ pH > 7.35 và pH < 7.45 ổn định.", "Giữ pH > 7.35 và pH < 7.45 ổn định."),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_html_entities_and_multiline_style_script(self):
        """Ensure diverse entities and multiline style/script blocks are cleanly unescaped and stripped."""
        samples = [
            ("Chỉ số &plusmn; 5% và liều &le; 100mg.", "Chỉ số ± 5% và liều ≤ 100mg."),
            ("Bệnh nhân có chỉ số &amp;lt; 0.10 U/L &amp; âm tính.", "Bệnh nhân có chỉ số < 0.10 U/L & âm tính."),
            ("<style>.cls { color: blue; }\nbody { margin: 0; }</style>\nNội dung chính.\n<script>\nconsole.log(1);\n</script>", "Nội dung chính."),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_multiline_blockquotes_and_formatted_tables(self):
        """Ensure multiline blockquotes and markdown tables with bold cells are preserved as clean text lines."""
        samples = [
            ("> Đoạn 1 trích dẫn.\n> Đoạn 2 trích dẫn.", "Đoạn 1 trích dẫn.\nĐoạn 2 trích dẫn."),
            ("| Xét nghiệm | Kết quả |\n| --- | --- |\n| **Bạch cầu** | 8.5 G/L |", "Xét nghiệm Kết quả\nBạch cầu 8.5 G/L"),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)

    def test_multilingual_chinese_vietnamese(self):
        """Ensure multilingual Chinese/Vietnamese texts with fullwidth spaces and punctuation are preserved."""
        samples = [
            ("慢性咽炎 có thể dùng Paracetamol 500mg không?", "慢性咽炎 có thể dùng Paracetamol 500mg không?"),
            ("医生回答：建议服用头孢克肟。　注意休息。", "医生回答：建议服用头孢克肟。 注意休息。"),
        ]
        for inp, exp in samples:
            with self.subTest(inp=inp):
                self.assertEqual(self._clean(inp), exp)


if __name__ == "__main__":
    unittest.main()
