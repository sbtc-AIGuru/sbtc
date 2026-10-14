#!/usr/bin/env python3
"""
Targeted Re-crawler and Deep Diagnostic for Chinese Medical Websites.
Focuses on recoverable failures in:
- www.wujue.com (gb18030 encoding + <td class="main"> EmpireCMS)
- *.39.net subdomains & ask.39.net (transient proxy timeouts)
- www.cnkang.com (ultra-short forum posts + encoding)
- www.120ask.com & familydoctor.com.cn (HTTP -> HTTPS upgrades)
"""

import sys
import os
import re
import html
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from curl_cffi import requests

DB_PATH = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung/proxy_crawl_checkpoint.sqlite")
OUT_DIR = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/bosung")
PROXY = "http://tntruong196:5f9b-e6-76c0b76d6ac41f-8aab10b1@gateway.sparkproxy.io:11000"
PROXIES = {"http": PROXY, "https": PROXY}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def clean_html_elements(soup: BeautifulSoup):
    for tag in soup(["script", "style", "iframe", "noscript", "svg"]):
        tag.decompose()

def extract_wujue(html_bytes: bytes) -> tuple[str, str]:
    decoded = ""
    for enc in ["gb18030", "gbk", "utf-8"]:
        try:
            decoded = html_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not decoded:
        decoded = html_bytes.decode("utf-8", errors="replace")
    
    soup = BeautifulSoup(decoded, "html.parser")
    clean_html_elements(soup)
    
    h1 = soup.find("h1") or soup.find("title")
    title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"_[^_]+中医五绝网.*$", "", title).strip()
    
    td = soup.find("td", class_="main")
    if td:
        for junk in td.find_all("table"):
            # keep small inline tables or remove outer menus
            pass
        body = td.get_text(separator="\n\n", strip=True)
    else:
        body_el = soup.find(["div", "article", "td"], class_=re.compile(r"content|detail|text", re.I))
        if body_el:
            body = body_el.get_text(separator="\n\n", strip=True)
        else:
            paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 15]
            body = "\n\n".join(paragraphs)
            
    parts = [p for p in [title, body] if p]
    res = "\n\n".join(parts).strip()
    if len(res) >= 20:
        return res, ""
    return "", f"Wujue content too short ({len(res)} chars)"

def extract_cnkang(html_bytes: bytes) -> tuple[str, str]:
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
    clean_html_elements(soup)
    
    h1 = soup.find("h1") or soup.find("title")
    title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"_[^_]+中华康网.*$", "", title).strip()
    
    # Check for short forum post or article body
    body_el = soup.find(["div", "article", "td"], class_=lambda c: c and ("content" in c or "detail" in c or "art" in c or "main" in c))
    if body_el:
        body = body_el.get_text(separator="\n\n", strip=True)
    else:
        # Check text lines in body
        lines = [line.strip() for line in soup.body.get_text(separator="\n").splitlines() if line.strip()] if soup.body else []
        # Filter out obvious header/footer keywords
        ignore_kw = {"男性", "女性", "健康", "生活", "医学", "您的位置：", "中华康网", "最新文章排行", "精彩推荐"}
        good_lines = [l for l in lines if l not in ignore_kw and not l.startswith(">>") and not l.startswith("www.cnkang.com")]
        body = "\n\n".join(good_lines)
        
    parts = [p for p in [title, body] if p]
    res = "\n\n".join(parts).strip()
    if len(res) >= 15:
        return res, ""
    return "", f"cnkang content too short ({len(res)} chars)"

def extract_120ask(html_bytes: bytes) -> tuple[str, str]:
    decoded = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(decoded, "html.parser")
    clean_html_elements(soup)
    
    h1 = soup.find("h1") or soup.find("title")
    title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"_[^_]+快速问医生.*$", "", title).strip()
    
    # Q&A containers
    parts = [title] if title else []
    ask_box = soup.find(["div", "p"], class_=lambda c: c and ("crazy_new" in c or "b_askbox" in c or "ask-desc" in c))
    if ask_box:
        parts.append(ask_box.get_text(separator="\n\n", strip=True))
        
    ans_divs = soup.find_all("div", class_=lambda c: c and ("b_anscont" in c or "reply-text" in c or "answer_con" in c))
    for a in ans_divs:
        txt = a.get_text(separator="\n\n", strip=True)
        if len(txt) > 10:
            parts.append(txt)
            
    if len(parts) == 1 and not ans_divs and not ask_box:
        body_el = soup.find(["div", "article"], class_=re.compile(r"content|detail", re.I))
        if body_el:
            parts.append(body_el.get_text(separator="\n\n", strip=True))
            
    res = "\n\n".join(parts).strip()
    if len(res) >= 20:
        return res, ""
    return "", f"120ask content too short ({len(res)} chars)"

def extract_39net(html_bytes: bytes) -> tuple[str, str]:
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
    clean_html_elements(soup)
    
    h1 = soup.find("h1") or soup.find("title")
    title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"_[^_]+39健康网.*$", "", title).strip()
    
    body_el = soup.find(["div", "article"], class_=lambda c: c and ("art_content" in c or "content" in c or "detail" in c))
    if body_el:
        body = body_el.get_text(separator="\n\n", strip=True)
    else:
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
        body = "\n\n".join(paras)
        
    parts = [p for p in [title, body] if p]
    res = "\n\n".join(parts).strip()
    if len(res) >= 30:
        return res, ""
    return "", f"39net content too short ({len(res)} chars)"

def extract_ask39(html_text: str) -> tuple[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    clean_html_elements(soup)
    
    title_el = soup.find(["h1", "p"], class_=lambda c: c and ("ask_tit" in c or "title" in c))
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        h1 = soup.find("h1") or soup.find("title")
        title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"_[^_]+39问医生.*$", "", title).strip()
    
    desc_el = soup.find(["div", "p"], class_=lambda c: c and ("sub_tit" in c or "ask_desc" in c or "question-desc" in c))
    desc = desc_el.get_text(separator="\n\n", strip=True) if desc_el else ""
    
    answers = []
    ans_divs = soup.find_all("div", class_=lambda c: c and ("doc_answer" in c or "answer_con" in c or "ans_box" in c or "reply_con" in c))
    for a in ans_divs:
        t = a.get_text(separator="\n\n", strip=True)
        if len(t) > 15:
            answers.append(t)
            
    parts = [p for p in [title, desc] + answers if p]
    res = "\n\n".join(parts).strip()
    if len(res) >= 30:
        return res, ""
    if not answers:
        return "", "Question has no verified doctor answer"
    return "", f"ask39 content too short ({len(res)} chars)"

def fetch_single(url: str) -> tuple[int, bytes, str]:
    """Fetch URL trying local IP first, then SparkProxy if needed."""
    candidate_urls = [url]
    if url.startswith("http://") and any(d in url for d in ["120ask.com", "cnkang.com", "familydoctor.com.cn"]):
        candidate_urls.insert(0, url.replace("http://", "https://", 1))
        
    for target_url in candidate_urls:
        # Try 1: Local IP
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=7, impersonate="chrome120")
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.status_code, resp.content, ""
            elif resp.status_code in [404, 410]:
                return resp.status_code, resp.content, f"HTTP {resp.status_code}"
            elif resp.status_code == 521:
                return 521, b"", "HTTP 521 Origin Server Down"
        except Exception:
            pass
            
        # Try 2: SparkProxy
        try:
            resp = requests.get(target_url, proxies=PROXIES, headers=HEADERS, timeout=8, impersonate="chrome120")
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.status_code, resp.content, ""
            elif resp.status_code in [404, 410]:
                return resp.status_code, resp.content, f"HTTP {resp.status_code}"
            elif resp.status_code == 521:
                return 521, b"", "HTTP 521 Origin Server Down"
        except Exception as e:
            last_err = str(e)
            
    return 0, b"", f"Connection failed: {last_err[:100]}"

def run_recrawl():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Select failed Chinese records
    cur.execute("""
        SELECT row_index, id, url, cluster, error 
        FROM crawl_records 
        WHERE success = 0 
          AND cluster IN ('wujue', 'china_other', '39net', 'ask39', 'cnkang')
    """)
    failed_rows = cur.fetchall()
    print(f"Total failed Chinese URLs to process: {len(failed_rows)}")
    
    recovered = 0
    confirmed_404 = 0
    confirmed_down = 0
    
    for idx, (row_index, doc_id, url, cluster, old_err) in enumerate(failed_rows, 1):
        domain = urlparse(url).netloc
        print(f"[{idx}/{len(failed_rows)}] ID {doc_id} | {domain} | {url[:60]}...", end=" ", flush=True)
        
        status, content, fetch_err = fetch_single(url)
        
        if status == 200 and content:
            # Extract based on domain
            if "wujue.com" in domain:
                extracted, ext_err = extract_wujue(content)
            elif "cnkang.com" in domain:
                extracted, ext_err = extract_cnkang(content)
            elif "120ask.com" in domain:
                extracted, ext_err = extract_120ask(content)
            elif "39.net" in domain and "ask.39.net" not in domain:
                extracted, ext_err = extract_39net(content)
            elif "ask.39.net" in domain:
                extracted, ext_err = extract_ask39(content.decode("utf-8", errors="replace"))
            else:
                # Default
                text = content.decode("utf-8", errors="replace")
                soup = BeautifulSoup(text, "html.parser")
                clean_html_elements(soup)
                h1 = soup.find("h1") or soup.find("title")
                title = h1.get_text(strip=True) if h1 else ""
                body = soup.find(["article", "div"], class_=re.compile(r"content|detail", re.I))
                body_text = body.get_text(separator="\n\n", strip=True) if body else ""
                extracted = f"{title}\n\n{body_text}".strip()
                ext_err = "" if len(extracted) >= 30 else "Extracted text too short"
                
            if extracted and not ext_err:
                cur.execute("""
                    UPDATE crawl_records 
                    SET text = ?, success = 1, error = NULL 
                    WHERE id = ?
                """, (extracted, doc_id))
                conn.commit()
                recovered += 1
                print(f"-> RECOVERED ({len(extracted)} chars)")
                continue
            else:
                cur.execute("""
                    UPDATE crawl_records 
                    SET text = ?, success = 0, error = ? 
                    WHERE id = ?
                """, (extracted if extracted else "", ext_err, doc_id))
                conn.commit()
                print(f"-> PARSE FAILED ({ext_err})")
        elif status in [404, 410]:
            confirmed_404 += 1
            cur.execute("""
                UPDATE crawl_records 
                SET success = 0, error = ? 
                WHERE id = ?
            """, (f"HTTP {status} (Origin deleted)", doc_id))
            conn.commit()
            print(f"-> CONFIRMED {status}")
        elif status == 521:
            confirmed_down += 1
            print("-> 521 DOWN")
        else:
            print(f"-> FETCH ERROR ({fetch_err[:50]})")
            
        time.sleep(0.1)
        
    print("\n" + "=" * 60)
    print(f"DONE RE-CRAWL SUMMARY:")
    print(f"  Recovered to SUCCESS: {recovered}")
    print(f"  Confirmed HTTP 404/Deleted: {confirmed_404}")
    print(f"  Confirmed Server Down: {confirmed_down}")
    
    # Re-export JSONL files for updated clusters
    for cl in ["39net", "ask39", "cnkang", "china_other"]:
        cur.execute("SELECT row_index, id, url, text, success, error FROM crawl_records WHERE cluster = ? ORDER BY row_index ASC", (cl,))
        rows = cur.fetchall()
        out_file = OUT_DIR / f"data_bosung_{cl}.jsonl"
        with open(out_file, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({
                    "row_index": r[0],
                    "id": r[1],
                    "url": r[2],
                    "text": r[3],
                    "success": r[4],
                    "error": r[5]
                }, ensure_ascii=False) + "\n")
        print(f"Re-exported {len(rows)} records to {out_file.name}")
        
    conn.close()

if __name__ == "__main__":
    run_recrawl()
