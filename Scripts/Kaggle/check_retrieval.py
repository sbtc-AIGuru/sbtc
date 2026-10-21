"""Small adapter checks, executed only inside the Kaggle notebook."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from copy import deepcopy

from Scripts.Kaggle.retrieval_runtime import build_source_index, JsonSourceStore, validate_submission, compare_query_traces


class SourceAdapterChecks(unittest.TestCase):
    def setUp(self):
        if not Path("/kaggle/input").is_dir():
            raise RuntimeError("Run these checks on Kaggle, not the local machine")
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"])
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.documents = [
            {"doc_id": 3, "children": [
                {"chunk_id": "3:c:0", "doc_id": 3, "chunk_text": "Tiếng Việt\n中文 &amp; English"},
                {"chunk_id": "3:c:1", "doc_id": 3, "chunk_text": "", "retrieval_eligible": False}]},
            {"doc_id": 17, "children": [
                {"chunk_id": "17:c:0", "doc_id": 17, "chunk_text": "Second source — exact  spacing"}]},
        ]

    def make_store(self, array=False):
        source = self.root / ("merged.json" if array else "merged.jsonl")
        lines = [json.dumps(doc, ensure_ascii=False) for doc in self.documents]
        text = "[\n" + ",\n".join(lines) + "\n]\n" if array else "\n".join(lines) + "\n"
        source.write_text(text)
        manifest = {"signature": {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                   "expected_documents": 2, "expected_chunks": 3}}
        database = self.root / "source.sqlite"
        local_source = self.root / ("local.json" if array else "local.jsonl")
        result = build_source_index(source, database, manifest, local_source=local_source)
        self.assertEqual(result["chunks"], 3)
        self.assertEqual(source.read_bytes(), local_source.read_bytes())
        self.assertEqual(build_source_index(source, database, manifest, local_source=local_source), result)
        store = JsonSourceStore(local_source, database, cache_bytes=1000)
        self.addCleanup(store.close)
        return source, database, manifest, store

    def test_jsonl_verbatim_offsets_missing_ids_and_cache(self):
        _, _, _, store = self.make_store()
        for _ in range(2):
            values = store.get_submission_chunks(["17:c:0", "3:c:0", "missing", "3:c:1"], batch_size=2)
            self.assertEqual(values["17:c:0"]["chunk_text"], self.documents[1]["children"][0]["chunk_text"])
            self.assertEqual(values["3:c:0"]["doc_id"], 3)
            self.assertEqual(values["3:c:0"]["chunk_text"], self.documents[0]["children"][0]["chunk_text"])
            self.assertEqual(values["3:c:1"]["chunk_text"], "")
            self.assertIsNone(values["missing"])
            self.assertLessEqual(store.cached_bytes, store.cache_bytes)

    def test_json_array_preserves_non_ascii_byte_offsets(self):
        _, _, _, store = self.make_store(array=True)
        self.assertEqual(store.get_submission_chunks(["17:c:0"])["17:c:0"]["doc_id"], 17)

    def test_source_checksum_mismatch_is_rejected(self):
        source, _, manifest, _ = self.make_store()
        manifest["signature"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum"):
            build_source_index(source, self.root / "wrong.sqlite", manifest)

    def test_validation_supports_resumed_out_of_order_journal(self):
        _, _, _, store = self.make_store()
        predictions = [{"id": 91, "relevant_docs": [3], "relevant_chunks": [
            {"doc_id": 3, "chunk_text": self.documents[0]["children"][0]["chunk_text"]}]},
            {"id": 14, "relevant_docs": [17], "relevant_chunks": [
                {"doc_id": 17, "chunk_text": self.documents[1]["children"][0]["chunk_text"]}]}]
        output, archive, checkpoint = [self.root / name for name in ("submission.json", "submission.zip", "checkpoint.jsonl")]
        output.write_text(json.dumps(predictions, ensure_ascii=False))
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(output, arcname=output.name)
        entries = [{"version": 1}, {"row": 8, "prediction": predictions[1], "chunk_ids": ["17:c:0"]},
                   {"row": 7, "prediction": predictions[0], "chunk_ids": ["3:c:0"]}]
        checkpoint.write_text("\n".join(json.dumps(item) for item in entries) + "\n")
        report = validate_submission(output, archive, checkpoint, [91, 14], store, start_row=7)
        self.assertEqual(report["source_chunks_verified"], 2)
        predictions[0]["relevant_chunks"][0]["chunk_text"] = "changed text"
        output.write_text(json.dumps(predictions))
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(output, arcname=output.name)
        with self.assertRaisesRegex(ValueError, "Checkpoint prediction"):
            validate_submission(output, archive, checkpoint, [91, 14], store, start_row=7)

    def test_live_comparison_accepts_only_equal_score_permutations(self):
        points = [{"payload": {"chunk_id": name}, "score": score}
                  for name, score in [("a", 0.5), ("b", 0.3), ("c", 0.3)]]
        baseline = [{"body": {"limit": 3}, "result": {"points": points}}]
        live = deepcopy(baseline)
        live[0]["result"]["points"][1:] = reversed(live[0]["result"]["points"][1:])
        self.assertEqual(compare_query_traces(baseline, live)["queries_with_tie_permutations"], 1)
        live[0]["result"]["points"].reverse()
        with self.assertRaisesRegex(ValueError, "distinct scores"):
            compare_query_traces(baseline, live)
        live = deepcopy(baseline)
        live[0]["result"]["points"][0]["payload"]["chunk_id"] = "different"
        with self.assertRaisesRegex(ValueError, "candidate set"):
            compare_query_traces(baseline, live)

    def test_cutoff_substitution_requires_expanded_live_score_evidence(self):
        body = {"limit": 2, "prefetch": [{"limit": 4}]}
        points = [{"payload": {"chunk_id": name}, "score": score}
                  for name, score in [("a", 0.5), ("b", 0.3), ("c", 0.3), ("d", 0.1)]]
        baseline = [{"body": body, "result": {"points": deepcopy(points[:2])}}]
        live = [{"body": body, "result": {"points": deepcopy([points[0], points[2]])}}]
        control = [{"body": {**body, "limit": 4}, "result": {"points": deepcopy(points)}}]
        with self.assertRaisesRegex(ValueError, "without cutoff tie evidence"):
            compare_query_traces(baseline, live)
        report = compare_query_traces(baseline, live, control)
        self.assertEqual(report["cutoff_tie_candidate_substitutions"], 1)
        self.assertFalse(report["identical_candidate_sets"])
        control[0]["result"]["points"][2]["score"] = 0.2
        with self.assertRaisesRegex(ValueError, "control changed"):
            compare_query_traces(baseline, live, control)
        control[0]["result"]["points"][2]["score"] = 0.3
        live[0]["result"]["points"] = deepcopy([points[2], points[1]])
        with self.assertRaisesRegex(ValueError, "above the cutoff tie"):
            compare_query_traces(baseline, live, control)


if __name__ == "__main__":
    unittest.main(verbosity=2)
