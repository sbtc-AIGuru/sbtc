"""High-Throughput 1-Hour Turbo Crawler for ask.39.net.

Optimized specifically for 1-hour trials with 10 Mbps unmetered bandwidth:
1. Squeezes maximum throughput: 50-60 continuous async workers.
2. Direct continuation: Seamlessly resumes from SQLite checkpoint, skipping 37,249+ crawled records.
3. Automated timebox limiter: Stops gracefully at 58 minutes to flush data before the 1-hour trial expires.
4. Flexible proxy support: Works with standard HTTP/SOCKS5 proxies, IP-auth, or User/Pass credentials.
5. Zero blocking: Async Queue pipeline with decoupled background DB committer.
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

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
DERIVED_DIR = REPO_ROOT.parent / "datacrawl" / "derived"
DB_PATH = DERIVED_DIR / "ask39_crawl_checkpoint.sqlite"
FINAL_JSONL = DERIVED_DIR / "crawled_phase1_priority3_ask39.jsonl"
LOG_PATH = DERIVED_DIR / "ask39_turbotrial.log"

START_ROW = 2_110_878
END_ROW = 2_448_252

# Verbatim Cleaner (ViBioMIR Standard)
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
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def extract_ask39(html_content: str, current_url: str = "") -> tuple[str, str | None]:
    if not html_content or len(html_content) < 500:
        return "", "HTML content too short"

    if "verify.html" in current_url or "滑动拼图验证" in html_content:
        return "", "WAF_CAPTCHA_VERIFY"

    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Title
    h1 = soup.find("h1")
    title = clean_to_verbatim(h1.get_text(strip=True)) if h1 else ""

    # 2. Question description
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

    # 3. Doctor info
    doc_div = soup.find(class_="doctor_all") or soup.find(class_="doc_txt")
    doc_info = ""
    if doc_div:
        for btn in doc_div.find_all(class_=["doc_btn", "btn"]):
            btn.decompose()
        doc_info = clean_to_verbatim(doc_div.get_text(separator=" ", strip=True))

    # 4. Doctor answer
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


class TurboCrawler:
    def __init__(
        self,
        db: CheckpointDB,
        proxy_host: str,
        proxy_port: str | int,
        proxy_user: str = "",
        proxy_pass: str = "",
        concurrency: int = 50,
        timeout_sec: int = 10,
        duration_minutes: int = 58,
        rotate_session: bool = False,
    ):
        self.db = db
        self.proxy_host = proxy_host
        self.proxy_port = str(proxy_port)
        self.proxy_user = proxy_user
        self.proxy_pass = proxy_pass
        self.concurrency = concurrency
        self.timeout_sec = timeout_sec
        self.max_duration_sec = duration_minutes * 60
        self.rotate_session = rotate_session

        self.req_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }

    def build_proxy_url(self, row_idx: int, attempt: int) -> str:
        if self.proxy_user and self.proxy_pass:
            user = self.proxy_user
            if self.rotate_session:
                sess = f"tb_{row_idx}_{attempt}_{random.randint(1000, 9999)}"
                user = f"{self.proxy_user}-session-{sess}"
            return f"http://{user}:{self.proxy_pass}@{self.proxy_host}:{self.proxy_port}"
        elif self.proxy_user:
            return f"http://{self.proxy_user}@{self.proxy_host}:{self.proxy_port}"
        else:
            return f"http://{self.proxy_host}:{self.proxy_port}"

    async def fetch_url(self, item: dict) -> dict:
        row_idx = item["row_index"]
        doc_id = item["id"]
        url = item["url"]

        for attempt in range(2):
            proxy_str = self.build_proxy_url(row_idx, attempt)
            proxies = {"http": proxy_str, "https": proxy_str}

            try:
                async with AsyncSession(impersonate="chrome124", proxies=proxies) as session:
                    resp = await session.get(url, headers=self.req_headers, timeout=self.timeout_sec)
                    status = resp.status_code
                    final_url = resp.url or url

                    if "verify.html" in final_url:
                        if attempt == 0:
                            await asyncio.sleep(0.2)
                            continue
                        return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": "WAF_CAPTCHA_VERIFY"}

                    if status == 200:
                        verbatim_text, err = extract_ask39(resp.text, current_url=final_url)
                        if verbatim_text:
                            return {"row_index": row_idx, "id": doc_id, "url": url, "success": True, "text": verbatim_text, "error": None}
                        else:
                            if err and "stub" in err.lower():
                                return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": err}
                            if attempt == 0:
                                await asyncio.sleep(0.2)
                                continue
                            return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": err or "Extraction failed"}
                    elif status == 404:
                        return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": "HTTP 404 Not Found"}
                    else:
                        if attempt == 0:
                            await asyncio.sleep(0.2)
                            continue
                        return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": f"HTTP {status}"}
            except Exception as e:
                err_msg = str(e)
                if attempt == 0:
                    await asyncio.sleep(0.2)
                    continue
                return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": err_msg[:80]}

        return {"row_index": row_idx, "id": doc_id, "url": url, "success": False, "text": "", "error": "Max retries exceeded"}

    async def run(self, targets: list[dict]):
        crawled_rows = self.db.get_crawled_rows()
        pending = [t for t in targets if t["row_index"] not in crawled_rows]

        log("=" * 65)
        log("⚡ KHỞI ĐỘNG 1-HOUR TURBO CRAWLER (10 Mbps UNMETERED)")
        log(f"📊 Tổng mục tiêu: {len(targets)} | Đã có sẵn: {len(crawled_rows)} | Cần cào: {len(pending)}")
        log(f"🚀 Số Worker song song: {self.concurrency} luồng | Timeout: {self.timeout_sec}s")
        log(f"⏱️ Khung giờ chạy: Tối đa {self.max_duration_sec // 60} phút (Tự động chốt dữ liệu trước khi hết trial)")
        log("=" * 65)

        if not pending:
            log("Tất cả dữ liệu đã được cào hoàn tất! Xuất JSONL...")
            exported = self.db.export_jsonl(FINAL_JSONL)
            log(f"Hoàn thành: {exported} records -> {FINAL_JSONL}")
            return

        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self.concurrency * 4)
        results_queue: asyncio.Queue[dict] = asyncio.Queue()
        stop_event = asyncio.Event()

        start_time = time.time()
        done_in_session = 0
        last_export_count = 0
        last_log_time = time.time()

        async def producer():
            for item in pending:
                if stop_event.is_set():
                    break
                await queue.put(item)

        async def worker():
            while not stop_event.is_set():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if producer_task.done() and queue.empty():
                        break
                    continue

                try:
                    res = await self.fetch_url(item)
                    await results_queue.put(res)
                except Exception as e:
                    await results_queue.put({
                        "row_index": item["row_index"],
                        "id": item["id"],
                        "url": item["url"],
                        "success": False,
                        "text": "",
                        "error": f"Worker err: {str(e)[:50]}",
                    })
                finally:
                    queue.task_done()

        async def db_writer():
            nonlocal done_in_session, last_export_count, last_log_time
            buffer = []
            while True:
                try:
                    res = await asyncio.wait_for(results_queue.get(), timeout=0.6)
                    buffer.append(res)
                    results_queue.task_done()
                except asyncio.TimeoutError:
                    pass

                now = time.time()
                elapsed = now - start_time
                should_flush = len(buffer) >= 30 or (buffer and (now - last_log_time >= 3.0)) or (stop_event.is_set() and buffer)

                if should_flush:
                    self.db.save_batch(buffer)
                    done_in_session += len(buffer)
                    buffer.clear()

                    tot, succ, fail = self.db.get_stats()
                    speed = done_in_session / max(elapsed, 0.001)
                    pct = (tot / len(targets)) * 100
                    rem_time_min = max(0.0, (self.max_duration_sec - elapsed) / 60.0)
                    last_log_time = now

                    log(
                        f"Tiến độ: {tot}/{len(targets)} ({pct:.2f}%) | "
                        f"Phiên Turbo: +{done_in_session} | "
                        f"Tốc độ: {speed:.2f} URLs/s | Thành công: {succ} | Lỗi/Stub: {fail} | "
                        f"Thời gian còn lại: {rem_time_min:.1f}m"
                    )

                    # Export snapshot every 2,000
                    if done_in_session - last_export_count >= 2000:
                        last_export_count = done_in_session
                        self.db.export_jsonl(FINAL_JSONL)
                        log(f"💾 Snapshot đã lưu ({tot} records) -> {FINAL_JSONL.name}")

                    # Check 1-hour timebox expiry
                    if elapsed >= self.max_duration_sec:
                        log("=" * 65)
                        log(f"⏰ [HẾT KHUNG GIỜ 58 PHÚT] Tự động dừng an toàn trước khi trial hết hạn!")
                        log(f"🏆 Tổng thu hoạch phiên Turbo: {done_in_session} bài cào mới!")
                        log("=" * 65)
                        stop_event.set()
                        break

                if stop_event.is_set() and results_queue.empty() and not buffer:
                    break

                if producer_task.done() and queue.empty() and all(w.done() for w in worker_tasks) and results_queue.empty() and not buffer:
                    break

        producer_task = asyncio.create_task(producer())
        worker_tasks = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        writer_task = asyncio.create_task(db_writer())

        done, _ = await asyncio.wait([producer_task, writer_task], return_when=asyncio.FIRST_COMPLETED)

        if writer_task in done:
            stop_event.set()
            producer_task.cancel()
        else:
            await queue.join()
            stop_event.set()
            await results_queue.join()
            await writer_task

        for w in worker_tasks:
            w.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

        exported = self.db.export_jsonl(FINAL_JSONL)
        log(f"🏁 HOÀN TẤT PHIÊN TURBO! Tổng số bản ghi xuất: {exported} -> {FINAL_JSONL}")


def main():
    parser = argparse.ArgumentParser(description="Turbo 1-Hour Trial Crawler for ask.39.net")
    parser.add_argument("--host", required=True, help="Proxy host (IP or domain)")
    parser.add_argument("--port", required=True, type=int, help="Proxy port")
    parser.add_argument("--user", default="", help="Proxy username")
    parser.add_argument("--password", default="", help="Proxy password")
    parser.add_argument("--concurrency", type=int, default=50, help="Workers concurrency (default: 50)")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds (default: 10)")
    parser.add_argument("--duration", type=int, default=58, help="Max run duration in minutes (default: 58)")
    parser.add_argument("--rotate-session", action="store_true", help="Append -session-xxx to user for rotating pools")
    args = parser.parse_args()

    print(f"Reading target ask.39.net records from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    targets = []
    for idx in range(START_ROW, min(END_ROW + 1, len(urls))):
        if "ask.39.net" in urls[idx]:
            targets.append({"row_index": idx, "id": ids[idx], "url": urls[idx]})

    print(f"Loaded {len(targets)} target URLs.")
    db = CheckpointDB(DB_PATH)
    crawler = TurboCrawler(
        db=db,
        proxy_host=args.host,
        proxy_port=args.port,
        proxy_user=args.user,
        proxy_pass=args.password,
        concurrency=args.concurrency,
        timeout_sec=args.timeout,
        duration_minutes=args.duration,
        rotate_session=args.rotate_session,
    )

    asyncio.run(crawler.run(targets=targets))


if __name__ == "__main__":
    main()
