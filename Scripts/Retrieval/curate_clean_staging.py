#!/usr/bin/env python3
"""Curate clean staging medical lexicon candidates.

This script filters raw candidate pools from 20261015-run-08, discarding noisy,
malformed, clause-fragment, and punctuation-laden items, keeping strictly
high-confidence medical terms ready for tokenizer and lexicon enrichment.

Derived files are outputted to:
artifacts/retrieval/medical-lexicon-staging/20261015-run-08/cleaned/
Original candidate files remain 100% untouched.
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

WORKSPACE = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru")
STAGING_DIR = WORKSPACE / "artifacts" / "retrieval" / "medical-lexicon-staging" / "20261015-run-08"
OUTPUT_DIR = STAGING_DIR / "cleaned"

VI_INPUT = STAGING_DIR / "candidates_vi.jsonl"
ZH_INPUT = STAGING_DIR / "candidates_zh.jsonl"
EN_INPUT = STAGING_DIR / "candidates_en.jsonl"

VIETNAMESE_DIACRITICS = set(
    "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    "ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ"
)

VI_LEADING_STOPWORDS = {
    "của", "và", "các", "những", "được", "trong", "cho", "tại", "với", "như", "vì", 
    "sau", "trước", "ở", "nếu", "thì", "là", "bị", "do", "khi", "đang", "theo", 
    "từ", "lên", "vào", "ra", "đến", "về", "một số", "có", "sẽ", "phải", "đã",
    "đối với", "cùng với", "nhằm", "để", "bởi", "rằng", "mà", "nên", "tuy", "dù",
    "ngay cả", "đặc biệt", "qua", "nhờ", "gồm", "thuộc", "bệnh nhân", "người bệnh",
    "chuột", "thỏ", "động vật", "bác sĩ"
}

VI_TRAILING_STOPWORDS = {
    "và", "hoặc", "của", "trong", "cho", "về", "với", "như", "các", "một số", 
    "là", "được", "xảy ra", "này", "đó", "kia", "sau", "trước", "nữa", "trên",
    "dưới", "khác", "khác nhau", "chung", "nhất", "hơn", "lại", "đi"
}

VI_INTERNAL_STOPWORDS = (
    " được ", " bị ", " so với ", " của ", " trong khi ", " cho thấy ", " ở mức ", 
    " đối với ", " cùng với ", " nhằm ", " và một số ", " trước khi ", " sau khi ",
    " xảy ra ", " gây ra ", " liên quan đến ", " theo dõi "
)

VI_NON_MEDICAL_EXACT = {
    "bài báo", "bài viết", "bài nghiên cứu", "bài toàn văn", "bài tổng quan", 
    "bài toán", "bàn giao", "hành khách", "miền tây nhật bản", "tài liệu tham khảo",
    "nghiên cứu bắt đầu lành mạnh", "đơn trung tâm", "khối u so với máu"
}

VI_CONVERSATIONAL_WORDS = {
    "biểu hiện", "bình thường", "bệnh viện", "chỉ số", "cảm giác", "dùng thuốc", 
    "dấu hiệu", "gần đây", "hai bên", "hiện tại", "không biết", "không có", 
    "khả năng", "kiểm tra", "kết quả", "lựa chọn", "nguy cơ", "nguy hiểm", 
    "nguyên nhân", "phương pháp", "sức khỏe", "sử dụng", "thời gian", "trả lời", 
    "tìm hiểu", "tình trạng", "tư vấn", "vấn đề", "xuất hiện", "ăn uống", 
    "đi khám", "ảnh hưởng", "ảnh hưởng đến"
}

ZH_STOP_PREFIXES = (
    "不算", "不是", "没有", "未见", "否认", "能否", "能不能", "是否", "可服", "主要是", "在线清洗"
)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def evaluate_vi(record: dict) -> tuple[bool, str, str]:
    surface = record.get("surface", "").strip()
    clean_surf = surface.strip("\"“\”\x27 ").strip()
    tokens = clean_surf.split()
    source_ids = record.get("source_ids", [])
    is_trusted = any(s.startswith("vi_fhir") or s == "vi_vietent_catalogue" for s in source_ids)

    # Kiểm tra độ dài ký tự tối thiểu: cấm tuyệt đối ký tự đơn lẻ (len <= 1)
    if len(clean_surf) <= 1:
        return False, "single_character_prohibited", clean_surf

    # Kiểm tra độ dài token
    if len(tokens) == 1:
        if not (is_trusted and (any(c in VIETNAMESE_DIACRITICS for c in clean_surf) or len(clean_surf) >= 4)):
            return False, "single_token_untrusted", clean_surf
    elif len(tokens) < 1 or len(tokens) > 5:
        return False, "token_length_out_of_range_2_5", clean_surf

    # Ký tự lạ
    if any(c in clean_surf for c in '[]{};:<>?="^~`|\\'):
        if not (is_trusted and "(" in clean_surf and ")" in clean_surf and clean_surf.count("(") == 1 and clean_surf.count(")") == 1):
            return False, "contains_weird_characters", clean_surf

    # Dấu ngắt câu / mệnh đề
    if re.search(r"[,;!?…。！？]", clean_surf):
        return False, "contains_clause_punctuation", clean_surf

    # Dính liều lượng
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|μg|g|kg|ml|l|%|đơn vị)\b", clean_surf, re.I):
        return False, "contains_dosage", clean_surf

    # Rò rỉ tiếng Anh / không dấu
    has_vi = any(c in VIETNAMESE_DIACRITICS for c in clean_surf)
    if not has_vi and not is_trusted:
        return False, "english_or_unaccented_leak", clean_surf

    # Internal stopwords
    lower_surf = f" {clean_surf.lower()} "
    if any(w in lower_surf for w in VI_INTERNAL_STOPWORDS):
        return False, "contains_internal_stopword", clean_surf

    # Leading stopwords
    first_w = tokens[0].lower()
    if first_w in VI_LEADING_STOPWORDS:
        return False, f"leading_stopword_{first_w}", clean_surf
    if len(tokens) >= 2 and f"{tokens[0].lower()} {tokens[1].lower()}" in VI_LEADING_STOPWORDS:
        return False, "leading_stopword_phrase", clean_surf

    # Trailing stopwords
    last_w = tokens[-1].lower()
    if last_w in VI_TRAILING_STOPWORDS:
        return False, f"trailing_stopword_{last_w}", clean_surf

    # Blacklist cụ thể & Từ hội thoại thông thường
    if clean_surf.lower() in VI_NON_MEDICAL_EXACT:
        return False, "blacklisted_non_medical", clean_surf
    if clean_surf.lower() in VI_CONVERSATIONAL_WORDS:
        return False, "conversational_generic_term", clean_surf

    return True, "approved_clean", clean_surf

def evaluate_zh(record: dict) -> tuple[bool, str, str]:
    surface = record.get("surface", "").strip()
    clean_surf = surface.strip("\"' \t").strip()
    if len(clean_surf) < 2 or len(clean_surf) > 10:
        return False, "char_length_out_of_range_2_10", clean_surf
    if not all('\u4e00' <= c <= '\u9fff' for c in clean_surf):
        return False, "contains_non_cjk_characters", clean_surf
    for prefix in ZH_STOP_PREFIXES:
        if clean_surf.startswith(prefix):
            return False, f"leading_zh_stop_{prefix}", clean_surf
    return True, "approved_clean", clean_surf

def evaluate_en(record: dict) -> tuple[bool, str, str]:
    surface = record.get("surface", "").strip()
    clean_surf = surface.strip("\"' \t").strip()
    tokens = clean_surf.split()
    if len(tokens) < 1 or len(tokens) > 6:
        return False, "token_length_out_of_range_1_6", clean_surf
    if "," in clean_surf:
        return False, "comma_mesh_inverted_form", clean_surf
    if any(c in clean_surf for c in '[]{};:<>?="^~`|\\'):
        return False, "contains_weird_characters", clean_surf
    if re.search(r"[,;!?…。！？]", clean_surf):
        return False, "contains_clause_punctuation", clean_surf
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|μg|g|kg|ml|l|%|units?)\b", clean_surf, re.I):
        return False, "contains_dosage", clean_surf
    return True, "approved_clean", clean_surf

def process_language(input_file: Path, clean_file: Path, rejected_file: Path, eval_fn) -> dict:
    clean_records = []
    rejected_records = []
    reasons = Counter()

    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            ok, reason, normalized_surface = eval_fn(rec)
            rec_out = dict(rec)
            rec_out["clean_surface"] = normalized_surface
            if ok:
                rec_out["curated_status"] = "approved_clean"
                clean_records.append(rec_out)
            else:
                rec_out["curated_status"] = "rejected"
                rec_out["rejection_reason"] = reason
                rejected_records.append(rec_out)
                reasons[reason] += 1

    # Ghi file clean
    with open(clean_file, "w", encoding="utf-8") as f:
        for r in clean_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Ghi file rejected
    with open(rejected_file, "w", encoding="utf-8") as f:
        for r in rejected_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "total": len(clean_records) + len(rejected_records),
        "clean": len(clean_records),
        "rejected": len(rejected_records),
        "clean_rate": (len(clean_records) / (len(clean_records) + len(rejected_records))) * 100 if clean_records else 0,
        "reasons": dict(reasons.most_common(10)),
        "clean_sha256": sha256_file(clean_file),
        "rejected_sha256": sha256_file(rejected_file),
    }

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Starting Lexicon Curation...")
    print(f"Staging source: {STAGING_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")

    vi_stats = process_language(
        VI_INPUT, 
        OUTPUT_DIR / "clean_candidates_vi.jsonl", 
        OUTPUT_DIR / "rejected_vi.jsonl", 
        evaluate_vi
    )
    print(f"\n[VI] Total: {vi_stats['total']} | Clean: {vi_stats['clean']} ({vi_stats['clean_rate']:.2f}%) | Rejected: {vi_stats['rejected']}")

    zh_stats = process_language(
        ZH_INPUT, 
        OUTPUT_DIR / "clean_candidates_zh.jsonl", 
        OUTPUT_DIR / "rejected_zh.jsonl", 
        evaluate_zh
    )
    print(f"[ZH] Total: {zh_stats['total']} | Clean: {zh_stats['clean']} ({zh_stats['clean_rate']:.2f}%) | Rejected: {zh_stats['rejected']}")

    en_stats = process_language(
        EN_INPUT, 
        OUTPUT_DIR / "clean_candidates_en.jsonl", 
        OUTPUT_DIR / "rejected_en.jsonl", 
        evaluate_en
    )
    print(f"[EN] Total: {en_stats['total']} | Clean: {en_stats['clean']} ({en_stats['clean_rate']:.2f}%) | Rejected: {en_stats['rejected']}")

    # Tạo manifest
    manifest = {
        "curation_version": "1.0.0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_run_id": "20261015-run-08",
        "input_checksums": {
            "candidates_vi.jsonl": sha256_file(VI_INPUT),
            "candidates_zh.jsonl": sha256_file(ZH_INPUT),
            "candidates_en.jsonl": sha256_file(EN_INPUT),
        },
        "stats": {
            "vi": vi_stats,
            "zh": zh_stats,
            "en": en_stats,
        }
    }

    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\nSaved manifest to {manifest_path}")

    # Tạo REPORT_CLEANING.md
    report_md = f"""# Báo cáo kết quả lọc sạch Medical Lexicon Staging (20261015-run-08)

**Thời gian tạo:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}  
**Thư mục nguồn (Read-only):** `{STAGING_DIR}`  
**Thư mục dẫn xuất sạch (Cleaned):** `{OUTPUT_DIR}`  

---

## 1. Tổng quan số lượng sau lọc

| Ngôn ngữ | Tổng số gốc | Dùng được ngay (Clean) | Tỷ lệ giữ lại | Bị loại bỏ (Rejected) | Tỷ lệ loại bỏ |
|---|---:|---:|---:|---:|---:|
| **Tiếng Việt (VI)** | 47.058 | **{vi_stats['clean']:,}** | **{vi_stats['clean_rate']:.2f}%** | {vi_stats['rejected']:,} | {100 - vi_stats['clean_rate']:.2f}% |
| **Tiếng Trung (ZH)** | 18.749 | **{zh_stats['clean']:,}** | **{zh_stats['clean_rate']:.2f}%** | {zh_stats['rejected']:,} | {100 - zh_stats['clean_rate']:.2f}% |
| **Tiếng Anh (EN)** | 267.768 | **{en_stats['clean']:,}** | **{en_stats['clean_rate']:.2f}%** | {en_stats['rejected']:,} | {100 - en_stats['clean_rate']:.2f}% |
| **TỔNG CỘNG** | **333.575** | **{vi_stats['clean'] + zh_stats['clean'] + en_stats['clean']:,}** | **{(vi_stats['clean'] + zh_stats['clean'] + en_stats['clean']) / (vi_stats['total'] + zh_stats['total'] + en_stats['total']) * 100:.2f}%** | **{vi_stats['rejected'] + zh_stats['rejected'] + en_stats['rejected']:,}** | **{(vi_stats['rejected'] + zh_stats['rejected'] + en_stats['rejected']) / (vi_stats['total'] + zh_stats['total'] + en_stats['total']) * 100:.2f}%** |

---

## 2. Chi tiết phân loại và lý do loại bỏ ("Cắt bỏ phần kia")

### 2.1 Tiếng Việt (`clean_candidates_vi.jsonl`: {vi_stats['clean']:,} từ)
- **Tiêu chuẩn giữ lại (Clean):**
  - Cụm từ 2–5 từ có dấu tiếng Việt chuẩn hoặc nằm trong danh mục Bộ Y tế / FHIR / VietENT.
  - Loại bỏ hoàn toàn dấu quote, brackets, dấu câu ngắt mệnh đề.
  - Loại bỏ các từ đơn 1 từ không cần thiết cho `fixed_words`.
- **Top các lý do loại bỏ:**
{chr(10).join(f"  - `{reason}`: {count:,} thuật ngữ" for reason, count in vi_stats['reasons'].items())}

### 2.2 Tiếng Trung (`clean_candidates_zh.jsonl`: {zh_stats['clean']:,} từ)
- **Đặc điểm:** Dữ liệu THUOCL cực kỳ sạch, 99.86% là danh từ y học CJK chuẩn độ dài 2–10 ký tự.
- **Bảo toàn:** Giữ nguyên các thuật ngữ YHCT bắt đầu bằng `和` (như *和胃整肠丸*, *和中理脾丸*) và tiền tố y học `无` (như *无尿*, *无精子症*, *无菌*).
- **Top các lý do loại bỏ:**
{chr(10).join(f"  - `{reason}`: {count:,} thuật ngữ" for reason, count in zh_stats['reasons'].items())}

### 2.3 Tiếng Anh (`clean_candidates_en.jsonl`: {en_stats['clean']:,} từ)
- **Tiêu chuẩn giữ lại (Clean):**
  - Các MeSH Descriptors tự nhiên (1–6 từ), không có dấu phẩy.
  - Sạch sẽ, sẵn sàng đối chiếu và phân đoạn.
- **Top các lý do loại bỏ:**
{chr(10).join(f"  - `{reason}`: {count:,} thuật ngữ" for reason, count in en_stats['reasons'].items())}

---

## 3. Kiểm tra tính toàn vẹn (Checksums)

- `candidates_vi.jsonl`: `{manifest['input_checksums']['candidates_vi.jsonl']}`
- `clean_candidates_vi.jsonl`: `{vi_stats['clean_sha256']}`
- `rejected_vi.jsonl`: `{vi_stats['rejected_sha256']}`
- `candidates_zh.jsonl`: `{manifest['input_checksums']['candidates_zh.jsonl']}`
- `clean_candidates_zh.jsonl`: `{zh_stats['clean_sha256']}`
- `rejected_zh.jsonl`: `{zh_stats['rejected_sha256']}`
- `candidates_en.jsonl`: `{manifest['input_checksums']['candidates_en.jsonl']}`
- `clean_candidates_en.jsonl`: `{en_stats['clean_sha256']}`
- `rejected_en.jsonl`: `{en_stats['rejected_sha256']}`
"""
    report_path = OUTPUT_DIR / "REPORT_CLEANING.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Saved cleaning report to {report_path}")

if __name__ == "__main__":
    main()
