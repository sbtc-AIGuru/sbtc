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


if __name__ == "__main__":
    unittest.main()
