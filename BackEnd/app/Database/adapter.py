"""Convert merged dataset records to SQL rows and restore their original fields."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import Chunk, Document

INTERNAL_FIELDS = {"source_fields", "extra_data", "source_position"}
DOCUMENT_FIELDS = {column.name for column in Document.__table__.columns} - INTERNAL_FIELDS
CHUNK_FIELDS = {column.name for column in Chunk.__table__.columns} - INTERNAL_FIELDS


def _row(record: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    return {
        **{key: deepcopy(record.get(key)) for key in fields},
        "source_fields": list(record),
        "extra_data": deepcopy({key: value for key, value in record.items() if key not in fields}),
    }


def document_to_rows(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate IDs and split a complete source record without filtering any data."""
    if not isinstance(record, dict):
        raise ValueError("A document must be a JSON object")
    doc_id = record.get("doc_id")
    if type(doc_id) is not int:
        raise ValueError("Document doc_id must be an integer")
    for key in ("url", "status"):
        if not isinstance(record.get(key), str):
            raise ValueError(f"Document {doc_id}: {key} must be a string")
    parents, children = record.get("parents"), record.get("children")
    if not isinstance(parents, list) or not isinstance(children, list):
        raise ValueError(f"Document {doc_id}: parents and children must be arrays")
    parent_ids = set()
    for parent in parents:
        if not isinstance(parent, dict) or not isinstance(parent.get("parent_id"), str):
            raise ValueError(f"Document {doc_id}: invalid parent metadata")
        if parent["parent_id"] in parent_ids:
            raise ValueError(f"Document {doc_id}: duplicate parent_id")
        parent_ids.add(parent["parent_id"])

    document_row = _row(
        {key: value for key, value in record.items() if key != "children"},
        DOCUMENT_FIELDS,
    )
    document_row["source_fields"] = list(record)
    chunk_rows = []
    chunk_ids = set()
    for position, child in enumerate(children):
        if not isinstance(child, dict) or child.get("doc_id") != doc_id:
            raise ValueError(f"Document {doc_id}: child doc_id does not match")
        for key in ("chunk_id", "parent_id", "chunk_text"):
            if not isinstance(child.get(key), str):
                raise ValueError(f"Document {doc_id}: child {key} must be a string")
        if not child["chunk_id"] or child["chunk_id"] in chunk_ids:
            raise ValueError(f"Document {doc_id}: empty or duplicate chunk_id")
        if child["parent_id"] not in parent_ids:
            raise ValueError(f"Document {doc_id}: child references an unknown parent_id")
        for key in ("chunk_order", "start_char", "end_char"):
            if type(child.get(key)) is not int or child[key] < 0:
                raise ValueError(f"Document {doc_id}: child {key} must be a nonnegative integer")
        if child["end_char"] < child["start_char"]:
            raise ValueError(f"Document {doc_id}: end_char precedes start_char")
        chunk_ids.add(child["chunk_id"])
        row = _row(child, CHUNK_FIELDS)
        row["source_position"] = position
        chunk_rows.append(row)
    return document_row, chunk_rows


def chunk_to_record(chunk: Chunk) -> dict[str, Any]:
    """Restore every original child field, including null and unknown values."""
    return {
        key: deepcopy(getattr(chunk, key) if key in CHUNK_FIELDS else chunk.extra_data[key])
        for key in chunk.source_fields
    }


def document_to_record(document: Document) -> dict[str, Any]:
    """Restore one original document with children in their source array order."""
    result = {}
    for key in document.source_fields:
        if key == "children":
            result[key] = [chunk_to_record(chunk) for chunk in document.chunks]
        elif key in DOCUMENT_FIELDS:
            result[key] = deepcopy(getattr(document, key))
        else:
            result[key] = deepcopy(document.extra_data[key])
    return result
