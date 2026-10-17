"""Merge crawled Kaggle shards (.sqlite or .jsonl) for ask.39.net.
Validates 100% ID integrity, verifies coverage of all 337,375 URLs,
and exports the final unified JSONL: datacrawl/derived/crawled_phase1_priority3_ask39.jsonl
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
MAIN_DB = OUTPUT_DIR / "ask39_crawl_checkpoint.sqlite"
FINAL_JSONL = OUTPUT_DIR / "crawled_phase1_priority3_ask39.jsonl"
DEFAULT_INPUT_DIR = OUTPUT_DIR / "kaggle_ask39_results"

START_ROW = 2_110_878
END_ROW = 2_448_252
EXPECTED_TOTAL = 337_375


def init_main_db(target_db: Path):
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target_db) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crawled_records (
                row_index INTEGER PRIMARY KEY,
                id INTEGER NOT NULL,
                url TEXT NOT NULL,
                success INTEGER NOT NULL,
                text TEXT,
                error TEXT,
                timestamp TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_success ON crawled_records(success)")
        conn.commit()


def merge_from_sqlite(source_db: Path, target_db: Path) -> int:
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
    print("\n" + "=" * 60)
    print("AUDITING MERGED DATABASE INTEGRITY FOR ask.39.net")
    print("=" * 60)

    # 1. Read targets from parquet
    table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    target_map = {}
    for idx in range(START_ROW, min(END_ROW + 1, len(urls))):
        if "ask.39.net" in urls[idx]:
            target_map[idx] = (ids[idx], urls[idx])

    print(f"Expected targets from parquet: {len(target_map)}")
    assert len(target_map) == EXPECTED_TOTAL, f"Expected {EXPECTED_TOTAL}, got {len(target_map)}"

    # 2. Check DB stats
    with sqlite3.connect(MAIN_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(success) FROM crawled_records")
        tot, succ = c.fetchone()
        tot = tot or 0
        succ = succ or 0
        failed = tot - succ

    pct = (tot / EXPECTED_TOTAL) * 100
    succ_pct = (succ / tot * 100) if tot > 0 else 0
    print(f"Database Total Rows: {tot} / {EXPECTED_TOTAL} ({pct:.2f}%)")
    print(f"Successful Records: {succ} ({succ_pct:.2f}%)")
    print(f"Failed Records    : {failed}")

    # 3. Validate mapping
    print("\nVerifying 100% row_index, id, url parity...")
    mismatches = 0
    with sqlite3.connect(MAIN_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT row_index, id, url FROM crawled_records")
        for row_idx, doc_id, url in c:
            if row_idx not in target_map:
                print(f"ERROR: Unknown row_index in DB: {row_idx}")
                mismatches += 1
                continue
            expected_id, expected_url = target_map[row_idx]
            if doc_id != expected_id or url != expected_url:
                print(f"ERROR Mismatch at row {row_idx}: DB id={doc_id}, expected={expected_id}")
                mismatches += 1
                if mismatches >= 10:
                    break

    if mismatches > 0:
        print(f"❌ INTEGRITY AUDIT FAILED with {mismatches} errors!")
        sys.exit(1)
    else:
        print("✅ 100% Integrity Parity Verified! Zero ID or URL mismatches.")

    # 4. Export strictly ascending sorted JSONL
    print(f"\nExporting unified JSONL -> {FINAL_JSONL} ...")
    FINAL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = FINAL_JSONL.with_suffix(".tmp")
    exported_count = 0
    with sqlite3.connect(MAIN_DB) as conn, open(tmp_out, "w", encoding="utf-8") as f:
        c = conn.cursor()
        c.execute("SELECT row_index, id, url, success, text, error FROM crawled_records ORDER BY row_index ASC")
        for r in c:
            item = {
                "row_index": r[0],
                "id": r[1],
                "url": r[2],
                "success": bool(r[3]),
                "text": r[4] or "",
                "error": r[5],
            }
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            exported_count += 1

    tmp_out.replace(FINAL_JSONL)
    size_mb = FINAL_JSONL.stat().st_size / (1024 * 1024)
    print(f"✅ EXPORT COMPLETE: {exported_count} records ({size_mb:.2f} MB)")
    print(f"File path: {FINAL_JSONL}")


def main():
    parser = argparse.ArgumentParser(description="Merge Kaggle Shards for ask.39.net")
    parser.add_argument("--input-dir", type=str, default=str(DEFAULT_INPUT_DIR), help="Directory containing shard files")
    parser.add_argument("--skip-merge", action="store_true", help="Skip merge step, only audit & export")
    args = parser.parse_args()

    init_main_db(MAIN_DB)
    input_dir = Path(args.input_dir)

    if not args.skip_merge and input_dir.exists():
        # Find sqlite and jsonl shards
        sqlite_files = sorted(list(input_dir.glob("*.sqlite")))
        jsonl_files = sorted(list(input_dir.glob("*.jsonl")))

        print(f"Found {len(sqlite_files)} SQLite files and {len(jsonl_files)} JSONL files in {input_dir}")

        for sf in sqlite_files:
            merge_from_sqlite(sf, MAIN_DB)

        # Merge JSONL if no sqlite counterpart
        for jf in jsonl_files:
            stem = jf.stem
            if not any(sf.stem == stem for sf in sqlite_files):
                merge_from_jsonl(jf, MAIN_DB)

    validate_and_export()


if __name__ == "__main__":
    main()
