"""Unit Tests for Tokenization Pipelines and Medical Lexicon.

Kiểm tra Underthesea, Jieba, chuẩn hóa và trích xuất thực thể y khoa.
"""

import unittest
from pathlib import Path

from sbtc.Scripts.Retrieval.analyzers import (
    ChinesePipeline,
    extract_medical_exact_tokens,
    normalize_medical_text,
)
from sbtc.Scripts.Retrieval.lexicon import MedicalLexicon


class TestAnalyzersAndLexicon(unittest.TestCase):
    def test_normalize_medical_text(self):
        """Kiểm tra NFKC, HTML unescape, lower, whitespace collapse."""
        raw = "Bệnh nhân &lt;b&gt;COVID-19&lt;/b&gt; có triệu chứng   SỐT CAO.  "
        expected = "bệnh nhân <b>covid-19</b> có triệu chứng sốt cao."
        self.assertEqual(normalize_medical_text(raw), expected)

    def test_extract_medical_exact_tokens(self):
        """Kiểm tra trích xuất biomarker, gene, liều lượng."""
        text = "bệnh nhân dùng liều 500mg paracetamol, nồng độ il-6 và cd4+ tăng cao sau sars-cov-2"
        tokens = extract_medical_exact_tokens(text)
        self.assertIn("500mg", tokens)
        self.assertIn("il-6", tokens)
        self.assertIn("cd4+", tokens)
        self.assertIn("sars-cov-2", tokens)

    def test_chinese_pipeline_jieba_and_bigrams(self):
        """Kiểm tra Jieba segmentation và CJK bigrams trong surface."""
        dict_path = Path(__file__).resolve().parent.parent / "resources" / "jieba_medical_dict.txt"
        pipeline = ChinesePipeline(user_dict_path=str(dict_path))
        text = "患者患有严重的肾衰竭和糖尿病"

        analysis = pipeline.analyze(text)
        # Contents phải chứa '肾衰竭' và '糖尿病'
        self.assertIn("肾衰竭", analysis["contents"])
        self.assertIn("糖尿病", analysis["contents"])

        # Surface phải chứa CJK bigrams
        self.assertIn("肾衰", analysis["surface"])
        self.assertIn("衰竭", analysis["surface"])

    def test_medical_lexicon_matching(self):
        """Kiểm tra nhận diện thực thể y khoa từ file sample JSONL."""
        sample_path = Path(__file__).resolve().parent.parent / "resources" / "medical_lexicon_vi_en_zh.sample.jsonl"
        lexicon = MedicalLexicon.from_jsonl(sample_path)

        query = "bệnh nhân bị suy thận giai đoạn cuối và đái tháo đường"
        concepts = lexicon.find_concepts(query)
        concept_ids = [c[1].concept_id for c in concepts]

        # Phải nhận diện được suy thận (Q12136) và đái tháo đường (Q12206)
        self.assertIn("Q12136", concept_ids)
        self.assertIn("Q12206", concept_ids)

        # Kiểm tra gợi ý bí danh / dịch cho query
        aliases = lexicon.get_aliases_for_query(query)
        self.assertTrue(len(aliases) > 0)


if __name__ == "__main__":
    unittest.main()
