"""Build an auditable, candidate-only VI/EN/ZH lexicon staging pack.

The script never writes to sbtc/Resources or to the analyzer runtime resources.
Input files are read from a pinned external cache and the local FHIR package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PARSER_VERSION = "1.5.0"
RUN_ID = "20261015-run-08"
TARGET_SYSTEMS = {
    "vn-drug-substance-cs": "vi_fhir_drug_substance",
    "vn-communicable-disease-cs": "vi_fhir_communicable_disease",
    "vn-yhct-disease-catalog-cs": "vi_fhir_yhct_disease_catalog",
    "vn-yhct-disease-cs": "vi_fhir_yhct_disease",
    "vn-yhct-examination-symptom-cs": "vi_fhir_yhct_examination_symptom",
    "vn-yhct-medicine-cs": "vi_fhir_yhct_medicine",
    "vn-yhct-symptom-cs": "vi_fhir_yhct_symptom",
    "vn-yhct-treatment-method-cs": "vi_fhir_yhct_treatment_method",
}
EXPECTED_PINS = {
    "vietbioner_commit": "19ba70a5947d1be72906d407c860b1666b9337e9",
    "vietent_revision": "8fc1aec4b3acd272cf50af39672efb27f2ea2e2d",
    "envimed_revision": "eb8e879b8cc968e73244896d87975ba2a2421963",
    "thuocl_commit": "a30ce79d895d01ab5132a5c74c29703ff7efb4cc",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_key(surface: str) -> str:
    value = unicodedata.normalize("NFKC", surface)
    return " ".join(value.casefold().split())


def quality_status(
    surface: str,
    source_id: str,
    reconstructed: bool = False,
    quality_hint: str | None = None,
) -> tuple[str, str | None]:
    stripped = surface.strip()
    if not stripped:
        return "rejected", "empty_surface"
    if quality_hint:
        return "review", quality_hint
    if len(stripped) > 100:
        return "review", "very_long_surface"
    if len(stripped.split()) > 8:
        return "review", "phrase_over_8_tokens"
    if re.search(r"[.!?。！？；;]$", stripped) and source_id in {
        "vi_envimedner_train",
        "vi_vietbioner_train",
    }:
        return "review", "sentence_punctuation_suffix"
    if source_id == "en_nlm_mesh_2026_descriptors" and "," in stripped:
        return "review", "comma_form_in_mesh_entry_requires_review"
    if re.search(r"[,;，；]", stripped):
        return "review", "list_or_multi_component_surface"
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|μg|g|kg|ml|mL|l|%|units?)\b", stripped, re.I):
        return "review", "dose_or_measurement_in_surface"
    if re.search(r"\[[A-Z]\d{1,3}(?:\.\d+)?\]", stripped):
        return "review", "embedded_classification_code"
    if reconstructed:
        return "review", "token_reconstructed_surface"
    if re.fullmatch(r"[\W_]+", stripped, flags=re.UNICODE):
        return "rejected", "punctuation_only"
    return "candidate", None


class CandidateBuilder:
    def __init__(self) -> None:
        self.groups: dict[tuple[str, str], dict[str, Any]] = {}
        self.source_stats: dict[str, Counter[str]] = defaultdict(Counter)
        self.source_language_stats: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self.rejections: list[dict[str, Any]] = []

    def add(
        self,
        *,
        source_id: str,
        language: str,
        surface: str,
        evidence: dict[str, Any],
        rights_status: str,
        reconstructed: bool = False,
        quality_hint: str | None = None,
    ) -> None:
        self.source_stats[source_id]["raw_surfaces"] += 1
        self.source_language_stats[source_id][language]["raw_surfaces"] += 1
        raw = surface
        surface = surface.strip()
        status, reason = quality_status(surface, source_id, reconstructed, quality_hint)
        if status == "rejected":
            self.source_stats[source_id]["rejected"] += 1
            self.source_stats[source_id][f"rejected:{reason}"] += 1
            self.source_language_stats[source_id][language]["rejected"] += 1
            self.source_language_stats[source_id][language][f"rejected:{reason}"] += 1
            self.rejections.append(
                {"source_id": source_id, "language": language, "surface": raw, "reason": reason, "evidence": evidence}
            )
            return
        if status == "review" and reason:
            self.source_stats[source_id][f"review_reason:{reason}"] += 1
            self.source_language_stats[source_id][language][f"review_reason:{reason}"] += 1
        key = normalized_key(surface)
        if not key:
            self.source_stats[source_id]["rejected"] += 1
            self.source_stats[source_id]["rejected:empty_normalized_key"] += 1
            return
        self.source_stats[source_id]["candidate_occurrences"] += 1
        self.source_stats[source_id][status] += 1
        self.source_language_stats[source_id][language]["candidate_occurrences"] += 1
        self.source_language_stats[source_id][language][status] += 1
        group_key = (language, key)
        group = self.groups.setdefault(
            group_key,
            {
                "language": language,
                "normalized_key": key,
                "surface": surface,
                "surface_variants": [],
                "source_ids": [],
                "source_refs": [],
                "occurrence_count": 0,
                "quality_status": "candidate",
                "quality_reasons": [],
                "rights_statuses": [],
                "loadable": False,
                "term_role": "segmentation_candidate",
            },
        )
        if surface not in group["surface_variants"]:
            group["surface_variants"].append(surface)
        if source_id not in group["source_ids"]:
            group["source_ids"].append(source_id)
        group["source_refs"].append(
            {
                "source_id": source_id,
                **evidence,
                "source_surface": raw,
                "quality_status": status,
                "quality_reason": reason,
            }
        )
        group["occurrence_count"] += 1
        if status == "review":
            group["quality_status"] = "review"
            if reason and reason not in group["quality_reasons"]:
                group["quality_reasons"].append(reason)
        if rights_status not in group["rights_statuses"]:
            group["rights_statuses"].append(rights_status)

    def rows(self, language: str | None = None) -> list[dict[str, Any]]:
        rows = [r for (lang, _), r in self.groups.items() if language is None or lang == language]
        for row in rows:
            row["surface_variants"].sort(key=lambda x: (normalized_key(x), x))
            row["source_ids"].sort()
            row["rights_statuses"].sort()
        return sorted(rows, key=lambda r: (r["language"], r["normalized_key"], r["surface"]))


def iter_fhir_concepts(concepts: list[dict[str, Any]], parent_path: tuple[str, ...] = ()):
    for concept in concepts:
        code = str(concept.get("code", ""))
        path = (*parent_path, code) if code else parent_path
        yield concept, path
        yield from iter_fhir_concepts(concept.get("concept", []) or [], path)


def parse_fhir(package_dir: Path, builder: CandidateBuilder) -> list[dict[str, Any]]:
    package_path = package_dir / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("name") != "hl7.fhir.vn.core" or package.get("version") != "0.10.0":
        raise ValueError(f"FHIR package pin mismatch: {package.get('name')} {package.get('version')}")
    results = []
    for filename, source_id in TARGET_SYSTEMS.items():
        path = package_dir / f"CodeSystem-{filename}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("id") != filename:
            raise ValueError(f"FHIR resource id mismatch in {path}")
        record_count = 0
        for concept, code_path in iter_fhir_concepts(data.get("concept", []) or []):
            record_count += 1
            properties = concept.get("property", []) or []
            not_selectable = any(
                p.get("code") == "notSelectable" and p.get("valueBoolean") is True for p in properties
            )
            code = str(concept.get("code", ""))
            base_evidence = {
                "resource_id": data.get("id"),
                "canonical": data.get("url"),
                "version": data.get("version"),
                "code": code,
                "code_path": list(code_path),
                "status": data.get("status"),
                "not_selectable": not_selectable,
                "file": path.name,
                "copyright": data.get("copyright"),
                "field": "concept.display",
            }
            display = concept.get("display")
            if display and not not_selectable:
                builder.add(
                    source_id=source_id,
                    language="vi",
                    surface=str(display),
                    evidence=base_evidence,
                    rights_status="source_copyright_review_required",
                )
            for designation in concept.get("designation", []) or []:
                lang = str(designation.get("language", "")).lower()
                value = designation.get("value")
                if not value or lang not in {"vi", "en"} or not_selectable:
                    continue
                evidence = {**base_evidence, "field": "concept.designation.value", "designation_language": lang}
                builder.add(
                    source_id=source_id,
                    language=lang,
                    surface=str(value),
                    evidence=evidence,
                    rights_status="source_copyright_review_required",
                )
        results.append(
            {
                "source_id": source_id,
                "artifact": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "source_records": record_count,
                "copyright": data.get("copyright"),
                "resource_status": data.get("status"),
                "license_status": "package_CC-BY-4.0_with_resource_copyright_review_required",
            }
        )
    return results


def parse_vietbioner(path: Path, builder: CandidateBuilder) -> dict[str, Any]:
    source_id = "vi_vietbioner_train"
    target = {"Symptom_and_Disease", "DiagnosticProcedure"}
    sentence_rows = 0
    malformed = 0
    label_counter: Counter[str] = Counter()
    sentence_tokens: list[tuple[str, str]] = []

    def emit_sentence() -> None:
        nonlocal sentence_rows
        if not sentence_tokens:
            return
        sentence_rows += 1
        i = 0
        while i < len(sentence_tokens):
            token, tag = sentence_tokens[i]
            entity_type = tag.removeprefix("I-").removeprefix("B-")
            if tag == "O" or entity_type not in target:
                i += 1
                continue
            group = [token]
            j = i + 1
            while j < len(sentence_tokens):
                next_token, next_tag = sentence_tokens[j]
                next_type = next_tag.removeprefix("I-").removeprefix("B-")
                if next_type != entity_type or next_tag == "O" or next_tag.startswith("B-"):
                    break
                group.append(next_token)
                j += 1
            surface = " ".join(group)
            builder.add(
                source_id=source_id,
                language="vi",
                surface=surface,
                evidence={
                    "split": "train",
                    "entity_type": entity_type,
                    "sentence_ordinal": sentence_rows,
                    "token_start": i,
                    "token_end": j,
                    "field": "CoNLL token sequence",
                    "surface_reconstructed_from_tokens": True,
                },
                rights_status="declared_CC-BY-4.0_source_text_context_review_required",
                reconstructed=True,
            )
            label_counter[entity_type] += 1
            i = j
        sentence_tokens.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            emit_sentence()
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            malformed += 1
            continue
        sentence_tokens.append((parts[0], parts[1]))
    emit_sentence()
    return {
        "source_id": source_id,
        "artifact": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "sentences": sentence_rows,
        "malformed_lines": malformed,
        "target_entity_mentions": dict(label_counter),
        "expected_target_mentions_from_card": {"Symptom_and_Disease": 838, "DiagnosticProcedure": 191},
        "license_status": "declared_CC-BY-4.0_source_text_context_review_required",
    }


def parse_envimed(train_dir: Path, builder: CandidateBuilder) -> dict[str, Any]:
    source_id = "vi_envimedner_train"
    files = sorted(train_dir.rglob("*.json"))
    records = 0
    spans = 0
    malformed = 0
    offset_mismatch = 0
    type_counts: Counter[str] = Counter()
    file_checksums: list[dict[str, Any]] = []
    for path in files:
        try:
            raw_bytes = path.read_bytes()
            file_checksums.append(
                {
                    "source_id": source_id,
                    "relative_path": str(path.relative_to(train_dir.parent.parent)),
                    "bytes": len(raw_bytes),
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                }
            )
            record = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            malformed += 1
            continue
        records += 1
        data = record.get("data", {}) or {}
        vi_text = data.get("vi_text", "")
        if not isinstance(vi_text, str):
            malformed += 1
            continue
        for annotation in record.get("annotations", []) or []:
            for result in annotation.get("result", []) or []:
                if result.get("from_name") != "vi_label" or result.get("to_name") != "vi_text":
                    continue
                value = result.get("value", {}) or {}
                start, end = value.get("start"), value.get("end")
                surface = value.get("text")
                labels = value.get("labels", []) or []
                if not isinstance(start, int) or not isinstance(end, int) or not isinstance(surface, str):
                    malformed += 1
                    continue
                if start < 0 or end < start or end > len(vi_text) or vi_text[start:end] != surface:
                    offset_mismatch += 1
                    continue
                spans += 1
                for label in labels:
                    type_counts[str(label)] += 1
                builder.add(
                    source_id=source_id,
                    language="vi",
                    surface=surface,
                    evidence={
                        "split": "train",
                        "sentence_file": str(path.relative_to(train_dir)),
                        "record_id": record.get("id"),
                        "annotation_id": result.get("id"),
                        "semantic_type_codes": [str(x) for x in labels],
                        "start": start,
                        "end": end,
                        "field": "data.vi_text/annotations[].result[].value.text",
                    },
                    rights_status="dataset_card_CC-BY-4.0_MedMentions_CC0_UMLS_type_codes_only",
                )
    return {
        "source_id": source_id,
        "revision": EXPECTED_PINS["envimed_revision"],
        "artifact": "train/**/*.json",
        "files": len(files),
        "records_read": records,
        "span_mentions": spans,
        "malformed_records_or_spans": malformed,
        "offset_mismatch": offset_mismatch,
        "semantic_type_counts": dict(sorted(type_counts.items())),
        "expected": {"train_files": 27013, "entity_mention_pairs": 122017},
        "license_status": "declared_CC-BY-4.0_with_MedMentions_CC0_and_UMLS_type_codes_only",
        "file_checksums": file_checksums,
    }


def parse_vietent(path: Path, builder: CandidateBuilder) -> dict[str, Any]:
    import pyarrow.parquet as pq

    source_id = "vi_vietent_catalogue"
    table = pq.read_table(path, columns=["term", "group"])
    raw = 0
    malformed = 0
    unique_terms: set[tuple[str, str]] = set()
    for term, group in zip(table.column("term").to_pylist(), table.column("group").to_pylist()):
        if term is None or group is None:
            malformed += 1
            continue
        raw += 1
        term, group = str(term), str(group)
        unique_terms.add((term, group))
    # The Parquet repeats catalogue terms once per generated sentence. Extract
    # each catalogue term/group pair once; do not let synthetic sentence
    # frequency become lexicon frequency or duplicate provenance.
    for term, group in sorted(unique_terms):
        builder.add(
            source_id=source_id,
            language="vi",
            surface=term,
            evidence={"field": "term", "group": group, "catalogue_only": True},
            rights_status="dataset_card_CC-BY-4.0",
        )
    return {
        "source_id": source_id,
        "revision": EXPECTED_PINS["vietent_revision"],
        "artifact": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "parquet_rows_scanned_for_catalogue_fields": raw,
        "malformed": malformed,
        "unique_term_group_pairs": len(unique_terms),
        "unique_terms": len({term for term, _ in unique_terms}),
        "expected_catalogue_terms": 235,
        "license_status": "dataset_card_CC-BY-4.0",
    }


def parse_thuocl(path: Path, builder: CandidateBuilder) -> dict[str, Any]:
    source_id = "zh_thuocl_medical"
    rows = 0
    malformed = 0
    df_min: int | None = None
    df_max: int | None = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            malformed += 1
            continue
        term, raw_df = parts
        try:
            df = int(raw_df)
        except ValueError:
            malformed += 1
            continue
        rows += 1
        df_min = df if df_min is None else min(df_min, df)
        df_max = df if df_max is None else max(df_max, df)
        builder.add(
            source_id=source_id,
            language="zh",
            surface=term,
            evidence={"field": "term", "source_df_audit_only": df, "line": line_no},
            rights_status="free_for_research_and_commercial_use_attribution_required",
        )
    return {
        "source_id": source_id,
        "commit": EXPECTED_PINS["thuocl_commit"],
        "artifact": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows_read": rows,
        "malformed": malformed,
        "df_min_audit_only": df_min,
        "df_max_audit_only": df_max,
        "expected_rows": 18749,
        "license_status": "README_allows_research_commercial_with_required_citation",
    }


def parse_mesh(path: Path, builder: CandidateBuilder) -> dict[str, Any]:
    source_id = "en_nlm_mesh_2026_descriptors"
    records = 0
    preferred = 0
    entry_terms = 0
    malformed = 0
    for _, record in ET.iterparse(path, events=("end",)):
        if record.tag != "DescriptorRecord":
            continue
        ui = record.findtext("DescriptorUI") or ""
        descriptor = record.findtext("DescriptorName/String") or ""
        tree_numbers = [x.text or "" for x in record.findall("./TreeNumberList/TreeNumber")]
        tree_roots = {x.strip()[:1] for x in tree_numbers if x.strip()}
        mesh_quality_hint = None if tree_roots.intersection({"A", "B", "C", "D", "E", "F", "G", "N"}) else "non_clinical_or_broad_mesh_tree"
        records += 1
        if descriptor:
            preferred += 1
            builder.add(
                source_id=source_id,
                language="en",
                surface=descriptor,
                evidence={"descriptor_ui": ui, "tree_numbers": tree_numbers, "term_relation": "preferred_descriptor_name", "field": "DescriptorName/String"},
                rights_status="NLM_terms_acknowledgement_and_currentness_notice_required",
                quality_hint=mesh_quality_hint,
            )
        seen: set[str] = set()
        for term in record.findall("./ConceptList/Concept/TermList/Term"):
            value = term.findtext("String") or ""
            if not value:
                malformed += 1
                continue
            if term.attrib.get("RecordPreferredTermYN") == "Y" or value == descriptor:
                continue
            if value in seen:
                continue
            seen.add(value)
            entry_terms += 1
            builder.add(
                source_id=source_id,
                language="en",
                surface=value,
                evidence={
                    "descriptor_ui": ui,
                    "tree_numbers": tree_numbers,
                    "term_relation": "mesh_entry_term",
                    "concept_preferred": term.attrib.get("ConceptPreferredTermYN"),
                    "lexical_tag": term.attrib.get("LexicalTag"),
                    "field": "ConceptList/Concept/TermList/Term/String",
                },
                rights_status="NLM_terms_acknowledgement_and_currentness_notice_required",
                quality_hint=mesh_quality_hint,
            )
        record.clear()
    return {
        "source_id": source_id,
        "production_year": 2026,
        "artifact": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "descriptor_records": records,
        "preferred_terms": preferred,
        "entry_terms": entry_terms,
        "malformed_terms": malformed,
        "license_status": "NLM_terms_conditions_acknowledgement_and_currentness_notice_required",
    }


def source_metadata(cache_dir: Path, fhir: list[dict[str, Any]], parser_counts: dict[str, Any]) -> dict[str, Any]:
    local_artifacts = {}
    for filename in [
        "vietbioner_train.txt",
        "vietent_train.parquet",
        "thuocl_medical.txt",
        "thuocl_README.md",
        "thuocl_LICENSE",
        "mesh_desc2026.xml",
        "envimed_README.md",
        "vietent_README.md",
        "vietbioner_README.md",
        "nlm_terms_and_conditions.html",
        "mesh_download_page.html",
        "pku_dataset_metadata.json",
        "mesh_http_metadata.json",
    ]:
        path = cache_dir / filename
        if path.exists():
            local_artifacts[filename] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return {
        "run_id": RUN_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION,
        "candidate_only": True,
        "production_resources_modified": False,
        "source_artifacts": local_artifacts,
        "fhir_package": {
            "path": "/home/tran-nhat-truong/Downloads/package",
            "package_json_sha256": sha256_file(Path("/home/tran-nhat-truong/Downloads/package/package.json")),
            "package": "hl7.fhir.vn.core",
            "version": "0.10.0",
            "license_declared": "CC-BY-4.0",
            "resources": fhir,
        },
        "source_results": parser_counts,
        "sources": [
            {
                "source_id": "vi_vn_core_fhir_0_10_0",
                "publisher": "Omi HealthTech; package contains resources citing Vietnamese Ministry of Health decisions",
                "canonical_url": "http://fhir.hl7.org.vn/core",
                "artifact": "hl7.fhir.vn.core package 0.10.0; 8 selected CodeSystem JSON files",
                "license_declared": "CC-BY-4.0 at package level",
                "attribution": "Omi HealthTech package attribution plus each CodeSystem copyright/source string; preserve all resource notices",
                "rights_status": "review_required_per_resource_source_copyright",
                "fields_used": ["concept.display", "concept.designation.value with explicit vi/en language"],
                "caveats": ["public draft", "package license does not independently resolve each cited source appendix"],
            },
            {
                "source_id": "vi_vietbioner_train",
                "publisher": "VietBioNER authors",
                "canonical_url": "https://github.com/ptpuyen1511/VietBioNER",
                "revision": EXPECTED_PINS["vietbioner_commit"],
                "artifact": "data_supervised_learning/train.txt",
                "license_declared": "CC BY 4.0 in repository README",
                "attribution": "Phan, Uyen; Nguyen, Phuong; Nguyen, Nhung. LREC 2022 VietBioNER paper.",
                "rights_status": "declared_CC_BY_4_0_source_context_review_required",
                "fields_used": ["train token/tag sequence; Symptom_and_Disease and DiagnosticProcedure only"],
                "caveats": ["biomedical grey literature focused on tuberculosis", "surface reconstructed from whitespace-separated tokens"],
            },
            {
                "source_id": "vi_envimedner_train",
                "publisher": "En-ViMedNER authors",
                "canonical_url": "https://huggingface.co/datasets/nhuvo/En-ViMedNER",
                "revision": EXPECTED_PINS["envimed_revision"],
                "artifact": "train/**/*.json only",
                "license_declared": "CC BY 4.0 dataset card; card states MedMentions source is CC0 and UMLS semantic type codes only are retained",
                "attribution": "Vo et al., En-ViMedNER: An English-Vietnamese Parallel Biomedical Corpus with UMLS Semantic Type Annotations, EMNLP 2026 (to appear per card).",
                "rights_status": "declared_CC_BY_4_0_with_upstream_notice_preserved",
                "fields_used": ["data.vi_text", "vi_label value.text/start/end/labels"],
                "caveats": ["silver-standard translated biomedical abstracts", "no dev/test or UMLS concept names/definitions/hierarchy used"],
            },
            {
                "source_id": "vi_vietent_catalogue",
                "publisher": "VietENT authors",
                "canonical_url": "https://huggingface.co/datasets/diepduclai/VietENT-Text",
                "revision": EXPECTED_PINS["vietent_revision"],
                "artifact": "data/train-00000-of-00001.parquet",
                "license_declared": "CC BY 4.0 dataset card",
                "attribution": "Diep Duc Lai, VietENT: a Vietnamese ENT clinical corpus for speech recognition (2026).",
                "rights_status": "declared_CC_BY_4_0",
                "fields_used": ["term", "group", "unique pair only"],
                "caveats": ["narrow ENT coverage", "20,908 rows repeat catalogue terms across generated sentences; sentence text is excluded"],
            },
            {
                "source_id": "en_nlm_mesh_2026_descriptors",
                "publisher": "U.S. National Library of Medicine",
                "canonical_url": "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml",
                "artifact": "MeSH 2026 production-year descriptor XML; English only",
                "retrieval_url": "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.gz",
                "retrieval_note": "HTTP Content-Encoding gzip was transparently decoded by requests; cached payload is the 312,952,703-byte XML representation. HEAD metadata: 16,812,612-byte transfer entity, ETag \"1008a44-658ddd3fe86cb\", last modified 2026-08-12.",
                "license_declared": "NLM Terms and Conditions (acknowledgement and currentness statement required; not labeled as CC license)",
                "attribution": "Courtesy of the U.S. National Library of Medicine; no endorsement implied.",
                "rights_status": "NLM_terms_conditions_notice_required",
                "terms_url": "https://www.nlm.nih.gov/databases/download/terms_and_conditions.html",
                "fields_used": ["DescriptorName/String", "ConceptList/Concept/TermList/Term/String"],
                "caveats": ["English descriptor/entry terms only", "non-current snapshots must be labeled as non-current if redistributed"],
            },
            {
                "source_id": "zh_thuocl_medical",
                "publisher": "THU Open Chinese Lexicon (THUNLP) contributors",
                "canonical_url": "https://github.com/thunlp/THUOCL",
                "revision": EXPECTED_PINS["thuocl_commit"],
                "artifact": "data/THUOCL_medical.txt",
                "license_declared": "README permits research and commercial use and requires citation; repository MIT file is not treated as sole data license",
                "attribution": "Han, Zhang, Ma, Tu, Guo, Liu, Sun. THUOCL: Tsinghua Open Chinese Lexicon. 2016.",
                "rights_status": "research_commercial_use_with_attribution_required",
                "fields_used": ["term", "DF retained for audit only"],
                "caveats": ["DF reflects older web/news/search corpora and is not used as Jieba frequency"],
            },
            {
                "source_id": "zh_pku_medical_segmentation_v1",
                "publisher": "Peking University Open Research Data Platform; Zhao Changyu and Wang Ruojia",
                "canonical_url": "https://doi.org/10.18170/DVN/SDM9GT",
                "artifact": "Dataverse file id 4667, 提交-词典数据.tab",
                "license_declared": "CC0 per official Dataverse API metadata",
                "attribution": "Zhao, Changyu; Wang, Ruojia (2018), Medical segmentation dictionary, version 1.0, DOI 10.18170/DVN/SDM9GT.",
                "rights_status": "CC0_confirmed_but_acquisition_failed",
                "metadata_url": "https://opendata.pku.edu.cn/api/datasets/:persistentId/?persistentId=doi:10.18170/DVN/SDM9GT",
                "download_url": "https://opendata.pku.edu.cn/api/access/datafile/4667",
                "caveats": ["expected 87,280 rows", "official download endpoint returned HTTP 500; no mirror substituted"],
            },
        ],
        "blocked_or_unavailable": [
            {
                "source_id": "zh_pku_medical_segmentation_v1",
                "canonical_url": "https://doi.org/10.18170/DVN/SDM9GT",
                "artifact": "提交-词典数据.tab (Dataverse file id 4667)",
                "license_metadata": "CC0",
                "expected_observations": 87280,
                "status": "acquisition_failed_http_500",
                "note": "Official metadata/API confirms file and CC0, but official file endpoint returned an internal server error. No mirror/substitute was used.",
            }
        ],
        "not_acquired_rights_gated": [
            {
                "source_id": "vi_snomed_ct_vn_supplement",
                "expected_labels_reported": 76066,
                "status": "not_acquired_rights_review_required",
                "reason": "No exact machine-readable artifact/reuse grant was pinned for this run.",
            },
            {
                "source_id": "vi_loinc_vn_2_78",
                "expected_designations_reported": 89470,
                "status": "not_acquired_rights_review_required",
                "reason": "LOINC terms/derivatives require source-specific attribution and reuse review; no artifact was pinned.",
            },
            {
                "source_id": "vi_icd10_vn_2026",
                "expected_labels_reported": 16052,
                "status": "not_acquired_rights_review_required",
                "reason": "The official lookup page is not a redistribution license or pinned bulk artifact; no UI scraping performed.",
            },
            {
                "source_id": "zh_cmesh",
                "status": "not_acquired_rights_unclear",
                "reason": "No machine-readable artifact with clear redistribution terms was confirmed.",
            },
            {
                "source_id": "vi_vietmedcss_meddict",
                "status": "not_acquired_rights_unclear",
                "reason": "Dataset card warns that the upstream Meddict terms have copyright restrictions; no term extraction performed.",
            },
        ],
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--fhir-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache = args.cache_dir

    builder = CandidateBuilder()
    fhir_results = parse_fhir(args.fhir_dir, builder)
    vb = parse_vietbioner(cache / "vietbioner_train.txt", builder)
    ve = parse_vietent(cache / "vietent_train.parquet", builder)
    thuocl = parse_thuocl(cache / "thuocl_medical.txt", builder)
    mesh_path = cache / "mesh_desc2026.xml"
    mesh = parse_mesh(mesh_path, builder)
    envimed_dir = cache / "envimed-repo" / "train"
    envimed = parse_envimed(envimed_dir, builder)
    envimed_file_checksums = envimed.pop("file_checksums")

    results = {
        "vietbioner": vb,
        "vietent": ve,
        "thuocl": thuocl,
        "mesh": mesh,
        "envimed": envimed,
        "fhir_sources": fhir_results,
    }
    source_counts = {}
    for source_id, stats in sorted(builder.source_stats.items()):
        source_counts[source_id] = dict(sorted(stats.items()))
    results["candidate_builder_counts"] = source_counts
    results["candidate_builder_counts_by_source_and_language"] = {
        source_id: {
            language: dict(sorted(counts.items()))
            for language, counts in sorted(languages.items())
        }
        for source_id, languages in sorted(builder.source_language_stats.items())
    }

    per_source_unique: dict[str, set[str]] = defaultdict(set)
    per_source_language_unique: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    cross_source_overlap = Counter()
    for row in builder.rows():
        for source_id in row["source_ids"]:
            per_source_unique[source_id].add(row["normalized_key"])
            per_source_language_unique[source_id][row["language"]].add(row["normalized_key"])
        if len(row["source_ids"]) > 1:
            cross_source_overlap[row["language"]] += 1
    results["per_source_unique_normalized_keys"] = {
        k: len(v) for k, v in sorted(per_source_unique.items())
    }
    results["per_source_language_unique_normalized_keys"] = {
        source_id: {language: len(keys) for language, keys in sorted(languages.items())}
        for source_id, languages in sorted(per_source_language_unique.items())
    }
    results["cross_source_overlap_keys_by_language"] = dict(sorted(cross_source_overlap.items()))

    checksum_path = args.output_dir / "input_file_checksums.jsonl"
    write_jsonl(checksum_path, envimed_file_checksums)

    language_counts = {}
    all_rows = builder.rows()
    for language in ("vi", "en", "zh"):
        rows = builder.rows(language)
        path = args.output_dir / f"candidates_{language}.jsonl"
        n = write_jsonl(path, rows)
        language_counts[language] = {
            "unique_normalized_keys": n,
            "candidate_quality": sum(r["quality_status"] == "candidate" for r in rows),
            "review_quality": sum(r["quality_status"] == "review" for r in rows),
            "loadable": sum(bool(r["loadable"]) for r in rows),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    # Deterministic, stratified hash-ranked sample. Hashing rather than taking
    # the first lexical rows avoids systematic alphabetic sampling bias.
    review_buckets: dict[tuple[str, str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for row in all_rows:
        for source_id in row["source_ids"]:
            bucket = (row["language"], source_id, row["quality_status"])
            rank = hashlib.sha256((source_id + "\0" + row["language"] + "\0" + row["normalized_key"]).encode("utf-8")).hexdigest()
            review_buckets[bucket].append((rank, row))
    samples = []
    for key in sorted(review_buckets):
        samples.extend(row for _, row in sorted(review_buckets[key], key=lambda pair: pair[0])[:25])
    # De-duplicate review rows appearing in multiple source buckets.
    sample_map = {(r["language"], r["normalized_key"]): r for r in samples}
    sample_path = args.output_dir / "review_sample.jsonl"
    write_jsonl(sample_path, [sample_map[k] for k in sorted(sample_map)])

    rejected_path = args.output_dir / "rejected.jsonl"
    write_jsonl(rejected_path, builder.rejections)

    manifest = source_metadata(cache, fhir_results, results)
    manifest["source_results"]["envimed"]["file_checksum_count"] = len(envimed_file_checksums)
    manifest["source_results"]["envimed"]["file_checksum_manifest"] = {
        "file": checksum_path.name,
        "sha256": sha256_file(checksum_path),
        "bytes": checksum_path.stat().st_size,
    }
    manifest["language_counts"] = language_counts
    manifest["source_counts"] = source_counts
    manifest_path = args.output_dir / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    catalog = [
        "# Source catalog — medical lexicon staging",
        "",
        f"Run: `{RUN_ID}` · Parser: `{PARSER_VERSION}` · Candidate-only staging.",
        "",
        "Use this run as the canonical staging output; earlier run directories are intermediate and must not be used for counts or integration.",
        "",
        "| Source / publisher | Language | Exact artifact and pin | Parsed scope/count | License or reuse condition |",
        "|---|---|---|---:|---|",
    ]
    catalog.extend([
        f"| VN Core FHIR 0.10.0 — `{r['source_id']}` ([source](http://fhir.hl7.org.vn/core)) | VI/EN designation | `{Path(r['artifact']).name}`; SHA-256 `{r['sha256']}` | {r['source_records']} concepts | Package CC-BY-4.0 declared; resource copyright shown in manifest, rights review required |"
        for r in fhir_results
    ])
    catalog.extend([
        f"| VietBioNER authors ([repository](https://github.com/ptpuyen1511/VietBioNER)) | VI | `data_supervised_learning/train.txt` @ `{EXPECTED_PINS['vietbioner_commit']}`; SHA-256 `{vb['sha256']}` | {vb['sentences']} sentences; 838 disease/symptom + 191 procedure mentions | README declares CC BY 4.0; attribution required; reconstructed spans remain review-only |",
        f"| En-ViMedNER authors ([dataset card](https://huggingface.co/datasets/nhuvo/En-ViMedNER)) | VI | `train/**/*.json` @ `{EXPECTED_PINS['envimed_revision']}`; {envimed['files']} files; checksum list in `input_file_checksums.jsonl` | {envimed['span_mentions']} VI mentions; {len(per_source_unique['vi_envimedner_train']):,} normalized unique | Card declares CC BY 4.0; states MedMentions source CC0; retains UMLS type codes only; attribution required |",
        f"| VietENT authors ([dataset card](https://huggingface.co/datasets/diepduclai/VietENT-Text)) | VI | `data/train-00000-of-00001.parquet` @ `{EXPECTED_PINS['vietent_revision']}`; SHA-256 `{ve['sha256']}` | {ve['parquet_rows_scanned_for_catalogue_fields']:,} rows scanned; {ve['unique_terms']} unique catalogue terms | Dataset card declares CC BY 4.0; cite authors; generated sentence text excluded |",
        f"| U.S. National Library of Medicine ([MeSH 2026 XML](https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml)) | EN | `desc2026.xml`; SHA-256 `{mesh['sha256']}` | {mesh['preferred_terms']:,} preferred + {mesh['entry_terms']:,} entry terms | NLM Terms and Conditions: say “Courtesy of the U.S. National Library of Medicine”; no endorsement; label non-current snapshots |",
        f"| THUOCL contributors ([repository/data](https://github.com/thunlp/THUOCL/tree/{EXPECTED_PINS['thuocl_commit']}/data)) | ZH | `data/THUOCL_medical.txt` @ `{EXPECTED_PINS['thuocl_commit']}`; SHA-256 `{thuocl['sha256']}` | {thuocl['rows_read']:,} term/DF rows; DF audit-only | README permits research/commercial use and requires citation; repo MIT is not treated as sole data license |",
        "| Zhao, Changyu; Wang Ruojia ([PKU DOI](https://doi.org/10.18170/DVN/SDM9GT)) | ZH | Dataverse file 4667 `提交-词典数据.tab`; expected MD5 `58e61aa91c749394aeda3346a622809b` | 87,280 expected; not downloaded | Official metadata says CC0; official download endpoint returned HTTP 500; no mirror used |",
        "",
        "## Required citations and notices",
        "",
        "- VietBioNER: Phan, Uyen; Nguyen, Phuong; Nguyen, Nhung. “A Named Entity Recognition Corpus for Vietnamese Biomedical Texts to Support Tuberculosis Treatment.” LREC 2022.",
        "- En-ViMedNER: Vo et al. “En-ViMedNER: An English-Vietnamese Parallel Biomedical Corpus with UMLS Semantic Type Annotations.” EMNLP 2026 (dataset card says to appear).",
        "- VietENT: Diep Duc Lai. “VietENT: a Vietnamese ENT clinical corpus for speech recognition.” 2026.",
        "- THUOCL: Han, Zhang, Ma, Tu, Guo, Liu, Sun. “THUOCL: Tsinghua Open Chinese Lexicon.” 2016.",
        "- MeSH: use the exact NLM acknowledgement and currentness wording recorded in `source_manifest.json`; do not imply NLM endorsement.",
        "",
        "Rights statements are upstream declarations, not legal advice. Every term remains non-loadable until rights and linguistic review are signed off.",
        "",
        "Not acquired in this run: SNOMED CT VN, LOINC VN and ICD-10 VN 2026 (artifact/reuse rights gate); CMeSH and VietMedCSS Meddict (machine-readable redistribution rights unclear). Details are in `source_manifest.json`.",
    ])
    (args.output_dir / "SOURCE_CATALOG.md").write_text("\n".join(catalog) + "\n", encoding="utf-8")

    report = [
        "# Medical lexicon source staging report",
        "",
        f"Run: `{RUN_ID}`; generated `{manifest['created_at_utc']}`; parser `{PARSER_VERSION}`.",
        "",
        "## Decision",
        "",
        "This is an auditable candidate pack only. `loadable=0` for all three languages: legal/source review and linguistic review have not been completed, and production Resources/runtime were not changed.",
        "",
        "## Counts by language",
        "",
        "| Language | Unique normalized keys | Candidate quality | Review quality | Loadable | Bytes | SHA-256 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for lang, c in language_counts.items():
        report.append(f"| {lang} | {c['unique_normalized_keys']} | {c['candidate_quality']} | {c['review_quality']} | {c['loadable']} | {c['bytes']} | `{c['sha256']}` |")
    report.extend(["", "## Per-source parse audit", "", "```json", json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True), "```", "", "## Output artifacts", ""])
    for name in ["candidates_vi.jsonl", "candidates_en.jsonl", "candidates_zh.jsonl", "review_sample.jsonl", "rejected.jsonl", "input_file_checksums.jsonl"]:
        p = args.output_dir / name
        report.append(f"- `{name}` — {p.stat().st_size} bytes, SHA-256 `{sha256_file(p)}`")
    report.extend([
        "",
        "## Scope and limitations",
        "",
        "- En-ViMedNER: only `train/` was checked out and parsed; no dev/test data was fetched. Each VI span was checked against `vi_text[start:end]`.",
        "- VietBioNER: only supervised `train.txt`; target labels only. Mentions were reconstructed by joining CoNLL tokens and therefore remain review-status.",
        "- VietENT-Text: only the `term` and `group` columns were read; synthetic sentence text was not used.",
        "- THUOCL DF was retained only as provenance/audit metadata, not as Jieba frequency.",
        "- MeSH: production-year 2026 English descriptor and entry terms; headings outside the selected clinical tree roots A-G/N are retained with review status; each occurrence records the review reason and MeSH tree numbers; NLM acknowledgement and currentness notice remain required.",
        "- Automatic review flags include token-reconstructed spans, long phrases, lists/recipes, dosage/measurements, embedded classification codes, comma-containing MeSH forms, and broad/non-clinical MeSH tree roots; these are retained rather than silently discarded.",
        "- MeSH comma-form review is intentionally conservative: a comma may be a standard inverted entry term (for example, 'Pain, Abdominal'), not a multi-item list. It is flagged for a MeSH-aware normalization decision, not rejected as bad data.",
        "- PKU: source license metadata confirms CC0 and the expected file, but the official download endpoint returned HTTP 500. No alternate copy was substituted.",
        "- VN Core FHIR: package is declared CC-BY-4.0, but resource-level ministry source/copyright notices are preserved and rights status stays under review.",
        "- No BM25 retrieval benchmark or `test.jsonl` benchmark was run; this stage only validates source parsing and counts.",
        "- The review sample is a deterministic hash-ranked stratified sample of at most 25 normalized keys per source/language/quality bucket; it is not a random sample of the whole source population.",
        "",
    ])
    report_path = args.output_dir / "REPORT.md"
    report_path.write_text("\n".join(report), encoding="utf-8")

    # Write a complete output manifest after all generated files are closed.
    output_hashes = {}
    for path in sorted(args.output_dir.iterdir()):
        if path.is_file() and path.name != "source_manifest.json":
            output_hashes[path.name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    manifest["output_artifacts"] = output_hashes
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"output_dir": str(args.output_dir), "language_counts": language_counts, "sources": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
