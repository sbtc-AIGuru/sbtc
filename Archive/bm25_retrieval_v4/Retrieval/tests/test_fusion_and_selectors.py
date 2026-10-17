"""Unit Tests for CandidateFusion and FixedBudgetSelector.

Kiểm tra RRF k=60, tính toán điểm dung hợp hai luồng và chính sách chọn lọc tối ưu F2.
"""

import unittest
from sbtc.Scripts.Retrieval.config import BudgetConfig
from sbtc.Scripts.Retrieval.fusion import CandidateFusion
from sbtc.Scripts.Retrieval.models import OriginalChunk, SearchHit
from sbtc.Scripts.Retrieval.selectors import FixedBudgetSelector


class MockTextStore:
    """Mock TextStore cho unit test selector."""

    def __init__(self, chunks_map):
        self.chunks_map = chunks_map

    def get_many(self, chunk_ids):
        return {cid: self.chunks_map[cid] for cid in chunk_ids if cid in self.chunks_map}


class TestFusionAndSelectors(unittest.TestCase):
    def test_rrf_scoring_and_doc_from_chunk(self):
        """Kiểm tra công thức RRF và tổng hợp doc run từ chunk run."""
        fusion = CandidateFusion(rrf_k=60)

        # Chunk run: chunk '50_0' rank 1, chunk '60_0' rank 2
        chunk_runs = {
            "chunk_vi": [
                SearchHit("50_0", 50, "50_0", rank=1, score=10.0, run_id="c_vi"),
                SearchHit("60_0", 60, "60_0", rank=2, score=8.0, run_id="c_vi"),
            ]
        }
        # Doc run: doc 60 rank 1, doc 50 rank 2
        doc_runs = {
            "doc_vi": [
                SearchHit("60", 60, None, rank=1, score=12.0, run_id="d_vi"),
                SearchHit("50", 50, None, rank=2, score=11.0, run_id="d_vi"),
            ]
        }

        fused_docs, fused_chunks = fusion.fuse(doc_runs, chunk_runs)

        # Fused chunks phải có 50_0 và 60_0
        self.assertEqual(len(fused_chunks), 2)
        self.assertEqual(fused_chunks[0].chunk_id, "50_0")

        # Fused docs:
        # Doc 50 nhận RRF từ doc_vi (rank 2: 1/(60+2) = 1/62) và từ doc_from_chunks (rank 1: 1/(60+1) = 1/61)
        # Doc 60 nhận RRF từ doc_vi (rank 1: 1/61) và từ doc_from_chunks (rank 2: 1/62)
        # Cả 2 doc đều nhận tổng 1/61 + 1/62 = 0.0325
        self.assertEqual(len(fused_docs), 2)

    def test_fixed_budget_selector_per_doc_cap_and_overlap_penalty(self):
        """Kiểm tra per-doc cap tối đa 4 chunks và phạt overlap > 70%."""
        config = BudgetConfig(
            max_selected_docs=20,
            max_selected_chunks=40,
            max_chunks_per_doc=4,
            overlap_penalty_threshold=0.7,
        )
        selector = FixedBudgetSelector(config)

        # Giả lập doc 100 có 6 chunks được retrieve
        candidate_docs = [SearchHit("100", 100, None, 1, 10.0, "doc_run")]
        candidate_chunks = [
            SearchHit(f"100_{i}", 100, f"100_{i}", i + 1, 10.0 - i, "chunk_run") for i in range(6)
        ]

        # Chunk 0: [0, 100]
        # Chunk 1: [20, 90] -> overlap với Chunk 0 là (90 - 20) = 70 chars. Chunk 1 có len=70 -> overlap 100% > 70% -> Bị loại!
        # Chunk 2: [150, 250] -> Không overlap -> Chọn
        # Chunk 3: [300, 400] -> Không overlap -> Chọn
        # Chunk 4: [450, 550] -> Không overlap -> Chọn (đã đủ 4 chunks cho doc 100)
        # Chunk 5: [600, 700] -> Bị giới hạn bởi per-doc cap (max 4) -> Bị loại!
        mock_chunks = {
            "100_0": OriginalChunk("100_0", 100, 0, "Đoạn 0", "sha0", start_char=0, end_char=100),
            "100_1": OriginalChunk("100_1", 100, 1, "Đoạn 1 overlap", "sha1", start_char=20, end_char=90),
            "100_2": OriginalChunk("100_2", 100, 2, "Đoạn 2", "sha2", start_char=150, end_char=250),
            "100_3": OriginalChunk("100_3", 100, 3, "Đoạn 3", "sha3", start_char=300, end_char=400),
            "100_4": OriginalChunk("100_4", 100, 4, "Đoạn 4", "sha4", start_char=450, end_char=550),
            "100_5": OriginalChunk("100_5", 100, 5, "Đoạn 5", "sha5", start_char=600, end_char=700),
        }
        mock_store = MockTextStore(mock_chunks)

        submission_item = selector.select(
            query_id=1,
            candidate_docs=candidate_docs,
            candidate_chunks=candidate_chunks,
            text_store=mock_store,
        )

        self.assertEqual(len(submission_item.relevant_docs), 1)
        self.assertEqual(submission_item.relevant_docs[0], "100")

        # Số chunks được chọn phải đúng bằng 4 (bỏ qua 100_1 vì overlap và 100_5 vì per-doc cap)
        selected_cids = [c.chunk_order for c in submission_item.relevant_chunks]
        self.assertEqual(selected_cids, [0, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
