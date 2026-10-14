"""Identity Registry and Parquet Membership Verification.

Theo SPEC-bm25-medical-multilingual.md Mục 3 & Mục 8.1.
Bảo toàn doc_id nguyên bản từ links_corpus_vi_en_zh.parquet.
Tuyệt đối không dùng row_index hay chỉ số mảng làm ID.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Set


class IdentityRegistry:
    """Quản lý danh sách doc_id hợp lệ từ snapshot Parquet và kiểm tra tính toàn vẹn."""

    def __init__(self, valid_ids: Set[int], parquet_sha256: str, min_id: int, max_id: int) -> None:
        self._valid_ids = valid_ids
        self._parquet_sha256 = parquet_sha256
        self._min_id = min_id
        self._max_id = max_id

    @property
    def valid_ids(self) -> Set[int]:
        return self._valid_ids

    @property
    def parquet_sha256(self) -> str:
        return self._parquet_sha256

    @property
    def doc_count(self) -> int:
        return len(self._valid_ids)

    @property
    def min_id(self) -> int:
        return self._min_id

    @property
    def max_id(self) -> int:
        return self._max_id

    def is_valid_doc_id(self, doc_id: Any) -> bool:
        """Kiểm tra doc_id có hợp lệ: phải là int (không phải bool, float) và thuộc Parquet."""
        if isinstance(doc_id, bool):
            return False
        if not isinstance(doc_id, int):
            try:
                # Nếu là string số nguyên, thử convert
                if isinstance(doc_id, str) and doc_id.isdigit():
                    doc_id = int(doc_id)
                else:
                    return False
            except Exception:
                return False

        return doc_id in self._valid_ids

    @classmethod
    def from_parquet(cls, parquet_path: str | Path) -> IdentityRegistry:
        """Đọc và tạo registry trực tiếp từ links_corpus_vi_en_zh.parquet."""
        path = Path(parquet_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file corpus Parquet: {path}")

        # Tính SHA256 của file Parquet
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                hasher.update(chunk)
        parquet_sha256 = hasher.hexdigest()

        # Đọc cột 'id' dùng PyArrow
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=["id"])
        id_array = table.column("id").to_pylist()

        valid_ids: Set[int] = set()
        min_id = float("inf")
        max_id = float("-inf")

        for val in id_array:
            if isinstance(val, int) and not isinstance(val, bool):
                valid_ids.add(val)
                if val < min_id:
                    min_id = val
                if val > max_id:
                    max_id = val

        return cls(
            valid_ids=valid_ids,
            parquet_sha256=parquet_sha256,
            min_id=int(min_id) if valid_ids else 0,
            max_id=int(max_id) if valid_ids else 0,
        )
