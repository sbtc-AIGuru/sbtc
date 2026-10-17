"""Merge Phase 1b rescued crawl records into Phase 1 final dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pyarrow.parquet as pq

from verbatim import clean_to_verbatim


def merge_rescued(
    base_jsonl: Path,
    rescued_jsonls: list[Path],
    parquet_path: Path,
    output_jsonl: Path,
) -> None:
    print(f"[Merge] Loading Parquet reference from {parquet_path}...")
    table = pq.read_table(parquet_path, columns=["id", "url"])
    ids_col = table.column("id")
    urls_col = table.column("url")

    # 1. Load rescued successful records
    rescued_records: dict[int, dict] = {}
    for rescued_file in rescued_jsonls:
        if not rescued_file.exists():
            print(f"[Merge] Warning: {rescued_file} does not exist yet. Skipping.")
            continue
        print(f"[Merge] Reading rescued records from {rescued_file}...")
        count = 0
        success_count = 0
        with open(rescued_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                count += 1
                row_idx = rec["row_index"]
                if rec.get("success"):
                    # Ensure verbatim cleaning
                    rec["text"] = clean_to_verbatim(rec.get("text", ""))
                    rescued_records[row_idx] = rec
                    success_count += 1
        print(f"[Merge]   -> Total: {count}, successful: {success_count}")

    print(f"[Merge] Total unique rescued successful rows to merge: {len(rescued_records)}")

    # 2. Iterate base JSONL and merge
    print(f"[Merge] Reading base dataset from {base_jsonl}...")
    temp_output = output_jsonl.with_suffix(".tmp")
    
    total_rows = 0
    base_success = 0
    new_success = 0
    replaced_count = 0

    with open(base_jsonl, "r", encoding="utf-8") as f_in, open(temp_output, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            row_idx = rec["row_index"]
            total_rows += 1
            if rec.get("success"):
                base_success += 1

            # Check if we have a rescued success for this row
            if row_idx in rescued_records:
                rescued_rec = rescued_records[row_idx]
                if not rec.get("success"):
                    replaced_count += 1
                rec = rescued_rec

            # Validation against Parquet
            expected_id = ids_col[row_idx].as_py()
            expected_url = urls_col[row_idx].as_py()
            assert rec["id"] == expected_id, f"ID mismatch at row {row_idx}: {rec['id']} != {expected_id}"
            assert rec["url"] == expected_url, f"URL mismatch at row {row_idx}: {rec['url']} != {expected_url}"

            if rec.get("success"):
                new_success += 1
                assert len(rec.get("text", "").strip()) > 0, f"Empty text for successful row {row_idx}"

            f_out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Atomic rename
    temp_output.replace(output_jsonl)

    print("\n=== MERGE SUMMARY ===")
    print(f"Total base rows: {total_rows}")
    print(f"Base success: {base_success} ({base_success / total_rows * 100:.2f}%)")
    print(f"Newly rescued rows: {replaced_count}")
    print(f"New total success: {new_success} ({new_success / total_rows * 100:.2f}%)")
    print(f"Output saved to: {output_jsonl}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="datacrawl/derived/crawled_phase1_final.jsonl",
        help="Path to base Phase 1 JSONL",
    )
    parser.add_argument(
        "--rescued",
        nargs="+",
        default=[
            "datacrawl/derived/crawled_phase1b_non_baidu.jsonl",
            "datacrawl/derived/crawled_phase1b_baidu.jsonl",
        ],
        help="Paths to rescued JSONL files",
    )
    parser.add_argument(
        "--parquet",
        default="sbtc/data/links_corpus.parquet",
        help="Path to links_corpus.parquet",
    )
    parser.add_argument(
        "--output",
        default="datacrawl/derived/crawled_phase1_final.jsonl",
        help="Target output JSONL path",
    )
    args = parser.parse_args()
    merge_rescued(
        base_jsonl=Path(args.base),
        rescued_jsonls=[Path(p) for p in args.rescued],
        parquet_path=Path(args.parquet),
        output_jsonl=Path(args.output),
    )


if __name__ == "__main__":
    main()
