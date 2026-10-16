"""Create auditable, read-only-derived curation artifacts for medical resources.

The source files are never edited. This command intentionally does not install the
derived terms into the retrieval analyzer or index.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


RULE_VERSION = "resource-curation-1.0"
LANGUAGES = ("vi", "en", "zh")
WORKSPACE = Path(__file__).resolve().parents[3]
RESOURCE_DIR = WORKSPACE / "sbtc" / "Resources"
SEED_PATH = WORKSPACE / "sbtc" / "Scripts" / "Retrieval" / "resources" / "concepts.json"
DEFAULT_OUTPUT = WORKSPACE / "sbtc" / "Scripts" / "Retrieval" / "resources" / "curated" / "20261015"

BASE_FILES = {
    "vi": RESOURCE_DIR / "base_vi.txt",
    "en": RESOURCE_DIR / "base_en.txt",
    "zh": RESOURCE_DIR / "base_zh.txt",
}
ALIGNED_PATH = RESOURCE_DIR / "concepts_aligned_vi_en_zh.jsonl"
SAMPLE_PATH = RESOURCE_DIR / "medical_lexicon_vi_en_zh.sample.jsonl"

QID_EVIDENCE = {
    "Q12136": {
        "status": "rejected_external_id",
        "reason": "Đối chiếu audit trước xác định QID không khớp nhãn renal failure.",
        "url": "https://www.wikidata.org/wiki/Q12136",
    },
    "Q181754": {
        "status": "rejected_external_id",
        "reason": "Đối chiếu audit trước xác định QID là heart failure, không phải paracetamol.",
        "url": "https://www.wikidata.org/wiki/Q181754",
    },
}

VI_LEADING_FRAGMENT = {
    "của", "và", "các", "những", "được", "trong", "cho", "tại", "với", "như", "vì", "sau", "trước",
    "ở", "năm", "ngày", "tháng", "một số",
}
VI_TRAILING_FRAGMENT = {
    "và", "hoặc", "của", "trong", "cho", "về", "với", "như", "các", "một số", "xem thêm", "là",
    "cao hơn một chút", "thấp hơn một chút",
}
VI_CONTEXT_WORDS = {
    "có", "được", "là", "theo", "người", "tại", "cho", "nằm", "đang", "mang", "vùng", "tuổi",
    "bị", "đều", "đối", "việc", "bạn", "nó", "khác", "sau", "dùng", "làm", "xảy", "như",
    "chiếm", "đầu", "trên", "cả", "nước", "lại", "ăn", "ông", "bà", "do",
}
EN_LEADING_FRAGMENT = {"of", "and", "with", "in", "on", "for", "the", "a", "an", "to", "without", "not"}
EN_TRAILING_FRAGMENT = {"and", "or", "of", "in", "for", "with", "to", "the", "a", "an"}
ZH_FRAGMENT_PREFIXES = ("年的", "的", "和", "与", "及", "节和", "在", "为", "于")
ZH_CONTEXT_MARKERS = ("不算", "不是", "没有", "无", "未见", "否认")
ZH_ACTION_PREFIXES = (
    "如", "可能", "达到", "达", "引起", "指导", "结合", "断为", "群是", "些", "前让",
    "膜局部", "歇性", "一些", "任何", "主要是", "完整", "者可服", "折磨",
)
ZH_CONTEXT_MARKERS_EXTRA = (
    "用于", "能否", "左右", "发作时", "发作后", "是否", "出现", "注射", "打针", "患病",
    "目前", "时期", "之后", "可服", "主要是", "任何一种", "一些", "完整", "者可", "折磨",
    "患有", "可以", "服用", "能不能", "会发生", "一旦", "家针对", "白或", "么是",
)
VI_GENERIC_REVIEW = {
    "bệnh cao hơn một chút", "bệnh gan và một số", "bệnh loãng xương xem thêm", "thuốc yêu quý",
    "chứng minh của thịt cóc", "chứng như tay yếu", "thuốc kháng axit thuốc", "bệnh hô hấp xảy",
    "thuốc trên cả nước", "thuốc dùng gừng", "thuốc ông nguyễn văn",
    "thuốc trước khi đoàn", "bệnh gout bệnh gout", "chứng và hậu quả", "thuốc men và bv",
    "thuốc không quy ước", "đau dịu đi", "xét nghiệm bệnh covid", "thuốc nhả", "thuốc điều chỉnh ức",
    "chứng đần độn", "thuốc nhất định", "thuốc trước mỗi lần", "bệnh chuyển biến nhanh",
    "bệnh không biết", "viêm nhiễm stds", "chứng và hỗ trợ", "thuốc điều hòa huyết",
    "thuốc men và chế", "thuốc không quá 60mg",
}
EN_GENERIC_REVIEW = {"fat", "inflammatory disorder", "neurological burden of disease"}
ZH_NONMEDICAL_REVIEW = {
    "指责孩子", "的指责孩子", "温州割包皮", "德州肿瘤", "烟台肿瘤", "邵通皮肤病",
    "克抄枣仁", "接回流入皮", "约凯丽雅皮", "不触到皮", "濮阳癫痫病", "部位的结核病",
    "控制症", "容易生病", "会有少少疼痛", "一是睾丸", "者加生石膏", "妈要控制好病",
    "不饮用茶叶", "性的佩罗尼病", "阻碍精子", "对热刺激的痛", "停药后原发病",
    "摸两个睾丸", "免了口服止痛", "性限局性皮", "控制脑部肿瘤", "容的常见皮", "乌鲁木齐皮",
}
FUNCTIONAL_ALIASES = {"hạ sốt", "thuốc kháng đông"}
REPORT_REVIEW_EXAMPLES = {
    "vi": (
        "bệnh cao hơn một chút", "bệnh gan và một số", "bệnh loãng xương xem thêm", "thuốc yêu quý",
        "bệnh viện e trong tình", "chứng như tay yếu", "thuốc ông nguyễn văn", "thuốc trước khi đoàn",
        "bệnh gout bệnh gout", "chứng và hậu quả",
    ),
    "en": ("anthrax meningitisg01", "meningococcal meningitisg01", "tuberculous meningitisg01", "fat", "inflammatory disorder"),
    "zh": (
        "不算糖尿病", "指责孩子", "的指责孩子", "年的慢性咽炎", "节和肌肉疼痛",
        "达到止痛", "如肉样瘤病", "克抄枣仁", "么是小儿重症", "妈要控制好病",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            raise ValueError(f"Blank JSONL line at {path}:{line_number}; refusing silent data loss")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_number}")
        rows.append((line_number, value))
    return rows


def json_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json_line(row) + "\n" for row in rows), encoding="utf-8")


def classify_term(term: str, language: str) -> tuple[str, list[str]]:
    value = normalize(term)
    reasons: list[str] = []
    if not value:
        return "exclude", ["empty_term"]
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in term):
        return "exclude", ["control_character"]
    if re.search(r"https?://|www\.|<[^>]*>|\[[^\]]+\]\([^)]*\)|(?:^|\s)#{1,6}\s", value):
        return "exclude", ["markup_or_url"]
    if html.unescape(value) != value or re.search(r"&(?:nbsp|amp|lt|gt|quot);", value):
        return "exclude", ["unresolved_html_entity"]

    tokens = value.split()
    if language == "vi":
        if len(tokens) == 5:
            reasons.append("five_token_window_shape_requires_review")
        if tokens[0] in VI_LEADING_FRAGMENT or value.startswith("một số "):
            reasons.append("possible_sentence_prefix")
        if tokens[-1] in VI_TRAILING_FRAGMENT or any(value.endswith(" " + phrase) for phrase in VI_TRAILING_FRAGMENT):
            reasons.append("possible_sentence_suffix")
        if "bệnh viện" in value:
            reasons.append("organization_or_provider_candidate")
        if value in VI_GENERIC_REVIEW:
            reasons.append("known_fragment_or_nonmedical_sample")
        if any(marker in value for marker in ("không tính", "không có", "chưa có", "không phải")):
            reasons.append("negation_or_context_candidate")
        if any(
            marker in value
            for marker in (
                "chứng minh", "là một loại", "gắn liền với", "xâm nhập vào", "lây qua các",
                "là do", "có thể", "không thể", "tập luyện", "mang vớ", "khoảng", "tại bv",
                "tại bệnh viện", "dược liệu ngừa", "như thế nào",
            )
        ):
            reasons.append("possible_sentence_or_context_phrase")
        if VI_CONTEXT_WORDS.intersection(tokens):
            reasons.append("possible_context_word")
    elif language == "en":
        if tokens[0] in EN_LEADING_FRAGMENT:
            reasons.append("possible_sentence_prefix")
        if tokens[-1] in EN_TRAILING_FRAGMENT:
            reasons.append("possible_sentence_suffix")
        if value in EN_GENERIC_REVIEW:
            reasons.append("generic_or_broad_phrase")
        if re.search(r"(?:meningitis|encephalitis|tuberculosis|anthrax)[a-z]\d{1,3}$", value):
            reasons.append("possible_code_glued_to_label")
    elif language == "zh":
        if value.startswith(ZH_FRAGMENT_PREFIXES):
            reasons.append("possible_sentence_prefix")
        if value.endswith(("和", "与", "及", "的", "在", "为")):
            reasons.append("possible_sentence_suffix")
        if any(marker in value for marker in ZH_CONTEXT_MARKERS):
            reasons.append("negation_or_context_candidate")
        if value in ZH_NONMEDICAL_REVIEW:
            reasons.append("known_nonmedical_sample")
        if "医院" in value:
            reasons.append("organization_or_provider_candidate")
        if value.startswith(ZH_ACTION_PREFIXES):
            reasons.append("possible_sentence_or_action_prefix")
        if any(marker in value for marker in ("可能因", "可能与", "达到", "引起", "导致", "患病")):
            reasons.append("possible_sentence_or_context_phrase")
        if any(marker in value for marker in ZH_CONTEXT_MARKERS_EXTRA):
            reasons.append("possible_context_phrase")
    else:
        raise ValueError(f"Unsupported language: {language}")

    if re.search(r"[。！？!?;；]", value):
        reasons.append("sentence_punctuation")
    return ("review" if reasons else "lexical_candidate"), sorted(set(reasons))


def curate_base(language: str, path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    groups: dict[str, dict[str, Any]] = {}
    raw_classifications = Counter()
    for line_number, original in enumerate(lines, start=1):
        normalized = normalize(original)
        status, reasons = classify_term(original, language)
        raw_classifications[status] += 1
        record = groups.setdefault(
            normalized,
            {
                "language": language,
                "normalized_term": normalized,
                "display_terms": [],
                "source_refs": [],
                "classification": status,
                "reasons": [],
                "rule_version": RULE_VERSION,
                "source_license_status": "unknown",
                "semantic_validation_status": "not_assessed",
            },
        )
        if original not in record["display_terms"]:
            record["display_terms"].append(original)
        record["source_refs"].append({"file": path.relative_to(WORKSPACE).as_posix(), "line": line_number})
        if status == "exclude" or (status == "review" and record["classification"] == "lexical_candidate"):
            record["classification"] = status
        record["reasons"] = sorted(set(record["reasons"]) | set(reasons))

    records = [groups[key] for key in sorted(groups)]
    stats = {
        "source_line_count": len(lines),
        "nonempty_source_line_count": sum(bool(line.strip()) for line in lines),
        "deduplicated_term_count": len(records),
        "classification_by_source_line": dict(sorted(raw_classifications.items())),
        "classification_by_deduplicated_term": dict(sorted(Counter(row["classification"] for row in records).items())),
        "review_reason_counts_by_term": dict(
            sorted(Counter(reason for row in records if row["classification"] == "review" for reason in row["reasons"]).items())
        ),
        "source_line_references_in_output": sum(len(row["source_refs"]) for row in records),
    }
    return records, stats


def validate_aligned_record(line_number: int, row: dict[str, Any]) -> None:
    required = {"concept_id", "category", "vi", "en", "zh", "icd10_code"}
    missing = required - row.keys()
    if missing:
        raise ValueError(f"Missing aligned fields at line {line_number}: {sorted(missing)}")
    if not isinstance(row["concept_id"], str) or not row["concept_id"].strip():
        raise ValueError(f"Invalid concept_id at line {line_number}")
    if not isinstance(row["category"], str) or not row["category"].strip():
        raise ValueError(f"Invalid category at line {line_number}")
    if any(not isinstance(row[lang], str) or not row[lang].strip() for lang in LANGUAGES):
        raise ValueError(f"Missing/non-string language label at line {line_number}")
    if not isinstance(row["icd10_code"], str):
        raise ValueError(f"Non-string icd10_code at line {line_number}")


def curate_aligned(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    source_rows = read_jsonl(path)
    groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    source_ids: set[str] = set()
    for line_number, row in source_rows:
        validate_aligned_record(line_number, row)
        if row["concept_id"] in source_ids:
            raise ValueError(f"Duplicate source concept_id {row['concept_id']} at line {line_number}")
        source_ids.add(row["concept_id"])
        key = tuple(normalize(row[lang]) for lang in LANGUAGES)
        groups[key].append((line_number, row))

    ordered_groups = sorted(groups.items(), key=lambda item: min(line for line, _ in item[1]))
    id_map: list[dict[str, Any]] = []
    concepts: list[dict[str, Any]] = []
    for key, members in ordered_groups:
        members.sort(key=lambda item: item[0])
        _, first = members[0]
        canonical_id = f"aligned:{first['concept_id']}"
        source_lines = [line for line, _ in members]
        original_ids = [row["concept_id"] for _, row in members]
        for index, (line_number, row) in enumerate(members):
            id_map.append(
                {
                    "source_concept_id": row["concept_id"],
                    "source_line": line_number,
                    "canonical_concept_id": canonical_id,
                    "mapping_rule": "exact_triple_merge" if index else "canonical_first_occurrence",
                }
            )
        icd_codes = sorted({row["icd10_code"].strip() for _, row in members if row["icd10_code"].strip()})
        categories = list(dict.fromkeys(row["category"] for _, row in members))
        concepts.append(
            {
                "concept_id": canonical_id,
                "source_concept_ids": original_ids,
                "labels": {lang: [first[lang]] for lang in LANGUAGES},
                "normalized_labels": {lang: key[index] for index, lang in enumerate(LANGUAGES)},
                "categories": categories,
                "category_conflict": len(categories) > 1,
                "icd10_codes": icd_codes,
                "icd10_verification_status": "unverified",
                "source_refs": [{"file": path.relative_to(WORKSPACE).as_posix(), "line": line} for line in source_lines],
                "exact_triple_duplicate_count": len(members) - 1,
                "ambiguous_labels": {lang: [] for lang in LANGUAGES},
                "status": "concept_candidate",
                "semantic_validation_status": "unverified",
                "source_license_status": "missing_in_source",
                "source": path.relative_to(WORKSPACE).as_posix(),
                "rule_version": RULE_VERSION,
            }
        )

    label_owners: dict[str, dict[str, set[str]]] = {lang: defaultdict(set) for lang in LANGUAGES}
    for concept in concepts:
        for lang in LANGUAGES:
            label_owners[lang][concept["normalized_labels"][lang]].add(concept["concept_id"])
    collision_groups: dict[str, int] = {}
    collision_label_records: dict[str, int] = {}
    for lang in LANGUAGES:
        colliding = {term: owners for term, owners in label_owners[lang].items() if len(owners) > 1}
        collision_groups[lang] = len(colliding)
        collision_label_records[lang] = sum(len(owners) for owners in colliding.values())
        for concept in concepts:
            term = concept["normalized_labels"][lang]
            if len(label_owners[lang][term]) > 1:
                concept["ambiguous_labels"][lang].append(term)

    stats = {
        "source_record_count": len(source_rows),
        "source_id_count": len(source_ids),
        "schema_validation": "passed",
        "canonical_exact_triple_count": len(concepts),
        "exact_triple_duplicate_groups": sum(1 for members in groups.values() if len(members) > 1),
        "rows_merged_as_exact_triples": sum(len(members) - 1 for members in groups.values()),
        "id_map_count": len(id_map),
        "icd_records_unverified": sum(bool(row["icd10_codes"]) for row in concepts),
        "label_collision_groups_by_language": collision_groups,
        "canonical_concepts_in_collision_by_language": collision_label_records,
    }
    if len(id_map) != len(source_rows):
        raise AssertionError("Aligned source ID mapping is incomplete")
    return concepts, id_map, stats


def alias_language(alias: str) -> tuple[str, str]:
    value = normalize(alias)
    if re.search(r"[\u3400-\u9fff]", value):
        return "zh", "han_script"
    if re.search(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặếềểễệốồổỗộớờởỡợứừửữự]", value):
        return "vi", "vietnamese_diacritic"
    return "unknown", "ascii_or_language_not_determinable"


def curate_sample(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(path)
    result: list[dict[str, Any]] = []
    for line_number, row in rows:
        identifier = row.get("concept_id")
        labels = row.get("labels")
        aliases = row.get("aliases", [])
        if not isinstance(identifier, str) or not isinstance(labels, dict) or not isinstance(aliases, list):
            raise ValueError(f"Invalid sample lexicon schema at line {line_number}")
        if not isinstance(row.get("type"), str) or not row["type"].strip():
            raise ValueError(f"Invalid sample type at line {line_number}")
        if not isinstance(row.get("ambiguity"), bool):
            raise ValueError(f"Invalid sample ambiguity flag at line {line_number}")
        for lang in LANGUAGES:
            if not isinstance(labels.get(lang), str) or not labels[lang].strip():
                raise ValueError(f"Invalid sample label {lang} at line {line_number}")
        evidence = QID_EVIDENCE.get(identifier, {})
        alias_rows = []
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError(f"Invalid alias at line {line_number}")
            lang, language_evidence = alias_language(alias)
            relation_reason = "source does not establish exact synonym relation"
            if normalize(alias) in {normalize(term) for term in FUNCTIONAL_ALIASES}:
                relation_reason = "possible treatment/function relation, not proven exact synonym"
            alias_rows.append(
                {
                    "text": alias,
                    "language": lang,
                    "language_assignment_basis": language_evidence,
                    "relation_status": "unverified",
                    "relation_reason": relation_reason,
                }
            )
        result.append(
            {
                "source_ref": {"file": path.relative_to(WORKSPACE).as_posix(), "line": line_number},
                "concept_id": identifier,
                "type": row.get("type"),
                "labels": row["labels"],
                "aliases": alias_rows,
                "source_ambiguity_flag": row.get("ambiguity"),
                "external_id_status": evidence.get("status", "review_external_id"),
                "external_id_reason": evidence.get("reason", "QID chưa được xác minh trong audit hiện tại."),
                "external_id_evidence_url": evidence.get("url"),
                "eligible_as_anchor": False,
                "rule_version": RULE_VERSION,
            }
        )
    stats = {
        "source_record_count": len(rows),
        "schema_validation": "passed",
        "external_id_rejected": sum(row["external_id_status"] == "rejected_external_id" for row in result),
        "external_id_pending_review": sum(row["external_id_status"] == "review_external_id" for row in result),
        "aliases_unverified": sum(len(row["aliases"]) for row in result),
        "aliases_language_unknown": sum(alias["language"] == "unknown" for row in result for alias in row["aliases"]),
    }
    return result, stats


def compare_seed(seed_path: Path, concepts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(seed.get("concepts"), list):
        raise ValueError("Seed concepts.json does not contain a concepts list")
    owners: dict[str, dict[str, set[str]]] = {lang: defaultdict(set) for lang in LANGUAGES}
    aligned_by_id = {concept["concept_id"]: concept for concept in concepts}
    for concept in concepts:
        for lang in LANGUAGES:
            owners[lang][concept["normalized_labels"][lang]].add(concept["concept_id"])

    comparisons = []
    for position, local in enumerate(seed["concepts"], start=1):
        if not isinstance(local, dict) or not isinstance(local.get("labels"), dict):
            raise ValueError(f"Invalid local seed record at position {position}")
        if not isinstance(local.get("concept_id"), str):
            raise ValueError(f"Invalid local seed concept at position {position}")
        if not local.get("source") or not local.get("license"):
            raise ValueError(f"Local seed provenance missing at position {position}")
        for lang in LANGUAGES:
            if not isinstance(local["labels"].get(lang), list):
                raise ValueError(f"Invalid local seed labels for {lang} at position {position}")
        local_labels = {
            lang: {
                normalize(term)
                for term in local.get("labels", {}).get(lang, [])
                if isinstance(term, str) and term.strip()
            }
            for lang in LANGUAGES
        }
        matching_languages: dict[str, list[str]] = {}
        candidates: set[str] = set()
        for lang in LANGUAGES:
            matches = set().union(*(owners[lang].get(term, set()) for term in local_labels[lang])) if local_labels[lang] else set()
            matching_languages[lang] = sorted(matches)
            candidates.update(matches)
        matched_lang_count = sum(bool(matching_languages[lang]) for lang in LANGUAGES)
        exact = [
            concept_id
            for concept_id in candidates
            if all(
                concept_id in matching_languages[lang]
                and aligned_by_id[concept_id]["normalized_labels"][lang] in local_labels[lang]
                for lang in LANGUAGES
            )
        ]
        basis = "exact_triple_label_overlap" if exact else (
            "partial_label_overlap" if matched_lang_count >= 2 else "single_or_no_label_overlap"
        )
        comparisons.append(
            {
                "seed_concept_id": local["concept_id"],
                "seed_position": position,
                "aligned_candidate_ids": sorted(candidates),
                "aligned_exact_triple_ids": sorted(exact),
                "matched_languages": [lang for lang in LANGUAGES if matching_languages[lang]],
                "matches_by_language": matching_languages,
                "comparison_basis": basis,
                "semantic_equivalence_status": "not_assessed",
                "source_license_status": "team_authored_seed; aligned_resource_license_unknown",
                "rule_version": RULE_VERSION,
            }
        )
    stats = {
        "seed_concept_count": len(comparisons),
        "exact_triple_label_overlap_count": sum(row["comparison_basis"] == "exact_triple_label_overlap" for row in comparisons),
        "partial_label_overlap_count": sum(row["comparison_basis"] == "partial_label_overlap" for row in comparisons),
        "single_or_no_label_overlap_count": sum(row["comparison_basis"] == "single_or_no_label_overlap" for row in comparisons),
    }
    return comparisons, stats


def verify_jsonl(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            value = json.loads(line)
            if not isinstance(value, dict):
                raise AssertionError(f"Non-object output at {path}:{line_number}")
            count += 1
    return count


def create_report(output_dir: Path, stats: dict[str, Any], samples: dict[str, list[dict[str, Any]]]) -> None:
    lines = [
        "# Resource curation report — 2026-10-15",
        "",
        f"Rule version: {RULE_VERSION}. Source files are read-only; this output is not installed into BM25.",
        "",
        "## Monolingual lists",
        "",
        "| Language | Source lines | Unique terms | Lexical candidates | Review | Excluded |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lang in LANGUAGES:
        item = stats["base"][lang]
        classes = item["classification_by_deduplicated_term"]
        lines.append(
            f"| {lang} | {item['source_line_count']} | {item['deduplicated_term_count']} | "
            f"{classes.get('lexical_candidate', 0)} | {classes.get('review', 0)} | {classes.get('exclude', 0)} |"
        )
    for lang in LANGUAGES:
        reasons = stats["base"][lang]["review_reason_counts_by_term"]
        lines.append(f"\n- {lang} review reasons: {json.dumps(reasons, ensure_ascii=False, sort_keys=True)}")
    lines.append("\nReason counts overlap when one term has several review cues; they are not disjoint groups.")
    lines.extend(
        [
            "",
            "lexical_candidate means only that deterministic structural rules found no review/exclusion cue. It is not a claim that the phrase is medically correct or an exact synonym.",
            "Vietnamese five-token entries are routed to review because the source has an unusually high five-token concentration; likely sentence/context words and Chinese action/context markers are also routed to review.",
            "A separate fixed-seed sample of 15 lexical candidates per language exposed residual contextual fragments and noisy strings. Several clear examples were moved into review; this sample does not estimate the full semantic error rate.",
            "Review records retain their source references and reasons. Excluded records are limited to mechanically identifiable formatting/empty/control problems.",
            "",
            "## Aligned concepts",
            "",
            f"- Input records: {stats['aligned']['source_record_count']}",
            f"- JSON/schema validation: {stats['aligned']['schema_validation']}; no malformed row was skipped.",
            f"- Exact normalized VI/EN/ZH triples after merge: {stats['aligned']['canonical_exact_triple_count']}",
            f"- Exact-triple duplicate groups: {stats['aligned']['exact_triple_duplicate_groups']}",
            f"- Redundant source rows merged: {stats['aligned']['rows_merged_as_exact_triples']}",
            f"- ICD-bearing canonical records, all unverified: {stats['aligned']['icd_records_unverified']}",
            f"- Label collision groups after exact-triple merge by language: {json.dumps(stats['aligned']['label_collision_groups_by_language'], ensure_ascii=False, sort_keys=True)}",
            "- Only exact triples are merged. Partial language collisions remain separate and are marked ambiguous for that language.",
            "- No source/license fields were present in the aligned file; the output records this as unknown/missing.",
            "",
            "## Sample external IDs",
            "",
            f"- Records: {stats['sample']['source_record_count']}; rejected external IDs: {stats['sample']['external_id_rejected']}; pending external ID review: {stats['sample']['external_id_pending_review']}.",
            f"- JSON/schema validation: {stats['sample']['schema_validation']}; no malformed row was skipped.",
            "- Rejected IDs are not deleted from the source; their records are retained in the review output and cannot be used as anchors.",
            "- Every alias relation remains unverified. ASCII aliases are marked language-unknown when script alone cannot establish language.",
            "",
            "## Local seed comparison",
            "",
            f"- Seed concepts compared: {stats['seed_comparison']['seed_concept_count']}",
            f"- Exact label triples: {stats['seed_comparison']['exact_triple_label_overlap_count']}; partial overlaps: {stats['seed_comparison']['partial_label_overlap_count']}; single/no overlap: {stats['seed_comparison']['single_or_no_label_overlap_count']}.",
            "- This is a label overlap report, not a semantic-equivalence decision.",
            "",
            "## Examples routed to review",
            "",
        ]
    )
    for lang in LANGUAGES:
        lines.append(f"### {lang}")
        for row in samples[lang]:
            refs = ", ".join(str(ref["line"]) for ref in row["source_refs"][:3])
            lines.append(f"- {row['normalized_term']} — {', '.join(row['reasons'])}; source line(s): {refs}.")
        if not samples[lang]:
            lines.append("- No configured examples matched the review rules.")
        lines.append("")
    lines.extend(
        [
            "## Validation and use limits",
            "",
            "- Converter checks every source row/ID is represented, JSONL outputs parse, canonical IDs are unique, source hashes are unchanged, and normalized terms have no duplicate output keys.",
            "- Automated rules cannot validate translations, medical correctness, ICD version/mapping, ontology hierarchy, or source license.",
            "- Do not load these candidates as production medical anchors or term dictionaries until review and separate test20k ablation are approved.",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def curate(output_dir: Path) -> dict[str, Any]:
    inputs = {
        **{f"base_{lang}": path for lang, path in BASE_FILES.items()},
        "aligned": ALIGNED_PATH,
        "sample": SAMPLE_PATH,
        "seed": SEED_PATH,
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing resource input(s): " + ", ".join(missing))
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing curation output: {output_dir}")
    source_hashes_before = {key: sha256(path) for key, path in inputs.items()}

    output_dir.mkdir(parents=True, exist_ok=False)
    stats: dict[str, Any] = {"base": {}}
    base_records: dict[str, list[dict[str, Any]]] = {}
    for lang, path in BASE_FILES.items():
        records, lang_stats = curate_base(lang, path)
        base_records[lang] = records
        stats["base"][lang] = lang_stats
        write_jsonl(output_dir / f"terms_{lang}.jsonl", records)

    concepts, id_map, stats["aligned"] = curate_aligned(ALIGNED_PATH)
    write_jsonl(output_dir / "concepts_candidates.jsonl", concepts)
    write_jsonl(output_dir / "concept_id_map.jsonl", id_map)

    sample, stats["sample"] = curate_sample(SAMPLE_PATH)
    write_jsonl(output_dir / "external_ids_review.jsonl", sample)

    seed_comparison, stats["seed_comparison"] = compare_seed(SEED_PATH, concepts)
    write_jsonl(output_dir / "seed_comparison.jsonl", seed_comparison)

    source_hashes_after = {key: sha256(path) for key, path in inputs.items()}
    if source_hashes_before != source_hashes_after:
        raise AssertionError("A source resource changed during curation")

    output_counts = {path.name: verify_jsonl(path) for path in sorted(output_dir.glob("*.jsonl"))}
    for lang in LANGUAGES:
        item = stats["base"][lang]
        if item["source_line_references_in_output"] != item["source_line_count"]:
            raise AssertionError(f"Lost source line references for {lang}")
        keys = [row["normalized_term"] for row in base_records[lang]]
        if len(keys) != len(set(keys)):
            raise AssertionError(f"Duplicate normalized term key in {lang}")
    if stats["aligned"]["id_map_count"] != stats["aligned"]["source_record_count"]:
        raise AssertionError("Aligned ID map cardinality mismatch")
    canonical_ids = [row["concept_id"] for row in concepts]
    if len(canonical_ids) != len(set(canonical_ids)):
        raise AssertionError("Canonical concept IDs are not unique")
    if len(sample) != stats["sample"]["source_record_count"]:
        raise AssertionError("Sample lexicon records were lost")
    if len(seed_comparison) != stats["seed_comparison"]["seed_concept_count"]:
        raise AssertionError("Seed comparison records were lost")

    samples: dict[str, list[dict[str, Any]]] = {}
    for lang in LANGUAGES:
        reviewed = [row for row in base_records[lang] if row["classification"] == "review"]
        by_term = {row["normalized_term"]: row for row in reviewed}
        samples[lang] = [by_term[term] for term in REPORT_REVIEW_EXAMPLES[lang] if term in by_term]
    create_report(output_dir, stats, samples)
    output_hashes = {
        path.name: sha256(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "schema_version": 1,
        "rule_version": RULE_VERSION,
        "normalization": {
            "unicode": "NFKC",
            "case": "lower",
            "whitespace": "collapse consecutive whitespace and strip edges",
            "unicode_diacritics_removed": False,
            "translation_or_spelling_rewrite": False,
        },
        "generated_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds"),
        "inputs": {
            key: {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "sha256": source_hashes_before[key],
                "bytes": path.stat().st_size,
                "source_license_status": "team_authored" if key == "seed" else "unknown_or_not_recorded",
            }
            for key, path in inputs.items()
        },
        "outputs": {"jsonl_record_counts": output_counts, "sha256": output_hashes},
        "statistics": stats,
        "safety": {
            "sources_modified": False,
            "integrated_into_bm25": False,
            "medical_semantics_verified": False,
            "licenses_verified": False,
            "for_valid_read": False,
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    manifest = curate(output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "statistics": manifest["statistics"],
                "output_counts": manifest["outputs"]["jsonl_record_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
