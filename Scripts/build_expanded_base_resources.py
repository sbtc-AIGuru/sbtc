"""build_expanded_base_resources.py: Chương trình xây dựng tập tài nguyên Base y khoa đa ngữ đồ sộ.

Tích hợp đa nguồn:
1. File Aligned 60K: medical_queries_60k_aligned.csv (856 concepts y sinh đối chiếu 1-1).
2. WHO ICD-10 XML: icd102019en.xml (hơn 20.000 bệnh danh chuẩn quốc tế).
3. Tri thức Đông Y & Dược thư: lexicon_data.py (vị thuốc Bắc, phương thang, biệt dược).
4. Khai phá đa tiến trình (Parallel Corpus Mining) từ các shards chunks y tế thực tế của cuộc thi.
"""

from __future__ import annotations

import csv
import glob
import html
import json
import os
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Thêm đường dẫn để nạp lexicon_data từ archive
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "sbtc" / "Archive" / "bm25_retrieval_v4"))
from Retrieval.lexicon_data import (  # type: ignore
    COLLOQUIAL_CONCEPTS,
    DISEASE_CONCEPTS,
    DRUG_CONCEPTS,
    LAB_CONCEPTS,
    TCM_CONCEPTS,
)

# ==============================================================================
# BỘ LỌC NGÔN NGỮ HỌC NGHIÊM NGẶT (STRICT LINGUISTIC FILTERS)
# ==============================================================================

VI_STOPWORDS_BOUNDARY: Set[str] = {
    "và", "hoặc", "là", "của", "cho", "trong", "ngoài", "với", "được", "bị", "sẽ", "đang", "đã",
    "này", "kia", "nào", "khác", "rất", "quá", "nhiều", "ít", "một", "các", "những", "vào", "ra",
    "lên", "xuống", "dần", "theo", "để", "do", "bởi", "tại", "từ", "đến", "về", "như", "nhất",
    "thì", "mà", "cũng", "chỉ", "còn", "khi", "nếu", "dù", "nên", "cần", "phải", "có", "không",
    "chưa", "chẳng", "ngay", "luôn", "rồi", "qua", "lại", "ngày", "tháng", "năm", "người",
    "ở", "trên", "dưới", "giữa", "trước", "sau", "lúc", "hồi", "dạo", "khiến", "giúp", "làm",
    "dùng", "uống", "tiêm", "sắc", "chữa", "trị", "mang", "mắc",
}

VI_BANNED_ANYWHERE: Set[str] = {
    "cần", "nên", "phải", "có thể", "khiến", "giúp", "đem", "hãy", "đừng", "chớ", "đã", "đang",
    "sẽ", "vừa", "mới", "cũng", "vẫn", "cứ", "còn", "lại", "bao gồm", "gồm", "rằng", "thì", "mà",
    "nếu", "bởi", "vì", "để", "song", "tuy", "dù", "khỏi", "cùng", "hồi", "dạo", "người bệnh",
    "bệnh nhân", "cơ sở", "tỉnh", "thành phố", "huyện", "xã", "phường", "dã chiến", "khách sạn",
    "công ty", "trường học", "giáo viên", "học sinh", "sinh viên", "cán bộ", "nhân viên",
    "thành viên", "đoàn viên", "hội viên", "bài viết", "trang web", "chương trình", "con tôi",
    "chúng tôi", "bác sĩ", "y tá", "điều dưỡng", "bố mẹ", "ông bà", "vợ chồng", "khách hàng",
    "tiến hành", "nhập viện", "xuất viện", "chuyển viện", "khám bệnh", "đi khám", "tái khám",
    "thuốc trừ sâu", "có dạng", "có triệu chứng", "hoặc", "hay",
}

VI_BANNED_TAILS: Set[str] = {
    "ở", "và", "hoặc", "hay", "của", "cho", "với", "trong", "ngoài", "trên", "dưới", "từ", "đến",
    "tại", "do", "về", "như", "là", "bị", "được", "này", "kia", "đó", "đấy", "nào", "gì", "sao",
    "ai", "đâu", "rất", "quá", "lắm", "hơn", "nhất", "chỉ", "chưa", "chẳng", "không", "có",
    "lấy", "dùng", "uống", "tiêm", "sắc", "xuất", "nhập", "tiến hành", "xuất hiện", "phát hiện",
    "xảy ra", "gia tăng", "suy giảm", "làm", "gây", "dẫn", "bảo đảm", "hỗ trợ", "giai", "nguy",
    "tinh", "bắc", "nam", "trung", "mỹ", "anh", "pháp", "việt", "kéo dài", "ngày", "tháng", "năm",
    "hôm", "nay", "qua", "sau", "trước", "sớm", "muộn", "nặng", "nhẹ", "cao", "thấp", "nhiều", "ít",
    "thế", "hệ", "h", "dạng", "loại", "nhóm",
}

ZH_VALID_SUFFIXES = (
    "炎", "症", "病", "瘤", "癌", "衰竭", "梗死", "梗塞", "综合征", "痛", "障碍",
    "感染", "损伤", "溃疡", "结石", "增生", "狭窄", "坏死", "硬化", "肿", "栓",
    "脓", "癣", "疹", "汤", "丸", "散", "颗粒", "胶囊", "口服液", "注射液", "膏",
    "草", "根", "花", "叶", "皮", "子", "仁", "参", "芪", "苓", "术", "连", "芩", "柏",
)

EN_STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most",
    "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other",
    "our", "ours", "ourselves", "out", "over", "own", "s", "same", "she", "should", "so", "some",
    "such", "t", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "with", "would",
    "study", "studies", "case", "cases", "report", "reports", "patient", "patients", "also", "may",
    "associated", "due", "following", "including", "used", "using", "based", "taken", "main", "severity",
    "unspecified", "encounter", "initial", "subsequent", "sequela", "other", "specified", "bilateral",
}

EN_PINYIN_MARKERS: Set[str] = {
    "tang", "wan", "san", "yin", "yang", "qi", "zhong", "xiao", "da", "bai", "hu", "fang",
    "bu", "yi", "shen", "di", "huang", "gui", "zhi", "chai", "ling", "gan", "cao", "lian",
}


def clean_vi_phrase(phrase: str) -> Optional[str]:
    """Gọt stopwords 2 đầu và kiểm định tính toàn vẹn của Cụm Danh từ Y khoa tiếng Việt."""
    if not phrase:
        return None
    phrase = unicodedata.normalize("NFKC", phrase)
    phrase = html.unescape(phrase)
    phrase = phrase.strip().lower()
    phrase = re.sub(r"[^\w\sà-ỹ]", " ", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip()

    for banned in VI_BANNED_ANYWHERE:
        if re.search(rf"\b{re.escape(banned)}\b", phrase):
            return None

    words = phrase.split()
    if not words:
        return None

    if words[0] == "viên":
        if len(words) < 2 or words[1] not in {"nén", "nang", "sủi", "ngậm", "đặt", "uống"}:
            return None

    while words and words[0] in VI_STOPWORDS_BOUNDARY:
        words.pop(0)
    while words and words[-1] in VI_STOPWORDS_BOUNDARY:
        words.pop()

    if len(words) < 2 or len(words) > 5:
        return None

    if words[-1] in VI_BANNED_TAILS:
        return None

    if len(words[-1]) <= 1:
        return None

    res = " ".join(words)
    if not re.match(r"^[a-zà-ỹ0-9\s]+$", res):
        return None

    return res


def clean_zh_term(term: str) -> Optional[str]:
    """Lọc các thuật ngữ y dược tiếng Trung chuẩn xác."""
    if not term:
        return None
    term = unicodedata.normalize("NFKC", term).strip()
    if not all("\u4e00" <= c <= "\u9fff" for c in term):
        return None
    if len(term) < 2 or len(term) > 6:
        return None
    if term.endswith(ZH_VALID_SUFFIXES):
        return term
    return None


def clean_en_phrase(phrase: str) -> Optional[str]:
    """Gọt stopwords và kiểm tra cụm từ tiếng Anh."""
    if not phrase:
        return None
    phrase = unicodedata.normalize("NFKC", phrase)
    phrase = html.unescape(phrase)
    phrase = phrase.strip().lower()
    phrase = re.sub(r"\(.*?\)", "", phrase)
    phrase = re.sub(r",\s*.*", "", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip()

    if len(phrase) > 55 or "obsolete" in phrase:
        return None

    if not re.search(r"^[a-z0-9\s\-]+$", phrase):
        return None

    words = phrase.split()
    pinyin_count = sum(1 for w in words if w in EN_PINYIN_MARKERS)
    if pinyin_count >= 2:
        return None

    while words and words[0] in EN_STOPWORDS:
        words.pop(0)
    while words and words[-1] in EN_STOPWORDS:
        words.pop()

    if len(words) < 1 or len(words) > 5:
        return None

    return " ".join(words)


# ==============================================================================
# PATTERNS CHO KHAI PHÁ CORPUS SHARDS (CORPUS MINING PATTERNS)
# ==============================================================================

VI_PATTERN = re.compile(
    r"\b(?:bệnh|hội chứng|chứng|triệu chứng|viêm|suy|thoái hóa|u|ung thư|nhiễm|rối loạn|tổn thương|đau|sưng|loét|sỏi|ngộ độc|dị ứng)\s+[a-zà-ỹ0-9]+(?:\s+[a-zà-ỹ0-9]+){1,3}\b",
    re.IGNORECASE,
)
VI_DRUG_PATTERN = re.compile(
    r"\b(?:thuốc|kháng sinh|kháng viêm|dược liệu|vị thuốc|chỉ số|xét nghiệm)\s+[a-zà-ỹ0-9]+(?:\s+[a-zà-ỹ0-9]+){1,2}\b",
    re.IGNORECASE,
)
EN_PATTERN = re.compile(
    r"\b[a-z]+(?:\s+[a-z]+){1,3}\s+(?:syndrome|disease|disorder|infection|failure|carcinoma|cancer|tumor|infarction|deficiency|hypertension|ulcer|calculi|pain|injury|edema)\b",
    re.IGNORECASE,
)
ZH_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,5}(?:炎|症|病|瘤|癌|衰竭|梗死|梗塞|综合征|痛|功能障碍|感染|损伤|溃疡|结石|增生|狭窄|坏死)"
)
ZH_TCM_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,4}(?:汤|丸|散|片|胶囊|颗粒|口服液|注射液|膏|草|根|花|叶|皮|子|仁)"
)


def _mine_single_shard(shard_path: str) -> Tuple[Counter, Counter, Counter, int]:
    vi_counter = Counter()
    en_counter = Counter()
    zh_counter = Counter()
    chunk_count = 0

    try:
        with open(shard_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                for child in record.get("children", []):
                    c_text = child.get("chunk_text", "")
                    if not c_text:
                        continue
                    chunk_count += 1
                    c_norm = unicodedata.normalize("NFKC", c_text).lower()

                    # Tiếng Việt
                    for p in VI_PATTERN.findall(c_norm):
                        cp = clean_vi_phrase(p)
                        if cp: vi_counter[cp] += 1
                    for p in VI_DRUG_PATTERN.findall(c_norm):
                        cp = clean_vi_phrase(p)
                        if cp: vi_counter[cp] += 1

                    # Tiếng Anh
                    for p in EN_PATTERN.findall(c_norm):
                        cp = clean_en_phrase(p)
                        if cp: en_counter[cp] += 1

                    # Tiếng Trung
                    for p in ZH_PATTERN.findall(c_text):
                        cp = clean_zh_term(p)
                        if cp: zh_counter[cp] += 1
                    for p in ZH_TCM_PATTERN.findall(c_text):
                        cp = clean_zh_term(p)
                        if cp: zh_counter[cp] += 1
    except Exception:
        pass

    return vi_counter, en_counter, zh_counter, chunk_count


def main() -> None:
    print("=" * 75)
    print("BẮT ĐẦU XÂY DỰNG TẬP DATA BASE Y KHOA ĐA NGỮ ĐỒ SỘ & CHUẨN XÁC")
    print("=" * 75)
    start_time = time.time()

    vi_vocab: Set[str] = set()
    en_vocab: Set[str] = set()
    zh_vocab: Set[str] = set()
    concepts_list: List[Dict[str, Any]] = []
    seen_concepts: Set[str] = set()

    # --------------------------------------------------------------------------
    # 1. NẠP TỪ FILE ALIGNED 60K (856 CONCEPTS ĐỐI CHIẾU 1-1)
    # --------------------------------------------------------------------------
    aligned_60k_path = Path("/home/tran-nhat-truong/Downloads/medical_queries_60k_aligned.csv")
    if aligned_60k_path.is_file():
        print(f"\n[1/4] Đang nạp từ file Aligned 60K: {aligned_60k_path.name}...")
        with open(aligned_60k_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                b_vi = clean_vi_phrase(row.get("base_vi", "")) or row.get("base_vi", "").strip().lower()
                b_en = clean_en_phrase(row.get("base_en", "")) or row.get("base_en", "").strip().lower()
                b_zh = clean_zh_term(row.get("base_zh", "")) or row.get("base_zh", "").strip()
                cid = row.get("concept_id", "").strip()

                if b_vi: vi_vocab.add(b_vi)
                if b_en: en_vocab.add(b_en)
                if b_zh: zh_vocab.add(b_zh)

                if cid and cid not in seen_concepts:
                    seen_concepts.add(cid)
                    concepts_list.append({
                        "concept_id": cid,
                        "category": row.get("category", ""),
                        "vi": b_vi,
                        "en": b_en,
                        "zh": b_zh,
                        "icd10_code": row.get("icd10_code", ""),
                    })
        print(f"  -> Đã nạp {len(seen_concepts)} concepts đối chiếu 1-1.")
        print(f"  -> Từ vựng 60k: VI={len(vi_vocab)}, EN={len(en_vocab)}, ZH={len(zh_vocab)}")
    else:
        print(f"Cảnh báo: Không tìm thấy {aligned_60k_path}")

    # --------------------------------------------------------------------------
    # 2. NẠP TỪ WHO ICD-10 XML CHÍNH THỨC (HƠN 20.000 BỆNH DANH QUỐC TẾ)
    # --------------------------------------------------------------------------
    icd_xml_path = Path("/home/tran-nhat-truong/Downloads/icd102019en.xml")
    if icd_xml_path.is_file():
        print(f"\n[2/4] Đang nạp và phân tích WHO ICD-10 XML: {icd_xml_path.name}...")
        tree = ET.parse(icd_xml_path)
        root = tree.getroot()
        who_count = 0
        for cls in root.findall("Class"):
            for rubric in cls.findall("Rubric"):
                if rubric.get("kind") in ("preferred", "inclusion"):
                    for label in rubric.findall("Label"):
                        raw_txt = "".join(label.itertext())
                        c_en = clean_en_phrase(raw_txt)
                        if c_en and len(c_en) > 2:
                            en_vocab.add(c_en)
                            who_count += 1
        print(f"  -> Đã trích xuất {who_count} lượt thuật ngữ bệnh học chuẩn WHO ICD-10.")
        print(f"  -> Tổng từ vựng tiếng Anh hiện tại: {len(en_vocab)}")
    else:
        print(f"Cảnh báo: Không tìm thấy {icd_xml_path}")

    # --------------------------------------------------------------------------
    # 3. NẠP TỪ KHO TRI THỨC ĐÔNG Y & DƯỢC THƯ (LEXICON_DATA.PY)
    # --------------------------------------------------------------------------
    print("\n[3/4] Đang nạp từ kho tri thức Đông Y & Dược thư (lexicon_data)...")
    curated_groups = [DISEASE_CONCEPTS, DRUG_CONCEPTS, TCM_CONCEPTS, COLLOQUIAL_CONCEPTS, LAB_CONCEPTS]
    lex_added_vi, lex_added_zh, lex_added_en = 0, 0, 0
    for group in curated_groups:
        for item in group:
            lbls = item.get("labels", {})
            if "vi" in lbls and lbls["vi"]:
                c_vi = clean_vi_phrase(lbls["vi"]) or lbls["vi"].strip().lower()
                if c_vi: vi_vocab.add(c_vi); lex_added_vi += 1
            if "zh" in lbls and lbls["zh"]:
                c_zh = clean_zh_term(lbls["zh"]) or lbls["zh"].strip()
                if c_zh: zh_vocab.add(c_zh); lex_added_zh += 1
            if "en" in lbls and lbls["en"]:
                c_en = clean_en_phrase(lbls["en"]) or lbls["en"].strip().lower()
                if c_en: en_vocab.add(c_en); lex_added_en += 1

            for alias in item.get("aliases", []):
                a_s = alias.strip()
                if any("\u4e00" <= ch <= "\u9fff" for ch in a_s):
                    c_zh = clean_zh_term(a_s) or a_s
                    zh_vocab.add(c_zh); lex_added_zh += 1
                elif any(ch in "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ" for ch in a_s):
                    c_vi = clean_vi_phrase(a_s)
                    if c_vi: vi_vocab.add(c_vi); lex_added_vi += 1
                else:
                    c_en = clean_en_phrase(a_s)
                    if c_en: en_vocab.add(c_en); lex_added_en += 1

    print(f"  -> Nạp thành công từ lexicon_data: VI={lex_added_vi}, ZH={lex_added_zh}, EN={lex_added_en}")

    # --------------------------------------------------------------------------
    # 4. KHAI PHÁ ĐA TIẾN TRÌNH TỪ CORPUS SHARDS (CORPUS MINING)
    # --------------------------------------------------------------------------
    shard_files = []
    shards_dir1 = repo_root / "data_final" / "chunks_format_v3_r3_reserve_test20k"
    shards_dir2 = repo_root / "data_final" / "chunks_format_v3_final"

    if shards_dir1.is_dir():
        shard_files.extend(glob.glob(str(shards_dir1 / "*.jsonl")))
    if shards_dir2.is_dir():
        all_final_shards = sorted(glob.glob(str(shards_dir2 / "*.jsonl")))
        # Lấy tối đa 150 shards tiêu biểu để tối ưu hóa thời gian và chất lượng
        shard_files.extend(all_final_shards[:150])

    print(f"\n[4/4] Khai phá song song từ {len(shard_files)} shards chunks corpus cuộc thi (8 CPU workers)...")

    mined_vi = Counter()
    mined_en = Counter()
    mined_zh = Counter()
    total_chunks = 0

    max_workers = min(os.cpu_count() or 4, 8)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_mine_single_shard, sf): sf for sf in shard_files}
        for future in as_completed(futures):
            try:
                vi_c, en_c, zh_c, c_count = future.result()
                mined_vi.update(vi_c)
                mined_en.update(en_c)
                mined_zh.update(zh_c)
                total_chunks += c_count
            except Exception:
                pass

    print(f"  -> Đã quét qua {total_chunks:,} chunks thực tế!")
    print(f"  -> Khai phá thô: VI={len(mined_vi)}, EN={len(mined_en)}, ZH={len(mined_zh)}")

    # Lọc ngưỡng tần số xuất hiện (Frequency Cutoff) để loại trừ triệt để nhiễu OOV hiếm gặp:
    # Tiếng Việt: lấy các cụm xuất hiện >= 2 lần
    for phrase, count in mined_vi.items():
        if count >= 2:
            vi_vocab.add(phrase)

    # Tiếng Trung: lấy các từ xuất hiện >= 2 lần
    for term, count in mined_zh.items():
        if count >= 2:
            zh_vocab.add(term)

    # Tiếng Anh: lấy các cụm xuất hiện >= 2 lần
    for phrase, count in mined_en.items():
        if count >= 2:
            en_vocab.add(phrase)

    # --------------------------------------------------------------------------
    # 5. XUẤT BẢN THÀNH PHẨM VÀO SBTC/RESOURCES/
    # --------------------------------------------------------------------------
    output_dir = repo_root / "sbtc" / "Resources"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. base_vi.txt
    sorted_vi = sorted(vi_vocab)
    vi_path = output_dir / "base_vi.txt"
    with open(vi_path, "w", encoding="utf-8") as f:
        for t in sorted_vi:
            f.write(t + "\n")

    # 2. base_zh.txt
    sorted_zh = sorted(zh_vocab)
    zh_path = output_dir / "base_zh.txt"
    with open(zh_path, "w", encoding="utf-8") as f:
        for t in sorted_zh:
            f.write(t + "\n")

    # 3. base_en.txt
    sorted_en = sorted(en_vocab)
    en_path = output_dir / "base_en.txt"
    with open(en_path, "w", encoding="utf-8") as f:
        for t in sorted_en:
            f.write(t + "\n")

    # 4. concepts_aligned_vi_en_zh.jsonl
    concepts_path = output_dir / "concepts_aligned_vi_en_zh.jsonl"
    with open(concepts_path, "w", encoding="utf-8") as f:
        for c in concepts_list:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    elapsed = time.time() - start_time
    print("\n" + "=" * 75)
    print("HOÀN TẤT XUẤT BẢN TẬP DATA BASE Y KHOA ĐỒ SỘ VÀ CHUẨN XÁC!")
    print(f"Thời gian thực thi: {elapsed:.2f}s")
    print("-" * 75)
    print(f"1. base_vi.txt:                    {len(sorted_vi):>6,} THUẬT NGỮ ĐỘC NHẤT 100% ({vi_path.stat().st_size / 1024:.1f} KB)")
    print(f"2. base_zh.txt:                    {len(sorted_zh):>6,} THUẬT NGỮ ĐỘC NHẤT 100% ({zh_path.stat().st_size / 1024:.1f} KB)")
    print(f"3. base_en.txt:                    {len(sorted_en):>6,} THUẬT NGỮ ĐỘC NHẤT 100% ({en_path.stat().st_size / 1024:.1f} KB)")
    print(f"4. concepts_aligned_vi_en_zh.jsonl: {len(concepts_list):>6,} CONCEPTS ĐỐI CHIẾU 1-1 ({concepts_path.stat().st_size / 1024:.1f} KB)")
    print("=" * 75)


if __name__ == "__main__":
    main()
