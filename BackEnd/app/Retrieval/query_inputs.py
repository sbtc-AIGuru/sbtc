"""Restore text alongside the Qwen notebook's replacement-vector columns."""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .utils import sha_file

QWEN_CONFIG = {
    "model": "Qwen/Qwen3-Embedding-0.6B",
    "revision": "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    "dimension": 1024, "inference_dtype": "float16", "max_length": 4096,
    "normalized": True, "padding_side": "left", "pooling": "last_token",
    "query_instruction": "Given a web search query, retrieve relevant passages that answer the query",
    "storage_dtype": "float16",
}
TEXT_COLUMNS = ("query", "english", "chinese")
VECTOR_NAMES = ("vector_original", "vector_english", "vector_chinese")


def combine_query_files(embedding_path, text_path, output_path):
    """Stream paired rows after verifying the exact source file and every query ID."""
    output = Path(output_path)
    embedding_path, text_path = Path(embedding_path), Path(text_path)
    if output.exists():
        raise FileExistsError(f"Combined input already exists: {output}")
    with pq.ParquetFile(embedding_path) as embeddings, pq.ParquetFile(text_path) as texts:
        if any(name not in source.schema_arrow.names for source in (embeddings, texts)
               for name in ("id", *TEXT_COLUMNS)):
            raise ValueError("Both files require id/query/english/chinese columns")
        info = json.loads((embeddings.schema_arrow.metadata or {}).get(b"query_embedding", b"{}"))
        if info.get("encoder") != QWEN_CONFIG or info.get("replaced_columns") != list(TEXT_COLUMNS):
            raise ValueError("Expected Qwen3 1024 FP16 replacement-vector notebook output")
        if info.get("source_sha256") != sha_file(text_path):
            raise ValueError("Query text file differs from the embedding notebook's source_sha256")
        if embeddings.metadata.num_rows != texts.metadata.num_rows or info.get("rows") != texts.metadata.num_rows:
            raise ValueError("Query text/vector row counts differ")
        for name in TEXT_COLUMNS:
            if embeddings.schema_arrow.field(name).type != pa.list_(pa.float16(), 1024):
                raise ValueError(f"{name} must contain 1024 float16 values")
            if not (pa.types.is_string(texts.schema_arrow.field(name).type) or
                    pa.types.is_large_string(texts.schema_arrow.field(name).type)):
                raise ValueError(f"{name} must contain original query text")
        fields = [texts.schema_arrow.field(name) for name in ("id", *TEXT_COLUMNS)]
        fields += [pa.field(name, pa.list_(pa.float16(), 1024)) for name in VECTOR_NAMES]
        fields += [pa.field("query_sha256", pa.string())]
        has_weight = "dense_weight" in embeddings.schema_arrow.names
        if has_weight:
            fields.append(embeddings.schema_arrow.field("dense_weight"))
        schema = pa.schema(fields, metadata={b"query_embedding": json.dumps({
            "format_version": 1, "encoder": QWEN_CONFIG,
            "vector_columns": dict(zip(TEXT_COLUMNS, VECTOR_NAMES)),
            "source_sha256": info["source_sha256"],
            "embedding_sha256": sha_file(embedding_path),
        }).encode()})
        temporary = output.with_suffix(output.suffix + ".partial")
        try:
            with pq.ParquetWriter(temporary, schema) as writer:
                pairs = zip(embeddings.iter_batches(batch_size=64),
                            texts.iter_batches(batch_size=64, columns=["id", *TEXT_COLUMNS]), strict=True)
                for vector_batch, text_batch in pairs:
                    rows = []
                    for vector, text in zip(vector_batch.to_pylist(), text_batch.to_pylist(), strict=True):
                        if vector["id"] != text["id"]:
                            raise ValueError("Query ID/text/vector alignment mismatch")
                        content = json.dumps([text[name] for name in TEXT_COLUMNS], ensure_ascii=False, separators=(",", ":"))
                        row = {**text, **{name: vector[key] for key, name in zip(TEXT_COLUMNS, VECTOR_NAMES)},
                               "query_sha256": hashlib.sha256(content.encode()).hexdigest()}
                        if has_weight:
                            row["dense_weight"] = vector["dense_weight"]
                        rows.append(row)
                    writer.write_table(pa.Table.from_pylist(rows, schema=schema))
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return output
