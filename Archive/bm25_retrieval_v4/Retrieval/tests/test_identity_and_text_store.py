"""Unit Tests for IdentityRegistry and SourcePointerTextStore.

Kiểm tra tính toàn vẹn danh tính và phục hồi văn bản nguyên bản qua binary seek.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sbtc.Scripts.Retrieval.identity import IdentityRegistry
from sbtc.Scripts.Retrieval.text_store import SourcePointerTextStore


class TestIdentityAndTextStore(unittest.TestCase):
    def test_identity_registry_validation(self):
        """Kiểm tra loại bỏ bool, float và kiểm tra membership."""
        valid_set = {100, 200, 300}
        reg = IdentityRegistry(valid_set, "dummy_hash", 100, 300)

        self.assertTrue(reg.is_valid_doc_id(100))
        self.assertTrue(reg.is_valid_doc_id("200"))
        self.assertFalse(reg.is_valid_doc_id(True))  # bool là subclass của int trong python!
        self.assertFalse(reg.is_valid_doc_id(False))
        self.assertFalse(reg.is_valid_doc_id(100.5))  # float
        self.assertFalse(reg.is_valid_doc_id(999))  # không thuộc whitelist
        self.assertFalse(reg.is_valid_doc_id("invalid_str"))

    def test_source_pointer_binary_seek_and_hash_integrity(self):
        """Tạo file shard JSONL giả lập, kiểm tra binary seek và hydrate verbatim."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            shard_file = tmp_path / "shard_0.jsonl"
            db_file = tmp_path / "metadata.sqlite"

            record_1 = {
                "id": 1001,
                "url": "https://example.com/med1",
                "text": "Đoạn văn bản y khoa mẫu về bệnh thận.",
                "children": [
                    {
                        "chunk_id": "1001_0",
                        "doc_id": 1001,
                        "chunk_order": 0,
                        "chunk_text": "Đoạn văn bản y khoa mẫu về bệnh thận.",
                        "start_char": 0,
                        "end_char": 37,
                        "retrieval_eligible": True,
                    }
                ],
            }

            record_2 = {
                "id": 1002,
                "url": "https://example.com/med2",
                "text": "Tim mạch và huyết áp cao.",
                "children": [
                    {
                        "chunk_id": "1002_0",
                        "doc_id": 1002,
                        "chunk_order": 0,
                        "chunk_text": "Tim mạch và huyết áp cao.",
                        "start_char": 0,
                        "end_char": 25,
                        "retrieval_eligible": True,
                    }
                ],
            }

            # Ghi shard và lưu byte offset
            pointers = []
            with open(shard_file, "wb") as f:
                for rec in [record_1, record_2]:
                    offset = f.tell()
                    line_bytes = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
                    length = len(line_bytes)
                    rec_sha = hashlib.sha256(line_bytes).hexdigest()
                    f.write(line_bytes)
                    pointers.append((rec["id"], rec["url"], offset, length, rec_sha, rec["children"][0]))

            # Khởi tạo TextStore
            store = SourcePointerTextStore(db_file, tmp_path, read_only=False)
            shard_id = store.register_shard(
                "shard_0.jsonl",
                shard_file.stat().st_size,
                shard_file.stat().st_mtime_ns,
                "dummy_shard_sha",
            )

            docs_batch = []
            chunks_batch = []
            for did, url, off, length, r_sha, ch in pointers:
                docs_batch.append((did, url, shard_id, off, length, r_sha))
                c_sha = hashlib.sha256(ch["chunk_text"].encode("utf-8")).hexdigest()
                chunks_batch.append(
                    (ch["chunk_id"], did, ch["chunk_order"], None, ch["start_char"], ch["end_char"], c_sha, "ok")
                )

            store.insert_batch(docs_batch, chunks_batch)

            # Test hydrate qua get_many
            hydrated = store.get_many(["1001_0", "1002_0"])
            self.assertEqual(len(hydrated), 2)
            self.assertEqual(hydrated["1001_0"].chunk_text, "Đoạn văn bản y khoa mẫu về bệnh thận.")
            self.assertEqual(hydrated["1002_0"].chunk_text, "Tim mạch và huyết áp cao.")
            self.assertTrue(hydrated["1001_0"].validate_hash())
            self.assertTrue(hydrated["1002_0"].validate_hash())

            store.close()


if __name__ == "__main__":
    unittest.main()
