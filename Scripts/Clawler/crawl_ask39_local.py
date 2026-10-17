"""Local High-Throughput & Resilient Crawler for ask.39.net (337,375 URLs).

Architecture:
- Patchright Chromium with Route Filtering (aborts images, fonts, media, CSS)
- Sustained Concurrency = 2 with random jitter (0.15s - 0.35s) to stay safely below Tencent WAF rate limits
- Isolated per-request tab lifecycle (eliminates tab navigation contamination)
- Circuit Breaker: Automatically pauses 45s on transient burst errors and resumes seamlessly
- Atomic SQLite checkpointing (WAL mode) with periodic JSONL snapshots every 2,500 records
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import html
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

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
DERIVED_DIR = REPO_ROOT.parent / "datacrawl" / "derived"
DB_PATH = DERIVED_DIR / "ask39_crawl_checkpoint.sqlite"
LOG_PATH = DERIVED_DIR / "ask39_crawler.log"
FINAL_JSONL = DERIVED_DIR / "crawled_phase1_priority3_ask39.jsonl"

START_ROW = 2_110_878
END_ROW = 2_448_252
TOTAL_TARGETS = 337_375

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ==============================================================================
# Verbatim Cleaner (ViBioMIR Standard)
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


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


# ==============================================================================
# ask.39.net DOM Extractor
# ==============================================================================
def extract_ask39(html_content: str) -> tuple[str, str | None]:
    if not html_content or len(html_content) < 500:
        return "", "HTML content too short or empty"

    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Title
    h1 = soup.find("h1")
    title = clean_to_verbatim(h1.get_text(strip=True)) if h1 else ""

    # 2. Question body
    q_div = soup.find(class_="txt_ms") or soup.find(class_="ask_cont")
    q_text = ""
    if q_div:
        for noise in q_div.find_all(class_=["relevant_ask", "other_look", "btn_consult", "my_consult", "ask_hid"]):
            noise.decompose()
        q_raw = q_div.get_text(separator=" ", strip=True)
        for bp in ["我要咨询", "其他人还在看"]:
            if bp in q_raw:
                q_raw = q_raw.split(bp)[0]
        q_text = clean_to_verbatim(q_raw)

    # 3. Doctor Info
    doc_div = soup.find(class_="doctor_all") or soup.find(class_="doc_txt")
    doc_info = ""
    if doc_div:
        for btn in doc_div.find_all(class_=["doc_btn", "btn"]):
            btn.decompose()
        doc_info = clean_to_verbatim(doc_div.get_text(separator=" ", strip=True))

    # 4. Doctor Answer
    ans_div = soup.find(class_="sele_txt") or soup.find(class_="doc_ans")
    ans_text = ""
    if ans_div:
        ans_text = clean_to_verbatim(ans_div.get_text(separator="\n", strip=True))

    if not title and not ans_text:
        return "", "Missing both title and answer"
    if not ans_text:
        return "", "Question has no verified doctor answer (stub)"

    parts = []
    if title:
        parts.append(title)
    if q_text and q_text != title:
        parts.append(f"【患者提问】\n{q_text}")
    if doc_info:
        parts.append(f"【医生信息】\n{doc_info}")
    if ans_text:
        parts.append(f"【医生回复】\n{ans_text}")

    return "\n\n".join(parts).strip(), None


# ==============================================================================
# SQLite Storage
# ==============================================================================
class CheckpointDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawled_records (
                    row_index INTEGER PRIMARY KEY,
                    id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    text TEXT,
                    error TEXT,
                    timestamp TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_success ON crawled_records(success)")
            conn.commit()

    def get_crawled_rows(self) -> set[int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT row_index FROM crawled_records "
                "WHERE success = 1 OR error LIKE 'HTTP 404%' OR error LIKE 'Question has no verified%'"
            )
            return {r[0] for r in cursor.fetchall()}

    def get_stats(self) -> tuple[int, int, int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*), sum(success) FROM crawled_records")
            row = cursor.fetchone()
            tot = row[0] or 0
            succ = row[1] or 0
            fail = tot - succ
            return tot, succ, fail

    def save_batch(self, records: list[dict]):
        if not records:
            return
        now_str = datetime.now().isoformat()
        rows = [
            (
                r["row_index"],
                r["id"],
                r["url"],
                1 if r["success"] else 0,
                r.get("text", ""),
                r.get("error", None),
                now_str,
            )
            for r in records
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO crawled_records (row_index, id, url, success, text, error, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()

    def export_jsonl(self, jsonl_path: Path) -> int:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = jsonl_path.with_suffix(".tmp")
        count = 0
        import json
        with sqlite3.connect(self.db_path) as conn, open(tmp_path, "w", encoding="utf-8") as f:
            cursor = conn.cursor()
            cursor.execute("SELECT row_index, id, url, success, text, error FROM crawled_records ORDER BY row_index ASC")
            for r in cursor:
                item = {
                    "row_index": r[0],
                    "id": r[1],
                    "url": r[2],
                    "success": bool(r[3]),
                    "text": r[4] or "",
                    "error": r[5],
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        tmp_path.replace(jsonl_path)
        return count


# ==============================================================================
# Crawler Engine with Circuit Breaker
# ==============================================================================
class LocalAsk39Crawler:
    def __init__(self, db: CheckpointDB, concurrency: int = 2, timeout_ms: int = 18000):
        self.db = db
        self.concurrency = concurrency
        self.timeout_ms = timeout_ms

    async def fetch_url(self, context, item: dict) -> dict:
        row_idx = item["row_index"]
        doc_id = item["id"]
        url = item["url"]

        # Retry up to 2 times with fresh page
        for attempt in range(2):
            page = await context.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                status = resp.status if resp else 0
                if status == 200:
                    html_content = await page.content()
                    verbatim_text, err = extract_ask39(html_content)
                    if verbatim_text:
                        return {"row_index": row_idx, "id": doc_id, "url": url, "success": True, "text": verbatim_text, "error": None}
                    else:
                        return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": err or "Extraction failed"}
                elif status == 404:
                    return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": "HTTP 404 Not Found"}
                else:
                    if attempt == 0:
                        await asyncio.sleep(1.0)
                        continue
                    return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": f"HTTP {status}"}
            except Exception as e:
                err_str = str(e)
                if attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": err_str[:80]}
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": "Max retries exceeded"}

    async def run(self, targets: list[dict], batch_size: int = 20):
        crawled_rows = self.db.get_crawled_rows()
        pending = [t for t in targets if t["row_index"] not in crawled_rows]

        log(f"=== Starting Local ask.39.net Crawler ===")
        log(f"Total targets: {len(targets)} | Already crawled: {len(crawled_rows)} | Pending: {len(pending)}")
        log(f"Configuration: Concurrency={self.concurrency}, Timeout={self.timeout_ms}ms, BatchSize={batch_size}")

        if not pending:
            log("All records already crawled! Exporting final JSONL...")
            exported = self.db.export_jsonl(FINAL_JSONL)
            log(f"Export complete: {exported} records -> {FINAL_JSONL}")
            return

        async with async_playwright() as p:
            log(f"Launching Patchright Chromium (Concurrency: {self.concurrency})...")
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(user_agent=DEFAULT_UA)

            # Block heavy resources
            await context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ["image", "font", "media", "stylesheet"]
                else route.continue_(),
            )

            sem = asyncio.Semaphore(self.concurrency)
            start_time = time.time()
            done_in_session = 0
            session_success = 0
            consecutive_transient_errors = 0
            last_export_count = 0

            num_batches = (len(pending) + batch_size - 1) // batch_size
            for b_idx in range(num_batches):
                b_start = b_idx * batch_size
                b_end = min((b_idx + 1) * batch_size, len(pending))
                batch_items = pending[b_start:b_end]

                # Circuit Breaker cooldown if triggered
                if consecutive_transient_errors >= 6:
                    log(f"[CircuitBreaker] Detected {consecutive_transient_errors} consecutive transient errors! Tencent WAF rate limit active.")
                    log("[CircuitBreaker] Sleeping 45 seconds for IP cooldown...")
                    await asyncio.sleep(45.0)
                    consecutive_transient_errors = 0
                    log("[CircuitBreaker] Cooldown elapsed! Resuming crawler...")

                async def worker_task(item):
                    async with sem:
                        await asyncio.sleep(random.uniform(0.15, 0.35))
                        return await self.fetch_url(context, item)

                batch_results = await asyncio.gather(*(worker_task(it) for it in batch_items))

                # Analyze batch errors
                batch_succ = sum(1 for r in batch_results if r["success"])
                batch_transient = sum(1 for r in batch_results if not r["success"] and any(k in (r.get("error") or "").lower() for k in ["timeout", "connection", "reset"]))

                if batch_transient >= batch_size // 2:
                    consecutive_transient_errors += batch_transient
                else:
                    consecutive_transient_errors = 0

                # Save atomically
                self.db.save_batch(batch_results)
                session_success += batch_succ
                done_in_session += len(batch_results)

                tot, succ, fail = self.db.get_stats()
                elapsed = time.time() - start_time
                speed = done_in_session / max(elapsed, 0.001)
                rem_urls = len(targets) - tot
                eta_hours = (rem_urls / max(speed, 0.001)) / 3600.0

                pct = (tot / len(targets)) * 100
                log(
                    f"Progress: {tot}/{len(targets)} ({pct:.2f}%) | "
                    f"Speed: {speed:.1f} URLs/s | Success: {succ} | Failed: {fail} | "
                    f"ETA: {eta_hours:.1f}h"
                )

                # Periodic snapshot every 2,500 records
                if done_in_session - last_export_count >= 2500:
                    last_export_count = done_in_session
                    self.db.export_jsonl(FINAL_JSONL)
                    log(f"Exported snapshot JSONL ({tot} records) -> {FINAL_JSONL.name}")

            await browser.close()
            exported = self.db.export_jsonl(FINAL_JSONL)
            log(f"CRAWL COMPLETE! Total exported: {exported} records -> {FINAL_JSONL}")


def main():
    parser = argparse.ArgumentParser(description="Local Crawler for ask.39.net")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrency (default: 3)")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size (default: 25)")
    parser.add_argument("--timeout", type=int, default=12000, help="Timeout in ms (default: 12000)")
    parser.add_argument("--start-row", type=int, default=START_ROW, help=f"Start row index (default: {START_ROW})")
    parser.add_argument("--end-row", type=int, default=END_ROW, help=f"End row index (default: {END_ROW})")
    args = parser.parse_args()

    # Load targets from parquet
    print(f"Reading target ask.39.net records from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    targets = []
    for idx in range(args.start_row, min(args.end_row + 1, len(urls))):
        if "ask.39.net" in urls[idx]:
            targets.append({"row_index": idx, "id": ids[idx], "url": urls[idx]})

    print(f"Loaded {len(targets)} target URLs (rows {args.start_row} -> {args.end_row}).")
    db = CheckpointDB(DB_PATH)
    crawler = LocalAsk39Crawler(db=db, concurrency=args.concurrency, timeout_ms=args.timeout)

    asyncio.run(crawler.run(targets=targets, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
