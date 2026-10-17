"""Unit Tests for Configuration Loader and Data Models."""

import unittest
from pathlib import Path
from sbtc.Scripts.Retrieval.config import BM25Config
from sbtc.Scripts.Retrieval.models import OriginalChunk, SearchHit, SubmissionItem, SubmissionChunk


class TestModelsAndConfig(unittest.TestCase):
    def test_parse_bm25_test_toml(self):
        """Kiểm tra đọc file cấu hình bm25-test.toml."""
        config_path = Path(__file__).resolve().parent.parent / "configs" / "bm25-test.toml"
        self.assertTrue(config_path.is_file())

        config = BM25Config.from_toml(config_path)
        self.assertEqual(config.bm25_doc.k1, 1.2)
        self.assertEqual(config.bm25_doc.b, 0.75)
        self.assertEqual(config.boost_doc.title, 1.5)
        self.assertEqual(config.budgets.max_selected_docs, 5)
        self.assertEqual(config.budgets.max_selected_chunks, 10)
        self.assertEqual(config.budgets.max_chunks_per_doc, 2)
        self.assertTrue(config.budgets.adaptive_selector)
        self.assertEqual(config.quality.allow_uncertain_format, True)

    def test_original_chunk_hash_validation(self):
        """Kiểm tra xác thực hash SHA256 trên OriginalChunk."""
        text = "bệnh nhân viêm phổi cấp"
        import hashlib
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        chunk_ok = OriginalChunk("1_0", 1, 0, text, sha)
        self.assertTrue(chunk_ok.validate_hash())

        chunk_corrupt = OriginalChunk("1_0", 1, 0, text + " sửa đổi", sha)
        self.assertFalse(chunk_corrupt.validate_hash())

    def test_submission_item_to_dict(self):
        """Kiểm tra schema to_dict của SubmissionItem khớp định dạng BTC."""
        item = SubmissionItem(
            id=123,
            relevant_docs=["583", "684"],
            relevant_chunks=[
                SubmissionChunk(doc_id="583", chunk_text="Văn bản trích xuất...", chunk_order=0)
            ],
        )
        d = item.to_dict()
        self.assertEqual(d["id"], 123)
        self.assertEqual(d["relevant_docs"], ["583", "684"])
        self.assertEqual(len(d["relevant_chunks"]), 1)
        self.assertEqual(d["relevant_chunks"][0]["doc_id"], "583")
        self.assertEqual(d["relevant_chunks"][0]["chunk_order"], 0)


if __name__ == "__main__":
    unittest.main()
