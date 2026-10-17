"""Offline batch translation runner for 1,200 competition queries using MultiMed-ST."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from BackEnd.app.Retrieval.query import iter_queries, QueryProjector
from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer
from BackEnd.app.Retrieval.lexicon import Lexicon
from BackEnd.app.Retrieval.translation import (
    LocalM2MTranslator,
    MultiMedCompositeTranslator,
    write_translation_cache,
)


def run_translation(
    queries_path: Path,
    models_dir: Path,
    output_path: Path,
    batch_size: int = 8,
    device: str | None = None,
) -> None:
    en_manifest = models_dir / "manifest_vi_en.json"
    zh_manifest = models_dir / "manifest_vi_zh.json"

    if not en_manifest.exists() or not zh_manifest.exists():
        raise FileNotFoundError(f"Missing manifest files in {models_dir}")

    print(f"Loading MultiMed-ST VI -> EN from {en_manifest}...")
    t0 = time.time()
    en_translator = LocalM2MTranslator(en_manifest, device=device)
    print(f"Loaded EN model in {time.time() - t0:.2f}s on device: {en_translator.device}")

    print(f"Loading MultiMed-ST VI -> ZH from {zh_manifest}...")
    t0 = time.time()
    zh_translator = LocalM2MTranslator(zh_manifest, device=device)
    print(f"Loaded ZH model in {time.time() - t0:.2f}s on device: {zh_translator.device}")

    composite_translator = MultiMedCompositeTranslator(en_translator, zh_translator)

    print(f"\nStarting batch translation from {queries_path} to {output_path}...")
    t_start = time.time()
    count = write_translation_cache(
        iter_queries(queries_path),
        composite_translator,
        output_path,
        batch_size=batch_size,
    )
    duration = time.time() - t_start
    print(f"\nSuccessfully translated {count} queries in {duration:.2f}s ({duration/count*1000:.1f} ms/query)!")
    print(f"Cache size: {output_path.stat().st_size / 1024:.1f} KiB")

    # Verification with QueryProjector
    print("Verifying cache with QueryProjector...")
    analyzer = MedicalAnalyzer(Lexicon())
    projector = QueryProjector(analyzer, output_path)
    print(f"QueryProjector loaded {len(projector.cache)} cached queries successfully!")


def main():
    parser = argparse.ArgumentParser(description="Run MultiMed-ST batch translation.")
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("newcorpus/query.parquet"),
        help="Path to query.parquet file",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("artifacts/models/MultiMed-ST"),
        help="Directory containing manifest_vi_en.json and manifest_vi_zh.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/retrieval/query-translations.jsonl"),
        help="Output path for query-translations.jsonl",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Translation batch size",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Device to use ('cpu' or 'cuda')",
    )
    args = parser.parse_args()
    run_translation(args.queries, args.models_dir, args.output, args.batch_size, args.device)


if __name__ == "__main__":
    main()
