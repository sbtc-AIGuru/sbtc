"""Export all 337,375 ask.39.net URLs into compact Parquet shards for Kaggle execution.

Generates:
- ask39_pending_all.parquet (all 337,375 URLs)
- ask39_shard_1.parquet to ask39_shard_6.parquet (~56,229 URLs each)
- kaggle_ask39_shards.zip containing all shards and standalone worker scripts
"""

from __future__ import annotations

import math
from pathlib import Path
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
OUTPUT_DIR = REPO_ROOT.parent / "datacrawl" / "derived" / "kaggle_ask39_shards"
ZIP_PATH = REPO_ROOT.parent / "datacrawl" / "derived" / "kaggle_ask39_shards.zip"
KAGGLE_DIR = REPO_ROOT / "Scripts" / "Clawler" / "kaggle"


def export_shards(num_shards: int = 6):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading target ask.39.net records from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    targets = []
    # Continuous range of ask.39.net: 2,110,878 to 2,448,252
    START_ROW = 2_110_878
    END_ROW = 2_448_252

    for idx in range(START_ROW, min(END_ROW + 1, len(urls))):
        u = urls[idx]
        if "ask.39.net" in u:
            targets.append((idx, ids[idx], u))

    total_targets = len(targets)
    print(f"Total ask.39.net targets identified: {total_targets}")
    assert total_targets == 337_375, f"Expected 337,375 targets, got {total_targets}"

    # 1. Export all as single parquet
    row_indices = [t[0] for t in targets]
    doc_ids = [t[1] for t in targets]
    url_list = [t[2] for t in targets]

    all_table = pa.Table.from_arrays(
        [
            pa.array(row_indices, type=pa.int64()),
            pa.array(doc_ids, type=pa.int64()),
            pa.array(url_list, type=pa.string()),
        ],
        names=["row_index", "id", "url"],
    )
    all_path = OUTPUT_DIR / "ask39_pending_all.parquet"
    pq.write_table(all_table, all_path, compression="zstd")
    print(f"Exported ask39_pending_all.parquet ({total_targets} rows, {all_path.stat().st_size / 1024:.1f} KB)")

    # 2. Export individual shards
    shard_size = math.ceil(total_targets / num_shards)
    shard_paths = []

    for s in range(num_shards):
        start_idx = s * shard_size
        end_idx = min((s + 1) * shard_size, total_targets)
        shard_data = targets[start_idx:end_idx]

        s_table = pa.Table.from_arrays(
            [
                pa.array([t[0] for t in shard_data], type=pa.int64()),
                pa.array([t[1] for t in shard_data], type=pa.int64()),
                pa.array([t[2] for t in shard_data], type=pa.string()),
            ],
            names=["row_index", "id", "url"],
        )
        s_path = OUTPUT_DIR / f"ask39_shard_{s + 1}.parquet"
        pq.write_table(s_table, s_path, compression="zstd")
        shard_paths.append(s_path)
        print(
            f"Exported Shard {s + 1}: {len(shard_data)} rows (row_index {shard_data[0][0]} -> {shard_data[-1][0]}) "
            f"-> {s_path.name} ({s_path.stat().st_size / 1024:.1f} KB)"
        )

    # 3. Create full Kaggle zip bundle
    print(f"\nCreating Kaggle bundle: {ZIP_PATH} ...")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        # Include all shards
        for sp in shard_paths:
            zf.write(sp, arcname=sp.name)
        zf.write(all_path, arcname=all_path.name)

        # Include worker scripts if present
        worker_script = KAGGLE_DIR / "ask39_kaggle_worker.py"
        if worker_script.exists():
            zf.write(worker_script, arcname=worker_script.name)
        notebook_path = KAGGLE_DIR / "ask39_kaggle_crawler.ipynb"
        if notebook_path.exists():
            zf.write(notebook_path, arcname=notebook_path.name)

    print(f"Zip bundle created successfully: {ZIP_PATH} ({ZIP_PATH.stat().st_size / (1024 * 1024):.2f} MB)")


if __name__ == "__main__":
    export_shards(num_shards=6)
