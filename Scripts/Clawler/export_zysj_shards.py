"""Export remaining zysjonline.com URLs into compact Parquet shards for Kaggle execution.

Generates:
- zysj_pending_all.parquet (all 187,965 URLs)
- zysj_shard_1.parquet (62,655 URLs)
- zysj_shard_2.parquet (62,655 URLs)
- zysj_shard_3.parquet (62,655 URLs)
- kaggle_shards.zip containing the shards
"""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
DB_PATH = REPO_ROOT.parent / "datacrawl" / "derived" / "zysj_crawl_checkpoint.sqlite"
OUTPUT_DIR = REPO_ROOT.parent / "datacrawl" / "derived" / "kaggle_shards"


def export_shards(num_shards: int = 5):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading target records from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH)
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    targets = []
    for idx in range(4_151_371, min(4_394_718, len(urls))):
        if "zysjonline.com" in urls[idx]:
            targets.append((idx, ids[idx], urls[idx]))

    print(f"Total targets identified in parquet: {len(targets)}")

    crawled_indices = set()
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT row_index FROM crawled_records "
                "WHERE success = 1 OR error LIKE 'HTTP 404%' OR error LIKE 'Article text too short%'"
            )
            crawled_indices = {r[0] for r in c.fetchall()}

    print(f"Already crawled in SQLite checkpoint: {len(crawled_indices)}")

    pending = [t for t in targets if t[0] not in crawled_indices]
    total_pending = len(pending)
    print(f"Total pending to crawl: {total_pending} URLs")

    if total_pending == 0:
        print("No pending records! Everything already crawled.")
        return

    # 1. Export all pending as single parquet
    row_indices = [p[0] for p in pending]
    doc_ids = [p[1] for p in pending]
    url_list = [p[2] for p in pending]

    all_table = pa.Table.from_arrays(
        [
            pa.array(row_indices, type=pa.int64()),
            pa.array(doc_ids, type=pa.int64()),
            pa.array(url_list, type=pa.string()),
        ],
        names=["row_index", "id", "url"],
    )
    all_path = OUTPUT_DIR / "zysj_pending_all.parquet"
    pq.write_table(all_table, all_path, compression="zstd")
    print(f"Exported all pending ({total_pending} rows) -> {all_path} ({all_path.stat().st_size / 1024:.1f} KB)")

    # 2. Export individual shards
    shard_size = math.ceil(total_pending / num_shards)
    shard_paths = []

    for s in range(num_shards):
        start_idx = s * shard_size
        end_idx = min((s + 1) * shard_size, total_pending)
        shard_data = pending[start_idx:end_idx]

        s_table = pa.Table.from_arrays(
            [
                pa.array([p[0] for p in shard_data], type=pa.int64()),
                pa.array([p[1] for p in shard_data], type=pa.int64()),
                pa.array([p[2] for p in shard_data], type=pa.string()),
            ],
            names=["row_index", "id", "url"],
        )
        s_path = OUTPUT_DIR / f"zysj_shard_{s + 1}.parquet"
        pq.write_table(s_table, s_path, compression="zstd")
        shard_paths.append(s_path)
        print(
            f"Exported Shard {s + 1} ({len(shard_data)} rows, row_index {shard_data[0][0]} -> {shard_data[-1][0]}) "
            f"-> {s_path} ({s_path.stat().st_size / 1024:.1f} KB)"
        )

    # 3. Create a zip archive for easy 1-click upload to Kaggle Dataset
    zip_path = OUTPUT_DIR.parent / "kaggle_zysj_shards.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(all_path, arcname=all_path.name)
        for sp in shard_paths:
            zf.write(sp, arcname=sp.name)

    print(f"\nCreated bundle zip: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.2f} MB)")
    print("Done exporting shards!")


if __name__ == "__main__":
    export_shards(num_shards=5)
