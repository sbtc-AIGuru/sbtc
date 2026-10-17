"""SourcePointerTextStore: SQLite Con trỏ Byte-Offset & Hydrate Verbatim 100%.

Theo SPEC-bm25-medical-multilingual.md Mục 8.2.
Không nhân đôi nội dung văn bản (tiết kiệm 20-25 GB đĩa).
Lưu trữ tọa độ byte-offset trong SQLite và đọc trực tiếp từ JSONL nguồn qua binary seek.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

from sbtc.Scripts.Retrieval.models import OriginalChunk, ShardInfo


class LRURecordCache:
    """Cache đơn giản lưu các record JSON đã decode theo byte budget."""

    def __init__(self, max_bytes: int = 128 * 1024 * 1024) -> None:  # 128 MiB
        self.max_bytes = max_bytes
        self.current_bytes = 0
        self._cache: OrderedDict[Tuple[int, int], dict] = OrderedDict()

    def get(self, shard_id: int, byte_offset: int) -> dict | None:
        key = (shard_id, byte_offset)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, shard_id: int, byte_offset: int, record: dict, record_bytes_len: int) -> None:
        key = (shard_id, byte_offset)
        if key in self._cache:
            self._cache.move_to_end(key)
            return

        while self.current_bytes + record_bytes_len > self.max_bytes and self._cache:
            _, evicted = self._cache.popitem(last=False)
            # Ước lượng giải phóng
            self.current_bytes = max(0, self.current_bytes - record_bytes_len)

        self._cache[key] = record
        self.current_bytes += record_bytes_len


class SourcePointerTextStore:
    """Kho lưu trữ con trỏ và phục hồi văn bản nguyên bản cho chunk."""

    def __init__(self, db_path: Path, repo_root: Path, read_only: bool = False) -> None:
        self.db_path = Path(db_path).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.read_only = read_only
        self._cache = LRURecordCache()
        self._shard_handles: Dict[int, Any] = {}
        self._shard_paths: Dict[int, Path] = {}

        # Khởi tạo kết nối SQLite
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

        if not read_only:
            self._init_tables()
        else:
            self.conn.execute("PRAGMA query_only = ON;")

    def _init_tables(self) -> None:
        """Tạo schema bảng con trỏ."""
        with self.conn:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = NORMAL;")
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_shards (
                    shard_id INTEGER PRIMARY KEY,
                    relative_path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    sha256 TEXT NOT NULL
                );
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    shard_id INTEGER NOT NULL,
                    record_byte_offset INTEGER NOT NULL,
                    record_byte_length INTEGER NOT NULL,
                    record_sha256 TEXT NOT NULL,
                    FOREIGN KEY(shard_id) REFERENCES source_shards(shard_id)
                );
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id INTEGER NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    parent_id TEXT,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    chunk_text_sha256 TEXT NOT NULL,
                    quality_state TEXT NOT NULL DEFAULT 'ok',
                    FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
                );
                """
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);")

    def register_shard(self, relative_path: str, size_bytes: int, mtime_ns: int, sha256_hash: str) -> int:
        """Đăng ký một shard file nguồn và trả về shard_id."""
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT OR REPLACE INTO source_shards (relative_path, size_bytes, mtime_ns, sha256)
                VALUES (?, ?, ?, ?)
                RETURNING shard_id;
                """,
                (relative_path, size_bytes, mtime_ns, sha256_hash),
            )
            row = cursor.fetchone()
            shard_id = row[0]
            self._shard_paths[shard_id] = (self.repo_root / relative_path).resolve()
            return shard_id

    def insert_batch(
        self,
        docs: Sequence[Tuple[int, str, int, int, int, str]],
        chunks: Sequence[Tuple[str, int, int, str | None, int, int, str, str]],
    ) -> None:
        """Ghi batch tài liệu và chunks vào cơ sở dữ liệu."""
        with self.conn:
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO documents (doc_id, url, shard_id, record_byte_offset, record_byte_length, record_sha256)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                docs,
            )
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO chunks (chunk_id, doc_id, chunk_order, parent_id, start_char, end_char, chunk_text_sha256, quality_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                chunks,
            )

    def _get_shard_path(self, shard_id: int) -> Path:
        """Lấy đường dẫn file của shard."""
        if shard_id not in self._shard_paths:
            cur = self.conn.execute("SELECT relative_path FROM source_shards WHERE shard_id = ?", (shard_id,))
            row = cur.fetchone()
            if not row:
                raise FileNotFoundError(f"Shard ID {shard_id} không tồn tại trong metadata.")
            self._shard_paths[shard_id] = (self.repo_root / row[0]).resolve()
        return self._shard_paths[shard_id]

    def _get_shard_handle(self, shard_id: int):
        """Mở và cache file handle nhị phân của shard."""
        if shard_id not in self._shard_handles:
            path = self._get_shard_path(shard_id)
            self._shard_handles[shard_id] = open(path, "rb")
        return self._shard_handles[shard_id]

    def get_many(self, chunk_ids: Sequence[str]) -> Mapping[str, OriginalChunk]:
        """Lấy danh sách OriginalChunk nguyên bản bằng Seek nhị phân trực tiếp."""
        if not chunk_ids:
            return {}

        results: Dict[str, OriginalChunk] = {}
        unique_ids = list(set(chunk_ids))

        # Query vị trí byte offset cho từng chunk
        # Sử dụng placeholders an toàn
        placeholders = ",".join("?" for _ in unique_ids)
        query = f"""
            SELECT c.chunk_id, c.doc_id, c.chunk_order, c.parent_id,
                   c.start_char, c.end_char, c.chunk_text_sha256, c.quality_state,
                   d.shard_id, d.record_byte_offset, d.record_byte_length, d.record_sha256
            FROM chunks c
            JOIN documents d ON c.doc_id = d.doc_id
            WHERE c.chunk_id IN ({placeholders});
        """

        rows = self.conn.execute(query, unique_ids).fetchall()

        # Nhóm theo shard và byte_offset để đọc 1 lần cho cùng record
        records_to_read: Dict[Tuple[int, int, int], List[sqlite3.Row]] = {}
        for row in rows:
            key = (row["shard_id"], row["record_byte_offset"], row["record_byte_length"])
            records_to_read.setdefault(key, []).append(row)

        for (shard_id, byte_offset, byte_len), chunk_rows in records_to_read.items():
            # Thử lấy từ cache
            record_json = self._cache.get(shard_id, byte_offset)
            if record_json is None:
                fh = self._get_shard_handle(shard_id)
                fh.seek(byte_offset)
                raw_bytes = fh.read(byte_len)

                # Kiểm tra record hash
                rec_sha = hashlib.sha256(raw_bytes).hexdigest()
                expected_rec_sha = chunk_rows[0]["record_sha256"]
                if expected_rec_sha and rec_sha != expected_rec_sha:
                    raise ValueError(
                        f"Phát hiện Data Corruption tại shard {shard_id}, offset {byte_offset}. Hash thực: {rec_sha}, kỳ vọng: {expected_rec_sha}"
                    )

                record_json = json.loads(raw_bytes.decode("utf-8"))
                self._cache.put(shard_id, byte_offset, record_json, byte_len)

            # Lấy chunk_text nguyên bản từ record_json
            children = record_json.get("children", [])
            for r in chunk_rows:
                cid = r["chunk_id"]
                c_order = r["chunk_order"]
                expected_sha = r["chunk_text_sha256"]

                # Tìm child khớp chunk_id hoặc chunk_order
                target_child = None
                if c_order < len(children) and children[c_order].get("chunk_id") == cid:
                    target_child = children[c_order]
                else:
                    for ch in children:
                        if ch.get("chunk_id") == cid:
                            target_child = ch
                            break

                if not target_child:
                    raise KeyError(f"Không tìm thấy child chunk {cid} trong JSON record của doc {r['doc_id']}.")

                verbatim_text = target_child.get("chunk_text", "")

                # Xác minh hash chunk
                actual_sha = hashlib.sha256(verbatim_text.encode("utf-8")).hexdigest()
                if actual_sha != expected_sha:
                    raise ValueError(
                        f"Chunk {cid} bị lệch hash nguyên bản: {actual_sha} != {expected_sha}. Text đã bị biến đổi!"
                    )

                results[cid] = OriginalChunk(
                    chunk_id=cid,
                    doc_id=r["doc_id"],
                    chunk_order=c_order,
                    chunk_text=verbatim_text,
                    chunk_text_sha256=actual_sha,
                    parent_id=r["parent_id"],
                    start_char=r["start_char"],
                    end_char=r["end_char"],
                    quality_state=r["quality_state"],
                )

        return results

    def close(self) -> None:
        """Đóng tất cả handles và kết nối SQLite."""
        for fh in self._shard_handles.values():
            try:
                fh.close()
            except Exception:
                pass
        self._shard_handles.clear()

        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
