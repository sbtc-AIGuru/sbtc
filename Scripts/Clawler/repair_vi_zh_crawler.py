#!/usr/bin/env python3
"""
Targeted High-Efficiency Repair & Recovery Crawler for Vietnamese and Chinese Targets.
Processes 6,836 defective/missing targets from repair_targets_vi_zh.parquet.
Features:
- Dual-path network: Local IP first (fast, direct) -> Fallback SparkProxy
- Specialized domain extractors (jbk.39.net, familydoctor, cnkang, wujue, 120ask, suckhoedoisong, etc.)
- Strict encoding handling (GB18030 / GBK / UTF-8)
- Verbatim text cleaning (clean_to_verbatim) to protect token LCS score
- SQLite WAL checkpointing & auto-export to data_repaired_vi_zh.jsonl
"""

import sys
import os
import re
import html
import json
import sqlite3
import time
import asyncio
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import pyarrow.parquet as pq
from curl_cffi import requests

TARGET_PARQUET = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/repair_targets_vi_zh.parquet")
DB_PATH = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/repair_crawl_checkpoint.sqlite")
OUT_JSONL = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/data_repaired_vi_zh.jsonl")

PROXY = "http://tntruong196:5f9b-e6-76c0b76d6ac41f-8aab10b1@gateway.sparkproxy.io:11000"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,zh-CN,zh;q=0.8,en;q=0.7",
}

def clean_to_verbatim(text: str) -> str:
    """Chuyển đổi Markdown thành Plain Verbatim Text theo quy chuẩn ViBioMIR."""
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

def clean_soup(soup: BeautifulSoup):
    for junk in soup(["script", "style", "iframe", "noscript", "svg", "header", "footer", "nav"]):
        junk.decompose()

def extract_content(html_bytes: bytes, url: str) -> tuple[str, str]:
    domain = urlparse(url).netloc.lower()
    
    # Decoding strategy
    decoded = ""
    enc_list = ["utf-8", "gb18030", "gbk"] if any(k in domain for k in ["cn", "39.net", "wujue", "120ask", "cnkang"]) else ["utf-8"]
    for enc in enc_list:
        try:
            decoded = html_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        decoded = html_bytes.decode("utf-8", errors="replace")
        
    soup = BeautifulSoup(decoded, "html.parser")
    clean_soup(soup)
    
    h1 = soup.find("h1") or soup.find("title")
    title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"_[^_]+(39健康网|快速问医生|中华康网|中医五绝网|家庭医生在线).*$", "", title).strip()
    
    body = ""
    # 1. wujue.com
    if "wujue.com" in domain:
        td = soup.find("td", class_="main")
        if td:
            body = td.get_text(separator="\n\n", strip=True)
            
    # 2. 120ask.com
    elif "120ask.com" in domain:
        parts = []
        ask = soup.find(["div", "p"], class_=lambda c: c and ("crazy_new" in c or "b_askbox" in c or "ask-desc" in c))
        if ask:
            parts.append(ask.get_text(separator="\n\n", strip=True))
        for a in soup.find_all("div", class_=lambda c: c and ("b_anscont" in c or "reply-text" in c)):
            t = a.get_text(separator="\n\n", strip=True)
            if len(t) > 10:
                parts.append(t)
        body = "\n\n".join(parts)
        
    # 3. jbk.39.net (Bách khoa bệnh tật)
    elif "jbk.39.net" in domain:
        info_el = soup.find(["div", "article"], class_=lambda c: c and ("art-text" in c or "info" in c or "intro" in c or "tab-box" in c or "item" in c))
        if info_el:
            body = info_el.get_text(separator="\n\n", strip=True)
            
    # 4. familydoctor.com.cn
    elif "familydoctor.com.cn" in domain:
        art = soup.find(["div", "article"], class_=lambda c: c and ("content" in c or "art-text" in c or "detail" in c or "main" in c))
        if art:
            body = art.get_text(separator="\n\n", strip=True)
            
    # 5. Vietnamese news & medical sites
    elif any(vn in domain for vn in ["suckhoedoisong.vn", "thaythuocvietnam.vn", "medlatec.vn", "laodong.vn", "dantri.com.vn", "bachmai.gov.vn"]):
        art = soup.find(["div", "article"], class_=lambda c: c and ("detail__content" in c or "content-detail" in c or "fck" in c or "post-content" in c or "body" in c or "entry" in c))
        if art:
            body = art.get_text(separator="\n\n", strip=True)
            
    # Default fallback
    if not body:
        art = soup.find(["article", "div"], class_=re.compile(r"content|detail|post-body|main-content|article_content", re.I))
        if art:
            body = art.get_text(separator="\n\n", strip=True)
        else:
            paragraphs = [p.get_text(strip=True) for p in soup.find_all(["p", "div"]) if len(p.get_text(strip=True)) > 25]
            body = "\n\n".join(paragraphs)
            
    full_text = f"{title}\n\n{body}".strip() if body else title
    verbatim_text = clean_to_verbatim(full_text)
    
    if len(verbatim_text) >= 20:
        return verbatim_text, ""
    return "", f"Extracted text too short ({len(verbatim_text)} chars)"

class RepairCrawler:
    def __init__(self, targets_file: Path, db_path: Path, out_file: Path, concurrency: int = 35):
        self.targets_file = targets_file
        self.db_path = db_path
        self.out_file = out_file
        self.concurrency = concurrency
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repair_records (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    text TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    error TEXT,
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rep_succ ON repair_records(success)")

    def get_completed_ids(self) -> set[int]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM repair_records WHERE success = 1 OR error LIKE '%404%' OR error LIKE '%410%'")
            return {r[0] for r in cur.fetchall()}

    def save_batch(self, batch: list[tuple]):
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO repair_records (id, url, text, success, domain, error)
                VALUES (?, ?, ?, ?, ?, ?)
            """, batch)

    def export_jsonl(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, url, text, success, error FROM repair_records ORDER BY id ASC")
            rows = cur.fetchall()
            
        with open(self.out_file, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({
                    "id": r[0],
                    "url": r[1],
                    "text": r[2],
                    "success": bool(r[3]),
                    "error": r[4]
                }, ensure_ascii=False) + "\n")
        print(f"\n[Export] Exported {len(rows):,} records to {self.out_file.name}")

    async def run(self):
        tbl = pq.read_table(self.targets_file)
        targets = tbl.to_pylist()
        completed = self.get_completed_ids()
        todo = [t for t in targets if t["id"] not in completed]
        
        print(f"\n[Repair] Total targets: {len(targets):,} | Done: {len(completed):,} | Todo: {len(todo):,}")
        if not todo:
            print("[Repair] Everything already completed!")
            self.export_jsonl()
            return

        work_queue: asyncio.Queue = asyncio.Queue()
        for item in todo:
            work_queue.put_nowait(item)

        save_queue: asyncio.Queue = asyncio.Queue()
        
        # Local session + Proxy session
        sess_local = requests.AsyncSession(impersonate="chrome120", max_clients=self.concurrency)
        sess_proxy = requests.AsyncSession(impersonate="chrome120", proxy=PROXY, max_clients=self.concurrency)

        crawled_count = 0
        succ_count = 0
        fail_count = 0
        start_time = time.perf_counter()

        async def db_writer():
            buf = []
            while True:
                item = await save_queue.get()
                if item is None:
                    if buf:
                        self.save_batch(buf)
                    save_queue.task_done()
                    break
                buf.append(item)
                if len(buf) >= 50:
                    self.save_batch(buf)
                    buf.clear()
                save_queue.task_done()

        writer_task = asyncio.create_task(db_writer())

        async def worker():
            nonlocal crawled_count, succ_count, fail_count
            while True:
                item = await work_queue.get()
                if item is None:
                    work_queue.task_done()
                    break

                doc_id = item["id"]
                url = item["url"]
                domain = item["domain"]
                
                target_url = url
                if url.startswith("http://") and any(d in url for d in ["120ask.com", "cnkang.com", "familydoctor.com.cn"]):
                    target_url = url.replace("http://", "https://", 1)

                success = False
                text = ""
                error = ""

                # Try Path 1: Local direct
                try:
                    resp = await sess_local.get(target_url, headers=HEADERS, timeout=6.0)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        cleaned, err = extract_content(resp.content, target_url)
                        if cleaned and not err:
                            text = cleaned
                            success = True
                        else:
                            error = err or "Extract failed"
                    elif resp.status_code in (404, 410):
                        error = f"HTTP {resp.status_code}"
                    elif resp.status_code in (403, 521, 502, 503, 504):
                        error = f"HTTP {resp.status_code}"
                except Exception as exc:
                    error = f"Local: {type(exc).__name__}"

                # Try Path 2: Fallback Proxy if not success and not 404
                if not success and "404" not in error and "410" not in error:
                    try:
                        resp = await sess_proxy.get(target_url, headers=HEADERS, timeout=7.0)
                        if resp.status_code == 200 and len(resp.content) > 500:
                            cleaned, err = extract_content(resp.content, target_url)
                            if cleaned and not err:
                                text = cleaned
                                success = True
                                error = ""
                            else:
                                error = err or "Extract failed"
                        elif resp.status_code in (404, 410):
                            error = f"HTTP {resp.status_code}"
                    except Exception as exc:
                        error = f"Proxy: {type(exc).__name__}"

                crawled_count += 1
                if success:
                    succ_count += 1
                else:
                    fail_count += 1

                await save_queue.put((doc_id, url, text, int(success), domain, error))
                work_queue.task_done()

                if crawled_count % 100 == 0 or crawled_count == len(todo):
                    elapsed = time.perf_counter() - start_time
                    spd = crawled_count / elapsed if elapsed > 0 else 0
                    print(f"[{crawled_count:,}/{len(todo):,}] ({crawled_count/len(todo)*100:.1f}%) | Succ: {succ_count:,} | Fail: {fail_count:,} | Speed: {spd:.1f} URLs/s", flush=True)

        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        await work_queue.join()

        for _ in range(self.concurrency):
            await work_queue.put(None)
        await asyncio.gather(*workers)

        await sess_local.close()
        await sess_proxy.close()

        await save_queue.put(None)
        await writer_task

        total_elapsed = time.perf_counter() - start_time
        print(f"\n[Done] Processed {crawled_count:,} URLs in {total_elapsed:.1f}s (Avg {crawled_count/total_elapsed:.1f} URLs/s) | OK: {succ_count:,} | Fail: {fail_count:,}")
        self.export_jsonl()

def main():
    crawler = RepairCrawler(TARGET_PARQUET, DB_PATH, OUT_JSONL, concurrency=35)
    asyncio.run(crawler.run())

if __name__ == "__main__":
    main()
