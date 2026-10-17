#!/usr/bin/env python3
"""
curate_ultra_clean_lexicon.py - Đợt 3: Làm sạch triệt để (Ultra-Clean) tập từ vựng y khoa.
Loại bỏ hoàn toàn các cụm hành động nghiên cứu (đánh giá, ghi nhận, phát hiện, sử dụng),
các liên từ/kết nối (kèm theo, liên quan, tiền sử), các cụm đếm/số thứ tự (phương pháp 1, nhóm 2),
và các thuật ngữ triết học/vật lý/giáo dục ngoài miền trong tiếng Trung.
"""

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[4]
INPUT_DIR = WORKSPACE / "artifacts" / "retrieval" / "medical-lexicon-staging" / "20261015-run-08" / "deep_cleaned"
OUTPUT_DIR = WORKSPACE / "artifacts" / "retrieval" / "medical-lexicon-staging" / "20261015-run-08" / "ultra_cleaned"

VI_INPUT = INPUT_DIR / "deep_clean_candidates_vi.jsonl"
ZH_INPUT = INPUT_DIR / "deep_clean_candidates_zh.jsonl"
EN_INPUT = INPUT_DIR / "deep_clean_candidates_en.jsonl"

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

# VI: Danh sách cụm từ nối, từ chức năng và rác hành vi nghiên cứu
VI_PURE_FUNCTIONAL = {
    "kèm theo", "tiền sử", "tiền sử bệnh", "tiền sử bệnh lý", "tiền sử gia đình",
    "liên quan", "liên quan dương", "liên quan thuận", "liên quan tích cực", "liên quan ung thư",
    "kết quả", "kết quả bất lợi", "kết quả bệnh", "kết quả nghiên cứu",
    "mức độ", "mức độ nghiêm trọng",
    "tình trạng bệnh", "tình trạng bệnh lý",
    "đặc điểm", "đặc điểm bệnh nhân", "đặc điểm lâm sàng",
    "yếu tố", "yếu tố nguy cơ", "yếu tố thuận lợi",
    "phương pháp điều trị", "phương pháp nghiên cứu",
    "thời gian bơi", "mía gốc lần 1", "ngày 0",
    "bảo vệ bằng mật khẩu", "bằng bác sĩ y khoa", "ba nhóm theo giới tính"
}

VI_RESEARCH_ACTION_PREFIXES = (
    "đánh giá ", "xác định ", "phát hiện ", "quan sát ", "ghi nhận ", 
    "sử dụng ", "thực hiện ", "cho thấy ", "có thể "
)

# Các ngoại lệ quý hiếm trong y học cần bảo vệ dù bắt đầu bằng các từ trên
VI_ACTION_EXCEPTIONS = {
    "xác định giới tính", "xác định trình tự", "xác định týp huyết thanh",
    "phát hiện dna hpv", "phát hiện hpv", "phát hiện virus", "phát hiện e. coli"
}

ZH_NON_MEDICAL = {
    "一元论", "二元论", "唯物主义", "唯心主义", "相对论", "光电效应", "自由落体", 
    "一年生植物", "二年生植物", "多年生植物", "一次性", "能力分组", "能力倾向测验",
    "时间知觉", "空间知觉", "社会知觉", "患者", "病人", "医生", "护士", "家属"
}

def evaluate_ultra_vi(record: dict) -> tuple[bool, str]:
    term = record.get("clean_surface", "").strip().lower()
    tokens = term.split()
    if not tokens:
        return False, "empty_term"
    
    # 1. Bắt đầu bằng chữ số hoặc ký tự lạ trừ khi là tên hóa chất/gen chuẩn
    if re.match(r"^[-+*/0-9]", term):
        if not re.match(r"^\d+-(?:hydroxy|alpha|beta|hxd|o-|amino|deoxy)", term):
            return False, "starts_with_digit_or_symbol"

    # 2. Số thứ tự, đếm mẫu, số lượng đối tượng
    if re.search(r"\b\d+\b", term):
        # Cho phép các định danh y khoa chuẩn
        if not re.search(r"\b(?:typ|type|thể|tế bào|nhiễm sắc thể|gen|kháng nguyên|cd|cox|h\d+n\d+|covid-?19|nhóm máu|độ|đoạn|nhánh|protein|thụ thể)\s+\d+\b", term):
            if re.search(r"\b(?:mẫu|bài|ca|người|bệnh nhân|phương pháp|giai đoạn|nhóm|lần|đợt|ngày|tháng|năm|giờ|phút|giây|tuổi|giếng|đốt sống)\s+\d+\b", term):
                return False, "count_or_sequence_number"
            if re.search(r"^\d+\s+", term):
                return False, "leading_number_count"

    # 3. Phương pháp nghiên cứu / thí nghiệm 2D/3D
    if re.search(r"\b(?:phương pháp\s+\d+|phương pháp\s+2d|phương pháp\s+3d|nghiên cứu\s+tiến cứu|nghiên cứu\s+hồi cứu|nhóm chứng|cỡ mẫu)\b", term):
        return False, "research_methodology_noise"

    # 4. Từ nối, từ chức năng
    if term in VI_PURE_FUNCTIONAL:
        return False, "pure_functional_phrase"

    # 5. Tiền tố tiền sử (history of disease -> giữ disease, bỏ tiền tố)
    if term.startswith("tiền sử "):
        return False, "prefix_tien_su"

    # 6. Tiền tố hành vi nghiên cứu
    for prefix in VI_RESEARCH_ACTION_PREFIXES:
        if term.startswith(prefix) and term not in VI_ACTION_EXCEPTIONS:
            return False, f"research_action_prefix_{prefix.strip()}"

    # 7. Giới từ kết thúc dang dở (trailing prepositions)
    last = tokens[-1]
    if last in {"ở", "cho", "với", "về", "của", "và", "như"}:
        return False, f"trailing_preposition_{last}"
    if last == "bằng" and (len(tokens) < 2 or tokens[-2] not in {"cân", "thăng", "công"}):
        return False, "trailing_preposition_bang"
    if last == "do" and (len(tokens) < 2 or tokens[-2] not in {"tự", "lý"}):
        return False, "trailing_preposition_do"

    return True, "approved_ultra_clean"

def evaluate_ultra_zh(record: dict) -> tuple[bool, str]:
    term = record.get("clean_surface", "").strip()
    if term in ZH_NON_MEDICAL:
        return False, "non_medical_domain_zh"
    return True, "approved_ultra_clean"

def evaluate_ultra_en(record: dict) -> tuple[bool, str]:
    # EN đã được lọc theo MeSH Clinical Subtrees (Tree A-G), giữ 100%
    return True, "approved_ultra_clean"

def run_curation():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== BẮT ĐẦU ĐỢT LÀM SẠCH TRIỆT ĐỂ (ULTRA-CLEAN LEXICON V3.0) ===")
    
    # 1. Xử lý tiếng Việt
    vi_clean, vi_rejected = [], []
    with VI_INPUT.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            is_valid, reason = evaluate_ultra_vi(rec)
            if is_valid:
                rec["ultra_curated_status"] = "approved_ultra_clean"
                vi_clean.append(rec)
            else:
                rec["ultra_curated_status"] = "rejected_ultra"
                rec["ultra_rejected_reason"] = reason
                vi_rejected.append(rec)
                
    print(f"Tiếng Việt (VI): {len(vi_clean)} sạch ({len(vi_clean)/(len(vi_clean)+len(vi_rejected))*100:.2f}%) | {len(vi_rejected)} loại")

    # 2. Xử lý tiếng Trung
    zh_clean, zh_rejected = [], []
    with ZH_INPUT.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            is_valid, reason = evaluate_ultra_zh(rec)
            if is_valid:
                rec["ultra_curated_status"] = "approved_ultra_clean"
                zh_clean.append(rec)
            else:
                rec["ultra_curated_status"] = "rejected_ultra"
                rec["ultra_rejected_reason"] = reason
                zh_rejected.append(rec)
                
    print(f"Tiếng Trung (ZH): {len(zh_clean)} sạch ({len(zh_clean)/(len(zh_clean)+len(zh_rejected))*100:.2f}%) | {len(zh_rejected)} loại")

    # 3. Xử lý tiếng Anh
    en_clean, en_rejected = [], []
    with EN_INPUT.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            is_valid, reason = evaluate_ultra_en(rec)
            if is_valid:
                rec["ultra_curated_status"] = "approved_ultra_clean"
                en_clean.append(rec)
            else:
                rec["ultra_curated_status"] = "rejected_ultra"
                rec["ultra_rejected_reason"] = reason
                en_rejected.append(rec)
                
    print(f"Tiếng Anh (EN): {len(en_clean)} sạch | {len(en_rejected)} loại")

    # Xuất các file JSONL
    vi_clean_path = OUTPUT_DIR / "ultra_clean_candidates_vi.jsonl"
    zh_clean_path = OUTPUT_DIR / "ultra_clean_candidates_zh.jsonl"
    en_clean_path = OUTPUT_DIR / "ultra_clean_candidates_en.jsonl"
    vi_rej_path = OUTPUT_DIR / "rejected_ultra_vi.jsonl"
    zh_rej_path = OUTPUT_DIR / "rejected_ultra_zh.jsonl"
    en_rej_path = OUTPUT_DIR / "rejected_ultra_en.jsonl"

    for path, data in [
        (vi_clean_path, vi_clean), (zh_clean_path, zh_clean), (en_clean_path, en_clean),
        (vi_rej_path, vi_rejected), (zh_rej_path, zh_rejected), (en_rej_path, en_rejected)
    ]:
        with path.open("w", encoding="utf-8") as out:
            for item in data:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Xuất từ điển phẳng segmentation_vi.txt và segmentation_zh.txt
    seg_vi_path = OUTPUT_DIR / "segmentation_vi.txt"
    seg_zh_path = OUTPUT_DIR / "segmentation_zh.txt"

    unique_vi_terms = sorted(list({r["clean_surface"].lower() for r in vi_clean if len(r["clean_surface"].strip()) > 1}))
    unique_zh_terms = sorted(list({r["clean_surface"].lower() for r in zh_clean if len(r["clean_surface"].strip()) > 1}))

    with seg_vi_path.open("w", encoding="utf-8") as f:
        for t in unique_vi_terms:
            f.write(t + "\n")

    with seg_zh_path.open("w", encoding="utf-8") as f:
        for t in unique_zh_terms:
            f.write(t + "\n")

    print(f"Đã xuất segmentation_vi.txt: {len(unique_vi_terms)} unique terms")
    print(f"Đã xuất segmentation_zh.txt: {len(unique_zh_terms)} unique terms")

    # Tạo Manifest
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_directory": str(INPUT_DIR),
        "output_directory": str(OUTPUT_DIR),
        "counts": {
            "vi": {"clean": len(vi_clean), "rejected": len(vi_rejected), "unique_terms": len(unique_vi_terms)},
            "zh": {"clean": len(zh_clean), "rejected": len(zh_rejected), "unique_terms": len(unique_zh_terms)},
            "en": {"clean": len(en_clean), "rejected": len(en_rejected), "unique_terms": len(en_clean)},
            "total_ultra_clean": len(vi_clean) + len(zh_clean) + len(en_clean)
        },
        "file_hashes": {
            "ultra_clean_candidates_vi.jsonl": sha256_file(vi_clean_path),
            "ultra_clean_candidates_zh.jsonl": sha256_file(zh_clean_path),
            "ultra_clean_candidates_en.jsonl": sha256_file(en_clean_path),
            "rejected_ultra_vi.jsonl": sha256_file(vi_rej_path),
            "rejected_ultra_zh.jsonl": sha256_file(zh_rej_path),
            "rejected_ultra_en.jsonl": sha256_file(en_rej_path),
            "segmentation_vi.txt": sha256_file(seg_vi_path),
            "segmentation_zh.txt": sha256_file(seg_zh_path),
        }
    }

    with (OUTPUT_DIR / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("=== HOÀN TẤT ĐỢT LÀM SẠCH TRIỆT ĐỂ (ULTRA-CLEAN) ===")

if __name__ == "__main__":
    run_curation()
