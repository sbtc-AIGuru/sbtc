"""Transform Crawl4AI markdown text into plain verbatim text.
Eliminates markdown syntax distortion for accurate biomedical token LCS overlap.
"""

from __future__ import annotations

import html
import re

ESCAPED_PATTERN = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~\"'$])")
PROTECTED_PATTERN = re.compile(r"\x00([0-9a-f]{2})\x00")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\[[^\]]*\]")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_DEFINITION_PATTERN = re.compile(r"^\s*\[[^\]]+\]:\s*https?://[^\n]*$", re.MULTILINE | re.IGNORECASE)
BARE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
DATA_IMAGE_PATTERN = re.compile(r"data:image/[^\s<>)\]]+", re.IGNORECASE)
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def remove_link_targets(text: str) -> str:
    """Keep visible link labels while removing image and URL targets."""
    text = HTML_IMAGE_PATTERN.sub("", text)
    text = MARKDOWN_IMAGE_PATTERN.sub(lambda match: match.group(1), text)
    text = REFERENCE_IMAGE_PATTERN.sub(lambda match: match.group(1), text)
    text = MARKDOWN_LINK_PATTERN.sub(lambda match: match.group(1), text)
    text = REFERENCE_DEFINITION_PATTERN.sub("", text)
    text = BARE_URL_PATTERN.sub("", text)
    return DATA_IMAGE_PATTERN.sub("", text)


def clean_to_verbatim(text: str) -> str:
    """Transform Crawl4AI markdown text into plain verbatim text."""
    if not text:
        return ""

    # 1. Unescape HTML entities first so entities inside links/text are decoded
    text = html.unescape(text)

    # 2. Clean broken unclosed <br tags (common in older Chinese forums like 120ask)
    text = re.sub(r"<br\b[^>]*>?|<br(?=[^\s>])", " ", text, flags=re.IGNORECASE)

    # 3. Strip valid HTML tags (<p>, <div>, etc.) without swallowing nested content
    text = re.sub(r"<[^<>]+>", " ", text)

    # 4. Protect backslash-escaped characters so their literal forms are preserved
    text = ESCAPED_PATTERN.sub(lambda m: f"\x00{ord(m.group(1)):02x}\x00", text)

    # 5. Keep visible labels, but discard link and image locations.
    text = remove_link_targets(text)

    # 7. Headers: lines starting with #, ##, etc. -> remove #
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 8. Tables: remove table border/alignment lines | --- | --- |
    text = re.sub(r"^\s*\|?\s*[-:]+[-| :]*\|?\s*$", "", text, flags=re.MULTILINE)
    # Replace table pipe delimiters with space
    text = re.sub(r"\|", " ", text)

    # 9. Bold, italics, strikethrough, inline code: remove formatting markers (*, _, ~, `)
    # Stripping these punctuation characters preserves all words, including nested _**word**_
    text = re.sub(r"[*_~`]", "", text)

    # 10. Restore protected backslash-escaped characters
    text = PROTECTED_PATTERN.sub(lambda m: chr(int(m.group(1), 16)), text)

    # 11. Collapse spaces per line while keeping line breaks
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned_lines.append("")
                prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False

    return "\n".join(cleaned_lines).strip()
