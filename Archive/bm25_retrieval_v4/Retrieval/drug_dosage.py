"""DrugDosageRecognizer: Nhận diện Tên thuốc & Liều lượng Đa tầng.

Theo đặc tả kỹ thuật:
- Tầng 1 (File Lookup): Dò trong file từ điển thuốc (drug_lexicon.txt / drug_lexicon.json)
  qua cấu trúc Trie Longest-match. Hỗ trợ nạp động (hot-reload) khi người dùng cung cấp file.
- Tầng 2 (Heuristic Fallback): Thuật toán nhận biết tự động khi từ chưa có trong file:
  + Nhận biết từ Latinh/English xen kẽ giữa tiếng Việt / Trung (Code-switching).
  + Nhận biết hậu tố gốc thuốc quốc tế (INN Drug Stems: -cillin, -prazole, -statin, ...).
  + Nhận biết cấu trúc liều lượng & nồng độ (500mg, 10.5mg/ml, 100mcg, 2 viên, 5%, 10 iu, ...).
  + Khóa cặp thực thể Thuốc + Liều lượng (paracetamol_500mg, amoxicillin_500mg).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# Danh sách hậu tố dược lý chuẩn hóa quốc tế (INN Stems & phổ biến)
INN_DRUG_STEMS = (
    # Kháng sinh / Kháng khuẩn
    "cillin", "mycin", "cycline", "floxacin", "penem", "cephin", "cef",
    # Tiêu hóa / Dạ dày
    "prazole", "tidine", "setron",
    # Tim mạch / Huyết áp
    "statin", "sartan", "pril", "dipine", "olol", "zosin", "artan",
    # Kháng viêm / Kháng histamine / Dị ứng
    "fenac", "profene", "profen", "coxib", "iramine", "tadine",
    # Corticosteroid
    "sone", "solone", "onide",
    # Sinh học / Miễn dịch
    "mab", "nib", "cept",
    # Kháng virus
    "vir", "vudine", "navir",
    # Giảm đau / Gây tê / Thuần hóa
    "caine", "adol", "codone", "fentanil",
    # Hạ đường huyết
    "gliptin", "glitazone", "gliflozin", "glutide",
    # Kháng nấm
    "conazole", "fungin",
    # Giãn phế quản
    "terol", "tropium",
)

# Danh sách từ ngoại lệ không phải thuốc (Blacklist: địa danh, cơ quan, từ thường viết hoa)
NON_DRUG_BLACKLIST = {
    "ha noi", "hanoi", "ho chi minh", "hcm", "da nang", "viet nam", "vietnam",
    "bo y te", "who", "fda", "cdc", "covid-19", "covid19", "sars-cov-2", "sarscov2",
    "benh vien", "khoa", "bac si", "benh nhan", "y te", "trung tam",
    "nam", "nu", "tuoi", "ngay", "thang", "tuan", "gio", "phut",
    "fever", "pain", "hospital", "doctor", "patient", "health",
}

# Regex nhận diện liều lượng và đơn vị y tế
# Hỗ trợ: 500mg, 500 mg, 10.5mg/ml, 10,5ml, 20mcg, 2 viên, 10 iu, 5%, 20mcg/kg/phút
DOSAGE_PATTERN = re.compile(
    r"\b(\d+(?:[\.,]\d+)?)\s*"
    r"(mg|mcg|µg|ug|g|kg|ml|l|iu|ui|%|viên|vien|ống|ong|gói|goi|giọt|giot|chai|bình)"
    r"(?:\s*/\s*(?:kg|ml|l|ngày|ngay|lần|lan|giờ|gio|phút|phut))*"
    r"(?=\s|[.,;!?:\)\]]|$)",
    re.IGNORECASE,
)


class TrieNode:
    """Node trong cây tiền tố cho Tầng 1 (File Lookup)."""

    def __init__(self) -> None:
        self.children: Dict[str, TrieNode] = {}
        self.is_end: bool = False
        self.canonical_name: str = ""


class DrugDosageRecognizer:
    """Bộ nhận diện Tên thuốc & Liều lượng Đa tầng."""

    def __init__(self, lexicon_path: Optional[str | Path] = None) -> None:
        self.lexicon_path = Path(lexicon_path).resolve() if lexicon_path else None
        self.trie_root = TrieNode()
        self.has_file_lexicon = False
        self._load_lexicon()

    def _load_lexicon(self) -> None:
        """Tầng 1: Nạp danh mục thuốc từ file (nếu có)."""
        self.trie_root = TrieNode()
        self.has_file_lexicon = False

        if not self.lexicon_path or not self.lexicon_path.is_file():
            return

        count = 0
        try:
            with open(self.lexicon_path, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if not name or name.startswith("#"):
                        continue
                    self._insert_to_trie(name.lower())
                    count += 1
            if count > 0:
                self.has_file_lexicon = True
        except Exception:
            self.has_file_lexicon = False

    def reload_lexicon(self, new_path: Optional[str | Path] = None) -> None:
        """Hỗ trợ cập nhật nạp lại file từ điển động."""
        if new_path:
            self.lexicon_path = Path(new_path).resolve()
        self._load_lexicon()

    def _insert_to_trie(self, phrase: str) -> None:
        curr = self.trie_root
        for ch in phrase:
            if ch not in curr.children:
                curr.children[ch] = TrieNode()
            curr = curr.children[ch]
        curr.is_end = True
        curr.canonical_name = phrase

    def _match_trie_at(self, text_lower: str, start_idx: int) -> Optional[Tuple[str, int]]:
        """So khớp cụm từ dài nhất trong Trie bắt đầu từ start_idx."""
        curr = self.trie_root
        longest_match = None
        longest_end = -1
        n = len(text_lower)

        for i in range(start_idx, n):
            ch = text_lower[i]
            if ch not in curr.children:
                break
            curr = curr.children[ch]
            if curr.is_end:
                longest_match = curr.canonical_name
                longest_end = i + 1

        if longest_match and longest_end != -1:
            return longest_match, longest_end
        return None

    def is_likely_drug_token(self, token: str, language: str = "vi") -> bool:
        """Thuật toán Tầng 2: Kiểm tra một token có đặc điểm là tên thuốc/hoạt chất."""
        clean = token.strip(".,;:!?()[]{}\"'").lower()
        if not clean or len(clean) < 3:
            return False

        # Kiểm tra Blacklist
        if clean in NON_DRUG_BLACKLIST:
            return False

        # Bỏ qua nếu toàn là số
        if clean.isdigit():
            return False

        # 1. Kiểm tra hậu tố INN Stems (áp dụng cho mọi ngôn ngữ)
        for stem in INN_DRUG_STEMS:
            if clean.endswith(stem) and len(clean) >= len(stem) + 2:
                return True

        # 2. Kiểm tra từ Latinh đặc thù y khoa xen kẽ (Code-switching)
        # Chỉ áp dụng khi văn bản nguồn là tiếng Việt hoặc tiếng Trung
        if language in ["vi", "zh"]:
            if re.match(r"^[a-zA-Z]{4,}$", token.strip(".,;:!?()[]{}")):
                return True

        return False

    def extract_drug_and_dosages(self, text: str, language: str = "vi") -> Dict[str, List[str]]:
        """Trích xuất tên thuốc, liều lượng và cặp (thuốc + liều lượng)."""
        if not text:
            return {"drugs": [], "dosages": [], "bound_entities": []}

        norm_text = unicodedata.normalize("NFKC", text)
        text_lower = norm_text.lower()
        n = len(text_lower)

        drugs_found: List[Tuple[int, int, str]] = []  # (start, end, drug_name)

        # -------------------------------------------------------------
        # 1. Trích xuất Tên thuốc
        # -------------------------------------------------------------
        if self.has_file_lexicon:
            # Ưu tiên Tầng 1: Tra cứu Trie từ File
            i = 0
            while i < n:
                match = self._match_trie_at(text_lower, i)
                if match:
                    name, end_idx = match
                    drugs_found.append((i, end_idx, name))
                    i = end_idx
                else:
                    i += 1

        # Tầng 2: Thuật toán Heuristic (cho những đoạn chưa được bắt bởi Tầng 1)
        token_matches = list(re.finditer(r"\b[a-zA-Z0-9\-_+/]+\b", norm_text))
        for m in token_matches:
            tok = m.group()
            s, e = m.start(), m.end()
            already_covered = any(ds <= s and e <= de for ds, de, _ in drugs_found)
            if not already_covered and self.is_likely_drug_token(tok, language=language):
                drugs_found.append((s, e, tok.lower()))

        # Sắp xếp drugs theo thứ tự xuất hiện
        drugs_found.sort(key=lambda x: x[0])

        # -------------------------------------------------------------
        # 2. Trích xuất Liều lượng
        # -------------------------------------------------------------
        dosages_found: List[Tuple[int, int, str]] = []  # (start, end, normalized_dosage)
        for m in DOSAGE_PATTERN.finditer(norm_text):
            raw_match = m.group(0)
            # Chuẩn hóa liều lượng: xóa khoảng trắng, đổi dấu phẩy sang chấm
            clean_dosage = re.sub(r"\s+", "", raw_match).replace(",", ".").lower()
            dosages_found.append((m.start(), m.end(), clean_dosage))

        dosages_found.sort(key=lambda x: x[0])

        # -------------------------------------------------------------
        # 3. Khóa Cặp Thuốc + Liều lượng (Drug-Dosage Binding)
        # Nguyên tắc Nearest Non-Crossing: Thuốc đi với liều gần nhất sau nó,
        # và giữa thuốc và liều không được xen vào một thuốc khác.
        # -------------------------------------------------------------
        bound_entities: List[str] = []
        bound_drug_indices: Set[int] = set()
        bound_dosage_indices: Set[int] = set()

        for d_idx, (d_s, d_e, d_name) in enumerate(drugs_found):
            # Tìm dosage gần nhất nằm sau d_e
            best_dos_idx = None
            min_gap = 999999

            for dos_idx, (dos_s, dos_e, dos_val) in enumerate(dosages_found):
                if dos_idx in bound_dosage_indices:
                    continue
                if dos_s >= d_e:
                    gap = dos_s - d_e
                    # Kiểm tra xem giữa d_e và dos_s có thuốc nào khác không
                    has_intervening_drug = any(
                        other_d_s >= d_e and other_d_s < dos_s
                        for other_idx, (other_d_s, _, _) in enumerate(drugs_found)
                        if other_idx != d_idx
                    )
                    if not has_intervening_drug and gap <= 35:
                        gap_text = norm_text[d_e:dos_s].strip(" :;,-()")
                        if len(gap_text.split()) <= 4:
                            if gap < min_gap:
                                min_gap = gap
                                best_dos_idx = dos_idx

            if best_dos_idx is not None:
                dos_val = dosages_found[best_dos_idx][2]
                drug_slug = re.sub(r"\s+", "_", d_name.strip())
                bound_token = f"{drug_slug}_{dos_val}"
                bound_entities.append(bound_token)
                bound_drug_indices.add(d_idx)
                bound_dosage_indices.add(best_dos_idx)

        all_drugs = [re.sub(r"\s+", "_", item[2].strip()) for item in drugs_found]
        all_dosages = [item[2] for item in dosages_found]

        return {
            "drugs": all_drugs,
            "dosages": all_dosages,
            "bound_entities": bound_entities,
        }

    def process_text_tokens(self, text: str, language: str = "vi") -> Tuple[str, List[str]]:
        """Nhận diện thuốc & liều lượng, trả về (chuỗi token exact, danh sách token exact)."""
        extracted = self.extract_drug_and_dosages(text, language=language)
        exact_tokens: List[str] = []

        exact_tokens.extend(extracted["bound_entities"])
        exact_tokens.extend(extracted["dosages"])
        for drug in extracted["drugs"]:
            if not any(drug in bound for bound in extracted["bound_entities"]):
                exact_tokens.append(drug)

        seen = set()
        unique_exact: List[str] = []
        for tok in exact_tokens:
            if tok not in seen:
                seen.add(tok)
                unique_exact.append(tok)

        return " ".join(unique_exact), unique_exact
