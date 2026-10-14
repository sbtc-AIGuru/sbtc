"""Unit test kiểm chứng DrugDosageRecognizer 2 tầng bằng unittest."""

import tempfile
import unittest
from pathlib import Path

from sbtc.Scripts.Retrieval.drug_dosage import DrugDosageRecognizer


class TestDrugDosageRecognizer(unittest.TestCase):
    def test_tc01_basic_drug_and_dosage_vietnamese(self):
        """TC01: Nhận diện thuốc và liều lượng trong văn bản tiếng Việt."""
        recognizer = DrugDosageRecognizer(lexicon_path=None)
        text = "Bệnh nhân uống Paracetamol 500mg ngày 2 viên"
        res = recognizer.extract_drug_and_dosages(text)

        self.assertIn("paracetamol_500mg", res["bound_entities"])
        self.assertIn("500mg", res["dosages"])
        self.assertIn("2viên", res["dosages"])

    def test_tc02_cross_language_chinese_english(self):
        """TC02: Nhận diện thuốc tiếng Anh xen kẽ trong văn bản tiếng Trung."""
        recognizer = DrugDosageRecognizer(lexicon_path=None)
        text = "推荐使用 阿司匹林 Aspirin 100mg 治疗"
        res = recognizer.extract_drug_and_dosages(text)

        self.assertIn("aspirin_100mg", res["bound_entities"])
        self.assertIn("100mg", res["dosages"])

    def test_tc03_decimal_and_concentration_dosage(self):
        """TC03: Nhận diện liều lượng số thập phân và nồng độ."""
        recognizer = DrugDosageRecognizer(lexicon_path=None)
        text = "Tiêm truyền Glucose 5% và Morphin 10.5mg/ml"
        res = recognizer.extract_drug_and_dosages(text)

        self.assertIn("glucose_5%", res["bound_entities"])
        self.assertIn("morphin_10.5mg/ml", res["bound_entities"])

    def test_tc04_inn_stems_fallback(self):
        """TC04: Nhận diện thuốc qua hậu tố INN Stem khi chưa có trong từ điển."""
        recognizer = DrugDosageRecognizer(lexicon_path=None)
        text = "Sử dụng Esomeprazole 40mg trước bữa ăn"
        res = recognizer.extract_drug_and_dosages(text)

        self.assertIn("esomeprazole_40mg", res["bound_entities"])

    def test_tc05_blacklist_non_drugs(self):
        """TC05: Đảm bảo các địa danh, cơ quan không bị nhận nhầm thành thuốc."""
        recognizer = DrugDosageRecognizer(lexicon_path=None)
        text = "Bệnh nhân chuyển từ Hà Nội lên Bộ Y tế xét nghiệm"
        res = recognizer.extract_drug_and_dosages(text)

        self.assertFalse(any("hanoi" in d or "ha noi" in d for d in res["drugs"]))
        self.assertFalse(any("bo y te" in d for d in res["drugs"]))

    def test_tc06_file_lexicon_tier1(self):
        """TC06 & TC07: Nạp Tầng 1 qua file từ điển thuốc động."""
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as f:
            f.write("Panadol Extra\n")
            f.write("Berberin\n")
            f_path = f.name

        try:
            recognizer = DrugDosageRecognizer(lexicon_path=f_path)
            self.assertTrue(recognizer.has_file_lexicon)

            text = "Uống Panadol Extra 2 viên khi đau đầu"
            res = recognizer.extract_drug_and_dosages(text)
            self.assertTrue("panadol_extra_2viên" in res["bound_entities"] or "panadol_extra" in res["drugs"])
        finally:
            Path(f_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
