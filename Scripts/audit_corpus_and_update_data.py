"""Comprehensive Audit of Crawled Corpus & Updater for data.py.

Performs:
1. Verifies if datacrawl/dataraw_main fully covers datacrawl/derived.
2. Cross-references all crawled records against BTC's links_corpus.parquet (4,394,718 rows).
3. Validates 1-1 ID integrity: row_index -> BTC id.
4. Calculates exact Success, Fail, Missing, and Total Target counts and percentages.
5. Generates the updated data.py with ROW_IDS (0-indexed in links_corpus.parquet) for failed & uncrawled URLs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_PATH = REPO_ROOT / "sbtc" / "data" / "links_corpus.parquet"
DATARAW_DIR = REPO_ROOT / "datacrawl" / "dataraw_main"
DERIVED_DIR = REPO_ROOT / "datacrawl" / "derived"
DATA_PY_PATH = REPO_ROOT / "data.py"


def fast_parse_line(line: str) -> tuple[int | None, int | None, bool]:
    # Try fast string search
    r_pos = line.find('"row_index":')
    if r_pos == -1:
        r_pos = line.find('"row_id":')
    if r_pos != -1:
        # find end of number
        r_start = line.find(":", r_pos) + 1
        r_end = line.find(",", r_start)
        if r_end != -1:
            try:
                row_idx = int(line[r_start:r_end].strip())
            except ValueError:
                row_idx = None
        else:
            row_idx = None
    else:
        row_idx = None

    id_pos = line.find('"id":')
    if id_pos == -1:
        id_pos = line.find('"doc_id":')
    if id_pos != -1:
        id_start = line.find(":", id_pos) + 1
        id_end = line.find(",", id_start)
        if id_end != -1:
            try:
                doc_id = int(line[id_start:id_end].strip())
            except ValueError:
                doc_id = None
        else:
            doc_id = None
    else:
        doc_id = None

    succ_pos = line.rfind('"success":')
    if succ_pos != -1:
        chunk = line[succ_pos:succ_pos + 20].lower()
        succ = "true" in chunk
    else:
        succ = False

    if row_idx is not None and doc_id is not None:
        return row_idx, doc_id, succ

    # Fallback to json.loads
    try:
        item = json.loads(line)
        row_idx = item.get("row_index", item.get("row_id"))
        doc_id = item.get("id", item.get("doc_id"))
        succ = bool(item.get("success", False))
        return row_idx, doc_id, succ
    except Exception:
        return None, None, False


def main():
    print("=" * 70)
    print("🔍 BẮT ĐẦU KIỂM TOÁN DỮ LIỆU CRAWL & CẬP NHẬT data.py")
    print("=" * 70)

    # Step 1: Verify coverage between derived and dataraw_main
    print("\n--- [BƯỚC 1] KIỂM TRA ĐỘ BAO PHỦ: derived -> dataraw_main ---")
    derived_files = list(DERIVED_DIR.glob("*.jsonl"))
    print(f"Số tệp JSONL trong derived: {len(derived_files)}")
    all_derived_covered = True
    for df in derived_files:
        mf = DATARAW_DIR / df.name
        if not mf.exists():
            print(f"❌ THIẾU TỆP: {df.name} có trong derived nhưng KHÔNG CÓ trong dataraw_main!")
            all_derived_covered = False
        else:
            df_size = df.stat().st_size
            mf_size = mf.stat().st_size
            if df_size != mf_size:
                print(f"⚠️ LỆCH DUNG LƯỢNG: {df.name} (derived: {df_size} bytes != dataraw_main: {mf_size} bytes)")
                all_derived_covered = False
            else:
                print(f"✅ KHỚP 100%: {df.name} ({df_size / (1024*1024):.2f} MB)")

    if all_derived_covered:
        print("👉 KẾT LUẬN BƯỚC 1: dataraw_main ĐÃ BAO PHỦ 100% TOÀN BỘ dữ liệu crawl từ derived!")
    else:
        print("👉 CẢNH BÁO BƯỚC 1: Có sự sai lệch giữa derived và dataraw_main!")

    # Step 2: Load BTC Parquet
    print("\n--- [BƯỚC 2] TẢI CORPUS GỐC CỦA BAN TỔ CHỨC (links_corpus.parquet) ---")
    t0 = time.time()
    btc_table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    num_btc_rows = btc_table.num_rows
    btc_ids = btc_table["id"].to_numpy()
    print(f"Tổng số bản ghi BTC: {num_btc_rows:,} dòng (Row index từ 0 đến {num_btc_rows - 1:,})")
    print(f"Thời gian tải Parquet: {time.time() - t0:.2f}s")

    # Status array: 0 = NOT_CRAWLED, 1 = SUCCESS, 2 = FAILED
    status = np.zeros(num_btc_rows, dtype=np.uint8)
    id_mismatches = 0
    out_of_bounds = 0

    # Step 3: Process all JSONL files in dataraw_main
    print("\n--- [BƯỚC 3] QUÉT VÀ KIỂM ĐẾM TOÀN BỘ CÁC TỆP TRONG dataraw_main ---")
    jsonl_files = sorted(DATARAW_DIR.glob("*.jsonl"))

    total_scanned_lines = 0
    for jf in jsonl_files:
        t_file_start = time.time()
        file_lines = 0
        file_succ = 0
        file_fail = 0

        with open(jf, "r", encoding="utf-8") as f:
            for line in f:
                file_lines += 1
                row_idx, doc_id, succ = fast_parse_line(line)
                if row_idx is None:
                    continue

                if row_idx < 0 or row_idx >= num_btc_rows:
                    out_of_bounds += 1
                    continue

                if doc_id is not None and doc_id != btc_ids[row_idx]:
                    id_mismatches += 1

                if succ:
                    file_succ += 1
                    status[row_idx] = 1  # Mark SUCCESS
                else:
                    file_fail += 1
                    # Only mark FAILED if not already SUCCESS
                    if status[row_idx] != 1:
                        status[row_idx] = 2

        total_scanned_lines += file_lines
        elapsed = time.time() - t_file_start
        print(f"  • {jf.name:50} | {file_lines:>10,} dòng | Succ: {file_succ:>9,} | Fail: {file_fail:>7,} ({elapsed:.2f}s)")

    print(f"\nTổng số dòng đã quét qua toàn bộ các tệp: {total_scanned_lines:,}")
    print(f"Số lỗi lệch ID so với BTC: {id_mismatches}")
    print(f"Số dòng ngoài dải [0, {num_btc_rows - 1}]: {out_of_bounds}")

    # Step 4: Summary calculations
    print("\n--- [BƯỚC 4] TỔNG HỢP VÀ ĐỐI CHIẾU VỚI DATA BAN TỔ CHỨC ---")
    num_success = int(np.sum(status == 1))
    num_failed = int(np.sum(status == 2))
    num_missing = int(np.sum(status == 0))
    num_target = num_failed + num_missing  # Cần cào bù

    pct_success = (num_success / num_btc_rows) * 100
    pct_failed = (num_failed / num_btc_rows) * 100
    pct_missing = (num_missing / num_btc_rows) * 100
    pct_target = (num_target / num_btc_rows) * 100

    print("📊 BẢNG TỔNG HỢP TOÀN BỘ CORPUS (4.394.718 URLs BTC):")
    print("-" * 65)
    print(f"1. Tổng số URLs trong links_corpus.parquet : {num_btc_rows:>10,} (100.00%)")
    print(f"2. Đã cào THÀNH CÔNG (Success)             : {num_success:>10,} ({pct_success:>6.2f}%)")
    print(f"3. Đã chạy nhưng THẤT BẠI (Failed)         : {num_failed:>10,} ({pct_failed:>6.2f}%)")
    print(f"4. CHƯA CHẠY / CÒN THIẾU (Missing)         : {num_missing:>10,} ({pct_missing:>6.2f}%)")
    print("-" * 65)
    print(f"👉 TỔNG CẦN CHẠY BÙ (Failed + Missing)      : {num_target:>10,} ({pct_target:>6.2f}%)")
    print("-" * 65)

    # Step 5: Extract target row indices and update data.py
    print("\n--- [BƯỚC 5] TIẾN HÀNH CẬP NHẬT FILE data.py ---")
    # Finding all row indices that are failed or missing
    # To maintain natural order from 0 to num_btc_rows - 1:
    target_row_indices = np.where((status == 0) | (status == 2))[0]
    failed_row_indices = np.where(status == 2)[0]
    missing_row_indices = np.where(status == 0)[0]

    assert len(target_row_indices) == num_target

    print(f"Chuẩn bị ghi {len(target_row_indices):,} row_id vào {DATA_PY_PATH}...")
    t_write = time.time()

    with open(DATA_PY_PATH, "w", encoding="utf-8") as f:
        f.write(f'"""Danh sách row_id (0-indexed trong links_corpus.parquet) còn thiếu và fail\n')
        f.write(f'phục vụ crawl bù toàn diện theo quy chuẩn ViBioMIR.\n')
        f.write(f'Tổng số URL ban tổ chức: {num_btc_rows:,}\n')
        f.write(f'Thành công: {num_success:,} ({pct_success:.2f}%)\n')
        f.write(f'Thiếu chưa chạy: {num_missing:,} ({pct_missing:.2f}%)\n')
        f.write(f'Đã chạy bị lỗi: {num_failed:,} ({pct_failed:.2f}%)\n')
        f.write(f'Tổng cần chạy bù: {num_target:,} ({pct_target:.2f}%)\n')
        f.write(f'"""\n\n')

        f.write(f"TOTAL_BTC_COUNT = {num_btc_rows}\n")
        f.write(f"SUCCESS_COUNT = {num_success}\n")
        f.write(f"MISSING_COUNT = {num_missing}\n")
        f.write(f"FAILED_COUNT = {num_failed}\n")
        f.write(f"TOTAL_TARGET_COUNT = {num_target}\n\n")

        f.write("ROW_IDS = [\n")
        # Write 10 IDs per line for compact readability and fast parsing
        chunk_size = 10
        for i in range(0, len(target_row_indices), chunk_size):
            chunk = target_row_indices[i:i + chunk_size]
            line_str = "    " + ", ".join(str(idx) for idx in chunk) + ",\n"
            f.write(line_str)
        f.write("]\n")

    write_elapsed = time.time() - t_write
    data_py_size_mb = DATA_PY_PATH.stat().st_size / (1024 * 1024)
    print(f"✅ ĐÃ CẬP NHẬT XONG {DATA_PY_PATH}!")
    print(f"Dung lượng file: {data_py_size_mb:.2f} MB | Thời gian ghi: {write_elapsed:.2f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
