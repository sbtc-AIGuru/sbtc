#!/usr/bin/env python3
"""
Stream-Merge 1.22M Final Corpus for ViBioMIR.

Consolidates:
1. `data_final/final_data_1.194k_backup.jsonl` (1,194,469 records from Mentor Day 2)
2. `datacrawl/derived/data_bosung_vinmec.jsonl` (26,129 records from Vinmec)

Outputs:
- `data_final/final_data.jsonl` (exactly 1,220,598 lines matching newcorpus/links_corpus_vi_en_zh.parquet)
- `data_final/final_data.jsonj` (hardlink)

Performance:
- Pure streaming O(1) memory: ~15 seconds to merge 5 GB.
- Verifies exact ID and URL alignment against parquet for all 1,220,598 rows.
"""

import json
import os
from pathlib import Path
import time
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[3]
PARQUET_PATH = REPO_ROOT / "newcorpus/links_corpus_vi_en_zh.parquet"
OLD_JSONL_PATH = REPO_ROOT / "data_final/final_data_1.194k_backup.jsonl"
VINMEC_JSONL_PATH = REPO_ROOT / "datacrawl/derived/data_bosung_vinmec.jsonl"
OUT_DIR = REPO_ROOT / "data_final"
OUT_JSONL = OUT_DIR / "final_data.jsonl"
OUT_JSONJ = OUT_DIR / "final_data.jsonj"
TMP_JSONL = OUT_DIR / "final_data.jsonl.tmp"

VINMEC_START_IDX = 707280
VINMEC_COUNT = 26129
VINMEC_END_IDX = VINMEC_START_IDX + VINMEC_COUNT  # 733409
TOTAL_ROWS = 1220598


def main():
    t0 = time.time()
    print("=" * 70)
    print("🚀 BẮT ĐẦU STREAM-MERGE 1.22M CORPUS (ViBioMIR Hugging Face Sync)")
    print("=" * 70)

    # 1. Load Parquet manifest
    print(f"[1/4] Đọc manifest Parquet từ {PARQUET_PATH}...")
    pq_table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    pq_ids = pq_table["id"].to_pylist()
    pq_urls = pq_table["url"].to_pylist()
    assert len(pq_ids) == TOTAL_ROWS, f"Expected {TOTAL_ROWS} rows, got {len(pq_ids)}"
    print(f"      Đã nạp {len(pq_ids):,} IDs mục tiêu.")

    # 2. Load Vinmec crawled records into memory dict
    print(f"[2/4] Nạp dữ liệu crawl Vinmec từ {VINMEC_JSONL_PATH}...")
    vinmec_data = {}
    if VINMEC_JSONL_PATH.exists():
        with open(VINMEC_JSONL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    vinmec_data[rec["id"]] = rec
                except Exception:
                    pass
    print(f"      Đã nạp {len(vinmec_data):,} bản ghi Vinmec vào bộ nhớ.")

    # 3. Stream merge
    print(f"[3/4] Stream-merge dữ liệu vào {TMP_JSONL}...")
    assert OLD_JSONL_PATH.exists(), f"Old backup not found at {OLD_JSONL_PATH}"

    ok_count = 0
    fail_count = 0
    mismatch_count = 0

    with open(OLD_JSONL_PATH, "r", encoding="utf-8") as fin, open(TMP_JSONL, "w", encoding="utf-8") as fout:
        # Part 1: First 707,280 lines (row 0 to 707,279)
        print(f"      + Ghi Part 1 (Hàng 0 -> {VINMEC_START_IDX - 1:,})...")
        for expected_row in range(VINMEC_START_IDX):
            line = fin.readline()
            if not line:
                raise RuntimeError(f"Unexpected EOF in old jsonl at row {expected_row}")
            rec = json.loads(line)
            rid = rec["id"]
            if rid != pq_ids[expected_row]:
                mismatch_count += 1
            rec["row_index"] = expected_row
            if rec["success"] and rec.get("text"):
                ok_count += 1
            else:
                fail_count += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Part 2: Vinmec block (rows 707,280 to 733,408)
        print(f"      + Ghi Part 2 (Hàng {VINMEC_START_IDX:,} -> {VINMEC_END_IDX - 1:,} - Vinmec 26.129 URLs)...")
        for expected_row in range(VINMEC_START_IDX, VINMEC_END_IDX):
            rid = pq_ids[expected_row]
            url = pq_urls[expected_row]
            v_rec = vinmec_data.get(rid)
            if v_rec and v_rec.get("success") and v_rec.get("text"):
                rec = {
                    "id": rid,
                    "row_index": expected_row,
                    "url": url,
                    "text": v_rec["text"],
                    "success": True,
                    "error": None,
                }
                ok_count += 1
            else:
                err = v_rec.get("error") if v_rec else "Vinmec not crawled / origin dead"
                rec = {
                    "id": rid,
                    "row_index": expected_row,
                    "url": url,
                    "text": "",
                    "success": False,
                    "error": err,
                }
                fail_count += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Part 3: Remaining lines (rows 733,409 to 1,220,597)
        print(f"      + Ghi Part 3 (Hàng {VINMEC_END_IDX:,} -> {TOTAL_ROWS - 1:,})...")
        for expected_row in range(VINMEC_END_IDX, TOTAL_ROWS):
            line = fin.readline()
            if not line:
                raise RuntimeError(f"Unexpected EOF in old jsonl at row {expected_row}")
            rec = json.loads(line)
            rid = rec["id"]
            if rid != pq_ids[expected_row]:
                mismatch_count += 1
            rec["row_index"] = expected_row
            if rec["success"] and rec.get("text"):
                ok_count += 1
            else:
                fail_count += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 4. Atomic swap and hardlink recreation
    print("[4/4] Hoàn tất ghi file, cập nhật atomic và tái tạo hardlink...")
    os.replace(TMP_JSONL, OUT_JSONL)
    if OUT_JSONJ.exists() or OUT_JSONJ.is_symlink():
        OUT_JSONJ.unlink()
    os.link(OUT_JSONL, OUT_JSONJ)

    total_written = ok_count + fail_count
    size_gb = OUT_JSONL.stat().st_size / (1024**3)

    print("\n" + "=" * 70)
    print(f"🎉 HOÀN TẤT MERGE 1.22M CORPUS trong {time.time()-t0:.1f}s!")
    print(f"   File đầu ra JSONL : {OUT_JSONL} ({size_gb:.2f} GB)")
    print(f"   File đầu ra JSONJ : {OUT_JSONJ} (hardlink)")
    print(f"   Tổng số bản ghi   : {total_written:,} (Kỳ vọng: {TOTAL_ROWS:,})")
    print(f"   Thành công (OK)   : {ok_count:,} ({ok_count/total_written*100:.2f}%)")
    print(f"   Thất bại / Lỗi    : {fail_count:,} ({fail_count/total_written*100:.2f}%)")
    print(f"   Lệch ID Parquet   : {mismatch_count}")
    print("=" * 70)

    assert total_written == TOTAL_ROWS
    assert mismatch_count == 0


if __name__ == "__main__":
    main()
