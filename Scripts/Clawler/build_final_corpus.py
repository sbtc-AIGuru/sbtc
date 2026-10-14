#!/usr/bin/env python3
"""
Build the unified, quality-verified final corpus for ViBioMIR:
  /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/final_data.jsonl
  (plus hardlink final_data.jsonj)

Reads all 1,194,469 target (id, url) pairs from:
  /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/newcorpus/links_corpus_vi_en_zh.parquet

Consolidates records across all JSONL files and SQLite checkpoints in `datacrawl/`,
applies `clean_to_verbatim` normalization (ViBioMIR Invariant #3), selects the
highest-quality record when an ID was crawled multiple times (verified against live
web ground truth), and writes 1,194,469 records in exact New Corpus order.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlparse

import pyarrow.parquet as pq

# ==============================================================================
# Verbatim Cleaner (Strictly conforming to ViBioMIR LCS token overlap standards)
# ==============================================================================
PROTECTED_PATTERN = re.compile(r"\x00([0-9a-f]{2})\x00")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\[[^\]]*\]")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
REFERENCE_DEFINITION_PATTERN = re.compile(r"^\s*\[[^\]]+\]:\s*https?://[^\n]*$", re.MULTILINE | re.IGNORECASE)
BARE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
DATA_IMAGE_PATTERN = re.compile(r"data:image/[^\s<>)\]]+", re.IGNORECASE)
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_TAG_PATTERN = re.compile(r"</?[a-zA-Z!][a-zA-Z0-9:_-]*(\s+[^>]*)?>|<!--.*?-->", re.DOTALL)


def clean_to_verbatim(text: str) -> str:
    """Chuyển đổi Markdown/HTML thành Plain Verbatim Text nguyên bản 100%."""
    if not text:
        return ""
    # Reject binary/compressed garbage where >15% of characters are replacement chars or control chars
    ufffd_cnt = text.count("\ufffd")
    if ufffd_cnt > 10 and (ufffd_cnt / len(text)) > 0.15:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<br\b[^>]*>?|<br(?=[^\s>])", " ", text, flags=re.IGNORECASE)
    text = HTML_IMAGE_PATTERN.sub("", text)
    text = MARKDOWN_IMAGE_PATTERN.sub(lambda m: m.group(1), text)
    text = REFERENCE_IMAGE_PATTERN.sub(lambda m: m.group(1), text)
    text = MARKDOWN_LINK_PATTERN.sub(lambda m: m.group(1), text)
    text = REFERENCE_DEFINITION_PATTERN.sub("", text)
    text = BARE_URL_PATTERN.sub("", text)
    text = DATA_IMAGE_PATTERN.sub("", text)
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|?\s*[-:]+[-| :]*\|?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"[*_~`]", "", text)
    text = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>~\"'$])", r"\1", text)
    text = PROTECTED_PATTERN.sub(lambda m: chr(int(m.group(1), 16)), text)
    # Strip isolated stray \ufffd symbols (<=2% of text) from otherwise valid UTF-8 articles
    if "\ufffd" in text and (text.count("\ufffd") / max(len(text), 1)) <= 0.02:
        text = text.replace("\ufffd", "")
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


# Boilerplate / junk signatures identified during live web inspection
NAV_JUNK_SIGNATURES = (
    "Mới nhất\n\nThời sự\n\nDiễn đàn\n\nNhân sự",
    "医学网站首页五绝医学科研教学医疗服务",
    "用手机扫描二维码在手机上继续观看",
    "Quan tâm nhất\n\nMới nhất\n\nXem thêm bình luận\n\nÝ kiến của bạn",
)

WAF_JUNK_SIGNATURES = (
    "attention required! | cloudflare",
    "just a moment...",
    "verify.html",
    "cf-browser-verification",
)


def score_candidate(text: str, url: str, source_name: str, base_priority: int, raw_ufffd_cnt: int = 0) -> float:
    """
    Compute an empirical quality score for a cleaned candidate text.
    Higher score wins. Grounded in live web comparisons across overlapping IDs.
    """
    if not text:
        return -1e9

    low = text.lower()
    for waf_sig in WAF_JUNK_SIGNATURES:
        if waf_sig in low and len(text) < 1500:
            return -1e6

    score = float(base_priority * 100)
    tlen = len(text)

    # 1. Penalty for genuine encoding corruption (>2% mojibake), mild penalty for isolated stray \ufffd
    if "\ufffd" in text or (raw_ufffd_cnt / max(tlen, 1)) > 0.02:
        score -= 50000.0
    elif raw_ufffd_cnt > 0:
        score -= min(raw_ufffd_cnt * 100.0, 800.0)

    # 2. Heavy penalty for navigation-menu-only or QR/comment boilerplate captures
    for nav_sig in NAV_JUNK_SIGNATURES:
        if nav_sig in text:
            score -= 80000.0

    # 3. Penalty for ultra-short stub captures (< 80 chars) or truncated snippets
    if tlen < 60:
        score -= 40000.0
    elif tlen < 140:
        score -= 15000.0

    if text.endswith("……") and tlen < 150:
        score -= 20000.0
    if text.endswith("\n\n详细") and tlen < 200:
        score -= 20000.0

    # 4. Domain-specific completeness bonuses verified against live web
    if "ask.39.net" in url:
        if "医生回复" in text:
            score += 20000.0
        if "其他人还在看" in text and "医生回复" not in text:
            score -= 10000.0

    if "nhathuoclongchau.com.vn" in url and source_name in ("longchau_ironclad", "longchau_sqlite", "longchau_old"):
        score += 20000.0

    if "pubmed.ncbi.nlm.nih.gov" in url and source_name.startswith("pubmed"):
        score += 20000.0

    if source_name in ("rescued_iiyi_wb", "rescued_zh_wb"):
        score += 25000.0

    # 5. For repaired_vi_zh: bonus on encyclopedia/cnkang where repaired_vi_zh extracted full body
    if source_name in ("repaired_vi_zh", "repair_sqlite"):
        if any(d in url for d in ("cnkang.com", "a-hospital.com", "zhongyibaodian.net")) and tlen >= 300:
            score += 4000.0

    # Mild length bonus (capped) so fuller articles beat truncated ones within similar tiers
    score += min(tlen, 6000) * 0.15
    return score


def main():
    t0 = time.time()
    nc_path = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/newcorpus/links_corpus_vi_en_zh.parquet")
    out_dir = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / "final_data.jsonl"
    out_jsonj = out_dir / "final_data.jsonj"
    tmp_jsonl = out_dir / "final_data.jsonl.tmp"

    print(f"[1/4] Loading New Corpus from {nc_path}...")
    table = pq.read_table(nc_path)
    nc_ids: list[int] = table.column("id").to_pylist()
    nc_urls: list[str] = table.column("url").to_pylist()
    nc_url_map: dict[int, str] = dict(zip(nc_ids, nc_urls))
    total_targets = len(nc_ids)
    print(f"      Loaded {total_targets:,} target (id, url) pairs.")

    # Store best record per ID:
    # best_texts[id] = cleaned_text
    # best_scores[id] = float score
    # best_sources[id] = source_name
    # best_errors[id] = error string (for failed records)
    best_texts: dict[int, str] = {}
    best_scores: dict[int, float] = {}
    best_sources: dict[int, str] = {}
    best_errors: dict[int, str] = {}
    multi_crawled_updates = 0
    multi_crawled_kept = 0

    def consider_record(rid: int, raw_text: str | None, success: bool, error: str | None, source_name: str, base_prio: int):
        nonlocal multi_crawled_updates, multi_crawled_kept
        if rid not in nc_url_map:
            return
        if not success or not raw_text:
            if rid not in best_texts and error and rid not in best_errors:
                best_errors[rid] = str(error)
            return

        cleaned = clean_to_verbatim(raw_text)
        if not cleaned:
            if rid not in best_texts and rid not in best_errors:
                best_errors[rid] = "Empty after clean_to_verbatim"
            return

        url = nc_url_map[rid]
        sc = score_candidate(cleaned, url, source_name, base_prio, raw_text.count("\ufffd"))
        if sc < -1e5:
            return

        if rid not in best_scores:
            best_texts[rid] = cleaned
            best_scores[rid] = sc
            best_sources[rid] = source_name
        else:
            if sc > best_scores[rid]:
                best_texts[rid] = cleaned
                best_scores[rid] = sc
                best_sources[rid] = source_name
                multi_crawled_updates += 1
            else:
                multi_crawled_kept += 1

    # Ordered list of all JSONL sources: (source_name, path, base_priority)
    jsonl_sources = [
        ("rescued_iiyi_wb", "datacrawl/derived/bosung/data_rescued_iiyi_wayback.jsonl", 95),
        ("rescued_zh_wb", "datacrawl/derived/bosung/data_rescued_zh_wayback.jsonl", 95),
        ("pubmed_main", "datacrawl/derived/bosung/data_bosung_pubmed.jsonl", 95),
        ("pubmed_s2", "datacrawl/derived/bosung/data_rescued_pubmed.jsonl", 95),
        ("pubmed_oa", "datacrawl/derived/bosung/data_rescued_pubmed_openalex.jsonl", 95),
        ("longchau_ironclad", "datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl", 95),
        ("longchau_old", "datacrawl/derived/bosung/data_bosung_longchau.jsonl", 90),
        ("baovn", "datacrawl/derived/bosung/data_bosung_baovn.jsonl", 90),
        ("baovn_misc", "datacrawl/derived/bosung/data_bosung_baovn_misc.jsonl", 90),
        ("bosung_39net", "datacrawl/derived/bosung/data_bosung_39net.jsonl", 88),
        ("bosung_ask39", "datacrawl/derived/bosung/data_bosung_ask39.jsonl", 88),
        ("phase1_ask39", "datacrawl/dataraw_main/crawled_phase1_priority3_ask39.jsonl", 86),
        ("bosung_cnkang", "datacrawl/derived/bosung/data_bosung_cnkang.jsonl", 85),
        ("bosung_china_other", "datacrawl/derived/bosung/data_bosung_china_other.jsonl", 82),
        ("bosung1", "datacrawl/dataraw_main/data_bosung1.jsonl", 85),
        ("bosung2", "datacrawl/dataraw_main/data_bosung2.jsonl", 85),
        ("bosung4", "datacrawl/dataraw_main/data_bosung4.jsonl", 85),
        ("kaggle_20261011", "datacrawl/dataraw_main/crawled_local_kaggle_success_unique_20261011.jsonl", 84),
        ("data_main", "datacrawl/dataraw_main/data.jsonl", 80),
        ("repaired_vi_zh", "datacrawl/derived/bosung/data_repaired_vi_zh.jsonl", 78),
        ("bosung_iiyi", "datacrawl/derived/bosung/data_bosung_iiyi.jsonl", 50),
        ("bosung_pharmacity", "datacrawl/derived/bosung/data_bosung_pharmacity.jsonl", 50),
    ]

    print("[2/4] Scanning JSONL sources...")
    for sname, spath, prio in jsonl_sources:
        p = Path(spath)
        if not p.exists():
            continue
        ts = time.time()
        before = len(best_texts)
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rid = rec.get("id")
                if rid is not None:
                    consider_record(
                        int(rid),
                        rec.get("text"),
                        bool(rec.get("success")),
                        rec.get("error"),
                        sname,
                        prio,
                    )
        added = len(best_texts) - before
        print(f"      + {sname:20s}: +{added:7,d} new OK (Total OK: {len(best_texts):9,d}) [{time.time()-ts:.1f}s]")

    # SQLite checkpoints (crucial for the 24,257 records in crawl_checkpoint.sqlite)
    sqlite_sources = [
        ("crawl_cp_sqlite", "datacrawl/derived/bosung/crawl_checkpoint.sqlite", "crawl_records", 87, {
            "bosung_39net", "bosung_ask39", "bosung_cnkang", "bosung_china_other", "baovn", "longchau_old"
        }),
        ("proxy_cp_sqlite", "datacrawl/derived/bosung/proxy_crawl_checkpoint.sqlite", "crawl_records", 86, set()),
        ("longchau_sqlite", "datacrawl/derived/bosung/longchau_ironclad_checkpoint.sqlite", "crawl_records", 94, {
            "longchau_ironclad"
        }),
        ("pubmed_sqlite", "datacrawl/derived/bosung/pubmed_crawl_checkpoint.sqlite", "crawl_records", 94, {
            "pubmed_main", "pubmed_s2", "pubmed_oa"
        }),
        ("ask39_sqlite", "datacrawl/derived/ask39_crawl_checkpoint.sqlite", "crawled_records", 86, {
            "phase1_ask39"
        }),
        ("zysj_sqlite", "datacrawl/derived/zysj_crawl_checkpoint.sqlite", "crawled_records", 85, set()),
        ("repair_sqlite", "datacrawl/derived/bosung/repair_crawl_checkpoint.sqlite", "repair_records", 78, {
            "repaired_vi_zh"
        }),
    ]

    print("[3/4] Scanning SQLite checkpoints...")
    for sname, spath, tbl, prio, exported_set in sqlite_sources:
        p = Path(spath)
        if not p.exists():
            continue
        ts = time.time()
        before = len(best_texts)
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute(f"SELECT id, text, success, error FROM {tbl};")
        for rid, txt, succ, err in cur:
            if rid is not None:
                rid_int = int(rid)
                if exported_set and best_sources.get(rid_int) in exported_set:
                    continue
                consider_record(rid_int, txt, bool(succ), err, sname, prio)
        conn.close()
        added = len(best_texts) - before
        print(f"      + {sname:20s}: +{added:7,d} new OK (Total OK: {len(best_texts):9,d}) [{time.time()-ts:.1f}s]")

    print(f"\n      Multi-crawled comparisons resolved: {multi_crawled_updates:,} upgraded, {multi_crawled_kept:,} kept.")
    from collections import Counter
    src_counts = Counter(best_sources.values())
    print("      Winning source breakdown:")
    for sname, cnt in src_counts.most_common():
        print(f"        - {sname:20s}: {cnt:9,d}")

    print(f"\n[4/4] Writing {total_targets:,} records to {out_jsonl}...")
    ok_written = 0
    fail_written = 0
    with open(tmp_jsonl, "w", encoding="utf-8") as fout:
        for row_idx, (rid, url) in enumerate(zip(nc_ids, nc_urls)):
            if rid in best_texts:
                rec = {
                    "id": rid,
                    "row_index": row_idx,
                    "url": url,
                    "text": best_texts[rid],
                    "success": True,
                    "error": None,
                }
                ok_written += 1
            else:
                rec = {
                    "id": rid,
                    "row_index": row_idx,
                    "url": url,
                    "text": "",
                    "success": False,
                    "error": best_errors.get(rid, "Not available / Origin down"),
                }
                fail_written += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

    os.replace(tmp_jsonl, out_jsonl)
    if out_jsonj.exists() or out_jsonj.is_symlink():
        out_jsonj.unlink()
    os.link(out_jsonl, out_jsonj)

    size_gb = out_jsonl.stat().st_size / (1024**3)
    print("\n======================================================================")
    print(f"✅ COMPLETED in {time.time() - t0:.1f}s!")
    print(f"   Output file 1 : {out_jsonl} ({size_gb:.2f} GB)")
    print(f"   Output file 2 : {out_jsonj} (hardlink, 0 extra disk space)")
    print(f"   Total records : {total_targets:,}")
    print(f"   Success (OK)  : {ok_written:,} ({ok_written / total_targets * 100:.2f}%)")
    print(f"   Failed/Dead   : {fail_written:,} ({fail_written / total_targets * 100:.2f}%)")
    print("======================================================================")


if __name__ == "__main__":
    main()
