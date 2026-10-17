from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import time
import tomllib
from pathlib import Path

from .utils import atomic_json, sha_file


def main(argv=None):
    parser = argparse.ArgumentParser(description="New medical multi-granularity BM25 candidate retrieval")
    commands = parser.add_subparsers(dest="command", required=True)
    names = ("prepare", "build", "index", "search", "export", "analyze", "preflight", "capacity", "translate")
    for name in names:
        p = commands.add_parser(name)
        for opt in ("config", "run-dir", "lexicon", "input-dir", "corpus", "scope", "queries", "output", "cache", "candidates", "zip", "text", "language", "model-manifest", "device"):
            p.add_argument("--"+opt)
        for opt in ("limit", "threads", "per-language-docs", "per-language-chunks", "max-docs", "max-chunks", "docs", "chunks", "expected-documents", "expected-chunks", "batch-size", "staging-target-bytes", "staging-max-bytes", "control-reserve-bytes", "writer-ram-buffer-mib", "disk-reserve-bytes"):
            p.add_argument("--"+opt, type=int)
        p.add_argument("--k1", type=float)
        p.add_argument("--b", type=float)
    args = vars(parser.parse_args(argv))
    config = {}
    if args.get("config"):
        with Path(args["config"]).open("rb") as f:
            config = tomllib.load(f)
    defaults = {"run_dir": "artifacts/retrieval/recall-first-test20k-release", "input_dir": "data_final/chunks_format_v3_r3_reserve_test20k", "corpus": "newcorpus/links_corpus_vi_en_zh.parquet", "scope": "data_final/test_20k.jsonl", "threads": 2, "per_language_docs": 300, "per_language_chunks": 1000, "max_docs": 1000, "max_chunks": 3000, "k1": 0.8, "b": 0.4, "docs": 20, "chunks": 40, "language": "vi", "staging_target_bytes": 250_000_000, "staging_max_bytes": 300_000_000, "control_reserve_bytes": 1_000_000, "writer_ram_buffer_mib": 16, "disk_reserve_bytes": 2_000_000_000}
    cfg = {**defaults, **config, **{k:v for k,v in args.items() if v is not None}}
    root = Path(cfg["run_dir"]).resolve()
    if cfg["command"] == "translate":
        from .translation import LocalNllbTranslator, write_translation_cache
        from .query import iter_queries
        if not all(cfg.get(k) for k in ("model_manifest", "queries", "output")):
            parser.error("translate requires --model-manifest --queries --output")
        translator = LocalNllbTranslator(Path(cfg["model_manifest"]), device=cfg.get("device", "cpu"))
        count = write_translation_cache(iter_queries(Path(cfg["queries"])), translator, Path(cfg["output"]), batch_size=cfg.get("batch_size", 8))
        print(json.dumps({"translated_unique_queries": count}))
        return
    if cfg["command"] == "capacity":
        from .capacity import estimate
        if not all(cfg.get(k) for k in ("expected_documents", "expected_chunks")):
            parser.error("capacity requires --expected-documents --expected-chunks")
        result = estimate(root, expected_documents=cfg["expected_documents"], expected_chunks=cfg["expected_chunks"])
        atomic_json(root/"capacity.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if cfg["command"] == "preflight":
        from .runtime import configure_java
        import shutil
        import subprocess
        configure_java()
        modules = subprocess.run([str(Path(os.environ["JAVA_HOME"])/"bin/java"), "--list-modules"], check=True, capture_output=True, text=True).stdout
        if "jdk.incubator.vector" not in modules:
            raise RuntimeError("Full JDK required: jdk.incubator.vector missing")
        print(json.dumps({"python": sys.version, "java_home": os.environ["JAVA_HOME"], "packages": {n: importlib.metadata.version(n) for n in ("pyserini", "jieba", "underthesea", "pyarrow")}, "disk_free": shutil.disk_usage(".").free}, ensure_ascii=False, indent=2))
        return
    if cfg["command"] == "build":
        from .backend import build_indexes
        build_indexes(root, threads=cfg["threads"])
        return
    if cfg["command"] == "index":
        from .lexicon import DEFAULT_LEXICON, Lexicon
        from .analyzers import MedicalAnalyzer
        from .rolling import RollingIndexer
        analyzer = MedicalAnalyzer(Lexicon(Path(cfg.get("lexicon", DEFAULT_LEXICON))))
        source = Path(cfg["input_dir"]).resolve()
        if root == source or source in root.parents:
            raise RuntimeError("Do not write artifacts inside source chunk directory")
        RollingIndexer(
            analyzer,
            staging_target_bytes=cfg["staging_target_bytes"],
            staging_max_bytes=cfg["staging_max_bytes"],
            control_reserve_bytes=cfg["control_reserve_bytes"],
            writer_ram_buffer_mib=cfg["writer_ram_buffer_mib"],
            disk_reserve_bytes=cfg["disk_reserve_bytes"],
            limit=cfg.get("limit"),
        ).run(source, root, Path(cfg["corpus"]), scope=Path(cfg["scope"]) if cfg.get("scope") else None)
        return
    if cfg["command"] == "export":
        from .store import TextStore
        from .query import iter_queries
        from .export import export_submission
        if not all(cfg.get(k) for k in ("queries", "candidates", "output")):
            parser.error("export requires --queries --candidates --output")
        ids = {q["id"] for q in iter_queries(Path(cfg["queries"]))}
        with TextStore(root/"metadata.sqlite") as store:
            export_submission(Path(cfg["candidates"]), Path(cfg["output"]), store, ids, docs=cfg["docs"], chunks=cfg["chunks"], zip_path=Path(cfg["zip"]) if cfg.get("zip") else None)
        return
    from .lexicon import DEFAULT_LEXICON, Lexicon
    from .analyzers import MedicalAnalyzer
    analyzer = MedicalAnalyzer(Lexicon(Path(cfg.get("lexicon", DEFAULT_LEXICON))))
    if cfg["command"] == "analyze":
        if not cfg.get("text"):
            parser.error("analyze requires --text")
        print(json.dumps({"index": analyzer.analyze(cfg["text"], cfg["language"], index_mode=True).fields, "query": analyzer.analyze(cfg["text"], cfg["language"], index_mode=False).fields}, ensure_ascii=False, indent=2))
    elif cfg["command"] == "prepare":
        from .corpus import CorpusPreparer
        if root.exists() and any(root.iterdir()) and not (root/"manifest.json").exists():
            raise RuntimeError("Refusing a nonempty directory without this component's manifest")
        source = Path(cfg["input_dir"]).resolve()
        if root == source or source in root.parents:
            raise RuntimeError("Do not write artifacts inside source chunk directory")
        CorpusPreparer(analyzer).prepare(source, root, Path(cfg["corpus"]), limit=cfg.get("limit"), scope=Path(cfg["scope"]) if cfg.get("scope") else None)
    else:
        from .backend import LuceneBackend
        from .engine import CandidateEngine
        from .corpus import fingerprint
        from .query import QueryProjector, iter_queries
        from .store import TextStore
        if not cfg.get("queries") or not cfg.get("output"):
            parser.error("search requires --queries and --output")
        manifest = json.loads((root/"manifest.json").read_text())
        if manifest.get("analyzer_profile") != "medical-no-folded-v1" or fingerprint(analyzer.lexicon) != manifest["spec"].get("analysis_fingerprint", manifest["spec"].get("fingerprint")):
            raise RuntimeError("Query analyzer/lexicon no longer matches index snapshot")
        output = Path(cfg["output"])
        if output.exists():
            raise RuntimeError("Output exists: choose a new output path")
        output.parent.mkdir(parents=True, exist_ok=True)
        projector = QueryProjector(analyzer, Path(cfg["cache"]) if cfg.get("cache") else None)
        store = TextStore(root/"metadata.sqlite")
        store.validate_sources()
        backend = LuceneBackend(root, k1=cfg["k1"], b=cfg["b"])
        engine = CandidateEngine(backend, projector, store, per_language_docs=cfg["per_language_docs"], per_language_chunks=cfg["per_language_chunks"], max_docs=cfg["max_docs"], max_chunks=cfg["max_chunks"], threads=cfg["threads"], k1=cfg["k1"], b=cfg["b"])
        count, duration, warnings = 0, 0.0, 0
        try:
            with output.with_suffix(output.suffix+".partial").open("w", encoding="utf-8") as f:
                for result in engine.search_batch(iter_queries(Path(cfg["queries"]))):
                    count += 1
                    duration += result["seconds"]
                    warnings += bool(result["warnings"])
                    f.write(json.dumps(result, ensure_ascii=False)+"\n")
                    if count % 20 == 0:
                        print(json.dumps({"queries": count, "seconds": duration}), flush=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(output.with_suffix(output.suffix+".partial"), output)
            atomic_json(output.with_suffix(output.suffix+".report.json"), {"queries": count, "search_seconds": duration, "queries_per_second": count/duration if duration else 0, "queries_with_warnings": warnings, "relevance_metrics": None, "snapshot_spec_hash": manifest["spec_hash"], "query_file_sha256": sha_file(Path(cfg["queries"])), "translation_cache_sha256": sha_file(Path(cfg["cache"])) if cfg.get("cache") else None, "config": cfg, "code_sha256": {p.name: sha_file(p) for p in Path(__file__).parent.glob("*.py")}, "note": "Candidate-generation run; no qrels used or relevance accuracy inferred."})
        finally:
            engine.close()


if __name__ == "__main__":
    main()
