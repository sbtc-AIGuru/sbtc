#!/usr/bin/env python3
"""
High-Performance Local Crawler for Vinmec (26,129 articles)
Part of ViBioMIR Corpus Synchronization with Hugging Face main.

Features:
- Concurrency 35 via ThreadPoolExecutor with curl_cffi (impersonate chrome120)
- DOM parser: extracts Title (h1) + Body (.main-col .entry), strips TOC & booking boilerplate
- Complies strictly with ViBioMIR Invariant #3 (clean_to_verbatim)
- SQLite WAL checkpointing + streaming JSONL export
- Resumable anytime without data loss
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
import pyarrow.parquet as pq

# Paths
REPO_ROOT = Path(__file__).resolve().parents[3]
PARQUET_PATH = REPO_ROOT / "newcorpus/links_corpus_vi_en_zh.parquet"
OUT_DIR = REPO_ROOT / "datacrawl/derived"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = OUT_DIR / "vinmec_crawl_checkpoint.sqlite"
JSONL_PATH = OUT_DIR / "data_bosung_vinmec.jsonl"

# Verbatim cleaner regexes
PROTECTED_PATTERN = re.compile(r"\x00([0-9a-f]{2})\x00")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\[[^\]]*\]")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_DEFINITION_PATTERN = re.compile(r"^\s*\[[^\]]+\]:\s*https?://[^\n]*$", re.MULTILINE | re.IGNORECASE)
BARE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
DATA_IMAGE_PATTERN = re.compile(r"data:image/[^\s<>)\]]+", re.IGNORECASE)
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_TAG_PATTERN = re.compile(r"</?[a-zA-Z!][a-zA-Z0-9:_-]*(\s+[^>]*)?>|<!--.*?-->", re.DOTALL)


def clean_to_verbatim(text: str) -> str:
    """Standard ViBioMIR Verbatim Text normalizer."""
    if not text:
        return ""
    ufffd_cnt = text.count("\ufffd")
    if ufffd_cnt > 10 and (ufffd_cnt / len(text)) > 0.15:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<br\b[^>]*>?|<br(?=[^\s>])", " ", text, flags=re.IGNORECASE)
    text = HTML_IMAGE_PATTERN.sub("", text)
    text = MARKDOWN_IMAGE_PATTERN.sub(lambda m: m.group(1), text)
    text = REFERENCE_IMAGE_PATTERN.sub(lambda m: m.group(1), text)
    text = MARKDOWN_LINK_PATTERN.sub(lambda m: m.group(1), text)
    text = REFERENCE_DEFINITION_PATTERN.sub("", text)
    text = BARE_URL_PATTERN.sub("", text)
    text = DATA_IMAGE_PATTERN.sub("", text)
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|?\s*[-:]+[-| :]*\|?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"[*_~`]", "", text)
    text = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>~\"$])", r"\1", text)
    text = PROTECTED_PATTERN.sub(lambda m: chr(int(m.group(1), 16)), text)
    if "\ufffd" in text and (text.count("\ufffd") / max(len(text), 1)) <= 0.02:
        text = text.replace("\ufffd", "")
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


def parse_vinmec_html(html_str: str) -> tuple[str, str]:
    """Extract clean title and article body from Vinmec HTML."""
    soup = BeautifulSoup(html_str, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    entry = (
        soup.select_one(".main-col .entry")
        or soup.find("div", class_="entry")
        or soup.find(class_=lambda c: c and "detail-content" in c)
    )
    if not entry:
        return title, ""

    # Remove non-content elements
    for tag in entry.find_all(["script", "style", "form", "button", "nav", "noscript", "aside"]):
        tag.decompose()

    for tag in entry.find_all(
        class_=lambda c: c
        and any(
            k in str(c).lower()
            for k in [
                "toc",
                "table-of-content",
                "banner",
                "social",
                "share",
                "widget",
                "appointment",
                "feedback",
                "author-info",
            ]
        )
    ):
        tag.decompose()

    text = entry.get_text(separator="\n", strip=True)
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]

    # Strip TOC header if present
    if lines and "mục lục" in lines[0].lower():
        lines = lines[1:]

    # Strip booking / hotline boilerplate at the bottom
    cutoff_idx = len(lines)
    for idx, line in enumerate(lines):
        low = line.lower()
        if any(
            k in low
            for k in [
                "để đặt lịch khám tại viện",
                "quý khách vui lòng bấm số hotline",
                "đặt mua gói dịch vụ",
                "tải và đặt lịch khám tự động trên ứng dụng my vinmec",
                "đặt lịch trực tiếp tại đây",
            ]
        ):
            cutoff_idx = idx
            break

    clean_lines = lines[:cutoff_idx]
    body = "\n\n".join(clean_lines).strip()
    full_text = f"{title}\n\n{body}".strip() if title else body
    return title, clean_to_verbatim(full_text)


class VinmecCrawler:
    def __init__(self, concurrency: int = 35):
        self.concurrency = concurrency
        self.stop_requested = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Init SQLite
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl_records (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                status_code INTEGER,
                text TEXT,
                success INTEGER,
                error TEXT,
                crawled_at TEXT
            );
        """)
        self.conn.commit()

    def _handle_signal(self, signum, frame):
        print(f"\n[!] Signal {signum} received. Gracefully stopping crawler...")
        self.stop_requested = True

    def get_crawled_ids(self) -> set[int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM crawl_records;")
        return {row[0] for row in cursor.fetchall()}

    def fetch_url(self, session: requests.Session, did: int, url: str) -> dict:
        for attempt in range(1, 4):
            try:
                resp = session.get(url, timeout=12)
                code = resp.status_code
                if code == 200:
                    title, text = parse_vinmec_html(resp.text)
                    if len(text) >= 40:
                        return {
                            "id": did,
                            "url": url,
                            "status_code": 200,
                            "text": text,
                            "success": 1,
                            "error": None,
                        }
                    else:
                        return {
                            "id": did,
                            "url": url,
                            "status_code": 200,
                            "text": "",
                            "success": 0,
                            "error": "Empty text after parse",
                        }
                elif code in (404, 410, 500, 502, 503):
                    return {
                        "id": did,
                        "url": url,
                        "status_code": code,
                        "text": "",
                        "success": 0,
                        "error": f"HTTP {code}",
                    }
                else:
                    if attempt == 3:
                        return {
                            "id": did,
                            "url": url,
                            "status_code": code,
                            "text": "",
                            "success": 0,
                            "error": f"HTTP {code}",
                        }
            except Exception as e:
                if attempt == 3:
                    return {
                        "id": did,
                        "url": url,
                        "status_code": -1,
                        "text": "",
                        "success": 0,
                        "error": str(e)[:100],
                    }
            time.sleep(attempt * 0.5)

        return {"id": did, "url": url, "status_code": -1, "text": "", "success": 0, "error": "Max retries exceeded"}

    def run(self):
        print("=" * 70)
        print("🏥 KÍCH HOẠT CRAWLER VINMEC VIETNAM (26.129 URLs)")
        print("=" * 70)

        # 1. Load targets
        table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
        all_ids = table["id"].to_pylist()
        all_urls = table["url"].to_pylist()

        vinmec_targets = [(did, u) for did, u in zip(all_ids, all_urls) if "vinmec.com" in u]
        total_targets = len(vinmec_targets)
        print(f"[*] Tổng số URLs Vinmec mục tiêu trong corpus: {total_targets:,}")

        # 2. Check already completed
        done_ids = self.get_crawled_ids()
        pending = [(did, u) for did, u in vinmec_targets if did not in done_ids]
        print(f"[*] Đã cào trước đó trong DB: {len(done_ids):,} ({len(done_ids)/total_targets*100:.2f}%)")
        print(f"[*] Số lượng cần cào đợt này : {len(pending):,}")

        if not pending:
            print("[✅] Toàn bộ 26.129 URLs Vinmec đã được cào hoàn tất!")
            self.export_jsonl(vinmec_targets)
            return

        # 3. Open JSONL in append mode
        jsonl_fout = open(JSONL_PATH, "a", encoding="utf-8")

        # 4. Multi-thread crawler
        t0 = time.time()
        completed = len(done_ids)
        succ_count = 0
        fail_count = 0
        batch_records = []

        print(f"[*] Bắt đầu cào với concurrency = {self.concurrency} workers...")

        # Worker local session pool
        def worker_task(target):
            did, u = target
            s = requests.Session(impersonate="chrome120")
            return self.fetch_url(s, did, u)

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_target = {executor.submit(worker_task, item): item for item in pending}

            for future in as_completed(future_to_target):
                if self.stop_requested:
                    print("\n[!] Dừng khẩn cấp, đang lưu dữ liệu...")
                    break

                res = future.result()
                res["crawled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                batch_records.append(res)
                completed += 1

                if res["success"]:
                    succ_count += 1
                else:
                    fail_count += 1

                # Flush to JSONL immediately
                jsonl_fout.write(json.dumps(res, ensure_ascii=False) + "\n")

                # Flush to SQLite every 50 records
                if len(batch_records) >= 50:
                    cur = self.conn.cursor()
                    cur.executemany(
                        """
                        INSERT OR REPLACE INTO crawl_records (id, url, status_code, text, success, error, crawled_at)
                        VALUES (:id, :url, :status_code, :text, :success, :error, :crawled_at);
                    """,
                        batch_records,
                    )
                    self.conn.commit()
                    batch_records.clear()

                # Progress log every 200 records or at completion
                if completed % 200 == 0 or completed == total_targets:
                    elapsed = time.time() - t0
                    speed = (completed - len(done_ids)) / max(elapsed, 0.001)
                    rem = total_targets - completed
                    eta_sec = rem / max(speed, 0.001)
                    eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60):02d}s"
                    print(
                        f"[{time.strftime('%H:%M:%S')}] Tiến độ: {completed:,}/{total_targets:,} ({completed/total_targets*100:.1f}%) "
                        f"| Tốc độ: {speed:.1f} URLs/s | OK: {succ_count:,} | Lỗi: {fail_count:,} | ETA: {eta_str}"
                    )

        # Final commit
        if batch_records:
            cur = self.conn.cursor()
            cur.executemany(
                """
                INSERT OR REPLACE INTO crawl_records (id, url, status_code, text, success, error, crawled_at)
                VALUES (:id, :url, :status_code, :text, :success, :error, :crawled_at);
            """,
                batch_records,
            )
            self.conn.commit()
            batch_records.clear()

        jsonl_fout.flush()
        jsonl_fout.close()

        print("\n" + "=" * 70)
        print(f"🎉 HOÀN TẤT LƯỢT CRAWL VINMEC trong {time.time()-t0:.1f}s!")
        print(f"   Tổng đã lưu trong SQLite : {len(self.get_crawled_ids()):,} / {total_targets:,}")
        print("=" * 70)

        # Export canonical JSONL from SQLite
        self.export_jsonl(vinmec_targets)

    def export_jsonl(self, vinmec_targets: list[tuple[int, str]]):
        print(f"[*] Xuất xưởng file JSONL chuẩn từ SQLite -> {JSONL_PATH}...")
        cur = self.conn.cursor()
        cur.execute("SELECT id, url, status_code, text, success, error FROM crawl_records;")
        records_map = {row[0]: row for row in cur.fetchall()}

        written = 0
        succ = 0
        with open(JSONL_PATH, "w", encoding="utf-8") as f:
            for did, u in vinmec_targets:
                if did in records_map:
                    r_id, r_url, r_code, r_text, r_succ, r_err = records_map[did]
                    rec = {
                        "id": r_id,
                        "url": r_url,
                        "status_code": r_code,
                        "text": r_text or "",
                        "success": bool(r_succ),
                        "error": r_err,
                    }
                else:
                    rec = {
                        "id": did,
                        "url": u,
                        "status_code": -1,
                        "text": "",
                        "success": False,
                        "error": "Not crawled",
                    }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                written += 1
                if rec["success"]:
                    succ += 1

        print(f"   Đã xuất đúng {written:,} dòng ({succ:,} thành công — {succ/written*100:.2f}%)")


if __name__ == "__main__":
    crawler = VinmecCrawler(concurrency=35)
    crawler.run()
