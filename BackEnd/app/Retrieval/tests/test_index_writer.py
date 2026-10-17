import json
import tempfile
import unittest
from pathlib import Path

from BackEnd.app.Retrieval.index_writer import DirectLucenePartition


class DirectLucenePartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="retrieval-direct-writer-")
        self.root = Path(self.temp.name)
        self.path = self.root / "index"
        self.run_id = "writer-test"
        self.spec_hash = "a" * 64

    def tearDown(self):
        self.temp.cleanup()

    def write_batch(self, name, records):
        path = self.root / name
        path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
        return path

    def test_create_commit_then_append_preserves_all_live_docs_and_latest_receipt(self):
        first = self.write_batch("batch-one.jsonl", [
            {"id": "doc-1", "contents": "alpha beta", "broad": "alpha beta"},
            {"id": "doc-2", "contents": "beta gamma", "broad": "beta gamma"},
        ])
        with DirectLucenePartition(self.path, run_id=self.run_id, spec_hash=self.spec_hash, partition="documents/vi", mode="create") as writer:
            added, digest = writer.add_jsonl(first)
            self.assertEqual(added, 2)
            one = writer.commit_batch(batch_id="batch-1", stage_sha256="b" * 64, event_digest=digest)
            self.assertEqual(one["documents"], 2)

        second = self.write_batch("batch-two.jsonl", [
            {"id": "doc-3", "contents": "gamma delta", "broad": "gamma delta"},
        ])
        with DirectLucenePartition(self.path, run_id=self.run_id, spec_hash=self.spec_hash, partition="documents/vi", mode="append") as writer:
            added, digest = writer.add_jsonl(second)
            self.assertEqual(added, 1)
            two = writer.commit_batch(batch_id="batch-2", stage_sha256="c" * 64, event_digest=digest)
            self.assertEqual(two["documents"], 3)

        receipt = DirectLucenePartition.read_committed(self.path)
        self.assertEqual(receipt["documents"], 3)
        self.assertEqual(receipt["user_data"]["batch_id"], "batch-2")
        self.assertEqual(receipt["user_data"]["run_id"], self.run_id)
        self.assertEqual(receipt["user_data"]["partition"], "documents/vi")

    def test_uncommitted_documents_are_not_committed_on_close_or_rollback(self):
        batch = self.write_batch("uncommitted.jsonl", [
            {"id": "doc-1", "contents": "alpha beta", "broad": "alpha beta"},
        ])
        writer = DirectLucenePartition(self.path, run_id=self.run_id, spec_hash=self.spec_hash, partition="chunks/zh", mode="create")
        writer.add_jsonl(batch)
        writer.rollback()
        receipt = DirectLucenePartition.read_committed(self.path)
        self.assertEqual(receipt["documents"], 0)
        self.assertEqual(receipt["user_data"]["batch_id"], "__initial__")

    def test_close_does_not_commit_documents_without_a_batch_receipt(self):
        batch = self.write_batch("close-uncommitted.jsonl", [
            {"id": "doc-1", "contents": "alpha beta", "broad": "alpha beta"},
        ])
        writer = DirectLucenePartition(self.path, run_id=self.run_id, spec_hash=self.spec_hash, partition="chunks/zh", mode="create")
        writer.add_jsonl(batch)
        writer.close()
        receipt = DirectLucenePartition.read_committed(self.path)
        self.assertEqual(receipt["documents"], 0)
        self.assertEqual(receipt["user_data"]["batch_id"], "__initial__")

    def test_create_refuses_to_overwrite_existing_partition(self):
        self.path.mkdir()
        (self.path / "keep.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "nonempty Lucene partition"):
            DirectLucenePartition(self.path, run_id=self.run_id, spec_hash=self.spec_hash, partition="documents/en", mode="create")
        self.assertEqual((self.path / "keep.txt").read_text(encoding="utf-8"), "preserve")

    def test_append_rejects_partition_from_another_run(self):
        with DirectLucenePartition(self.path, run_id=self.run_id, spec_hash=self.spec_hash, partition="documents/vi", mode="create"):
            pass
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            DirectLucenePartition(self.path, run_id=self.run_id, spec_hash="d" * 64, partition="documents/vi", mode="append")


if __name__ == "__main__":
    unittest.main()
