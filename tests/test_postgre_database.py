"""Lossless dataset persistence and transaction checks for the SQL database."""

from __future__ import annotations

from copy import deepcopy
from itertools import islice
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, CreateTable
from sqlalchemy.dialects import postgresql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from BackEnd.app.Database import Base, Chunk, Document, PostgreManager
from BackEnd.app.Database.adapter import document_to_rows
from BackEnd.app.Database.import_merged import import_documents, iter_merged_documents

BACKENDS = ["sqlite"] + (["postgresql"] if os.getenv("SBTC_TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def engine(request):
    """Use in-memory SQLite or a unique schema in an explicit test database."""
    if request.param == "sqlite":
        database_engine = create_engine("sqlite://")

        @event.listens_for(database_engine, "connect")
        def enable_foreign_keys(connection, connection_record):
            connection.execute("PRAGMA foreign_keys=ON")
    else:
        url = make_url(os.environ["SBTC_TEST_DATABASE_URL"])
        schema = f"sbtc_test_{uuid4().hex}"
        setup_engine = create_engine(url)
        try:
            with setup_engine.begin() as connection:
                connection.execute(CreateSchema(schema))
        finally:
            setup_engine.dispose()
        url = url.set(query={**url.query, "options": f"-csearch_path={schema}"})
        database_engine = create_engine(url)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.fixture
def manager(engine):
    database = PostgreManager(engine=engine)
    database.init_db()
    yield database
    database.close()


def sample_document(doc_id: int = 1) -> dict:
    """Represent every known dataset field, including nested and future fields."""
    return {
        "doc_id": doc_id,
        "url": f"https://example.com/{doc_id}",
        "status": "ok",
        "parents": [{
            "parent_id": f"{doc_id}:p:0", "start_char": 0, "end_char": 100,
            "block_type": "section", "unit_count": 40, "future_parent": [None, "中文"],
        }],
        "children": [
            {
                "chunk_id": f"{doc_id}:c:{order}", "parent_id": f"{doc_id}:p:0",
                "doc_id": doc_id, "chunk_order": order, "start_char": order * 20,
                "end_char": order * 20 + 10, "chunk_text": text,
                "unit_count": 10, "oversized_reason": None, "boundary_type": "paragraph",
                "short_chunk_reason": None, "overlap_units": 0,
                "overlap_exception": "document_start", "retrieval_eligible": eligible,
                "future_child": {"values": [True, None, "Tiếng Việt"]},
            }
            for order, text, eligible in [(1, "Tiếng Việt\n中文。", True), (0, "", False)]
        ],
        "strategy": "hybrid", "version": "paragraph-v3", "doc_type": "article",
        "classification_reason": "long_text", "classification_confidence": "medium",
        "raw_sha256": "a" * 64, "source_sha256": "b" * 64,
        "source_length": 100, "source_units": 40,
        "excluded_spans": [{"start_char": 70, "end_char": 80, "reason": "noise"}],
        "coverage": {"non_whitespace_total": 100, "non_whitespace_indexed": 90},
        "structural_boundary_rate": 1.0, "input_line": 1,
        "future_document": {"null": None, "list": [1, 2]},
        "extra_data": "a source key colliding with an internal column",
    }


def write_merged(path: Path, records: list[dict]) -> None:
    path.write_text("[\n" + ",\n".join(
        json.dumps(record, ensure_ascii=False) for record in records
    ) + "\n]\n", encoding="utf-8")


def test_only_two_tables_and_postgresql_jsonb():
    assert set(Base.metadata.tables) == {"document", "chunk"}
    ddl = str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))
    assert "parents JSONB NOT NULL" in ddl
    assert "coverage JSONB" in ddl
    assert "doc_id BIGSERIAL" not in ddl
    chunk_ddl = str(CreateTable(Chunk.__table__).compile(dialect=postgresql.dialect()))
    assert "FOREIGN KEY(doc_id) REFERENCES document (doc_id) ON DELETE RESTRICT" in chunk_ddl


def test_round_trip_preserves_all_fields_and_original_child_order(manager):
    record = sample_document()
    snapshot = deepcopy(record)
    assert manager.add_document(record) == (1, 2)
    assert record == snapshot
    assert manager.get_document(1) == record
    assert manager.get_chunk("1:c:1") == record["children"][0]
    assert manager.get_chunks_by_document(1, limit=1) == record["children"][:1]
    assert manager.get_chunks_by_document(1, offset=1) == record["children"][1:]


def test_skipped_document_and_explicit_null_are_not_lost(manager):
    skipped = {"doc_id": 2, "url": "https://example.com/failed", "status": "skipped",
               "parents": [], "children": [], "reason": "crawl_failed", "input_line": 2}
    null = {**skipped, "doc_id": 3, "strategy": None, "coverage": None}
    assert manager.add_documents([skipped, null]) == (2, 0)
    assert manager.get_document(2) == skipped
    assert "strategy" not in manager.get_document(2)
    assert manager.get_document(3) == null
    assert manager.get_chunks_by_document(2) == []


def test_duplicate_existing_id_rolls_back_entire_batch(manager):
    manager.add_document(sample_document(1))
    with pytest.raises(IntegrityError):
        manager.add_documents([sample_document(2), sample_document(1)])
    assert manager.get_document(2) is None
    assert manager.get_chunk("2:c:1") is None
    assert manager.get_document(1) == sample_document(1)


def test_duplicate_chunk_id_rolls_back_new_document(manager):
    manager.add_document(sample_document(1))
    new_document = sample_document(2)
    new_document["children"][0]["chunk_id"] = "1:c:1"
    with pytest.raises(IntegrityError):
        manager.add_document(new_document)
    assert manager.get_document(2) is None


def test_duplicate_batch_id_is_rejected_before_insert(manager):
    with pytest.raises(ValueError, match="Duplicate doc_id"):
        manager.add_documents([sample_document(1), sample_document(1)])
    assert manager.get_document(1) is None


@pytest.mark.parametrize("mutation, message", [
    (lambda d: d["children"][0].update(doc_id=999), "doc_id does not match"),
    (lambda d: d["children"][0].update(parent_id="unknown"), "unknown parent_id"),
    (lambda d: d["children"][0].update(start_char=-1), "nonnegative integer"),
    (lambda d: d["children"][0].update(end_char=0), "end_char precedes"),
    (lambda d: d["children"][0].update(chunk_text=None), "must be a string"),
])
def test_invalid_relationship_or_chunk_is_rejected(manager, mutation, message):
    record = sample_document()
    mutation(record)
    with pytest.raises(ValueError, match=message):
        manager.add_document(record)
    assert manager.get_document(1) is None


def test_database_foreign_key_and_check_constraints(engine, manager):
    document, chunks = document_to_rows(sample_document())
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(Chunk), chunks[0])
    with engine.begin() as connection:
        connection.execute(insert(Document), document)
    invalid = {**chunks[0], "start_char": -1}
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(Chunk), invalid)


def test_missing_records_and_empty_batch(manager):
    assert manager.add_documents([]) == (0, 0)
    assert manager.get_document(999) is None
    assert manager.get_chunk("unknown") is None
    assert manager.get_chunks_by_document(999) == []
    with pytest.raises(ValueError):
        manager.get_chunks_by_document(1, limit=0)


def test_streaming_import_batch_boundaries_and_limit(manager, tmp_path):
    records = [sample_document(i) for i in range(1, 5)]
    path = tmp_path / "merged.json"
    write_merged(path, records)
    assert list(iter_merged_documents(path)) == records
    assert import_documents(manager, path, batch_documents=2, max_batch_chunks=3, limit=3) == (3, 6)
    for record in records[:3]:
        assert manager.get_document(record["doc_id"]) == record
    assert manager.get_document(4) is None


def test_large_document_is_not_split_across_transactions(manager, tmp_path):
    path = tmp_path / "merged.json"
    record = sample_document()
    write_merged(path, [record])
    assert import_documents(manager, path, max_batch_chunks=1) == (1, 2)
    assert manager.get_document(1) == record


@pytest.mark.parametrize("contents", [
    "[\n{}\n", "[\n{},\n]\n", "[\n{}\n{}\n]\n", "[\n{}\n]\nextra",
    "[\nnot-json\n]\n", "[\n42\n]\n", "{}\n",
])
def test_malformed_input_is_rejected(tmp_path, contents):
    path = tmp_path / "merged.json"
    path.write_text(contents)
    with pytest.raises(ValueError):
        list(iter_merged_documents(path))


def test_reader_is_lazy(tmp_path):
    path = tmp_path / "merged.json"
    path.write_text('[\n{"doc_id":1},\nnot-json\n]\n')
    reader = iter_merged_documents(path)
    assert next(reader) == {"doc_id": 1}
    with pytest.raises(ValueError):
        next(reader)


def test_real_merged_records_round_trip(manager):
    path = PROJECT_ROOT / "data" / "merged.json"
    if not path.exists():
        pytest.skip("Local merged.json dataset is not available")
    records = list(islice(iter_merged_documents(path), 100))
    expected_chunks = sum(len(record["children"]) for record in records)
    assert manager.add_documents(records) == (len(records), expected_chunks)
    for record in records:
        assert manager.get_document(record["doc_id"]) == record


def test_postgresql_script_creates_matching_schema(engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("SQL script needs a PostgreSQL test server")
    script = (PROJECT_ROOT / "BackEnd/app/Database/postgre_script.sql").read_text()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(script)
    database = PostgreManager(engine=engine)
    database.init_db()
    record = sample_document()
    database.add_document(record)
    assert database.get_document(1) == record
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT pg_typeof(parents)::text FROM document WHERE doc_id=1",
        ).scalar_one() == "jsonb"


def test_database_url_required_and_no_connection_on_import(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        PostgreManager()
    with pytest.raises(ValueError, match="PostgreSQL"):
        PostgreManager("sqlite://")
    manager = PostgreManager("postgresql://USER:PASSWORD@localhost/DATABASE_NAME")
    try:
        assert manager.engine.url.drivername == "postgresql+psycopg"
    finally:
        manager.close()
