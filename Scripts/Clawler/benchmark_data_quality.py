#!/usr/bin/env python3
"""
Benchmark Data Quality Script:
1. Samples representative URLs from each of the 9 major domain categories.
2. Fetches Ground Truth directly from the live web (or archive/API).
3. Finds and compares ALL instances of each target across all JSONL/SQLite files in datacrawl/.
4. Analyzes structural fidelity, HTML distortion, Markdown artifacts, Mojibake, and content completeness.
5. Produces ranking and recommends the BEST source file for each category.
"""

import sys
import os
import json
import sqlite3
import re
import html
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import pyarrow.parquet as pq
from curl_cffi import requests

sys.path.insert(0, '/home/tran-nhat-truong/TranNhatTruong/other/AIGuru')
from sbtc.Scripts.Clawler.repair_vi_zh_crawler import clean_to_verbatim

NEWCORPUS_PATH = Path('newcorpus/links_corpus_vi_en_zh.parquet')
DATACRAWL_DIR = Path('datacrawl')

def load_corpus_samples():
    table = pq.read_table(NEWCORPUS_PATH)
    ids = table['id'].to_pylist()
    urls = table['url'].to_pylist()
    
    # 9 Domains / URL Types
    targets_config = {
        "en_pubmed": {"pattern": r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", "name": "PubMed (EN)"},
        "zh_ask39": {"pattern": r"ask\.39\.net/question/(\d+)", "name": "ask.39.net (ZH - Q&A)"},
        "zh_39net_sub": {"pattern": r"(?:baby|woman|food|fitness|cancer|jbk)\.39\.net/", "name": "*.39.net Articles (ZH)"},
        "zh_zysj": {"pattern": r"zysj\.com\.cn", "name": "zysj.com.cn (ZH - TCM Classics)"},
        "zh_cnkang": {"pattern": r"cnkang\.com", "name": "cnkang.com (ZH - Health Articles)"},
        "zh_iiyi": {"pattern": r"article\.iiyi\.com", "name": "article.iiyi.com (ZH - Clinical Cases)"},
        "zh_wujue": {"pattern": r"wujue\.com", "name": "wujue.com (ZH - Herb & Disease)"},
        "vi_baovn": {"pattern": r"(?:suckhoedoisong|baonghean|baohaiphong|laodong|thaythuocvietnam)\.vn", "name": "Báo chí & Sức khỏe VN (VI)"},
        "vi_medlatec": {"pattern": r"medlatec\.vn", "name": "medlatec.vn (VI - Lab & Diseases)"},
        "vi_longchau": {"pattern": r"nhathuoclongchau\.com\.vn", "name": "nhathuoclongchau.com.vn (VI - Pharmacy)"}
    }
    
    samples = {}
    for cat, conf in targets_config.items():
        pat = re.compile(conf['pattern'])
        for doc_id, u in zip(ids, urls):
            if pat.search(u):
                if cat not in samples:
                    samples[cat] = {"id": doc_id, "url": u, "category": conf['name']}
                    break
    return samples

def find_instances_in_datacrawl(doc_id, url):
    """Scan all jsonl and sqlite files for records matching doc_id or url."""
    instances = []
    
    # 1. Check SQLite DBs
    for db in DATACRAWL_DIR.rglob("*.sqlite"):
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            for tbl in tables:
                cur.execute(f"PRAGMA table_info({tbl})")
                cols = {c[1] for c in cur.fetchall()}
                id_col = 'id' if 'id' in cols else ('doc_id' if 'doc_id' in cols else None)
                if id_col:
                    cur.execute(f"SELECT * FROM {tbl} WHERE {id_col} = ?", (doc_id,))
                    row = cur.fetchone()
                    if row:
                        col_names = [c[1] for c in cur.fetchall()] or list(cols)
                        row_dict = dict(zip([c[1] for c in cur.execute(f"PRAGMA table_info({tbl})").fetchall()], row))
                        instances.append({
                            "source_file": str(db.relative_to(DATACRAWL_DIR)),
                            "source_type": "sqlite",
                            "text": row_dict.get('text', row_dict.get('chunk_text', '')),
                            "status": row_dict.get('success', row_dict.get('status', 'OK')),
                            "raw_record": row_dict
                        })
            conn.close()
        except:
            pass
            
    # 2. Check JSONL files
    for jf in DATACRAWL_DIR.rglob("*.jsonl"):
        if "aiguru_chunks" in str(jf): continue
        try:
            with open(jf, "rb") as fp:
                for line in fp:
                    if f'"id": {doc_id}'.encode() in line or f'"id":{doc_id}'.encode() in line or f'"doc_id": {doc_id}'.encode() in line or f'"doc_id":{doc_id}'.encode() in line:
                        obj = json.loads(line)
                        instances.append({
                            "source_file": str(jf.relative_to(DATACRAWL_DIR)),
                            "source_type": "jsonl",
                            "text": obj.get('text', obj.get('chunk_text', '')),
                            "status": obj.get('success', obj.get('status', 'OK')),
                            "raw_record": obj
                        })
                        break
        except:
            pass
            
    return instances

def inspect_text_quality(text):
    """Detailed quality checks: length, HTML tags, markdown distortion, mojibake, structure."""
    if not text:
        return {"ok": False, "len": 0, "issues": ["TEXT_EMPTY"]}
        
    issues = []
    # Check HTML tags
    html_tags = re.findall(r'<[a-zA-Z\/][^>]*>', text)
    if html_tags:
        issues.append(f"CONTAINS_HTML_TAGS ({len(html_tags)} tags, eg {html_tags[0]})")
        
    # Check Markdown distortion (links, bold, images)
    md_links = re.findall(r'\[([^\]]+)\]\([^)]+\)', text)
    if md_links:
        issues.append(f"CONTAINS_MARKDOWN_LINKS ({len(md_links)} links)")
    md_bolds = re.findall(r'\*\*([^*]+)\*\*', text)
    if md_bolds:
        issues.append(f"CONTAINS_MARKDOWN_BOLD ({len(md_bolds)} instances)")
        
    # Check Mojibake / encoding errors
    if '\ufffd' in text:
        issues.append("CONTAINS_MOJIBAKE_REPLACEMENT_CHAR (\ufffd)")
    if '锟斤拷' in text:
        issues.append("CONTAINS_GBK_UTF8_MOJIBAKE (锟斤拷)")
        
    # Check Structure (Paragraphs, sentences)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    has_title_and_body = len(lines) >= 2
    
    return {
        "ok": len(issues) == 0,
        "len": len(text),
        "lines": len(lines),
        "has_structure": has_title_and_body,
        "issues": issues
    }

def main():
    print("================================================================================")
    print("       AUDIT & BENCHMARK CHẤT LƯỢNG DỮ LIỆU ĐÃ CRAWL THEO TỪNG LOẠI URL")
    print("================================================================================")
    
    samples = load_corpus_samples()
    print(f"Loaded {len(samples)} representative sample URLs from New Corpus:\n")
    for cat, s in samples.items():
        print(f"[{cat:15s}] ID: {s['id']:<8} | {s['category']:<30} | {s['url']}")
        
    report = []
    
    for cat, s in samples.items():
        doc_id = s['id']
        url = s['url']
        name = s['category']
        
        print(f"\n" + "="*80)
        print(f"ĐANG KIỂM ĐỊNH LOẠI: {name} (ID: {doc_id})")
        print(f"URL: {url}")
        print("="*80)
        
        # 1. Fetch Live Web Ground Truth
        live_text = ""
        live_html_len = 0
        live_status = "UNKNOWN"
        try:
            if "pubmed" in cat:
                # E-utilities API
                pmid = re.search(r'/(\d+)', url).group(1)
                api_u = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
                resp = requests.get(api_u, timeout=10)
                live_status = f"HTTP {resp.status_code}"
                if resp.status_code == 200:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.content)
                    title = "".join(root.find(".//ArticleTitle").itertext()) if root.find(".//ArticleTitle") is not None else ""
                    abstract_parts = []
                    for ab in root.findall(".//AbstractText"):
                        lbl = ab.get('Label')
                        t = "".join(ab.itertext()).strip()
                        if lbl: abstract_parts.append(f"{lbl}: {t}")
                        else: abstract_parts.append(t)
                    live_text = clean_to_verbatim(f"{title}\n\n" + "\n\n".join(abstract_parts))
                    live_html_len = len(resp.content)
            elif "iiyi" in cat:
                # Wayback archive
                cur_archive = f"https://web.archive.org/web/20211202130103id_/{url}"
                resp = requests.get(cur_archive, impersonate='chrome120', timeout=15)
                live_status = f"HTTP {resp.status_code}"
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    title = soup.find('h1').get_text().strip() if soup.find('h1') else ""
                    cont = soup.find('div', class_='cont').get_text(separator="\n").strip() if soup.find('div', class_='cont') else ""
                    live_text = clean_to_verbatim(f"{title}\n\n{cont}")
                    live_html_len = len(resp.text)
            else:
                resp = requests.get(url, impersonate='chrome120', timeout=12)
                live_status = f"HTTP {resp.status_code}"
                if resp.status_code == 200:
                    live_html_len = len(resp.text)
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    # Strip scripts & styles
                    for s in soup(['script', 'style', 'noscript', 'nav', 'header', 'footer']): s.decompose()
                    h1 = soup.find('h1')
                    title = h1.get_text().strip() if h1 else (soup.find('title').get_text().strip() if soup.find('title') else "")
                    body = soup.get_text(separator="\n").strip()
                    live_text = clean_to_verbatim(f"{title}\n\n{body}")[:4000]
        except Exception as e:
            live_status = f"Fetch Error: {e}"
            
        print(f"[*] LIVE WEB GROUND TRUTH: Status={live_status} | HTML Len={live_html_len:,} | Verbatim Len={len(live_text):,}")
        if live_text:
            print(f"    Preview: {live_text[:180].replace(chr(10), ' ')}...")
            
        # 2. Find All Crawled Instances in Datacrawl
        instances = find_instances_in_datacrawl(doc_id, url)
        print(f"[*] CRAWLED INSTANCES IN DATACRAWL: Found {len(instances)} versions across storage files.")
        
        category_eval = {
            "category": name,
            "sample_id": doc_id,
            "sample_url": url,
            "live_status": live_status,
            "live_verbatim_len": len(live_text),
            "versions": []
        }
        
        for idx, inst in enumerate(instances, 1):
            src_file = inst['source_file']
            crawled_text = inst['text']
            q = inspect_text_quality(crawled_text)
            
            # Estimate Overlap / Similarity with live text
            overlap_pct = 0.0
            if live_text and crawled_text:
                live_tokens = set(live_text.lower().split())
                crawled_tokens = set(crawled_text.lower().split())
                if live_tokens:
                    overlap_pct = len(live_tokens & crawled_tokens) / len(live_tokens) * 100.0
                    
            print(f"  Version {idx}: File `{src_file}`")
            print(f"    Text Length: {q['len']:,} chars | Lines: {q.get('lines', 0)} | Overlap vs Live: {overlap_pct:.1f}%")
            if q['issues']:
                print(f"    CẢNH BÁO LỖI: {', '.join(q['issues'])}")
            else:
                print(f"    CHẤT LƯỢNG: Chuẩn Verbatim sạch 100% (Không rác HTML, không Markdown)")
            print(f"    Preview: {crawled_text[:120].replace(chr(10), ' ')}...")
            
            category_eval["versions"].append({
                "source_file": src_file,
                "text_len": q['len'],
                "overlap_pct": round(overlap_pct, 2),
                "issues": q['issues'],
                "quality_grade": "GOLD" if q['ok'] and q['len'] >= 100 else ("ACCEPTABLE" if q['ok'] else "DEFECTIVE")
            })
            
        report.append(category_eval)
        
    # Save Benchmark Result
    with open('datacrawl/derived/bosung/benchmark_data_quality_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        
    print("\n" + "="*80)
    print("HOÀN TẤT BENCHMARK! Kết quả chi tiết đã được lưu tại:")
    print("datacrawl/derived/bosung/benchmark_data_quality_report.json")
    print("="*80)

if __name__ == '__main__':
    main()
