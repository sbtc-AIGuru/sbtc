#!/usr/bin/env python3
"""
Overnight Autonomous Crawler for Nhà Thuốc Long Châu (nhathuoclongchau.com.vn).
Designed to crawl ~74k remaining URLs safely overnight with automatic rest intervals,
canary probes, and adaptive circuit breakers.

Operating Strategy:
1. Initial Cooldown: Waits 20 minutes (1200s) for Cloudflare to clear its IP challenge.
2. Canary Probe: Tests 1 request to ensure HTTP 200 OK before starting. If still 403,
   continues waiting in 3-minute increments until fully clear.
3. Batch & Rest Cycles:
   - Crawls in batches of 1,000 URLs at a relaxed, human-safe pace (4.0 - 4.2 req/s).
   - After each batch (~4 mins), sleeps for 2 minutes (120s) to reset Cloudflare's sliding window.
4. Auto-Circuit Breaker:
   - If any 403/429 occurs, trips immediately, pauses all workers, rests for 10-12 minutes,
     verifies with canary probe, and auto-resumes.
5. Atomic Checkpointing: SQLite WAL + streaming JSONL append. Pre-seeds existing successes.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import html
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as sync_requests
from curl_cffi.requests import AsyncSession

# ==============================================================================
# Verbatim Cleaner (Strictly conforming to ViBioMIR LCS token overlap standards)
# ==============================================================================
PROTECTED_PATTERN = re.compile(r"\x00([0-9a-f]{2})\x00")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\[[^\]]*\]")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_DEFINITION_PATTERN = re.compile(r"^\s*\[[^\]]+\]:\s*https?://[^\n]*$", re.MULTILINE | re.IGNORECASE)
BARE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
DATA_IMAGE_PATTERN = re.compile(r"data:image/[^\s<>)\]]+", re.IGNORECASE)
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
LONGCHAU_NEXT_RE = re.compile(r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>", re.DOTALL)
BUILD_ID_RE = re.compile(r"\"buildId\":\"([^\"]+)\"")


def clean_to_verbatim(text: str) -> str:
    """Transform markdown and HTML into 100% verbatim plain text for ViBioMIR."""
    if not text:
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
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|?\s*[-:]+[-| :]*\|?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"[*_~`]", "", text)
    text = PROTECTED_PATTERN.sub(lambda m: chr(int(m.group(1), 16)), text)
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


def parse_nextjs_payload(data: dict) -> tuple[str, str | None]:
    """Extract clean verbatim text from Next.js pageProps JSON payload."""
    props = data.get("pageProps", {})

    # Pattern A: /bai-viet/ article
    detail = props.get("detail", {}).get("data", {})
    if detail:
        title = detail.get("name", "")
        sapo = detail.get("shortDescription", "")
        desc_html = detail.get("description", "")
        desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n\n").strip() if desc_html else ""
        parts = [p for p in [title, sapo, desc_text] if p]
        full_text = "\n\n".join(parts).strip()
        verbatim = clean_to_verbatim(full_text)
        if len(verbatim) >= 40:
            return verbatim, None

    # Pattern B: /benh/ disease page
    benh = props.get("data", {})
    if benh and isinstance(benh, dict):
        title = benh.get("name", "") or benh.get("title", "")
        desc_html = benh.get("description", "") or benh.get("content", "")
        desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n\n").strip() if desc_html else ""
        parts = [p for p in [title, desc_text] if p]
        full_text = "\n\n".join(parts).strip()
        verbatim = clean_to_verbatim(full_text)
        if len(verbatim) >= 40:
            return verbatim, None

    # Pattern C: Generic article in pageProps
    art = props.get("article", {})
    if art and isinstance(art, dict):
        title = art.get("title", "") or art.get("name", "")
        desc = art.get("content", "") or art.get("description", "")
        desc_text = BeautifulSoup(desc, "html.parser").get_text(separator="\n\n").strip() if desc else ""
        parts = [p for p in [title, desc_text] if p]
        full_text = "\n\n".join(parts).strip()
        verbatim = clean_to_verbatim(full_text)
        if len(verbatim) >= 40:
            return verbatim, None

    return "", "Text too short or empty in Next.js props"


def extract_html_fallback(html_text: str) -> tuple[str, str | None]:
    """Fallback extractor from raw HTML string via __NEXT_DATA__ or DOM."""
    if not html_text or len(html_text) < 300:
        return "", "HTML too short"

    m = LONGCHAU_NEXT_RE.search(html_text)
    if m:
        try:
            payload = json.loads(m.group(1))
            verbatim, err = parse_nextjs_payload(payload)
            if verbatim:
                return verbatim, None
        except Exception:
            pass

    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
        t.decompose()

    h1 = soup.find("h1")
    title = clean_to_verbatim(h1.get_text(strip=True)) if h1 else ""

    content_div = (
        soup.find(class_=re.compile(r"post-content|article-content|detail-content|content|main-content", re.I)) or
        soup.find(id=re.compile(r"post-content|article-content|content", re.I)) or
        soup.find("article") or
        soup.find("main")
    )

    if content_div:
        for noise in content_div.find_all(class_=re.compile(r"related|share|tag|author|comment|social|adv|banner|suggest", re.I)):
            noise.decompose()
        body_text = content_div.get_text(separator="\n\n", strip=True)
    else:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        body_text = "\n\n".join(paragraphs)

    full_text = f"{title}\n\n{body_text}" if title else body_text
    verbatim = clean_to_verbatim(full_text)

    if len(verbatim) >= 40:
        return verbatim, None
    return "", f"Text too short ({len(verbatim)} chars)"


class AsyncRateLimiter:
    def __init__(self, rate: float):
        self.rate = rate
        self.interval = 1.0 / rate if rate > 0 else 0
        self.last = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            wait = self.last + self.interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self.last = time.monotonic()


class CircuitBreaker:
    def __init__(self):
        self.pause_until = 0.0
        self.lock = asyncio.Lock()
        self.trip_count = 0

    def is_paused(self) -> bool:
        return time.time() < self.pause_until

    async def wait_if_paused(self):
        while time.time() < self.pause_until:
            rem = self.pause_until - time.time()
            if rem > 0:
                await asyncio.sleep(min(rem, 5.0))

    async def trip(self, cooldown: float, reason: str = "HTTP 403/429"):
        async with self.lock:
            self.trip_count += 1
            now = time.time()
            new_until = now + cooldown
            if new_until > self.pause_until:
                self.pause_until = new_until
                ts = datetime.fromtimestamp(new_until).strftime('%H:%M:%S')
                print(f"\n⚠️  [CIRCUIT BREAKER #{self.trip_count}] Tripped ({reason})! Entering deep cooldown for {cooldown/60:.1f}m until {ts}...", flush=True)


class OvernightLongChauCrawler:
    def __init__(
        self,
        target_file: Path,
        db_path: Path,
        jsonl_path: Path,
        log_path: Path,
        batch_size: int = 1000,
        batch_rest: int = 120,
        rate: float = 4.2,
        concurrency: int = 6,
        timeout: int = 15,
        initial_wait: int = 1200,
    ):
        self.target_file = target_file
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.log_path = log_path
        self.batch_size = batch_size
        self.batch_rest = batch_rest
        self.rate = rate
        self.concurrency = concurrency
        self.timeout = timeout
        self.initial_wait = initial_wait

        self.rate_limiter = AsyncRateLimiter(rate)
        self.breaker = CircuitBreaker()
        self.build_id = "3Dqz_e7TVxL9dSgSOS83-"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_sqlite()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def init_sqlite(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crawl_records (
                id INTEGER PRIMARY KEY,
                row_index INTEGER,
                url TEXT NOT NULL,
                text TEXT,
                success INTEGER NOT NULL,
                error TEXT,
                crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()

    def preseed_existing_records(self):
        """Pre-seed existing successes from JSONL files into the DB."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        total_seeded = 0

        files_to_check = [
            Path("datacrawl/derived/bosung/data_bosung_longchau.jsonl"),
            Path("datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl"),
        ]

        for fpath in files_to_check:
            if not fpath.exists():
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("success"):
                            cur.execute("""
                                INSERT OR IGNORE INTO crawl_records (id, row_index, url, text, success, error)
                                VALUES (?, ?, ?, ?, 1, NULL);
                            """, (rec["id"], rec.get("row_index", 0), rec.get("url", ""), rec.get("text", "")))
                            total_seeded += 1
                    except Exception:
                        pass

        conn.commit()
        conn.close()
        self.log(f"Pre-seeded {total_seeded:,} successes into SQLite checkpoint.")

    def get_crawled_ids(self) -> set[int]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM crawl_records WHERE success = 1 OR error = 'HTTP 404' OR error = 'HTTP 410';")
        crawled = {r[0] for r in cur.fetchall()}
        conn.close()
        return crawled

    def save_record(self, item: dict, text: str, success: bool, error: str | None = None):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO crawl_records (id, row_index, url, text, success, error, crawled_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
        """, (item["id"], item["row_index"], item["url"], text, 1 if success else 0, error))
        conn.commit()
        conn.close()

        if success:
            rec = {
                "id": item["id"],
                "row_index": item["row_index"],
                "url": item["url"],
                "text": text,
                "success": True,
                "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def run_canary_probe(self) -> bool:
        """Synchronously probe the homepage to verify IP is unblocked."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        try:
            r = sync_requests.get("https://nhathuoclongchau.com.vn/", headers=headers, impersonate="chrome120", timeout=10)
            if r.status_code == 200:
                m = BUILD_ID_RE.search(r.text)
                if m:
                    self.build_id = m.group(1)
                return True
            return False
        except Exception:
            return False

    async def wait_for_ip_clear(self):
        """Wait until homepage returns HTTP 200 OK before proceeding."""
        if self.initial_wait > 0:
            self.log(f"Entering initial cooldown: waiting {self.initial_wait / 60:.1f} minutes ({self.initial_wait}s)...")
            remaining = self.initial_wait
            while remaining > 0:
                step = min(remaining, 60)
                await asyncio.sleep(step)
                remaining -= step
                if remaining > 0 and remaining % 300 == 0:
                    self.log(f"Cooldown in progress: {remaining / 60:.1f}m remaining...")

        self.log("Running Canary Probe to test IP status...")
        probe_count = 0
        while True:
            probe_count += 1
            ok = self.run_canary_probe()
            if ok:
                self.log(f"✅ Canary Probe PASSED (HTTP 200 OK)! BuildId: {self.build_id}. IP is clean and ready.")
                break
            else:
                self.log(f"⏳ Canary Probe #{probe_count} returned 403/Blocked. Sleeping 120s before next probe...")
                await asyncio.sleep(120)

    async def fetch_item(self, session: AsyncSession, item: dict, sem: asyncio.Semaphore) -> bool:
        url = item["url"]
        p = urlparse(url).path
        slug = p.strip("/").split("/")[-1]
        is_bai_viet = "/bai-viet/" in url
        is_benh = "/benh/" in url

        headers_json = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://nhathuoclongchau.com.vn/",
        }
        headers_html = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://nhathuoclongchau.com.vn/",
        }

        async with sem:
            for attempt in range(3):
                await self.breaker.wait_if_paused()
                await self.rate_limiter.acquire()
                await asyncio.sleep(random.uniform(0.04, 0.12))

                try:
                    # Strategy 1: Next.js JSON API (CDN Cached)
                    if is_bai_viet or is_benh:
                        route_type = "bai-viet" if is_bai_viet else "benh"
                        next_url = f"https://nhathuoclongchau.com.vn/_next/data/{self.build_id}/{route_type}/{slug}.json"
                        resp = await session.get(next_url, headers=headers_json, timeout=self.timeout)

                        if resp.status_code == 200:
                            try:
                                payload = resp.json()
                                verbatim, err = parse_nextjs_payload(payload)
                                if verbatim:
                                    self.save_record(item, verbatim, True, None)
                                    return True
                            except Exception:
                                pass

                        elif resp.status_code == 429:
                            cooldown = float(resp.headers.get("retry-after", 180))
                            await self.breaker.trip(min(max(cooldown, 60), 600), "HTTP 429 on Next.js API")
                            continue

                        elif resp.status_code == 403:
                            await self.breaker.trip(600, "HTTP 403 Cloudflare Challenge")
                            continue

                    # Strategy 2: HTML Fallback
                    resp_html = await session.get(url, headers=headers_html, timeout=self.timeout)
                    if resp_html.status_code == 200:
                        verbatim, err = extract_html_fallback(resp_html.text)
                        if verbatim:
                            self.save_record(item, verbatim, True, None)
                            return True
                        else:
                            self.save_record(item, "", False, err)
                            return False

                    elif resp_html.status_code in [404, 410]:
                        self.save_record(item, "", False, f"HTTP {resp_html.status_code}")
                        return False

                    elif resp_html.status_code == 429:
                        cooldown = float(resp_html.headers.get("retry-after", 180))
                        await self.breaker.trip(min(max(cooldown, 60), 600), "HTTP 429 on HTML")
                        continue

                    elif resp_html.status_code == 403:
                        await self.breaker.trip(600, "HTTP 403 Cloudflare Challenge on HTML")
                        continue

                except Exception as e:
                    if attempt == 2:
                        self.save_record(item, "", False, str(e))
                        return False
                    await asyncio.sleep(1.5)

            return False

    async def run(self):
        self.log(f"=== KHỞI ĐỘNG CRAWLER XUYÊN ĐÊM LONG CHÂU ===")
        self.log(f"Target file: {self.target_file}")
        with open(self.target_file, "r", encoding="utf-8") as f:
            all_targets = json.load(f)

        self.preseed_existing_records()
        crawled_ids = self.get_crawled_ids()
        pending = [it for it in all_targets if it["id"] not in crawled_ids]

        self.log(f"Tổng URLs BTC: {len(all_targets):,} | Đã xong: {len(crawled_ids):,} | Còn lại: {len(pending):,}")
        if not pending:
            self.log("🎉 Toàn bộ dữ liệu Long Châu đã hoàn tất 100%!")
            return

        # Phase 1: Wait for cooldown & Canary probe
        await self.wait_for_ip_clear()

        # Phase 2: Autonomous Batching Loop
        total_pending = len(pending)
        total_success = 0
        total_done = 0
        batch_idx = 0
        t_global = time.time()

        # Chunk pending into batches
        batches = [pending[i:i + self.batch_size] for i in range(0, len(pending), self.batch_size)]
        self.log(f"Phân chia: {len(batches)} batches (mỗi batch {self.batch_size:,} bài, nghỉ {self.batch_rest}s giữa các batch)")

        sem = asyncio.Semaphore(self.concurrency)

        async with AsyncSession(impersonate="chrome120") as session:
            for b_items in batches:
                batch_idx += 1
                b_total = len(b_items)
                self.log(f"\n--- BẮT ĐẦU BATCH {batch_idx}/{len(batches)} ({b_total:,} bài) ---")

                t_batch = time.time()
                b_done = 0
                b_ok = 0

                tasks = [asyncio.create_task(self.fetch_item(session, it, sem)) for it in b_items]

                for fut in asyncio.as_completed(tasks):
                    ok = await fut
                    b_done += 1
                    total_done += 1
                    if ok:
                        b_ok += 1
                        total_success += 1

                    if b_done % 100 == 0 or b_done == b_total:
                        el_b = time.time() - t_batch
                        spd_b = b_done / el_b if el_b > 0 else 0
                        pct_global = (total_done / total_pending) * 100
                        rem_items = total_pending - total_done
                        el_g = time.time() - t_global
                        spd_g = total_done / el_g if el_g > 0 else 0
                        eta_m = (rem_items / spd_g) / 60 if spd_g > 0 else 0

                        self.log(
                            f"[Batch {batch_idx}] {b_done:,}/{b_total:,} | Speed: {spd_b:.1f} u/s | "
                            f"Toàn bộ: {total_done:,}/{total_pending:,} ({pct_global:.1f}%) | "
                            f"OK: {total_success:,} | ETA: {eta_m:.1f}m"
                        )

                el_b = time.time() - t_batch
                self.log(f"Hoàn thành Batch {batch_idx}/{len(batches)}: OK {b_ok:,}/{b_total:,} trong {el_b / 60:.1f}m.")

                # If more batches remain, enter inter-batch rest
                if batch_idx < len(batches):
                    self.log(f"💤 Nghỉ xả hơi {self.batch_rest}s để reset Cloudflare sliding window trước khi vào batch tiếp...")
                    await asyncio.sleep(self.batch_rest)

        total_elapsed = time.time() - t_global
        self.log(f"\n🎉 HOÀN TẤT TOÀN DIỆN CRAWLER XUYÊN ĐÊM trong {total_elapsed / 3600:.1f} giờ! Thành công: {total_success:,}/{total_pending:,}")


def main():
    parser = argparse.ArgumentParser(description="Overnight Autonomous Long Chau Crawler")
    parser.add_argument("--targets", type=str, default="datacrawl/kaggle_longchau/longchau_missing_all.json")
    parser.add_argument("--db", type=str, default="datacrawl/derived/bosung/longchau_ironclad_checkpoint.sqlite")
    parser.add_argument("--out-jsonl", type=str, default="datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl")
    parser.add_argument("--log", type=str, default="datacrawl/derived/bosung/longchau_overnight.log")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size (default: 1000)")
    parser.add_argument("--batch-rest", type=int, default=120, help="Rest in seconds between batches (default: 120s = 2m)")
    parser.add_argument("--rate", type=float, default=4.2, help="Request rate (default: 4.2 req/s)")
    parser.add_argument("--concurrency", type=int, default=6, help="Concurrency workers (default: 6)")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout (default: 15s)")
    parser.add_argument("--initial-wait", type=int, default=1200, help="Initial cooldown wait in seconds (default: 1200s = 20m)")

    args = parser.parse_args()

    crawler = OvernightLongChauCrawler(
        target_file=Path(args.targets),
        db_path=Path(args.db),
        jsonl_path=Path(args.out_jsonl),
        log_path=Path(args.log),
        batch_size=args.batch_size,
        batch_rest=args.batch_rest,
        rate=args.rate,
        concurrency=args.concurrency,
        timeout=args.timeout,
        initial_wait=args.initial_wait,
    )

    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
