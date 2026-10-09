"""Manage reusable SQLAlchemy sessions and atomic document/chunk inserts."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from sqlalchemy import create_engine, insert, select
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import selectinload, sessionmaker

from .adapter import chunk_to_record, document_to_record, document_to_rows
from .models import Base, Chunk, Document
from dotenv import load_dotenv

load_dotenv()
INSERT_PAGE_SIZE = 1_000


class PostgreManager:
    """Manage Document and Chunk using the reference project's session pattern."""

    def __init__(
        self, database_url: str | URL | None = None, *,
        echo: bool = False, engine: Engine | None = None,
    ) -> None:
        if engine is None:
            resolved_url = database_url or os.getenv("DATABASE_URL")
            if not resolved_url:
                raise RuntimeError("Set DATABASE_URL or pass database_url explicitly")
            url = make_url(resolved_url)
            if url.drivername in {"postgresql", "postgres"}:
                url = url.set(drivername="postgresql+psycopg")
            if url.get_backend_name() != "postgresql":
                raise ValueError("DATABASE_URL must use PostgreSQL")
            engine = create_engine(url, echo=echo, pool_pre_ping=True)
        self.engine = engine
        self.session_factory = sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False,
        )

    def init_db(self) -> None:
        """Create missing tables; never drop or replace existing tables."""
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        """Release the engine's connection pool."""
        self.engine.dispose()

    def add_documents(self, records: Sequence[dict[str, Any]]) -> tuple[int, int]:
        """Insert a batch atomically; duplicate IDs raise and roll back the batch."""
        document_rows, chunk_rows = [], []
        doc_ids, chunk_ids = set(), set()
        for record in records:
            document_row, children = document_to_rows(record)
            doc_id = document_row["doc_id"]
            if doc_id in doc_ids:
                raise ValueError(f"Duplicate doc_id in batch: {doc_id}")
            doc_ids.add(doc_id)
            for child in children:
                if child["chunk_id"] in chunk_ids:
                    raise ValueError(f"Duplicate chunk_id in batch: {child['chunk_id']}")
                chunk_ids.add(child["chunk_id"])
            document_rows.append(document_row)
            chunk_rows.extend(children)
        if not document_rows:
            return 0, 0
        with self.session_factory.begin() as session:
            for model, rows in ((Document, document_rows), (Chunk, chunk_rows)):
                for offset in range(0, len(rows), INSERT_PAGE_SIZE):
                    session.execute(
                        insert(model), rows[offset:offset + INSERT_PAGE_SIZE],
                        execution_options={"render_nulls": True},
                    )
        return len(document_rows), len(chunk_rows)

    def add_document(self, record: dict[str, Any]) -> tuple[int, int]:
        """Insert one complete document and all its children atomically."""
        return self.add_documents([record])

    def get_document(self, doc_id: int) -> dict[str, Any] | None:
        """Return a lossless source-shaped record or None when not found."""
        with self.session_factory() as session:
            document = session.scalar(
                select(Document).where(Document.doc_id == doc_id)
                .options(selectinload(Document.chunks)),
            )
            return document_to_record(document) if document is not None else None

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Return one child chunk with all original fields."""
        with self.session_factory() as session:
            chunk = session.get(Chunk, chunk_id)
            return chunk_to_record(chunk) if chunk is not None else None

    def get_chunks_by_document(
        self, doc_id: int, *, limit: int = 100, offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Page through children in their original array order."""
        if limit <= 0 or offset < 0:
            raise ValueError("limit must be positive and offset must be nonnegative")
        with self.session_factory() as session:
            chunks = session.scalars(
                select(Chunk).where(Chunk.doc_id == doc_id)
                .order_by(Chunk.source_position).limit(limit).offset(offset),
            )
            return [chunk_to_record(chunk) for chunk in chunks]
