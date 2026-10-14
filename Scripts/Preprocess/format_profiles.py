"""Content evidence and exact source spans for deterministic format profiles.

Rules are deliberately conservative. Confidence is a rule strength, not a
calibrated probability; unknown language and flattened layout stay explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from bisect import bisect_right
import re
from urllib.parse import urlparse

from sbtc.Scripts.Preprocess.boilerplate import detect_boilerplate, _span
from sbtc.Scripts.Preprocess.chunking import count_units, _period_is_boundary

PROFILE_VERSION = "format-v2"
CRAWL_ERROR_PREFIX = "Crawl4AI Error: This page is not fully supported."
# Labels observed in test_20k PubMed, not arbitrary uppercase statistics such as CI/OR/ES.
ABSTRACT_LABELS = (
    "BACKGROUND", "INTRODUCTION", "OBJECTIVE", "OBJECTIVES", "PURPOSE", "AIM", "AIMS", "METHOD", "METHODS",
    "MATERIALS AND METHODS", "MATERIAL AND METHODS", "PATIENTS AND METHODS", "METHODS AND RESULTS",
    "RESULT", "RESULTS", "CONCLUSION", "CONCLUSIONS", "DISCUSSION", "SIGNIFICANCE",
    "FINDINGS", "INTERPRETATION", "FUNDING", "MAIN RESULTS", "SEARCH METHODS", "SELECTION CRITERIA",
    "DATA COLLECTION AND ANALYSIS", "DESIGN", "SETTING", "SETTINGS", "PARTICIPANTS", "INTERVENTIONS",
    "STUDY DESIGN", "STUDY DESIGN, SIZE, DURATION", "DESIGN, SETTINGS, AND PARTICIPANTS",
    "DESIGN, SETTING, AND PARTICIPANTS", "OUTCOMES", "UNLABELLED", "RATIONALE", "LIMITATIONS",
    "CASE PRESENTATION", "CASE REPORT", "CASE SUMMARY", "SUMMARY", "SUMMARY ANSWER", "STUDY QUESTION",
    "WHAT IS KNOWN ALREADY", "WIDER IMPLICATIONS OF THE FINDINGS", "MAIN RESULTS AND THE ROLE OF CHANCE",
    "TRIAL REGISTRATION", "TRIAL REGISTRATION NUMBER", "PURPOSE OF REVIEW", "RECENT FINDINGS", "IMPORTANCE",
    "LESSONS", "METHODOLOGY", "CONCLUSIONS AND RELEVANCE", "MAIN OUTCOME MEASURES",
    "RÉSULTATS", "RESULTADOS", "OBJETIVO", "OBJETIVOS", "CONCLUSIONES", "CONTEXTE", "OBJECTIF",
    "HINTERGRUND", "ERGEBNISSE", "ZAKLJUČAK", "目的", "方法", "结果", "结论",
)
ABSTRACT_LABEL = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(label) for label in sorted(ABSTRACT_LABELS, key=len, reverse=True)) + r")\s*[:：]", re.I)
QA_LABEL = re.compile(r"^(?:【医生回复】|医生回答|医生回复|医生解答|病情分析|指导意见|答[：:])")
FIELD_LABELS = ("用法用量", "不良反应", "禁忌", "注意事项", "药理作用", "适应症", "成分",
                "疾病描述", "症状体征", "疾病病因", "病理生理", "诊断检查", "治疗方案",
                "Tìm hiểu chung", "Triệu chứng", "Nguyên nhân", "Nguy cơ",
                "Phương pháp chẩn đoán", "Chế độ sinh hoạt", "Chống chỉ định", "Liều dùng")
NUMBERED = re.compile(r"^(?:\d+[.)、．](?!\d)|[一二三四五六七八九十]+[、．.]|[（(]\d+[)）])")
CONFERENCE_ENTRY = re.compile(r"(?<!\w)[OP]\d{1,3}(?=\s+[A-Z])")
VI_WORDS = re.compile(r"\b(?:bệnh|thuốc|triệu|chứng|điều|trị|người|những|không|được|sức|khỏe|của|và)\b", re.I)
EN_WORDS = re.compile(r"\b(?:the|and|of|in|to|with|patients|study|were|was|results|methods|conclusions)\b", re.I)
FR_WORDS = re.compile(r"\b(?:les|des|dans|une|pour|sur|avec|ont|étude|patients|résultats|conclusion)\b", re.I)
ES_WORDS = re.compile(r"\b(?:los|las|del|una|para|con|se|por|estudio|pacientes|resultados|conclusión)\b", re.I)
SERBIAN_LABEL = re.compile(r"\b(?:ZAKLJUČAK|ZAKLJUCAK|UVOD|METODE|REZULTATI|CILJ)\b", re.I)
NUMERIC = re.compile(
    r"(?<!\w)(?:[$€£]\s*)?\d+(?:[.,:]\d+)+(?:\s*[-–—~～]\s*\d+(?:[.,]\d+)*)?"
    r"(?:[ \t]*(?:mg|ml|mmol/L|mmHg|μg|µg|kg|g|%|℃|°[ \t]*C)(?![A-Za-z]))?"
    r"|(?<!\w)\d+(?:[.,]\d+)?[ \t]*(?:mg|ml|mmol/L|mmHg|μg|µg|kg|%|℃|°[ \t]*C)(?![A-Za-z])", re.I)
PAIRS = {"(": ")", "（": "）", "[": "]", "【": "】"}
CANONICAL_BRACKETS = {"（": "(", "）": ")"}
FORMULA_DOSE = re.compile(r"[（(][^）)\n]{0,18}(?:钱|分|两|克|粒|mg|g)[^）)\n]{0,10}[）)]")
MANUFACTURER_FIELDS = ("生产企业：", "批准字号：", "包装规格：")
SCIENTIFIC_ABBREVIATION = re.compile(r"(?:\bet\s+al|\bi\.v|\bvs)\.$", re.I)


@dataclass(frozen=True)
class Atom:
    start: int
    end: int
    units: int
    role: str
    boundary_type: str
    section_path: tuple[str, ...]
    language: str
    region: int
    repair_reason: str | None = None


def language_hint(text: str) -> tuple[str, str]:
    """Detect strong textual evidence only; foreign personal names do not imply vi."""
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = sum(ch.isalpha() for ch in text)
    vi = len(VI_WORDS.findall(text))
    en = len(EN_WORDS.findall(text))
    fr = len(FR_WORDS.findall(text))
    es = len(ES_WORDS.findall(text))
    label = text.strip().upper().rstrip(":：")
    if label in ("目的", "方法", "结果", "结论"): return "zh", "chinese_section_label"
    if label in ("RÉSULTATS", "CONTEXTE", "OBJECTIF"): return "fr", "french_section_label"
    if label in ("RESULTADOS", "OBJETIVO", "OBJETIVOS", "CONCLUSIONES"): return "es", "spanish_section_label"
    if cjk >= 6 and cjk > letters * .2:
        return "zh", "cjk_script"
    if vi >= 3 and vi > en:
        return "vi", "vietnamese_function_and_medical_words"
    if SERBIAN_LABEL.search(text) and en < 3:
        return "sr", "serbian_section_labels"
    if fr >= 3 and fr > en and fr > es: return "fr", "french_function_and_research_words"
    if es >= 3 and es > en and es > fr: return "es", "spanish_function_and_research_words"
    if en >= 3:
        return "en", "english_function_and_research_words"
    return "und", "insufficient_textual_evidence"


def is_crawl_error_placeholder(text: str) -> bool:
    """Match the known standalone Crawl4AI error template, not generic error prose."""
    candidate = text.strip()
    if not candidate.startswith(CRAWL_ERROR_PREFIX) or len(candidate) > 2000:
        return False
    lowered = candidate.lower()
    return all(marker in lowered for marker in (
        "error message:", "possible reasons:", "suggestions:",
    ))


def select_profile(text: str, url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path
    entries = list(CONFERENCE_ENTRY.finditer(text))
    labels = list(ABSTRACT_LABEL.finditer(text))
    lines = _lines(text)
    field_spans = [(start, end, label) for start, end, line in lines if count_units(line) <= 20
                   for label in FIELD_LABELS if label.lower() in line.lower()]
    fields = sorted({label for _, _, label in field_spans})
    evidence = []
    if len(entries) >= 3 and ("proceedings" in text[:500].lower() or "congress" in text[:500].lower()):
        profile, confidence = "structured_list", "high"
        evidence.append({"rule": "conference_entries", "count": len(entries), "spans": [dict(start_char=m.start(), end_char=m.end()) for m in entries[:10]]})
    elif any(marker in text for marker in ("健康咨询描述", "病情分析", "【医生回复】", "医生回答")):
        profile, confidence = "qa", "high"
        markers = list(re.finditer(r"健康咨询描述|病情分析|【医生回复】|医生回答", text))
        evidence.append({"rule": "question_answer_markers", "spans": [dict(start_char=m.start(), end_char=m.end()) for m in markers[:10]]})
    elif host in ("ask.39.net", "www.120ask.com", "120ask.com"):
        profile, confidence = "qa", "medium"
        evidence.append({"rule": "qa_domain_prior", "domain": host})
    elif len(fields) >= 3 or "可能疾病 伴随症状 就诊科室" in text or ("药品百科" in text[:500] and any(x in text for x in ("用法用量", "不良反应"))):
        profile, confidence = "disease_drug_catalogue", "high"
        evidence.append({"rule": "clinical_fields", "labels": fields, "spans": [dict(start_char=a, end_char=b) for a, b, _ in field_spans[:10]]})
    elif len(labels) >= 2 or host == "pubmed.ncbi.nlm.nih.gov":
        profile, confidence = "research_abstract", "high" if len(labels) >= 2 else "medium"
        evidence.append({"rule": "research_labels" if labels else "pubmed_prior", "count": len(labels), "domain": host,
                         "spans": [dict(start_char=m.start(), end_char=m.end()) for m in labels[:10]]})
    elif "/books/" in path or (host.endswith("zhongyibaodian.net") and len(FORMULA_DOSE.findall(text[:2000])) >= 2 and "药品百科" not in text[:500]):
        profile, confidence = "tcm_book", "medium"
        evidence.append({"rule": "book_path_or_formula", "path": path})
    elif count_units(text) >= 100 or "\n" in text:
        profile, confidence = "narrative_article", "low"
        evidence.append({"rule": "prose_fallback", "spans": [dict(start_char=0, end_char=len(text))]})
    else:
        profile, confidence = "generic", "low"
        evidence.append({"rule": "unknown_format", "spans": [dict(start_char=0, end_char=len(text))]})
    source_language = "en" if host == "pubmed.ncbi.nlm.nih.gov" else "und"
    if host.endswith((".vn", ".com.vn")):
        source_language = "vi"
    elif host.endswith((".cn", "39.net", "120ask.com", "a-hospital.com", "zysjonline.com", "zhongyibaodian.net")):
        source_language = "zh"
    return dict(profile=profile, format_confidence=confidence, format_evidence=evidence,
                source_language=source_language, source_language_basis="domain_prior" if source_language != "und" else "unknown",
                profile_version=PROFILE_VERSION)


def _brackets(text: str) -> tuple[list[dict], int]:
    """Accept local balanced expressions; do not pair damaged opens across abstracts.

    ASCII/fullwidth parentheses are interoperable in the crawled source. A pair
    across paragraph breaks is trusted only within 1200 characters and six line
    breaks; longer pairs remain source text and are flagged for review.
    """
    spans, stack, damaged = [], [], 0
    for index, raw_char in enumerate(text):
        ch = CANONICAL_BRACKETS.get(raw_char, raw_char)
        if ch in PAIRS:
            stack.append((ch, index))
        elif ch in PAIRS.values():
            if stack and ch == PAIRS[stack[-1][0]]:
                _, start = stack.pop()
                segment = text[start:index + 1]
                if len(segment) <= 1200 and segment.count("\n") <= 6 and count_units(segment) <= 500:
                    spans.append(dict(start_char=start, end_char=index + 1, kind="bracket_expression"))
                else: damaged += 1
            else: damaged += 1
    return spans, damaged + len(stack)


def protected_spans(text: str) -> list[dict]:
    spans = [dict(start_char=m.start(), end_char=m.end(), kind="numeric_expression") for m in NUMERIC.finditer(text)]
    spans.extend(_brackets(text)[0])
    return sorted(spans, key=lambda s: (s["start_char"], s["end_char"]))


def _lines(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int, str]]:
    end = len(text) if end is None else end
    result = []
    for match in re.finditer(r"[^\n]+", text[start:end]):
        left, right = start + match.start(), start + match.end()
        while left < right and text[left].isspace(): left += 1
        while right > left and text[right - 1].isspace(): right -= 1
        if left < right: result.append((left, right, text[left:right]))
    return result


def format_exclusions(text: str, url: str, profile: str) -> list[dict]:
    candidates = detect_boilerplate(text, url)
    host = urlparse(url).hostname or ""
    lines = _lines(text)
    # A paired marker gives an unambiguous doctor biography, never a disease keyword alone.
    for match in re.finditer(r"【医生信息】", text):
        reply = text.find("【医生回复】", match.end())
        next_bio = text.find("【医生信息】", match.end())
        if reply >= 0 and (next_bio < 0 or reply < next_bio):
            span = _span(text, match.start(), reply, "doctor_biography", "paired doctor-information/reply markers")
            span.update(end_char=reply, text=text[span["start_char"]:reply])
            candidates.append(span)
    # Keyboard pagination is distinct from quoted 原文 links and their clinical snippets.
    for index, (start, end, line) in enumerate(lines):
        if "方向键翻页" in line and "←" in line:
            left = index
            while left > 0 and index - left < 3 and len(lines[left - 1][2]) < 80:
                left -= 1
                if lines[left][2] == "←": break
            right = index + 1
            while right < len(lines) and right - index <= 2 and len(lines[right][2]) < 80:
                right += 1
                if lines[right - 1][2] == "→": break
            candidates.append(_span(text, lines[left][0], lines[right - 1][1], "book_pagination", "arrow/keyboard pagination layout"))
    if "longchau" in host and lines:
        first_title = lines[0][2]
        app = text.find("Ứng dụng Nhà Thuốc Long Châu")
        second_title = text.find(first_title, app + 1) if app >= 0 else -1
        if app >= 0 and second_title > app and "Tra cứu thuốc" in text[app:second_title] and "Xem theo chữ cái" in text[app:second_title]:
            candidates.append(_span(text, app, second_title, "store_navigation", "app banner, alphabet and catalogue before repeated title"))
            title = _span(text, lines[0][0], lines[0][1], "duplicate_title_before_navigation", "exact title repeated after store navigation; retained as title context")
            title["duplicate_of_span"] = dict(start_char=second_title, end_char=second_title + len(first_title))
            candidates.append(title)
            following = _lines(text, second_title)[:6]
            if len(following) >= 5 and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", following[1][2]) and sum(
                    any(line.lower().startswith(label.lower()) for label in FIELD_LABELS) for _, _, line in following[2:]) >= 3:
                candidates.append(_span(text, second_title, following[1][1], "catalogue_header_context", "title/date header separated from body by repeated field TOC; retained as context metadata"))
        related = text.rfind("\nBài viết liên quan\n")
        if related > len(text) * .6 and "Xem tất cả" in text[related:related + 120]:
            candidates.append(_span(text, related, len(text), "related_articles_navigation", "related-articles heading and view-all marker at tail"))
        # Consecutive field labels, repeated in the page body, are a TOC rather than six empty sections.
        index = 0
        while index < len(lines):
            end_index = index
            while end_index < len(lines) and (lines[end_index][2] in FIELD_LABELS or lines[end_index][2] in
                    ("Nội dung chính", "Phương pháp chẩn đoán & điều trị", "Chế độ sinh hoạt & phòng ngừa")):
                end_index += 1
            if end_index - index >= 4 and any(text.find(lines[j][2], lines[end_index - 1][1]) >= 0 for j in range(index, end_index)):
                candidates.append(_span(text, lines[index][0], lines[end_index - 1][1], "repeated_field_toc", "four or more adjacent field labels repeated later"))
            index = max(index + 1, end_index)
    if host.endswith(("a-hospital.com", "zhongyibaodian.net")):
        for index, (start, end, line) in enumerate(lines):
            # ICD menus keep many unrelated diseases on one line. Never remove a lone ICD code in prose.
            marker = line.find("国际疾病与相关健康问题统计分类第十版")
            if marker >= 0 and line[marker:].count("·") >= 15:
                candidates.append(_span(text, start + marker, end, "icd_navigation", "ICD navigation heading and dense linked disease separators"))
            elif marker >= 0 and sum(item[2].count("·") for item in lines[index + 1:index + 4]) >= 15:
                stop = index + 1
                while stop < len(lines) and lines[stop][2].count("·") >= 2: stop += 1
                candidates.append(_span(text, start + marker, lines[stop - 1][1], "icd_navigation", "ICD heading followed by consecutive dense linked disease lists"))
        nav = re.search(r"(?m)^急救常识\s*-\s*中毒急救\s*$", text)
        if nav and "出自A+医学百科" in text[nav.end():] and len(_lines(text, nav.end())) >= 20:
            candidates.append(_span(text, nav.start(), len(text), "wiki_navigation_footer", "dense emergency navigation plus wiki attribution/footer"))
        for match in re.finditer(r"(?m)^药品百科\s*$", text):
            following = text[match.end():match.end() + 200]
            if "如何读懂药品说明书" in following and "杀菌消炎药" in following:
                stop = text.find("\n中医宝典 >", match.end())
                candidates.append(_span(text, match.start(), stop if stop >= 0 else len(text), "drug_taxonomy_navigation", "drug encyclopedia menu with instruction and taxonomy markers"))
    # Remove exact duplicate renderings only when a repeated breadcrumb/TOC identifies the template.
    render_evidence = sum(text.count(term) >= 2 for term in ("跳转到", "中医宝典 >", "详细>>"))
    if render_evidence:
        for start, end, line in lines:
            if len(line) < 200: continue
            previous = text.find(line, 0, start)
            if previous >= 0:
                span = _span(text, start, end, "duplicate_rendered_paragraph", "exact earlier copy plus repeated template markers")
                span["duplicate_of_span"] = {"start_char": previous, "end_char": previous + len(line)}
                candidates.append(span)
    merged = []
    for span in sorted(candidates, key=lambda s: (s["start_char"], -s["end_char"])):
        if span["start_char"] >= span["end_char"]: continue
        span["evidence"] = [{"rule_id": span["rule_id"], "reason": span["reason"]}]
        if merged and span["start_char"] <= merged[-1]["end_char"]:
            merged[-1]["end_char"] = max(merged[-1]["end_char"], span["end_char"])
            merged[-1]["text"] = text[merged[-1]["start_char"]:merged[-1]["end_char"]]
            merged[-1]["evidence"].extend(span["evidence"])
        else: merged.append(span)
    return merged


def sentence_spans(text: str, start: int, end: int, protected: list[dict] | None = None) -> list[tuple[int, int]]:
    """Whole sentences, with numeric/abbreviation guards and balanced brackets."""
    result = []
    protected = protected_spans(text) if protected is None else protected
    local_protected = sorted((s["start_char"], s["end_char"]) for s in protected if s["end_char"] > start and s["start_char"] < end)
    protect_index = 0
    cursor = start
    index = start
    while index < end:
        char = text[index]
        while protect_index < len(local_protected) and local_protected[protect_index][1] <= index + 1: protect_index += 1
        inside = protect_index < len(local_protected) and local_protected[protect_index][0] < index + 1 < local_protected[protect_index][1]
        previous = text[index - 1] if index > start else ""
        following = text[index + 1] if index + 1 < end else ""
        cjk_period = char == "." and bool(re.fullmatch(r"[\u3400-\u9fff]", previous)) and bool(re.fullmatch(r"[\u3400-\u9fff]", following))
        abbreviation = char == "." and bool(SCIENTIFIC_ABBREVIATION.search(text[max(start, index - 30):index + 1]))
        boundary = not inside and (char in "。！？!?" or
                    char == "．" and not (index > start and index + 1 < end and text[index-1].isdigit() and text[index+1].isdigit()) or
                    char == "." and not abbreviation and (cjk_period or _period_is_boundary(text[start:end], index - start)))
        if boundary:
            stop = index + 1
            while stop < end and text[stop] in '”’」』）》】)"\'': stop += 1
            left = cursor
            while left < stop and text[left].isspace(): left += 1
            if left < stop: result.append((left, stop))
            cursor, index = stop, stop
        else: index += 1
    while cursor < end and text[cursor].isspace(): cursor += 1
    if cursor < end: result.append((cursor, end))
    return result


def _oversized_split_points(
    text: str, start: int, end: int, method: str, base_atoms: list[Atom],
    headings: list[dict], protected: list[dict],
) -> list[int]:
    points: list[int] = []
    if method == "semantic":
        ordered = [atom for atom in base_atoms if atom.end > start and atom.start < end]
        for previous, following in zip(ordered, ordered[1:]):
            if following.start <= start or following.start >= end:
                continue
            if (previous.region, previous.language, previous.role, previous.section_path) != (
                following.region, following.language, following.role, following.section_path
            ):
                points.append(following.start)
    elif method == "heading":
        points.extend(span["start_char"] for span in headings if start < span["start_char"] < end)
    elif method == "paragraph":
        points.extend(start + match.end() for match in re.finditer(r"\n[ \t]*\n+", text[start:end]))
    elif method == "sentence":
        points.extend(atom.start for atom in base_atoms if start < atom.start < end)
        spans = sentence_spans(text, start, end, protected)
        points.extend(span_start for span_start, _ in spans[1:])
        for match in re.finditer(r"[.!?。！？；;](?=\s)", text[start:end]):
            punctuation = match.group()
            absolute = start + match.end()
            if punctuation == ".":
                before = text[max(start, start + match.start() - 30):absolute]
                after = text[absolute:].lstrip()
                if (not after or not after[0].isalpha() or re.search(r"\b(?:et\s+al|i\.v|vs|e\.g|i\.e)\.$", before, re.I)
                        or (match.start() > 0 and text[start + match.start() - 1].isdigit())):
                    continue
            points.append(absolute)
    elif method == "line":
        points.extend(start + match.end() for match in re.finditer(r"\n+", text[start:end]))
    elif method == "clause":
        points.extend(match.end() for match in re.finditer(r"[;；,，、]", text[start:end], re.S))
        points = [start + point for point in points]
    elif method == "whitespace":
        points.extend(start + match.end() for match in re.finditer(r"\s+", text[start:end]))

    points = sorted(set(point for point in points if start < point < end))
    return [point for point in points if not any(
        span["start_char"] < point < span["end_char"] for span in protected
    )]


def _split_ranges(start: int, end: int, points: list[int], text: str) -> list[tuple[int, int]]:
    result = []
    boundaries = [start, *points, end]
    for left, right in zip(boundaries, boundaries[1:]):
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            result.append((left, right))
    return result


def _repair_oversized_atoms(
    text: str, atoms: list[Atom], base_atoms: list[Atom], headings: list[dict],
    protected: list[dict], max_units: int = 500,
) -> list[Atom]:
    """Break pathological atoms at source-safe boundaries, keeping exact spans and local metadata."""
    methods = ("semantic", "heading", "paragraph", "sentence", "line", "clause", "whitespace")
    repaired = []
    for atom in atoms:
        if atom.units <= max_units:
            repaired.append(atom)
            continue

        def split_range(start: int, end: int, first_method: int = 0) -> list[tuple[int, int, str]]:
            if count_units(text[start:end]) <= max_units:
                return [(start, end, methods[max(0, first_method - 1)] if first_method else "sentence")]
            for method_index in range(first_method, len(methods)):
                method = methods[method_index]
                ranges = _split_ranges(
                    start, end,
                    _oversized_split_points(text, start, end, method, base_atoms, headings, protected),
                    text,
                )
                if len(ranges) < 2:
                    continue
                pieces = []
                for left, right in ranges:
                    if count_units(text[left:right]) <= max_units:
                        pieces.append((left, right, method))
                    else:
                        pieces.extend(split_range(left, right, method_index + 1))
                return pieces
            return [(start, end, "oversized_unresolved")]

        fragments = split_range(atom.start, atom.end)
        for start, end, reason in fragments:
            overlapping = [base for base in base_atoms if max(start, base.start) < min(end, base.end)]
            metadata = max(overlapping, key=lambda base: min(end, base.end) - max(start, base.start)) if overlapping else atom
            repaired.append(replace(
                metadata, start=start, end=end, units=count_units(text[start:end]),
                boundary_type="oversized_unresolved" if reason == "oversized_unresolved" else f"oversize_{reason}",
                repair_reason=reason,
            ))
    return repaired


def _role(line: str, first: bool, profile: str) -> str:
    if first and count_units(line) <= 60 and len(line) <= 350: return "title"
    if profile == "qa":
        if re.match(r"^(?:您好|你好)[，,\s]*医生[，,\s]", line): return "question"
        if QA_LABEL.match(line) or line.startswith(("您好", "你好")): return "answer"
        if line.startswith(("健康咨询描述", "曾经的治疗", "想得到怎样", "问题描述", "病情描述")): return "question"
    if line.startswith("…") or line == "原文 →": return "quoted_snippet"
    if ABSTRACT_LABEL.match(line): return "abstract_section"
    if line.endswith((":", "：", "∶")) and count_units(line) <= 20: return "label"
    if any(line.lower().startswith(x.lower()) for x in FIELD_LABELS) and count_units(line) <= 20: return "field_heading"
    if profile == "disease_drug_catalogue" and count_units(line) <= 25 and not line.endswith(tuple(".!?。！？")) and any(
            label in line for label in FIELD_LABELS[:14]): return "field_heading"
    if NUMBERED.match(line) and len(line) < 120: return "list_entry"
    if line.startswith("《") and line.endswith("》"): return "citation"
    if profile == "tcm_book" and len(FORMULA_DOSE.findall(line)) >= 2: return "formula"
    if (count_units(line) <= 15 and count_units(line) >= 3 and line[0].isupper()
            and not re.search(r"[.!?。！？,:：]$", line) and not re.match(r"^\d+[.,]\d", line)):
        return "heading"
    return "body"


def _section_spans(text: str, profile: str, headings: list[dict]) -> list[dict]:
    """Keep inline research labels as source evidence without forcing tiny chunks."""
    if profile == "research_abstract":
        labels = [(m.start(), m.end(), m.group().rstrip(" :："), "abstract_section")
                  for m in ABSTRACT_LABEL.finditer(text)]
    else:
        labels = [(s["start_char"], s["end_char"], text[s["start_char"]:s["end_char"]], s["role"])
                  for s in headings if s["role"] != "title"]
    return [dict(start_char=start, label_end_char=label_end, end_char=labels[index + 1][0] if index + 1 < len(labels) else len(text),
                 label=label, role=role, confidence="medium")
            for index, (start, label_end, label, role) in enumerate(labels)]


def analyse_format(text: str, url: str) -> dict:
    metadata = select_profile(text, url)
    profile = metadata["profile"]
    protected = protected_spans(text)
    exclusions = format_exclusions(text, url, profile)
    regions = []
    cursor = 0
    for span in exclusions:
        if cursor < span["start_char"]: regions.append((cursor, span["start_char"]))
        cursor = span["end_char"]
    if cursor < len(text): regions.append((cursor, len(text)))
    atoms, headings, questions, answers, language_spans = [], [], [], [], []
    region_id, last_language, section = 0, "und", ()
    first_start = _lines(text)[0][0]
    first_line = _lines(text)[0]
    titles = [dict(start_char=first_line[0], end_char=first_line[1])] if len(first_line[2]) <= 350 and count_units(first_line[2]) <= 60 else []
    for region_start, region_end in regions:
        region_id += 1
        lines = _lines(text, region_start, region_end)
        blocks = []
        skip_to = -1
        table_header = None
        for index, (start, end, line) in enumerate(lines):
            if start < skip_to: continue
            role = _role(line, start == first_start, profile)
            if line == "可能疾病 伴随症状 就诊科室":
                table_header, role = line, "table_header"
            elif table_header and len(line.split()) >= 3 and count_units(line) <= 60:
                role = "table_row"
            else: table_header = None
            if profile == "disease_drug_catalogue" and index + 3 < len(lines) and all(
                    lines[index + j + 1][2].startswith(prefix) for j, prefix in enumerate(MANUFACTURER_FIELDS)):
                end, role = lines[index + 3][1], "manufacturer_record"
                skip_to = end
                line = text[start:end]
            language, basis = language_hint(line)
            # Short captions/headings inherit adjacent content unless there is positive language evidence.
            if language == "und" and len(line) <= 140 and count_units(line) <= 20:
                language = last_language
            if language != "und" and last_language not in ("und", language): region_id += 1
            if language != "und": last_language = language
            if role == "answer" and re.match(r"^(?:【医生回复】|病情分析|医生回答|医生回复)", line):
                region_id += 1
            if role in ("title", "heading", "field_heading", "abstract_section"):
                label = line.split(":", 1)[0].split("：", 1)[0] if role == "abstract_section" else line
                section = (label[:160],)
                headings.append(dict(start_char=start, end_char=end, role=role))
            if role in ("title", "question") and profile == "qa": questions.append(dict(start_char=start, end_char=end))
            if role == "answer": answers.append(dict(start_char=start, end_char=end))
            blocks.append([start, end, role, section, language, region_id])
            language_spans.append(dict(start_char=start, end_char=end, language=language, basis=basis))
        # Join broken inline text before sentence scanning. Labels/title must attach forward.
        joined = []
        for block in blocks:
            if joined:
                previous = joined[-1]
                previous_text = text[previous[0]:previous[1]]
                must_link = previous[2] in ("title", "heading", "field_heading", "label", "citation") or (
                    previous[2] in ("answer", "abstract_section") and previous_text.endswith((":", "：")) and count_units(previous_text) <= 20)
                following_text = text[block[0]:block[1]]
                # Join inline link fragments, not an unbounded list of independent records.
                soft_break = (previous[2] in ("body", "question", "quoted_snippet") and block[2] == "body"
                              and previous_text[-1] not in ".!?。！？:：" and not NUMBERED.match(following_text)
                              and (following_text[0].islower() or following_text[0] in ",;.:：，、)）"
                                   or count_units(previous_text) <= 3))
                if previous[5] == block[5] and (must_link or soft_break):
                    previous[1] = block[1]
                    if previous[4] == "und": previous[4] = block[4]
                    if must_link and previous[2] != "answer":
                        previous[2] = "body"
                    continue
            joined.append(block.copy())
        for start, end, role, section_path, language, block_region in joined:
            entry_matches = list(CONFERENCE_ENTRY.finditer(text, start, end)) if profile == "structured_list" else []
            if len(entry_matches) >= 2:
                entry_starts = [start] + [m.start() for m in entry_matches if m.start() > start]
                spans = [(a, b) for a, b in zip(entry_starts, entry_starts[1:] + [end])]
                boundary_type, role = "list_entry", "list_entry"
            elif role in ("table_row", "table_header", "formula", "manufacturer_record") or (
                    role == "list_entry" and count_units(text[start:end]) <= 300):
                spans, boundary_type = [(start, end)], "structural_atom"
            else:
                spans, boundary_type = sentence_spans(text, start, end, protected), "sentence"
            if role in ("title", "heading", "field_heading", "label", "citation") and len(spans) > 1:
                first_line_end = text.find("\n", start, end)
                if first_line_end >= 0 and spans[0][1] <= first_line_end:
                    spans = [(spans[0][0], spans[1][1])] + spans[2:]
            for atom_start, atom_end in spans:
                while atom_end > atom_start and text[atom_end - 1].isspace(): atom_end -= 1
                atom_text = text[atom_start:atom_end]
                atoms.append(Atom(atom_start, atom_end, count_units(atom_text), role,
                                  boundary_type, section_path, language, block_region))
    # A protected expression can span inline anchors/newlines. Enforce it after
    # all block detectors, rather than trusting a per-line sentence scanner.
    intervals = []
    for span in protected:
        start, end = span["start_char"], span["end_char"]
        if intervals and start < intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(end, intervals[-1][1]))
        else: intervals.append((start, end))
    interval_starts = [start for start, _ in intervals]

    def inside_protected(position: int) -> bool:
        index = bisect_right(interval_starts, position) - 1
        return index >= 0 and intervals[index][0] < position < intervals[index][1]

    base_atoms = atoms
    merged_atoms = []
    for atom in atoms:
        previous = merged_atoms[-1] if merged_atoms else None
        protected_link = previous and (inside_protected(atom.start) or inside_protected(previous.end))
        label_link = (previous and previous.region == atom.region and text[previous.start:previous.end].rstrip().endswith((":", "：", "∶")))
        if protected_link or label_link:
            previous = merged_atoms[-1]
            if not any(max(previous.start, s["start_char"]) < min(atom.end, s["end_char"]) for s in exclusions):
                language = atom.language if previous.language == "und" else previous.language
                merged_atoms[-1] = replace(previous, end=atom.end, units=count_units(text[previous.start:atom.end]), language=language,
                                          boundary_type="must_link_atom" if label_link else previous.boundary_type)
                continue
        merged_atoms.append(atom)
    atoms = _repair_oversized_atoms(text, merged_atoms, base_atoms, headings, protected)
    # A short document should keep its coherent question/abstract, even with inline labels.
    if atoms and not exclusions and count_units(text) <= 300 and len({a.language for a in atoms if a.language != "und"}) <= 1:
        atoms = [replace(a, region=0) for a in atoms]
    return dict(metadata=metadata, atoms=atoms, excluded_spans=exclusions, heading_spans=headings, title_spans=titles,
                section_spans=_section_spans(text, profile, headings),
                question_spans=questions, answer_spans=answers, content_language_spans=language_spans,
                protected_spans=protected, damaged_bracket_count=_brackets(text)[1])
