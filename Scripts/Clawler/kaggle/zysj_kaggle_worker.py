"""Standalone High-Throughput Crawler Worker for Kaggle.
Bypasses Cloudflare Turnstile using Patchright and fetches via curl_cffi with Chrome 124 TLS impersonation.

100% self-contained: no external repo dependencies required.
Solves the Datacenter TLS Fingerprint mismatch and eliminates the Thundering Herd solver stampede.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import html
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import sys
import time

from bs4 import BeautifulSoup
from patchright.async_api import async_playwright
import pyarrow.parquet as pq

# Try importing curl_cffi for authentic Chrome TLS fingerprinting
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ==============================================================================
# Verbatim Cleaning (Strictly conforming to ViBioMIR token LCS overlap standards)
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


def remove_link_targets(text: str) -> str:
    text = HTML_IMAGE_PATTERN.sub("", text)
    text = MARKDOWN_IMAGE_PATTERN.sub(lambda m: m.group(1), text)
    text = REFERENCE_IMAGE_PATTERN.sub(lambda m: m.group(1), text)
    text = MARKDOWN_LINK_PATTERN.sub(lambda m: m.group(1), text)
    text = REFERENCE_DEFINITION_PATTERN.sub("", text)
    text = BARE_URL_PATTERN.sub("", text)
    return DATA_IMAGE_PATTERN.sub("", text)


def clean_to_verbatim(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<br\b[^>]*>?|<br(?=[^\s>])", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[a-zA-Z][^<>]*>", " ", text)
    text = ESCAPED_PATTERN.sub(lambda m: f"\x00{ord(m.group(1)):02x}\x00", text)
    text = remove_link_targets(text)
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


# ==============================================================================
# Logging & Session Management
# ==============================================================================
def log(msg: str, log_file: Path | None = None):
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass


class TurnstileSolver:
    """Solves Cloudflare Turnstile with Patchright and harvests cf_clearance."""

    def __init__(self, user_agent: str = DEFAULT_UA, log_file: Path | None = None):
        self.user_agent = user_agent
        self.log_file = log_file
        self.cookies: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._last_solve_time: float = 0.0

    async def natural_click(self, page, elem):
        box = await elem.bounding_box()
        if not box:
            return
        click_x = box["x"] + random.uniform(22, 28)
        click_y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)
        cur_x = random.randint(100, 300)
        cur_y = random.randint(100, 200)
        await page.mouse.move(cur_x, cur_y)
        await asyncio.sleep(0.05)
        for i in range(1, 11):
            ix = cur_x + (click_x - cur_x) * (i / 10) + random.uniform(-2, 2)
            iy = cur_y + (click_y - cur_y) * (i / 10) + random.uniform(-2, 2)
            await page.mouse.move(ix, iy)
            await asyncio.sleep(0.02)
        await page.mouse.move(click_x, click_y)
        await asyncio.sleep(0.15)
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.06, 0.12))
        await page.mouse.up()

    async def solve(self, force: bool = False) -> dict[str, str]:
        async with self._lock:
            # Atomic cooldown: at most 1 solve every 60s unless explicitly forced
            now = time.time()
            if self.cookies and not force and (now - self._last_solve_time < 60):
                return self.cookies

            log("[Solver] Launching Patchright to solve Cloudflare Turnstile...", self.log_file)
            t0 = time.time()
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(
                    user_agent=self.user_agent,
                    locale="zh-CN,zh;q=0.9",
                    viewport={"width": 1366, "height": 768}
                )
                page = await context.new_page()

                try:
                    await page.goto("https://zysjonline.com/", wait_until="domcontentloaded", timeout=25000)
                    for _ in range(15):
                        await asyncio.sleep(1)
                        for f in page.frames:
                            if "challenges.cloudflare.com" in f.url:
                                elem = await f.frame_element()
                                if elem:
                                    await self.natural_click(page, elem)
                                    break
                        t = await page.title()
                        if "中医世家" in t or ("请稍候" not in t and "Just a moment" not in t):
                            break

                    cookies_list = await context.cookies()
                    new_cookies = {c["name"]: c["value"] for c in cookies_list}
                    if "cf_clearance" in new_cookies:
                        self.cookies = new_cookies
                        self._last_solve_time = time.time()
                        log(f"[Solver] Turnstile solved successfully in {time.time() - t0:.2f}s! (cf_clearance acquired)", self.log_file)
                    else:
                        log("[Solver] Warning: cf_clearance not found in cookies yet.", self.log_file)
                except Exception as e:
                    log(f"[Solver] Error during Turnstile solve: {e}", self.log_file)
                finally:
                    await browser.close()

            return self.cookies


# ==============================================================================
# HTML Content Extraction
# ==============================================================================
def extract_article_verbatim(html_content: str, url: str) -> tuple[bool, str, str]:
    if not html_content or len(html_content) < 50:
        return False, "", "Empty response body"

    soup = BeautifulSoup(html_content, "html.parser")
    title_tag = soup.find("title")
    title_str = title_tag.get_text(strip=True) if title_tag else ""

    if "页面未找到" in title_str or "404" in title_str:
        return False, "", "HTTP 404: 页面不存在"
    if "请稍候" in title_str or "Just a moment" in title_str or "403 Forbidden" in html_content[:400]:
        return False, "", "WAF 403 Challenge"

    for selector in ["aside", "nav", "header", "footer", "dialog", "script", "style", ".sticky", "noscript", "svg"]:
        for tag in soup.select(selector):
            tag.decompose()

    body_tag = soup.find("article") or soup.find("main") or soup.find("body")
    if not body_tag:
        return False, "", "No main container found"

    text = clean_to_verbatim(body_tag.get_text(separator="\n", strip=True))
    if len(text) < 15:
        return False, "", f"Article text too short ({len(text)} chars)"

    return True, text, ""


# ==============================================================================
# SQLite Checkpoint Storage
# ==============================================================================
class ShardCheckpoint:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
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
        definitive = [
            (row_idx, doc_id, url, 1 if success else 0, text, error, now_str)
            for row_idx, doc_id, url, success, text, error in batch
            if success or "404" in error or "too short" in error
        ]
        if not definitive:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO crawled_records (row_index, id, url, success, text, error, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, definitive)
            conn.commit()

    def get_stats(self) -> tuple[int, int, int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(success) FROM crawled_records")
            row = cursor.fetchone()
            tot = row[0] or 0
            succ = row[1] or 0
            return tot, succ, tot - succ

    def export_to_jsonl(self, jsonl_path: Path):
        import json
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
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
        return count


# ==============================================================================
# Network Fetcher: Chrome TLS Impersonation
# ==============================================================================
class ChromeNetworkClient:
    """HTTP Client using curl_cffi Chrome 124 TLS mimicry, or httpx fallback."""

    def __init__(self, cookies: dict[str, str], user_agent: str = DEFAULT_UA):
        self.cookies = cookies
        self.user_agent = user_agent
        self.session = None
        self._init_session()

    def _init_session(self):
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://zysjonline.com/",
        }
        if HAS_CURL_CFFI:
            self.session = CurlAsyncSession(
                impersonate="chrome124",
                cookies=self.cookies,
                headers=headers,
                timeout=6.0,
                max_clients=30,
            )
        else:
            self.session = httpx.AsyncClient(
                cookies=self.cookies,
                http2=True,
                headers=headers,
                timeout=6.0,
                follow_redirects=True,
            )

    def update_cookies(self, new_cookies: dict[str, str]):
        self.cookies.update(new_cookies)
        if HAS_CURL_CFFI:
            if self.session:
                self.session.cookies.update(new_cookies)
        else:
            if self.session:
                self.session.cookies.update(new_cookies)

    async def fetch(self, url: str) -> tuple[int, str]:
        if HAS_CURL_CFFI:
            resp = await self.session.get(url, timeout=6.0)
            return resp.status_code, resp.text
        else:
            resp = await self.session.get(url, timeout=6.0)
            return resp.status_code, resp.text

    async def close(self):
        if self.session:
            await self.session.close()


async def crawl_single(
    client: ChromeNetworkClient,
    row_idx: int,
    doc_id: int,
    url: str,
    semaphore: asyncio.Semaphore,
) -> tuple[int, int, str, bool, str, str]:
    """Fetch 1 record with forced asyncio timeout safeguard."""
    async with semaphore:
        for attempt in range(2):
            try:
                await asyncio.sleep(random.uniform(0.02, 0.06))
                status, html_content = await asyncio.wait_for(client.fetch(url), timeout=8.0)

                if status == 403 or "请稍候" in html_content[:400] or "Just a moment" in html_content[:400]:
                    return row_idx, doc_id, url, False, "", "WAF 403 Challenge"

                if status == 404:
                    return row_idx, doc_id, url, False, "", "HTTP 404: 页面不存在"

                if status != 200:
                    await asyncio.sleep(0.5)
                    continue

                success, text, err = extract_article_verbatim(html_content, url)
                return row_idx, doc_id, url, success, text, err
            except Exception:
                await asyncio.sleep(0.5)

    return row_idx, doc_id, url, False, "", "Fetch failed"


# ==============================================================================
# Main Orchestrator Loop
# ==============================================================================
async def run_shard_crawler(
    targets: list[tuple[int, int, str]],
    output_dir: Path,
    shard_id: int | str,
    concurrency: int = 15,
    batch_size: int = 25,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / f"zysj_shard_{shard_id}.sqlite"
    jsonl_path = output_dir / f"zysj_shard_{shard_id}.jsonl"
    log_file = output_dir / f"zysj_shard_{shard_id}.log"

    checkpoint = ShardCheckpoint(db_path)
    crawled = checkpoint.get_crawled_indices()
    pending = [t for t in targets if t[0] not in crawled]

    engine_tag = "curl_cffi (Chrome 124 TLS impersonation)" if HAS_CURL_CFFI else "httpx (standard OpenSSL)"
    log(f"Shard {shard_id}: Engine={engine_tag}", log_file)
    log(f"Shard {shard_id}: Total={len(targets)} | Crawled={len(crawled)} | Pending={len(pending)}", log_file)

    if not pending:
        log(f"Shard {shard_id} already 100% completed! Exporting JSONL...", log_file)
        cnt = checkpoint.export_to_jsonl(jsonl_path)
        log(f"Exported {cnt} records to {jsonl_path}", log_file)
        return

    # 1. Initial Turnstile Solve
    solver = TurnstileSolver(log_file=log_file)
    cookies = await solver.solve(force=True)
    if not cookies or "cf_clearance" not in cookies:
        log("Retrying initial Turnstile solve...", log_file)
        await asyncio.sleep(3)
        cookies = await solver.solve(force=True)

    client = ChromeNetworkClient(cookies=cookies)
    semaphore = asyncio.Semaphore(concurrency)
    log(f"Shard {shard_id}: Starting fetch loop (batch_size={batch_size}, concurrency={concurrency})...", log_file)

    start_t = time.time()
    processed = 0
    success_cnt = 0
    failed_cnt = 0

    batch_idx = 0
    try:
        while batch_idx < len(pending):
            batch_targets = pending[batch_idx : batch_idx + batch_size]
            tasks = [crawl_single(client, r, i, u, semaphore) for r, i, u in batch_targets]
            results = await asyncio.gather(*tasks)

            waf_blocks = sum(1 for r in results if r[5] == "WAF 403 Challenge")
            b_succ = sum(1 for r in results if r[3])
            b_fail = len(results) - b_succ

            # Batch-level Circuit Breaker: if >= 30% of batch hit WAF 403, pause and refresh ONCE
            if len(batch_targets) >= 10 and waf_blocks > (len(batch_targets) * 0.3):
                log(
                    f"[CircuitBreaker] WAF Challenge triggered on {waf_blocks}/{len(batch_targets)} URLs. "
                    f"Pausing 15s and re-solving session once...",
                    log_file
                )
                await asyncio.sleep(15)
                new_cookies = await solver.solve(force=True)
                client.update_cookies(new_cookies)
                log("[CircuitBreaker] Session refreshed. Retrying same batch...", log_file)
                await asyncio.sleep(2)
                continue

            # Save batch to SQLite
            checkpoint.save_batch(results)
            processed += len(results)
            success_cnt += b_succ
            failed_cnt += b_fail
            batch_idx += len(batch_targets)

            elapsed = time.time() - start_t
            rate = processed / elapsed if elapsed > 0 else 0
            eta_m = ((len(pending) - processed) / rate) / 60 if rate > 0 else 0

            log(
                f"[{shard_id}] {processed}/{len(pending)} ({processed/len(pending)*100:.1f}%) | "
                f"Speed: {rate:.1f} URLs/s | Succ: {success_cnt} | Fail: {failed_cnt} | ETA: {eta_m:.1f}m",
                log_file
            )
    finally:
        await client.close()

    tot, succ, fail = checkpoint.get_stats()
    log(f"Shard {shard_id} Completed! DB Total: {tot} (Success: {succ}, Failed: {fail})", log_file)
    cnt = checkpoint.export_to_jsonl(jsonl_path)
    log(f"Exported {cnt} records to {jsonl_path}", log_file)


def main():
    parser = argparse.ArgumentParser(description="Kaggle Worker for zysjonline.com")
    parser.add_argument("--shard-file", type=str, default=None, help="Path to specific shard parquet file")
    parser.add_argument("--all-file", type=str, default=None, help="Path to zysj_pending_all.parquet")
    parser.add_argument("--shard", type=int, default=1, help="Shard number (1-indexed)")
    parser.add_argument("--total-shards", type=int, default=5, help="Total number of shards")
    parser.add_argument("--concurrency", type=int, default=15, help="Number of concurrent workers")
    parser.add_argument("--output-dir", type=str, default="/kaggle/working", help="Output directory")

    args = parser.parse_args()
    out_dir = Path(args.output_dir)

    targets = []
    if args.shard_file and Path(args.shard_file).exists():
        table = pq.read_table(args.shard_file)
        r_indices = table["row_index"].to_pylist()
        ids = table["id"].to_pylist()
        urls = table["url"].to_pylist()
        targets = list(zip(r_indices, ids, urls))
        shard_id = Path(args.shard_file).stem.replace("zysj_shard_", "")
    elif args.all_file and Path(args.all_file).exists():
        table = pq.read_table(args.all_file)
        r_indices = table["row_index"].to_pylist()
        ids = table["id"].to_pylist()
        urls = table["url"].to_pylist()
        all_targets = list(zip(r_indices, ids, urls))
        total_len = len(all_targets)
        sz = math.ceil(total_len / args.total_shards)
        s_idx = (args.shard - 1) * sz
        e_idx = min(args.shard * sz, total_len)
        targets = all_targets[s_idx:e_idx]
        shard_id = f"shard_{args.shard}_of_{args.total_shards}"
    else:
        candidates = list(Path("/kaggle/input").glob("**/zysj_shard_*.parquet")) + list(Path(".").glob("**/zysj_shard_*.parquet"))
        if candidates:
            target_cand = candidates[0]
            print(f"Auto-detected shard file: {target_cand}")
            table = pq.read_table(target_cand)
            targets = list(zip(table["row_index"].to_pylist(), table["id"].to_pylist(), table["url"].to_pylist()))
            shard_id = target_cand.stem.replace("zysj_shard_", "")
        else:
            print("ERROR: No shard file found! Specify --shard-file or --all-file.")
            sys.exit(1)

    asyncio.run(run_shard_crawler(targets, out_dir, shard_id, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
