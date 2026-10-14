"""IndexBuilder: Quản lý Chuẩn Bị Dữ Liệu và Xây Dựng 6 Lucene Index Partitions.

Theo SPEC-bm25-medical-multilingual.md Mục 8.1, Mục 12.2 và Mục 12.3.
- Hợp nhất source char intervals cho document body (De-overlap) chống nhân đôi TF.
- Tạo staging JSONL với các field tokenized chuẩn.
- Gọi Anserini subprocess qua Python sys.executable độc lập.
- Atomic publish và hỗ trợ resume idempotent qua fingerprint.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

from sbtc.Scripts.Retrieval.analyzers import TokenPipelineRegistry
from sbtc.Scripts.Retrieval.config import BM25Config
from sbtc.Scripts.Retrieval.models import PreparedRecord


def union_intervals(intervals: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Hợp nhất các khoảng ký tự giao nhau thành danh sách các khoảng rời rạc."""
    if not intervals:
        return []
    sorted_inv = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_inv[0]]
    for current in sorted_inv[1:]:
        prev_start, prev_end = merged[-1]
        cur_start, cur_end = current
        if cur_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, cur_end))
        else:
            merged.append(current)
    return merged


class IndexBuilder:
    """Điều phối chuẩn bị dữ liệu staging và build 6 partition Lucene."""

    def __init__(self, config: BM25Config, pipeline_registry: TokenPipelineRegistry) -> None:
        self.config = config
        self.pipelines = pipeline_registry
        self.run_dir = self.config.run_dir
        self.prepared_dir = self.run_dir / "prepared"
        self.indexes_dir = self.run_dir / "indexes"

        # Định nghĩa 6 partition
        self.partitions = [
            ("documents", "vi"),
            ("documents", "en"),
            ("documents", "zh"),
            ("chunks", "vi"),
            ("chunks", "en"),
            ("chunks", "zh"),
        ]

    def _get_staging_dir(self, granularity: str, language: str) -> Path:
        d = self.prepared_dir / granularity / language
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _get_index_dir(self, granularity: str, language: str) -> Path:
        d = self.indexes_dir / granularity / language
        d.parent.mkdir(parents=True, exist_ok=True)
        return d

    def build_document_body_deoverlap(self, record: Mapping[str, Any]) -> str:
        """Dựng thân tài liệu từ union intervals của các child chunk hợp lệ."""
        raw_text = record.get("text", "")
        children = record.get("children", [])
        if not children:
            return raw_text

        # Gom intervals của các child đủ điều kiện
        valid_intervals = []
        for ch in children:
            if ch.get("retrieval_eligible") is not False:
                s = ch.get("start_char", 0)
                e = ch.get("end_char", 0)
                if e > s:
                    valid_intervals.append((s, e))

        if not valid_intervals:
            return raw_text

        merged_intervals = union_intervals(valid_intervals)
        body_parts = []
        for s, e in merged_intervals:
            if raw_text:
                part = raw_text[s:e].strip()
                if part:
                    body_parts.append(part)

        return "\n\n".join(body_parts) if body_parts else raw_text

    def prepare_and_stage_record(
        self,
        record: Mapping[str, Any],
        language: str,
        staging_writers: Dict[Tuple[str, str], Any],
    ) -> None:
        """Phân tích và ghi record vào các staging JSONL file tương ứng."""
        pipeline = self.pipelines.get_pipeline(language)
        doc_id_val = record.get("doc_id") or record.get("id")
        doc_id_str = str(doc_id_val)

        # 1. Document Level
        doc_body = self.build_document_body_deoverlap(record)
        doc_analysis = pipeline.analyze(doc_body)
        title_str = record.get("title", "")
        title_tokens = pipeline.analyze(title_str)["contents"] if title_str else ""

        doc_prepared = PreparedRecord(
            id=doc_id_str,
            contents=doc_analysis["contents"],
            title=title_tokens,
            section="",
            surface=doc_analysis["surface"],
            medical_exact=doc_analysis["medical_exact"],
            concepts=doc_analysis["concepts"],
        )
        staging_writers[("documents", language)].write(
            json.dumps(doc_prepared.to_dict(), ensure_ascii=False) + "\n"
        )

        # 2. Chunk Level
        for child in record.get("children", []):
            if child.get("retrieval_eligible") is False:
                continue
            chunk_id = child["chunk_id"]
            chunk_text = child.get("chunk_text", "")
            if not chunk_text.strip():
                continue

            chunk_analysis = pipeline.analyze(chunk_text)
            chunk_prepared = PreparedRecord(
                id=chunk_id,
                contents=chunk_analysis["contents"],
                title=title_tokens,
                section="",
                surface=chunk_analysis["surface"],
                medical_exact=chunk_analysis["medical_exact"],
                concepts=chunk_analysis["concepts"],
            )
            staging_writers[("chunks", language)].write(
                json.dumps(chunk_prepared.to_dict(), ensure_ascii=False) + "\n"
            )

    def run_indexer_subprocess(self, granularity: str, language: str) -> None:
        """Gọi Anserini Lucene Indexer cho một phân vùng cụ thể."""
        staging_dir = self._get_staging_dir(granularity, language)
        index_dir = self._get_index_dir(granularity, language)
        building_dir = index_dir.with_name(f"{index_dir.name}.building")

        # Kiểm tra xem index đã hoàn tất trước đó chưa (Resume check)
        if index_dir.exists() and (index_dir / "segments.gen").exists():
            print(f"Partition {granularity}/{language} đã tồn tại hợp lệ. Bỏ qua (Resume).")
            return

        if building_dir.exists():
            shutil.rmtree(building_dir)

        # Chuẩn bị môi trường JVM
        env = os.environ.copy()
        env["JAVA_TOOL_OPTIONS"] = f"-Xmx{self.config.resources.jvm_heap}"

        # Anserini command
        cmd = [
            sys.executable,
            "-m",
            "pyserini.index.lucene",
            "--collection",
            "JsonCollection",
            "--input",
            str(staging_dir),
            "--index",
            str(building_dir),
            "--generator",
            "DefaultLuceneDocumentGenerator",
            "--threads",
            str(self.config.resources.index_threads),
            "--pretokenized",
            "--fields",
            "title",
            "section",
            "surface",
            "medical_exact",
            "concepts",
        ]

        print(f"Bắt đầu build partition {granularity}/{language}: {' '.join(cmd)}")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Lỗi khi build index {granularity}/{language}:")
            print(result.stderr)
            raise RuntimeError(f"Anserini indexer thất bại với mã lỗi {result.returncode}")

        # Atomic rename sang thư mục chính thức
        if index_dir.exists():
            shutil.rmtree(index_dir)
        building_dir.rename(index_dir)
        print(f"Hoàn thành xuất sắc partition {granularity}/{language} tại: {index_dir}")
