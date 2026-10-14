"""Quality Policy and Data Audit for BM25 Retrieval.

Theo SPEC-bm25-medical-multilingual.md Mục 3, Mục 8.3, và Mục 17.
Kiểm soát tính hợp lệ của document và chunk, chặn các lỗi dữ liệu nghiêm trọng.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from sbtc.Scripts.Retrieval.config import QualityPolicyConfig


class QualityPolicy:
    """Đánh giá điều kiện lập chỉ mục của tài liệu và đoạn văn bản."""

    def __init__(self, config: QualityPolicyConfig) -> None:
        self.config = config
        self.stats = {
            "total_docs_seen": 0,
            "eligible_docs": 0,
            "ineligible_docs": 0,
            "total_chunks_seen": 0,
            "eligible_chunks": 0,
            "ineligible_chunks": 0,
            "uncertain_format_warnings": 0,
            "oversized_unresolved_blocks": 0,
        }

    def evaluate_doc(self, record: Mapping[str, Any]) -> Tuple[bool, str]:
        """Đánh giá tài liệu có đủ điều kiện index không."""
        self.stats["total_docs_seen"] += 1

        # 1. Kiểm tra trạng thái status
        status = record.get("status")
        if status != "ok":
            self.stats["ineligible_docs"] += 1
            return False, f"Document status is '{status}' (not 'ok')"

        # 2. Kiểm tra danh sách children chunks
        children = record.get("children", [])
        if not children:
            self.stats["ineligible_docs"] += 1
            return False, "Document has no child chunks"

        # 3. Cảnh báo uncertain_format (không loại bỏ dữ liệu)
        warnings = record.get("warnings", [])
        if "uncertain_format" in warnings:
            self.stats["uncertain_format_warnings"] += 1

        self.stats["eligible_docs"] += 1
        return True, "Eligible"

    def evaluate_chunk(self, chunk_data: Mapping[str, Any]) -> Tuple[bool, str]:
        """Đánh giá child chunk có đủ điều kiện index không."""
        self.stats["total_chunks_seen"] += 1

        # 1. Kiểm tra cờ retrieval_eligible
        if chunk_data.get("retrieval_eligible") is False:
            self.stats["ineligible_chunks"] += 1
            return False, "retrieval_eligible is False"

        # 2. Kiểm tra văn bản chunk_text
        text = chunk_data.get("chunk_text", "").strip()
        if not text:
            self.stats["ineligible_chunks"] += 1
            return False, "chunk_text is empty"

        # 3. Kiểm tra oversized unresolved
        if self.config.block_on_oversized_unresolved:
            if chunk_data.get("unresolved") is True or chunk_data.get("quality_state") == "unresolved":
                self.stats["oversized_unresolved_blocks"] += 1
                return False, "Oversized unresolved chunk (Release Blocker)"

        self.stats["eligible_chunks"] += 1
        return True, "Eligible"
