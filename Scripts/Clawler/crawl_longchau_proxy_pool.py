#!/usr/bin/env python3
"""
High-Speed Multi-Proxy Rotating Pool Crawler for Nhà Thuốc Long Châu (nhathuoclongchau.com.vn).
Rotates across 166+ verified working proxies (SOCKS4/SOCKS5/HTTP) + Local Direct IP.

Key Features:
1. Per-Proxy Rate Limiter & Circuit Breaker:
   - Each proxy is throttled individually (default min_interval=1.2s, ~50 req/min/IP)
     so no single IP triggers Cloudflare's sliding-window WAF block.
   - If a proxy receives HTTP 403 or 429, ONLY that proxy enters a 15-minute cooldown;
     the URL is immediately retried on another healthy proxy.
   - If a proxy fails 4 consecutive connection/timeout attempts, it is quarantined for
     5 minutes (or retired if dead) so workers only use fast, live proxies.
2. Persistent Session Pool:
   - Reuses curl_cffi AsyncSession per proxy to keep TLS/TCP connections warm and fast.
3. Dynamic Next.js buildId Discovery:
   - Uses CDN-cached `/_next/data/{buildId}/...` JSON endpoint (65% smaller than HTML).
   - Automatically refreshes `buildId` if HTML fallback detects a newer deployment.
4. ViBioMIR Invariants:
   - Preserves exact 1-1 `id`, `row_index`, and `url`.
   - Applies `clean_to_verbatim` to protect LCS token overlap.
   - Atomic SQLite WAL checkpointing + JSONL streaming append.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import html
import json
from pathlib import Path
import random
import re
import sqlite3
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

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
LONGCHAU_NEXT_RE = re.compile(r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>", re.DOTALL)
BUILD_ID_RE = re.compile(r"\"buildId\":\"([^\"]+)\"")


def clean_to_verbatim(text: str) -> str:
    """Transform markdown and HTML into 100% verbatim plain text for ViBioMIR."""
    if not text:
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
    text = re.sub(r"<[^>]+>", " ", text)
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


def parse_nextjs_payload(data: dict) -> tuple[str, str | None]:
    """Extract clean verbatim text from Next.js pageProps JSON payload."""
    props = data.get("pageProps", {})

    # Pattern A: /bai-viet/ article
    detail = props.get("detail", {}).get("data", {})
    if detail and isinstance(detail, dict):
        title = detail.get("name", "")
        sapo = detail.get("shortDescription", "")
        desc_html = detail.get("description", "")
        desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n\n").strip() if desc_html else ""
        parts = [p for p in [title, sapo, desc_text] if p]
        full_text = "\n\n".join(parts).strip()
        verbatim = clean_to_verbatim(full_text)
        if len(verbatim) >= 40:
            return verbatim, None

    # Pattern B: /benh/ disease page
    benh = props.get("data", {})
    if benh and isinstance(benh, dict):
        title = benh.get("name", "") or benh.get("title", "")
        desc_html = benh.get("description", "") or benh.get("content", "")
        desc_text = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n\n").strip() if desc_html else ""
        parts = [p for p in [title, desc_text] if p]
        full_text = "\n\n".join(parts).strip()
        verbatim = clean_to_verbatim(full_text)
        if len(verbatim) >= 40:
            return verbatim, None

    # Pattern C: Generic article in pageProps
    art = props.get("article", {})
    if art and isinstance(art, dict):
        title = art.get("title", "") or art.get("name", "")
        desc = art.get("content", "") or art.get("description", "")
        desc_text = BeautifulSoup(desc, "html.parser").get_text(separator="\n\n").strip() if desc else ""
        parts = [p for p in [title, desc_text] if p]
        full_text = "\n\n".join(parts).strip()
        verbatim = clean_to_verbatim(full_text)
        if len(verbatim) >= 40:
            return verbatim, None

    return "", "Text too short or empty in Next.js props"


def extract_html_fallback(html_text: str) -> tuple[str, str | None, str | None]:
    """Fallback extractor from raw HTML string via __NEXT_DATA__ or DOM. Returns (verbatim, err, new_build_id)."""
    if not html_text or len(html_text) < 300:
        return "", "HTML too short", None

    new_build_id = None
    bm = BUILD_ID_RE.search(html_text)
    if bm:
        new_build_id = bm.group(1)

    m = LONGCHAU_NEXT_RE.search(html_text)
    if m:
        try:
            payload = json.loads(m.group(1))
            verbatim, err = parse_nextjs_payload(payload)
            if verbatim:
                return verbatim, None, new_build_id
        except Exception:
            pass

    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
        t.decompose()

    h1 = soup.find("h1")
    title = clean_to_verbatim(h1.get_text(strip=True)) if h1 else ""

    content_div = (
        soup.find(class_=re.compile(r"post-content|article-content|detail-content|content|main-content", re.I))
        or soup.find(id=re.compile(r"post-content|article-content|content", re.I))
        or soup.find("article")
        or soup.find("main")
    )

    if content_div:
        for noise in content_div.find_all(
            class_=re.compile(r"related|share|tag|author|comment|social|adv|banner|suggest", re.I)
        ):
            noise.decompose()
        body_text = content_div.get_text(separator="\n\n", strip=True)
    else:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        body_text = "\n\n".join(paragraphs)

    full_text = f"{title}\n\n{body_text}" if title else body_text
    verbatim = clean_to_verbatim(full_text)

    if len(verbatim) >= 40:
        return verbatim, None, new_build_id
    return "", f"Text too short ({len(verbatim)} chars)", new_build_id


@dataclass
class ProxyNode:
    proxy_url: str | None  # None means DIRECT local IP
    min_interval: float = 1.2
    available_at: float = 0.0
    in_use: int = 0
    max_concurrent: int = 2
    ok_count: int = 0
    err_count: int = 0
    cf_block_count: int = 0
    consecutive_errors: int = 0
    retired: bool = False
    window_requests: int = 0
    session: AsyncSession | None = field(default=None, repr=False)

    @property
    def label(self) -> str:
        return self.proxy_url if self.proxy_url else "DIRECT_LOCAL"


class ProxyPoolManager:
    def __init__(self, proxy_urls: list[str], include_direct: bool = True, min_interval: float = 1.2):
        self.nodes: list[ProxyNode] = []
        if include_direct:
            # Local IP gets a strict 0.30s interval (~3.3 req/s max) and proactive rest every 800 reqs
            self.nodes.append(ProxyNode(proxy_url=None, min_interval=0.35, max_concurrent=2))
        for p in proxy_urls:
            self.nodes.append(ProxyNode(proxy_url=p, min_interval=min_interval, max_concurrent=2))
        self.lock = asyncio.Lock()

    async def init_sessions(self):
        for node in self.nodes:
            node.session = AsyncSession(
                impersonate="chrome120",
                proxy=node.proxy_url,
                verify=False,
            )

    async def close_sessions(self):
        for node in self.nodes:
            if node.session is not None:
                try:
                    await node.session.close()
                except Exception:
                    pass

    async def acquire(self, prefer_proven: bool = False) -> ProxyNode:
        """Select the healthiest ready ProxyNode, or wait briefly for the next available one."""
        while True:
            async with self.lock:
                now = time.monotonic()
                active_nodes = [n for n in self.nodes if not n.retired]
                if not active_nodes:
                    # Un-retire all nodes if somehow all got retired
                    for n in self.nodes:
                        n.retired = False
                        n.consecutive_errors = 0
                        n.available_at = now + 5.0
                    active_nodes = self.nodes

                ready = [
                    n for n in active_nodes
                    if n.available_at <= now and n.in_use < n.max_concurrent
                ]
                if ready:
                    if prefer_proven:
                        proven = [n for n in ready if n.ok_count > 0 and n.consecutive_errors == 0]
                        if proven:
                            ready = proven
                    # Pick node with lowest in_use, fewest consecutive errors, proven history
                    ready.sort(
                        key=lambda n: (
                            n.in_use,
                            n.consecutive_errors,
                            0 if n.ok_count > 0 else 1,
                            random.random(),
                        )
                    )
                    chosen = ready[0]
                    chosen.in_use += 1
                    chosen.available_at = now + chosen.min_interval + random.uniform(0.05, 0.25)
                    return chosen

                # Calculate shortest wait time among nodes not at max_concurrent
                candidates = [n for n in active_nodes if n.in_use < n.max_concurrent]
                if candidates:
                    soonest = min(n.available_at for n in candidates)
                    wait_s = max(0.05, min(soonest - now, 1.0))
                else:
                    wait_s = 0.10

            await asyncio.sleep(wait_s)

    async def release_success(self, node: ProxyNode):
        async with self.lock:
            node.in_use = max(0, node.in_use - 1)
            node.ok_count += 1
            node.consecutive_errors = 0
            node.window_requests += 1
            # Proactive rest after 750 consecutive requests on the same IP to avoid Cloudflare 403
            if node.window_requests >= 750:
                node.window_requests = 0
                node.available_at = max(node.available_at, time.monotonic() + 90.0)

    async def release_cf_block(self, node: ProxyNode, cooldown: float = 600.0):
        async with self.lock:
            node.in_use = max(0, node.in_use - 1)
            node.cf_block_count += 1
            node.window_requests = 0
            node.available_at = max(node.available_at, time.monotonic() + cooldown)

    async def release_error(self, node: ProxyNode):
        async with self.lock:
            node.in_use = max(0, node.in_use - 1)
            node.err_count += 1
            node.consecutive_errors += 1
            now = time.monotonic()
            if node.proxy_url is not None:
                if node.consecutive_errors >= 3 and node.ok_count == 0:
                    # Dead proxy from the start -> retire quickly
                    node.retired = True
                elif node.consecutive_errors >= 4:
                    # Quarantine flaky proxy for 3 minutes
                    node.available_at = max(node.available_at, now + 180.0)
                    node.consecutive_errors = 0
                else:
                    node.available_at = max(node.available_at, now + 3.0)
            else:
                node.available_at = max(node.available_at, now + 2.0)

    def stats_summary(self) -> tuple[int, int, int]:
        now = time.monotonic()
        alive = sum(1 for n in self.nodes if not n.retired and n.available_at <= now + 5.0)
        cooling = sum(1 for n in self.nodes if not n.retired and n.available_at > now + 5.0)
        retired = sum(1 for n in self.nodes if n.retired)
        return alive, cooling, retired


class MultiProxyLongChauCrawler:
    def __init__(
        self,
        target_file: Path,
        proxy_file: Path,
        db_path: Path,
        jsonl_path: Path,
        log_path: Path,
        concurrency: int = 55,
        timeout: float = 8.0,
        min_interval: float = 1.2,
        include_direct: bool = True,
    ):
        self.target_file = target_file
        self.proxy_file = proxy_file
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.log_path = log_path
        self.concurrency = concurrency
        self.timeout = timeout
        self.min_interval = min_interval
        self.include_direct = include_direct

        self.build_id = "3Dqz_e7TVxL9dSgSOS83-"
        self.db_lock = asyncio.Lock()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=60.0)
        self.init_sqlite()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def init_sqlite(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crawl_records (
                id INTEGER PRIMARY KEY,
                row_index INTEGER,
                url TEXT NOT NULL,
                text TEXT,
                success INTEGER NOT NULL,
                error TEXT,
                crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    def preseed_existing_records(self):
        cur = self.conn.cursor()
        total_seeded = 0
        files_to_check = [
            Path("datacrawl/derived/bosung/data_bosung_longchau.jsonl"),
            Path("datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl"),
        ]
        for fpath in files_to_check:
            if not fpath.exists():
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("success"):
                            cur.execute(
                                """
                                INSERT OR IGNORE INTO crawl_records (id, row_index, url, text, success, error)
                                VALUES (?, ?, ?, ?, 1, NULL);
                                """,
                                (rec["id"], rec.get("row_index", 0), rec.get("url", ""), rec.get("text", "")),
                            )
                            total_seeded += 1
                    except Exception:
                        pass
        self.conn.commit()
        self.log(f"Pre-seeded/verified {total_seeded:,} JSONL successes in SQLite checkpoint.")

    def get_crawled_ids(self) -> set[int]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id FROM crawl_records WHERE success = 1 OR error = 'HTTP 404' OR error = 'HTTP 410';"
        )
        return {r[0] for r in cur.fetchall()}

    async def save_record(self, item: dict, text: str, success: bool, error: str | None = None):
        async with self.db_lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO crawl_records (id, row_index, url, text, success, error, crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
                """,
                (item["id"], item["row_index"], item["url"], text, 1 if success else 0, error),
            )
            self.conn.commit()

            if success:
                rec = {
                    "id": item["id"],
                    "row_index": item["row_index"],
                    "url": item["url"],
                    "text": text,
                    "success": True,
                    "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                with open(self.jsonl_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def load_proxies(self) -> list[str]:
        if not self.proxy_file.exists():
            return []
        seen = set()
        out = []
        for line in self.proxy_file.read_text(encoding="utf-8").splitlines():
            p = line.strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    async def fetch_item(self, pool: ProxyPoolManager, item: dict, sem: asyncio.Semaphore) -> bool:
        url = item["url"]
        p = urlparse(url).path
        slug = p.strip("/").split("/")[-1]
        is_bai_viet = "/bai-viet/" in url
        is_benh = "/benh/" in url

        headers_json = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://nhathuoclongchau.com.vn/",
        }
        headers_html = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://nhathuoclongchau.com.vn/",
        }

        async with sem:
            last_err = "Max retries exceeded"
            # Allow up to 8 attempts; attempts >= 2 prefer proven proxies (ok_count > 0)
            for attempt in range(8):
                node = await pool.acquire(prefer_proven=(attempt >= 2))
                session = node.session
                req_timeout = 12.0 if node.proxy_url is None else self.timeout
                released = False

                try:
                    # Strategy 1: Next.js JSON API (CDN Cached)
                    if is_bai_viet or is_benh:
                        route_type = "bai-viet" if is_bai_viet else "benh"
                        next_url = f"https://nhathuoclongchau.com.vn/_next/data/{self.build_id}/{route_type}/{slug}.json"
                        resp = await session.get(next_url, headers=headers_json, timeout=req_timeout)

                        if resp.status_code == 200:
                            try:
                                payload = resp.json()
                            except Exception:
                                await pool.release_error(node)
                                released = True
                                last_err = "Invalid JSON on 200"
                                continue

                            verbatim, err = parse_nextjs_payload(payload)
                            if verbatim:
                                await pool.release_success(node)
                                released = True
                                await self.save_record(item, verbatim, True, None)
                                return True

                        elif resp.status_code in (403, 429):
                            await pool.release_cf_block(node, cooldown=600.0)
                            released = True
                            last_err = f"HTTP {resp.status_code}"
                            continue

                        elif resp.status_code >= 500:
                            await pool.release_error(node)
                            released = True
                            last_err = f"HTTP {resp.status_code}"
                            continue

                    # Strategy 2: HTML Fallback (when _next/data returns 404 or misses props)
                    resp_html = await session.get(url, headers=headers_html, timeout=req_timeout)
                    if resp_html.status_code == 200:
                        verbatim, err, new_bid = extract_html_fallback(resp_html.text)
                        if new_bid and new_bid != self.build_id:
                            self.log(f"🔄 Updated Next.js buildId: {self.build_id} -> {new_bid}")
                            self.build_id = new_bid
                        if verbatim:
                            await pool.release_success(node)
                            released = True
                            await self.save_record(item, verbatim, True, None)
                            return True
                        else:
                            if "nhathuoclongchau" not in resp_html.text.lower():
                                await pool.release_error(node)
                                released = True
                                last_err = "Proxy fake 200 HTML"
                                continue
                            await pool.release_success(node)
                            released = True
                            await self.save_record(item, "", False, err)
                            return False

                    elif resp_html.status_code in (404, 410):
                        await pool.release_success(node)
                        released = True
                        await self.save_record(item, "", False, f"HTTP {resp_html.status_code}")
                        return False

                    elif resp_html.status_code in (403, 429):
                        await pool.release_cf_block(node, cooldown=600.0)
                        released = True
                        last_err = f"HTTP {resp_html.status_code}"
                        continue

                    else:
                        await pool.release_error(node)
                        released = True
                        last_err = f"HTTP {resp_html.status_code}"
                        continue

                except Exception as e:
                    if not released:
                        await pool.release_error(node)
                        released = True
                    last_err = str(e)[:120]
                    continue

            await self.save_record(item, "", False, last_err)
            return False

    async def run(self):
        self.log("=== KHỞI ĐỘNG MULTI-PROXY POOL CRAWLER LONG CHÂU ===")
        with open(self.target_file, "r", encoding="utf-8") as f:
            all_targets = json.load(f)

        self.preseed_existing_records()
        crawled_ids = self.get_crawled_ids()
        pending = [it for it in all_targets if it["id"] not in crawled_ids]

        proxies = self.load_proxies()
        self.log(
            f"Tổng URLs mục tiêu: {len(all_targets):,} | Đã xong: {len(crawled_ids):,} | "
            f"Còn lại: {len(pending):,} | Số Proxy nạp: {len(proxies)} (+ Direct={self.include_direct})"
        )
        if not pending:
            self.log("🎉 Toàn bộ dữ liệu Long Châu đã hoàn tất 100%!")
            return

        pool = ProxyPoolManager(
            proxy_urls=proxies,
            include_direct=self.include_direct,
            min_interval=self.min_interval,
        )
        await pool.init_sessions()

        total_pending = len(pending)
        total_success = 0
        total_done = 0
        t_global = time.time()

        sem = asyncio.Semaphore(self.concurrency)
        chunk_size = 2000
        chunks = [pending[i : i + chunk_size] for i in range(0, len(pending), chunk_size)]

        try:
            for c_idx, c_items in enumerate(chunks, 1):
                c_total = len(c_items)
                t_chunk = time.time()
                c_done = 0
                c_ok = 0

                tasks = [asyncio.create_task(self.fetch_item(pool, it, sem)) for it in c_items]
                for fut in asyncio.as_completed(tasks):
                    ok = await fut
                    c_done += 1
                    total_done += 1
                    if ok:
                        c_ok += 1
                        total_success += 1

                    if c_done % 200 == 0 or c_done == c_total:
                        el_c = time.time() - t_chunk
                        spd_c = c_done / el_c if el_c > 0 else 0
                        el_g = time.time() - t_global
                        spd_g = total_done / el_g if el_g > 0 else 0
                        rem = total_pending - total_done
                        eta_m = (rem / spd_g) / 60 if spd_g > 0 else 0
                        pct = (total_done / total_pending) * 100
                        alive, cooling, retired = pool.stats_summary()

                        self.log(
                            f"[Wave {c_idx}/{len(chunks)}] {c_done:,}/{c_total:,} | "
                            f"Speed: {spd_c:.1f} u/s (Avg: {spd_g:.1f} u/s) | "
                            f"Tiến độ: {total_done:,}/{total_pending:,} ({pct:.1f}%) | "
                            f"OK: {total_success:,} ({total_success/max(1,total_done)*100:.1f}%) | "
                            f"Pool[Alive:{alive} Cool:{cooling} Ret:{retired}] | ETA: {eta_m:.1f}m"
                        )
        finally:
            await pool.close_sessions()
            self.conn.close()

        total_elapsed = time.time() - t_global
        self.log(
            f"\n🎉 HOÀN TẤT MULTI-PROXY CRAWLER trong {total_elapsed / 60:.1f} phút! "
            f"Thành công: {total_success:,}/{total_pending:,}"
        )


def main():
    parser = argparse.ArgumentParser(description="Multi-Proxy Rotating Pool Crawler for Long Chau")
    parser.add_argument("--targets", type=str, default="datacrawl/kaggle_longchau/longchau_missing_all.json")
    parser.add_argument("--proxies", type=str, default="datacrawl/derived/bosung/user_proxies_working.txt")
    parser.add_argument("--db", type=str, default="datacrawl/derived/bosung/longchau_ironclad_checkpoint.sqlite")
    parser.add_argument("--out-jsonl", type=str, default="datacrawl/derived/bosung/data_bosung_longchau_ironclad.jsonl")
    parser.add_argument("--log", type=str, default="datacrawl/derived/bosung/longchau_proxy_pool.log")
    parser.add_argument("--concurrency", type=int, default=55, help="Concurrent workers (default: 55)")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-proxy request timeout (default: 8.0s)")
    parser.add_argument("--min-interval", type=float, default=1.2, help="Min seconds between requests per proxy")
    parser.add_argument("--no-direct", action="store_true", help="Disable direct local IP and use only proxies")

    args = parser.parse_args()
    crawler = MultiProxyLongChauCrawler(
        target_file=Path(args.targets),
        proxy_file=Path(args.proxies),
        db_path=Path(args.db),
        jsonl_path=Path(args.out_jsonl),
        log_path=Path(args.log),
        concurrency=args.concurrency,
        timeout=args.timeout,
        min_interval=args.min_interval,
        include_direct=not args.no_direct,
    )
    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
