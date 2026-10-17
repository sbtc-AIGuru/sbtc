"""Pack format-profile atoms without rewriting or splicing source text."""
from __future__ import annotations

from sbtc.Scripts.Preprocess.chunking import ChunkConfig, count_units, _covered_non_whitespace
from sbtc.Scripts.Preprocess.format_profiles import Atom, PROFILE_VERSION, analyse_format


def _parent_groups(atoms: list[Atom], config: ChunkConfig) -> list[list[Atom]]:
    groups, current, units = [], [], 0
    for atom in atoms:
        if current and (atom.region != current[-1].region or units + atom.units > config.parent_max_units):
            groups.append(current)
            current, units = [], 0
        current.append(atom)
        units += atom.units
    if current: groups.append(current)
    # Rebalance a tiny parent remainder within the same semantic region.
    for index in range(len(groups) - 1, 0, -1):
        previous, tail = groups[index - 1], groups[index]
        if previous[-1].region != tail[0].region: continue
        while sum(a.units for a in tail) < config.min_units and len(previous) > 1:
            candidate = previous[-1]
            if sum(a.units for a in previous[:-1]) < config.min_units: break
            if sum(a.units for a in tail) + candidate.units > config.parent_max_units: break
            tail.insert(0, previous.pop())
    return groups


def _pack(atoms: list[Atom], config: ChunkConfig) -> list[tuple[int, int, str | None]]:
    if sum(a.units for a in atoms) <= config.max_units:
        return [(0, len(atoms), None)]
    ranges = []
    start = 0
    while start < len(atoms):
        end, units = start, 0
        while end < len(atoms):
            atom = atoms[end]
            if end > start and (units + atom.units > config.max_units or
                                units >= config.target_units or atom.units > config.max_units):
                break
            units += atom.units
            end += 1
            if atom.units > config.max_units: break
        ranges.append([start, end])
        start = end
    # A short tail is often avoidable by moving an intact sentence from its neighbour.
    if len(ranges) > 1:
        left, tail = ranges[-2], ranges[-1]
        left_units = sum(a.units for a in atoms[left[0]:left[1]])
        tail_units = sum(a.units for a in atoms[tail[0]:tail[1]])
        if left_units + tail_units <= config.max_units:
            left[1] = tail[1]
            ranges.pop()
        else:
            while tail_units < config.min_units and left[1] - left[0] > 1:
                candidate = atoms[left[1] - 1].units
                if left_units - candidate < config.min_units or tail_units + candidate > config.max_units: break
                left[1] -= 1
                tail[0] -= 1
                left_units -= candidate
                tail_units += candidate
    packed = []
    for index, (base_start, end) in enumerate(ranges):
        overlap_start = base_start
        exception = None
        if index and config.overlap_units:
            capacity = config.max_units - sum(a.units for a in atoms[base_start:end])
            previous_start = ranges[index - 1][0]
            overlap = 0
            candidates = []
            while overlap_start > previous_start:
                candidate = atoms[overlap_start - 1].units
                if overlap + candidate > capacity: break
                overlap_start -= 1
                overlap += candidate
                candidates.append((abs(overlap - config.overlap_units), overlap_start, overlap))
                if overlap >= config.overlap_units: break
            if candidates:
                _, overlap_start, overlap = min(candidates)
                if not 30 <= overlap <= 50: exception = "whole_atom_overlap"
            else:
                overlap_start = base_start
                exception = "whole_atom_exceeds_capacity"
        elif index:
            exception = "overlap_disabled"
        packed.append((overlap_start, end, exception))
    return packed


def _atom_metadata(atom: Atom) -> dict:
    return dict(start_char=atom.start, end_char=atom.end, role=atom.role, boundary_type=atom.boundary_type,
                section_path=list(atom.section_path), language=atom.language, region=atom.region, unit_count=atom.units)


def build_format_chunks(source: str, record: dict, config: ChunkConfig, output: dict) -> dict:
    analysis = analyse_format(source, record["url"])
    metadata, atoms = analysis["metadata"], analysis["atoms"]
    output.update(metadata)
    output["version"] = PROFILE_VERSION
    output["packing_version"] = config.version
    output["atom_spans"] = [_atom_metadata(atom) for atom in atoms]
    for name in ("heading_spans", "question_spans", "answer_spans", "content_language_spans", "protected_spans"):
        output[name] = analysis[name]
    doc_id = record["id"]
    excluded = [dict(span, doc_id=doc_id) for span in analysis["excluded_spans"]]
    output["excluded_spans"] = excluded
    question = None
    if analysis["question_spans"]:
        question = dict(start_char=analysis["question_spans"][0]["start_char"], end_char=analysis["question_spans"][-1]["end_char"])
    for parent_order, parent_atoms in enumerate(_parent_groups(atoms, config)):
        start, end = parent_atoms[0].start, parent_atoms[-1].end
        parent_id = f"{doc_id}:p:{parent_order}:{start}:{end}:{PROFILE_VERSION}"
        roles = sorted({a.role for a in parent_atoms})
        parent = dict(parent_id=parent_id, start_char=start, end_char=end, block_type=metadata["profile"],
                      unit_count=count_units(source[start:end]), section_roles=roles,
                      section_paths=[list(p) for p in dict.fromkeys(a.section_path for a in parent_atoms)],
                      content_languages=sorted({a.language for a in parent_atoms}), question_span=question)
        output["parents"].append(parent)
        previous_child = None
        for first_atom, end_atom, exception in _pack(parent_atoms, config):
            selected = parent_atoms[first_atom:end_atom]
            child_start, child_end = selected[0].start, selected[-1].end
            units = count_units(source[child_start:child_end])
            oversized = None
            if units > config.max_units:
                oversized = "oversized_structural_atom" if selected[0].boundary_type in ("structural_atom", "list_entry") else "oversized_sentence"
            overlap = 0
            if previous_child and child_start < previous_child["end_char"]:
                overlap = count_units(source[child_start:min(child_end, previous_child["end_char"])])
            if not previous_child:
                exception = "document_start" if not output["children"] else "semantic_region_or_parent_boundary"
            if units < 100:
                short_reason = ("short_document" if output["source_units"] < 100 else
                                "question_context" if all(a.role in ("title", "question") for a in selected) and metadata["profile"] == "qa" else
                                "hard_boundary_region" if parent["unit_count"] < 100 else "whole_atom_budget_remainder")
                evidence = dict(parent_units=parent["unit_count"], source_units=output["source_units"],
                                atom_units=[a.units for a in selected], max_units=config.max_units,
                                region=selected[0].region)
            else:
                short_reason, evidence = None, None
            order = len(output["children"])
            child = dict(chunk_id=f"{doc_id}:c:{order}:{child_start}:{child_end}:{PROFILE_VERSION}", parent_id=parent_id,
                         doc_id=doc_id, chunk_order=order, start_char=child_start, end_char=child_end,
                         chunk_text=source[child_start:child_end], unit_count=units, oversized_reason=oversized,
                         boundary_type=selected[-1].boundary_type, boundary_reason="whole_source_atom",
                         short_chunk_reason=short_reason, short_reason_evidence=evidence,
                         overlap_units=overlap, overlap_exception=exception, retrieval_eligible=True,
                         profile=metadata["profile"], section_roles=sorted({a.role for a in selected}),
                         section_paths=[list(p) for p in dict.fromkeys(a.section_path for a in selected)],
                         content_languages=sorted({a.language for a in selected}),
                         protected_span_checks={"cuts": 0, "policy": "whole_sentence_and_structural_atoms"})
            output["children"].append(child)
            previous_child = child
    total = sum(not ch.isspace() for ch in source)
    indexed = _covered_non_whitespace(source, output["children"])
    excluded_count = _covered_non_whitespace(source, excluded)
    covered = _covered_non_whitespace(source, output["children"] + excluded)
    if covered != total: raise AssertionError("Format chunk spans do not cover source")
    output["coverage"] = dict(non_whitespace_total=total, non_whitespace_covered=covered,
                              non_whitespace_indexed=indexed, non_whitespace_excluded=excluded_count)
    output["structural_boundary_rate"] = 1.0  # Boundaries preserve atoms; this is not a retrieval metric.
    warnings = []
    if metadata["format_confidence"] == "low": warnings.append(dict(code="uncertain_format", count=1))
    if any(child["oversized_reason"] for child in output["children"]):
        warnings.append(dict(code="oversized_atom_review", count=sum(bool(c["oversized_reason"]) for c in output["children"])))
    if record["text"].count("|") >= 6:
        warnings.append(dict(code="structure_lost", count=1))
    if metadata["profile"] == "structured_list": warnings.append(dict(code="content_limited", count=1))
    output["format_warnings"] = warnings
    return output
