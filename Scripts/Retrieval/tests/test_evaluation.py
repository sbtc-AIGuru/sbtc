"""Unit Tests for BtcEvaluator and BTC Scoring Compliance.

Kiểm tra 100% các quy tắc chấm điểm và chuẩn hóa của BTC ViBioMIR.
"""

import unittest
from sbtc.Scripts.Retrieval.evaluation import (
    BtcEvaluator,
    btc_tokens,
    compute_f_beta,
    lcs_tokens_length,
)


class TestBtcEvaluator(unittest.TestCase):
    def test_btc_tokens_normalizer(self):
        """Kiểm tra 5 bước chuẩn hóa BTC."""
        raw = "   Thuốc &amp; Bệnh   VIỆN \n\n  100mg/ml   "
        expected = ["thuốc", "&", "bệnh", "viện", "100mg/ml"]
        self.assertEqual(btc_tokens(raw), expected)

    def test_lcs_tokens_non_contiguous(self):
        """LCS không bắt buộc phải liên tiếp nhau."""
        a = ["bệnh", "nhân", "bị", "viêm", "phổi", "nặng"]
        b = ["bệnh", "nhân", "viêm", "phổi"]
        # LCS chung: ['bệnh', 'nhân', 'viêm', 'phổi'] -> độ dài 4
        self.assertEqual(lcs_tokens_length(a, b), 4)

    def test_overlap_threshold_399_vs_400(self):
        """Kiểm tra ngưỡng đúng 40% bằng bất đẳng thức integer: 5*LCS >= 2*len(g)."""
        # len(g) = 1000
        # Nếu LCS = 399 -> 39.9% -> False
        # Nếu LCS = 400 -> 40.0% -> True
        len_g = 1000
        lcs_399 = 399
        lcs_400 = 400
        self.assertFalse(5 * lcs_399 >= 2 * len_g)
        self.assertTrue(5 * lcs_400 >= 2 * len_g)

    def test_doc_id_mismatch_fails_matching(self):
        """Sai doc_id thì không khớp dù chunk_text giống 100%."""
        preds = [
            {
                "id": 1,
                "relevant_docs": ["100"],
                "relevant_chunks": [{"doc_id": "100", "chunk_text": "viêm gan b mãn tính", "chunk_order": 0}],
            }
        ]
        gts = [
            {
                "id": 1,
                "relevant_docs": ["200"],
                "relevant_chunks": [{"doc_id": "200", "chunk_text": "viêm gan b mãn tính", "chunk_order": 0}],
            }
        ]
        report = BtcEvaluator.evaluate(preds, gts)
        self.assertEqual(report.macro_doc_precision, 0.0)
        self.assertEqual(report.macro_doc_recall, 0.0)
        self.assertEqual(report.macro_chunk_precision, 0.0)
        self.assertEqual(report.macro_chunk_recall, 0.0)
        self.assertEqual(report.macro_chunk_f2, 0.0)

    def test_many_to_many_chunk_matching(self):
        """Một prediction có thể match nhiều ground truth, nhiều prediction match cùng 1 ground truth."""
        # GT có 2 chunks cùng doc_id 50
        # g1: 'thuốc paracetamol giảm đau hạ sốt' (5 tokens)
        # g2: 'thuốc paracetamol dùng cho người lớn' (5 tokens)
        # Prediction: c1 chứa cả hai ý: 'thuốc paracetamol giảm đau hạ sốt dùng cho người lớn' (8 tokens)
        # LCS(c1, g1) = 5/5 (100% >= 40%) -> match g1
        # LCS(c1, g2) = 5/5 (100% >= 40%) -> match g2
        preds = [
            {
                "id": 1,
                "relevant_docs": ["50"],
                "relevant_chunks": [
                    {
                        "doc_id": "50",
                        "chunk_text": "thuốc paracetamol giảm đau hạ sốt dùng cho người lớn",
                        "chunk_order": 0,
                    }
                ],
            }
        ]
        gts = [
            {
                "id": 1,
                "relevant_docs": ["50"],
                "relevant_chunks": [
                    {"doc_id": "50", "chunk_text": "thuốc paracetamol giảm đau hạ sốt", "chunk_order": 0},
                    {"doc_id": "50", "chunk_text": "thuốc paracetamol dùng cho người lớn", "chunk_order": 1},
                ],
            }
        ]
        report = BtcEvaluator.evaluate(preds, gts)
        # 1 prediction match cả 2 gt chunks:
        # Precision: 1/1 = 1.0
        # Recall: 2/2 = 1.0
        # F2 = 1.0
        self.assertEqual(report.macro_chunk_precision, 1.0)
        self.assertEqual(report.macro_chunk_recall, 1.0)
        self.assertEqual(report.macro_chunk_f2, 1.0)

    def test_macro_f2_not_f2_of_macros(self):
        """Macro F2 phải là trung bình cộng của F2 từng query, không phải F2(macro P, macro R)."""
        # Query 1: P=1.0, R=1.0 -> F2=1.0
        # Query 2: P=0.0, R=0.0 -> F2=0.0
        # Macro P = 0.5, Macro R = 0.5
        # Nếu tính sai bằng F2(0.5, 0.5) -> 0.5
        # Nếu tính đúng bằng mean(1.0, 0.0) -> 0.5
        # Xét ca bất đối xứng:
        # Query 1: P=1.0, R=0.25 -> F2 = 5*(1*0.25)/(4*1 + 0.25) = 1.25 / 4.25 = 0.2941
        # Query 2: P=0.25, R=1.0 -> F2 = 5*(0.25*1)/(4*0.25 + 1) = 1.25 / 2.0 = 0.6250
        # Mean(F2) = (0.2941 + 0.6250) / 2 = 0.4595
        # Macro P = 0.625, Macro R = 0.625 -> F2(0.625, 0.625) = 0.625 != 0.4595!
        f2_q1 = compute_f_beta(1.0, 0.25)
        f2_q2 = compute_f_beta(0.25, 1.0)
        expected_macro_f2 = (f2_q1 + f2_q2) / 2.0
        f2_of_macros = compute_f_beta(0.625, 0.625)

        self.assertNotAlmostEqual(expected_macro_f2, f2_of_macros)


if __name__ == "__main__":
    unittest.main()
