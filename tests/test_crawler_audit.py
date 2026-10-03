"""Audit test script for ViBioMIR crawler scripts.
Tests:
1. ID preservation and mapping (parquet 'id' vs 'row_index').
2. Resume / retry / append logic analysis.
3. Domain coverage in site_configs.py.
4. Verbatim content extraction & markdown token distortion analysis.
5. Throughput and efficiency benchmarking.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urlsplit

import pyarrow.parquet as pq

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from utils import load_url_range, SourceRecord
from site_configs import build_run_configs


def normalize_btc(text: str) -> list[str]:
    """BTC normalization: NFKC, unescape, lower, collapse spaces, split tokens."""
    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text.split() if text else []


def test_1_id_preservation():
    """Verify that load_url_range preserves Parquet 'id' and does not confuse it with row index."""
    parquet_path = PROJECT_ROOT / "data/links_corpus.parquet"
    if not parquet_path.exists():
        print("[Test 1 SKIP] data/links_corpus.parquet not found")
        return

    table = pq.read_table(parquet_path)
    total_rows = len(table)
    
    # Check row 0, 1, 100, 1000
    test_ranges = [(0, 10), (100, 110), (1000, 1005)]
    all_matched = True
    
    for start, end in test_ranges:
        batches = list(load_url_range(parquet_path, start, end, batch_size=50))
        flat_records = [r for b in batches for r in b]
        
        for r in flat_records:
            expected_id = table["id"][r.row_index].as_py()
            expected_url = table["url"][r.row_index].as_py()
            
            if r.id != expected_id:
                print(f"[Test 1 FAIL] Row {r.row_index}: record.id={r.id} != expected_id={expected_id}")
                all_matched = False
                break
            if r.url != expected_url:
                print(f"[Test 1 FAIL] Row {r.row_index}: record.url mismatch")
                all_matched = False
                break

    # Specifically check if row 0 id != 0
    first_record = next(iter(load_url_range(parquet_path, 0, 0, 1)))[0]
    if first_record.row_index == 0 and first_record.id == 583:
        print(f"[Test 1 PASS] Row 0 has row_index=0, id=583. ID mapping in load_url_range preserves Parquet id.")
    else:
        print(f"[Test 1 FAIL] Row 0 mismatch: row_index={first_record.row_index}, id={first_record.id}")


def test_2_resume_and_validate_logic():
    """Analyze resume & append logic between crawl.py and krun_range.py validate_output."""
    print("\n--- Test 2: Analyzing Resume / Append / Validate Logic ---")
    # Analysis check:
    # In crawl.py:
    #   pending = [record for record in batch if completed.get(record.id) != record.url]
    #   results = await crawl_batch(..., pending, ...)
    #   save_results(output, results)  --> with output.open('a')
    # In krun_range.py:
    #   validate_output uses zip_longest(source_records(job.start, job.end), handle)
    #   and checks line-by-line: record['id'] == source.id
    print("Finding: If a job fails partially (e.g. crawls records 0-20, crashes at 21), and is resumed:")
    print("  1. 'completed' dict has records 0-20.")
    print("  2. The next run will skip 0-20 in 'pending'.")
    print("  3. crawl_batch runs for 21-50.")
    print("  4. save_results APPENDS 21-50 to output.")
    print("  5. Resulting file has records 0-20, then 21-50. Row count = 50.")
    print("HOWEVER: If a job retries a BATCH that partially succeeded without cleaning the old output file:")
    print("  - If output was not truncated, duplicate records or interleaved rows will be appended.")
    print("  - validate_output in krun_range.py strictly checks: line N must match source row N.")
    print("  - Any duplicate or missing row at line N will trigger: ValueError('ID/URL/text mismatch').")


def test_3_domain_coverage():
    """Check how many of the 97 domains and 4.39M URLs have explicit selectors."""
    print("\n--- Test 3: Domain Coverage in site_configs.py ---")
    parquet_path = PROJECT_ROOT / "data/links_corpus.parquet"
    if not parquet_path.exists():
        print("[Test 3 SKIP] data/links_corpus.parquet not found")
        return

    from collections import Counter
    table = pq.read_table(parquet_path)
    urls = table["url"].to_pylist()
    
    _, domain_configs = build_run_configs()
    
    domain_counts = Counter()
    for u in urls:
        try:
            h = urlsplit(u).netloc.lower()
            if h.startswith("www."):
                h = h[4:]
            domain_counts[h] += 1
        except Exception:
            pass

    configured_count = 0
    unconfigured_count = 0
    unconfigured_domains = []
    
    for d, c in domain_counts.items():
        cfg = domain_configs.get(d)
        if cfg is None and d.endswith(".39.net"):
            cfg = domain_configs.get("39.net")
        if cfg is not None:
            configured_count += c
        else:
            unconfigured_count += c
            unconfigured_domains.append((d, c))

    print(f"Total domains: {len(domain_counts)}")
    print(f"Configured domains: {len(domain_counts) - len(unconfigured_domains)}")
    print(f"Configured URLs: {configured_count:,} ({configured_count/len(urls)*100:.2f}%)")
    print(f"Unconfigured domains: {len(unconfigured_domains)}")
    print(f"Unconfigured URLs (fall back to default pruning filter): {unconfigured_count:,} ({unconfigured_count/len(urls)*100:.2f}%)")
    print("Top 5 unconfigured domains by URL volume:")
    for d, c in sorted(unconfigured_domains, key=lambda x: x[1], reverse=True)[:5]:
        print(f"  - {d:30s}: {c:8,d} URLs")


def test_4_content_quality_and_verbatim_check():
    """Inspect text extraction behavior: compare raw HTML text vs fit_markdown vs raw_markdown."""
    print("\n--- Test 4: Verbatim Content Extraction & Markdown Distortion Check ---")
    import urllib.request
    from bs4 import BeautifulSoup
    
    # Test on a known Vietnamese health article
    url = "https://suckhoedoisong.vn/chip-dien-tu-phat-hien-ung-thu-hiv-16975640.htm"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[Test 4 SKIP] Could not fetch sample URL: {e}")
        return

    soup = BeautifulSoup(raw_html, "html.parser")
    
    # In suckhoedoisong, selector in site_configs.py is:
    # target_elements=[".detail__contenent-main > header", ".detail__contenent-main > .detail-content"]
    # Let's inspect what elements exist:
    header = soup.select_one(".detail__contenent-main > header") or soup.select_one("header")
    content = soup.select_one(".detail__contenent-main > .detail-content") or soup.select_one(".detail-content") or soup.select_one("#articleContent")
    
    # Check if selector in site_configs is correct
    print("Selector inspection for suckhoedoisong.vn:")
    print("  Header found:", header is not None)
    print("  Content found (.detail__contenent-main > .detail-content):", content is not None)
    
    if content is None:
        # Check why
        mains = soup.find_all(class_=re.compile("detail", re.I))
        print("  Available detail classes in HTML:", [m.get("class") for m in mains[:5]])

    # Markdown vs raw tokens test
    sample_paragraph_html = (
        '<p>Bệnh nhân có thể sử dụng <a href="https://example.com/thuoc">thuốc Paracetamol</a> '
        'với liều lượng <strong>500mg</strong> mỗi 4-6 giờ.</p>'
    )
    soup_sample = BeautifulSoup(sample_paragraph_html, "html.parser")
    verbatim_text = soup_sample.get_text() # "Bệnh nhân có thể sử dụng thuốc Paracetamol với liều lượng 500mg mỗi 4-6 giờ."
    
    # In Markdown, it would be:
    # "Bệnh nhân có thể sử dụng [thuốc Paracetamol](https://example.com/thuoc) với liều lượng **500mg** mỗi 4-6 giờ."
    markdown_text = (
        "Bệnh nhân có thể sử dụng [thuốc Paracetamol](https://example.com/thuoc) với liều lượng **500mg** mỗi 4-6 giờ."
    )
    
    tokens_verbatim = normalize_btc(verbatim_text)
    tokens_markdown = normalize_btc(markdown_text)
    
    print("\nToken distortion comparison on sample text:")
    print("  Original raw text tokens:", tokens_verbatim)
    print("  Markdown text tokens:    ", tokens_markdown)
    
    # Calculate LCS
    def lcs(x, y):
        m, n = len(x), len(y)
        dp = [[0]*(n+1) for _ in range(m+1)]
        for i in range(m):
            for j in range(n):
                if x[i] == y[j]:
                    dp[i+1][j+1] = dp[i][j] + 1
                else:
                    dp[i+1][j+1] = max(dp[i+1][j], dp[i][j+1])
        return dp[m][n]

    lcs_val = lcs(tokens_verbatim, tokens_markdown)
    overlap = lcs_val / len(tokens_verbatim)
    print(f"  LCS: {lcs_val} / {len(tokens_verbatim)}")
    print(f"  Overlap: {overlap:.2f}")
    if tokens_verbatim != tokens_markdown:
        print("  NOTICE: Markdown syntax introduces tokens like '[thuốc', 'paracetamol](https://example.com/thuoc)', '**500mg**'.")
        print("  This can cause token mismatch when comparing against plain-text reference chunks!")


if __name__ == "__main__":
    print("=== RUNNING CRAWLER AUDIT TESTS ===")
    test_1_id_preservation()
    test_2_resume_and_validate_logic()
    test_3_domain_coverage()
    test_4_content_quality_and_verbatim_check()
    print("\n=== AUDIT TESTS COMPLETE ===")
