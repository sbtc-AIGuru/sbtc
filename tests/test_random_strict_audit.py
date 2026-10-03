"""Strict audit verification on randomly sampled URLs from links_corpus.parquet.
Checks all 5 constraints from AGENTS.md:
1. Parquet ID preservation (id is untouched integer, not row_index).
2. Plain Verbatim text quality (no markdown distortion).
3. Failure consistency (if success=False, text="").
4. BTC 5-step normalization and tokenization integrity.
5. compact.py deduplication and canonical sorting.
"""

from __future__ import annotations

import asyncio
import html
import json
from pathlib import Path
import re
import sys
import unicodedata
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from compact import compact
from crawl4ai import AsyncWebCrawler
from fetch import crawl_one
from site_configs import build_run_configs
from utils import JsonlWriter, SourceRecord


def normalize_btc(text: str) -> list[str]:
    """Exact BTC 5-step normalization."""
    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text.split() if text else []


class TestStrictRandomAudit(unittest.IsolatedAsyncioTestCase):
    """Rigorous audit against all project invariants on randomly selected URLs."""

    async def test_random_urls_against_all_constraints(self):
        source_parquet = PROJECT_ROOT / "data/links_corpus.parquet"
        if not source_parquet.exists():
            self.skipTest("links_corpus.parquet not found")

        table = pq.read_table(source_parquet)

        # 8 random rows sampled across the entire 4.39M corpus
        test_rows = [
            50,         # Row 50: Bach Mai (VN Hospital)
            120_000,    # Row 120,000: HelloBacsi (VN Portal)
            500_000,    # Row 500,000: Suc Khoe Doi Song (VN Newspaper)
            1_000_050,  # Row 1,000,050: 120Ask (CN Q&A)
            1_500_000,  # Row 1,500,000: Cnkang (CN Advisory)
            1_973_214,  # Row 1,973,214: Wujue (CN Traditional Medicine Multi-page)
            3_000_000,  # Row 3,000,000: A-Hospital (CN MediaWiki)
            4_000_000,  # Row 4,000,000: Youlai (CN Clinical Portal)
        ]

        sample_records: list[SourceRecord] = []
        for sample_idx, row_idx in enumerate(test_rows):
            orig_id = table["id"][row_idx].as_py()
            orig_url = table["url"][row_idx].as_py()
            sample_records.append(SourceRecord(row_index=sample_idx, id=orig_id, url=orig_url))

        # Create temporary sample parquet
        sample_parquet_path = PROJECT_ROOT / "data/test_strict_audit_sample.parquet"
        sample_table = pa.Table.from_arrays(
            [
                pa.array([r.id for r in sample_records], type=pa.int64()),
                pa.array([r.url for r in sample_records], type=pa.string()),
            ],
            names=["id", "url"],
        )
        pq.write_table(sample_table, sample_parquet_path)

        # Output jsonl path
        raw_output_path = PROJECT_ROOT / "data/test_strict_audit_raw.jsonl"
        canonical_output_path = PROJECT_ROOT / "data/test_strict_audit_canonical.jsonl"
        for p in (raw_output_path, canonical_output_path):
            if p.exists():
                p.unlink()

        # Run crawl on all 8 records with dual HTTP + Browser strategies
        run_config, domain_configs = build_run_configs()
        browser_sem = asyncio.Semaphore(2)
        http_sem = asyncio.Semaphore(4)

        results = []
        print("\n=== STARTING STRICT AUDIT ON 8 RANDOM URLS ===")
        async with AsyncWebCrawler() as http_crawler, AsyncWebCrawler() as browser_crawler:
            with JsonlWriter(raw_output_path) as writer:
                for rec in sample_records:
                    print(f"\n[Crawling Row {rec.row_index}] ID={rec.id} URL={rec.url[:65]}...")
                    outcome = await crawl_one(
                        record=rec,
                        browser=browser_crawler,
                        http=http_crawler,
                        browser_semaphore=browser_sem,
                        http_semaphore=http_sem,
                        run_config=run_config,
                        domain_configs=domain_configs,
                        fetch_mode="auto",
                    )
                    writer.write(outcome.payload)
                    results.append(outcome)
                    print(f"  -> Mode: {outcome.mode} | Success: {outcome.payload.get('success')} | Time: {outcome.elapsed_seconds:.2f}s")
                    if not outcome.payload.get("success"):
                        print(f"  -> Error reason: {outcome.payload.get('error')}")

        print("\n=== VERIFYING ALL 5 CONSTRAINTS STRICTLY ===")

        # CONSTRAINT 1: ID Preservation
        for rec, outcome in zip(sample_records, results):
            payload = outcome.payload
            self.assertEqual(
                payload["id"], rec.id,
                f"Constraint 1 VIOLATION: ID altered! Expected {rec.id}, got {payload['id']}"
            )
            self.assertEqual(
                payload["url"], rec.url,
                f"Constraint 1 VIOLATION: URL altered! Expected {rec.url}, got {payload['url']}"
            )
            # Ensure ID is NOT the row index
            self.assertNotEqual(
                payload["id"], payload["row_index"],
                f"Constraint 1 WARNING: ID equals row_index at row {rec.row_index}!"
            )
        print("[Constraint 1 PASS] 100% IDs preserved as immutable Primary Keys.")

        # CONSTRAINT 2 & 3: Verbatim Quality & Failure Consistency
        for outcome in results:
            payload = outcome.payload
            text = payload.get("text", "")
            if payload.get("success"):
                # Must have substantial text
                self.assertGreaterEqual(
                    len(text), 40,
                    f"Constraint 2 VIOLATION: Successful article has too little text: {len(text)} chars"
                )
                # Must NOT contain markdown link syntax [text](url)
                self.assertNotRegex(
                    text, r"\[.*?\]\(http.*?\)",
                    f"Constraint 2 VIOLATION: Markdown link artifact found in ID {payload['id']}"
                )
                # Must NOT contain markdown image syntax ![alt](url)
                self.assertNotRegex(
                    text, r"!\[.*?\]\(.*?\)",
                    f"Constraint 2 VIOLATION: Markdown image artifact found in ID {payload['id']}"
                )
                # Must NOT contain markdown table separator
                self.assertNotIn(
                    "| --- |", text,
                    f"Constraint 2 VIOLATION: Markdown table separator found in ID {payload['id']}"
                )
                # Must NOT contain unclosed broken br tag <br...
                self.assertNotRegex(
                    text, r"<br(?=[^\s>])",
                    f"Constraint 2 VIOLATION: Broken <br tag found in ID {payload['id']}"
                )
            else:
                # If failure, text MUST be empty string
                self.assertEqual(
                    text, "",
                    f"Constraint 3 VIOLATION: Failed record must have empty text string, got: {text[:50]}"
                )
                self.assertTrue(
                    bool(payload.get("error")),
                    f"Constraint 3 VIOLATION: Failed record must have error description in ID {payload['id']}"
                )
        print("[Constraint 2 & 3 PASS] Plain Verbatim text clean & failure consistency verified.")

        # CONSTRAINT 4: BTC 5-Step Normalization Test
        for outcome in results:
            payload = outcome.payload
            if payload.get("success"):
                tokens = normalize_btc(payload["text"])
                self.assertGreaterEqual(
                    len(tokens), 3,
                    f"Constraint 4 VIOLATION: Too few tokens after BTC normalization in ID {payload['id']}"
                )
                # Tokens must not contain unescaped brackets or URL remnants
                for tok in tokens[:50]:
                    self.assertFalse(
                        tok.startswith("[") and "]" in tok,
                        f"Constraint 4 VIOLATION: Markdown token remnant '{tok}' in ID {payload['id']}"
                    )
        print("[Constraint 4 PASS] BTC 5-step normalization passes cleanly on all tokens.")

        # CONSTRAINT 5: compact.py Canonicalization
        raw_lines, success_cnt, fail_cnt = compact(
            source=sample_parquet_path,
            raw=raw_output_path,
            output=canonical_output_path,
            start=0,
            end=len(sample_records) - 1,
        )
        self.assertEqual(raw_lines, len(sample_records))
        self.assertEqual(success_cnt + fail_cnt, len(sample_records))
        self.assertTrue(canonical_output_path.exists())

        # Verify canonical output line order
        canonical_lines = [json.loads(l) for l in canonical_output_path.read_text(encoding="utf-8").splitlines()]
        for idx, row in enumerate(canonical_lines):
            self.assertEqual(row["row_index"], idx)
            self.assertEqual(row["id"], sample_records[idx].id)
        print(f"[Constraint 5 PASS] compact.py verified: {success_cnt} success, {fail_cnt} failed, canonical order preserved.")

        print("\n=== ALL 5 CONSTRAINTS VERIFIED & PASSED 100% ===")


if __name__ == "__main__":
    unittest.main()
