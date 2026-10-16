"""Consolidate 6 subagent batch lexicons into the comprehensive Medical Terminology Guard for all 1,200 BTC queries.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BATCH_DIR = REPO_ROOT / "artifacts" / "guard_batches"
OUTPUT_FILE = REPO_ROOT / "sbtc" / "Resources" / "medical_terminology_guard_1200.json"
QUERY_FILE = REPO_ROOT / "sbtc" / "data" / "query.parquet"

def clean_term(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())

def main():
    import pandas as pd
    
    all_terms = {}
    total_raw_entries = 0
    batch_stats = {}

    files_to_merge = [BATCH_DIR / f"batch_{b_id}_lexicon.json" for b_id in range(1, 7)]
    supp_file = BATCH_DIR / "batch_supplement_lexicon.json"
    if supp_file.exists():
        files_to_merge.append(supp_file)

    for f_path in files_to_merge:
        if not f_path.exists():
            print(f"[WARNING] File {f_path.name} not found yet!")
            continue
        with open(f_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        batch_stats[f_path.stem] = len(data)
        total_raw_entries += len(data)
        for item in data:
            vi = clean_term(item.get("vi", ""))
            en = item.get("en", "").strip()
            zh = item.get("zh", "").strip()
            cat = item.get("category", "general").strip()
            qids = item.get("source_qids", [])
            
            if not vi or not en or not zh:
                continue
                
            if vi not in all_terms:
                all_terms[vi] = {
                    "vi": vi,
                    "en": en,
                    "zh": zh,
                    "category": cat,
                    "source_qids": set(qids)
                }
            else:
                all_terms[vi]["source_qids"].update(qids)
                if len(en) > len(all_terms[vi]["en"]):
                    all_terms[vi]["en"] = en
                if len(zh) > len(all_terms[vi]["zh"]):
                    all_terms[vi]["zh"] = zh

    # Also load baseline medical terminology lexicon from validation
    try:
        from validation.translate_validation_queries import MEDICAL_TERMINOLOGY_LEXICON
        for vi, en, zh in MEDICAL_TERMINOLOGY_LEXICON:
            vi = clean_term(vi)
            if vi not in all_terms:
                all_terms[vi] = {
                    "vi": vi,
                    "en": en,
                    "zh": zh,
                    "category": "dental" if "răng" in vi or "nha" in vi or "lợi" in vi or "tủy" in vi or "ngà" in vi else "disease",
                    "source_qids": set()
                }
    except Exception as e:
        print(f"[INFO] Notice regarding baseline lexicon: {e}")

    print(f"Total raw entries across batches: {total_raw_entries}")
    print(f"Total unique clinical terms after deduplication: {len(all_terms)}")
    print("Batch counts:", batch_stats)

    # Sort by length of VI term descending (Longest-Match-First for regex / substring search)
    sorted_lexicon = sorted(all_terms.values(), key=lambda x: (-len(x["vi"]), x["vi"]))
    for item in sorted_lexicon:
        item["source_qids"] = sorted(list(item["source_qids"]))

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_lexicon, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(sorted_lexicon)} standardized guard terms to {OUTPUT_FILE}!")

    # Verify coverage across all 1200 queries
    df = pd.read_parquet(QUERY_FILE)
    matched_queries = 0
    match_distribution = []

    for _, row in df.iterrows():
        qid = int(row["id"])
        q_text = str(row["query"]).lower()
        matches = [t["vi"] for t in sorted_lexicon if t["vi"] in q_text]
        if matches:
            matched_queries += 1
            match_distribution.append(len(matches))

    coverage_pct = (matched_queries / len(df)) * 100
    avg_matches = sum(match_distribution) / len(match_distribution) if match_distribution else 0.0
    print("\n" + "=" * 60)
    print("COVERAGE VERIFICATION REPORT ON 1,200 BTC QUERIES:")
    print("=" * 60)
    print(f"Total queries: {len(df)}")
    print(f"Queries with at least 1 Medical Guard term: {matched_queries} / {len(df)} ({coverage_pct:.2f}%)")
    print(f"Average guard terms per covered query: {avg_matches:.2f}")
    print("=" * 60)

if __name__ == "__main__":
    main()
