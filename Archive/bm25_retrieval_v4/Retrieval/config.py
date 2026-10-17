"""Configuration loader and schema validator for BM25 Retrieval.

Sử dụng thư viện chuẩn tomllib của Python 3.12.
Tuân thủ Mục 16 của SPEC-bm25-medical-multilingual.md.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class FieldBoostConfig:
    """Cấu hình trọng số boost cho từng field trong Lucene search."""

    contents: float = 1.0
    title: float = 1.0
    section: float = 0.2
    surface: float = 0.15
    medical_exact: float = 0.5
    concepts: float = 0.5


@dataclass(frozen=True)
class BM25Params:
    """Tham số k1 và b của BM25."""

    k1: float = 1.2
    b: float = 0.75


@dataclass(frozen=True)
class BudgetConfig:
    """Ngân sách ứng viên và kết quả nộp bài tối ưu F2."""

    candidate_docs_per_variant: int = 200
    candidate_chunks_per_variant: int = 1000
    max_selected_docs: int = 20
    max_selected_chunks: int = 40
    max_chunks_per_doc: int = 4
    overlap_penalty_threshold: float = 0.7
    rrf_k: int = 60
    adaptive_selector: bool = False
    doc_score_ratio: float = 0.5
    chunk_score_ratio: float = 0.5
    min_selected_docs: int = 1
    min_selected_chunks: int = 1


@dataclass(frozen=True)
class QualityPolicyConfig:
    """Cấu hình chính sách kiểm soát chất lượng dữ liệu."""

    block_on_oversized_unresolved: bool = True
    allow_uncertain_format: bool = True
    require_parquet_membership: bool = True


@dataclass(frozen=True)
class QueryBridgeConfig:
    """Cấu hình cho QueryBridge."""

    mode: str = "lexical-control"  # 'lexical-control' hoặc 'multilingual'
    max_clauses: int = 128
    translation_cache_dir: str | None = None
    lexicon_path: str | None = None


@dataclass(frozen=True)
class ResourceConfig:
    """Giới hạn tài nguyên thực thi."""

    jvm_heap: str = "3g"
    batch_records: int = 1000
    batch_bytes: int = 64 * 1024 * 1024  # 64 MiB
    max_search_threads: int = 4
    index_threads: int = 2


@dataclass(frozen=True)
class BM25Config:
    """Cấu hình tổng thể của BM25 Retrieval Engine."""

    corpus_snapshot: Path
    source_scope: Path
    chunk_input: Path
    run_dir: Path
    queries_path: Path | None = None

    bm25_doc: BM25Params = field(default_factory=BM25Params)
    bm25_chunk: BM25Params = field(default_factory=BM25Params)

    boost_doc: FieldBoostConfig = field(
        default_factory=lambda: FieldBoostConfig(
            contents=1.0, title=1.5, section=0.2, surface=0.15, medical_exact=0.5, concepts=0.5
        )
    )
    boost_chunk: FieldBoostConfig = field(
        default_factory=lambda: FieldBoostConfig(
            contents=1.0, title=0.2, section=0.2, surface=0.15, medical_exact=0.5, concepts=0.5
        )
    )

    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    quality: QualityPolicyConfig = field(default_factory=QualityPolicyConfig)
    bridge: QueryBridgeConfig = field(default_factory=QueryBridgeConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)

    @classmethod
    def from_toml(cls, toml_path: str | Path) -> BM25Config:
        """Đọc và xác thực cấu hình từ file TOML."""
        path = Path(toml_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file cấu hình: {path}")

        with open(path, "rb") as f:
            data = tomllib.load(f)

        # Kiểm tra các trường bắt buộc
        for req in ["corpus_snapshot", "source_scope", "chunk_input", "run_dir"]:
            if req not in data:
                raise ValueError(f"Thiếu trường bắt buộc '{req}' trong cấu hình TOML.")

        repo_root = Path(__file__).resolve().parent.parent.parent.parent

        def resolve_p(p_str: str) -> Path:
            p = Path(p_str)
            if not p.is_absolute():
                return (repo_root / p).resolve()
            return p.resolve()

        corpus_snapshot = resolve_p(data["corpus_snapshot"])
        source_scope = resolve_p(data["source_scope"])
        chunk_input = resolve_p(data["chunk_input"])
        run_dir = resolve_p(data["run_dir"])
        queries_path = resolve_p(data["queries_path"]) if "queries_path" in data else None

        # BM25 params
        doc_k1 = data.get("bm25", {}).get("doc_k1", 1.2)
        doc_b = data.get("bm25", {}).get("doc_b", 0.75)
        chunk_k1 = data.get("bm25", {}).get("chunk_k1", 1.2)
        chunk_b = data.get("bm25", {}).get("chunk_b", 0.75)

        # Field boosts
        doc_boosts = data.get("boost_doc", {})
        chunk_boosts = data.get("boost_chunk", {})

        # Budgets
        bg_data = data.get("budgets", {})
        budgets = BudgetConfig(
            candidate_docs_per_variant=bg_data.get("candidate_docs_per_variant", 200),
            candidate_chunks_per_variant=bg_data.get("candidate_chunks_per_variant", 1000),
            max_selected_docs=bg_data.get("max_selected_docs", 20),
            max_selected_chunks=bg_data.get("max_selected_chunks", 40),
            max_chunks_per_doc=bg_data.get("max_chunks_per_doc", 4),
            overlap_penalty_threshold=bg_data.get("overlap_penalty_threshold", 0.7),
            rrf_k=bg_data.get("rrf_k", 60),
            adaptive_selector=bg_data.get("adaptive_selector", False),
            doc_score_ratio=bg_data.get("doc_score_ratio", 0.5),
            chunk_score_ratio=bg_data.get("chunk_score_ratio", 0.5),
            min_selected_docs=bg_data.get("min_selected_docs", 1),
            min_selected_chunks=bg_data.get("min_selected_chunks", 1),
        )

        # Quality
        q_data = data.get("quality_policy", {})
        quality = QualityPolicyConfig(
            block_on_oversized_unresolved=q_data.get("block_on_oversized_unresolved", True),
            allow_uncertain_format=q_data.get("allow_uncertain_format", True),
            require_parquet_membership=q_data.get("require_parquet_membership", True),
        )

        # QueryBridge
        br_data = data.get("query_bridge", {})
        bridge = QueryBridgeConfig(
            mode=br_data.get("mode", "lexical-control"),
            max_clauses=br_data.get("max_clauses", 128),
            translation_cache_dir=br_data.get("translation_cache_dir"),
            lexicon_path=br_data.get("lexicon_path"),
        )

        # Resources
        res_data = data.get("resources", {})
        resources = ResourceConfig(
            jvm_heap=res_data.get("jvm_heap", "3g"),
            batch_records=res_data.get("batch_records", 1000),
            batch_bytes=res_data.get("batch_bytes", 64 * 1024 * 1024),
            max_search_threads=res_data.get("max_search_threads", 4),
            index_threads=res_data.get("index_threads", 2),
        )

        return cls(
            corpus_snapshot=corpus_snapshot,
            source_scope=source_scope,
            chunk_input=chunk_input,
            run_dir=run_dir,
            queries_path=queries_path,
            bm25_doc=BM25Params(k1=doc_k1, b=doc_b),
            bm25_chunk=BM25Params(k1=chunk_k1, b=chunk_b),
            boost_doc=FieldBoostConfig(**doc_boosts) if doc_boosts else FieldBoostConfig(contents=1.0, title=1.5, section=0.2, surface=0.15, medical_exact=0.5, concepts=0.5),
            boost_chunk=FieldBoostConfig(**chunk_boosts) if chunk_boosts else FieldBoostConfig(contents=1.0, title=0.2, section=0.2, surface=0.15, medical_exact=0.5, concepts=0.5),
            budgets=budgets,
            quality=quality,
            bridge=bridge,
            resources=resources,
        )
