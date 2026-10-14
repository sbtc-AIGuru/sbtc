"""Deterministic, paragraph-only medical document chunking."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re
from urllib.parse import urlparse

from sbtc.Scripts.Clawler.verbatim import clean_with_report
from sbtc.Scripts.Preprocess.boilerplate import detect_boilerplate


STRATEGIES = ("basic", "structure", "adaptive", "hybrid", "format")
QA_MARKERS = ("健康咨询描述", "问题描述", "病情描述", "医生回答", "医生回复", "医生解答", "指导意见", "病情分析")
QUESTION_RE = re.compile(r"^(?:健康咨询描述|问题描述|病情描述|患者提问|提问|问[：:])")
ANSWER_RE = re.compile(r"^(?:医生回答|医生回复|医生解答|指导意见|病情分析|答[：:])")
HEADING_RE = re.compile(
    r"^(?:【[^】]{1,32}】|"
    r"(?:[一二三四五六七八九十]+[、．.]|\d+[、．.)])\s*[^。！？；.!?;，,]{1,60}|"
    r"(?:症状|病因|诊断|治疗|预防|注意事项|临床表现|用法|处方|功效与作用|"
    r"Triệu chứng|Nguyên nhân|Chẩn đoán|Điều trị|Phòng ngừa)\s*[：:]?)$",
    re.IGNORECASE,
)
CONTINUATION_RE = re.compile(r"^(?:但是|因此|所以|此外|其中|然而|如果|若|同时|不过|Tuy nhiên|Do đó)", re.IGNORECASE)
OPEN_CONTEXT_RE = re.compile(r"(?:但|如果|若|因为|由于|没有|无|未|không|nếu|nhưng)[：:,，、]?\s*$", re.IGNORECASE)
CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F))


@dataclass(frozen=True)
class ChunkConfig:
    min_units: int = 150
    target_units: int = 220
    max_units: int = 300
    overlap_units: int = 40
    parent_max_units: int = 1200
    version: str = "paragraph-v3"
    format_overlap_policy: str = "post_pack"

    def __post_init__(self) -> None:
        if not (0 < self.min_units <= self.target_units <= self.max_units):
            raise ValueError("Require 0 < min_units <= target_units <= max_units")
        if not (0 <= self.overlap_units < self.min_units):
            raise ValueError("Require 0 <= overlap_units < min_units")
        if self.parent_max_units < self.max_units:
            raise ValueError("parent_max_units must be at least max_units")
        if not self.version or any(ch.isspace() for ch in self.version):
            raise ValueError("version must be nonempty and contain no whitespace")
        if self.format_overlap_policy not in ("post_pack", "reserve"):
            raise ValueError("format_overlap_policy must be post_pack or reserve")


@dataclass(frozen=True)
class Paragraph:
    start: int
    end: int
    units: int
    role: str
    blank_before: bool
    text: str
    boundary_type: str = "paragraph"


@dataclass(frozen=True)
class PackedGroup:
    atoms: list[Paragraph]
    overlap_units: int = 0
    overlap_exception: str | None = None


SENTENCE_END = frozenset("。．！？!?；;")
CLAUSE_END = frozenset("，、：,:;")
CLOSING_PUNCTUATION = frozenset("”’」』）》】)\"'")
PERIOD_ABBREVIATIONS = frozenset(("bs.", "dr.", "mr.", "mrs.", "ms.", "pgs.", "ts.", "ths.", "e.g.", "i.e.", "v.v."))


def _is_cjk(char: str) -> bool:
    value = ord(char)
    return any(low <= value <= high for low, high in CJK_RANGES)


def count_units(text: str) -> int:
    """Count CJK characters and intact Latin/numeric medical expressions."""
    count = 0
    index = 0
    while index < len(text):
        char = text[index]
        if _is_cjk(char):
            count += 1
            index += 1
        elif char.isalnum():
            count += 1
            index += 1
            while index < len(text):
                current = text[index]
                if current.isalnum() and not _is_cjk(current):
                    index += 1
                elif current in ".+/_-%" and index + 1 < len(text) and text[index + 1].isalnum() and not _is_cjk(text[index + 1]):
                    index += 1
                else:
                    break
        else:
            index += 1
    return count


def classify_document_details(text: str, url: str) -> tuple[str, str, str]:
    """Return type, matching rule, and an uncalibrated heuristic confidence."""
    domain = urlparse(url).hostname or ""
    qa_domain = any(domain == name or domain.endswith("." + name) for name in ("120ask.com", "ask.39.net"))
    if any(marker in text for marker in QA_MARKERS):
        return "qa", "qa_marker", "high"
    if qa_domain:
        return "qa", "qa_domain", "medium"
    if len(text) > 500:
        return "article", "long_text", "medium"
    if "\n" in text:
        return "article", "multiline", "low"
    return "other", "fallback", "low"


def classify_document(text: str, url: str) -> str:
    return classify_document_details(text, url)[0]


def _extract_paragraphs(text: str, base_offset: int) -> list[Paragraph]:
    spans: list[Paragraph] = []
    cursor = 0
    blank = False
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not content.strip():
            blank = True
            cursor += len(line)
            continue
        leading = len(content) - len(content.lstrip())
        trailing = len(content.rstrip())
        local_start, local_end = cursor + leading, cursor + trailing
        start, end = base_offset + local_start, base_offset + local_end
        visible = text[local_start:local_end]
        if QUESTION_RE.match(visible):
            role = "question"
        elif ANSWER_RE.match(visible):
            role = "answer"
        elif not spans and len(visible) <= 120:
            role = "heading"
        elif len(visible) <= 120 and HEADING_RE.fullmatch(visible):
            role = "heading"
        else:
            role = "body"
        spans.append(Paragraph(start, end, count_units(visible), role, blank, visible))
        blank = False
        cursor += len(line)
    return spans


def extract_paragraphs(text: str) -> list[Paragraph]:
    return _extract_paragraphs(text, 0)


def _period_is_boundary(text: str, index: int) -> bool:
    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isdigit() and following.isdigit():
        return False
    if previous.isalnum() and following.isalnum():
        return False
    prefix = text[:index + 1].lower()
    token_match = re.search(r"([\w.]+\.)$", prefix)
    token = token_match.group(1) if token_match else ""
    if token in PERIOD_ABBREVIATIONS or (len(token) == 2 and token[0].isalpha()):
        return False
    lookahead = index + 1
    while lookahead < len(text) and text[lookahead] in CLOSING_PUNCTUATION:
        lookahead += 1
    if lookahead >= len(text) or text[lookahead].isspace():
        return True
    return bool(previous) and _is_cjk(previous) and _is_cjk(text[lookahead])


def _split_at_boundaries(text: str, start: int, end: int, delimiters: frozenset[str], *, periods: bool) -> list[tuple[int, int]]:
    boundaries: list[int] = []
    index = start
    while index < end:
        char = text[index]
        boundary = char in delimiters or (periods and char == "." and _period_is_boundary(text[start:end], index - start))
        if boundary:
            boundary_end = index + 1
            while boundary_end < end and text[boundary_end] in CLOSING_PUNCTUATION:
                boundary_end += 1
            boundaries.append(boundary_end)
            index = boundary_end
        else:
            index += 1
    spans: list[tuple[int, int]] = []
    cursor = start
    for boundary_end in boundaries:
        visible_start = cursor
        while visible_start < boundary_end and text[visible_start].isspace():
            visible_start += 1
        visible_end = boundary_end
        while visible_end > visible_start and text[visible_end - 1].isspace():
            visible_end -= 1
        if visible_start < visible_end:
            spans.append((visible_start, visible_end))
        cursor = boundary_end
    visible_start = cursor
    while visible_start < end and text[visible_start].isspace():
        visible_start += 1
    visible_end = end
    while visible_end > visible_start and text[visible_end - 1].isspace():
        visible_end -= 1
    if visible_start < visible_end:
        spans.append((visible_start, visible_end))
    return spans


def _paragraph_atoms(text: str, paragraph: Paragraph, config: ChunkConfig) -> list[Paragraph]:
    sentence_spans = _split_at_boundaries(text, paragraph.start, paragraph.end, SENTENCE_END, periods=True)
    atoms: list[Paragraph] = []
    for sentence_start, sentence_end in sentence_spans:
        sentence_text = text[sentence_start:sentence_end]
        sentence_units = count_units(sentence_text)
        clause_spans = [(sentence_start, sentence_end)]
        if sentence_units > max(config.overlap_units + 10, 50):
            candidates = _split_at_boundaries(text, sentence_start, sentence_end, CLAUSE_END, periods=False)
            if len(candidates) > 1:
                clause_spans = candidates
        for atom_start, atom_end in clause_spans:
            atom_text = text[atom_start:atom_end]
            atoms.append(Paragraph(
                atom_start, atom_end, count_units(atom_text), paragraph.role,
                paragraph.blank_before and not atoms, atom_text,
                "clause" if clause_spans != [(sentence_start, sentence_end)] else "sentence" if len(sentence_spans) > 1 else "paragraph",
            ))
    return atoms


def extract_atoms(text: str, config: ChunkConfig | None = None) -> list[Paragraph]:
    """Extract exact-slice sentence/clause atoms used by Hybrid v3 packing."""
    config = config or ChunkConfig()
    atoms: list[Paragraph] = []
    for paragraph in extract_paragraphs(text):
        atoms.extend(_paragraph_atoms(text, paragraph, config))
    return atoms


def _sections(paragraphs: list[Paragraph], doc_type: str, strategy: str) -> list[list[Paragraph]]:
    if strategy == "basic" or doc_type == "qa":
        return [paragraphs]
    sections: list[list[Paragraph]] = []
    current: list[Paragraph] = []
    for paragraph in paragraphs:
        if current and paragraph.role == "heading":
            sections.append(current)
            current = []
        current.append(paragraph)
    if current:
        sections.append(current)
    return sections


def _parents(paragraphs: list[Paragraph], doc_type: str, strategy: str, config: ChunkConfig) -> list[list[Paragraph]]:
    result: list[list[Paragraph]] = []
    for section in _sections(paragraphs, doc_type, strategy):
        if strategy != "hybrid":
            result.append(section)
            continue
        current: list[Paragraph] = []
        units = 0
        for paragraph in section:
            if current and units + paragraph.units > config.parent_max_units and not (len(current) == 1 and current[0].role == "heading"):
                if len(current) > 1 and _looks_like_lead_in(current[-1]):
                    lead_in = current.pop()
                    result.append(current)
                    current, units = [lead_in], lead_in.units
                else:
                    result.append(current)
                    current, units = [], 0
            current.append(paragraph)
            units += paragraph.units
        if current:
            result.append(current)
    return result


def _target(doc_type: str, strategy: str, config: ChunkConfig) -> int:
    if strategy in ("basic", "structure"):
        return config.target_units
    if doc_type == "qa":
        return min(config.max_units, max(config.target_units, int(config.max_units * 0.93)))
    if doc_type == "other":
        return min(config.max_units, max(config.target_units, int(config.max_units * 0.8)))
    return config.target_units


def _related_boundary(left: Paragraph, right: Paragraph) -> bool:
    return (
        left.role == "heading"
        or (left.role == "question" and right.role == "answer")
        or bool(OPEN_CONTEXT_RE.search(left.text))
        or bool(CONTINUATION_RE.match(right.text))
    )


def _looks_like_lead_in(atom: Paragraph) -> bool:
    text = atom.text.strip()
    return (
        atom.role == "heading"
        or (
            atom.units <= 15
            and atom.boundary_type == "paragraph"
            and text
            and text[-1] not in ".!?;:。．！？；：，,"
        )
    )


def _child_groups(paragraphs: list[Paragraph], doc_type: str, strategy: str, config: ChunkConfig) -> list[list[Paragraph]]:
    if not paragraphs:
        return []
    if sum(paragraph.units for paragraph in paragraphs) <= config.max_units:
        return [paragraphs]
    target = _target(doc_type, strategy, config)
    base: list[tuple[int, int]] = []
    start = 0
    while start < len(paragraphs):
        end = start
        units = 0
        while end < len(paragraphs):
            next_units = paragraphs[end].units
            if end > start:
                if units + next_units > config.max_units:
                    break
                related = strategy in ("adaptive", "hybrid") and _related_boundary(paragraphs[end - 1], paragraphs[end])
                if units >= config.min_units and units + next_units > target and not related:
                    break
            units += next_units
            end += 1
        base.append((start, end))
        start = end
    groups: list[list[Paragraph]] = []
    for index, (start, end) in enumerate(base):
        if index and config.overlap_units:
            overlap = 0
            base_units = sum(item.units for item in paragraphs[start:end])
            while start > 0:
                candidate = paragraphs[start - 1].units
                if overlap + candidate > config.overlap_units or base_units + overlap + candidate > config.max_units:
                    break
                start -= 1
                overlap += candidate
        groups.append(paragraphs[start:end])
    return groups


def _hybrid_child_groups(atoms: list[Paragraph], doc_type: str, config: ChunkConfig) -> list[PackedGroup]:
    if not atoms:
        return []
    if sum(atom.units for atom in atoms) <= config.max_units:
        return [PackedGroup(atoms)]
    target = min(_target(doc_type, "hybrid", config), config.max_units - config.overlap_units)
    content_limit = config.max_units - config.overlap_units
    ranges: list[list[int]] = []
    start = 0
    while start < len(atoms):
        if atoms[start].units > config.max_units:
            ranges.append([start, start + 1])
            start += 1
            continue
        end = start
        units = 0
        while end < len(atoms):
            next_units = atoms[end].units
            if next_units > config.max_units:
                break
            if end > start and units + next_units > content_limit:
                break
            related = end > start and _related_boundary(atoms[end - 1], atoms[end])
            if end > start and units >= config.min_units and units + next_units > target and not related:
                break
            units += next_units
            end += 1
        if end == start:
            ranges.append([start, start + 1])
            start += 1
        else:
            ranges.append([start, end])
            start = end

    if len(ranges) > 1:
        last_start, last_end = ranges[-1]
        last_units = sum(atom.units for atom in atoms[last_start:last_end])
        if last_units < 100:
            previous_start, previous_end = ranges[-2]
            previous_units = sum(atom.units for atom in atoms[previous_start:previous_end])
            if previous_units + last_units <= content_limit:
                ranges[-2][1] = last_end
                ranges.pop()
            else:
                while last_units < 100 and previous_end - previous_start > 1:
                    candidate = atoms[previous_end - 1].units
                    if previous_units - candidate < config.min_units:
                        break
                    previous_end -= 1
                    last_start -= 1
                    previous_units -= candidate
                    last_units += candidate
                ranges[-2][1] = previous_end
                ranges[-1][0] = last_start

    for index in range(len(ranges) - 1):
        previous_start, previous_end = ranges[index]
        next_start, next_end = ranges[index + 1]
        if previous_end - previous_start <= 1 or previous_end != next_start:
            continue
        candidate = atoms[previous_end - 1]
        previous_units = sum(atom.units for atom in atoms[previous_start:previous_end])
        next_units = sum(atom.units for atom in atoms[next_start:next_end])
        if _looks_like_lead_in(candidate) and previous_units - candidate.units >= config.min_units and next_units + candidate.units <= content_limit:
            ranges[index][1] -= 1
            ranges[index + 1][0] -= 1

    groups: list[PackedGroup] = []
    for index, (base_start, end) in enumerate(ranges):
        if index == 0:
            groups.append(PackedGroup(atoms[base_start:end]))
            continue
        capacity = config.max_units - sum(atom.units for atom in atoms[base_start:end])
        overlap_start = base_start
        overlap = 0
        exception = None
        while overlap_start > 0:
            candidate = atoms[overlap_start - 1].units
            if candidate > capacity - overlap:
                exception = "max_capacity"
                break
            if candidate > 50:
                if overlap == 0:
                    overlap_start -= 1
                    overlap += candidate
                    exception = "oversized_atom"
                break
            if overlap + candidate > 50:
                break
            overlap_start -= 1
            overlap += candidate
            if overlap >= config.overlap_units:
                break
        if not overlap and exception is None:
            exception = "max_capacity"
        elif 0 < overlap < 30 and exception is None:
            exception = "below_target"
        groups.append(PackedGroup(atoms[overlap_start:end], overlap, exception))
    return groups


def _covered_non_whitespace(text: str, children: list[dict]) -> int:
    intervals = sorted((child["start_char"], child["end_char"]) for child in children)
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum(sum(not char.isspace() for char in text[start:end]) for start, end in merged)


def _included_regions(length: int, excluded: list[dict]) -> list[tuple[int, int]]:
    regions = []
    cursor = 0
    for span in excluded:
        if cursor < span["start_char"]:
            regions.append((cursor, span["start_char"]))
        cursor = max(cursor, span["end_char"])
    if cursor < length:
        regions.append((cursor, length))
    return regions


def chunk_document(record: dict, config: ChunkConfig | None = None, *, strategy: str = "hybrid") -> dict:
    """Create a compact, auditable hierarchy for one crawled document."""
    config = config or ChunkConfig()
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    doc_id, raw_text, url, success = (record.get(key) for key in ("id", "text", "url", "success"))
    if type(doc_id) is not int or not isinstance(raw_text, str) or not isinstance(url, str) or type(success) is not bool:
        raise ValueError("Record needs integer id, string text/url, and boolean success")
    output = {"doc_id": doc_id, "url": url, "status": "skipped", "parents": [], "children": []}
    if not success or not raw_text.strip():
        output["text"] = ""
        output["reason"] = "crawl_failed" if not success else "empty_text"
        return output
    source, cleaning = clean_with_report(raw_text)
    output.update(cleaning=cleaning, raw_sha256=cleaning["input_sha256"], source_sha256=cleaning["output_sha256"])
    if not source:
        output["text"] = ""
        output["reason"] = "empty_after_cleaning"
        return output
    if strategy == "format":
        from sbtc.Scripts.Preprocess.format_profiles import PROFILE_VERSION, is_crawl_error_placeholder
        if is_crawl_error_placeholder(source):
            output.update(
                status="skipped", strategy="format", version=config.version,
                profile_version=PROFILE_VERSION, text="", reason="crawl_error_placeholder",
            )
            return output
    all_paragraphs = extract_paragraphs(source)
    if not all_paragraphs:
        output["reason"] = "no_paragraphs"
        return output
    doc_type, classification_reason, classification_confidence = classify_document_details(source, url)
    output.update(
        status="ok", strategy=strategy, version=config.version, doc_type=doc_type,
        classification_reason=classification_reason,
        classification_confidence=classification_confidence,
        source_length=len(source), source_units=count_units(source),
    )
    if strategy == "format":
        from sbtc.Scripts.Preprocess.format_chunking import build_format_chunks
        return build_format_chunks(source, record, config, output)
    excluded = detect_boilerplate(source, url) if strategy == "hybrid" else []
    output["excluded_spans"] = [dict(span, doc_id=doc_id) for span in excluded]
    parents = []
    for region_start, region_end in _included_regions(len(source), excluded):
        region_paragraphs = _extract_paragraphs(source[region_start:region_end], region_start)
        if region_paragraphs:
            parents.extend(_parents(region_paragraphs, doc_type, strategy, config))
    for parent_order, parent_paragraphs in enumerate(parents):
        parent_start, parent_end = parent_paragraphs[0].start, parent_paragraphs[-1].end
        parent_id = f"{doc_id}:p:{parent_order}:{parent_start}:{parent_end}:{config.version}"
        output["parents"].append({
            "parent_id": parent_id, "start_char": parent_start, "end_char": parent_end,
            "block_type": "qa_region" if doc_type == "qa" else "section" if parent_paragraphs[0].role == "heading" else "region",
            "unit_count": sum(item.units for item in parent_paragraphs),
            "topic": None,
        })
        child_atoms = []
        for paragraph in parent_paragraphs:
            child_atoms.extend(_paragraph_atoms(source, paragraph, config) if strategy == "hybrid" else [paragraph])
        if strategy == "hybrid":
            packed_groups = _hybrid_child_groups(child_atoms, doc_type, config)
        else:
            packed_groups = []
            previous_end = None
            for group in _child_groups(child_atoms, doc_type, strategy, config):
                overlap = sum(item.units for item in group if previous_end is not None and item.end <= previous_end)
                packed_groups.append(PackedGroup(group, overlap, "max_capacity" if previous_end is not None and not overlap else None))
                previous_end = group[-1].end
        parent_units = sum(item.units for item in child_atoms)
        for packed_index, packed in enumerate(packed_groups):
            child_paragraphs = packed.atoms
            start, end = child_paragraphs[0].start, child_paragraphs[-1].end
            order = len(output["children"])
            units = sum(item.units for item in child_paragraphs)
            reason = "oversized_atom" if len(child_paragraphs) == 1 and child_paragraphs[0].units > config.max_units else None
            if units < 100:
                if output["source_units"] < 100:
                    short_reason = "short_document"
                elif doc_type == "qa" and parent_units < 100:
                    short_reason = "qa_atomic"
                elif parent_units < 100:
                    short_reason = "atomic_section"
                elif any(item.units > config.max_units for item in child_atoms):
                    short_reason = "oversized_neighbor"
                else:
                    short_reason = "atomic_section"
            else:
                short_reason = None
            first_in_parent = packed_index == 0
            child = {
                "chunk_id": f"{doc_id}:c:{order}:{start}:{end}:{config.version}",
                "parent_id": parent_id, "doc_id": doc_id, "chunk_order": order,
                "start_char": start, "end_char": end, "chunk_text": source[start:end],
                "unit_count": units, "oversized_reason": reason,
                "boundary_type": child_paragraphs[-1].boundary_type,
                "short_chunk_reason": short_reason,
                "overlap_units": packed.overlap_units,
                "overlap_exception": (
                    "document_start" if first_in_parent and not output["children"] else
                    "parent_boundary" if first_in_parent else packed.overlap_exception
                ),
                "retrieval_eligible": True,
            }
            if not (parent_start <= start < end <= parent_end) or child["chunk_text"] != source[start:end]:
                raise AssertionError("Invalid parent-child source span")
            output["children"].append(child)
    total = sum(not char.isspace() for char in source)
    indexed = _covered_non_whitespace(source, output["children"])
    excluded_count = _covered_non_whitespace(source, output["excluded_spans"])
    covered = _covered_non_whitespace(source, output["children"] + output["excluded_spans"])
    output["coverage"] = {
        "non_whitespace_total": total,
        "non_whitespace_covered": covered,
        "non_whitespace_indexed": indexed,
        "non_whitespace_excluded": excluded_count,
    }
    heading_starts = [item.start for item in all_paragraphs[1:] if item.role == "heading"]
    intact = 0
    for child in output["children"]:
        next_heading = bisect_right(heading_starts, child["start_char"])
        intact += next_heading == len(heading_starts) or heading_starts[next_heading] >= child["end_char"]
    output["structural_boundary_rate"] = intact / len(output["children"]) if output["children"] else 1.0
    if covered != total:
        raise AssertionError("Source content was not covered by child spans")
    return output
