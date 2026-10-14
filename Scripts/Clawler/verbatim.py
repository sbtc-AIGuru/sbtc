"""Conservative, versioned conversion of extracted markup to verbatim text.

Medical symbols and ambiguous syntax are retained. All offsets downstream refer
to the returned source, never to raw crawl text.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import html
from html.parser import HTMLParser
import re

CLEANER_VERSION = "verbatim-v4"

ESCAPED_PATTERN = re.compile(r"\\([\\\x60*{}\[\]()#+\-.!_>~\"'$])")
BARE_URL_PATTERN = re.compile(r"""https?://[^\s<>()\[\]{}"'\u0080-\U0010ffff]+""", re.IGNORECASE | re.ASCII)
DATA_IMAGE_PATTERN = re.compile(r"data:image/[a-z0-9.+-]+;base64,[a-z0-9+/=]+", re.IGNORECASE | re.ASCII)
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"""</?([a-zA-Z][a-zA-Z0-9-]*)(?:\s+(?:[^<>'"]|"[^"]*"|'[^']*')*)?\s*/?>""")

UNICODE_SPACES_PATTERN = re.compile(r"[\xa0\u3000\u2000-\u200a\u202f\u205f]")
ENTITY_PATTERN = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SOFT_HYPHEN_PATTERN = re.compile(r"(?<=\w)\u00ad|\u00ad(?=\w)")
RETAINED_FORMAT_PATTERN = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
HEADER_PATTERN = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
LONGCHAU_UI_PATTERN = re.compile(r"(?m)^[ \t]*Kích thước chữ[ \t]*\n[ \t]*Mặc định[ \t]*\n[ \t]*Lớn hơn[ \t]*$(\n)?")
STRIKETHROUGH_PATTERN = re.compile(r"~~(?!\s)(.+?)(?<!\s)~~")
FENCE_PATTERN = re.compile(r"(?m)^[ \t]{0,3}(\x60{3,}|~{3,})[^\n]*\n(.*?)^[ \t]{0,3}\1[ \t]*(?:\n|$)", re.DOTALL)
CODE_SPAN_PATTERN = re.compile(r"(?<![\\\x60])(\x60+)(?!\x60)([^\n]*?)(?<![\\\x60])\1(?!\x60)")
ASTERISK_EMPHASIS_PATTERN = re.compile(r"(?<!\w)(\*{1,3})(?!\s)(.+?)(?<!\s)\1(?!\w)")
UNDERSCORE_EMPHASIS_PATTERN = re.compile(r"(?<!\w)(_{1,3})(?!\s)(.+?)(?<!\s)\1(?!\w)")

PARAGRAPH_TAGS = frozenset(("p", "div", "article", "section", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol", "table"))
INLINE_TAGS = frozenset(("a", "em", "strong", "b", "i", "u", "s", "del", "span", "sup", "sub", "small", "code", "font", "mark"))
KNOWN_TAGS = PARAGRAPH_TAGS | INLINE_TAGS | {"br", "hr", "li", "tr", "td", "th", "thead", "tbody", "img"}


class _ImageAlt(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.alt = ""

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.alt = dict(attrs).get("alt") or ""


class _Cleanup:
    def __init__(self, raw: str):
        self.actions = Counter()
        self.warnings = Counter()
        self.literals: list[str] = []
        # Pick a deterministic delimiter absent even after entity decoding.
        decoded = html.unescape(html.unescape(raw))
        self.prefix = "\ue000"
        while self.prefix in raw or self.prefix in decoded:
            self.prefix += "\ue000"

    def sub(self, pattern, replacement, text: str, action: str) -> str:
        def replace(match):
            value = replacement(match) if callable(replacement) else match.expand(replacement)
            if value != match.group(0):
                self.actions[action] += 1
            return value
        return pattern.sub(replace, text)

    def protect(self, value: str) -> str:
        index = len(self.literals)
        self.literals.append(value)
        return f"{self.prefix}{index}{self.prefix}"

    def restore(self, text: str) -> str:
        pattern = re.compile(re.escape(self.prefix) + r"(\d+)" + re.escape(self.prefix))
        return pattern.sub(lambda match: self.literals[int(match.group(1))], text)


def _html_text(text: str, state: _Cleanup) -> str:
    text = state.sub(SCRIPT_STYLE_PATTERN, " ", text, "embedded_block")
    text = state.sub(HTML_COMMENT_PATTERN, " ", text, "html_comment")
    state.warnings["incomplete_embedded_block"] += len(re.findall(r"<(?:script|style)\b|<!--", text, re.IGNORECASE))

    def strip_tag(match):
        tag = match.group(1).lower()
        markup = match.group(0)
        if tag not in KNOWN_TAGS:
            state.warnings["ambiguous_html"] += 1
            return markup
        if tag == "img":
            parser = _ImageAlt()
            parser.feed(markup)
            return parser.alt
        if tag in {"br", "hr"}:
            return "\n" if tag == "br" else "\n\n"
        if not markup.startswith("</") and tag in PARAGRAPH_TAGS:
            return "\n\n"
        if markup.startswith("</"):
            if tag in PARAGRAPH_TAGS:
                return "\n\n"
            if tag in {"li", "tr"}:
                return "\n"
            if tag in {"td", "th"}:
                return " "
        return ""

    text = state.sub(HTML_TAG_PATTERN, strip_tag, text, "html_tag")
    state.warnings["incomplete_html"] += len(re.findall(r"(?:<br|</?(?:p|div|span|img)(?=[\s/]|[^\x00-\x7f]))[^\n>]*(?:\n|$)", text, re.IGNORECASE))
    return text


def _balanced_end(text: str, start: int, opening: str, closing: str) -> int | None:
    """Bound the scanner's work; leave unsupported or incomplete markup intact."""
    depth = 0
    quote = None
    index = start
    while index < min(len(text), start + 4096):
        char = text[index]
        if char in "\r\n":
            return None
        if char == "\\":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = None
        elif opening == "(" and char in "\"'" and index > start and text[index - 1].isspace():
            quote = char
        elif char == opening:
            depth += 1
            if depth > 32:
                return None
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _reference_key(label: str) -> str:
    return " ".join(label.split()).casefold()


def _destination_valid(value: str) -> bool:
    if not value or re.fullmatch(r""""[^"]*"|'[^']*'""", value):
        return True  # Empty destination, optionally followed by a quoted title.
    match = re.fullmatch(r"""(<[^<>\s]*>|[^\s]+)(?:[ \t]+(?:"[^"]*"|'[^']*'))?[ \t]*""", value)
    if not match:
        return False
    destination = match.group(1).strip("<>")
    # Crawl4AI normally emits absolute targets. Bare words may be medical
    # parenthetical notation; keep these ambiguous "relative links" verbatim.
    return bool(re.match(r"(?:https?://|mailto:|tel:|data:image/|/|#)", destination, re.IGNORECASE))


def _remove_link_targets(text: str, state: _Cleanup, *, definitions: dict[str, str] | None = None, depth: int = 0) -> str:
    if depth >= 8:
        state.warnings["nested_markup_limit"] += 1
        return text
    text = state.sub(HTML_IMAGE_PATTERN, lambda m: _html_text(m.group(0), state), text, "html_image")
    collect_definitions = definitions is None
    definitions = {} if definitions is None else definitions

    def definition(match):
        destination = match.group(2).strip()
        if not re.match(r"<?(?:https?://|/|#)", destination, re.IGNORECASE) or not _destination_valid(destination):
            return match.group(0)
        definitions.setdefault(_reference_key(match.group(1)), destination)
        return ""

    pattern = re.compile(r"(?m)^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(.+)$")
    if collect_definitions:
        text = state.sub(pattern, definition, text, "reference_definition")
    if "[" not in text:
        return _url_targets(text, state)
    pieces = []
    index = 0
    while index < len(text):
        image = text.startswith("![", index)
        start = index + 1 if image else index
        if text[start] != "[":
            pieces.append(text[index])
            index += 1
            continue
        end = _balanced_end(text, start, "[", "]")
        if end is None:
            pieces.append(text[index])
            index += 1
            continue
        label = text[start + 1:end]
        next_index = end + 1
        action = None
        if next_index < len(text) and text[next_index] == "(":
            target_end = _balanced_end(text, next_index, "(", ")")
            if target_end is not None and _destination_valid(text[next_index + 1:target_end].strip()):
                next_index = target_end + 1
                action = "markdown_image" if image else "markdown_link"
            else:
                state.warnings["incomplete_markdown_link" if target_end is None else "ambiguous_markdown_target"] += 1
        elif next_index < len(text) and text[next_index] == "[":
            reference_end = _balanced_end(text, next_index, "[", "]")
            if reference_end is not None:
                key = _reference_key(text[next_index + 1:reference_end] or label)
                if key in definitions:
                    next_index = reference_end + 1
                    action = "reference_image" if image else "reference_link"
        elif _reference_key(label) in definitions:
            action = "reference_image" if image else "reference_link"
        if action:
            if "[" in label:
                label = _remove_link_targets(label, state, definitions=definitions, depth=depth + 1)
            pieces.append(label)
            state.actions[action] += 1
            index = next_index
        else:
            # Consume the full label so inner brackets are not reinterpreted.
            pieces.append(text[index:end + 1])
            index = end + 1
    text = "".join(pieces)
    return _url_targets(text, state)


def _url_targets(text: str, state: _Cleanup) -> str:
    def punctuation(match):
        value = match.group(0)
        # Terminal punctuation belongs to the surrounding sentence.
        return value[len(value.rstrip(".,;:!?")):]
    text = state.sub(BARE_URL_PATTERN, punctuation, text, "bare_url")
    return state.sub(DATA_IMAGE_PATTERN, "", text, "data_image")


def remove_link_targets(text: str) -> str:
    """Keep visible labels while removing recognized image and URL targets."""
    state = _Cleanup(text)
    protected = _protect_literals(text, state, unwrap_code=False)
    return state.restore(_remove_link_targets(protected, state))


def _protect_literals(text: str, state: _Cleanup, *, unwrap_code: bool = True) -> str:
    text = state.sub(FENCE_PATTERN, lambda m: state.protect(m.group(2) if unwrap_code else m.group(0)), text, "fenced_code")
    text = state.sub(CODE_SPAN_PATTERN, lambda m: state.protect(m.group(2) if unwrap_code else m.group(0)), text, "inline_code")
    text = state.sub(ESCAPED_PATTERN, lambda m: state.protect(m.group(1) if unwrap_code else m.group(0)), text, "markdown_escape")
    state.warnings["unmatched_code_marker"] += text.count(chr(96))
    state.warnings["unmatched_fence"] += len(re.findall(r"(?m)^[ \t]{0,3}~{3,}", text))
    return text


def _tables(text: str, state: _Cleanup) -> str:
    if "|" not in text:
        return text
    lines = text.split("\n")

    def cells(line):
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    index = 1
    while index < len(lines):
        alignment = cells(lines[index])
        if "|" not in lines[index] or len(alignment) < 2 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in alignment):
            index += 1
            continue
        header = lines[index - 1]
        if "|" not in header or len(cells(header)) != len(alignment):
            index += 1
            continue
        lines[index] = None
        state.actions["table_separator"] += 1
        row_index = index - 1
        while row_index < len(lines):
            if row_index == index:
                row_index += 1
                continue
            line = lines[row_index]
            if not line or "|" not in line or len(cells(line)) != len(alignment):
                break
            replacement = " ".join(cells(line))
            if replacement != line:
                state.actions["table_row"] += 1
            lines[row_index] = replacement
            row_index += 1
        index = max(index + 1, row_index)
    return "\n".join(line for line in lines if line is not None)


def _quotes(text: str, state: _Cleanup) -> str:
    pattern = re.compile(r"(?m)^[ \t]*>[ \t]?(.*)$")
    for _ in range(3):
        text = state.sub(pattern, lambda m: m.group(0) if re.match(r"^[> \t]*=?[ \t]*[-+]?\d", m.group(1)) else m.group(1), text, "markdown_quote")
    return text


def _decode_entities(text: str, state: _Cleanup) -> str:
    def decode(match):
        body = match.group(0)[1:-1]
        if not body.startswith("#") and body + ";" not in html.entities.html5:
            return match.group(0)
        return html.unescape(match.group(0))
    for _ in range(2):
        decoded = state.sub(ENTITY_PATTERN, decode, text, "html_entity")
        if decoded != text:
            state.actions["html_entity_pass"] += 1
        text = decoded
    return text


def _unicode_text(text: str, state: _Cleanup) -> str:
    if text.startswith("\ufeff"):
        state.actions["leading_bom"] += len(text) - len(text.lstrip("\ufeff"))
        text = text.lstrip("\ufeff")
    text = state.sub(re.compile(r"\r\n?"), "\n", text, "line_ending")
    text = state.sub(UNICODE_SPACES_PATTERN, " ", text, "unicode_space")
    text = state.sub(CONTROL_PATTERN, " ", text, "control_separator")
    text = state.sub(SOFT_HYPHEN_PATTERN, "", text, "soft_hyphen")
    state.warnings["retained_format_character"] += len(RETAINED_FORMAT_PATTERN.findall(text))
    state.warnings["replacement_character"] += text.count("\ufffd")
    state.warnings["unresolved_entity"] += len(ENTITY_PATTERN.findall(text))
    return text


def clean_with_report(text: str) -> tuple[str, dict]:
    """Clean one source and return deterministic transformation metadata."""
    if not isinstance(text, str):
        raise TypeError("Cleaner input must be a string")
    state = _Cleanup(text)
    source = text.lstrip("\ufeff")
    if source != text:
        state.actions["leading_bom"] += len(text) - len(source)
    source = _protect_literals(source, state)
    source = _decode_entities(source, state)
    source = _html_text(source, state)
    source = _remove_link_targets(source, state)
    source = state.sub(HEADER_PATTERN, "", source, "markdown_heading")
    source = _quotes(source, state)
    source = _tables(source, state)
    source = state.sub(LONGCHAU_UI_PATTERN, "", source, "known_ui")
    source = state.sub(STRIKETHROUGH_PATTERN, r"\1", source, "strikethrough")
    for _ in range(3):
        source = state.sub(ASTERISK_EMPHASIS_PATTERN, r"\2", source, "emphasis")
        source = state.sub(UNDERSCORE_EMPHASIS_PATTERN, r"\2", source, "emphasis")
    state.warnings["unresolved_emphasis"] += len(re.findall(r"\*{2,}|_{2,}", source))
    source = state.restore(source)
    source = _unicode_text(source, state)
    lines = []
    for line in source.splitlines():
        stripped = state.sub(re.compile(r"[ \t]+"), " ", line, "horizontal_space").strip()
        if stripped or not lines or lines[-1]:
            lines.append(stripped)
    cleaned = "\n".join(lines).strip()
    if cleaned != source:
        state.actions["line_whitespace"] += 1
    # A document consisting solely of presentation markers has no text to
    # index. Keep meaningful standalone symbols such as '+' outside this set.
    if cleaned and re.fullmatch(r"[\s#*_~\x60|:;,.!?\[\](){}<>。！？；：、-]+", cleaned):
        cleaned = ""
        state.actions["markup_only"] += 1
    report = {
        "version": CLEANER_VERSION,
        "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "output_sha256": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
        "input_chars": len(text), "output_chars": len(cleaned),
        "actions": dict(sorted(state.actions.items())),
        "warnings": [{"code": code, "count": count} for code, count in sorted(state.warnings.items()) if count],
    }
    return cleaned, report


def clean_to_verbatim(text: str) -> str:
    """Return the plain verbatim source using the same core as the report API."""
    return clean_with_report(text)[0]
