"""Standalone High-Throughput Crawler Worker for ask.39.net on Kaggle.

Uses Patchright Chromium with Route Filtering (aborts images, fonts, media, CSS)
and isolated per-request page lifecycle to eliminate tab navigation contamination.

100% self-contained: no external repo dependencies required.
Includes atomic SQLite checkpointing and automatic JSONL snapshot exporting.
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

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
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
# Logging
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


# ==============================================================================
# ask.39.net Specialized Q&A DOM Extractor
# ==============================================================================
def extract_ask39(html_content: str) -> tuple[str, str | None]:
    """Extract clinical Q&A components from ask.39.net HTML.

    Returns:
        (verbatim_text, error_message)
    """
    if not html_content or len(html_content) < 500:
        return "", "HTML content too short or empty"

    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Question Title
    h1 = soup.find("h1")
    title = clean_to_verbatim(h1.get_text(strip=True)) if h1 else ""

    # 2. Question Body & Symptoms
    q_div = soup.find(class_="txt_ms") or soup.find(class_="ask_cont")
    q_text = ""
    if q_div:
        # Strip navigation noise, ads, button tags
        for noise in q_div.find_all(class_=["relevant_ask", "other_look", "btn_consult", "my_consult", "ask_hid"]):
            noise.decompose()
        q_raw = q_div.get_text(separator=" ", strip=True)
        # Remove common repeating UI boilerplates
        for bp in ["我要咨询", "其他人还在看"]:
            if bp in q_raw:
                q_raw = q_raw.split(bp)[0]
        q_text = clean_to_verbatim(q_raw)

    # 3. Doctor Info
    doc_div = soup.find(class_="doctor_all") or soup.find(class_="doc_txt")
    doc_info = ""
    if doc_div:
        # Strip '找医生' buttons
        for btn in doc_div.find_all(class_=["doc_btn", "btn"]):
            btn.decompose()
        doc_info = clean_to_verbatim(doc_div.get_text(separator=" ", strip=True))

    # 4. Doctor Answer (sele_txt is the verified main clinical advice container)
    ans_div = soup.find(class_="sele_txt") or soup.find(class_="doc_ans")
    ans_text = ""
    if ans_div:
        ans_text = clean_to_verbatim(ans_div.get_text(separator="\n", strip=True))

    # Validate essential clinical contents
    if not title and not ans_text:
        return "", "Missing both question title and doctor answer"
    if not ans_text:
        return "", "Question has no verified doctor answer (unanswered/stub)"

    parts = []
    if title:
        parts.append(title)
    if q_text and q_text != title:
        parts.append(f"【患者提问】\n{q_text}")
    if doc_info:
        parts.append(f"【医生信息】\n{doc_info}")
    if ans_text:
        parts.append(f"【医生回复】\n{ans_text}")

    full_verbatim = "\n\n".join(parts).strip()
    return full_verbatim, None


# ==============================================================================
# SQLite Checkpoint Storage
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

    def get_total_count(self) -> tuple[int, int, int]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*), sum(success) FROM crawled_records")
            row = cursor.fetchone()
            total = row[0] or 0
            success = row[1] or 0
            failed = total - success
            return total, success, failed

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
# Async Browser Crawler Engine
# ==============================================================================
class Ask39Crawler:
    def __init__(
        self,
        db: CheckpointDB,
        concurrency: int = 5,
        timeout_ms: int = 20000,
        log_file: Path | None = None,
    ):
        self.db = db
        self.concurrency = concurrency
        self.timeout_ms = timeout_ms
        self.log_file = log_file

    async def fetch_url(self, context, item: dict) -> dict:
        row_idx = item["row_index"]
        doc_id = item["id"]
        url = item["url"]

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

    async def run(self, targets: list[dict], shard_id: int | str, jsonl_path: Path, batch_size: int = 25):
        total_targets = len(targets)
        crawled_rows = self.db.get_crawled_rows()
        pending = [t for t in targets if t["row_index"] not in crawled_rows]

        log(f"Shard {shard_id}: Total targets = {total_targets} | Already crawled = {len(crawled_rows)} | Pending = {len(pending)}", self.log_file)

        if not pending:
            log(f"Shard {shard_id}: All {total_targets} records already crawled! Exporting final JSONL...", self.log_file)
            exported = self.db.export_jsonl(jsonl_path)
            log(f"Shard {shard_id}: Export complete: {exported} records -> {jsonl_path}", self.log_file)
            return

        async with async_playwright() as p:
            log(f"Launching Patchright Chromium headless (Concurrency: {self.concurrency}, Timeout: {self.timeout_ms}ms)...", self.log_file)
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                ],
            )

            async def create_fresh_context():
                ctx = await browser.new_context(user_agent=DEFAULT_UA)
                await ctx.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ["image", "font", "media", "stylesheet"]
                    else route.continue_(),
                )
                return ctx

            context = await create_fresh_context()
            sem = asyncio.Semaphore(self.concurrency)

            start_time = time.time()
            done_in_session = 0
            session_success = 0
            last_export_count = 0
            last_recycle_count = 0
            consecutive_transient_batches = 0

            # Process in micro-batches
            num_batches = (len(pending) + batch_size - 1) // batch_size
            for b_idx in range(num_batches):
                b_start = b_idx * batch_size
                b_end = min((b_idx + 1) * batch_size, len(pending))
                batch_items = pending[b_start:b_end]

                async def worker_fetch(item):
                    async with sem:
                        # Add slight jitter to avoid request burst to Tencent WAF
                        await asyncio.sleep(random.uniform(0.15, 0.35))
                        return await self.fetch_url(context, item)

                batch_results = await asyncio.gather(*(worker_fetch(it) for it in batch_items))

                # Analyze batch errors for WAF detection
                batch_transient = sum(
                    1 for r in batch_results
                    if not r["success"] and any(k in (r.get("error") or "").lower() for k in ["timeout", "connection", "reset", "timed out", "closed"])
                )

                # Circuit Breaker: Auto-pause 35s if WAF rate-limit triggers
                if batch_transient >= max(3, int(len(batch_items) * 0.4)):
                    consecutive_transient_batches += 1
                    if consecutive_transient_batches >= 2:
                        log(f"[CircuitBreaker] Tencent WAF rate-limit detected ({batch_transient}/{len(batch_items)} timeouts). Cooling down 35s to unban IP...", self.log_file)
                        await asyncio.sleep(35.0)
                        consecutive_transient_batches = 0
                        log("[CircuitBreaker] Cooldown elapsed! Resuming crawler...", self.log_file)
                else:
                    consecutive_transient_batches = 0

                # Save atomically
                self.db.save_batch(batch_results)
                batch_succ = sum(1 for r in batch_results if r["success"])
                session_success += batch_succ
                done_in_session += len(batch_results)

                total_in_db, tot_succ, tot_fail = self.db.get_total_count()
                elapsed = time.time() - start_time
                speed = done_in_session / max(elapsed, 0.001)
                rem_urls = total_targets - total_in_db
                eta_min = (rem_urls / max(speed, 0.001)) / 60.0

                pct = (total_in_db / total_targets) * 100
                log(
                    f"Shard {shard_id} Progress: {total_in_db}/{total_targets} ({pct:.1f}%) | "
                    f"Speed: {speed:.1f} URLs/s | Success: {tot_succ} | Failed: {tot_fail} | "
                    f"ETA: {eta_min:.1f}m",
                    self.log_file,
                )

                # Periodic JSONL snapshot every 2,500 records
                if done_in_session - last_export_count >= 2500:
                    last_export_count = done_in_session
                    self.db.export_jsonl(jsonl_path)
                    log(f"Shard {shard_id}: Exported snapshot JSONL ({total_in_db} records) -> {jsonl_path.name}", self.log_file)

                # Proactive Context Recycling every 1,200 records to free RAM & stale sockets
                if done_in_session - last_recycle_count >= 1200:
                    last_recycle_count = done_in_session
                    log(f"[Recycle] Re-creating browser context after {done_in_session} records to keep Chromium memory fresh...", self.log_file)
                    try:
                        await context.close()
                    except Exception:
                        pass
                    context = await create_fresh_context()

            # Final export
            await browser.close()
            exported = self.db.export_jsonl(jsonl_path)
            log(f"Shard {shard_id} CRAWL COMPLETE! Total exported: {exported} records -> {jsonl_path}", self.log_file)


# ==============================================================================
# CLI Entrypoint
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Kaggle Worker for ask.39.net crawler")
    parser.add_argument("--shard", type=int, default=1, help="Shard number (1 to 6)")
    parser.add_argument("--parquet", type=str, default=None, help="Explicit path to shard Parquet file")
    parser.add_argument("--concurrency", type=int, default=4, help="Number of concurrent browser tabs")
    parser.add_argument("--timeout", type=int, default=15000, help="Page navigation timeout in ms")
    parser.add_argument("--batch-size", type=int, default=25, help="Micro-batch size for saving")
    parser.add_argument("--output-dir", type=str, default="/kaggle/working", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine input parquet file
    if args.parquet:
        parquet_path = Path(args.parquet)
        shard_id = args.shard
    else:
        candidate_paths = [
            out_dir / f"ask39_shard_{args.shard}.parquet",
            Path(f"/kaggle/input/ask39-shards/ask39_shard_{args.shard}.parquet"),
            Path(f"/kaggle/input/kaggle-ask39-shards/ask39_shard_{args.shard}.parquet"),
            Path(f"ask39_shard_{args.shard}.parquet"),
        ]
        parquet_path = None
        for p in candidate_paths:
            if p.exists():
                parquet_path = p
                break
        if not parquet_path:
            matches = list(Path("/kaggle/input").rglob(f"ask39_shard_{args.shard}.parquet")) if Path("/kaggle/input").exists() else []
            if matches:
                parquet_path = matches[0]

        if not parquet_path or not parquet_path.exists():
            print(f"Error: Could not locate ask39_shard_{args.shard}.parquet in input directories.")
            print("Checked candidate locations:")
            for c in candidate_paths:
                print(f"  - {c}")
            sys.exit(1)
        shard_id = args.shard

    log_file = out_dir / f"ask39_crawler_shard_{shard_id}.log"
    db_path = out_dir / f"ask39_shard_{shard_id}.sqlite"
    jsonl_path = out_dir / f"ask39_shard_{shard_id}.jsonl"

    print(f"=== Starting ask.39.net Crawler Shard {shard_id} ===")
    print(f"Parquet input: {parquet_path}")
    print(f"Checkpoint DB: {db_path}")
    print(f"Output JSONL : {jsonl_path}")

    # Load targets from parquet
    table = pq.read_table(parquet_path)
    row_indices = table["row_index"].to_pylist()
    doc_ids = table["id"].to_pylist()
    urls = table["url"].to_pylist()
    targets = [{"row_index": r, "id": i, "url": u} for r, i, u in zip(row_indices, doc_ids, urls)]

    db = CheckpointDB(db_path)
    crawler = Ask39Crawler(
        db=db,
        concurrency=args.concurrency,
        timeout_ms=args.timeout,
        log_file=log_file,
    )

    asyncio.run(crawler.run(targets=targets, shard_id=shard_id, jsonl_path=jsonl_path, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
