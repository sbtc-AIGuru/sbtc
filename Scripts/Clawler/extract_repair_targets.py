#!/usr/bin/env python3
"""
Extract targets that are MISSING or DEFECTIVE (failed / too short / corrupted)
for Vietnamese and Chinese domains in the BTC New Corpus.
Excludes:
- English PubMed (handled via E-utilities API)
- nhathuoclongchau.com.vn (temporarily paused by user)
- Known dead servers / closed stagings (iiyi 521, pharmacity 403)
"""

import sys
import re
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse
import pyarrow as pa
import pyarrow.parquet as pq

NEWCORPUS_PATH = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/newcorpus/links_corpus_vi_en_zh.parquet")
DATACRAWL_DIR = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl")
OUT_PARQUET = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/repair_targets_vi_zh.parquet")

def load_newcorpus():
    print(f"Loading New Corpus from {NEWCORPUS_PATH}...")
    tbl = pq.read_table(NEWCORPUS_PATH)
    ids = tbl["id"].to_pylist()
    urls = tbl["url"].to_pylist()
    target_dict = dict(zip(ids, urls))
    print(f"Total New Corpus targets: {len(target_dict):,}")
    return target_dict

def scan_valid_completed_ids(target_dict):
    """Scan all sources to find truly clean success IDs."""
    print("Scanning datacrawl for valid completed IDs...")
    t0 = time.time()
    valid_succ_ids = set()
    
    # 1. Scan high-quality derived JSONL files
    clean_derived_files = [
        "derived/bosung/data_bosung_39net.jsonl",
        "derived/bosung/data_bosung_ask39.jsonl",
        "derived/bosung/data_bosung_baovn.jsonl",
        "derived/bosung/data_bosung_cnkang.jsonl",
        "derived/bosung/data_bosung_china_other.jsonl",
        "derived/data_bosung4.jsonl",
        "dataraw_main/crawled_local_kaggle_success_unique_20261011.jsonl",
    ]
    
    for rel_f in clean_derived_files:
        p = DATACRAWL_DIR / rel_f
        if not p.exists():
            continue
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    doc_id = row.get("id")
                    if doc_id in target_dict and row.get("success") in [True, 1]:
                        text = row.get("text", "")
                        if len(text.strip()) >= 50 and "\ufffd" not in text:
                            valid_succ_ids.add(doc_id)
                except Exception:
                    pass
                    
    # 2. Scan SQLite checkpoints
    for db_path in DATACRAWL_DIR.rglob("*.sqlite"):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for tbl_name in [r[0] for r in cur.fetchall()]:
                cur.execute(f"PRAGMA table_info({tbl_name})")
                cols = {c[1] for c in cur.fetchall()}
                if "id" in cols and "success" in cols:
                    cur.execute(f"SELECT id, text FROM {tbl_name} WHERE success = 1")
                    for doc_id, text in cur.fetchall():
                        if doc_id in target_dict and text and len(text.strip()) >= 50 and "\ufffd" not in text:
                            valid_succ_ids.add(doc_id)
            conn.close()
        except Exception:
            pass

    # 3. Scan data.jsonl (main)
    main_p = DATACRAWL_DIR / "dataraw_main/data.jsonl"
    if main_p.exists():
        with open(main_p, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    doc_id = row.get("id")
                    if doc_id in target_dict and doc_id not in valid_succ_ids:
                        if row.get("success") in [True, 1]:
                            text = row.get("text", "")
                            if len(text.strip()) >= 50 and "\ufffd" not in text and "安全验证" not in text:
                                valid_succ_ids.add(doc_id)
                except Exception:
                    pass

    print(f"Found {len(valid_succ_ids):,} truly clean & success IDs in {time.time() - t0:.2f}s.")
    return valid_succ_ids

def main():
    target_dict = load_newcorpus()
    valid_succ_ids = scan_valid_completed_ids(target_dict)
    
    # Filter for Vietnamese & Chinese defective/missing items
    # Exclude pubmed, longchau, known dead
    excluded_domains = {
        "pubmed.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        "nhathuoclongchau.com.vn",
        "pmc-ecm-healthblog.beta.pharmacity.io",
        "article.iiyi.com",
        "bingli.iiyi.com",
    }
    
    repair_list = []
    stats_by_domain = {}
    
    for doc_id, url in target_dict.items():
        if doc_id in valid_succ_ids:
            continue
            
        domain = urlparse(url).netloc.lower()
        if any(ex in domain for ex in excluded_domains):
            continue
            
        # Determine language & cluster
        if any(d in domain for d in ["39.net", "cnkang.com", "120ask.com", "wujue.com", "familydoctor.com.cn", "youlai.cn", "msdmanuals.cn"]):
            lang = "zh"
            cluster = "zh_" + domain.split(".")[-2] if "." in domain else "zh_misc"
        else:
            lang = "vi"
            cluster = "vi_" + domain.split(".")[-2] if "." in domain else "vi_misc"
            
        repair_list.append({
            "id": doc_id,
            "url": url,
            "domain": domain,
            "lang": lang,
            "cluster": cluster
        })
        
        stats_by_domain[domain] = stats_by_domain.get(domain, 0) + 1
        
    print(f"\nTotal targets to repair/crawl: {len(repair_list):,}")
    print("\nBreakdown by domain:")
    for dom, cnt in sorted(stats_by_domain.items(), key=lambda x: x[1], reverse=True)[:25]:
        print(f"  {dom:<35}: {cnt:>6,} URLs")
        
    # Save to parquet
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(repair_list)
    pq.write_table(table, OUT_PARQUET)
    print(f"\nSaved {len(repair_list):,} repair targets to: {OUT_PARQUET}")

if __name__ == "__main__":
    main()
