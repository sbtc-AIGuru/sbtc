#!/usr/bin/env python3
"""
Rescue Script for 104 Missing PubMed URLs using Semantic Scholar Academic Graph API.
Conforms strictly to ViBioMIR rules: Verbatim text, preserves integer ID, safe derivative output.
"""

import os
import sys
import json
import time
import html
import re
import sqlite3
import urllib.request
import ssl
from pathlib import Path

# Paths
MISSING_JSON = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/missing_en_detailed.json')
SQLITE_DB = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/pubmed_crawl_checkpoint.sqlite')
OUTPUT_JSONL = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_rescued_pubmed.jsonl')
MAIN_JSONL = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_bosung_pubmed.jsonl')

def clean_to_verbatim(text: str) -> str:
    """Chuyển đổi Markdown thành Plain Verbatim Text nguyên bản 100%."""
    if not text:
        return ""
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|?\s*[-:]+[-| :]*\|?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"[*_~`]", "", text)
    text = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>~\"'$])", r"\1", text)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"<br\b[^>]*>?|<br(?=[^\s>])", " ", text, flags=re.IGNORECASE)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned_lines.append("")
                prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False
    return "\n".join(cleaned_lines).strip()

def main():
    print(f"Loading missing PubMed list from: {MISSING_JSON}...")
    with open(MISSING_JSON, 'r', encoding='utf-8') as f:
        missing_items = json.load(f)
    print(f"Total targets to rescue: {len(missing_items)}")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    rescued_records = []
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()

    success_count = 0
    abstract_count = 0

    for idx, item in enumerate(missing_items, 1):
        doc_id = item['id']
        row_index = item['row_index']
        url = item['url']
        pmid = item['pmid']

        api_url = f"https://api.semanticscholar.org/graph/v1/paper/PMID:{pmid}?fields=title,abstract,year,venue,publicationTypes"
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

        paper_data = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                    paper_data = json.loads(resp.read().decode('utf-8'))
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait_time = 2.5 * (attempt + 1)
                    # print(f"  [429 RateLimit] Waiting {wait_time:.1f}s for PMID {pmid}...")
                    time.sleep(wait_time)
                elif e.code == 404:
                    # Paper not found in S2
                    break
                else:
                    time.sleep(1.0)
            except Exception as e:
                time.sleep(1.0)

        if paper_data and (paper_data.get('title') or paper_data.get('abstract')):
            title = (paper_data.get('title') or '').strip()
            abstract = (paper_data.get('abstract') or '').strip()
            year = paper_data.get('year') or ''
            venue = paper_data.get('venue') or ''

            if abstract:
                raw_text = f"{title}\n\n{abstract}"
                abstract_count += 1
            elif venue or year:
                raw_text = f"{title}\n\nPublished in {venue} ({year})."
            else:
                raw_text = title

            verbatim_text = clean_to_verbatim(raw_text)
            
            if len(verbatim_text) >= 15:
                success_count += 1
                rec = {
                    "id": doc_id,
                    "row_index": row_index,
                    "url": url,
                    "text": verbatim_text,
                    "success": True,
                    "cluster": "pubmed_rescued",
                    "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                rescued_records.append(rec)

                # Update SQLite
                cur.execute("""
                    UPDATE crawl_records 
                    SET text = ?, success = 1, error = NULL, cluster = 'pubmed_rescued'
                    WHERE id = ?
                """, (verbatim_text, doc_id))
                conn.commit()

                print(f"[{idx:3d}/{len(missing_items)}] RESCUED PMID {pmid} | ID {doc_id} | Len={len(verbatim_text)} | Title: {title[:60]}...")
            else:
                print(f"[{idx:3d}/{len(missing_items)}] TOO SHORT PMID {pmid} | ID {doc_id}")
        else:
            print(f"[{idx:3d}/{len(missing_items)}] NOT FOUND IN S2: PMID {pmid} | ID {doc_id}")

        time.sleep(1.3)

    conn.close()

    print(f"\n==========================================")
    print(f"HOÀN TẤT RESCUE PUBMED: {success_count} / {len(missing_items)} THÀNH CÔNG!")
    print(f"Số bài có Abstract hoàn chỉnh: {abstract_count}")
    print(f"==========================================")

    # Save to derivative jsonl
    with open(OUTPUT_JSONL, 'w', encoding='utf-8') as f:
        for r in rescued_records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"Saved {len(rescued_records)} records to {OUTPUT_JSONL}")

if __name__ == '__main__':
    main()
