"""Merge crawled Kaggle shards (.sqlite or .jsonl) back into local SQLite checkpoint.
Validates 100% ID integrity, verifies coverage, and exports the final unified JSONL.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import sqlite3
import sys

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
OUTPUT_DIR = REPO_ROOT.parent / "datacrawl" / "derived"
MAIN_DB = OUTPUT_DIR / "zysj_crawl_checkpoint.sqlite"
FINAL_JSONL = OUTPUT_DIR / "crawled_phase1_priority2_zysjonline.jsonl"


def merge_from_sqlite(source_db: Path, target_db: Path) -> int:
    """Merge records from a shard SQLite into the main SQLite database."""
    print(f"Merging from SQLite DB: {source_db} ...")
    count = 0
    with sqlite3.connect(source_db) as s_conn, sqlite3.connect(target_db) as t_conn:
        s_cursor = s_conn.cursor()
        s_cursor.execute("SELECT row_index, id, url, success, text, error, timestamp FROM crawled_records")
        rows = s_cursor.fetchall()
        t_conn.executemany("""
            INSERT OR REPLACE INTO crawled_records (row_index, id, url, success, text, error, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)
        t_conn.commit()
        count = len(rows)
    print(f"  -> Merged {count} records from {source_db.name}")
    return count


def merge_from_jsonl(source_jsonl: Path, target_db: Path) -> int:
    """Merge records from a shard JSONL into the main SQLite database."""
    print(f"Merging from JSONL file: {source_jsonl} ...")
    count = 0
    batch = []
    with open(source_jsonl, "r", encoding="utf-8") as f, sqlite3.connect(target_db) as conn:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            row_idx = obj["row_index"]
            doc_id = obj["id"]
            url = obj["url"]
            success = 1 if obj.get("success") else 0
            text = obj.get("text", "")
            error = obj.get("error", "")
            timestamp = obj.get("timestamp", "")
            batch.append((row_idx, doc_id, url, success, text, error, timestamp))
            if len(batch) >= 1000:
                conn.executemany("""
                    INSERT OR REPLACE INTO crawled_records (row_index, id, url, success, text, error, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
                count += len(batch)
                batch = []
        if batch:
            conn.executemany("""
                INSERT OR REPLACE INTO crawled_records (row_index, id, url, success, text, error, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.commit()
            count += len(batch)
    print(f"  -> Merged {count} records from {source_jsonl.name}")
    return count


def validate_and_export():
    """Validate completeness and export final JSONL."""
    print("\n" + "=" * 60)
    print("AUDITING MERGED DATABASE INTEGRITY")
    print("=" * 60)

    # 1. Read targets from parquet
    table = pq.read_table(PARQUET_PATH)
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    target_indices = set()
    for idx in range(4_151_371, min(4_394_718, len(urls))):
        if "zysjonline.com" in urls[idx]:
            target_indices.add(idx)

    expected_total = len(target_indices)
    print(f"Expected total targets from parquet: {expected_total}")

    with sqlite3.connect(MAIN_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(success) FROM crawled_records")
        tot, succ = c.fetchone()
        tot = tot or 0
        succ = succ or 0
        fail = tot - succ

        print(f"Total in SQLite checkpoint: {tot}/{expected_total} ({tot/expected_total*100:.2f}%)")
        print(f"  - Successful articles:    {succ} ({succ/tot*100 if tot > 0 else 0:.2f}%)")
        print(f"  - Failed / 404 records:   {fail}")

        c.execute("SELECT row_index FROM crawled_records")
        db_indices = {r[0] for r in c.fetchall()}

    missing = target_indices - db_indices
    if missing:
        print(f"\nWARNING: Still missing {len(missing)} records from target set!")
        print(f"Sample missing row_indices: {list(missing)[:5]}")
    else:
        print("\nPERFECT: 100% of all target row_indices are accounted for in SQLite!")

    # 2. Export to final JSONL
    print(f"\nExporting to final output: {FINAL_JSONL} ...")
    FINAL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    exported = 0
    with sqlite3.connect(MAIN_DB) as conn, open(FINAL_JSONL, "w", encoding="utf-8") as f:
        cursor = conn.cursor()
        cursor.execute("SELECT row_index, id, url, success, text, error FROM crawled_records ORDER BY row_index ASC")
        for r_idx, d_id, u, s, t, e in cursor:
            obj = {
                "row_index": r_idx,
                "id": d_id,
                "url": u,
                "success": bool(s),
                "text": t if s else "",
                "error": e if not s else "",
            }
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            exported += 1

    print(f"Exported {exported} lines to {FINAL_JSONL} ({FINAL_JSONL.stat().st_size / 1024 / 1024:.2f} MB)")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Merge Kaggle shards into local SQLite")
    parser.add_argument("input_paths", nargs="*", help="Files or directory containing Kaggle shards (.sqlite or .jsonl)")
    args = parser.parse_args()

    paths_to_merge = []
    for p_str in args.input_paths:
        p = Path(p_str)
        if p.is_dir():
            paths_to_merge.extend(p.glob("*.sqlite"))
            paths_to_merge.extend(p.glob("*.jsonl"))
        elif p.is_file():
            paths_to_merge.append(p)
        else:
            for matched in glob.glob(p_str):
                paths_to_merge.append(Path(matched))

    if not paths_to_merge:
        # Default check in datacrawl/derived/kaggle_results
        default_dir = OUTPUT_DIR / "kaggle_results"
        if default_dir.exists():
            paths_to_merge.extend(default_dir.glob("*.sqlite"))
            paths_to_merge.extend(default_dir.glob("*.jsonl"))

    if paths_to_merge:
        print(f"Found {len(paths_to_merge)} shard files to merge:")
        for p in paths_to_merge:
            if p.suffix == ".sqlite" and p != MAIN_DB:
                merge_from_sqlite(p, MAIN_DB)
            elif p.suffix == ".jsonl" and p != FINAL_JSONL:
                merge_from_jsonl(p, MAIN_DB)
    else:
        print("No new shard files specified to merge. Running audit on existing DB...")

    validate_and_export()


if __name__ == "__main__":
    main()
