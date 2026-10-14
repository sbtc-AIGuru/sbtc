#!/usr/bin/env python3
"""
Comprehensive Audit Script:
Scans ALL crawled data in /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl
and matches against BTC New Corpus (links_corpus_vi_en_zh.parquet - 1,194,469 URLs).
Filters strictly by status == 'success' (success=True / success=1).
"""

import os
import sys
import re
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse
import pyarrow.parquet as pq

DATACRAWL_DIR = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl")
NEWCORPUS_PATH = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/newcorpus/links_corpus_vi_en_zh.parquet")

def load_target_corpus():
    print(f"Loading target corpus from: {NEWCORPUS_PATH}...")
    t0 = time.time()
    table = pq.read_table(NEWCORPUS_PATH)
    ids = table["id"].to_pylist()
    urls = table["url"].to_pylist()
    
    target_ids = set(ids)
    target_urls = set(urls)
    target_id_to_url = dict(zip(ids, urls))
    
    # Classify by language / group
    zh_domains = {"39.net", "cnkang.com", "120ask.com", "zysj.com.cn", "wujue.com", "iiyi.com", "familydoctor.com.cn", "youlai.cn", "msdmanuals.cn", "people.com.cn", "xywy.com"}
    en_domains = {"pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "sciencedirect.com", "nature.com", "springer.com"}
    
    stats_lang = {"vi": set(), "en": set(), "zh": set()}
    domain_to_ids = {}
    
    for doc_id, url in zip(ids, urls):
        domain = urlparse(url).netloc.lower()
        if domain not in domain_to_ids:
            domain_to_ids[domain] = set()
        domain_to_ids[domain].add(doc_id)
        
        # Language check
        is_zh = any(zh in domain for zh in zh_domains)
        is_en = any(en in domain for en in en_domains)
        if is_zh:
            stats_lang["zh"].add(doc_id)
        elif is_en:
            stats_lang["en"].add(doc_id)
        else:
            stats_lang["vi"].add(doc_id)
            
    print(f"Loaded {len(target_ids):,} target IDs in {time.time() - t0:.2f}s.")
    print(f"  Target Language Breakdown: VI={len(stats_lang['vi']):,}, ZH={len(stats_lang['zh']):,}, EN={len(stats_lang['en']):,}")
    return target_ids, target_urls, target_id_to_url, stats_lang, domain_to_ids

def scan_all_datacrawl(target_ids, target_urls):
    print("\nScanning ALL files in datacrawl directory...")
    t0 = time.time()
    
    crawled_success_ids = set()
    crawled_success_urls = set()
    file_contributions = []
    
    id_re = re.compile(rb'"id":\s*(\d+)')
    succ_re = re.compile(rb'"success":\s*(?:true|1)\b')
    url_re = re.compile(rb'"url":\s*"([^"]+)"')
    
    # 1. Scan all JSONL files
    jsonl_files = sorted(DATACRAWL_DIR.rglob("*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL files to scan.")
    
    for f in jsonl_files:
        # Skip aiguru_chunks_v3 as they are chunk artifacts, not raw crawls, unless needed
        if "aiguru_chunks_v3" in str(f):
            continue
            
        file_size_mb = f.stat().st_size / (1024 * 1024)
        t_file = time.time()
        file_total = 0
        file_succ = 0
        file_matched_target = 0
        
        with open(f, "rb") as fp:
            for line in fp:
                file_total += 1
                # Check for success
                if succ_re.search(line):
                    file_succ += 1
                    m_id = id_re.search(line)
                    if m_id:
                        doc_id = int(m_id.group(1))
                        if doc_id in target_ids:
                            crawled_success_ids.add(doc_id)
                            file_matched_target += 1
                    else:
                        m_u = url_re.search(line)
                        if m_u:
                            try:
                                url_str = m_u.group(1).decode("utf-8")
                                if url_str in target_urls:
                                    crawled_success_urls.add(url_str)
                            except Exception:
                                pass
                                
        dt = time.time() - t_file
        rel_path = f.relative_to(DATACRAWL_DIR)
        print(f"  [JSONL] {rel_path} ({file_size_mb:.1f} MB): {file_total:,} rows, {file_succ:,} succ, {file_matched_target:,} matched in {dt:.1f}s")
        file_contributions.append((str(rel_path), file_size_mb, file_total, file_succ, file_matched_target))
        
    # 2. Scan SQLite databases
    sqlite_files = sorted(DATACRAWL_DIR.rglob("*.sqlite"))
    print(f"\nFound {len(sqlite_files)} SQLite databases to scan.")
    
    for db in sqlite_files:
        db_size_mb = db.stat().st_size / (1024 * 1024)
        rel_path = db.relative_to(DATACRAWL_DIR)
        db_matched_target = 0
        db_succ_total = 0
        
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            
            for tbl in tables:
                cur.execute(f"PRAGMA table_info({tbl})")
                cols = {c[1] for c in cur.fetchall()}
                if "id" in cols and "success" in cols:
                    cur.execute(f"SELECT id FROM {tbl} WHERE success = 1")
                    rows = cur.fetchall()
                    db_succ_total += len(rows)
                    for r in rows:
                        doc_id = r[0]
                        if doc_id in target_ids:
                            crawled_success_ids.add(doc_id)
                            db_matched_target += 1
            conn.close()
            print(f"  [SQLITE] {rel_path} ({db_size_mb:.1f} MB): {db_succ_total:,} succ rows, {db_matched_target:,} matched")
            file_contributions.append((str(rel_path), db_size_mb, 0, db_succ_total, db_matched_target))
        except Exception as e:
            print(f"  [SQLITE] Error {rel_path}: {e}")
            
    print(f"\nScan completed in {time.time() - t0:.2f}s.")
    return crawled_success_ids, crawled_success_urls, file_contributions

def main():
    target_ids, target_urls, target_id_to_url, stats_lang, domain_to_ids = load_target_corpus()
    total_target = len(target_ids)
    
    crawled_ids, crawled_urls, contributions = scan_all_datacrawl(target_ids, target_urls)
    
    # Total matched
    total_matched = len(crawled_ids)
    pct = total_matched / total_target * 100.0
    missing_count = total_target - total_matched
    missing_pct = missing_count / total_target * 100.0
    
    print("\n" + "=" * 80)
    print("           BÁO CÁO ĐỐI SOÁT TOÀN DIỆN: DATACRAWL vs BTC NEWCORPUS")
    print("=" * 80)
    print(f"Tổng số URLs/IDs trong New Corpus BTC:  {total_target:,} (100.00%)")
    print(f"Số lượng ĐÃ CRAWL THÀNH CÔNG (Success):  {total_matched:,} ({pct:.2f}%)")
    print(f"Số lượng CÒN THIẾU (Chưa xong / Failed): {missing_count:,} ({missing_pct:.2f}%)")
    print("-" * 80)
    
    # Language Breakdown
    print("PHÂN BỔ THEO NGÔN NGỮ:")
    for lang, lang_name in [("vi", "Tiếng Việt"), ("zh", "Tiếng Trung"), ("en", "Tiếng Anh")]:
        lang_set = stats_lang[lang]
        lang_total = len(lang_set)
        lang_succ = len(lang_set.intersection(crawled_ids))
        lang_pct = lang_succ / lang_total * 100.0 if lang_total > 0 else 0
        lang_miss = lang_total - lang_succ
        print(f"  * {lang_name:<12}: Đã xong {lang_succ:>7,} / {lang_total:>7,} URLs  ({lang_pct:>6.2f}%)  [Còn thiếu: {lang_miss:>7,}]")
    print("-" * 80)
    
    # Top Missing Domains
    print("TOP 10 TÊN MIỀN CÒN THIẾU NHIỀU NHẤT TRONG NEW CORPUS:")
    domain_stats = []
    for dom, d_ids in domain_to_ids.items():
        total_d = len(d_ids)
        succ_d = len(d_ids.intersection(crawled_ids))
        miss_d = total_d - succ_d
        rate_d = succ_d / total_d * 100.0
        domain_stats.append((dom, total_d, succ_d, miss_d, rate_d))
        
    domain_stats.sort(key=lambda x: x[3], reverse=True)
    print(f"  {'Tên Miền (Domain)':<40} | {'Tổng BTC':<9} | {'Đã Xong':<9} | {'Còn Thiếu':<9} | {'Tỷ Lệ (%)':<8}")
    print("  " + "-" * 82)
    for dom, tot, succ, miss, rate in domain_stats[:12]:
        print(f"  {dom:<40} | {tot:>9,} | {succ:>9,} | {miss:>9,} | {rate:>7.2f}%")
        
    print("=" * 80)

if __name__ == "__main__":
    main()
