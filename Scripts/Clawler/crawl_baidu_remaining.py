"""Crawl rescued remaining Baidu Health URLs (2,037 targets from Phase 1b).

High quality verbatim extraction for Baidu Medical Encyclopedia.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
import httpx
import pyarrow.parquet as pq

# Import repository verbatim cleaner
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Scripts" / "Preprocess"))
sys.path.insert(0, str(REPO_ROOT / "Scripts" / "Clawler"))
from verbatim import clean_to_verbatim  # type: ignore

PARQUET_PATH = REPO_ROOT / "data" / "links_corpus.parquet"
DERIVED_DIR = REPO_ROOT.parent / "datacrawl" / "derived"
INPUT_IDS_JSON = DERIVED_DIR / "phase1b_baidu_remaining_ids.json"
OUTPUT_JSONL = DERIVED_DIR / "crawled_phase1b_baidu_rescued.jsonl"

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def extract_baidu_verbatim(html_text: str) -> tuple[bool, str, str]:
    """Extract clean verbatim encyclopedia text from Baidu Health HTML."""
    if not html_text or len(html_text) < 100:
        return False, "", "Empty or too short HTML response"

    soup = BeautifulSoup(html_text, "html.parser")

    # Remove script, style, comments, nav, footer
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "nav", "footer"]):
        tag.decompose()

    # Title
    h1 = soup.find("h1")
    title_text = h1.get_text(strip=True) if h1 else ""
    if not title_text and soup.title:
        title_text = soup.title.get_text(strip=True).split("-")[0].strip()

    # Content block
    dict_content = soup.find(class_=lambda c: c and "health-dict" in c)
    if not dict_content:
        # Fallback to general container
        dict_content = soup.find("article") or soup.find("main") or soup.body

    body_text = dict_content.get_text("\n\n", strip=True) if dict_content else ""

    # Combine heading and body
    full_text = f"{title_text}\n\n{body_text}".strip() if title_text and title_text not in body_text else body_text.strip()
    verbatim_text = clean_to_verbatim(full_text)

    if len(verbatim_text) < 50:
        return False, "", f"Extracted text too short ({len(verbatim_text)} chars)"

    return True, verbatim_text, ""


async def fetch_one(
    client: httpx.AsyncClient,
    row_idx: int,
    doc_id: int,
    url: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Fetch single Baidu URL with retries."""
    max_retries = 3
    async with semaphore:
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(random.uniform(0.04, 0.08))
                resp = await client.get(url, headers=HEADERS, timeout=12.0)

                if resp.status_code == 200:
                    if len(resp.text) == 0:
                        return {
                            "row_index": row_idx,
                            "id": doc_id,
                            "url": url,
                            "success": False,
                            "text": "",
                            "error": "Empty body (Deleted entry on Baidu)",
                        }
                    succ, text, err = extract_baidu_verbatim(resp.text)
                    return {
                        "row_index": row_idx,
                        "id": doc_id,
                        "url": url,
                        "success": succ,
                        "text": text,
                        "error": err,
                    }
                elif resp.status_code in (404, 410):
                    return {
                        "row_index": row_idx,
                        "id": doc_id,
                        "url": url,
                        "success": False,
                        "text": "",
                        "error": f"HTTP {resp.status_code}",
                    }
                else:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    return {
                        "row_index": row_idx,
                        "id": doc_id,
                        "url": url,
                        "success": False,
                        "text": "",
                        "error": f"HTTP {resp.status_code}",
                    }
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return {
                    "row_index": row_idx,
                    "id": doc_id,
                    "url": url,
                    "success": False,
                    "text": "",
                    "error": f"Network Error: {type(e).__name__}",
                }
            except Exception as e:
                return {
                    "row_index": row_idx,
                    "id": doc_id,
                    "url": url,
                    "success": False,
                    "text": "",
                    "error": f"Unexpected Error: {e}",
                }

    return {
        "row_index": row_idx,
        "id": doc_id,
        "url": url,
        "success": False,
        "text": "",
        "error": "Max retries exceeded",
    }


async def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Baidu Health rescue crawler...")
    with open(INPUT_IDS_JSON, "r", encoding="utf-8") as f:
        target_row_indices = json.load(f)

    print(f"Loaded {len(target_row_indices)} target row indices from {INPUT_IDS_JSON}")

    # Read manifest from parquet
    print(f"Reading manifest from {PARQUET_PATH}...")
    table = pq.read_table(PARQUET_PATH)
    urls = table["url"].to_pylist()
    ids = table["id"].to_pylist()

    targets = [(idx, ids[idx], urls[idx]) for idx in target_row_indices]
    print(f"Prepared {len(targets)} targets. First: row_index={targets[0][0]}, id={targets[0][1]}")

    concurrency = 8
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=25)

    start_time = time.time()
    results = []
    processed = 0
    success_count = 0
    failed_count = 0

    batch_size = 50
    async with httpx.AsyncClient(limits=limits, follow_redirects=True, timeout=15.0) as client:
        for i in range(0, len(targets), batch_size):
            batch = targets[i : i + batch_size]
            tasks = [fetch_one(client, r_idx, d_id, u, semaphore) for r_idx, d_id, u in batch]
            batch_results = await asyncio.gather(*tasks)

            for res in batch_results:
                results.append(res)
                processed += 1
                if res["success"]:
                    success_count += 1
                else:
                    failed_count += 1

            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta_m = (len(targets) - processed) / rate / 60 if rate > 0 else 0
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Progress: {processed}/{len(targets)} ({processed/len(targets)*100:.1f}%) | "
                f"Speed: {rate:.1f} URLs/s | Success: {success_count} | Failed: {failed_count} | "
                f"ETA: {eta_m:.1f}m"
            )

    # Sort results in ascending row_index order
    results.sort(key=lambda r: r["row_index"])

    # Write to output JSONL
    print(f"\nWriting results to {OUTPUT_JSONL}...")
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Baidu rescue complete! "
        f"Total: {len(results)} | Success: {success_count} ({success_count/len(results)*100:.2f}%) | "
        f"Failed: {failed_count} | Output: {OUTPUT_JSONL}"
    )


if __name__ == "__main__":
    asyncio.run(main())
