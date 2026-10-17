"""Sample 10 random queries from query.parquet, translate with MultiMed-ST, measure latency, and format for clinical review."""
from __future__ import annotations

import argparse
import json
import random
import re
import resource
import time
from pathlib import Path

import pyarrow.parquet as pq

from BackEnd.app.Retrieval.translation import (
    LocalM2MTranslator,
    MultiMedCompositeTranslator,
)


def get_peak_ram_mb() -> float:
    # ru_maxrss is in KiB on Linux
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def check_numbers_preserved(source: str, translation: str) -> bool:
    source_nums = set(re.findall(r"\d+(?:[.,]\d+)?", source))
    trans_nums = set(re.findall(r"\d+(?:[.,]\d+)?", translation))
    return source_nums <= trans_nums


def evaluate_samples(
    parquet_path: Path,
    models_dir: Path,
    output_json: Path,
    sample_size: int = 10,
    seed: int = 42,
) -> None:
    print(f"Reading queries from {parquet_path}...")
    table = pq.read_table(parquet_path)
    all_rows = [{"id": int(r["id"]), "query": str(r["query"])} for r in table.to_pylist()]
    print(f"Loaded {len(all_rows)} total queries.")

    random.seed(seed)
    sampled = random.sample(all_rows, sample_size)

    en_manifest = models_dir / "manifest_vi_en.json"
    zh_manifest = models_dir / "manifest_vi_zh.json"

    print("Loading MultiMed-ST models...")
    t0 = time.time()
    en_tr = LocalM2MTranslator(en_manifest)
    zh_tr = LocalM2MTranslator(zh_manifest)
    comp = MultiMedCompositeTranslator(en_tr, zh_tr)
    print(f"Models loaded in {time.time() - t0:.2f}s. Initial RAM: {get_peak_ram_mb():.1f} MB.")

    # Warmup
    print("Warming up models...")
    _ = comp.translate(["Triệu chứng sốt xuất huyết là gì?"])

    print(f"\n=======================================================")
    print(f"Translating {sample_size} Sampled Queries with Timing Measurement...")
    print(f"=======================================================\n")

    results = []
    total_latency_start = time.time()

    for idx, item in enumerate(sampled, 1):
        q_id = item["id"]
        source = item["query"]

        t_start = time.time()
        # Measure EN
        t_en_0 = time.time()
        en_text = en_tr.translate([source])[0]
        en_ms = (time.time() - t_en_0) * 1000

        # Measure ZH
        t_zh_0 = time.time()
        zh_text = zh_tr.translate([source])[0]
        zh_ms = (time.time() - t_zh_0) * 1000

        item_total_ms = (time.time() - t_start) * 1000

        num_ok_en = check_numbers_preserved(source, en_text)
        num_ok_zh = check_numbers_preserved(source, zh_text)

        entry = {
            "index": idx,
            "id": q_id,
            "source_query": source,
            "en_translation": en_text,
            "zh_translation": zh_text,
            "en_latency_ms": round(en_ms, 2),
            "zh_latency_ms": round(zh_ms, 2),
            "total_latency_ms": round(item_total_ms, 2),
            "numbers_preserved_en": num_ok_en,
            "numbers_preserved_zh": num_ok_zh,
        }
        results.append(entry)
        print(f"[{idx}/{sample_size}] ID {q_id} ({item_total_ms:.1f}ms): {source[:60]}...")
        print(f"    EN ({en_ms:.1f}ms): {en_text}")
        print(f"    ZH ({zh_ms:.1f}ms): {zh_text}")
        print()

    total_duration = time.time() - total_latency_start
    peak_ram = get_peak_ram_mb()

    latencies = [r["total_latency_ms"] for r in results]
    avg_latency = sum(latencies) / len(latencies)

    summary = {
        "sample_size": sample_size,
        "seed": seed,
        "total_duration_sec": round(total_duration, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
        "throughput_queries_per_sec": round(sample_size / total_duration, 2),
        "peak_ram_mb": round(peak_ram, 1),
        "results": results,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n=======================================================")
    print(f"Benchmarking Complete!")
    print(f"  Total time: {total_duration:.2f}s for {sample_size} queries")
    print(f"  Avg Latency per query (EN + ZH): {avg_latency:.1f} ms")
    print(f"  Throughput: {sample_size / total_duration:.2f} queries/sec")
    print(f"  Peak RAM: {peak_ram:.1f} MB")
    print(f"  Results saved to: {output_json}")
    print(f"=======================================================")


def main():
    parser = argparse.ArgumentParser(description="Evaluate 10 random samples with MultiMed-ST.")
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("newcorpus/query.parquet"),
        help="Path to query.parquet",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("artifacts/models/MultiMed-ST"),
        help="Path to models directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/retrieval/eval_10_samples.json"),
        help="Output JSON file path",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Number of samples to evaluate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed",
    )
    args = parser.parse_args()
    evaluate_samples(args.queries, args.models_dir, args.output, args.sample_size, args.seed)


if __name__ == "__main__":
    main()
