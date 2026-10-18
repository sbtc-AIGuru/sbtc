import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer
from BackEnd.app.Retrieval.backend import LuceneBackend, build_indexes
from BackEnd.app.Retrieval.corpus import CorpusPreparer
from BackEnd.app.Retrieval.index_writer import DirectLucenePartition
from BackEnd.app.Retrieval.lexicon import Lexicon
from BackEnd.app.Retrieval.models import FIELDS
from BackEnd.app.Retrieval.rolling import RollingIndexer, _prepared_jsonl, _prepared_jsonl_size
from BackEnd.app.Retrieval.store import TextStore


class RollingIndexerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="retrieval-rolling-test-")
        self.root = Path(self.temp.name)
        self.input = self.root / "source"
        self.input.mkdir()
        self.analyzer = MedicalAnalyzer(Lexicon())
        self.records = self._records()
        self.source = self.input / "part-000000.jsonl"
        self.source.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in self.records), encoding="utf-8")
        self.corpus = self.root / "corpus.parquet"
        pq.write_table(pa.Table.from_pylist([{"id": r["doc_id"], "url": r["url"]} for r in self.records]), self.corpus)
        self.bulk_root = self.root / "bulk"
        self.rolling_root = self.root / "rolling"

    def tearDown(self):
        self.temp.cleanup()

    def test_prepared_jsonl_streams_bounded_json_and_matches_canonical_record(self):
        fields = {
            "contents": ("药物", 'quoted"token', r"back\\slash"),
            "broad": ("高血压",),
            "exact": (),
            "anchors": ("local:hypertension",),
            "title": ("医学",),
        }
        pieces = list(_prepared_jsonl("chunk:1", fields))
        encoded = b"".join(pieces)
        expected = json.dumps(
            {"id": "chunk:1", **{field: " ".join(fields[field]) for field in FIELDS}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        self.assertEqual(encoded, expected)
        self.assertEqual(_prepared_jsonl_size("chunk:1", fields), len(encoded))

        large_token = "药" * 100_000
        streamed = list(_prepared_jsonl("chunk:2", {**fields, "contents": (large_token,)}))
        self.assertGreater(len(streamed), 10)
        self.assertLessEqual(max(map(len, streamed)), 8192)
        self.assertEqual(json.loads(b"".join(streamed))["contents"], large_token)

    @staticmethod
    def _records():
        examples = [
            ("vi", "Bệnh nhân bị tăng huyết áp và đái tháo đường type 2."),
            ("vi", "Theo dõi suy thận mạn và kiểm soát huyết áp."),
            ("en", "Patient has hypertension and diabetes mellitus type 2."),
            ("en", "Chronic kidney disease requires regular blood pressure monitoring."),
            ("zh", "患者患有高血压和2型糖尿病。"),
            ("zh", "慢性肾病需要定期监测血压。"),
        ]
        records = []
        for offset, (language, text) in enumerate(examples):
            doc_id = 1001 + offset
            records.append({
                "doc_id": doc_id,
                "url": f"https://example.test/{doc_id}",
                "status": "ok",
                "source_language": language,
                "title_spans": [],
                "children": [{
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}:0",
                    "chunk_order": 0,
                    "start_char": 0,
                    "end_char": len(text),
                    "chunk_text": text,
                    "content_languages": [language],
                    "retrieval_eligible": True,
                }],
            })
        return records

    def make_indexer(self):
        return RollingIndexer(
            self.analyzer,
            staging_target_bytes=700,
            staging_max_bytes=5_000,
            control_reserve_bytes=1_024,
            writer_ram_buffer_mib=1,
            disk_reserve_bytes=0,
        )

    def build_bulk_baseline(self):
        CorpusPreparer(self.analyzer).prepare(self.input, self.bulk_root, self.corpus)
        build_indexes(self.bulk_root)

    def test_rolling_matches_bulk_and_caps_single_live_stage(self):
        self.build_bulk_baseline()
        manifest = self.make_indexer().run(self.input, self.rolling_root, self.corpus)
        self.assertEqual(manifest["status"], "READY")
        self.assertTrue(manifest["prepared"])
        self.assertEqual(manifest["counts"]["records"], len(self.records))
        self.assertEqual(manifest["counts"]["chunks"], len(self.records))
        self.assertEqual(len(manifest["indexes"]), 6)
        self.assertNotIn("folded", FIELDS)

        for path in (self.rolling_root / "prepared").rglob("*.jsonl") if (self.rolling_root / "prepared").exists() else ():
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertNotIn("folded", json.loads(line))

        with TextStore(self.rolling_root / "metadata.sqlite") as store:
            self.assertEqual(store.db.execute("SELECT count(*) FROM document_routes").fetchone()[0], len(self.records))
            self.assertEqual(store.db.execute("SELECT count(*) FROM chunk_routes").fetchone()[0], len(self.records))
            for record in self.records:
                child = record["children"][0]
                self.assertEqual(store.get(child["chunk_id"])["chunk_text"], child["chunk_text"])

        prepared = list((self.rolling_root / "staging").glob("batch-*") )
        self.assertEqual(prepared, [])
        with (self.rolling_root / "rolling_metrics.jsonl").open(encoding="utf-8") as source:
            metrics = [json.loads(line) for line in source]
        prepared_batches = [row for row in metrics if row["status"] == "PREPARED"]
        self.assertGreater(len(prepared_batches), 1)
        self.assertLessEqual(max(row["stage_bytes"] for row in prepared_batches), 5_000)
        self.assertTrue(any(row["events"] == 1 for row in prepared_batches), "target should split chunk and document views into separate batches")

        self.assertEqual(DirectLucenePartition.read_committed(self.rolling_root / "indexes/documents/vi")["user_data"]["analyzer_profile"], "medical-no-folded-v1")
        for root in (self.bulk_root, self.rolling_root):
            for granularity in ("documents", "chunks"):
                for language in ("vi", "en", "zh"):
                    index_path = root / "indexes" / granularity / language
                    self.assertFalse(self._has_field(index_path, "folded"))
                    self.assertGreater(self._doc_count(index_path, "broad"), 0)

        bulk = LuceneBackend(self.bulk_root, k1=0.8, b=0.4)
        rolling = LuceneBackend(self.rolling_root, k1=0.8, b=0.4)
        try:
            queries = {
                "vi": "tăng huyết áp",
                "en": "hypertension diabetes",
                "zh": "高血压 糖尿病",
            }
            for lang, query in queries.items():
                analysis = self.analyzer.analyze(query, lang, index_mode=False).fields
                query_fields = {field: analysis[field] for field in FIELDS if analysis.get(field)}
                for granularity in ("documents", "chunks"):
                    expected = bulk.search(granularity, lang, query_fields, k=10)
                    actual = rolling.search(granularity, lang, query_fields, k=10)
                    self.assertEqual([hit.identifier for hit in actual], [hit.identifier for hit in expected])
                    for got, want in zip(actual, expected):
                        self.assertTrue(math.isclose(got.score, want.score, rel_tol=1e-6, abs_tol=1e-5), (lang, granularity, got, want))
        finally:
            bulk.close()
            rolling.close()

    def test_limit_stops_after_complete_source_records(self):
        limited_root = self.root / "rolling-limit"
        manifest = RollingIndexer(
            self.analyzer,
            staging_target_bytes=700,
            staging_max_bytes=5_000,
            control_reserve_bytes=1_024,
            writer_ram_buffer_mib=1,
            disk_reserve_bytes=0,
            limit=2,
        ).run(self.input, limited_root, self.corpus)
        self.assertEqual(manifest["status"], "READY")
        self.assertEqual(manifest["counts"]["records"], 2)
        self.assertEqual(manifest["counts"]["chunks"], 2)
        with TextStore(limited_root / "metadata.sqlite") as store:
            identifiers = [row[0] for row in store.db.execute("SELECT id FROM documents ORDER BY id")]
            self.assertEqual(identifiers, [1001, 1002])

    def test_partial_partition_commit_resumes_without_duplicate_documents(self):
        indexer = self.make_indexer()
        original = DirectLucenePartition.commit_batch
        fired = {"value": False}

        def interrupt_after_first_partition(writer, **kwargs):
            if writer.partition == "chunks/vi" and not fired["value"]:
                fired["value"] = True
                raise RuntimeError("injected interruption before second partition commit")
            return original(writer, **kwargs)

        with patch.object(DirectLucenePartition, "commit_batch", new=interrupt_after_first_partition):
            with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                indexer.run(self.input, self.rolling_root, self.corpus)
        self.assertTrue(fired["value"])

        manifest = self.make_indexer().run(self.input, self.rolling_root, self.corpus)
        self.assertEqual(manifest["status"], "READY")
        self.assertEqual(manifest["counts"]["records"], len(self.records))
        with TextStore(self.rolling_root / "metadata.sqlite") as store:
            self.assertEqual(store.db.execute("SELECT count(*) FROM documents").fetchone()[0], len(self.records))
            self.assertEqual(store.db.execute("SELECT count(*) FROM chunks").fetchone()[0], len(self.records))
        for granularity in ("documents", "chunks"):
            for language in ("vi", "en", "zh"):
                index = DirectLucenePartition.read_committed(self.rolling_root / "indexes" / granularity / language)
                self.assertEqual(index["documents"], manifest["counts"][f"views_{granularity}_{language}"])

    @staticmethod
    def _doc_count(index_path: Path, field: str) -> int:
        from BackEnd.app.Retrieval.runtime import configure_java
        configure_java()
        from pyserini.pyclass import autoclass
        directory = autoclass("org.apache.lucene.store.FSDirectory").open(autoclass("java.nio.file.Paths").get(str(index_path)))
        try:
            reader = autoclass("org.apache.lucene.index.DirectoryReader").open(directory)
            try:
                return int(reader.getDocCount(field))
            finally:
                reader.close()
        finally:
            directory.close()

    @staticmethod
    def _has_field(index_path: Path, field: str) -> bool:
        from BackEnd.app.Retrieval.runtime import configure_java
        configure_java()
        from pyserini.pyclass import autoclass
        directory = autoclass("org.apache.lucene.store.FSDirectory").open(autoclass("java.nio.file.Paths").get(str(index_path)))
        try:
            reader = autoclass("org.apache.lucene.index.DirectoryReader").open(directory)
            try:
                infos = autoclass("org.apache.lucene.index.FieldInfos").getMergedFieldInfos(reader)
                return infos.fieldInfo(field) is not None
            finally:
                reader.close()
        finally:
            directory.close()


if __name__ == "__main__":
    unittest.main()
