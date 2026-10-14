#!/usr/bin/env python3
"""
Rescue Script for 97 Matched article.iiyi.com URLs using Wayback Machine Archive via curl_cffi.
Impersonates Chrome 120 browser fingerprint to avoid Archive.org rate limits.
Conforms strictly to ViBioMIR rules: Verbatim text, preserves integer ID, safe derivative output.
"""

import os
import sys
import json
import time
import html
import re
import sqlite3
from bs4 import BeautifulSoup
from pathlib import Path
from curl_cffi import requests

# Add project root to sys.path
sys.path.insert(0, '/home/tran-nhat-truong/TranNhatTruong/other/AIGuru')
from sbtc.Scripts.Clawler.repair_vi_zh_crawler import clean_to_verbatim

INPUT_JSON = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/iiyi_matched_wayback.json')
SQLITE_DB = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/repair_crawl_checkpoint.sqlite')
OUTPUT_JSONL = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_rescued_iiyi_wayback.jsonl')

def main():
    if not INPUT_JSON.exists():
        print(f"Error: {INPUT_JSON} not found!")
        return

    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        targets = json.load(f)

    print(f"Loaded {len(targets)} iiyi targets to rescue from Wayback Machine via curl_cffi.")

    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()

    rescued = []
    success_count = 0

    for idx, item in enumerate(targets, 1):
        doc_id = item['id']
        url = item['url']
        ts = item['timestamp']

        archive_url = f"https://web.archive.org/web/{ts}id_/{url}"
        raw_html = None

        for attempt in range(4):
            try:
                resp = requests.get(archive_url, impersonate='chrome120', timeout=20)
                if resp.status_code == 200:
                    raw_html = resp.text
                    break
                elif resp.status_code == 429:
                    time.sleep(4.0 * (attempt + 1))
                else:
                    time.sleep(2.0)
            except Exception as e:
                time.sleep(3.0 * (attempt + 1))

        if not raw_html or len(raw_html) < 200:
            print(f"[{idx:2d}/{len(targets)}] FAIL Fetch: ID {doc_id} | TS {ts}")
            time.sleep(2.5)
            continue

        soup = BeautifulSoup(raw_html, 'html.parser')
        
        # Extract title
        title_el = soup.find('h1')
        if not title_el:
            top_el = soup.find('div', class_='top')
            if top_el:
                title_el = top_el.find('h1')
        if not title_el:
            title_el = soup.find('title')
        title = title_el.get_text().strip() if title_el else ""
        title = re.sub(r'-专业文章|-爱爱医.*$', '', title).strip()

        # Extract content
        cont_el = soup.find('div', class_='cont')
        if not cont_el:
            cont_el = soup.find('div', class_='article_cont')
        if not cont_el:
            cont_el = soup.find('div', class_='cont-box')
        content = cont_el.get_text(separator="\n").strip() if cont_el else ""

        full_raw = f"{title}\n\n{content}".strip()
        verbatim_text = clean_to_verbatim(full_raw)

        if len(verbatim_text) >= 50:
            success_count += 1
            rec = {
                "id": doc_id,
                "url": url,
                "text": verbatim_text,
                "success": True,
                "cluster": "iiyi_rescued_wayback",
                "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            rescued.append(rec)

            # Update SQLite repair_records
            cur.execute("""
                INSERT OR REPLACE INTO repair_records (id, url, text, success, domain, error)
                VALUES (?, ?, ?, 1, 'article.iiyi.com', NULL)
            """, (doc_id, url, verbatim_text))
            conn.commit()

            print(f"[{idx:2d}/{len(targets)}] RESCUED OK: ID {doc_id} | Len={len(verbatim_text):4d} chars | Title: {title[:45]}")
        else:
            print(f"[{idx:2d}/{len(targets)}] SHORT TEXT: ID {doc_id} | Len={len(verbatim_text)}")

        time.sleep(2.5)

    conn.close()

    print(f"\n==================================================")
    print(f"TỔNG KẾT RESCUE IIYI: CỨU THÀNH CÔNG {success_count} / {len(targets)} BÀI!")
    print(f"==================================================")

    with open(OUTPUT_JSONL, 'w', encoding='utf-8') as f:
        for r in rescued:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"Saved {len(rescued)} records to {OUTPUT_JSONL}")

if __name__ == '__main__':
    main()
