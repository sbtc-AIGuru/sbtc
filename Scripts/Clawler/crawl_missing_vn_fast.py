#!/usr/bin/env python3
"""
Fast Local Crawler for 191 Missing Vietnamese News & Hospital Articles.
Domains: thaythuocvietnam.vn, medlatec.vn, laodong.vn, bachmai.gov.vn,
tiemchunglongchau.com.vn, youmed.vn, tamanhhospital.vn, etc.

Conforms strictly to ViBioMIR rules:
- Verbatim text extraction (clean_to_verbatim)
- Preserves immutable integer id from New Corpus
- Safe derivative output to datacrawl/derived/bosung/data_bosung_baovn_misc.jsonl
- Atomic SQLite checkpointing to repair_crawl_checkpoint.sqlite
"""

import os
import sys
import json
import time
import html
import re
import sqlite3
from urllib.parse import urlparse
from pathlib import Path
from bs4 import BeautifulSoup
from curl_cffi import requests

INPUT_JSON = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/missing_vn_non_lc.json')
SQLITE_DB = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/repair_crawl_checkpoint.sqlite')
OUTPUT_JSONL = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_bosung_baovn_misc.jsonl')

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

def extract_general_vietnamese(html_content: str, url: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
        tag.decompose()

    h1 = soup.find("h1")
    title = clean_to_verbatim(h1.get_text(strip=True)) if h1 else ""
    if not title and soup.title:
        title = clean_to_verbatim(soup.title.string.split("-")[0].split("|")[0].strip())

    # Candidate content containers
    content_el = (
        soup.find(class_=re.compile(r"detail-content|content-detail|article-content|fck_detail|main-content|post-content|entry-content", re.I)) or
        soup.find(id=re.compile(r"content|article|detail", re.I)) or
        soup.find("article") or
        soup.find("main")
    )

    if content_el:
        for junk in content_el.find_all(class_=re.compile(r"related|share|tag|author|comment|social|adv|banner|box-info", re.I)):
            junk.decompose()
        body_text = content_el.get_text(separator="\n\n", strip=True)
    else:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        body_text = "\n\n".join(paragraphs)

    full_text = f"{title}\n\n{body_text}" if title else body_text
    return clean_to_verbatim(full_text)

def main():
    if not INPUT_JSON.exists():
        print(f"Error: {INPUT_JSON} not found!")
        return

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        targets = json.load(f)

    print(f"Loaded {len(targets)} missing Vietnamese articles to crawl directly.")

    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()

    rescued = []
    success_count = 0

    session = requests.Session(impersonate="chrome120")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    for idx, item in enumerate(targets, 1):
        doc_id = item["id"]
        url = item["url"]
        host = item["host"]

        verbatim_text = ""
        error_msg = None

        for attempt in range(2):
            try:
                resp = session.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    verbatim_text = extract_general_vietnamese(resp.text, url)
                    if len(verbatim_text) >= 40:
                        break
                    else:
                        error_msg = f"Text too short ({len(verbatim_text)} chars)"
                elif resp.status_code in [404, 410]:
                    error_msg = f"HTTP {resp.status_code}"
                    break
                else:
                    error_msg = f"HTTP {resp.status_code}"
                    time.sleep(1.0)
            except Exception as e:
                error_msg = str(e)
                time.sleep(1.0)

        if verbatim_text and len(verbatim_text) >= 40:
            success_count += 1
            rec = {
                "id": doc_id,
                "url": url,
                "text": verbatim_text,
                "success": True,
                "domain": host,
                "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            rescued.append(rec)

            cur.execute("""
                INSERT OR REPLACE INTO repair_records (id, url, text, success, domain, error, crawled_at)
                VALUES (?, ?, ?, 1, ?, NULL, CURRENT_TIMESTAMP)
            """, (doc_id, url, verbatim_text, host))
            conn.commit()

            print(f"[{idx:3d}/{len(targets)}] SUCCESS ID {doc_id} | {host} | Len: {len(verbatim_text)} chars")
        else:
            print(f"[{idx:3d}/{len(targets)}] FAILED ID {doc_id} | {host} | {error_msg}")

        time.sleep(0.08)

    conn.close()

    print(f"\n==========================================")
    print(f"HOÀN TẤT CRAWL BÁO CHÍ & BỆNH VIỆN VN:")
    print(f"Thành công: {success_count} / {len(targets)} bài!")
    print(f"==========================================")

    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for r in rescued:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Đã lưu {len(rescued)} bản ghi vào: {OUTPUT_JSONL}")

if __name__ == "__main__":
    main()
