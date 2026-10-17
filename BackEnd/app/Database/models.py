"""PostgreSQL models covering every field in the merged chunk dataset."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, Float, ForeignKey,
    Integer, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_VALUE = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True), "postgresql",
)


class Base(DeclarativeBase):
    """Base class for the two database tables."""


class Document(Base):
    """A source document, including skipped documents and all parent metadata."""

    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint("source_length >= 0", name="document_source_length_check"),
        CheckConstraint("source_units >= 0", name="document_source_units_check"),
        CheckConstraint("input_line >= 0", name="document_input_line_check"),
        CheckConstraint(
            "structural_boundary_rate BETWEEN 0 AND 1",
            name="document_boundary_rate_check",
        ),
    )

    doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    parents: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VALUE, nullable=False)
    strategy: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(Text)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    classification_confidence: Mapped[str | None] = mapped_column(Text)
    raw_sha256: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(Text)
    source_length: Mapped[int | None] = mapped_column(BigInteger)
    source_units: Mapped[int | None] = mapped_column(BigInteger)
    excluded_spans: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_VALUE)
    coverage: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE)
    structural_boundary_rate: Mapped[float | None] = mapped_column(Float)
    input_line: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text)

    # Preserve unknown fields and distinguish missing keys from explicit JSON null.
    source_fields: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSON_VALUE, nullable=False, default=dict, server_default=text("'{}'"),
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", order_by="Chunk.source_position", lazy="raise",
    )


class Chunk(Base):
    """One child chunk; parent_id references an entry in Document.parents."""

    __tablename__ = "chunk"
    __table_args__ = (
        UniqueConstraint("doc_id", "source_position", name="chunk_document_position_key"),
        CheckConstraint("source_position >= 0", name="chunk_source_position_check"),
        CheckConstraint("chunk_order >= 0", name="chunk_order_check"),
        CheckConstraint("start_char >= 0", name="chunk_start_char_check"),
        CheckConstraint("end_char >= start_char", name="chunk_end_char_check"),
        CheckConstraint("unit_count >= 0", name="chunk_unit_count_check"),
        CheckConstraint("overlap_units >= 0", name="chunk_overlap_units_check"),
    )

    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.doc_id", ondelete="RESTRICT"), nullable=False,
    )
    parent_id: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    unit_count: Mapped[int | None] = mapped_column(BigInteger)
    oversized_reason: Mapped[str | None] = mapped_column(Text)
    boundary_type: Mapped[str | None] = mapped_column(Text)
    short_chunk_reason: Mapped[str | None] = mapped_column(Text)
    overlap_units: Mapped[int | None] = mapped_column(BigInteger)
    overlap_exception: Mapped[str | None] = mapped_column(Text)
    retrieval_eligible: Mapped[bool | None] = mapped_column(Boolean)

    source_position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fields: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSON_VALUE, nullable=False, default=dict, server_default=text("'{}'"),
    )
    document: Mapped[Document] = relationship(back_populates="chunks")
