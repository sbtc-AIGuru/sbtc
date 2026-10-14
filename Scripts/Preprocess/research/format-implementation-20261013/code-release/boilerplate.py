"""Conservative, auditable boilerplate span detection for crawled medical text."""

from __future__ import annotations

import re


TAIL_MARKERS = (
    ("其他人还在看", "related_content_tail", "related-content marker"),
    ("中药方大全 按拼音查询", "alphabetical_navigation_tail", "alphabetical medicine navigation"),
    ("点击字母查看完整药方列表", "alphabetical_navigation_tail", "alphabetical medicine navigation"),
)
AUDIO_ERROR_RE = re.compile(r"(?m)^[^\n]*浏览器不支持\s*audio\s*元素[^\n]*$")
PHONE_RE = re.compile(r"(?:\+?\d[\d ()/.-]{7,}\d)")


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _span(text: str, start: int, end: int, rule_id: str, reason: str) -> dict:
    start, end = _trimmed_span(text, start, end)
    return {
        "rule_id": rule_id,
        "start_char": start,
        "end_char": end,
        "confidence": "high",
        "reason": reason,
        "retrieval_eligible": False,
        "text": text[start:end],
    }


def _booking_tail(text: str) -> dict | None:
    lower = text.lower()
    markers = ("mời bạn xem thêm thông tin", "để tìm hiểu thêm thông tin")
    starts = [lower.find(marker) for marker in markers if lower.find(marker) >= 0]
    if not starts:
        return None
    start = min(starts)
    if start < len(text) * 0.55:
        return None
    tail = lower[start:]
    signals = sum(term in tail for term in ("hotline", "zalo", "website:", "facebook:", "mua thuốc online", "đt:"))
    signals += bool(PHONE_RE.search(tail))
    if signals < 3:
        return None
    return _span(text, start, len(text), "booking_contact_tail", "promotional booking/contact block at document tail")


def _department_navigation(text: str) -> dict | None:
    marker = "按重点科室分类的医院列表有："
    marker_start = text.find(marker)
    if marker_start < 0:
        return None
    line_start = text.find("\n", marker_start + len(marker))
    if line_start < 0:
        return None
    line_start += 1
    line_end = text.find("\n", line_start)
    if line_end < 0:
        line_end = len(text)
    candidate = text[line_start:line_end]
    if candidate.count("科") < 30:
        return None
    return _span(text, line_start, line_end, "department_navigation_block", "dense hospital-department navigation list")


def detect_boilerplate(text: str, url: str = "") -> list[dict]:
    """Return high-confidence spans to exclude from retrieval while preserving source."""
    if not text:
        return []
    candidates: list[dict] = []
    for marker, rule_id, reason in TAIL_MARKERS:
        start = text.find(marker)
        if start >= 0:
            candidates.append(_span(text, start, len(text), rule_id, reason))
    arrow = re.search(r"(?m)^\s*->\s+", text)
    if arrow and arrow.start() >= len(text) * 0.7:
        candidates.append(_span(text, arrow.start(), len(text), "related_arrow_tail", "related-link and byline tail"))
    booking = _booking_tail(text)
    if booking:
        candidates.append(booking)
    department_navigation = _department_navigation(text)
    if department_navigation:
        candidates.append(department_navigation)
    for match in AUDIO_ERROR_RE.finditer(text):
        candidates.append(_span(text, match.start(), match.end(), "unsupported_audio_line", "browser audio fallback text"))

    merged: list[dict] = []
    for candidate in sorted(candidates, key=lambda item: (item["start_char"], item["end_char"])):
        if candidate["start_char"] >= candidate["end_char"]:
            continue
        if merged and candidate["start_char"] <= merged[-1]["end_char"]:
            if candidate["end_char"] > merged[-1]["end_char"]:
                merged[-1]["end_char"] = candidate["end_char"]
                merged[-1]["text"] = text[merged[-1]["start_char"]:candidate["end_char"]]
            continue
        merged.append(candidate)
    return merged
