"""High-performance local crawler for ViBioMIR corpus gap filling.
Crawls Long Chau, Vietnamese Newspapers, and 39.net Subdomains with zero proxy cost.
Features:
- Multi-Domain Smart Extractor (Next.js __NEXT_DATA__, Vietnamese CMS, Chinese GBK)
- Preserves exact row_index and id mapping from links_corpus.parquet
- SQLite WAL checkpointing + Streaming JSONL export to datacrawl/derived/bosung/
- Fully compliant with clean_to_verbatim v2 and ViBioMIR invariants
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
import pyarrow.parquet as pq

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data import ROW_IDS

PARQUET_PATH = REPO_ROOT / "sbtc/data/links_corpus.parquet"
DEFAULT_OUT_DIR = REPO_ROOT / "datacrawl/derived/bosung"
DEFAULT_DB_PATH = DEFAULT_OUT_DIR / "crawl_checkpoint.sqlite"

# Precompiled regexes
LONGCHAU_NEXT_RE = re.compile(r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>", re.DOTALL)
CONTENT_CLASS_RE = re.compile(r"content|detail|article|entry|post|body|fck_detail", re.I)
STRIP_TAGS_RE = re.compile(r"related|share|tag|author|comment|social|adv|banner", re.I)


def classify_cluster(url: str) -> str:
    """Classify target URL into domain clusters."""
    host = urlparse(url).hostname or ""
    if "nhathuoclongchau.com.vn" in host:
        return "longchau"
    if host.endswith(".39.net") and not host.startswith("ask."):
        return "39net"
    if host.endswith(".vn"):
        return "baovn"
    return "other"


def extract_longchau(html_text: str) -> tuple[str, str]:
    """Smart extraction for Long Chau Next.js state or DOM fallback."""
    m = LONGCHAU_NEXT_RE.search(html_text)
    if m:
        try:
            page_props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
            # 1. Article page (/bai-viet/)
            detail = page_props.get("detail", {}).get("data", {})
            if detail:
                title = detail.get("name", "")
                sapo = detail.get("shortDescription", "")
                desc_html = detail.get("description", "")
                desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n\n").strip()
                parts = [p for p in [title, sapo, desc_text] if p]
                return "\n\n".join(parts).strip(), ""

            # 2. Disease page (/benh/)
            benh = page_props.get("data", {})
            if benh and isinstance(benh, dict) and "name" in benh:
                title = benh.get("name", "")
                parts = [title] if title else []
                for key in ["overview", "symptom", "cause", "risk", "diagnoseAndTreaty", "livingAndPreventive"]:
                    val = benh.get(key)
                    if isinstance(val, str) and val.strip():
                        parts.append(BeautifulSoup(val, "html.parser").get_text(separator="\n\n").strip())
                return "\n\n".join(parts).strip(), ""
        except Exception:
            pass

    # Fallback DOM parsing
    soup = BeautifulSoup(html_text, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    body_el = soup.find(["div", "article"], class_=re.compile(r"post-content|article-detail|content|detail", re.I))
    body = body_el.get_text(separator="\n\n").strip() if body_el else ""
    if not body:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        body = "\n\n".join(paragraphs)
    parts = [p for p in [title, body] if p]
    return "\n\n".join(parts).strip(), ""


def extract_baovn(html_text: str) -> tuple[str, str]:
    """Smart extraction for Vietnamese local newspaper CMS."""
    if "Không tìm thấy đường dẫn hoặc thông tin này" in html_text or "Nội dung này không tồn tại" in html_text:
        return "", "HTTP 200 soft 404: post removed on web"

    soup = BeautifulSoup(html_text, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    # Sapo
    sapo_el = soup.find(["div", "p"], class_=re.compile(r"sc-longform-header-text|sapo|lead|summary", re.I))
    sapo = sapo_el.get_text(strip=True) if sapo_el else ""

    # Body
    body_el = (
        soup.find(["article", "div"], class_=re.compile(r"b-maincontent|content-article|entry|detail-content|content-detail|fck_detail|article-content|post-content|main-content", re.I)) or
        soup.find(["article", "div"], id=re.compile(r"content-detail|main-content|article-content|content", re.I)) or
        soup.find("article")
    )
    if body_el:
        for junk in body_el.find_all(["script", "style", "div"], class_=STRIP_TAGS_RE):
            junk.decompose()
        body = body_el.get_text(separator="\n\n", strip=True)
    else:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        body = "\n\n".join(paragraphs)

    parts = [p for p in [title, sapo, body] if p]
    return "\n\n".join(parts).strip(), ""


def extract_39net(html_bytes: bytes) -> tuple[str, str]:
    """Smart extraction for 39.net static article subdomains (utf-8 / gb18030)."""
    decoded = ""
    for enc in ["utf-8", "gb18030", "gbk"]:
        try:
            decoded = html_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        decoded = html_bytes.decode("utf-8", errors="replace")

    if "抱歉，您访问的页面不存在" in decoded or "页面不存在" in decoded[:500]:
        return "", "Soft 404: page does not exist on 39.net"

    soup = BeautifulSoup(decoded, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    art_el = (
        soup.find("div", class_="art_box") or
        soup.find("div", class_="art_content") or
        soup.find("div", id="contentText") or
        soup.find("div", class_="content")
    )
    if art_el:
        for junk in art_el.find_all(["script", "style"]):
            junk.decompose()
        body = art_el.get_text(separator="\n\n", strip=True)
    else:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
        body = "\n\n".join(paragraphs)

    parts = [p for p in [title, body] if p]
    return "\n\n".join(parts).strip(), ""


def extract_content(html_bytes: bytes, url: str, cluster: str) -> tuple[str, str]:
    """Multi-domain content extractor dispatcher."""
    try:
        if cluster == "longchau":
            text = html_bytes.decode("utf-8", errors="replace")
            return extract_longchau(text)
        elif cluster == "baovn":
            text = html_bytes.decode("utf-8", errors="replace")
            return extract_baovn(text)
        elif cluster == "39net":
            return extract_39net(html_bytes)
        else:
            text = html_bytes.decode("utf-8", errors="replace")
            soup = BeautifulSoup(text, "html.parser")
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else ""
            body_el = soup.find(["article", "div"], class_=CONTENT_CLASS_RE)
            body = body_el.get_text(separator="\n\n", strip=True) if body_el else ""
            parts = [p for p in [title, body] if p]
            return "\n\n".join(parts).strip(), ""
    except Exception as err:
        return "", f"Extraction error: {type(err).__name__}: {err}"


class LocalCrawler:
    def __init__(self, db_path: Path, out_dir: Path, concurrency: int = 45):
        self.db_path = db_path
        self.out_dir = out_dir
        self.concurrency = concurrency
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_records (
                    row_index INTEGER PRIMARY KEY,
                    id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    text TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    cluster TEXT NOT NULL,
                    error TEXT,
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cluster ON crawl_records(cluster)")

    def get_completed_rows(self) -> set[int]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT row_index FROM crawl_records WHERE success = 1")
            return {row[0] for row in cursor.fetchall()}

    def save_batch(self, batch: list[tuple]):
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO crawl_records (row_index, id, url, text, success, cluster, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, batch)

    def export_jsonl(self, cluster: str | None = None) -> Path:
        """Export completed records to JSONL file."""
        query = "SELECT row_index, id, url, text, success, error FROM crawl_records"
        params = ()
        if cluster and cluster != "all":
            query += " WHERE cluster = ?"
            params = (cluster,)
            out_file = self.out_dir / f"data_bosung_{cluster}.jsonl"
        else:
            out_file = self.out_dir / "data_bosung_local_all.jsonl"

        query += " ORDER BY row_index ASC"

        with sqlite3.connect(self.db_path, timeout=30.0) as conn, open(out_file, "w", encoding="utf-8") as f:
            cursor = conn.cursor()
            cursor.execute(query, params)
            count = 0
            for r_idx, doc_id, url, text, success, error in cursor:
                rec = {
                    "row_index": r_idx,
                    "id": doc_id,
                    "url": url,
                    "text": text,
                    "success": bool(success),
                }
                if error:
                    rec["error"] = error
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1

        print(f"[Export] Saved {count:,} records to {out_file}")
        return out_file

    async def crawl_targets(self, targets: list[dict], cluster_name: str):
        completed = self.get_completed_rows()
        todo = [t for t in targets if t["row_index"] not in completed]
        total = len(todo)
        print(f"[{cluster_name.upper()}] Total targets: {len(targets):,} | Already done: {len(targets) - total:,} | To crawl: {total:,}")

        if not todo:
            print(f"[{cluster_name.upper()}] All targets already completed!")
            return

        semaphore = asyncio.Semaphore(self.concurrency)
        save_queue: asyncio.Queue = asyncio.Queue()
        session = requests.AsyncSession(impersonate="chrome120")

        crawled_count = 0
        success_count = 0
        failed_count = 0
        start_time = time.perf_counter()

        # Database writer worker
        async def db_writer():
            buffer = []
            while True:
                item = await save_queue.get()
                if item is None:
                    if buffer:
                        self.save_batch(buffer)
                    save_queue.task_done()
                    break
                buffer.append(item)
                if len(buffer) >= 50:
                    self.save_batch(buffer)
                    buffer.clear()
                save_queue.task_done()

        writer_task = asyncio.create_task(db_writer())

        async def worker(item: dict):
            nonlocal crawled_count, success_count, failed_count
            r_idx, doc_id, url, cl = item["row_index"], item["id"], item["url"], item["cluster"]

            async with semaphore:
                text = ""
                success = False
                error = ""
                for attempt in range(4):
                    try:
                        resp = await session.get(url, timeout=12)
                        if resp.status_code == 200:
                            cleaned, err = extract_content(resp.content, url, cl)
                            if cleaned and len(cleaned) >= 20:
                                text = cleaned
                                success = True
                                error = ""
                            else:
                                success = False
                                error = err or f"Extracted text too short ({len(cleaned)} chars)"
                            break
                        elif resp.status_code == 429:
                            # Adaptive backoff on 429 Too Many Requests
                            if attempt == 3:
                                success = False
                                error = "HTTP 429 (Too Many Requests)"
                            await asyncio.sleep(2.0 + attempt * 1.5)
                            continue
                        else:
                            success = False
                            error = f"HTTP {resp.status_code}"
                            break
                    except Exception as exc:
                        if attempt == 3:
                            success = False
                            error = f"{type(exc).__name__}: {str(exc)[:100]}"
                        await asyncio.sleep(1.0)
                await asyncio.sleep(0.05)

            crawled_count += 1
            if success:
                success_count += 1
            else:
                failed_count += 1

            await save_queue.put((r_idx, doc_id, url, text, int(success), cl, error))

            if crawled_count % 500 == 0 or crawled_count == total:
                elapsed = time.perf_counter() - start_time
                speed = crawled_count / elapsed if elapsed > 0 else 0
                pct = (crawled_count / total) * 100
                print(f"[{cl.upper()}] {crawled_count:,}/{total:,} ({pct:.1f}%) | Success: {success_count:,} | Fail: {failed_count:,} | Speed: {speed:.1f} URLs/s", flush=True)

        tasks = [asyncio.create_task(worker(item)) for item in todo]
        await asyncio.gather(*tasks)

        # Shutdown writer
        await save_queue.put(None)
        await writer_task

        total_elapsed = time.perf_counter() - start_time
        avg_speed = crawled_count / total_elapsed if total_elapsed > 0 else 0
        print(f"[{cluster_name.upper()} DONE] Finished {crawled_count:,} URLs in {total_elapsed:.1f}s (Avg {avg_speed:.1f} URLs/s) | OK: {success_count:,} | Fail: {failed_count:,}")
        self.export_jsonl(cluster_name)


def load_cluster_targets(cluster: str, limit: int = 0) -> list[dict]:
    """Load target records from Parquet filtered by cluster."""
    print("[Load] Reading links_corpus.parquet...")
    table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    id_col = table.column("id")
    url_col = table.column("url")

    targets = []
    for r in ROW_IDS:
        url = url_col[r].as_py()
        cl = classify_cluster(url)
        if cluster == "all" or cl == cluster:
            targets.append({
                "row_index": r,
                "id": id_col[r].as_py(),
                "url": url,
                "cluster": cl,
            })
            if limit > 0 and len(targets) >= limit:
                break
    return targets


async def main_async():
    parser = argparse.ArgumentParser(description="Local multi-domain gap crawler")
    parser.add_argument("--cluster", choices=["longchau", "baovn", "39net", "group1", "all"], default="longchau")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="0 for all")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--export-only", action="store_true", help="Only export DB to JSONL")
    args = parser.parse_args()

    crawler = LocalCrawler(db_path=args.db, out_dir=args.out_dir, concurrency=args.concurrency)

    if args.export_only:
        crawler.export_jsonl(args.cluster)
        return

    if args.cluster == "group1":
        for cl in ["baovn", "39net"]:
            targets = load_cluster_targets(cl, limit=args.limit)
            print(f"\n{'='*70}\n[Group 1] Starting cluster '{cl}': {len(targets):,} target rows\n{'='*70}", flush=True)
            await crawler.crawl_targets(targets, cl)
        return

    targets = load_cluster_targets(args.cluster, limit=args.limit)
    print(f"[Setup] Target cluster '{args.cluster}': Loaded {len(targets):,} target rows", flush=True)
    await crawler.crawl_targets(targets, args.cluster)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
