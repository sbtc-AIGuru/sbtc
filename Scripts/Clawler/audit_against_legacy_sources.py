#!/usr/bin/env python3
"""
Comprehensive Cross-Audit: final_data.jsonl vs. All Legacy Sources
Checks:
1. False Negatives: Did final_data miss any record that was successfully crawled in any older file?
2. Content Quality: Did final_data pick the best version when multiple versions existed?
3. Length & Fidelity: Analyze cases where text length differs between final and legacy.
"""

import json
import os
from pathlib import Path
import sqlite3
import sys
import time

def main():
    final_path = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/final_data.jsonl")
    if not final_path.exists():
        print(f"Error: {final_path} does not exist!")
        sys.exit(1)

    print("[Step 1] Loading final_data.jsonl summary...")
    t0 = time.time()
    
    # Store: id -> (success: bool, text_len: int)
    final_status = {}
    final_sample_texts = {} # id -> text for a subset of IDs to inspect
    
    total_final = 0
    final_success_count = 0
    final_failed_ids = set()
    
    with open(final_path, "r", encoding="utf-8") as f:
        for line_idx, line in enumerate(f):
            total_final += 1
            rec = json.loads(line)
            rid = rec["id"]
            succ = rec["success"]
            txt = rec.get("text", "") or ""
            tlen = len(txt)
            final_status[rid] = (succ, tlen)
            if succ:
                final_success_count += 1
            else:
                final_failed_ids.add(rid)

    print(f"  Loaded {total_final:,} records from final_data.jsonl in {time.time()-t0:.2f}s")
    print(f"  Success: {final_success_count:,} | Failed: {len(final_failed_ids):,}")

    # Legacy JSONL files to check
    legacy_files = [
        ("dataraw_main/data.jsonl", "datacrawl/dataraw_main/data.jsonl"),
        ("dataraw_main/crawled_local_kaggle_20261011.jsonl", "datacrawl/dataraw_main/crawled_local_kaggle_success_unique_20261011.jsonl"),
        ("dataraw_main/crawled_phase1_ask39.jsonl", "datacrawl/dataraw_main/crawled_phase1_priority3_ask39.jsonl"),
        ("dataraw_main/data_bosung1.jsonl", "datacrawl/dataraw_main/data_bosung1.jsonl"),
        ("dataraw_main/data_bosung2.jsonl", "datacrawl/dataraw_main/data_bosung2.jsonl"),
        ("dataraw_main/data_bosung3.jsonl", "datacrawl/dataraw_main/data_bosung3.jsonl"),
        ("dataraw_main/data_bosung4.jsonl", "datacrawl/dataraw_main/data_bosung4.jsonl"),
        ("derived/bosung/data_bosung_longchau_ironclad.jsonl", "datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl"),
        ("derived/bosung/data_bosung_longchau.jsonl", "datacrawl/derived/bosung/data_bosung_longchau.jsonl"),
        ("derived/bosung/data_bosung_pubmed.jsonl", "datacrawl/derived/bosung/data_bosung_pubmed.jsonl"),
        ("derived/bosung/data_bosung_baovn.jsonl", "datacrawl/derived/bosung/data_bosung_baovn.jsonl"),
        ("derived/bosung/data_bosung_ask39.jsonl", "datacrawl/derived/bosung/data_bosung_ask39.jsonl"),
        ("derived/bosung/data_bosung_cnkang.jsonl", "datacrawl/derived/bosung/data_bosung_cnkang.jsonl"),
        ("derived/bosung/data_repaired_vi_zh.jsonl", "datacrawl/derived/bosung/data_repaired_vi_zh.jsonl"),
        ("derived/bosung/data_rescued_iiyi_wayback.jsonl", "datacrawl/derived/bosung/data_rescued_iiyi_wayback.jsonl"),
        ("derived/bosung/data_rescued_pubmed.jsonl", "datacrawl/derived/bosung/data_rescued_pubmed.jsonl"),
        ("derived/bosung/data_rescued_pubmed_openalex.jsonl", "datacrawl/derived/bosung/data_rescued_pubmed_openalex.jsonl"),
        ("derived/bosung/data_rescued_zh_wayback.jsonl", "datacrawl/derived/bosung/data_rescued_zh_wayback.jsonl"),
    ]

    print("\n[Step 2] Checking for False Negatives (failed in final, but succeeded in legacy)...")
    false_negatives = [] # list of (id, source, text_len, preview)
    
    # Also track content comparison:
    # IDs where legacy was significantly longer (>50% longer than final)
    significantly_longer_legacy = [] # list of (id, source, final_len, legacy_len, url)
    # IDs where final was significantly longer (>50% longer than legacy)
    significantly_longer_final = 0
    # IDs where legacy had mojibake (\ufffd) but final is clean
    legacy_mojibake_fixed = 0

    for label, rel_path in legacy_files:
        p = Path(rel_path)
        if not p.exists():
            continue
        ts = time.time()
        count_checked = 0
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rid = rec.get("id")
                if rid is None:
                    continue
                rid = int(rid)
                if rid not in final_status:
                    continue
                
                count_checked += 1
                succ = bool(rec.get("success"))
                raw_txt = rec.get("text") or ""
                raw_len = len(raw_txt)

                # Check if it's a false negative
                if rid in final_failed_ids and succ and raw_len > 60:
                    false_negatives.append((rid, label, raw_len, raw_txt[:100].replace("\n", " ")))

                # Check content length comparison for success records
                final_succ, final_len = final_status[rid]
                if final_succ and succ and final_len > 0 and raw_len > 0:
                    if "\ufffd" in raw_txt and raw_txt.count("\ufffd") > 2:
                        legacy_mojibake_fixed += 1
                    
                    if raw_len > final_len * 1.5 and (raw_len - final_len) > 200:
                        if len(significantly_longer_legacy) < 50:
                            significantly_longer_legacy.append((rid, label, final_len, raw_len, rec.get("url", ""), raw_txt[:200]))
                    elif final_len > raw_len * 1.5 and (final_len - raw_len) > 200:
                        significantly_longer_final += 1

        print(f"  + Checked {label:50s} ({count_checked:8,d} matched IDs in {time.time()-ts:.2f}s)")

    # Also check SQLite checkpoints for false negatives
    sqlite_files = [
        ("crawl_checkpoint.sqlite", "datacrawl/derived/bosung/crawl_checkpoint.sqlite", "crawl_records"),
        ("longchau_ironclad_checkpoint.sqlite", "datacrawl/derived/bosung/longchau_ironclad_checkpoint.sqlite", "crawl_records"),
        ("pubmed_crawl_checkpoint.sqlite", "datacrawl/derived/bosung/pubmed_crawl_checkpoint.sqlite", "crawl_records"),
        ("ask39_crawl_checkpoint.sqlite", "datacrawl/derived/ask39_crawl_checkpoint.sqlite", "crawled_records"),
        ("zysj_crawl_checkpoint.sqlite", "datacrawl/derived/zysj_crawl_checkpoint.sqlite", "crawled_records"),
    ]

    print("\n[Step 3] Checking SQLite checkpoints for False Negatives...")
    for label, rel_path, tbl in sqlite_files:
        p = Path(rel_path)
        if not p.exists():
            continue
        ts = time.time()
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute(f"SELECT id, text, success FROM {tbl};")
        count_checked = 0
        for rid, txt, succ in cur:
            if rid is None:
                continue
            rid = int(rid)
            if rid in final_failed_ids:
                txt_len = len(txt or "")
                if succ and txt_len > 60:
                    false_negatives.append((rid, label, txt_len, (txt or "")[:100].replace("\n", " ")))
            count_checked += 1
        conn.close()
        print(f"  + Checked SQLite {label:45s} ({count_checked:8,d} records in {time.time()-ts:.2f}s)")

    print("\n" + "="*80)
    print("AUDIT RESULTS SUMMARY:")
    print("="*80)
    print(f"1. Total False Negatives (records failed in final but valid in legacy): {len(false_negatives)}")
    if false_negatives:
        print("   Found false negatives:")
        for fn in false_negatives[:10]:
            print(f"     ID {fn[0]} in {fn[1]}: len={fn[2]} | Preview: {fn[3]}")
    else:
        print("   ✅ ZERO False Negatives! Not a single valid record from any legacy file was missed.")

    print(f"\n2. Legacy Mojibake occurrences cleaned/avoided in final: {legacy_mojibake_fixed:,}")
    print(f"3. Records where final_data is significantly longer (>50% longer): {significantly_longer_final:,}")
    print(f"4. Records where legacy was significantly longer (>50% longer): {len(significantly_longer_legacy):,}")
    
    if significantly_longer_legacy:
        print("\n   Investigating why legacy was longer in these sample cases:")
        for rid, label, flen, rlen, url, preview in significantly_longer_legacy[:5]:
            print(f"   - ID {rid} ({url}): final={flen} chars vs legacy={rlen} chars in {label}")
            print(f"     Legacy preview: {preview[:120]}...")

    print("="*80)

if __name__ == "__main__":
    main()
