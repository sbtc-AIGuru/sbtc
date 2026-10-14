"""Content evidence and exact source spans for deterministic format profiles.

Rules are deliberately conservative. Confidence is a rule strength, not a
calibrated probability; unknown language and flattened layout stay explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from urllib.parse import urlparse

from sbtc.Scripts.Preprocess.boilerplate import detect_boilerplate, _span
from sbtc.Scripts.Preprocess.chunking import count_units, _period_is_boundary

PROFILE_VERSION = "format-v1"
ABSTRACT_LABEL = re.compile(
    r"(?:BACKGROUND|INTRODUCTION|OBJECTIVES?|PURPOSE|AIMS?|METHODS?|MATERIALS AND METHODS|"
    r"RESULTS?|CONCLUSIONS?|DISCUSSION|SIGNIFICANCE|目的|方法|结果|结论)\s*[:：]", re.I)
QA_LABEL = re.compile(r"^(?:【医生回复】|医生回答|医生回复|医生解答|病情分析|指导意见|答[：:])")
FIELD_LABELS = ("用法用量", "不良反应", "禁忌", "注意事项", "药理作用", "适应症", "成分",
                "疾病描述", "症状体征", "疾病病因", "病理生理", "诊断检查", "治疗方案",
                "Tìm hiểu chung", "Triệu chứng", "Nguyên nhân", "Nguy cơ",
                "Phương pháp chẩn đoán", "Chế độ sinh hoạt", "Chống chỉ định", "Liều dùng")
NUMBERED = re.compile(r"^(?:\d+[.)、．](?!\d)|[一二三四五六七八九十]+[、．.]|[（(]\d+[)）])")
CONFERENCE_ENTRY = re.compile(r"(?<!\w)[OP]\d{1,3}(?=\s+[A-Z])")
VI_WORDS = re.compile(r"\b(?:bệnh|thuốc|triệu|chứng|điều|trị|người|những|không|được|sức|khỏe|của|và)\b", re.I)
EN_WORDS = re.compile(r"\b(?:the|and|of|in|to|with|patients|study|were|was|results|methods|conclusions)\b", re.I)
SERBIAN_LABEL = re.compile(r"\b(?:ZAKLJUČAK|ZAKLJUCAK|UVOD|METODE|REZULTATI|CILJ)\b", re.I)
NUMERIC = re.compile(
    r"(?<!\w)(?:[$€£]\s*)?\d+(?:[.,:]\d+)+(?:\s*[-–—~～]\s*\d+(?:[.,]\d+)*)?"
    r"(?:\s*(?:mg|ml|mmol/L|mmHg|μg|µg|kg|g|%|℃|°\s*C))?"
    r"|(?<!\w)\d+(?:[.,]\d+)?\s*(?:mg|ml|mmol/L|mmHg|μg|µg|kg|%|℃|°\s*C)\b", re.I)
PAIRS = {"(": ")", "（": "）", "[": "]", "【": "】"}


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


def language_hint(text: str) -> tuple[str, str]:
    """Detect strong textual evidence only; foreign personal names do not imply vi."""
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    letters = sum(ch.isalpha() for ch in text)
    vi = len(VI_WORDS.findall(text))
    en = len(EN_WORDS.findall(text))
    if cjk >= 6 and cjk > letters * .2:
        return "zh", "cjk_script"
    if vi >= 3 and vi > en:
        return "vi", "vietnamese_function_and_medical_words"
    if SERBIAN_LABEL.search(text) and en < 3:
        return "sr", "serbian_section_labels"
    if en >= 3:
        return "en", "english_function_and_research_words"
    return "und", "insufficient_textual_evidence"


def select_profile(text: str, url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path
    entries = list(CONFERENCE_ENTRY.finditer(text))
    labels = list(ABSTRACT_LABEL.finditer(text))
    fields = [label for label in FIELD_LABELS if label.lower() in text.lower()]
    evidence = []
    if len(entries) >= 3 and ("proceedings" in text[:500].lower() or "congress" in text[:500].lower()):
        profile, confidence = "structured_list", "high"
        evidence.append({"rule": "conference_entries", "count": len(entries)})
    elif any(marker in text for marker in ("健康咨询描述", "病情分析", "【医生回复】", "医生回答")):
        profile, confidence = "qa", "high"
        evidence.append({"rule": "question_answer_markers"})
    elif host in ("ask.39.net", "www.120ask.com", "120ask.com"):
        profile, confidence = "qa", "medium"
        evidence.append({"rule": "qa_domain_prior"})
    elif len(fields) >= 3 or ("药品百科" in text[:500] and any(x in fields for x in ("用法用量", "不良反应"))):
        profile, confidence = "disease_drug_catalogue", "high"
        evidence.append({"rule": "clinical_fields", "labels": fields})
    elif len(labels) >= 2 or host == "pubmed.ncbi.nlm.nih.gov":
        profile, confidence = "research_abstract", "high" if len(labels) >= 2 else "medium"
        evidence.append({"rule": "research_labels" if labels else "pubmed_prior", "count": len(labels)})
    elif "/books/" in path or (host.endswith("zhongyibaodian.net") and "《" in text and "药品百科" not in text[:500]):
        profile, confidence = "tcm_book", "medium"
        evidence.append({"rule": "book_path_or_citation"})
    elif count_units(text) >= 100 or "\n" in text:
        profile, confidence = "narrative_article", "low"
        evidence.append({"rule": "prose_fallback"})
    else:
        profile, confidence = "generic", "low"
        evidence.append({"rule": "unknown_format"})
    source_language = "en" if host == "pubmed.ncbi.nlm.nih.gov" else "und"
    if host.endswith((".vn", ".com.vn")):
        source_language = "vi"
    elif host.endswith((".cn", "39.net", "120ask.com", "a-hospital.com", "zysjonline.com", "zhongyibaodian.net")):
        source_language = "zh"
    return dict(profile=profile, format_confidence=confidence, format_evidence=evidence,
                source_language=source_language, source_language_basis="domain_prior" if source_language != "und" else "unknown",
                profile_version=PROFILE_VERSION)


def protected_spans(text: str) -> list[dict]:
    spans = [dict(start_char=m.start(), end_char=m.end(), kind="numeric_expression") for m in NUMERIC.finditer(text)]
    stack = []
    for index, ch in enumerate(text):
        if ch in PAIRS:
            stack.append((ch, index))
        elif stack and ch == PAIRS[stack[-1][0]]:
            opening, start = stack.pop()
            spans.append(dict(start_char=start, end_char=index + 1, kind="bracket_expression"))
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
        for start, end, line in lines:
            # ICD menus keep many unrelated diseases on one line. Never remove a lone ICD code in prose.
            marker = line.find("国际疾病与相关健康问题统计分类第十版")
            if marker >= 0 and line[marker:].count("·") >= 15:
                candidates.append(_span(text, start + marker, end, "icd_navigation", "ICD navigation heading and dense linked disease separators"))
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


def sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Whole sentences, with numeric/abbreviation guards and balanced brackets."""
    result, stack = [], []
    cursor = start
    index = start
    while index < end:
        char = text[index]
        if char in PAIRS: stack.append(char)
        elif stack and char == PAIRS[stack[-1]]: stack.pop()
        boundary = not stack and (char in "。！？!?" or
                    char == "．" and not (index > start and index + 1 < end and text[index-1].isdigit() and text[index+1].isdigit()) or
                    char == "." and _period_is_boundary(text[start:end], index - start))
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


def _role(line: str, first: bool, profile: str) -> str:
    if first and count_units(line) <= 60 and len(line) <= 350: return "title"
    if profile == "qa":
        if QA_LABEL.match(line) or line.startswith(("您好", "你好")): return "answer"
        if line.startswith(("健康咨询描述", "曾经的治疗", "想得到怎样", "问题描述", "病情描述")): return "question"
    if line.startswith("…") or line == "原文 →": return "quoted_snippet"
    if ABSTRACT_LABEL.match(line): return "abstract_section"
    if line.endswith((":", "：", "∶")) and count_units(line) <= 20: return "label"
    if any(line.lower().startswith(x.lower()) for x in FIELD_LABELS) and count_units(line) <= 20: return "field_heading"
    if NUMBERED.match(line) and len(line) < 120: return "list_entry"
    if line.startswith("《") and line.endswith("》"): return "citation"
    if (count_units(line) <= 15 and count_units(line) >= 3 and line[0].isupper()
            and not re.search(r"[.!?。！？,:：]$", line) and not re.match(r"^\d+[.,]\d", line)):
        return "heading"
    return "body"


def analyse_format(text: str, url: str) -> dict:
    metadata = select_profile(text, url)
    profile = metadata["profile"]
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
    for region_start, region_end in regions:
        region_id += 1
        lines = _lines(text, region_start, region_end)
        blocks = []
        for index, (start, end, line) in enumerate(lines):
            role = _role(line, start == first_start, profile)
            language, basis = language_hint(line)
            # Short captions/headings inherit adjacent content unless there is positive language evidence.
            if language == "und": language = last_language
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
                    previous[2] == "answer" and previous_text.endswith((":", "：")) and count_units(previous_text) <= 20)
                soft_break = (previous[2] in ("body", "question", "quoted_snippet") and block[2] == "body"
                              and previous_text[-1] not in ".!?。！？" and not NUMBERED.match(text[block[0]:block[1]]))
                if previous[5] == block[5] and (must_link or soft_break):
                    previous[1] = block[1]
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
            elif role == "list_entry" or (profile == "tcm_book" and re.search(r"(?:处方|方药|组成)[：:∶]", text[start:end])):
                spans, boundary_type = [(start, end)], "structural_atom"
            else:
                spans, boundary_type = sentence_spans(text, start, end), "sentence"
            if role in ("title", "heading", "field_heading", "label", "citation") and len(spans) > 1:
                first_line_end = text.find("\n", start, end)
                if first_line_end >= 0 and spans[0][1] <= first_line_end:
                    spans = [(spans[0][0], spans[1][1])] + spans[2:]
            for atom_start, atom_end in spans:
                while atom_end > atom_start and text[atom_end - 1].isspace(): atom_end -= 1
                atom_text = text[atom_start:atom_end]
                atoms.append(Atom(atom_start, atom_end, count_units(atom_text), role,
                                  boundary_type, section_path, language, block_region))
    # A short document should keep its coherent question/abstract, even with inline labels.
    if atoms and not exclusions and count_units(text) <= 300 and len({a.language for a in atoms if a.language != "und"}) <= 1:
        atoms = [replace(a, region=0) for a in atoms]
    return dict(metadata=metadata, atoms=atoms, excluded_spans=exclusions, heading_spans=headings,
                question_spans=questions, answer_spans=answers, content_language_spans=language_spans,
                protected_spans=protected_spans(text))
