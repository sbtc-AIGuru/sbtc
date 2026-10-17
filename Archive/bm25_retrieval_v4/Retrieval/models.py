"""Core data models and DTOs for BM25 Retrieval Component.

Tuân thủ bất biến ViBioMIR và SPEC-bm25-medical-multilingual.md.
Tất cả DTOs là frozen dataclass để bảo đảm tính toàn vẹn (immutability).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class OriginalChunk:
    """Đoạn chunk nguyên bản được hydrate từ SourcePointerTextStore."""

    chunk_id: str
    doc_id: int
    chunk_order: int
    chunk_text: str
    chunk_text_sha256: str
    parent_id: str | None = None
    start_char: int = 0
    end_char: int = 0
    quality_state: str = "ok"

    def validate_hash(self) -> bool:
        """Kiểm tra tính toàn vẹn SHA256 của chunk_text."""
        import hashlib

        computed = hashlib.sha256(self.chunk_text.encode("utf-8")).hexdigest()
        return computed == self.chunk_text_sha256


@dataclass(frozen=True)
class ShardInfo:
    """Thông tin metadata của một shard file JSONL nguồn."""

    shard_id: int
    relative_path: str
    size_bytes: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class DocumentPointer:
    """Con trỏ vị trí byte-offset của một tài liệu trong file shard JSONL."""

    doc_id: int
    url: str
    source_sha256: str
    shard_id: int
    record_byte_offset: int
    record_byte_length: int
    record_sha256: str


@dataclass(frozen=True)
class SearchHit:
    """Một kết quả hit từ Lucene search backend."""

    external_id: str
    doc_id: int
    chunk_id: str | None
    rank: int
    score: float
    run_id: str
    granularity: str = "chunk"  # 'document' hoặc 'chunk'
    language: str = "vi"  # 'vi', 'en', 'zh'
    source_shard: str = ""


@dataclass(frozen=True)
class AnalyzedQuery:
    """Query đã qua phân tích và tokenization theo ngôn ngữ/variant."""

    query_id: int
    query_hash: str
    language: str  # 'vi', 'en', 'zh'
    variant_key: str  # 'original', 'alias_expanded', 'translated'
    tokens_map: Mapping[str, str] = field(default_factory=dict)
    # Ví dụ: {"contents": "ung_thư phổi", "surface": "ung thư phổi", "medical_exact": "..."}


@dataclass(frozen=True)
class PreparedRecord:
    """Record chuẩn bị ghi vào Staging JSONL cho Anserini indexer."""

    id: str
    contents: str
    title: str = ""
    section: str = ""
    surface: str = ""
    medical_exact: str = ""
    concepts: str = ""

    def to_dict(self) -> dict[str, str]:
        """Chuyển thành dict để ghi JSONL."""
        return {
            "id": self.id,
            "contents": self.contents,
            "title": self.title,
            "section": self.section,
            "surface": self.surface,
            "medical_exact": self.medical_exact,
            "concepts": self.concepts,
        }


@dataclass(frozen=True)
class SubmissionChunk:
    """Chunk xuất ra theo quy cách file nộp của BTC."""

    doc_id: str  # BTC quy định chuỗi doc_id
    chunk_text: str  # Chuỗi nguyên bản verbatim 100%
    chunk_order: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "chunk_text": self.chunk_text,
            "chunk_order": self.chunk_order,
        }


@dataclass(frozen=True)
class SubmissionItem:
    """Kết quả dự đoán cho một truy vấn duy nhất theo quy chuẩn BTC."""

    id: int  # Query ID
    relevant_docs: Sequence[str]  # Danh sách doc_id (string)
    relevant_chunks: Sequence[SubmissionChunk]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "relevant_docs": list(self.relevant_docs),
            "relevant_chunks": [c.to_dict() for c in self.relevant_chunks],
        }


@dataclass(frozen=True)
class QueryInput:
    """Truy vấn thô từ query.parquet."""

    id: int
    query: str
