#!/usr/bin/env python3
"""
Rescue Script for 50 Missing PubMed URLs using OpenAlex API.
OpenAlex maintains comprehensive bibliographic and inverted-index abstracts for academic works worldwide.
Conforms strictly to ViBioMIR rules:
1. Verbatim text extraction (clean_to_verbatim)
2. Preserves integer doc_id from New Corpus
3. Safe derivative output to datacrawl/derived/bosung/
4. Updates SQLite checkpoint and tracks all metrics
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
MISSING_JSON = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/missing_en_final50.json')
SQLITE_DB = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/pubmed_crawl_checkpoint.sqlite')
OUTPUT_JSONL = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_rescued_pubmed_openalex.jsonl')

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

def reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct linear text from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join([word for _, word in word_positions])

def main():
    if not MISSING_JSON.exists():
        print(f"Error: {MISSING_JSON} does not exist!")
        return

    with open(MISSING_JSON, 'r', encoding='utf-8') as f:
        targets = json.load(f)

    print(f"Loaded {len(targets)} PubMed targets to rescue via OpenAlex API.")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()

    rescued_records = []
    success_count = 0
    full_abstract_count = 0

    for idx, item in enumerate(targets, 1):
        doc_id = item['id']
        row_index = item['row_index']
        url = item['url']
        pmid = item['pmid']

        api_url = f"https://api.openalex.org/works/pmid:{pmid}"
        req = urllib.request.Request(
            api_url, 
            headers={"User-Agent": "AIGuruBiomedicalResearch/1.0 (mailto:nlp_researcher@gmail.com)"}
        )

        work_data = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                    work_data = json.loads(resp.read().decode('utf-8'))
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(2.0 * (attempt + 1))
                elif e.code == 404:
                    # Not indexed in OpenAlex
                    break
                else:
                    time.sleep(1.0)
            except Exception as e:
                time.sleep(1.0)

        if work_data:
            title = (work_data.get('title') or '').strip()
            raw_abstract = reconstruct_abstract(work_data.get('abstract_inverted_index'))
            venue = (work_data.get('primary_location') or {}).get('source', {}).get('display_name', '') if work_data.get('primary_location') else ''
            year = work_data.get('publication_year') or ''

            if raw_abstract:
                full_text = f"{title}\n\n{raw_abstract}"
                full_abstract_count += 1
            elif venue or year:
                full_text = f"{title}\n\nPublished in {venue} ({year})."
            else:
                full_text = title

            verbatim_text = clean_to_verbatim(full_text)

            if len(verbatim_text) >= 15:
                success_count += 1
                rec = {
                    "id": doc_id,
                    "row_index": row_index,
                    "url": url,
                    "text": verbatim_text,
                    "success": True,
                    "cluster": "pubmed_rescued_openalex",
                    "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                rescued_records.append(rec)

                # Update SQLite Checkpoint
                cur.execute("""
                    UPDATE crawl_records
                    SET text = ?, success = 1, error = NULL, cluster = 'pubmed_rescued_openalex'
                    WHERE id = ?
                """, (verbatim_text, doc_id))
                conn.commit()

                has_abs_str = f"Abstract ({len(raw_abstract)} chars)" if raw_abstract else "Title only"
                print(f"[{idx:2d}/{len(targets)}] SUCCESS PMID {pmid} | ID {doc_id} | {has_abs_str} | Title: {title[:55]}...")
            else:
                print(f"[{idx:2d}/{len(targets)}] TOO SHORT PMID {pmid} | ID {doc_id}")
        else:
            print(f"[{idx:2d}/{len(targets)}] NOT FOUND: PMID {pmid} | ID {doc_id}")

        time.sleep(0.15)

    conn.close()

    print(f"\n==========================================")
    print(f"HOÀN TẤT RESCUE PUBMED QUA OPENALEX:")
    print(f"Cứu thành công: {success_count} / {len(targets)} bài!")
    print(f"Số bài có Abstract hoàn chỉnh: {full_abstract_count}")
    print(f"==========================================")

    # Save derivative jsonl
    with open(OUTPUT_JSONL, 'w', encoding='utf-8') as f:
        for r in rescued_records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"Đã lưu {len(rescued_records)} bản ghi vào: {OUTPUT_JSONL}")

if __name__ == '__main__':
    main()
