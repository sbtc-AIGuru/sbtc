"""High-performance proxy crawler for ViBioMIR corpus gap filling.
Optimized for SparkProxy rotating residential proxy (250 threads).
Crawls ask.39.net, 39.net subdomains, Long Chau, cnkang.com and remaining gaps.
Features:
- Multi-Domain Smart Extractor (ask.39.net Q&A, Next.js __NEXT_DATA__, Chinese GBK/UTF-8)
- 100% RAW Extracted Text (decoupled from clean_to_verbatim to prevent data corruption)
- Preserves exact row_index and immutable id mapping from links_corpus.parquet
- SQLite WAL checkpointing + Streaming JSONL export to datacrawl/derived/bosung/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data import ROW_IDS

PARQUET_PATH = REPO_ROOT / "newcorpus/links_corpus_vi_en_zh.parquet"
DEFAULT_OUT_DIR = REPO_ROOT / "datacrawl/derived/bosung"
DEFAULT_DB_PATH = DEFAULT_OUT_DIR / "proxy_crawl_checkpoint.sqlite"
DEFAULT_PROXY = "http://tntruong196:5f9b-e6-76c0b76d6ac41f-8aab10b1@gateway.sparkproxy.io:11000"

# Precompiled regexes
LONGCHAU_NEXT_RE = re.compile(r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>", re.DOTALL)
CONTENT_CLASS_RE = re.compile(r"content|detail|article|entry|post|body|fck_detail", re.I)
STRIP_TAGS_RE = re.compile(r"related|share|tag|author|comment|social|adv|banner", re.I)


def classify_cluster(url: str) -> str:
    """Classify target URL into domain clusters."""
    host = urlparse(url).hostname or ""
    if "ask.39.net" in host:
        return "ask39"
    if host.endswith(".39.net"):
        return "39net"
    if "nhathuoclongchau.com.vn" in host:
        return "longchau"
    if "cnkang.com" in host:
        return "cnkang"
    if "iiyi.com" in host:
        return "iiyi"
    if any(x in host for x in [".cn", "120ask", "wujue", "familydoctor", "cndzys"]):
        return "china_other"
    if "pharmacity.io" in host:
        return "pharmacity"
    if "pubmed.ncbi.nlm.nih.gov" in host:
        return "pubmed"
    if host.endswith(".vn"):
        return "baovn"
    return "misc"


def extract_ask39(html_content: str, current_url: str = "") -> tuple[str, str]:
    """Smart extractor for ask.39.net clinical Q&A pages."""
    if not html_content or len(html_content) < 400:
        return "", "HTML content too short"
    if "verify.html" in current_url or "滑动拼图验证" in html_content:
        return "", "WAF_CAPTCHA_VERIFY"

    soup = BeautifulSoup(html_content, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    q_div = soup.find(class_="txt_ms") or soup.find(class_="ask_cont")
    q_text = ""
    if q_div:
        for noise in q_div.find_all(class_=["relevant_ask", "other_look", "btn_consult", "my_consult", "ask_hid"]):
            noise.decompose()
        q_raw = q_div.get_text(separator=" ", strip=True)
        for bp in ["我要咨询", "其他人还在看"]:
            if bp in q_raw:
                q_raw = q_raw.split(bp)[0]
        q_text = q_raw.strip()

    doc_div = soup.find(class_="doctor_all") or soup.find(class_="doc_txt")
    doc_info = ""
    if doc_div:
        for btn in doc_div.find_all(class_=["doc_btn", "btn"]):
            btn.decompose()
        doc_info = doc_div.get_text(separator=" ", strip=True)

    ans_div = soup.find(class_="sele_txt") or soup.find(class_="doc_ans")
    ans_text = ""
    if ans_div:
        ans_text = ans_div.get_text(separator="\n\n", strip=True)

    if not title and not ans_text:
        return "", "Missing both title and answer"
    if not ans_text:
        return "", "Question has no verified doctor answer"

    parts = []
    if title:
        parts.append(title)
    if q_text and q_text != title:
        parts.append(f"【患者提问】\n{q_text}")
    if doc_info:
        parts.append(f"【医生信息】\n{doc_info}")
    if ans_text:
        parts.append(f"【医生回复】\n{ans_text}")

    return "\n\n".join(parts).strip(), ""


def extract_39net(html_bytes: bytes, current_url: str = "") -> tuple[str, str]:
    """Smart extraction for 39.net static article subdomains (utf-8 / gb18030)."""
    if "verify.html" in current_url:
        return "", "WAF_CAPTCHA_VERIFY"

    decoded = ""
    for enc in ["utf-8", "gb18030", "gbk"]:
        try:
            decoded = html_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        decoded = html_bytes.decode("utf-8", errors="replace")

    if "滑动拼图验证" in decoded:
        return "", "WAF_CAPTCHA_VERIFY"
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


def extract_cnkang(html_bytes: bytes) -> tuple[str, str]:
    """Smart extractor for cnkang.com health articles."""
    decoded = ""
    for enc in ["utf-8", "gb18030", "gbk"]:
        try:
            decoded = html_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        decoded = html_bytes.decode("utf-8", errors="replace")

    soup = BeautifulSoup(decoded, "html.parser")
    h1 = soup.find("h1") or soup.find("title")
    title = h1.get_text(strip=True) if h1 else ""
    if "_中华康网" in title:
        title = title.replace("_中华康网", "").strip()

    body_el = soup.find(["div", "article"], class_=lambda c: c and ("content" in c or "detail" in c or "art" in c or "main" in c))
    if body_el:
        for junk in body_el.find_all(["script", "style"]):
            junk.decompose()
        body = body_el.get_text(separator="\n\n", strip=True)
    else:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
        body = "\n\n".join(paragraphs)

    parts = [p for p in [title, body] if p]
    return "\n\n".join(parts).strip(), ""


def extract_content(html_bytes: bytes, url: str, cluster: str, final_url: str) -> tuple[str, str]:
    """Multi-domain content extractor dispatcher."""
    try:
        if cluster == "ask39":
            text = html_bytes.decode("utf-8", errors="replace")
            return extract_ask39(text, final_url)
        elif cluster == "39net":
            return extract_39net(html_bytes, final_url)
        elif cluster == "longchau":
            text = html_bytes.decode("utf-8", errors="replace")
            return extract_longchau(text)
        elif cluster == "cnkang":
            return extract_cnkang(html_bytes)
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


class ProxyCrawler:
    def __init__(self, db_path: Path, out_dir: Path, proxy: str, concurrency: int = 180):
        self.db_path = db_path
        self.out_dir = out_dir
        self.proxy = proxy
        self.concurrency = concurrency
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_records (
                    row_index INTEGER NOT NULL,
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    text TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    cluster TEXT NOT NULL,
                    error TEXT,
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cluster ON crawl_records(cluster)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_row_index ON crawl_records(row_index)")

    def get_completed_ids(self) -> set[int]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM crawl_records 
                WHERE success = 1 
                   OR error LIKE '%404%' 
                   OR error LIKE '%410%' 
                   OR error = 'HTTP_403_STAGING_CLOSED'
            """)
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
            out_file = self.out_dir / "data_bosung_all.jsonl"

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

        print(f"[Export] Saved {count:,} records to {out_file}", flush=True)
        return out_file

    async def crawl_targets(self, targets: list[dict], cluster_name: str):
        completed = self.get_completed_ids()
        todo = [t for t in targets if t["id"] not in completed]
        total = len(todo)
        print(f"\n{'='*70}\n[{cluster_name.upper()}] Total targets: {len(targets):,} | Already done: {len(targets) - total:,} | To crawl: {total:,}\n{'='*70}", flush=True)

        if not todo:
            print(f"[{cluster_name.upper()}] All targets already completed!", flush=True)
            self.export_jsonl(cluster_name)
            return

        num_sessions = 8
        workers_per_session = max(1, self.concurrency // num_sessions)
        work_queue: asyncio.Queue = asyncio.Queue()
        for item in todo:
            work_queue.put_nowait(item)

        save_queue: asyncio.Queue = asyncio.Queue()
        sessions = [
            requests.AsyncSession(
                impersonate="chrome120",
                proxy=self.proxy,
                max_clients=workers_per_session + 5,
            )
            for _ in range(num_sessions)
        ]

        crawled_count = 0
        success_count = 0
        failed_count = 0
        start_time = time.perf_counter()

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
                if len(buffer) >= 100:
                    self.save_batch(buffer)
                    buffer.clear()
                save_queue.task_done()

        writer_task = asyncio.create_task(db_writer())

        async def worker_loop(session: requests.AsyncSession):
            nonlocal crawled_count, success_count, failed_count
            while True:
                item = await work_queue.get()
                if item is None:
                    work_queue.task_done()
                    break

                r_idx, doc_id, url, cl = item["row_index"], item["id"], item["url"], item["cluster"]
                text = ""
                success = False
                for attempt in range(6):
                    try:
                        req_timeout = 6.0 if cl == "longchau" else (15.0 if cl == "ask39" else 8.0)
                        resp = await session.get(url, headers={"Connection": "close"}, timeout=req_timeout)
                        final_url = str(resp.url)
                        if resp.status_code == 200:
                            cleaned, err = extract_content(resp.content, url, cl, final_url)
                            if err == "WAF_CAPTCHA_VERIFY":
                                await asyncio.sleep(0.3 + attempt * 0.3)
                                continue
                            if cleaned and len(cleaned) >= 20:
                                text = cleaned
                                success = True
                                error = ""
                            else:
                                success = False
                                error = err or f"Extracted text too short ({len(cleaned)} chars)"
                            break
                        elif resp.status_code in (404, 410):
                            success = False
                            error = f"HTTP {resp.status_code}"
                            break
                        elif resp.status_code in (403, 429, 500, 502, 503, 504):
                            error = f"HTTP {resp.status_code}"
                            await asyncio.sleep(0.2 + attempt * 0.2)
                            continue
                        else:
                            success = False
                            error = f"HTTP {resp.status_code}"
                            await asyncio.sleep(0.2)
                    except Exception as exc:
                        exc_str = str(exc)
                        error = f"{type(exc).__name__}: {exc_str[:100]}"
                        if attempt < 5:
                            await asyncio.sleep(0.2 + attempt * 0.2)
                            continue
                        success = False

                crawled_count += 1
                if success:
                    success_count += 1
                else:
                    failed_count += 1

                await save_queue.put((r_idx, doc_id, url, text, int(success), cl, error))
                work_queue.task_done()

                if crawled_count % 500 == 0 or crawled_count == total:
                    elapsed = time.perf_counter() - start_time
                    speed = crawled_count / elapsed if elapsed > 0 else 0
                    pct = (crawled_count / total) * 100
                    print(f"[{cl.upper()}] {crawled_count:,}/{total:,} ({pct:.1f}%) | Success: {success_count:,} | Fail: {failed_count:,} | Speed: {speed:.1f} URLs/s", flush=True)

        worker_tasks = []
        for sess in sessions:
            for _ in range(workers_per_session):
                worker_tasks.append(asyncio.create_task(worker_loop(sess)))

        # Wait for all items to complete
        await work_queue.join()

        # Stop workers
        for _ in range(len(worker_tasks)):
            await work_queue.put(None)
        await asyncio.gather(*worker_tasks)

        # Close sessions
        for sess in sessions:
            await sess.close()

        # Shutdown writer
        await save_queue.put(None)
        await writer_task

        total_elapsed = time.perf_counter() - start_time
        avg_speed = crawled_count / total_elapsed if total_elapsed > 0 else 0
        print(f"[{cluster_name.upper()} DONE] Finished {crawled_count:,} URLs in {total_elapsed:.1f}s (Avg {avg_speed:.1f} URLs/s) | OK: {success_count:,} | Fail: {failed_count:,}", flush=True)
        self.export_jsonl(cluster_name)


def load_cluster_targets(cluster: str, limit: int = 0) -> list[dict]:
    """Load target records filtered by cluster from data.py."""
    import data
    print(f"[Load] Loading targets for cluster '{cluster}' from data.py...", flush=True)

    targets = []
    for r, doc_id, url in zip(data.ROW_IDS, data.DOC_IDS, data.URLS):
        cl = classify_cluster(url)
        if cluster == "all" or cl == cluster:
            targets.append({
                "row_index": r,
                "id": doc_id,
                "url": url,
                "cluster": cl,
            })
            if limit > 0 and len(targets) >= limit:
                break
    print(f"[Load] Cluster '{cluster}': Found {len(targets):,} targets", flush=True)
    return targets


async def main_async():
    parser = argparse.ArgumentParser(description="Proxy multi-domain gap crawler")
    parser.add_argument("--cluster", choices=["ask39", "cnkang", "39net", "longchau", "china_other", "baovn", "misc", "iiyi", "remaining", "all"], default="remaining")
    parser.add_argument("--proxy", type=str, default=DEFAULT_PROXY)
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--limit", type=int, default=0, help="0 for all")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--export-only", action="store_true", help="Only export DB to JSONL")
    args = parser.parse_args()

    crawler = ProxyCrawler(db_path=args.db, out_dir=args.out_dir, proxy=args.proxy, concurrency=args.concurrency)

    if args.export_only:
        crawler.export_jsonl(args.cluster)
        return

    # Handle pharmacity closed staging URLs once if not already in DB
    pharmacity_targets = load_cluster_targets("pharmacity")
    if pharmacity_targets:
        completed = crawler.get_completed_ids()
        ph_batch = [
            (t["row_index"], t["id"], t["url"], "", 0, "pharmacity", "HTTP_403_STAGING_CLOSED")
            for t in pharmacity_targets if t["id"] not in completed
        ]
        if ph_batch:
            print(f"[Pharmacity] Recording {len(ph_batch):,} closed staging records to DB...", flush=True)
            crawler.save_batch(ph_batch)
            crawler.export_jsonl("pharmacity")

    # Pipeline execution order for all remaining clusters:
    # 1. ask39 (6.2k)
    # 2. cnkang (1.5k)
    # 3. 39net (1.0k)
    # 4. longchau (79k)
    # 5. china_other (0.4k)
    # 6. baovn (0.2k)
    # 7. misc (0.1k)
    # 8. iiyi (0.7k)
    if args.cluster == "remaining":
        clusters_to_run = ["ask39", "cnkang", "39net", "longchau", "china_other", "baovn", "misc", "iiyi"]
        for cl in clusters_to_run:
            targets = load_cluster_targets(cl, limit=args.limit)
            await crawler.crawl_targets(targets, cl)
        return

    targets = load_cluster_targets(args.cluster, limit=args.limit)
    await crawler.crawl_targets(targets, args.cluster)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
