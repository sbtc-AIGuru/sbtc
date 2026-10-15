"""Critical leakage, evidence, negative-label and export invariants."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Scripts.BGE_M3_Data.common import load_config, parse_model_json, read_jsonl, text_hash, write_json, write_jsonl
from Scripts.BGE_M3_Data.corpus import canonical_url, group_documents, iter_documents, passage_rejection, prepare
from Scripts.BGE_M3_Data.export import export_dataset, retrieval_metrics, validate_triplet
from Scripts.BGE_M3_Data.generation import judge_decisions, validate_generated_item
from Scripts.BGE_M3_Data.kaggle import build_bundle
from Scripts.BGE_M3_Data.mining import candidate_allowed, filter_teacher_candidates, lexical_terms


CONFIG = ROOT / "Scripts/BGE_M3_Data/config.json"
TEXT = "B\u00e1o c\u00e1o c\u1ee7a WHO t\u1ed5ng h\u1ee3p c\u00e1c nghi\u00ean c\u1ee9u trong giai \u0111o\u1ea1n 1990 \u0111\u1ebfn 2021. " * 4
EVIDENCE = "c\u00e1c nghi\u00ean c\u1ee9u trong giai \u0111o\u1ea1n 1990 \u0111\u1ebfn 2021."
QUERY = "B\u00e1o c\u00e1o WHO t\u1ed5ng h\u1ee3p nghi\u00ean c\u1ee9u trong nh\u1eefng n\u0103m n\u00e0o?"


def passage(identity: str, group: str = "g1", split: str = "train", text: str = TEXT) -> dict:
    return {"chunk_id": identity, "doc_id": identity.split(":")[0], "parent_id": "parent",
            "start_char": 0, "end_char": len(text), "text": text, "text_hash": text_hash(text),
            "language": "vi", "domain": "example.vn", "group_id": group, "split": split,
            "question_only_risk": False, "url": "https://example.vn/article"}


def document(identity: int, text: str = TEXT, url: str | None = None) -> dict:
    return {"doc_id": identity, "url": url or f"https://example.vn/{identity}", "status": "ok",
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "doc_type": "article",
            "parents": [{"parent_id": f"{identity}:p", "start_char": 0, "end_char": len(text)}],
            "children": [{"chunk_id": f"{identity}:c", "parent_id": f"{identity}:p", "doc_id": identity,
                          "start_char": 0, "end_char": len(text), "chunk_order": 0,
                          "chunk_text": text, "retrieval_eligible": True}]}


class TestCorpusSafety(unittest.TestCase):
    def setUp(self):
        self.config = load_config(CONFIG)

    def test_stream_checksum_and_invalid_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "merged.json"
            source = "[\n" + json.dumps(document(1)) + "\n]\n"
            path.write_text(source)
            digest = hashlib.sha256()
            self.assertEqual(len(list(iter_documents(path, digest))), 1)
            self.assertEqual(digest.hexdigest(), hashlib.sha256(source.encode()).hexdigest())
            path.write_text("[\n{},\n]\n")
            with self.assertRaisesRegex(ValueError, "Trailing comma"):
                list(iter_documents(path, hashlib.sha256()))
            path.write_text("[\n{}\n{}\n]\n")
            with self.assertRaisesRegex(ValueError, "Missing separator"):
                list(iter_documents(path, hashlib.sha256()))

    def test_short_headings_ads_and_wrong_spans_rejected(self):
        child = document(1)["children"][0]
        self.assertIsNone(passage_rejection(child, "vi", self.config))
        short = {**child, "chunk_text": "\u75c7\u72b6", "end_char": 2}
        self.assertEqual(passage_rejection(short, "zh", self.config), "short_or_heading")
        ad = "\u9884\u7ea6\u6302\u53f7 \u533b\u9662\u6392\u540d " * 30
        self.assertEqual(passage_rejection({**child, "chunk_text": ad, "end_char": len(ad)}, "zh", self.config), "hospital_advertising")
        self.assertEqual(passage_rejection({**child, "end_char": 10}, "vi", self.config), "invalid_character_span")

    def test_reserved_duplicate_and_title_groups_never_leak(self):
        records = []
        for identity, source_hash, title in [(1, "same", "shared medical title"), (2, "same", "different title"), (3, "third", "shared medical title")]:
            records.append({"doc_id": identity, "source_sha256": source_hash, "canonical_url": f"https://test/{identity}",
                            "title": title, "language": "vi", "children": [{"text_hash": str(identity)}]})
        reserved = [deepcopy(records[1])]
        group_documents(records, reserved, self.config)
        self.assertEqual(len({record["group_id"] for record in records}), 1)
        self.assertEqual({record["split"] for record in records}, {"test"})

    def test_full_prepare_is_bounded_reproducible_and_preserves_source(self):
        config = {**self.config, "documents_per_source": 3, "query_passages": 6, "max_corpus_chunks": 12,
                  "min_passage_chars": {"vi": 50, "zh": 30}, "negative_count": 1}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "merged.json"
            rows = [document(index, f"Th\u00f4ng tin y t\u1ebf ri\u00eang {index}.\n" + TEXT + str(index)) for index in range(30)]
            source.write_text("[\n" + ",\n".join(json.dumps(row) for row in rows) + "\n]\n")
            before = source.read_bytes()
            first = prepare(source, root / "first", config, [])
            second = prepare(source, root / "second", config, [])
            self.assertEqual(first["source_sha256"], second["source_sha256"])
            self.assertEqual((root / "first/corpus.jsonl").read_bytes(), (root / "second/corpus.jsonl").read_bytes())
            self.assertLessEqual(first["stages"]["prepare"]["corpus_chunks"], 3)
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(prepare(source, root / "first", config, []), first)

    def test_canonical_url_preserves_resource_parameters(self):
        self.assertEqual(canonical_url("https://EXAMPLE.com/a?id=7&utm_source=x#top"), "https://example.com/a?id=7")


class TestEvidenceAndNegatives(unittest.TestCase):
    def setUp(self):
        self.config = load_config(CONFIG)
        self.anchor = passage("1:a")
        self.sibling = passage("1:b", text=EVIDENCE + "\n" + TEXT)
        self.task = {"task_id": "task", "chunk_id": "1:a", "doc_id": "1", "group_id": "g1", "split": "train",
                     "passage_language": "vi", "query_language": "vi"}
        self.item = {"query": QUERY, "evidence": EVIDENCE, "answer": "1990 to 2021", "intent": "fact"}

    def test_multi_positive_offsets_and_nonliteral_evidence(self):
        row = validate_generated_item(self.item, self.task, self.anchor, [self.anchor, self.sibling])
        self.assertEqual(set(row["positive_chunk_ids"]), {"1:a", "1:b"})
        for span in row["evidence_spans"]:
            text = {"1:a": self.anchor, "1:b": self.sibling}[span["chunk_id"]]["text"]
            self.assertEqual(text[span["start_char"]:span["end_char"]], EVIDENCE)
        with self.assertRaisesRegex(ValueError, "exact substring"):
            validate_generated_item({**self.item, "evidence": "The years were 1990 to 2021."}, self.task, self.anchor, [self.anchor])

    def test_judge_is_strict_about_ids_and_boolean_flags(self):
        self.assertEqual(parse_model_json('```json\n{"items":[]}\n```'), {"items": []})
        with self.assertRaisesRegex(ValueError, "boolean"):
            judge_decisions('{"items":[{"id":0,"supported":"false"}]}', 1, "supported")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            judge_decisions('{"items":[{"id":0,"label":"unanswerable"},{"id":0,"label":"uncertain"}]}', 2, "label")

    def test_negatives_exclude_overlap_evidence_and_heldout_passages(self):
        row = validate_generated_item(self.item, self.task, self.anchor, [self.anchor])
        self.assertFalse(candidate_allowed(self.sibling, row))
        self.assertFalse(candidate_allowed(passage("2:a", "g2"), row))
        self.assertFalse(candidate_allowed(passage("3:a", "g3", "test", "unrelated text"), row))
        self.assertTrue(candidate_allowed(passage("4:a", "g4", "train", "unrelated text"), row))

    def test_teacher_rejects_high_scoring_false_negatives_and_aligns_scores(self):
        row = validate_generated_item(self.item, self.task, self.anchor, [self.anchor])
        candidates = [passage(f"{index}:a", f"g{index}", text=f"unrelated text {index}") for index in range(2, 6)]
        config = {**self.config, "negative_count": 2, "negative_judge_candidates": 3}
        result = filter_teacher_candidates(row, ["1:a"], [4.0], candidates, [3.5, -1.0, -2.0, -3.0], config)
        self.assertIsNotNone(result)
        self.assertEqual([value["score"] for value in result["negative_candidates"]], [-1.0, -2.0, -3.0])
        self.assertIsNone(filter_teacher_candidates(row, ["1:a"], [-4.0], candidates, [-5.0] * 4, config))

    def test_sqlite_bm25_subword_query_with_split_join(self):
        with sqlite3.connect(":memory:") as database:
            database.execute("CREATE VIRTUAL TABLE passages USING fts5(terms)")
            database.execute("CREATE TABLE metadata(row_id INTEGER PRIMARY KEY,split TEXT)")
            database.executemany("INSERT INTO passages(rowid,terms) VALUES (?,?)", [(1, lexical_terms([0, 4, 5, 2], {0, 2})), (2, "t4 t5")])
            database.executemany("INSERT INTO metadata VALUES (?,?)", [(1, "train"), (2, "test")])
            rows = database.execute("SELECT passages.rowid FROM passages JOIN metadata ON passages.rowid=metadata.row_id WHERE passages MATCH ? AND metadata.split='train' ORDER BY bm25(passages) LIMIT ?", ('"t4" OR "t5"', 10)).fetchall()
            self.assertEqual(rows, [(1,)])


class TestExportsAndKaggle(unittest.TestCase):
    def test_export_keeps_silver_labels_and_enforces_completion(self):
        config = {**load_config(CONFIG), "negative_count": 1, "minimum_export_train_queries": 1, "minimum_export_eval_queries": 0}
        anchor = passage("1:a")
        negative = passage("2:a", "g2", text="A different supported topic.")
        task = {"task_id": "task", "group_id": "g1", "split": "train", "query_language": "vi", "passage_language": "vi"}
        item = {"query": QUERY, "evidence": EVIDENCE, "answer": "1990 to 2021", "intent": "fact"}
        row = validate_generated_item(item, task, anchor, [anchor])
        row.update(pos_scores=[4.0], negative_candidates=[{"chunk_id": "2:a", "score": -3.0}],
                   positive_judge={"supported": True})
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "cache").mkdir()
            write_json(work / "manifest.json", {"configuration": config, "stages": {}})
            write_jsonl(work / "corpus.jsonl", [anchor, negative])
            write_jsonl(work / "tasks.jsonl", [task])
            write_jsonl(work / "queries-0.jsonl", [row])
            write_jsonl(work / "mined-0.jsonl", [row])
            write_jsonl(work / "generation-ledger-0.jsonl", [{"task_id": "task"}])
            write_jsonl(work / "mining-ledger-0.jsonl", [{"query_id": row["query_id"]}])
            write_jsonl(work / "cache/eligible.jsonl", [{"chunk_id": "1:a"}, {"chunk_id": "2:a"}])
            decision = {"chunk_id": "2:a", "score": -3.0, "label": "unanswerable"}
            write_jsonl(work / "negative-judgments-0.jsonl", [{"query_id": row["query_id"], "verified_negative_candidates": [decision], "negative_decisions": [decision]}])
            report = export_dataset(work, config)
            self.assertTrue(report["dataset_complete"])
            exported = list(read_jsonl(work / "dataset/train.jsonl"))[0]
            self.assertEqual(exported["pos"], [TEXT])
            self.assertEqual(exported["neg_scores"], [-3.0])
            self.assertTrue((work / "bge_m3_dataset.zip").exists())
            provenance = list(read_jsonl(work / "dataset/provenance.jsonl"))[0]
            bad = deepcopy(provenance)
            bad["negative_judgments"][0]["label"] = "answerable"
            with self.assertRaisesRegex(ValueError, "unanswerable judgment"):
                validate_triplet(bad, {"1:a": anchor, "2:a": negative}, 1)
            incomplete = {**config, "minimum_export_train_queries": 2}
            with self.assertRaisesRegex(RuntimeError, "gates failed"):
                export_dataset(work, incomplete)

    def test_retrieval_metrics_count_multiple_positives(self):
        metrics = retrieval_metrics([{"positive_chunk_ids": ["a", "b"], "baseline_dense_top10": ["x", "b"]}])
        self.assertEqual(metrics["Recall@10"], 0.5)
        self.assertEqual(metrics["MRR@10"], 0.5)

    def test_private_self_contained_notebook_has_no_install_steps(self):
        config = load_config(CONFIG)
        for name in ("generator", "embedder", "reranker"):
            config[f"{name}_revision"] = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            write_json(config_path, config)
            build_bundle(root / "bundle", config_path, "owner/merged", "owner/bge-data", 12345, "b" * 64)
            metadata = json.loads((root / "bundle/kernel-metadata.json").read_text())
            self.assertTrue(metadata["is_private"])
            self.assertTrue(metadata["enable_gpu"])
            self.assertEqual(metadata["dataset_sources"], ["owner/merged"])
            notebook = json.loads((root / "bundle/notebook.ipynb").read_text())
            for cell in notebook["cells"]:
                if cell["cell_type"] == "code":
                    compile(cell["source"], "notebook", "exec")
                    self.assertNotIn("pip install", cell["source"])
                    self.assertNotIn("KAGGLE_KEY", cell["source"])


if __name__ == "__main__":
    unittest.main()
