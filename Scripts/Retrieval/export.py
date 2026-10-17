from __future__ import annotations

import html
import json
import os
import re
import unicodedata
import zipfile
from pathlib import Path

from .store import TextStore
from .utils import source_id


def btc_normalized(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(unicodedata.normalize("NFKC", text)).lower()).strip()


def export_submission(candidates: Path, output: Path, store: TextStore, expected_ids: set[int], *, docs: int, chunks: int, zip_path: Path | None = None):
    if docs < 0 or chunks < 0 or output.exists() or (zip_path and zip_path.exists()):
        raise ValueError("Invalid budgets or output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix+".partial")
    seen = set()
    with candidates.open() as source, temporary.open("w", encoding="utf-8") as target:
        target.write("[")
        for line in source:
            item = json.loads(line)
            identifier = source_id(item["id"])
            if identifier in seen or identifier not in expected_ids:
                raise ValueError("Duplicate or unexpected query ID")
            seen.add(identifier)
            doc_ids = list(dict.fromkeys(source_id(d["doc_id"]) for d in item["documents"]))[:docs]
            for doc in doc_ids:
                if not store.document_exists(doc):
                    raise ValueError("Predicted document missing source identity")
            texts, dedup = [], set()
            for chunk in item["chunks"]:
                if len(texts) >= chunks:
                    break
                text = store.get(chunk["chunk_id"])
                if int(text["doc_id"]) != chunk["doc_id"] or text["chunk_order"] != chunk["chunk_order"]:
                    raise ValueError("Candidate source mapping mismatch")
                key = (text["doc_id"], btc_normalized(text["chunk_text"]))
                if key not in dedup:
                    texts.append(text)
                    dedup.add(key)
            if len(seen) > 1:
                target.write(",\n")
            json.dump({"id": identifier, "relevant_docs": list(map(str, doc_ids)), "relevant_chunks": texts}, target, ensure_ascii=False)
        if seen != expected_ids:
            raise ValueError("Missing expected query IDs")
        target.write("]\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, output)
    if zip_path:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(output, arcname=output.name)
