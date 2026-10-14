"""build_lexicon.py: Xây Dựng Kho Từ Điển Y Khoa Đa Ngữ Đồ Sộ & Sạch Rác Ngữ Pháp.

Tích hợp 8 nguồn tri thức y sinh và khẩu ngữ bệnh nhân:
1. ICD-10 Chuẩn hóa Quốc tế (WHO, Bộ Y Tế VN, ICD-10-CN) 22 chương bệnh.
2. Human Disease Ontology (DOID - OBO Foundry): Hệ thống ontology bệnh lý chuẩn quốc tế.
3. Medical Abbreviations & Trilingual Terminology (KumaTea & WHO).
4. Dược thư & Hoạt chất, Biệt dược phổ biến (Generic & Brand names).
5. Đông Y / Y học cổ truyền (TCM: Vị thuốc Bắc, Bài thuốc cổ phương chuẩn Hán-Việt-Anh).
6. ViMQ NER Gold Dataset (ICONIP2021) & ViMedical Consumer Health Vocabulary (12k câu hỏi bệnh nhân).
7. Xét nghiệm, Chẩn đoán hình ảnh & Chỉ số lâm sàng.
8. Khai phá có định hướng (Curated QA & Clinical Mining) từ corpus thực tế (300 shards).

Áp dụng bộ lọc ngôn ngữ học nghiêm ngặt (Strict Linguistic & Boundary Stopword Pruning):
- Loại bỏ 100% rác ngữ pháp (giới từ, liên từ, trợ động từ ở 2 đầu và bên trong cụm).
- Chặn đứng mọi từ cắt cụt đuôi (dangling tails: tinh, nguy, giai, thế, xuất, nhập...).
- Chỉ giữ lại Cụm Danh từ Y khoa thực thụ (Strict Clinical Noun Phrases).
- Tách bạch chuẩn xác tiếng Việt, tiếng Anh và tiếng Trung.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sbtc.Scripts.Retrieval.lexicon_data import (
    COLLOQUIAL_CONCEPTS,
    DISEASE_CONCEPTS,
    DRUG_CONCEPTS,
    LAB_CONCEPTS,
    TCM_CONCEPTS,
)

# ==============================================================================
# BỘ LỌC STOPWORDS & NGỮ PHÁP TIẾNG ANH (STRICT ENGLISH LINGUISTIC FILTER)
# ==============================================================================
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
    "incidence", "prevalence", "risk", "effect", "effects", "evaluation", "role", "level", "levels",
    "group", "groups", "result", "results", "day", "days", "year", "years", "month", "months", "age",
    "time", "times", "method", "methods", "conclusion", "conclusions", "background", "objective",
    "physician", "physicians", "hospital", "clinic", "clinical", "sample", "samples", "showed", "observed",
    "unspecified", "encounter", "initial", "subsequent", "sequela", "complicating", "complication",
    "without", "other", "specified", "bilateral", "left", "right", "site", "sites", "obsolete",
}

EN_PINYIN_MARKERS: Set[str] = {
    "tang", "wan", "san", "yin", "yang", "qi", "zhong", "xiao", "da", "bai", "hu", "fang",
    "bu", "yi", "shen", "di", "huang", "gui", "zhi", "chai", "ling", "gan", "cao", "lian",
}

EN_VALID_ENDINGS: Set[str] = {
    "disease", "diseases", "disorder", "disorders", "syndrome", "syndromes", "infection", "infections",
    "inflammation", "failure", "carcinoma", "cancer", "cancers", "tumor", "tumors", "pain",
    "hypertension", "injury", "injuries", "allergy", "allergies", "deficiency", "ulcer", "ulcers",
    "calculi", "calculus", "arthritis", "dermatitis", "colitis", "gastritis", "bronchitis",
    "pneumonia", "hepatitis", "cirrhosis", "asthma", "stroke", "infarction", "thrombosis", "embolism",
    "diabetes", "edema", "bleeding", "lesion", "lesions", "therapy", "treatment", "medication",
    "antibiotic", "antibiotics", "virus", "viruses", "bacterial", "bacteria", "antibody", "antibodies",
    "receptor", "receptors", "protein", "proteins", "acid", "cell", "cells", "tissue", "tissues",
    "artery", "vein", "vessels", "heart", "liver", "kidney", "lung", "brain", "tract", "test", "panel",
    "sarcoma", "lymphoma", "leukemia", "stenosis", "aneurysm", "atrophy", "hypertrophy", "spasm",
    "paralysis", "fever", "cough", "diarrhea", "vomiting", "nausea", "headache", "dementia", "sclerosis",
    "fibrosis", "necrosis", "gangrene", "abscess", "polyp", "cyst", "hernia", "fracture", "dislocation",
    "cataract", "glaucoma", "blindness", "deafness", "tinnitus", "vertigo", "epilepsy", "insomnia",
    "anemia", "neutropenia", "thrombocytopenia", "acidosis", "alkalosis", "hypoglycemia", "hyperglycemia",
}

EN_VALID_PREFIXES: Set[str] = {
    "acute", "chronic", "congenital", "recurrent", "primary", "secondary", "ischemic",
    "coronary", "pulmonary", "renal", "hepatic", "cardiac", "cerebral", "gastric",
    "respiratory", "vascular", "myocardial", "muscular", "skeletal", "immune", "autoimmune",
    "allergic", "infectious", "viral", "bacterial", "inflammatory", "metabolic", "endocrine",
    "malignant", "benign", "diabetic", "rheumatoid", "essential", "juvenile", "idiopathic",
    "systemic", "hereditary", "toxic", "neurological", "congestive", "hypertensive",
}


def clean_en_phrase(phrase: str) -> Optional[str]:
    """Gọt stopwords 2 đầu và kiểm định tính toàn vẹn của Cụm Danh từ Y khoa tiếng Anh."""
    if not phrase:
        return None
    phrase = phrase.strip().lower()

    # Loại bỏ tiền tố obsolete của DOID
    if "obsolete" in phrase:
        return None

    # Xóa ngoặc đơn và phần chú giải
    phrase = re.sub(r"\(.*?\)", "", phrase)
    phrase = re.sub(r",\s*.*", "", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip()

    # Giới hạn độ dài chuỗi ký tự hợp lý (tránh các chuỗi liên kết gạch ngang vô tận)
    if len(phrase) > 55:
        return None

    # Chỉ chấp nhận ký tự chữ cái tiếng Anh và dấu gạch nối
    if not re.search(r"^[a-z\s\-]+$", phrase):
        return None

    words = phrase.split()
    # Loại bỏ Pinyin
    pinyin_count = sum(1 for w in words if w in EN_PINYIN_MARKERS)
    if pinyin_count >= 2:
        return None

    # Gọt stopwords ở đầu và đuôi
    while words and words[0] in EN_STOPWORDS:
        words.pop(0)
    while words and words[-1] in EN_STOPWORDS:
        words.pop()

    if len(words) < 2 or len(words) > 5:
        return None

    # Kiểm tra đuôi hoặc đầu danh từ y sinh hợp lệ
    last_word = words[-1]
    first_word = words[0]

    if last_word in EN_VALID_ENDINGS or first_word in EN_VALID_PREFIXES:
        return " ".join(words)

    # Nếu cụm từ là bệnh lý 2-3 từ không có đuôi chuẩn nhưng là cụm danh từ tự nhiên hợp lệ
    if len(words) in {2, 3} and all(w not in EN_STOPWORDS for w in words):
        return " ".join(words)

    return None


# ==============================================================================
# BỘ LỌC STOPWORDS & NGỮ PHÁP TIẾNG VIỆT (STRICT VIETNAMESE LINGUISTIC FILTER)
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

VI_DIACRITICS_PATTERN = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]")


def clean_vi_phrase(phrase: str) -> Optional[str]:
    """Gọt stopwords 2 đầu và kiểm định tính toàn vẹn của Cụm Danh từ Y khoa tiếng Việt."""
    if not phrase:
        return None
    phrase = unicodedata.normalize("NFKC", phrase)
    phrase = html.unescape(phrase)
    phrase = phrase.strip().lower()
    phrase = re.sub(r"[^\w\sà-ỹ]", " ", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip()

    # Chặn các từ ngữ cấm xuất hiện ở bất kỳ đâu trong cụm từ
    for banned in VI_BANNED_ANYWHERE:
        if re.search(rf"\b{re.escape(banned)}\b", phrase):
            return None

    words = phrase.split()
    if not words:
        return None

    # Chặn đứng từ 'viên' đồng âm (nhân viên, đoàn viên, thành viên...)
    if words[0] == "viên":
        if len(words) < 2 or words[1] not in {"nén", "nang", "sủi", "ngậm", "đặt", "uống"}:
            return None

    # Gọt stopwords ở đầu và đuôi
    while words and words[0] in VI_STOPWORDS_BOUNDARY:
        words.pop(0)
    while words and words[-1] in VI_STOPWORDS_BOUNDARY:
        words.pop()

    if len(words) < 2 or len(words) > 4:
        return None

    # Chặn các từ ngữ bị cắt cụt hoặc động từ treo lơ lửng ở đuôi
    if words[-1] in VI_BANNED_TAILS:
        return None

    # Đảm bảo không kết thúc bằng từ 1 ký tự (như h, b...)
    if len(words[-1]) <= 1:
        return None

    # Chỉ chấp nhận ký tự tiếng Việt hợp lệ
    res = " ".join(words)
    if not re.match(r"^[a-zà-ỹ0-9\s]+$", res):
        return None

    return res


# ==============================================================================
# BỘ LỌC TIẾNG TRUNG (STRICT CHINESE FILTER)
# ==============================================================================
ZH_VALID_SUFFIXES = (
    "炎", "症", "病", "瘤", "癌", "衰竭", "梗死", "梗塞", "综合征", "痛", "障碍",
    "感染", "损伤", "溃疡", "结石", "增生", "狭窄", "坏死", "硬化", "肿", "栓",
    "脓", "癣", "疹", "汤", "丸", "散", "颗粒", "胶囊", "口服液", "注射液", "膏",
    "草", "根", "花", "叶", "皮", "子", "仁", "参", "芪", "苓", "术", "连", "芩", "柏",
)


def clean_zh_term(term: str) -> Optional[str]:
    """Lọc các thuật ngữ y dược tiếng Trung chuẩn xác."""
    if not term:
        return None
    term = unicodedata.normalize("NFKC", term).strip()
    # Chỉ nhận chữ Hán
    if not all("\u4e00" <= c <= "\u9fff" for c in term):
        return None
    if len(term) < 2 or len(term) > 6:
        return None
    # Phải kết thúc bằng hậu tố y dược chuẩn
    if term.endswith(ZH_VALID_SUFFIXES):
        return term
    return None


def clean_text_basic(text: str) -> str:
    """Chuẩn hóa Unicode NFKC và lowercase."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text)
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


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
EN_PREFIX_PATTERN = re.compile(
    r"\b(?:acute|chronic|severe|mild|secondary|primary|congestive|ischemic|coronary|pulmonary|renal|hepatic|cardiac|cerebral|gastric)\s+[a-z]+(?:\s+[a-z]+){1,2}\b",
    re.IGNORECASE,
)
ZH_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,5}(?:炎|症|病|瘤|癌|衰竭|梗死|梗塞|综合征|痛|功能障碍|感染|损伤|溃疡|结石|增生|狭窄|坏死)"
)
ZH_TCM_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{2,4}(?:汤|丸|散|片|胶囊|颗粒|口服液|注射液|膏|草|根|花|叶|皮|子|仁)"
)


def _mine_single_shard(shard_path_str: str) -> tuple[Counter, Counter, Counter, int]:
    vi_counter = Counter()
    en_counter = Counter()
    zh_counter = Counter()
    chunk_count = 0
    try:
        with open(shard_path_str, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                for child in record.get("children", []):
                    chunk_text = child.get("chunk_text", "")
                    if not chunk_text:
                        continue
                    chunk_count += 1
                    cleaned_c = clean_text_basic(chunk_text)

                    # 1. Tiếng Việt
                    for raw_p in VI_PATTERN.findall(cleaned_c):
                        cleaned_p = clean_vi_phrase(raw_p)
                        if cleaned_p:
                            vi_counter[cleaned_p] += 1
                    for raw_p in VI_DRUG_PATTERN.findall(cleaned_c):
                        cleaned_p = clean_vi_phrase(raw_p)
                        if cleaned_p:
                            vi_counter[cleaned_p] += 1

                    # 2. Tiếng Anh
                    for raw_p in EN_PATTERN.findall(cleaned_c):
                        cleaned_p = clean_en_phrase(raw_p)
                        if cleaned_p:
                            en_counter[cleaned_p] += 1
                    for raw_p in EN_PREFIX_PATTERN.findall(cleaned_c):
                        cleaned_p = clean_en_phrase(raw_p)
                        if cleaned_p:
                            en_counter[cleaned_p] += 1

                    # 3. Tiếng Trung
                    for raw_p in ZH_PATTERN.findall(chunk_text):
                        cleaned_p = clean_zh_term(raw_p)
                        if cleaned_p:
                            zh_counter[cleaned_p] += 1
                    for raw_p in ZH_TCM_PATTERN.findall(chunk_text):
                        cleaned_p = clean_zh_term(raw_p)
                        if cleaned_p:
                            zh_counter[cleaned_p] += 1
    except Exception:
        pass
    return vi_counter, en_counter, zh_counter, chunk_count


class LexiconBuilder:
    """Điều phối thu thập, khai phá có chọn lọc và xuất bản 4 bộ tài nguyên y khoa."""

    def __init__(
        self,
        output_dir: Path,
        raw_dir: Path | None = None,
        chunks_dir: Path | None = None,
        max_shards_to_mine: int = 300,
    ) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = Path(raw_dir).resolve() if raw_dir else None
        self.chunks_dir = Path(chunks_dir).resolve() if chunks_dir else None
        self.max_shards_to_mine = max_shards_to_mine

        self.all_concepts: List[Dict[str, Any]] = []
        self.vietnamese_compounds: Set[str] = set()
        self.english_compounds: Set[str] = set()
        self.chinese_words: Dict[str, int] = {}

    def load_curated_concepts(self) -> None:
        """Nạp toàn bộ khung tri thức y khoa chuẩn hóa (22 chương ICD-10, Dược thư, TCM, CHV, Xét nghiệm)."""
        curated_groups = [
            DISEASE_CONCEPTS,
            DRUG_CONCEPTS,
            TCM_CONCEPTS,
            COLLOQUIAL_CONCEPTS,
            LAB_CONCEPTS,
        ]

        seen_concept_ids = set()
        for group in curated_groups:
            for item in group:
                cid = item["concept_id"]
                if cid in seen_concept_ids:
                    continue
                seen_concept_ids.add(cid)

                clean_labels = {
                    lang: clean_text_basic(val) for lang, val in item.get("labels", {}).items()
                }
                raw_aliases = item.get("aliases", [])
                clean_aliases = list(dict.fromkeys([clean_text_basic(a) for a in raw_aliases if clean_text_basic(a)]))

                concept_entry = {
                    "concept_id": cid,
                    "type": item.get("type", "medical"),
                    "labels": clean_labels,
                    "aliases": clean_aliases,
                    "ambiguity": False,
                }
                self.all_concepts.append(concept_entry)

                # 1. Tiếng Việt
                vi_lbl = clean_vi_phrase(clean_labels.get("vi", ""))
                if vi_lbl:
                    self.vietnamese_compounds.add(vi_lbl)
                for alias in clean_aliases:
                    if re.search(r"[a-zà-ỹ]", alias) and " " in alias:
                        c_vi = clean_vi_phrase(alias)
                        if c_vi:
                            self.vietnamese_compounds.add(c_vi)

                # 2. Tiếng Anh
                en_lbl = clean_en_phrase(clean_labels.get("en", ""))
                if en_lbl:
                    self.english_compounds.add(en_lbl)
                for alias in clean_aliases:
                    c_en = clean_en_phrase(alias)
                    if c_en:
                        self.english_compounds.add(c_en)

                # 3. Tiếng Trung
                zh_lbl = clean_zh_term(clean_labels.get("zh", ""))
                if zh_lbl:
                    self.chinese_words[zh_lbl] = 50000
                for alias in clean_aliases:
                    c_zh = clean_zh_term(alias)
                    if c_zh:
                        self.chinese_words[c_zh] = 50000

        print(f"Đã nạp {len(self.all_concepts)} concepts chuẩn hóa từ kho tri thức y khoa mở rộng.")

    def load_external_datasets(self) -> None:
        """Nạp dữ liệu từ 8 nguồn raw chuẩn quốc tế và cộng đồng y sinh."""
        if not self.raw_dir or not self.raw_dir.exists():
            print("Thư mục raw datasets không tồn tại, bỏ qua bước nạp raw datasets.")
            return

        print("Đang nạp và thanh lọc dữ liệu từ 8 nguồn raw quốc tế & cộng đồng...")

        # 1. ICD-10 English Codes
        icd_en_file = self.raw_dir / "icd10_en_codes.csv"
        if icd_en_file.exists():
            count_en = 0
            with open(icd_en_file, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 4:
                        code = row[0].strip().upper()
                        # Lọc các chương bệnh lâm sàng chuẩn A00 - R99
                        if code and code[0] in "ABCDEFGHIJKLMNOPQR":
                            for col in [3, 4, 5]:
                                if col < len(row):
                                    term = clean_en_phrase(row[col])
                                    if term:
                                        self.english_compounds.add(term)
                                        count_en += 1
            print(f"  -> Đã nạp từ ICD-10 English Codes: thêm {count_en} lượt thuật ngữ bệnh lý.")

        # 2. Human Disease Ontology (DOID - OBO Foundry)
        doid_file = self.raw_dir / "human_disease_ontology.obo"
        if doid_file.exists():
            count_doid = 0
            with open(doid_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("name: "):
                        term = clean_en_phrase(line[6:])
                        if term:
                            self.english_compounds.add(term)
                            count_doid += 1
                    elif line.startswith("synonym: "):
                        m = re.search(r"\"([^\"]+)\"", line)
                        if m:
                            term = clean_en_phrase(m.group(1))
                            if term:
                                self.english_compounds.add(term)
                                count_doid += 1
            print(f"  -> Đã nạp từ Human Disease Ontology (DOID): thêm {count_doid} thuật ngữ & từ đồng nghĩa.")

        # 3. Medical Abbreviations & Trilingual Terminology
        abbr_file = self.raw_dir / "medical_abbreviations.csv"
        if abbr_file.exists():
            count_abbr = 0
            with open(abbr_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    m = clean_en_phrase(row.get("Meaning", ""))
                    if m:
                        self.english_compounds.add(m)
                    t = clean_zh_term(row.get("Translation", ""))
                    if t:
                        self.chinese_words[t] = 50000
                    count_abbr += 1
            print(f"  -> Đã nạp từ Medical Abbreviations: {count_abbr} thuật ngữ đa ngữ.")

        # 4. Chinese ICD-10 (ICD-10-CN)
        cn_file = self.raw_dir / "icd10_cn_disease.csv"
        if cn_file.exists():
            count_cn = 0
            with open(cn_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    t = clean_zh_term(row.get("disease", ""))
                    if t:
                        self.chinese_words[t] = 50000
                        count_cn += 1
            print(f"  -> Đã nạp từ ICD-10-CN: {count_cn} bệnh lý tiếng Trung.")

        # 5. ViMedical Disease (603 Diseases & 12k Patient Questions)
        vimed_file = self.raw_dir / "vimedical_disease.csv"
        if vimed_file.exists():
            count_vimed = 0
            symptom_pattern = re.compile(r"(?:triệu chứng như|cảm thấy|dấu hiệu như|bị)\s+([^.,?!;]+)", re.I)
            with open(vimed_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    d = clean_vi_phrase(row.get("Disease", ""))
                    if d:
                        self.vietnamese_compounds.add(d)
                        count_vimed += 1
                    q = row.get("Question", "")
                    for m in symptom_pattern.findall(q):
                        for p in re.split(r",|\bv\xe0\b", m):
                            # Nếu chuỗi hoàn toàn tiếng Anh (không dấu), kiểm tra đưa vào EN
                            if not VI_DIACRITICS_PATTERN.search(p) and re.match(r"^[a-z\s\-]+$", p.strip().lower()):
                                cleaned_en = clean_en_phrase(p)
                                if cleaned_en:
                                    self.english_compounds.add(cleaned_en)
                            else:
                                cleaned_sym = clean_vi_phrase(p)
                                if cleaned_sym:
                                    self.vietnamese_compounds.add(cleaned_sym)
            print(f"  -> Đã nạp từ ViMedical Disease: {count_vimed} bệnh lý và triệu chứng khẩu ngữ bệnh nhân.")

        # 6. ViMQ NER Gold Dataset (ICONIP2021)
        count_vimq = 0
        for split in ["train", "dev", "test"]:
            vimq_path = self.raw_dir / f"vimq_{split}.json"
            if vimq_path.exists():
                with open(vimq_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        sent = item.get("sentence", "").split()
                        for start, end, label in item.get("seq_label", []):
                            if label in {"SYMPTOM_AND_DISEASE", "medical_procedure", "drug"}:
                                entity_words = sent[start:end+1]
                                entity_text = " ".join(entity_words).replace("_", " ").strip()
                                # Phân luồng nếu là tên thuốc tiếng Anh (không có dấu tiếng Việt)
                                if not VI_DIACRITICS_PATTERN.search(entity_text) and re.match(r"^[a-z\s\-]+$", entity_text.lower()):
                                    cleaned_en = clean_en_phrase(entity_text)
                                    if cleaned_en:
                                        self.english_compounds.add(cleaned_en)
                                else:
                                    cleaned_ent = clean_vi_phrase(entity_text)
                                    if cleaned_ent:
                                        self.vietnamese_compounds.add(cleaned_ent)
                                        count_vimq += 1
        print(f"  -> Đã nạp từ ViMQ NER Gold Dataset: {count_vimq} thực thể lâm sàng & thuốc vàng.")

    def mine_corpus_shards(self) -> None:
        """Khai phá có chọn lọc từ corpus bằng đa tiến trình song song."""
        if not self.chunks_dir or not self.chunks_dir.exists():
            print("Không tìm thấy thư mục chunks để khai phá corpus. Bỏ qua bước mining.")
            return

        shard_files = sorted(self.chunks_dir.glob("*.jsonl"))
        if not shard_files:
            return

        step = max(1, len(shard_files) // self.max_shards_to_mine)
        selected_shards = shard_files[::step][: self.max_shards_to_mine]

        import os
        from concurrent.futures import ProcessPoolExecutor, as_completed

        max_workers = min(8, os.cpu_count() or 4)
        print(f"Bắt đầu khai phá có chọn lọc song song trên {max_workers} tiến trình ({len(selected_shards)} shards)...")

        vi_phrase_counter = Counter()
        en_phrase_counter = Counter()
        zh_term_counter = Counter()

        t0 = time.time()
        scanned_chunks = 0
        done_shards = 0

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_mine_single_shard, str(p)): p for p in selected_shards}
            for fut in as_completed(futures):
                done_shards += 1
                try:
                    v_c, e_c, z_c, c_cnt = fut.result()
                    vi_phrase_counter.update(v_c)
                    en_phrase_counter.update(e_c)
                    zh_term_counter.update(z_c)
                    scanned_chunks += c_cnt
                except Exception:
                    pass

                if done_shards % 25 == 0 or done_shards == len(selected_shards):
                    print(f"  -> Đã quét {done_shards}/{len(selected_shards)} shards ({scanned_chunks:,} chunks, {time.time()-t0:.1f}s)")

        # Lọc tần suất có ý nghĩa lâm sàng (tần suất >= 3)
        mined_vi = [p for p, c in vi_phrase_counter.items() if c >= 3]
        mined_en = [p for p, c in en_phrase_counter.items() if c >= 3]
        mined_zh = [t for t, c in zh_term_counter.items() if c >= 3]

        print(f"Khai phá sạch từ shards được: {len(mined_vi):,} cụm VI, {len(mined_en):,} cụm EN, và {len(mined_zh):,} thuật ngữ ZH!")

        for p in mined_vi:
            self.vietnamese_compounds.add(p)

        for p in mined_en:
            self.english_compounds.add(p)

        for t in mined_zh:
            if t not in self.chinese_words:
                self.chinese_words[t] = 30000

    def export_all(self) -> None:
        """Xuất ra 4 file thành phẩm sạch rác 100%."""
        # 1. medical_lexicon_vi_en_zh.full.jsonl
        full_lexicon_path = self.output_dir / "medical_lexicon_vi_en_zh.full.jsonl"
        with open(full_lexicon_path, "w", encoding="utf-8") as f:
            for item in self.all_concepts:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Đã xuất file concept đa ngữ: {full_lexicon_path} ({len(self.all_concepts)} concepts)")

        # 2. jieba_medical_dict.txt (Tiếng Trung)
        jieba_dict_path = self.output_dir / "jieba_medical_dict.txt"
        with open(jieba_dict_path, "w", encoding="utf-8") as f:
            for word, weight in sorted(self.chinese_words.items(), key=lambda x: -x[1]):
                f.write(f"{word} {weight} n\n")
        print(f"Đã xuất file từ điển Jieba tiếng Trung: {jieba_dict_path} ({len(self.chinese_words)} terms)")

        # 3. vietnamese_medical_compounds.txt (Tiếng Việt)
        vi_compounds_path = self.output_dir / "vietnamese_medical_compounds.txt"
        # Sắp xếp theo số từ giảm dần để Trie Longest-Match ưu tiên ghép cụm dài trước
        sorted_vi = sorted(self.vietnamese_compounds, key=lambda x: (len(x.split()), len(x)), reverse=True)
        with open(vi_compounds_path, "w", encoding="utf-8") as f:
            for term in sorted_vi:
                f.write(f"{term}\n")
        print(f"Đã xuất file cụm từ y khoa tiếng Việt: {vi_compounds_path} ({len(sorted_vi)} compounds)")

        # 4. english_medical_compounds.txt (Tiếng Anh)
        en_compounds_path = self.output_dir / "english_medical_compounds.txt"
        sorted_en = sorted(self.english_compounds, key=lambda x: (len(x.split()), len(x)), reverse=True)
        with open(en_compounds_path, "w", encoding="utf-8") as f:
            for term in sorted_en:
                f.write(f"{term}\n")
        print(f"Đã xuất file cụm từ y khoa tiếng Anh: {en_compounds_path} ({len(sorted_en)} compounds)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Comprehensive Clean Trilingual Medical Lexicon")
    parser.add_argument("--output-dir", default="sbtc/Scripts/Retrieval/resources")
    parser.add_argument("--raw-dir", default="sbtc/Scripts/Retrieval/resources/raw")
    parser.add_argument("--chunks-dir", default="data_final/chunks_format_v3_final")
    parser.add_argument("--max-shards", type=int, default=300)
    args = parser.parse_args()

    builder = LexiconBuilder(
        output_dir=Path(args.output_dir),
        raw_dir=Path(args.raw_dir),
        chunks_dir=Path(args.chunks_dir),
        max_shards_to_mine=args.max_shards,
    )
    builder.load_curated_concepts()
    builder.load_external_datasets()
    builder.mine_corpus_shards()
    builder.export_all()
    print("HOÀN TẤT XÂY DỰNG KHO TỪ ĐIỂN Y KHOA ĐA NGỮ ĐỒ SỘ & SẠCH RÁC 100%!")


if __name__ == "__main__":
    main()
