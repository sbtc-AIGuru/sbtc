import sys
from pathlib import Path
sys.path.insert(0, '/home/tran-nhat-truong/TranNhatTruong/other/AIGuru')
import sqlite3
import json
import re
from urllib.parse import urlparse
import pyarrow.parquet as pq

# 1. Lấy 104 URLs EN bị lỗi trong sqlite
conn = sqlite3.connect('datacrawl/derived/bosung/pubmed_crawl_checkpoint.sqlite')
c = conn.cursor()
c.execute('SELECT id, row_index, url, error FROM crawl_records WHERE success = 0')
en_failed = c.fetchall()
conn.close()

print(f'=== PHÂN TÍCH 104 URLs TIẾNG ANH (PubMed) ===')
print(f'Tổng số EN failed: {len(en_failed)}')
pmids = []
for fid, r_idx, u, err in en_failed:
    m = re.search(r'/(\d+)/?', u)
    if m:
        pmids.append((fid, r_idx, u, m.group(1), err))

# 2. Đọc corpus & scan datacrawl
NEWCORPUS_PATH = 'newcorpus/links_corpus_vi_en_zh.parquet'
table = pq.read_table(NEWCORPUS_PATH)
corpus_ids = table['id'].to_pylist()
corpus_urls = table['url'].to_pylist()
corpus_dict = dict(zip(corpus_ids, corpus_urls))

from sbtc.Scripts.Clawler.audit_datacrawl_vs_newcorpus import load_target_corpus, scan_all_datacrawl
target_ids, target_urls, target_id_to_url, stats_lang, domain_to_ids = load_target_corpus()
crawled_succ_ids, crawled_succ_urls, _ = scan_all_datacrawl(target_ids, target_urls)

missing_zh_ids = stats_lang['zh'] - crawled_succ_ids
print(f'\n=== PHÂN TÍCH {len(missing_zh_ids)} URLs TIẾNG TRUNG (ZH) CÒN THIẾU ===')
zh_domain_items = {}
for mid in missing_zh_ids:
    u = corpus_dict[mid]
    dom = urlparse(u).netloc.lower()
    if dom not in zh_domain_items:
        zh_domain_items[dom] = []
    zh_domain_items[dom].append((mid, u))

for dom, items in sorted(zh_domain_items.items(), key=lambda x: len(x[1]), reverse=True):
    print(f'Domain: {dom:30s} | Thiếu: {len(items):4d} URLs')
    for m in items[:2]:
        print(f'    Sample: ID={m[0]} -> {m[1]}')

with open('datacrawl/derived/bosung/missing_zh_detailed.json', 'w', encoding='utf-8') as f:
    json.dump({dom: [{'id': m[0], 'url': m[1]} for m in items] for dom, items in zh_domain_items.items()}, f, ensure_ascii=False, indent=2)

with open('datacrawl/derived/bosung/missing_en_detailed.json', 'w', encoding='utf-8') as f:
    json.dump([{'id': p[0], 'row_index': p[1], 'url': p[2], 'pmid': p[3], 'error': p[4]} for p in pmids], f, ensure_ascii=False, indent=2)

print('\nĐã lưu danh sách chi tiết vào missing_zh_detailed.json và missing_en_detailed.json!')
