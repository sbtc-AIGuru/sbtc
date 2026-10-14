"""Hybrid High-Throughput Crawler for zysjonline.com (Cloudflare Turnstile Solver + curl_cffi Chrome TLS Workers).

Architecture:
1. TurnstileSessionManager uses Patchright (binary-patched Chromium) to solve
   Cloudflare Turnstile with natural mouse trajectory and harvest cf_clearance.
2. Async Worker Pool uses curl_cffi AsyncSession (impersonate="chrome124") to fetch pages
   with 100% matched Chrome TLS fingerprint and HTTP/2 settings.
3. Domain-specific cookie filtering isolates .zysjonline.com clearance token.
4. Autonomous Circuit Breaker probes IP status every 3 minutes if Cloudflare WAF triggers cooldown.
5. SQLite checkpointing ensures 100% crash resilience, atomic writes, and seamless resume.
6. Content extraction outputs 100% Verbatim Plain Text conforming to ViBioMIR invariants.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession
from patchright.async_api import async_playwright
import pyarrow.parquet as pq

# Import repository verbatim cleaner
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Scripts" / "Preprocess"))
sys.path.insert(0, str(REPO_ROOT / "Scripts" / "Clawler"))
from verbatim import clean_to_verbatim  # type: ignore

# Matched User-Agent for Chrome 124 TLS Impersonation
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
OUTPUT_DIR = REPO_ROOT.parent / "datacrawl" / "derived"
OUTPUT_JSONL = OUTPUT_DIR / "crawled_phase1_priority2_zysjonline.jsonl"
CHECKPOINT_DB = OUTPUT_DIR / "zysj_crawl_checkpoint.sqlite"

DOMAIN = "zysjonline.com"
START_INDEX = 4_151_371
END_INDEX = 4_394_717  # inclusive, total 243,347 URLs
LOG_FILE = OUTPUT_DIR / "zysj_crawler.log"


def log(msg: str):
    """Safely log to stdout and append to file, ignoring terminal detach/IO errors."""
    try:
        sys.stdout.write(f"{msg}\n")
        sys.stdout.flush()
    except Exception:
        pass
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


class TurnstileSessionManager:
    """Manages Cloudflare Turnstile bypass and cf_clearance cookie lifecycle."""

    def __init__(self, user_agent: str = DEFAULT_UA):
        self.user_agent = user_agent
        self.cookies: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._last_solve_time: float = 0.0

    async def natural_click(self, page, elem):
        """Perform human-like Bezier curve mouse movement and click."""
        box = await elem.bounding_box()
        if not box:
            return
        click_x = box["x"] + random.uniform(22, 28)
        click_y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)

        cur_x = random.randint(100, 300)
        cur_y = random.randint(100, 200)
        await page.mouse.move(cur_x, cur_y)
        await asyncio.sleep(0.05)

        steps = 10
        for i in range(1, steps + 1):
            ix = cur_x + (click_x - cur_x) * (i / steps) + random.uniform(-2, 2)
            iy = cur_y + (click_y - cur_y) * (i / steps) + random.uniform(-2, 2)
            await page.mouse.move(ix, iy)
            await asyncio.sleep(0.02)

        await page.mouse.move(click_x, click_y)
        await asyncio.sleep(0.15)
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.06, 0.12))
        await page.mouse.up()

    def apply_cookies_to_session(self, session: AsyncSession):
        """Set cookies with domain '.zysjonline.com' so libcurl attaches them to outgoing requests."""
        session.cookies.clear()
        for name, value in self.cookies.items():
            session.cookies.set(name, value, domain=".zysjonline.com")

    async def solve_turnstile(
        self,
        target_url: str | None = None,
        req_time: float | None = None,
        force: bool = False,
    ) -> dict[str, str]:
        """Solve Turnstile with Patchright and return cookies."""
        async with self._lock:
            if self.cookies and "cf_clearance" in self.cookies and not force:
                if req_time is not None and self._last_solve_time > req_time:
                    return self.cookies
                elif req_time is None and (time.time() - self._last_solve_time < 30):
                    return self.cookies

            log(f"[{datetime.now().strftime('%H:%M:%S')}] [Solver] Launching Patchright to solve Turnstile...")
            t0 = time.time()
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ]
                )
                context = await browser.new_context(
                    user_agent=self.user_agent,
                    locale="zh-CN",
                    viewport={"width": 1366, "height": 768}
                )
                page = await context.new_page()

                try:
                    home_url = "https://zysjonline.com/"
                    for goto_attempt in range(3):
                        try:
                            await page.goto(home_url, wait_until="domcontentloaded", timeout=25000)
                            break
                        except Exception as e_goto:
                            if goto_attempt < 2:
                                log(f"[{datetime.now().strftime('%H:%M:%S')}] [Solver] Homepage navigation glitch ({e_goto}). Retrying in 2s...")
                                await asyncio.sleep(2)
                            else:
                                raise e_goto

                    # Click Turnstile checkbox if challenge frame is present
                    for i in range(25):
                        await asyncio.sleep(1)
                        for f in page.frames:
                            if "challenges.cloudflare.com" in f.url:
                                try:
                                    elem = await f.frame_element()
                                    if elem:
                                        box = await elem.bounding_box()
                                        if box:
                                            await page.mouse.click(box["x"] + 25, box["y"] + box["height"] / 2)
                                except Exception:
                                    pass
                        try:
                            t = await page.title()
                            if t and "请稍候" not in t and "Just a moment" not in t and "Loading" not in t and "403" not in t:
                                cookies_list = await context.cookies()
                                new_cookies = {c["name"]: c["value"] for c in cookies_list if "zysjonline.com" in c.get("domain", "")}
                                if "cf_clearance" in new_cookies:
                                    break
                        except Exception:
                            pass

                    # Wait 1.5s for cookies to finalize
                    await asyncio.sleep(1.5)
                    cookies_list = await context.cookies()
                    new_cookies = {c["name"]: c["value"] for c in cookies_list if "zysjonline.com" in c.get("domain", "")}

                    if "cf_clearance" in new_cookies:
                        self.cookies = new_cookies
                        self._last_solve_time = time.time()
                        log(
                            f"[{datetime.now().strftime('%H:%M:%S')}] [Solver] Turnstile solved successfully in "
                            f"{time.time() - t0:.2f}s! ({len(new_cookies)} cookies acquired: {list(new_cookies.keys())})"
                        )
                        return self.cookies
                    else:
                        log(f"[{datetime.now().strftime('%H:%M:%S')}] [Solver] Warning: cf_clearance not acquired!")
                        return {}
                except Exception as e:
                    log(f"[{datetime.now().strftime('%H:%M:%S')}] [Solver] Error during Turnstile solve: {e}")
                    return {}
                finally:
                    await browser.close()

            return {}


def extract_verbatim_text(html_content: str, url: str) -> tuple[bool, str, str]:
    """Extract clean verbatim article text from zysjonline HTML.

    Returns:
        (success: bool, text: str, error: str)
    """
    if not html_content or len(html_content) < 50:
        return False, "", "Empty response body"

    soup = BeautifulSoup(html_content, "html.parser")

    # Check for error or 404 pages
    title_tag = soup.find("title")
    title_str = title_tag.get_text(strip=True) if title_tag else ""
    if "页面未找到" in title_str or "404" in title_str:
        return False, "", "HTTP 404: 页面未找到"
    if "请稍候" in title_str or "Just a moment" in title_str:
        return False, "", "Cloudflare challenge page detected"

    # Remove boilerplate elements
    for selector in ["aside", "nav", "header", "footer", "dialog", "script", "style", ".sticky", "noscript", "svg"]:
        for tag in soup.select(selector):
            tag.decompose()

    # Determine heading
    h1_tag = soup.find("h1")
    heading = h1_tag.get_text(strip=True) if h1_tag else ""
    if not heading and title_str:
        heading = re.sub(r"\s*-\s*中医世家.*$", "", title_str).strip()

    body_text = ""
    # Case A: Articles (articles/misc/...)
    article_tag = soup.find("article")
    if article_tag:
        content_box = article_tag.find("div", class_=lambda c: c and ("leading-8" in c or "space-y-4" in c))
        if content_box:
            body_text = content_box.get_text("\n\n", strip=True)
        else:
            body_text = article_tag.get_text("\n\n", strip=True)

    # Case B: Books / Classics (books/...)
    if not body_text:
        main_tag = soup.find("main")
        if main_tag:
            content_div = main_tag.find("div", class_=lambda c: c and "min-w-0" in c)
            if content_div:
                body_text = content_div.get_text("\n\n", strip=True)
            else:
                body_text = main_tag.get_text("\n\n", strip=True)

    if not body_text:
        body_text = soup.get_text("\n\n", strip=True)

    # Combine heading and body
    full_raw = f"{heading}\n\n{body_text}".strip() if heading and heading not in body_text else body_text.strip()
    verbatim_text = clean_to_verbatim(full_raw)

    if len(verbatim_text) < 10:
        return False, "", f"Article text too short ({len(verbatim_text)} chars)"

    return True, verbatim_text, ""


class SQLiteCheckpoint:
    """Thread-safe SQLite storage for crash resilience and resume."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawled_records (
                    row_index INTEGER PRIMARY KEY,
                    id INTEGER,
                    url TEXT,
                    success INTEGER,
                    text TEXT,
                    error TEXT,
                    timestamp TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_success ON crawled_records(success)")
            conn.commit()

    def get_crawled_indices(self) -> set[int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT row_index FROM crawled_records WHERE success = 1 OR error LIKE 'HTTP 404%' OR error LIKE 'Article text too short%'")
            return {row[0] for row in cursor.fetchall()}

    def save_batch(self, batch: list[tuple[int, int, str, bool, str, str]]):
        now_str = datetime.now().isoformat()
        definitive_records = [
            (row_idx, doc_id, url, 1 if success else 0, text, error, now_str)
            for row_idx, doc_id, url, success, text, error in batch
            if success or "404" in error or "too short" in error
        ]
        if not definitive_records:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO crawled_records (row_index, id, url, success, text, error, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, definitive_records)
            conn.commit()

    def get_stats(self) -> tuple[int, int, int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(success) FROM crawled_records")
            row = cursor.fetchone()
            total = row[0] or 0
            success = row[1] or 0
            return total, success, total - success

    def export_to_jsonl(self, jsonl_path: Path, expected_total: int | None = None):
        """Export all crawled records in exact row_index order to JSONL."""
        import json
        log(f"Exporting database records to {jsonl_path} in ascending row_index order...")
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT row_index, id, url, success, text, error FROM crawled_records ORDER BY row_index ASC")
            with open(jsonl_path, "w", encoding="utf-8") as f:
                for row_idx, doc_id, url, succ, text, err in cursor:
                    obj = {
                        "row_index": row_idx,
                        "id": doc_id,
                        "url": url,
                        "success": bool(succ),
                        "text": text if succ else "",
                        "error": err if not succ else "",
                    }
                    f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    count += 1
                    if succ:
                        success_count += 1

        log(f"Export complete: {count} records written ({success_count} success). Target path: {jsonl_path}")


async def crawl_single_record(
    session: AsyncSession,
    session_mgr: TurnstileSessionManager,
    row_idx: int,
    doc_id: int,
    url: str,
    semaphore: asyncio.Semaphore,
) -> tuple[int, int, str, bool, str, str]:
    """Fetch and parse one record with curl_cffi AsyncSession and auto re-challenge handling."""
    max_retries = 3
    headers = {
        "User-Agent": session_mgr.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://zysjonline.com/",
    }

    async with semaphore:
        for attempt in range(max_retries):
            req_time = time.time()
            try:
                # Pacing jitter to prevent rate-limit bursts
                await asyncio.sleep(random.uniform(0.20, 0.35))
                resp = await session.get(url, headers=headers, timeout=12.0)

                # Case 1: Cloudflare challenge re-triggered
                if resp.status_code == 403 or "请稍候" in resp.text[:500] or "Just a moment" in resp.text[:500]:
                    return row_idx, doc_id, url, False, "", "Cloudflare WAF 403 / re-challenge"

                # Case 2: 404 Not Found
                if resp.status_code == 404:
                    return row_idx, doc_id, url, False, "", "HTTP 404: 页面不存在"

                # Case 3: Other HTTP error
                if resp.status_code != 200:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    return row_idx, doc_id, url, False, "", f"HTTP {resp.status_code}"

                # Success response: extract verbatim text
                success, text, error = extract_verbatim_text(resp.text, url)
                return row_idx, doc_id, url, success, text, error

            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return row_idx, doc_id, url, False, "", f"Error: {type(e).__name__} {e}"

    return row_idx, doc_id, url, False, "", "Max retries exceeded"


async def probe_ip_status(session_mgr: TurnstileSessionManager, test_url: str | None = None) -> dict[str, str]:
    """Autonomous probe loop that checks IP cooldown every 3 minutes."""
    probe_attempt = 1
    while True:
        log(f"[{datetime.now().strftime('%H:%M:%S')}] [Probe #{probe_attempt}] Checking Cloudflare WAF status...")
        cookies = await session_mgr.solve_turnstile(target_url=test_url, force=True)
        if cookies and "cf_clearance" in cookies:
            log(f"[{datetime.now().strftime('%H:%M:%S')}] [Probe] >>> CLOUDFLARE WAF COOLDOWN RELEASED! <<<")
            return cookies
        log(f"[{datetime.now().strftime('%H:%M:%S')}] [Probe] WAF cooldown still active. Sleeping 3m before next probe...")
        probe_attempt += 1
        await asyncio.sleep(180)


async def run_crawler(limit: int | None = None, concurrency: int = 8, batch_save_size: int = 50):
    """Main crawler entrypoint using curl_cffi Chrome TLS Impersonation."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint = SQLiteCheckpoint(CHECKPOINT_DB)

    # 1. Read targets from parquet
    log(f"Reading target records from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH)
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    # Filter targets for zysjonline.com in [START_INDEX, END_INDEX]
    targets = []
    for idx in range(START_INDEX, min(END_INDEX + 1, len(urls))):
        if DOMAIN in urls[idx]:
            targets.append((idx, ids[idx], urls[idx]))

    total_targets = len(targets)
    log(f"Total targets identified in parquet: {total_targets} URLs (indices {START_INDEX} -> {END_INDEX})")

    # Filter out already crawled records from checkpoint
    crawled_set = checkpoint.get_crawled_indices()
    pending_targets = [t for t in targets if t[0] not in crawled_set]
    log(f"Already crawled in SQLite checkpoint: {len(crawled_set)} records.")
    log(f"Pending to crawl: {len(pending_targets)} records.")

    if limit is not None:
        pending_targets = pending_targets[:limit]
        log(f"Applied limit: processing {len(pending_targets)} records.")

    if not pending_targets:
        log("All targets already crawled! Exporting to JSONL...")
        checkpoint.export_to_jsonl(OUTPUT_JSONL, expected_total=total_targets)
        return

    # 2. Initialize Session Manager & Solve Turnstile (with autonomous probe)
    session_mgr = TurnstileSessionManager(user_agent=DEFAULT_UA)
    initial_target_url = pending_targets[0][2] if pending_targets else None
    cookies = await session_mgr.solve_turnstile(target_url=initial_target_url)
    if not cookies or "cf_clearance" not in cookies:
        log("[CircuitBreaker] Initial solve did not acquire cf_clearance. Entering autonomous cooldown probe...")
        cookies = await probe_ip_status(session_mgr, test_url=initial_target_url)

    # 3. Setup Async curl_cffi Worker Session
    semaphore = asyncio.Semaphore(concurrency)

    # 4. Process in chunked batches
    start_time = time.time()
    processed_count = 0
    success_count = 0
    failed_count = 0

    session = AsyncSession(impersonate="chrome124")
    session_mgr.apply_cookies_to_session(session)

    try:
        batch_idx = 0
        while batch_idx < len(pending_targets):
            batch_targets = pending_targets[batch_idx : batch_idx + batch_save_size]
            tasks = [
                crawl_single_record(session, session_mgr, row_idx, doc_id, url, semaphore)
                for row_idx, doc_id, url in batch_targets
            ]

            results = await asyncio.gather(*tasks)
            batch_success = sum(1 for r in results if r[3])
            batch_failed = len(results) - batch_success
            has_transient_error = any(
                ("WAF" in r[5] or "Cloudflare" in r[5] or "403" in r[5] or "Max retries" in r[5] or "Error:" in r[5])
                for r in results if not r[3] and not ("404" in r[5] or "too short" in r[5])
            )

            # Circuit breaker: if batch encountered WAF re-challenge or transient errors, NEVER skip batch!
            if batch_failed > 0 and has_transient_error:
                log(f"[{datetime.now().strftime('%H:%M:%S')}] [CircuitBreaker] Batch hit {batch_failed}/{len(batch_targets)} transient/WAF errors. Resolving session & retrying batch...")
                await probe_ip_status(session_mgr, test_url=batch_targets[0][2])
                try:
                    await session.close()
                except Exception:
                    pass
                session = AsyncSession(impersonate="chrome124")
                session_mgr.apply_cookies_to_session(session)
                continue

            # Save batch to SQLite (only definitive successes or permanent errors)
            checkpoint.save_batch(results)

            processed_count += len(results)
            success_count += batch_success
            failed_count += batch_failed
            batch_idx += len(batch_targets)

            elapsed = time.time() - start_time
            rate = processed_count / elapsed if elapsed > 0 else 0
            eta_seconds = (len(pending_targets) - processed_count) / rate if rate > 0 else 0
            eta_minutes = eta_seconds / 60

            log(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Progress: {processed_count}/{len(pending_targets)} ({processed_count/len(pending_targets)*100:.1f}%) | "
                f"Speed: {rate:.1f} URLs/s | Success: {success_count} | Failed: {failed_count} | "
                f"ETA: {eta_minutes:.1f}m"
            )

            # Incremental JSONL snapshot & proactive session recycling every 2,500 records
            if processed_count > 0 and processed_count % 2500 == 0:
                try:
                    checkpoint.export_to_jsonl(OUTPUT_JSONL)
                except Exception as ex:
                    log(f"Warning: Incremental JSONL export failed: {ex}")
                log(f"[{datetime.now().strftime('%H:%M:%S')}] [SessionRecycle] Proactively recycling AsyncSession connection pool...")
                try:
                    await session.close()
                except Exception:
                    pass
                session = AsyncSession(impersonate="chrome124")
                session_mgr.apply_cookies_to_session(session)
    finally:
        try:
            await session.close()
        except Exception:
            pass

    # Export to JSONL after completion
    total_db, succ_db, fail_db = checkpoint.get_stats()
    log(f"\nCrawling session completed! Total in DB: {total_db} (Success: {succ_db}, Failed: {fail_db})")
    checkpoint.export_to_jsonl(OUTPUT_JSONL, expected_total=total_targets)


def main():
    parser = argparse.ArgumentParser(description="Hybrid Crawler for zysjonline.com (curl_cffi Chrome TLS)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of pending records to crawl")
    parser.add_argument("--concurrency", type=int, default=3, help="Number of concurrent async curl_cffi workers")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch save size for SQLite commits")
    parser.add_argument("--export-only", action="store_true", help="Only export existing SQLite DB to JSONL")
    args = parser.parse_args()

    if args.export_only:
        cp = SQLiteCheckpoint(CHECKPOINT_DB)
        cp.export_to_jsonl(OUTPUT_JSONL)
        return

    asyncio.run(run_crawler(limit=args.limit, concurrency=args.concurrency, batch_save_size=args.batch_size))


if __name__ == "__main__":
    main()
