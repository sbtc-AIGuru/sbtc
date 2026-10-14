"""High-performance NCBI E-utilities API crawler for PubMed ViBioMIR corpus.
Crawls 240,000 PubMed articles using official NCBI E-fetch XML batching.
Features:
- Batches up to 200 PMIDs per HTTP request (~1,200 requests total).
- Respects NCBI rate limit (3 requests/sec default, 10 req/s with API key).
- Preserves exact id and row_index mapping from newcorpus/links_corpus_vi_en_zh.parquet.
- Extracts Title + full AbstractText with XML itertext (100% Raw Extracted Text).
- SQLite WAL checkpointing + Streaming JSONL export to datacrawl/derived/bosung/
- Fully compliant with ViBioMIR invariants.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests
import pyarrow.parquet as pq

# Repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
PARQUET_PATH = REPO_ROOT / "newcorpus/links_corpus_vi_en_zh.parquet"
DEFAULT_OUT_DIR = REPO_ROOT / "datacrawl/derived/bosung"
DEFAULT_DB_PATH = DEFAULT_OUT_DIR / "pubmed_crawl_checkpoint.sqlite"
DEFAULT_JSONL_PATH = DEFAULT_OUT_DIR / "data_bosung_pubmed.jsonl"

NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PMID_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


def parse_pubmed_xml(xml_bytes: bytes) -> dict[str, tuple[str, bool, str]]:
    """Parse PubMed XML and extract title + abstract for each PMID.
    Returns: dict of pmid -> (text, success, error)
    """
    results: dict[str, tuple[str, bool, str]] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return {}, f"XML_PARSE_ERROR: {e}"

    # 1. Parse standard PubmedArticle
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            pmid_el = art.find(".//PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()

        title_el = art.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        abstract_parts = []
        for abs_el in art.findall(".//AbstractText"):
            label = abs_el.get("Label")
            part_text = "".join(abs_el.itertext()).strip()
            if label and not part_text.upper().startswith(label.upper()):
                abstract_parts.append(f"{label}: {part_text}")
            elif part_text:
                abstract_parts.append(part_text)

        full_text = title
        if abstract_parts:
            if full_text:
                full_text += "\n\n" + "\n\n".join(abstract_parts)
            else:
                full_text = "\n\n".join(abstract_parts)

        if full_text:
            cleaned_text = html.unescape(full_text.strip())
            results[pmid] = (cleaned_text, True, "")
        else:
            results[pmid] = ("", False, "EMPTY_TITLE_AND_ABSTRACT")

    # 2. Parse PubmedBookArticle (books, StatPearls)
    for art in root.findall(".//PubmedBookArticle"):
        pmid_el = art.find(".//BookDocument/PMID")
        if pmid_el is None or not pmid_el.text:
            pmid_el = art.find(".//PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()

        title_el = art.find(".//ArticleTitle") or art.find(".//BookTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        abstract_parts = []
        for abs_el in art.findall(".//AbstractText"):
            label = abs_el.get("Label")
            part_text = "".join(abs_el.itertext()).strip()
            if label and not part_text.upper().startswith(label.upper()):
                abstract_parts.append(f"{label}: {part_text}")
            elif part_text:
                abstract_parts.append(part_text)

        full_text = title
        if abstract_parts:
            if full_text:
                full_text += "\n\n" + "\n\n".join(abstract_parts)
            else:
                full_text = "\n\n".join(abstract_parts)

        if full_text:
            cleaned_text = html.unescape(full_text.strip())
            results[pmid] = (cleaned_text, True, "")
        else:
            results[pmid] = ("", False, "EMPTY_BOOK_ARTICLE")

    return results, ""


class PubMedCrawler:
    def __init__(self, db_path: Path, out_dir: Path, batch_size: int = 200, delay: float = 0.35, api_key: str = ""):
        self.db_path = db_path
        self.out_dir = out_dir
        self.batch_size = batch_size
        self.delay = delay
        self.api_key = api_key
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
                    cluster TEXT NOT NULL DEFAULT 'pubmed',
                    error TEXT,
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_row_index ON crawl_records(row_index)")

    def get_completed_ids(self) -> set[int]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM crawl_records WHERE success = 1")
            return {row[0] for row in cur.fetchall()}

    def save_batch(self, batch: list[tuple]):
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO crawl_records (row_index, id, url, text, success, cluster, error)
                VALUES (?, ?, ?, ?, ?, 'pubmed', ?)
            """, batch)

    def export_jsonl(self) -> Path:
        out_file = self.out_dir / "data_bosung_pubmed.jsonl"
        with sqlite3.connect(self.db_path, timeout=30.0) as conn, open(out_file, "w", encoding="utf-8") as f:
            cur = conn.cursor()
            cur.execute("SELECT row_index, id, url, text, success, error FROM crawl_records ORDER BY row_index ASC")
            count = 0
            for r_idx, doc_id, url, text, success, error in cur:
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
        print(f"[Export] Saved {count:,} PubMed records to {out_file} ({out_file.stat().st_size / 1024 / 1024:.2f} MB)")
        return out_file

    async def crawl_all(self, targets: list[dict]):
        completed = self.get_completed_ids()
        todo = [t for t in targets if t["id"] not in completed]
        total_targets = len(targets)
        todo_count = len(todo)
        print(f"[PUBMED] Total targets: {total_targets:,} | Already completed: {total_targets - todo_count:,} | To crawl: {todo_count:,}")

        if not todo:
            print("[PUBMED] All PubMed targets already crawled successfully!")
            self.export_jsonl()
            return

        session = requests.AsyncSession(impersonate="chrome120")
        start_time = time.perf_counter()
        crawled_count = 0
        success_count = 0
        failed_count = 0

        # Chunk todo into batches of self.batch_size
        batches = [todo[i:i + self.batch_size] for i in range(0, todo_count, self.batch_size)]
        print(f"[PUBMED] Split {todo_count:,} items into {len(batches):,} batches (Batch size: {self.batch_size})", flush=True)

        for b_idx, batch in enumerate(batches):
            pmid_map = {t["pmid"]: t for t in batch}
            pmids_str = ",".join(pmid_map.keys())

            params = {
                "db": "pubmed",
                "id": pmids_str,
                "retmode": "xml",
            }
            if self.api_key:
                params["api_key"] = self.api_key

            # Request with retry
            db_records = []
            for attempt in range(4):
                try:
                    resp = await session.get(
                        NCBI_EFETCH_URL,
                        params=params,
                        timeout=25,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                    )
                    if resp.status_code == 200:
                        parsed_articles, err = parse_pubmed_xml(resp.content)
                        if err:
                            raise ValueError(err)

                        # Match parsed articles back to targets
                        for pmid, t_info in pmid_map.items():
                            if pmid in parsed_articles:
                                text, ok, err_msg = parsed_articles[pmid]
                                db_records.append((t_info["row_index"], t_info["id"], t_info["url"], text, 1 if ok else 0, err_msg))
                                if ok:
                                    success_count += 1
                                else:
                                    failed_count += 1
                            else:
                                # Not in XML (rare deleted PMID)
                                db_records.append((t_info["row_index"], t_info["id"], t_info["url"], "", 0, "PMID_NOT_RETURNED_BY_NCBI"))
                                failed_count += 1
                        break
                    elif resp.status_code == 429:
                        # Rate limited, backoff
                        await asyncio.sleep(2.0 * (attempt + 1))
                    else:
                        await asyncio.sleep(1.0 * (attempt + 1))
                except Exception as ex:
                    if attempt == 3:
                        for pmid, t_info in pmid_map.items():
                            db_records.append((t_info["row_index"], t_info["id"], t_info["url"], "", 0, f"FETCH_EXCEPTION: {str(ex)[:100]}"))
                            failed_count += 1
                    else:
                        await asyncio.sleep(1.5 * (attempt + 1))

            if db_records:
                self.save_batch(db_records)

            crawled_count += len(batch)

            # Polite delay between batch requests
            if self.delay > 0:
                await asyncio.sleep(self.delay)

            # Log progress every 5 batches or at end
            if (b_idx + 1) % 5 == 0 or (b_idx + 1) == len(batches):
                elapsed = time.perf_counter() - start_time
                speed = crawled_count / elapsed if elapsed > 0 else 0
                pct = (crawled_count / todo_count) * 100
                print(f"[PUBMED] {crawled_count:,}/{todo_count:,} ({pct:.1f}%) | Success: {success_count:,} | Fail: {failed_count:,} | Speed: {speed:.1f} URLs/s", flush=True)

        total_elapsed = time.perf_counter() - start_time
        avg_speed = crawled_count / total_elapsed if total_elapsed > 0 else 0
        print(f"\n[PUBMED DONE] Crawled {crawled_count:,} URLs in {total_elapsed:.1f}s (Avg {avg_speed:.1f} URLs/s) | OK: {success_count:,} | Fail: {failed_count:,}", flush=True)
        self.export_jsonl()


def load_pubmed_targets(limit: int = 0) -> list[dict]:
    """Load all PubMed targets from newcorpus/links_corpus_vi_en_zh.parquet."""
    print(f"[Load] Reading PubMed targets from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH, columns=["id", "url"])
    id_col = table.column("id")
    url_col = table.column("url")

    targets = []
    for r in range(len(table)):
        u = url_col[r].as_py()
        if "pubmed.ncbi.nlm.nih.gov" in u:
            m = PMID_RE.search(u)
            if m:
                targets.append({
                    "row_index": r,
                    "id": id_col[r].as_py(),
                    "url": u,
                    "pmid": m.group(1),
                })
                if limit > 0 and len(targets) >= limit:
                    break
    print(f"[Load] Loaded {len(targets):,} PubMed targets with valid PMIDs.")
    return targets


async def main_async():
    parser = argparse.ArgumentParser(description="PubMed NCBI E-fetch Batch Crawler")
    parser.add_argument("--batch-size", type=int, default=200, help="PMIDs per request (default: 200)")
    parser.add_argument("--delay", type=float, default=0.34, help="Delay between requests in seconds (default: 0.34)")
    parser.add_argument("--limit", type=int, default=0, help="0 for all 240,000")
    parser.add_argument("--api-key", type=str, default="", help="Optional NCBI API Key")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--export-only", action="store_true", help="Only export DB to JSONL")
    args = parser.parse_args()

    crawler = PubMedCrawler(
        db_path=args.db,
        out_dir=args.out_dir,
        batch_size=args.batch_size,
        delay=args.delay,
        api_key=args.api_key
    )

    if args.export_only:
        crawler.export_jsonl()
        return

    targets = load_pubmed_targets(limit=args.limit)
    await crawler.crawl_all(targets)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
