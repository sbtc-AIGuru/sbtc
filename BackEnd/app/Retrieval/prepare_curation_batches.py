#!/usr/bin/env python3
"""
prepare_curation_batches.py - Prepare context-rich medical batches from test_20k.jsonl
for LLM deep semantic reading and entity curation.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

WORKSPACE = Path(__file__).resolve().parents[4]
TEST_20K = WORKSPACE / "data_final" / "test_20k.jsonl"
OUT_DIR = WORKSPACE / "artifacts" / "retrieval" / "llm-curated-segmentation-20261016" / "staging"
OUT_DIR.mkdir(parents=True, exist_ok=True)

(OUT_DIR / "vi").mkdir(exist_ok=True)
(OUT_DIR / "zh").mkdir(exist_ok=True)
(OUT_DIR / "en").mkdir(exist_ok=True)

# Load existing terms to help identify already known terms
VI_EXISTING = set()
with open(Path(__file__).resolve().parent / "resources/segmentation_vi.txt") as f:
    for line in f:
        t = line.strip().lower()
        if t:
            VI_EXISTING.add(t)

ZH_EXISTING = set()
with open(Path(__file__).resolve().parent / "resources/segmentation_zh.txt") as f:
    for line in f:
        t = line.strip().lower()
        if t:
            ZH_EXISTING.add(t)

print(f"Loaded existing: VI={len(VI_EXISTING)}, ZH={len(ZH_EXISTING)}")

# Categorize articles by language/domain
vi_articles = []
zh_articles = []
en_articles = []

with open(TEST_20K) as f:
    for line in f:
        row = json.loads(line)
        if not row.get("success"):
            continue
        url = row.get("url", "")
        text = row.get("text", "")
        if not text or len(text.strip()) < 50:
            continue
        
        doc_id = row.get("id")
        
        # Categorize
        if "pubmed.ncbi.nlm.nih.gov" in url:
            en_articles.append({"id": doc_id, "url": url, "text": text})
        elif any(d in url for d in ["vinmec.com", "nhathuoclongchau.com.vn", "medlatec.vn", "bachmai.gov.vn", "suckhoedoisong.vn", "suckhoecongdongonline.vn", "thanhnien.vn", "laodong.vn"]):
            vi_articles.append({"id": doc_id, "url": url, "text": text})
        elif any(d in url for d in ["120ask.com", "zhongyibaodian.net", "cnkang.com", "a-hospital.com", "ask.39.net", "zysjonline.com"]):
            zh_articles.append({"id": doc_id, "url": url, "text": text})

print(f"Filtered articles: VI={len(vi_articles)}, ZH={len(zh_articles)}, EN={len(en_articles)}")

def split_sentences(text: str, lang: str) -> list[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sentences = []
    for line in lines:
        if lang == "zh":
            parts = re.split(r"[。！？；;\n]+", line)
        else:
            parts = re.split(r"(?<=[a-zA-ZÀ-ỹ0-9])\.\s+|\n+", line)
        for p in parts:
            p = p.strip()
            if len(p) >= 15:
                sentences.append(p)
    return sentences

# Save articles into thematic batches of ~50 articles each
def write_batches(articles, lang: str, batch_size: int = 50, max_batches: int = 20):
    for b_idx in range(min(max_batches, (len(articles) + batch_size - 1) // batch_size)):
        batch_slice = articles[b_idx * batch_size : (b_idx + 1) * batch_size]
        batch_file = OUT_DIR / lang / f"batch_{b_idx:03d}.jsonl"
        with open(batch_file, "w", encoding="utf-8") as f:
            for art in batch_slice:
                sents = split_sentences(art["text"], lang)
                f.write(json.dumps({
                    "id": art["id"],
                    "url": art["url"],
                    "sentences": sents[:15]  # Top informative sentences per article
                }, ensure_ascii=False) + "\n")
        print(f"Wrote {lang} batch {b_idx}: {len(batch_slice)} articles -> {batch_file.name}")

write_batches(vi_articles, "vi", batch_size=50, max_batches=15)
write_batches(zh_articles, "zh", batch_size=50, max_batches=15)
write_batches(en_articles, "en", batch_size=50, max_batches=15)

print("Batch preparation complete!")
