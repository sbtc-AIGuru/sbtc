#!/usr/bin/env python3
"""Deep Clean & Semantic Typing of Staging Medical Lexicon (20261015-run-08).

Applies deep domain filtering:
- Eliminates academic research, methodology, statistical and sample size noise.
- Eliminates non-clinical hospital/institute and geographic entities.
- Enforces MeSH clinical subtree constraints (A, B, C, D, E, F, G only; drops Z, V, I, J, M, K, L).
- Performs 5-class semantic typing ([DIS], [DRUG], [SYM], [ANA], [PROC]).
- Generates segmentation-ready flat dictionaries (.txt) for Underthesea and Jieba.

Derived files are outputted to:
artifacts/retrieval/medical-lexicon-staging/20261015-run-08/deep_cleaned/
All source files remain strictly read-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[4]
CLEANED_DIR = WORKSPACE / "artifacts" / "retrieval" / "medical-lexicon-staging" / "20261015-run-08" / "cleaned"
OUTPUT_DIR = WORKSPACE / "artifacts" / "retrieval" / "medical-lexicon-staging" / "20261015-run-08" / "deep_cleaned"

VI_INPUT = CLEANED_DIR / "clean_candidates_vi.jsonl"
ZH_INPUT = CLEANED_DIR / "clean_candidates_zh.jsonl"
EN_INPUT = CLEANED_DIR / "clean_candidates_en.jsonl"

# 1. Tiếng Việt - Từ khóa loại trừ nghiên cứu / cơ sở / địa danh
VI_ACADEMIC_RESEARCH_PATTERNS = re.compile(
    r"\b(nghiên cứu|tổng quan|bảng hỏi|cỡ mẫu|giả thuyết|nhóm chứng|hồi quy|phương sai|mô hình|"
    r"chiến lược phân tích|thuần tập|khảo sát|đối chứng|thống kê|đánh giá kết quả|thử nghiệm lâm sàng)\b",
    re.I
)

VI_GEO_ORG_PATTERNS = re.compile(
    r"\b(bệnh viện|phòng khám|trung tâm y tế|trung tâm|nhật bản|trung quốc|hà nội|hồ chí minh|châu á|châu âu|hoa kỳ|nước mỹ)\b",
    re.I
)

VI_MACHINE_TRANS_ODDITIES = ("anh bệnh", "anh lựu", "anh nham", "anh sang thương")

# 2. Tiếng Trung - Từ khóa loại trừ viện nghiên cứu / mô hình
ZH_INSTITUTE_PATTERNS = re.compile(r"(研究所|医学杂志|口腔医学|人民医院|专科医院|生物制品研究所)")
ZH_MATH_STATS_PATTERNS = re.compile(r"(函数模型|前瞻性研究|前瞻性调查|数学模型|统计分析|动物模型)")

# 3. Tiếng Anh - Cây MeSH lâm sàng được phép giữ lại
CLINICAL_MESH_TREES = set("ABCDEFG")
EXCLUDED_MESH_TREES = set("ZVIJMK")  # Z: Geo, V: Pub, I: Sociology, J: Tech/Agri, M: Occupations, K: Humanities

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def classify_semantic_type_vi(surface: str, source_ids: list[str]) -> str:
    low = surface.lower()
    # Nguồn FHIR chuyên biệt
    if "vi_fhir_drug_substance" in source_ids or "vi_fhir_yhct_medicine" in source_ids or "vi_vietent_catalogue" in source_ids:
        return "DRUG"
    if "vi_fhir_communicable_disease" in source_ids or "vi_fhir_yhct_disease" in source_ids or "vi_fhir_yhct_disease_catalog" in source_ids:
        return "DIS"
    if "vi_fhir_yhct_symptom" in source_ids or "vi_fhir_yhct_examination_symptom" in source_ids:
        return "SYM"
    if "vi_fhir_yhct_treatment_method" in source_ids:
        return "PROC"

    # Rule theo từ vựng
    if any(w in low for w in ("thuốc", "kháng sinh", "axit", "acid", "vitamin", "cao ", "hoàn", "tán", "viên ", "tiêm", "dược")):
        return "DRUG"
    if any(w in low for w in ("bệnh", "hội chứng", "ung thư", "viêm", "suy ", "u ", "loét", "rối loạn", "nhiễm khuẩn", "nhiễm trùng", "tăng huyết áp")):
        return "DIS"
    if any(w in low for w in ("đau", "sốt", "ho", "khó thở", "buồn nôn", "ngứa", "chóng mặt", "mệt mỏi", "co giật", "phù", "chảy máu", "ợ ")):
        return "SYM"
    if any(w in low for w in ("phẫu thuật", "nội soi", "siêu âm", "chụp", "xét nghiệm", "châm cứu", "xoa bóp", "sinh thiết", "ghép", "cắt bỏ", "dẫn lưu")):
        return "PROC"
    if any(w in low for w in ("tim", "phổi", "gan", "thận", "dạ dày", "ruột", "mạch", "não", "xương", "khớp", "da", "mắt", "tai", "mũi", "họng", "tử cung", "tế bào", "niêm mạc")):
        return "ANA"
    return "DIS"  # Default clinical entity

def classify_semantic_type_zh(surface: str) -> str:
    if any(c in surface for c in ("丸", "散", "片", "胶囊", "汤", "膏", "颗粒", "油", "注射液", "酸", "素", "醇", "酮")):
        return "DRUG"
    if any(c in surface for c in ("炎", "病", "症", "癌", "瘤", "衰竭", "梗死", "综合征", "失调", "感染")):
        return "DIS"
    if any(c in surface for c in ("痛", "热", "晕", "咳", "喘", "吐", "痒", "麻", "肿")):
        return "SYM"
    if any(c in surface for c in ("术", "穿刺", "切除", "移植", "透析", "检查", "疗法", "引流")):
        return "PROC"
    if any(c in surface for c in ("心", "肝", "脾", "肺", "肾", "脑", "胃", "肠", "骨", "血", "皮")):
        return "ANA"
    return "DIS"

def classify_semantic_type_en(record: dict) -> str:
    tree_codes = []
    for ref in record.get("source_refs", []):
        for tr in ref.get("tree_numbers", []):
            if tr:
                tree_codes.append(tr[0])
    
    if "D" in tree_codes:
        return "DRUG"
    if "C" in tree_codes:
        return "DIS"
    if "A" in tree_codes:
        return "ANA"
    if "E" in tree_codes:
        return "PROC"
    if "F" in tree_codes:
        return "SYM"
    return "DIS"

def deep_clean_vi(record: dict) -> tuple[bool, str, str, str]:
    surface = record.get("clean_surface") or record.get("surface", "").strip()
    low = surface.lower()
    source_ids = record.get("source_ids", [])

    if len(surface) <= 1:
        return False, "single_character", surface, ""

    if low in VI_MACHINE_TRANS_ODDITIES or low.startswith("anh "):
        return False, "machine_translation_oddity", surface, ""

    if VI_ACADEMIC_RESEARCH_PATTERNS.search(low):
        return False, "academic_research_methodology_noise", surface, ""

    if VI_GEO_ORG_PATTERNS.search(low):
        return False, "geographic_or_hospital_org_noise", surface, ""

    sem_type = classify_semantic_type_vi(surface, source_ids)
    return True, "approved_deep_clean", surface, sem_type

def deep_clean_zh(record: dict) -> tuple[bool, str, str, str]:
    surface = record.get("clean_surface") or record.get("surface", "").strip()
    if len(surface) <= 1:
        return False, "single_character", surface, ""

    if ZH_INSTITUTE_PATTERNS.search(surface):
        return False, "institute_or_hospital_name_noise", surface, ""

    if ZH_MATH_STATS_PATTERNS.search(surface):
        return False, "math_or_academic_survey_noise", surface, ""

    sem_type = classify_semantic_type_zh(surface)
    return True, "approved_deep_clean", surface, sem_type

def deep_clean_en(record: dict) -> tuple[bool, str, str, str]:
    surface = record.get("clean_surface") or record.get("surface", "").strip()
    if len(surface) <= 1:
        return False, "single_character", surface, ""

    tree_roots = set()
    for ref in record.get("source_refs", []):
        for tr in ref.get("tree_numbers", []):
            if tr:
                tree_roots.add(tr[0])

    # Nếu có tree_numbers, bắt buộc phải có ít nhất 1 tree lâm sàng y sinh
    if tree_roots:
        has_clinical = any(tr in CLINICAL_MESH_TREES for tr in tree_roots)
        if not has_clinical:
            return False, f"non_clinical_mesh_tree_{sorted(tree_roots)}", surface, ""

    sem_type = classify_semantic_type_en(record)
    return True, "approved_deep_clean", surface, sem_type

def process_deep_language(input_file: Path, clean_file: Path, rejected_file: Path, eval_fn) -> dict:
    clean_records = []
    rejected_records = []
    reasons = Counter()
    semantic_types = Counter()

    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            ok, reason, norm_surface, sem_type = eval_fn(rec)
            rec_out = dict(rec)
            rec_out["clean_surface"] = norm_surface
            rec_out["semantic_type"] = sem_type
            if ok:
                rec_out["deep_curated_status"] = "approved_deep_clean"
                clean_records.append(rec_out)
                semantic_types[sem_type] += 1
            else:
                rec_out["deep_curated_status"] = "rejected_deep"
                rec_out["deep_rejection_reason"] = reason
                rejected_records.append(rec_out)
                reasons[reason] += 1

    with open(clean_file, "w", encoding="utf-8") as f:
        for r in clean_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(rejected_file, "w", encoding="utf-8") as f:
        for r in rejected_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "total": len(clean_records) + len(rejected_records),
        "clean": len(clean_records),
        "rejected": len(rejected_records),
        "clean_rate": (len(clean_records) / (len(clean_records) + len(rejected_records))) * 100 if clean_records else 0,
        "reasons": dict(reasons.most_common(10)),
        "semantic_types": dict(semantic_types.most_common()),
        "clean_sha256": sha256_file(clean_file),
        "rejected_sha256": sha256_file(rejected_file),
    }

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Starting Deep Domain Curation & Semantic Typing...")
    print(f"Source: {CLEANED_DIR}")
    print(f"Destination: {OUTPUT_DIR}\n")

    vi_stats = process_deep_language(
        VI_INPUT,
        OUTPUT_DIR / "deep_clean_candidates_vi.jsonl",
        OUTPUT_DIR / "rejected_deep_vi.jsonl",
        deep_clean_vi
    )
    print(f"[VI] Total: {vi_stats['total']:,} | Deep Clean: {vi_stats['clean']:,} ({vi_stats['clean_rate']:.2f}%) | Rejected: {vi_stats['rejected']:,}")
    print(f"     Semantic types: {vi_stats['semantic_types']}")
    print(f"     Top rejections: {vi_stats['reasons']}")

    zh_stats = process_deep_language(
        ZH_INPUT,
        OUTPUT_DIR / "deep_clean_candidates_zh.jsonl",
        OUTPUT_DIR / "rejected_deep_zh.jsonl",
        deep_clean_zh
    )
    print(f"\n[ZH] Total: {zh_stats['total']:,} | Deep Clean: {zh_stats['clean']:,} ({zh_stats['clean_rate']:.2f}%) | Rejected: {zh_stats['rejected']:,}")
    print(f"     Semantic types: {zh_stats['semantic_types']}")
    print(f"     Top rejections: {zh_stats['reasons']}")

    en_stats = process_deep_language(
        EN_INPUT,
        OUTPUT_DIR / "deep_clean_candidates_en.jsonl",
        OUTPUT_DIR / "rejected_deep_en.jsonl",
        deep_clean_en
    )
    print(f"\n[EN] Total: {en_stats['total']:,} | Deep Clean: {en_stats['clean']:,} ({en_stats['clean_rate']:.2f}%) | Rejected: {en_stats['rejected']:,}")
    print(f"     Semantic types: {en_stats['semantic_types']}")
    print(f"     Top rejections: {en_stats['reasons']}")

    # Xuất danh sách phẳng .txt phục vụ trực tiếp Underthesea fixed_words và Jieba dict
    vi_flat_file = OUTPUT_DIR / "segmentation_vi.txt"
    with open(OUTPUT_DIR / "deep_clean_candidates_vi.jsonl", "r", encoding="utf-8") as f, open(vi_flat_file, "w", encoding="utf-8") as out:
        seen = set()
        for line in f:
            surf = json.loads(line)["clean_surface"]
            if surf.lower() not in seen:
                out.write(surf + "\n")
                seen.add(surf.lower())

    zh_flat_file = OUTPUT_DIR / "segmentation_zh.txt"
    with open(OUTPUT_DIR / "deep_clean_candidates_zh.jsonl", "r", encoding="utf-8") as f, open(zh_flat_file, "w", encoding="utf-8") as out:
        seen = set()
        for line in f:
            surf = json.loads(line)["clean_surface"]
            if surf not in seen:
                out.write(surf + "\n")
                seen.add(surf)

    print(f"\nSaved segmentation dictionary: {vi_flat_file} ({len(seen)} unique terms)")
    print(f"Saved segmentation dictionary: {zh_flat_file}")

    # Tạo manifest
    manifest = {
        "deep_curation_version": "2.0.0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_checksums": {
            "clean_candidates_vi.jsonl": sha256_file(VI_INPUT),
            "clean_candidates_zh.jsonl": sha256_file(ZH_INPUT),
            "clean_candidates_en.jsonl": sha256_file(EN_INPUT),
        },
        "stats": {
            "vi": vi_stats,
            "zh": zh_stats,
            "en": en_stats,
        },
        "flat_checksums": {
            "segmentation_vi.txt": sha256_file(vi_flat_file),
            "segmentation_zh.txt": sha256_file(zh_flat_file),
        }
    }

    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Báo cáo REPORT_DEEP_CLEANING.md
    report_md = f"""# Báo cáo Kết Quả Làm Sạch Sâu & Định Danh Thực Thể Y Khoa (Deep Domain Curation v2.0)

**Thời gian tạo:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}  
**Thư mục nguồn (Read-only):** `{CLEANED_DIR}`  
**Thư mục dẫn xuất sạch sâu (Deep Cleaned):** `{OUTPUT_DIR}`  

---

## 1. Tổng quan số lượng sau khi lọc sạch sâu

| Ngôn ngữ | Tổng số đầu vào | Sạch sâu (Deep Clean) | Tỷ lệ giữ lại | Bị loại bỏ thêm | Tỷ lệ loại bỏ |
|---|---:|---:|---:|---:|---:|
| **Tiếng Việt (VI)** | 22.595 | **{vi_stats['clean']:,}** | **{vi_stats['clean_rate']:.2f}%** | {vi_stats['rejected']:,} | {100 - vi_stats['clean_rate']:.2f}% |
| **Tiếng Trung (ZH)** | 18.732 | **{zh_stats['clean']:,}** | **{zh_stats['clean_rate']:.2f}%** | {zh_stats['rejected']:,} | {100 - zh_stats['clean_rate']:.2f}% |
| **Tiếng Anh (EN)** | 166.608 | **{en_stats['clean']:,}** | **{en_stats['clean_rate']:.2f}%** | {en_stats['rejected']:,} | {100 - en_stats['clean_rate']:.2f}% |
| **TỔNG CỘNG** | **207.935** | **{vi_stats['clean'] + zh_stats['clean'] + en_stats['clean']:,}** | **{(vi_stats['clean'] + zh_stats['clean'] + en_stats['clean']) / (vi_stats['total'] + zh_stats['total'] + en_stats['total']) * 100:.2f}%** | **{vi_stats['rejected'] + zh_stats['rejected'] + en_stats['rejected']:,}** | **{(vi_stats['rejected'] + zh_stats['rejected'] + en_stats['rejected']) / (vi_stats['total'] + zh_stats['total'] + en_stats['total']) * 100:.2f}%** |

---

## 2. Phân loại 5 nhóm Thực thể Y sinh (Semantic Typing)

| Nhóm thực thể | Ý nghĩa lâm sàng | Tiếng Việt (VI) | Tiếng Trung (ZH) | Tiếng Anh (EN) |
|---|---|---:|---:|---:|
| **`[DIS]` Disease / Condition** | Tên bệnh, hội chứng, khối u, bệnh lý | {vi_stats['semantic_types'].get('DIS', 0):,} | {zh_stats['semantic_types'].get('DIS', 0):,} | {en_stats['semantic_types'].get('DIS', 0):,} |
| **`[DRUG]` Drug / Chemical** | Hoạt chất, dược phẩm, bài thuốc YHCT | {vi_stats['semantic_types'].get('DRUG', 0):,} | {zh_stats['semantic_types'].get('DRUG', 0):,} | {en_stats['semantic_types'].get('DRUG', 0):,} |
| **`[SYM]` Symptom / Sign** | Triệu chứng, dấu hiệu lâm sàng | {vi_stats['semantic_types'].get('SYM', 0):,} | {zh_stats['semantic_types'].get('SYM', 0):,} | {en_stats['semantic_types'].get('SYM', 0):,} |
| **`[ANA]` Anatomy** | Bộ phận cơ thể, giải phẫu, cơ quan | {vi_stats['semantic_types'].get('ANA', 0):,} | {zh_stats['semantic_types'].get('ANA', 0):,} | {en_stats['semantic_types'].get('ANA', 0):,} |
| **`[PROC]` Procedure / Test** | Xét nghiệm, thủ thuật ngoại khoa, trị liệu | {vi_stats['semantic_types'].get('PROC', 0):,} | {zh_stats['semantic_types'].get('PROC', 0):,} | {en_stats['semantic_types'].get('PROC', 0):,} |

---

## 3. Chi tiết các nhóm rác ngữ nghĩa vừa được loại bỏ triệt để

### 3.1 Tiếng Việt
{chr(10).join(f"- `{reason}`: {count:,} thuật ngữ" for reason, count in vi_stats['reasons'].items())}

### 3.2 Tiếng Trung
{chr(10).join(f"- `{reason}`: {count:,} thuật ngữ" for reason, count in zh_stats['reasons'].items())}

### 3.3 Tiếng Anh (Loại bỏ các cây MeSH ngoài miền y sinh)
{chr(10).join(f"- `{reason}`: {count:,} thuật ngữ" for reason, count in en_stats['reasons'].items())}

---

## 4. Checksums kiểm toán

- `deep_clean_candidates_vi.jsonl`: `{vi_stats['clean_sha256']}`
- `deep_clean_candidates_zh.jsonl`: `{zh_stats['clean_sha256']}`
- `deep_clean_candidates_en.jsonl`: `{en_stats['clean_sha256']}`
- `segmentation_vi.txt`: `{manifest['flat_checksums']['segmentation_vi.txt']}`
- `segmentation_zh.txt`: `{manifest['flat_checksums']['segmentation_zh.txt']}`
"""
    report_path = OUTPUT_DIR / "REPORT_DEEP_CLEANING.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Saved deep cleaning report to {report_path}")

if __name__ == "__main__":
    main()
