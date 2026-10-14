"""CorpusReader: Streaming Shard Files & Bounded Memory Reader.

Theo SPEC-bm25-medical-multilingual.md Mục 8 & Mục 12.1.
Đọc file JSONL theo từng dòng nhị phân, ghi nhận byte-offset chính xác cho mỗi record.
Không bao giờ nạp toàn bộ shard hay corpus vào RAM.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, List, Tuple

from sbtc.Scripts.Retrieval.identity import IdentityRegistry
from sbtc.Scripts.Retrieval.quality import QualityPolicy


class CorpusReader:
    """Đọc dữ liệu streaming từ danh sách shard JSONL."""

    def __init__(
        self,
        chunk_dir: Path,
        identity_registry: IdentityRegistry,
        quality_policy: QualityPolicy,
        batch_records: int = 1000,
        batch_bytes: int = 64 * 1024 * 1024,  # 64 MiB
    ) -> None:
        self.chunk_dir = Path(chunk_dir).resolve()
        self.identity_registry = identity_registry
        self.quality_policy = quality_policy
        self.batch_records = batch_records
        self.batch_bytes = batch_bytes

    def get_shard_files(self) -> List[Path]:
        """Lấy danh sách các file shard JSONL được sắp xếp."""
        if not self.chunk_dir.exists():
            raise FileNotFoundError(f"Thư mục chunks không tồn tại: {self.chunk_dir}")

        if self.chunk_dir.is_file():
            return [self.chunk_dir]

        # Quét các file jsonl trong thư mục
        shards = sorted(self.chunk_dir.glob("*.jsonl"))
        if not shards:
            # Thử quét đệ quy
            shards = sorted(self.chunk_dir.rglob("*.jsonl"))
        return shards

    @staticmethod
    def compute_file_stats(file_path: Path) -> Tuple[int, int, str]:
        """Tính kích thước (bytes), mtime (ns) và SHA256 của file shard."""
        stat = file_path.stat()
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                hasher.update(chunk)
        return stat.st_size, stat.st_mtime_ns, hasher.hexdigest()

    def stream_records(self) -> Iterator[Tuple[Path, int, int, dict]]:
        """Stream từng record JSONL cùng tọa độ byte offset.

        Yields:
            (shard_path, byte_offset, byte_length, record_json)
        """
        for shard_path in self.get_shard_files():
            with open(shard_path, "rb") as f:
                while True:
                    byte_offset = f.tell()
                    line = f.readline()
                    if not line:
                        break
                    byte_length = len(line)
                    line_str = line.strip()
                    if not line_str:
                        continue

                    try:
                        record = json.loads(line_str.decode("utf-8"))
                    except Exception as e:
                        print(f"Lỗi parse JSON tại {shard_path} offset {byte_offset}: {e}")
                        continue

                    line_sha256 = hashlib.sha256(line).hexdigest()
                    yield (shard_path, byte_offset, byte_length, record, line_sha256)
