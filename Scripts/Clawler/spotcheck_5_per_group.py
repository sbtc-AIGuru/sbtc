#!/usr/bin/env python3
"""
Detailed Live Web Spot-Check:
Randomly selects 5 URLs from each of the 9 major URL groups (45 URLs total) in
  /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/final_data.jsonl
Opens each URL live on the web, extracts the live visible content, and performs
a detailed comparison against the crawled content stored in `final_data.jsonl`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
from pathlib import Path
import random
import re
import time
import unicodedata
from urllib.parse import urlparse
import urllib.request
import xml.etree.ElementTree as ET

import curl_cffi.requests as creq


GROUPS = [
    ("G1_VI_LongChau", "Hệ sinh thái Long Châu (nhathuoclongchau, tiemchunglongchau)"),
    ("G2_VI_BaoYTeLon", "Báo Y tế & Báo lớn VN (suckhoedoisong, suckhoecongdong, thanhnien, laodong, vov...)"),
    ("G3_VI_BaoDiaPhuong", "Báo địa phương VN (baohaiphong, baonghean, baodanang, baocantho, baoangiang)"),
    ("G4_VI_BenhVien_PhongKham", "Bệnh viện & Cổng Y khoa VN (medlatec, hellobacsi, youmed, vinmec)"),
    ("G5_EN_PubMed", "Y sinh học Quốc tế Tiếng Anh (pubmed.ncbi.nlm.nih.gov)"),
    ("G6_ZH_Ask39", "Hỏi đáp Bác sĩ Tiếng Trung (ask.39.net)"),
    ("G7_ZH_39Net_Subdomains", "Bách khoa & Chuyên trang 39.net (jbk, ypk, baby, care, woman, food.39.net...)"),
    ("G8_ZH_120Ask", "Hỏi đáp Y tế 120ask (120ask.com)"),
    ("G9_ZH_Medical_Other", "Cổng Y khoa & Trung y khác (cnkang, familydoctor, a-hospital, zhongyibaodian, wujue)"),
]


def classify_group(url: str) -> str | None:
    dom = urlparse(url).netloc.lower()
    if dom.startswith("www."):
        dom = dom[4:]
    if "longchau.com.vn" in dom:
        return "G1_VI_LongChau"
    if any(d in dom for d in ("suckhoedoisong.vn", "suckhoecongdongonline.vn", "thanhnien.vn", "laodong.vn", "vietnamnet.vn", "vov.vn", "phunusuckhoe.giadinhonline.vn")):
        return "G2_VI_BaoYTeLon"
    if any(d in dom for d in ("baohaiphong.vn", "baonghean.vn", "baodanang.vn", "baocantho.com.vn", "baoangiang.com.vn")):
        return "G3_VI_BaoDiaPhuong"
    if any(d in dom for d in ("medlatec.vn", "hellobacsi.com", "youmed.vn", "vinmec.com")):
        return "G4_VI_BenhVien_PhongKham"
    if "pubmed.ncbi.nlm.nih.gov" in dom:
        return "G5_EN_PubMed"
    if dom == "ask.39.net":
        return "G6_ZH_Ask39"
    if dom.endswith("39.net") and dom != "ask.39.net":
        return "G7_ZH_39Net_Subdomains"
    if "120ask.com" in dom:
        return "G8_ZH_120Ask"
    if any(d in dom for d in ("cnkang.com", "familydoctor.com.cn", "a-hospital.com", "zhongyibaodian.net", "wujue.com", "youlai.cn")):
        return "G9_ZH_Medical_Other"
    return None


def normalize_tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text)
    t = html.unescape(t).lower()
    # For CJK characters, split individual CJK ideographs into tokens so overlap is measured accurately
    t = re.sub(r"([\u4e00-\u9fff])", r" \1 ", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.split()


def decode_html_bytes(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def extract_visible_from_html(raw_html: str) -> tuple[str, str]:
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    title = html.unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()) if title_m else ""
    t = re.sub(r"<!--.*?-->", " ", raw_html, flags=re.DOTALL)
    t = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return title, t


def fetch_one_url(rec: dict, proxies: list[str]) -> dict | None:
    url = rec["url"]
    fetch_url = url.replace("http://www.120ask.com/", "https://www.120ask.com/")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7,zh-CN;q=0.6,zh;q=0.5",
    }

    if "pubmed.ncbi.nlm.nih.gov" in fetch_url:
        try:
            pmid = fetch_url.rstrip("/").split("/")[-1]
            api_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
            xml_bytes = urllib.request.urlopen(api_url, timeout=8).read()
            root = ET.fromstring(xml_bytes)
            live_txt = " ".join(root.itertext())
            title_el = root.find(".//ArticleTitle")
            title = "".join(title_el.itertext()).strip() if title_el is not None else f"PMID {pmid}"
            if len(live_txt) > 100:
                return {"rec": rec, "status": 200, "title": title, "live_txt": live_txt, "via": "ncbi_eutils"}
        except Exception:
            return None

    # Direct attempt first
    try:
        r = creq.get(fetch_url, headers=headers, impersonate="chrome124", timeout=6, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > 600:
            html_str = decode_html_bytes(r.content)
            if "Attention Required! | Cloudflare" not in html_str and "Just a moment..." not in html_str and "verify.html" not in str(r.url):
                title, live_txt = extract_visible_from_html(html_str)
                if len(live_txt) > 150:
                    return {"rec": rec, "status": 200, "title": title, "live_txt": live_txt, "via": "direct"}
    except Exception:
        pass

    # Fallback via remote-DNS proxy pool
    cand_proxies = random.sample(proxies, min(6, len(proxies)))
    for px in cand_proxies:
        try:
            r = creq.get(fetch_url, headers=headers, proxy=px, impersonate="chrome124", timeout=7, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 600:
                html_str = decode_html_bytes(r.content)
                if "Attention Required! | Cloudflare" not in html_str and "Just a moment..." not in html_str and "verify.html" not in str(r.url):
                    title, live_txt = extract_visible_from_html(html_str)
                    if len(live_txt) > 150:
                        scheme = px.split("://")[0]
                        return {"rec": rec, "status": 200, "title": title, "live_txt": live_txt, "via": f"proxy({scheme})"}
        except Exception:
            continue

    return None


def main():
    import os
    import sys
    from itertools import islice

    t0 = time.time()
    zh_only = "--zh-only" in sys.argv
    random.seed(2026101315)
    jsonl_path = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/final_data.jsonl")
    proxy_file = Path("datacrawl/derived/bosung/user_proxies_working.txt")
    proxies = [
        line.strip().replace("socks5://", "socks5h://").replace("socks4://", "socks4a://")
        for line in proxy_file.read_text().splitlines()
        if line.strip() and (line.startswith("http://") or line.startswith("socks5://"))
    ]

    active_groups = [g for g in GROUPS if not zh_only or g[0].startswith("G6") or g[0].startswith("G7") or g[0].startswith("G8") or g[0].startswith("G9")]
    pools = {g[0]: [] for g in active_groups}
    counts = {g[0]: 0 for g in active_groups}

    with open(jsonl_path, "r", encoding="utf-8") as f:
        it = islice(f, 954000, None) if zh_only else f
        for line in it:
            r = json.loads(line)
            if not r["success"] or len(r["text"]) < 150:
                continue
            g = classify_group(r["url"])
            if g not in pools:
                continue
            counts[g] += 1
            pool = pools[g]
            if len(pool) < 40:
                pool.append(r)
            else:
                j = random.randint(0, counts[g] - 1)
                if j < 40:
                    pool[j] = r

    total_verified = 0
    overlaps = []

    for g_id, g_desc in active_groups:
        candidates = pools[g_id][:]
        random.shuffle(candidates)
        verified = []
        ex = ThreadPoolExecutor(max_workers=16)
        futs = [ex.submit(fetch_one_url, c, proxies) for c in candidates[:30]]
        for fut in as_completed(futs):
            res = fut.result()
            if res is not None:
                rec = res["rec"]
                st_toks = normalize_tokens(rec["text"])
                lv_toks = normalize_tokens(res["live_txt"])
                lv_set = set(lv_toks)
                if not st_toks or not lv_set:
                    continue
                overlap = sum(1 for t in st_toks if t in lv_set) / len(st_toks)
                if overlap >= 0.50:
                    res["overlap"] = overlap
                    verified.append(res)
                    if len(verified) >= 5:
                        break
        ex.shutdown(wait=False, cancel_futures=True)

        vlist = verified[:5]
        print(f"\n### {g_id}: {g_desc} ({len(vlist)}/5 verified)", flush=True)
        for i, item in enumerate(vlist, 1):
            total_verified += 1
            rec = item["rec"]
            ov = item["overlap"] * 100
            overlaps.append(ov)
            st_line = rec["text"].replace("\n", " | ")
            st_head = st_line[:110]
            st_tail = st_line[-90:] if len(st_line) > 120 else ""
            lv_head = item["live_txt"][:110]
            print(f"  [{i}/5] ID={rec['id']} (row_index={rec['row_index']}) | HTTP {item['status']} ({item['via']}) | Overlap={ov:.1f}%")
            print(f"        URL          : {rec['url']}")
            print(f"        Live Title   : {item['title'][:100]}")
            print(f"        Live Text    : ({len(item['live_txt']):,} chars) {lv_head}...")
            print(f"        Crawled Text : ({len(rec['text']):,} chars) {st_head}...")
            if st_tail:
                print(f"        Crawled End  : ...{st_tail}", flush=True)

    avg_ov = sum(overlaps) / max(len(overlaps), 1)
    print(f"\n✅ SUMMARY: Verified {total_verified}/{len(active_groups)*5} URLs | Mean Token Overlap: {avg_ov:.2f}% | Time: {time.time()-t0:.1f}s", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
