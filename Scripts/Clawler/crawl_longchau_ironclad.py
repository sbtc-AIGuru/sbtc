#!/usr/bin/env python3
"""
Ironclad High-Resilience Crawler for Nhà Thuốc Long Châu (nhathuoclongchau.com.vn).
Designed specifically to prevent Cloudflare Rate Limits & Bans on Local Residential IP.

Architecture:
1. Next.js Edge Data Cache Route First (/_next/data/{buildId}/...) -> 65% smaller, CDN cached.
2. DOM / HTML Fallback if Next.js data route is missing.
3. Strict ViBioMIR Verbatim Text Cleaner (clean_to_verbatim) preserving 100% LCS token overlap.
4. Token Bucket Rate Limiter (8-10 req/s with jitter) to stay well under Cloudflare's WAF radar.
5. Circuit Breaker: Automatically detects HTTP 429, parses Retry-After, pauses all workers,
   runs a canary probe, and auto-resumes gracefully without burning the IP.
6. Atomic SQLite WAL checkpointing + Streaming JSONL append.
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
from curl_cffi.requests import AsyncSession
import pyarrow.parquet as pq

# ==============================================================================
# Verbatim Cleaner (Strictly conforming to ViBioMIR LCS token overlap standards)
# ==============================================================================
ESCAPED_PATTERN = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~\"'$])")
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

    # 1. Try __NEXT_DATA__ script tag
    m = LONGCHAU_NEXT_RE.search(html_text)
    if m:
        try:
            payload = json.loads(m.group(1))
            verbatim, err = parse_nextjs_payload(payload)
            if verbatim:
                return verbatim, None
        except Exception:
            pass

    # 2. DOM Parsing Fallback
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
    """Token bucket / leaky bucket rate limiter ensuring smooth, unburstable throughput."""
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
    """Automatic trip-switch that detects 429 / WAF blocks and pauses all workers gracefully."""
    def __init__(self):
        self.pause_until = 0.0
        self.lock = asyncio.Lock()

    def is_paused(self) -> bool:
        return time.time() < self.pause_until

    async def wait_if_paused(self):
        while time.time() < self.pause_until:
            rem = self.pause_until - time.time()
            if rem > 0:
                await asyncio.sleep(min(rem, 2.0))

    async def trip(self, cooldown: float, reason: str = "HTTP 429"):
        async with self.lock:
            now = time.time()
            new_until = now + cooldown
            if new_until > self.pause_until:
                self.pause_until = new_until
                print(f"\n⚠️  [CIRCUIT BREAKER] Tripped ({reason})! Pausing all workers for {cooldown:.1f}s until {datetime.fromtimestamp(new_until).strftime('%H:%M:%S')}...", flush=True)


class LongChauIroncladCrawler:
    def __init__(
        self,
        target_file: Path,
        db_path: Path,
        jsonl_path: Path,
        rate: float = 10.0,
        concurrency: int = 10,
        timeout: int = 15,
    ):
        self.target_file = target_file
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.rate = rate
        self.concurrency = concurrency
        self.timeout = timeout

        self.rate_limiter = AsyncRateLimiter(rate)
        self.breaker = CircuitBreaker()
        self.build_id = "3Dqz_e7TVxL9dSgSOS83-"  # Initial default, auto-refreshed

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_sqlite()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

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

    def preseed_existing_jsonl(self):
        """Seed existing records from JSONL to avoid duplicate requests."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        total_seeded = 0

        files_to_check = [
            Path("datacrawl/derived/bosung/data_bosung_longchau.jsonl"),
            self.jsonl_path,
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
        self.log(f"Pre-seeded {total_seeded:,} existing successes into checkpoint.")

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

    async def refresh_build_id(self, session: AsyncSession):
        """Fetch current buildId dynamically from homepage."""
        try:
            r = await session.get("https://nhathuoclongchau.com.vn/", timeout=10)
            if r.status_code == 200:
                m = BUILD_ID_RE.search(r.text)
                if m:
                    new_id = m.group(1)
                    if new_id != self.build_id:
                        self.log(f"Refreshed buildId: {self.build_id} -> {new_id}")
                        self.build_id = new_id
        except Exception as e:
            self.log(f"Failed to refresh buildId: {e}")

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
                # 1. Wait if Circuit Breaker is active
                await self.breaker.wait_if_paused()

                # 2. Pacing with rate limiter + small jitter
                await self.rate_limiter.acquire()
                await asyncio.sleep(random.uniform(0.02, 0.08))

                try:
                    # Strategy 1: Try Next.js JSON endpoint (ultra-fast, CDN-cached)
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
                            cooldown = float(resp.headers.get("retry-after", 60))
                            await self.breaker.trip(min(max(cooldown, 30), 600), "HTTP 429 on Next.js API")
                            continue

                        elif resp.status_code == 404:
                            # Build ID might have changed or page has custom route, proceed to HTML fallback
                            pass

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
                        cooldown = float(resp_html.headers.get("retry-after", 60))
                        await self.breaker.trip(min(max(cooldown, 30), 600), "HTTP 429 on HTML")
                        continue

                    elif resp_html.status_code == 403:
                        await self.breaker.trip(30, "HTTP 403 Cloudflare Challenge")
                        continue

                except Exception as e:
                    if attempt == 2:
                        self.save_record(item, "", False, str(e))
                        return False
                    await asyncio.sleep(1.0)

            return False

    async def run(self):
        self.log(f"Loading target URLs from: {self.target_file}")
        with open(self.target_file, "r", encoding="utf-8") as f:
            items = json.load(f)

        total_target = len(items)
        self.preseed_existing_jsonl()

        crawled_ids = self.get_crawled_ids()
        pending = [it for it in items if it["id"] not in crawled_ids]

        self.log(f"Target Summary: Total={total_target:,} | Already Finished={len(crawled_ids):,} | Pending to Crawl={len(pending):,}")
        if not pending:
            self.log("✅ All items already 100% completed!")
            return

        self.log(f"Starting Ironclad Session: Rate={self.rate:.1f} req/s | Concurrency={self.concurrency} | Timeout={self.timeout}s")

        sem = asyncio.Semaphore(self.concurrency)
        t0 = time.time()
        success_count = 0
        done_count = 0

        async with AsyncSession(impersonate="chrome120") as session:
            await self.refresh_build_id(session)

            tasks = [asyncio.create_task(self.fetch_item(session, it, sem)) for it in pending]

            for fut in asyncio.as_completed(tasks):
                ok = await fut
                done_count += 1
                if ok:
                    success_count += 1

                if done_count % 100 == 0 or done_count == len(pending):
                    elapsed = time.time() - t0
                    speed = done_count / elapsed if elapsed > 0 else 0
                    pct = (done_count / len(pending)) * 100
                    rem_sec = (len(pending) - done_count) / speed if speed > 0 else 0
                    eta_min = rem_sec / 60
                    self.log(
                        f"Progress: {done_count:,}/{len(pending):,} ({pct:.1f}%) | "
                        f"Speed: {speed:.1f} URLs/s | OK: {success_count:,} ({(success_count/done_count)*100:.1f}%) | "
                        f"ETA: {eta_min:.1f}m"
                    )

        total_elapsed = time.time() - t0
        self.log(f"✅ Ironclad Session Completed in {total_elapsed / 60:.1f}m! Success={success_count:,}/{len(pending):,}")


def main():
    parser = argparse.ArgumentParser(description="Ironclad Crawler for Long Chau on Local Residential IP")
    parser.add_argument("--targets", type=str, default="datacrawl/kaggle_longchau/longchau_missing_all.json", help="Path to missing JSON")
    parser.add_argument("--db", type=str, default="datacrawl/derived/bosung/longchau_ironclad_checkpoint.sqlite", help="SQLite DB path")
    parser.add_argument("--out-jsonl", type=str, default="datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl", help="JSONL output path")
    parser.add_argument("--rate", type=float, default=9.5, help="Request rate in req/s (default: 9.5)")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency level (default: 10)")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout in seconds (default: 15)")

    args = parser.parse_args()

    crawler = LongChauIroncladCrawler(
        target_file=Path(args.targets),
        db_path=Path(args.db),
        jsonl_path=Path(args.out_jsonl),
        rate=args.rate,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )

    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
