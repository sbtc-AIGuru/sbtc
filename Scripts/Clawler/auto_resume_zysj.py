"""Auto-Bridge & Resume Orchestrator for zysjonline.com.

Monitors Cloudflare cooldown status every 3 minutes.
The moment Cloudflare WAF releases the IP cooldown, it automatically launches
the sustained hybrid crawler to crawl through the night seamlessly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys
import time

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Scripts" / "Clawler"))
from crawl_zysj_hybrid import DEFAULT_UA, log, run_crawler  # type: ignore


async def check_cloudflare_status() -> bool:
    """Probe zysjonline.com article to check if Cloudflare WAF rate limit is released."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context(user_agent=DEFAULT_UA, locale="zh-CN,zh;q=0.9", viewport={"width": 1366, "height": 768})
            page = await context.new_page()

            await page.goto("https://zysjonline.com/html/yaofang/41235.html", wait_until="domcontentloaded", timeout=20000)

            # Check if Turnstile is present and click
            for _ in range(12):
                await asyncio.sleep(1)
                for f in page.frames:
                    if "challenges.cloudflare.com" in f.url:
                        elem = await f.frame_element()
                        if elem:
                            box = await elem.bounding_box()
                            if box:
                                await page.mouse.move(box["x"] + 25, box["y"] + box["height"] / 2)
                                await asyncio.sleep(0.1)
                                await page.mouse.down()
                                await asyncio.sleep(0.1)
                                await page.mouse.up()
                                break
                t = await page.title()
                if "中医世家" in t or "方" in t:
                    await browser.close()
                    return True

            body = await page.inner_text("body")
            await browser.close()
            if "403 Forbidden" in body or "Just a moment" in t:
                return False

            return "中医世家" in t or "方" in t
    except Exception as e:
        log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Probe check exception: {e}")
        return False


async def bridge_loop():
    log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Starting Cloudflare Cooldown Auto-Bridge monitor...")

    check_interval = 180  # check every 3 minutes
    attempt = 1

    while True:
        log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Probe #{attempt}: checking Cloudflare status...")
        is_open = await check_cloudflare_status()

        if is_open:
            log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] >>> CLOUDFLARE WAF COOLDOWN RELEASED! <<<")
            log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Launching sustained crawler (concurrency=12)...")
            try:
                await run_crawler(concurrency=12, batch_save_size=200)
                log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Sustained crawler completed successfully!")
                break
            except Exception as e:
                log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Crawler encountered exception: {e}. Will re-probe in {check_interval}s...")
                await asyncio.sleep(check_interval)
        else:
            log(f"[{datetime.now().strftime('%H:%M:%S')}] [Bridge] Cooldown still active (403). Sleeping {check_interval}s before next probe...")
            attempt += 1
            await asyncio.sleep(check_interval)


if __name__ == "__main__":
    asyncio.run(bridge_loop())
