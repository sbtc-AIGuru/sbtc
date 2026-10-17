"""Typing Protocols and OOP Contracts for BM25 Retrieval Component.

Theo SPEC-bm25-medical-multilingual.md Mục 11.
Tuân thủ nguyên tắc composition, tách biệt giao diện và triển khai thực tế.
"""

from __future__ import annotations

from typing import (
    Any,
    Iterable,
    Iterator,
    Mapping,
    Protocol,
    Sequence,
    Tuple,
)

from sbtc.Scripts.Retrieval.models import (
    AnalyzedQuery,
    OriginalChunk,
    QueryInput,
    SearchHit,
    SubmissionItem,
)


class TokenPipeline(Protocol):
    """Giao diện pipeline phân tích từ vựng cho một ngôn ngữ cụ thể."""

    @property
    def language(self) -> str:
        """Mã ngôn ngữ: 'vi', 'en', 'zh'."""
        ...

    def analyze(self, text: str) -> Mapping[str, str]:
        """Phân tích văn bản thành các trường tokenized.

        Returns:
            Mapping chứa các trường: 'contents', 'surface', 'medical_exact', 'concepts'.
            Các token trong mỗi trường được nối với nhau bằng đúng 1 khoảng trắng.
        """
        ...


class QueryBridge(Protocol):
    """Cầu nối mở rộng và chuẩn bị truy vấn đa ngữ."""

    def bridge(self, query: QueryInput) -> Sequence[AnalyzedQuery]:
        """Tạo danh sách các truy vấn đã phân tích (gốc, mở rộng thuật ngữ, dịch)."""
        ...


class SearchBackend(Protocol):
    """Giao diện kết nối tới engine tìm kiếm (Lucene/Pyserini)."""

    def search_batch(
        self,
        queries: Sequence[AnalyzedQuery],
        *,
        k_docs: int = 200,
        k_chunks: int = 1000,
    ) -> Mapping[str, Sequence[SearchHit]]:
        """Thực hiện tìm kiếm theo lô cho danh sách truy vấn đã phân tích."""
        ...

    def close(self) -> None:
        """Đóng các searcher và tài nguyên."""
        ...


class CandidateFusion(Protocol):
    """Dung hợp xếp hạng từ nhiều phân vùng index và biến thể truy vấn."""

    def fuse(
        self,
        runs: Mapping[str, Sequence[SearchHit]],
    ) -> Tuple[Sequence[SearchHit], Sequence[SearchHit]]:
        """Dung hợp các runs thành danh sách ứng viên (candidate_docs, candidate_chunks).

        Returns:
            Tuple gồm (fused_docs, fused_chunks) đã sắp xếp theo thứ tự ưu tiên.
        """
        ...


class OriginalTextStore(Protocol):
    """Kho lưu trữ và phục hồi chuỗi văn bản nguyên bản của chunk."""

    def get_many(self, chunk_ids: Sequence[str]) -> Mapping[str, OriginalChunk]:
        """Lấy danh sách chunk nguyên bản từ ID.

        Seek trực tiếp vào file nguồn mà không nạp toàn bộ văn bản vào RAM.
        """
        ...

    def close(self) -> None:
        """Đóng kết nối cơ sở dữ liệu con trỏ."""
        ...


class ResultSelector(Protocol):
    """Lựa chọn kết quả cuối cùng theo ngân sách tối ưu F2 cho BTC."""

    def select(
        self,
        query_id: int,
        candidate_docs: Sequence[SearchHit],
        candidate_chunks: Sequence[SearchHit],
        text_store: OriginalTextStore,
    ) -> SubmissionItem:
        """Chọn danh sách nộp bài (tối đa 20 docs, tối đa 40 chunks)."""
        ...


class QualityPolicy(Protocol):
    """Chính sách kiểm soát chất lượng dữ liệu đầu vào."""

    def evaluate_doc(self, record: Mapping[str, Any]) -> Tuple[bool, str]:
        """Đánh giá xem tài liệu có đủ điều kiện index không (eligible, reason)."""
        ...

    def evaluate_chunk(self, chunk_data: Mapping[str, Any]) -> Tuple[bool, str]:
        """Đánh giá xem chunk có đủ điều kiện index không (eligible, reason)."""
        ...
