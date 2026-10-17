#!/usr/bin/env python3
"""
Rescue Script for Missing Chinese (ZH) URLs using Wayback Machine Replay Direct Redirects.
Supports msdmanuals.cn, cnkang.com, wujue.com, bingli.iiyi.com, 120ask.com, and youlai.cn.

Conforms strictly to ViBioMIR rules:
1. Verbatim text extraction (clean_to_verbatim)
2. Preserves integer doc_id mapping 1-1
3. Safe derivative output to datacrawl/derived/bosung/data_rescued_zh_wayback.jsonl
4. Updates SQLite repair_crawl_checkpoint.sqlite
5. Gentle rate limiting (1.8s delay) to ensure stable connection with Archive.org
"""

import os
import sys
import json
import time
import html
import re
import sqlite3
import subprocess
from urllib.parse import urlparse
from pathlib import Path
from bs4 import BeautifulSoup

MISSING_JSON = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/missing_zh_final.json')
SQLITE_DB = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/repair_crawl_checkpoint.sqlite')
OUTPUT_JSONL = Path('/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_rescued_zh_wayback.jsonl')

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

def extract_msd(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        t.decompose()
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    sections = soup.find_all("section", class_="topic__section")
    if sections:
        body = "\n\n".join(s.get_text(separator="\n", strip=True) for s in sections)
    else:
        main = soup.find("div", class_="topic__content") or soup.find("main") or soup.find("article") or soup.body
        body = main.get_text(separator="\n", strip=True) if main else ""
    full_text = f"{title}\n\n{body}" if title else body
    return clean_to_verbatim(full_text)

def extract_cnkang(raw_bytes: bytes) -> str:
    html_text = ""
    for enc in ["gb18030", "gbk", "utf-8", "gb2312"]:
        try:
            html_text = raw_bytes.decode(enc)
            break
        except Exception:
            pass
    if not html_text:
        html_text = raw_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        t.decompose()
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    if not title and soup.title:
        title = soup.title.string.split("_")[0].strip()
    body = soup.find("div", class_="art_content") or soup.find("div", id="art_content") or soup.find("div", id="content")
    if not body:
        for p in soup.find_all("p"):
            if len(p.get_text(strip=True)) > 50:
                body = p.parent
                break
    body_text = body.get_text(separator="\n", strip=True) if body else ""
    full_text = f"{title}\n\n{body_text}" if title else body_text
    return clean_to_verbatim(full_text)

def extract_generic_zh(raw_bytes: bytes) -> str:
    html_text = ""
    for enc in ["utf-8", "gb18030", "gbk", "gb2312"]:
        try:
            html_text = raw_bytes.decode(enc)
            break
        except Exception:
            pass
    if not html_text:
        html_text = raw_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        t.decompose()
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    if not title and soup.title:
        title = soup.title.string.split("_")[0].split("-")[0].strip()
    main = soup.find("article") or soup.find("main") or soup.find(id="content") or soup.find(class_="content") or soup.body
    body_text = main.get_text(separator="\n", strip=True) if main else ""
    full_text = f"{title}\n\n{body_text}" if title else body_text
    return clean_to_verbatim(full_text)

def main():
    if not MISSING_JSON.exists():
        print(f"Error: {MISSING_JSON} does not exist!")
        return

    with open(MISSING_JSON, "r", encoding="utf-8") as f:
        all_missing = json.load(f)

    # Filter targets for viable domains
    target_domains = ["msdmanuals.cn", "cnkang.com", "wujue.com", "bingli.iiyi.com", "120ask.com", "youlai.cn"]
    targets = [it for it in all_missing if any(d in it["url"] for d in target_domains)]
    print(f"Loaded {len(targets)} candidates from domains: {target_domains}")

    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()

    rescued = []
    success_count = 0

    for idx, item in enumerate(targets, 1):
        doc_id = item["id"]
        url = item["url"]
        domain = urlparse(url).netloc

        # Check location header from Wayback
        check_cmd = ["curl", "-s", "-I", "--connect-timeout", "6", "-m", "10", f"https://web.archive.org/web/{url}"]
        raw_loc = ""
        for attempt in range(3):
            try:
                out = subprocess.check_output(check_cmd).decode("utf-8")
                if "HTTP/2 302" in out or "HTTP/1.1 302" in out:
                    locs = [l.split(":", 1)[1].strip() for l in out.splitlines() if l.lower().startswith("location:")]
                    if locs:
                        raw_loc = locs[0]
                        break
                elif "HTTP/2 200" in out or "HTTP/1.1 200" in out:
                    raw_loc = f"https://web.archive.org/web/{url}"
                    break
            except Exception:
                time.sleep(1.5)

        if not raw_loc:
            print(f"[{idx:2d}/{len(targets)}] NOT ARCHIVED | ID {doc_id} | {domain} | {url[:45]}")
            time.sleep(1.8)
            continue

        # Prepare verbatim id_ replay URL
        # Format: https://web.archive.org/web/<ts>id_/<orig_url>
        replay_url = raw_loc
        match = re.search(r"web\.archive\.org/web/(\d+)(?:id_)?/(.+)", raw_loc)
        if match:
            ts, orig = match.group(1), match.group(2)
            replay_url = f"https://web.archive.org/web/{ts}id_/{orig}"

        # Fetch HTML snapshot
        raw_bytes = None
        fetch_cmd = ["curl", "-sL", "--connect-timeout", "8", "-m", "20", replay_url]
        for attempt in range(3):
            try:
                raw_bytes = subprocess.check_output(fetch_cmd)
                if len(raw_bytes) > 500:
                    break
            except Exception:
                time.sleep(2.0)

        if not raw_bytes or len(raw_bytes) < 300:
            print(f"[{idx:2d}/{len(targets)}] EMPTY HTML | ID {doc_id} | {domain}")
            time.sleep(1.8)
            continue

        # Extract text based on domain
        try:
            if "msdmanuals.cn" in domain:
                raw_html = raw_bytes.decode("utf-8", errors="ignore")
                verbatim_text = extract_msd(raw_html)
            elif "cnkang.com" in domain:
                verbatim_text = extract_cnkang(raw_bytes)
            else:
                verbatim_text = extract_generic_zh(raw_bytes)
        except Exception as e:
            print(f"[{idx:2d}/{len(targets)}] EXTRACT ERROR | ID {doc_id} | {e}")
            time.sleep(1.8)
            continue

        if len(verbatim_text) >= 40:
            success_count += 1
            rec = {
                "id": doc_id,
                "url": url,
                "text": verbatim_text,
                "success": True,
                "domain": domain,
                "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            rescued.append(rec)

            # Checkpoint into SQLite
            cur.execute("""
                INSERT OR REPLACE INTO repair_records (id, url, text, success, domain, error, crawled_at)
                VALUES (?, ?, ?, 1, ?, NULL, CURRENT_TIMESTAMP)
            """, (doc_id, url, verbatim_text, domain))
            conn.commit()

            print(f"[{idx:2d}/{len(targets)}] RESCUED ID {doc_id} | {domain} | Len: {len(verbatim_text)} chars")
        else:
            print(f"[{idx:2d}/{len(targets)}] TEXT TOO SHORT | ID {doc_id} | Len: {len(verbatim_text)}")

        time.sleep(1.8)

    conn.close()

    print(f"\n==========================================")
    print(f"HOÀN TẤT RESCUE TIẾNG TRUNG QUA WAYBACK MACHINE:")
    print(f"Cứu thành công: {success_count} / {len(targets)} bài!")
    print(f"==========================================")

    # Save to derivative JSONL
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for r in rescued:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Đã lưu {len(rescued)} bản ghi vào: {OUTPUT_JSONL}")

if __name__ == "__main__":
    main()
