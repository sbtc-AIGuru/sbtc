#!/usr/bin/env python3
"""
curate_worker.py - Helper utilities for medical_curator subagents to record
and validate curated terms.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

WORKSPACE = Path(__file__).resolve().parents[4]
CHUNKS_DIR = WORKSPACE / "data_final" / "chunks_format_v3_final"
TARGET_DIR = WORKSPACE / "artifacts" / "retrieval" / "llm-curated-segmentation-20261016"
RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
TARGET_DIR.mkdir(parents=True, exist_ok=True)
RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

# Load base existing sets
VI_EXISTING = set()
with open(RESOURCES_DIR / "segmentation_vi.txt") as f:
    for line in f:
        t = unicodedata.normalize("NFKC", line.strip().lower())
        if t:
            VI_EXISTING.add(t)

ZH_EXISTING = set()
with open(RESOURCES_DIR / "segmentation_zh.txt") as f:
    for line in f:
        t = unicodedata.normalize("NFKC", line.strip().lower())
        if t:
            ZH_EXISTING.add(t)

VALID_CLASSES = {"[DIS]", "[DRUG]", "[SYM]", "[ANA]", "[PROC]"}

NEGATIVE_KEYWORDS_VI = [
    "nghiên cứu", "khảo sát", "đánh giá", "ghi nhận", "kết quả",
    "kèm theo", "tiền sử", "liên quan", "nguy cơ", "hiệu quả",
    "cho thấy", "phát hiện", "bác sĩ", "bệnh viện", "phòng khám",
    "thực hiện", "phương pháp", "tiến hành", "báo cáo", "theo dõi"
]

NEGATIVE_KEYWORDS_ZH = [
    "你好", "请问", "怎么回事", "不知道", "有啥问题", "怎么办",
    "医院", "专科医院", "门诊", "医生", "大夫", "专家",
    "调查", "研究", "分析", "结果", "建议", "注意", "可以", "发生"
]


def clean_term(term: str) -> str:
    t = unicodedata.normalize("NFKC", term.strip().lower())
    # Strip boundary punctuation
    t = re.sub(r"^[\s\"'.,:;()\[\]{}/*+-]+|[\s\"'.,:;()\[\]{}/*+-]+$", "", t).strip()
    return t


def is_valid_term(term: str, lang: str) -> bool:
    if not term or len(term) < 2:
        return False
    if lang == "vi":
        if term in VI_EXISTING:
            return False
        # Reject if exact match or simple noisy patterns
        if any(term == bad or term.startswith(bad + " ") or term.endswith(" " + bad) for bad in NEGATIVE_KEYWORDS_VI):
            return False
    elif lang == "zh":
        if term in ZH_EXISTING:
            return False
        if any(bad in term for bad in NEGATIVE_KEYWORDS_ZH):
            return False
    return True


def append_simple_terms(lang: str, terms: list[str]) -> int:
    """
    Appends a list of terms (curated directly by LLM) to the supplement dictionary.
    No long citations or provenance needed - keeps output clean and lean.
    """
    txt_path = TARGET_DIR / f"segmentation_{lang}_supplement.txt"
    res_path = RESOURCES_DIR / f"segmentation_{lang}_supplement.txt"

    seen = set()
    if txt_path.exists():
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                t = clean_term(line)
                if t:
                    seen.add(t)

    added = 0
    for raw in terms:
        t = clean_term(raw)
        if not is_valid_term(t, lang):
            continue
        if t in seen:
            continue
        seen.add(t)
        added += 1

    sorted_terms = sorted(list(seen))
    for p in (txt_path, res_path):
        with open(p, "w", encoding="utf-8") as f:
            for t in sorted_terms:
                f.write(t + "\n")

    print(f"[{lang.upper()}] Added {added} new terms. Total in supplement: {len(sorted_terms)} terms -> {txt_path.name}")
    return added


def append_curated_zh_records(records: list[dict]) -> int:
    """
    Appends curated Chinese records to curated_zh.jsonl and keeps
    artifacts/segmentation_zh_supplement.txt and resources/segmentation_zh_supplement.txt
    in 100% sync.
    """
    jsonl_path = TARGET_DIR / "curated_zh.jsonl"
    txt_path = TARGET_DIR / "segmentation_zh_supplement.txt"
    res_path = RESOURCES_DIR / "segmentation_zh_supplement.txt"

    existing_terms = set()
    existing_records = []
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                rec = json.loads(line_str)
                t = clean_term(rec["term"])
                if t and t not in existing_terms:
                    existing_terms.add(t)
                    rec["term"] = t
                    existing_records.append(rec)

    new_added = 0
    for rec in records:
        term = clean_term(rec.get("term", ""))
        cls = rec.get("class", "").strip() or rec.get("label", "").strip()
        if cls and not cls.startswith("[") and f"[{cls}]" in VALID_CLASSES:
            cls = f"[{cls}]"
        if not term or not is_valid_term(term, "zh"):
            continue
        if term in existing_terms:
            continue
        if cls not in VALID_CLASSES:
            continue
        clean_rec = {
            "term": term,
            "class": cls,
            "source_id": rec.get("source_id", rec.get("source", "part-001074.jsonl")),
            "context": rec.get("context", "")
        }
        existing_records.append(clean_rec)
        existing_terms.add(term)
        new_added += 1

    # Write jsonl
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in existing_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write sorted txt files
    sorted_terms = sorted(list(existing_terms))
    for p in (txt_path, res_path):
        with open(p, "w", encoding="utf-8") as f:
            for t in sorted_terms:
                f.write(t + "\n")

    assert len(sorted_terms) == len(existing_records), f"Mismatch: {len(sorted_terms)} terms vs {len(existing_records)} records"
    print(f"[ZH] Appended {new_added} new records. Total count: {len(sorted_terms)} terms (zero diff).")
    return new_added


def append_curated_vi_records(records: list[dict]) -> int:
    """
    Appends curated Vietnamese records to curated_vi.jsonl and keeps
    artifacts/segmentation_vi_supplement.txt and resources/segmentation_vi_supplement.txt
    in sync.
    """
    jsonl_path = TARGET_DIR / "curated_vi.jsonl"
    txt_path = TARGET_DIR / "segmentation_vi_supplement.txt"
    res_path = RESOURCES_DIR / "segmentation_vi_supplement.txt"

    # Load existing supplement terms
    supplement_terms = set()
    if txt_path.exists():
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                t = clean_term(line)
                if t:
                    supplement_terms.add(t)

    existing_jsonl_terms = set()
    existing_records = []
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                rec = json.loads(line_str)
                t = clean_term(rec["term"])
                if t and t not in existing_jsonl_terms:
                    existing_jsonl_terms.add(t)
                    existing_records.append(rec)

    new_added = 0
    for rec in records:
        term = clean_term(rec.get("term", ""))
        cls = rec.get("class", "").strip() or rec.get("label", "").strip()
        if cls and not cls.startswith("[") and f"[{cls}]" in VALID_CLASSES:
            cls = f"[{cls}]"
        if not term or not is_valid_term(term, "vi"):
            continue
        if term in supplement_terms or term in existing_jsonl_terms:
            continue
        if cls not in VALID_CLASSES:
            continue
        clean_rec = {
            "term": term,
            "class": cls,
            "source_id": rec.get("source_id", "part-000048.jsonl"),
            "context": rec.get("context", "")
        }
        existing_records.append(clean_rec)
        existing_jsonl_terms.add(term)
        supplement_terms.add(term)
        new_added += 1

    # Write jsonl
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in existing_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write sorted txt files
    sorted_terms = sorted(list(supplement_terms))
    for p in (txt_path, res_path):
        with open(p, "w", encoding="utf-8") as f:
            for t in sorted_terms:
                f.write(t + "\n")

    print(f"[VI] Appended {new_added} new records. Total in supplement: {len(sorted_terms)} terms -> {txt_path.name}")
    return new_added


def dump_part_batch(part_name: str, doc_offset: int = 0, num_docs: int = 15, max_chars_per_doc: int = 2000) -> str:
    """
    Reads a slice of documents from chunks_format_v3_final/{part_name}
    and formats their chunks for LLM reading.
    """
    part_path = CHUNKS_DIR / part_name
    if not part_path.exists():
        return f"Error: Part {part_name} not found in {CHUNKS_DIR}"

    output_lines = [f"=== READING {part_name} (doc_offset={doc_offset}, num_docs={num_docs}) ==="]
    count = 0
    with open(part_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx < doc_offset:
                continue
            if count >= num_docs:
                break
            try:
                doc = json.loads(line)
            except Exception:
                continue

            doc_id = doc.get("doc_id")
            url = doc.get("url", "")
            children = doc.get("children", [])
            output_lines.append(f"\n--- [DOC ID: {doc_id}] ({url}) ---")
            
            doc_chars = 0
            for c_idx, c in enumerate(children):
                txt = c.get("chunk_text", "").strip()
                if not txt:
                    continue
                output_lines.append(f"[Chunk {c_idx}]: {txt}")
                doc_chars += len(txt)
                if doc_chars >= max_chars_per_doc:
                    output_lines.append("[...remaining chunks in doc omitted for brevity...]")
                    break
            count += 1

    output_lines.append(f"\n=== END OF BATCH ({count} documents read from {part_name}) ===")
    return "\n".join(output_lines)


def get_part_doc_count(part_name: str) -> int:
    part_path = CHUNKS_DIR / part_name
    if not part_path.exists():
        return 0
    count = 0
    with open(part_path, "r", encoding="utf-8") as f:
        for _ in f:
            count += 1
    return count


if __name__ == "__main__":
    print(f"Curate worker ready. Loaded VI={len(VI_EXISTING)}, ZH={len(ZH_EXISTING)} existing terms.")
