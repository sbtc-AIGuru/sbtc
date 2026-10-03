"""Test suite for the Verbatim Text Cleaner.
Verifies conversion of Crawl4AI markdown to raw verbatim text without distortion.
"""

import html
import re
import unicodedata


def clean_to_verbatim(text: str) -> str:
    """Transform Crawl4AI markdown text into plain verbatim text."""
    if not text:
        return ""

    # 1. Markdown images: ![alt](url) -> keep alt text
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)

    # 2. Markdown links: [text](url "title") -> keep anchor text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # 3. Headers: lines starting with #, ##, etc. -> remove #
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 4. Tables: remove table border/alignment lines | --- | --- |
    text = re.sub(r"^\s*\|?\s*[-:]+[-| :]*\|?\s*$", "", text, flags=re.MULTILINE)
    # Replace table pipe delimiters with space
    text = re.sub(r"\|", " ", text)

    # 5. Bold, italics, strikethrough, inline code: remove formatting markers (*, _, ~, `)
    # Stripping these punctuation characters preserves all words, including nested _**word**_
    text = re.sub(r"[*_~`]", "", text)

    # 6. Unescape backslash escapes (\", \*, \[, \])
    text = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>~\"'$])", r"\1", text)

    # 7. Unescape HTML entities & clean residual broken HTML tags
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"<br\b[^>]*>?|<br(?=[^\s>])", " ", text, flags=re.IGNORECASE)

    # 8. Collapse spaces per line while keeping line breaks
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for l in lines:
        if not l:
            if not prev_empty:
                cleaned_lines.append("")
                prev_empty = True
        else:
            cleaned_lines.append(l)
            prev_empty = False

    return "\n".join(cleaned_lines).strip()


def test_verbatim_cleaner():
    sample = """### 82 ca mắc ho gà: Chỉ có vắc xin là cách phòng bệnh tốt nhất
_**Từ đầu năm đến nay, nước ta đã ghi nhận 82 trường hợp**_
![bệnh ho gà](http://suckhoedoisong.vn/ho_ga3.jpg)
Khuyến cáo tiêm virut [viêm gan b](http://suckhoedoisong.vn/viem-gan-b "Viêm gan B") và Haemophilus.
| Lịch tiêm chủng: | Ghi chú |
| --- | --- |
| Mũi 1: 2 tháng | Bắt buộc |
<br抑郁症的自我疗法
"""
    result = clean_to_verbatim(sample)
    print("--- INPUT SAMPLE ---")
    print(sample)
    print("--- CLEANED VERBATIM RESULT ---")
    print(result)

    # Check assertions
    assert "###" not in result
    assert "_**" not in result
    assert "![bệnh ho gà]" not in result
    assert "bệnh ho gà" in result
    assert "[viêm gan b]" not in result
    assert "viêm gan b và Haemophilus" in result
    assert "---" not in result
    assert "|" not in result
    assert "Lịch tiêm chủng: Ghi chú" in result
    assert "Mũi 1: 2 tháng Bắt buộc" in result
    print("\n[ALL VERBATIM CLEANER ASSERTIONS PASSED!]")


if __name__ == "__main__":
    test_verbatim_cleaner()
