"""Chunking checks based only on datacrawl/test.jsonl records."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from sbtc.Scripts.Clawler.verbatim import clean_to_verbatim
from sbtc.Scripts.Preprocess.boilerplate import detect_boilerplate
from sbtc.Scripts.Preprocess.chunking import ChunkConfig, chunk_document, classify_document_details, extract_atoms, extract_paragraphs


DATASET = Path(__file__).resolve().parents[2] / "datacrawl/test.jsonl"


def sample_records() -> dict[str, dict]:
    selected: dict[str, dict] = {}
    with DATASET.open(encoding="utf-8") as stream:
        for raw in stream:
            record = json.loads(raw)
            text = record["text"]
            if "failure" not in selected and not record["success"]:
                selected["failure"] = record
            if "short_qa" not in selected and record["id"] == 925642:
                selected["short_qa"] = record
            if "long_qa" not in selected and record["id"] == 925414:
                selected["long_qa"] = record
            if "article" not in selected and record["id"] == 101063:
                selected["article"] = record
            if "headings" not in selected and record["id"] == 101260:
                selected["headings"] = record
            if "zh_headings" not in selected and record["id"] == 766450:
                selected["zh_headings"] = record
            if "zh_numbered_headings" not in selected and record["id"] == 766453:
                selected["zh_numbered_headings"] = record
            if "inline_brackets" not in selected and record["id"] == 885981:
                selected["inline_brackets"] = record
            if "single_line" not in selected and text and "\n" not in text:
                selected["single_line"] = record
            if "oversized" not in selected and any(len(line) > 1500 for line in text.splitlines()):
                selected["oversized"] = record
            if "giant_chinese" not in selected and record["id"] == 1429888:
                selected["giant_chinese"] = record
            if "fullwidth_period" not in selected and record["id"] == 884718:
                selected["fullwidth_period"] = record
            if "department_navigation" not in selected and record["id"] == 3003234:
                selected["department_navigation"] = record
            for name, doc_id in (
                ("clickbait_tail", 101154), ("hotline_tail", 103925),
                ("seo_tail", 2443608), ("navigation_tail", 2991145),
                ("audio_error", 942223),
            ):
                if name not in selected and record["id"] == doc_id:
                    selected[name] = record
            if len(selected) == 18:
                break
    expected = {
        "failure", "short_qa", "long_qa", "article", "headings", "zh_headings",
        "zh_numbered_headings", "inline_brackets", "single_line", "oversized",
        "giant_chinese", "clickbait_tail", "hotline_tail", "seo_tail",
        "navigation_tail", "audio_error", "fullwidth_period", "department_navigation",
    }
    if len(selected) != len(expected):
        raise AssertionError(f"Missing test.jsonl samples: {expected - selected.keys()}")
    return selected


class ChunkComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = sample_records()
        cls.config = ChunkConfig()

    def test_failed_crawl_is_reported_without_chunks(self) -> None:
        output = chunk_document(self.records["failure"], self.config)
        self.assertEqual(output["status"], "skipped")
        self.assertEqual(output["doc_id"], self.records["failure"]["id"])
        self.assertEqual(output["parents"], [])
        self.assertEqual(output["children"], [])

    def test_short_qa_remains_one_parent_and_child(self) -> None:
        record = self.records["short_qa"]
        output = chunk_document(record, self.config)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["doc_type"], "qa")
        self.assertIn(output["classification_reason"], ("qa_marker", "qa_domain"))
        self.assertIn(output["classification_confidence"], ("high", "medium"))
        source = clean_to_verbatim(record["text"])
        self.assertLessEqual(output["source_units"], self.config.max_units)
        self.assertEqual(len(output["parents"]), 1)
        self.assertEqual(len(output["children"]), 1)
        self.assertEqual(output["children"][0]["chunk_text"], source)

    def test_long_qa_keeps_all_children_within_natural_boundaries(self) -> None:
        record = self.records["long_qa"]
        source = clean_to_verbatim(record["text"])
        boundaries = extract_atoms(source, self.config)
        starts = {item.start for item in boundaries}
        ends = {item.end for item in boundaries}
        output = chunk_document(record, self.config)
        self.assertGreater(output["source_units"], self.config.max_units)
        self.assertGreater(len(output["children"]), 1)
        for child in output["children"]:
            self.assertIn(child["start_char"], starts)
            self.assertIn(child["end_char"], ends)

    def test_classification_records_which_rule_matched(self) -> None:
        qa = self.records["short_qa"]
        article = self.records["article"]
        short = self.records["single_line"]
        self.assertEqual(classify_document_details(clean_to_verbatim(qa["text"]), qa["url"]), ("qa", "qa_marker", "high"))
        self.assertEqual(classify_document_details(clean_to_verbatim(article["text"]), article["url"]), ("article", "long_text", "medium"))
        self.assertEqual(classify_document_details(clean_to_verbatim(short["text"]), short["url"]), ("other", "fallback", "low"))
        self.assertEqual(classify_document_details(clean_to_verbatim(short["text"]), "https://www.120ask.com/a"), ("qa", "qa_domain", "medium"))
        self.assertEqual(classify_document_details(clean_to_verbatim(short["text"]) + "\n", short["url"]), ("article", "multiline", "low"))

    def test_article_children_are_exact_contiguous_slices_of_cleaned_source(self) -> None:
        record = self.records["article"]
        source = clean_to_verbatim(record["text"])
        output = chunk_document(record, self.config)
        parents = {parent["parent_id"]: parent for parent in output["parents"]}
        self.assertGreater(len(output["children"]), 1)
        self.assertEqual(output["coverage"]["non_whitespace_covered"], output["coverage"]["non_whitespace_total"])
        for order, child in enumerate(output["children"]):
            self.assertEqual(child["doc_id"], record["id"])
            self.assertEqual(child["chunk_order"], order)
            self.assertEqual(child["chunk_text"], source[child["start_char"]:child["end_char"]])
            parent = parents[child["parent_id"]]
            self.assertLessEqual(parent["start_char"], child["start_char"])
            self.assertLessEqual(child["end_char"], parent["end_char"])

    def test_oversized_chinese_paragraph_uses_natural_boundaries(self) -> None:
        record = self.records["giant_chinese"]
        source = clean_to_verbatim(record["text"])
        output = chunk_document(record, self.config)
        self.assertGreater(len(output["children"]), 3)
        self.assertFalse(any(child["oversized_reason"] == "oversized_paragraph" for child in output["children"]))
        for child in output["children"]:
            self.assertEqual(child["chunk_text"], source[child["start_char"]:child["end_char"]])

    def test_sentence_atoms_do_not_split_decimal_domain_or_abbreviation(self) -> None:
        record = dict(
            self.records["single_line"],
            text='Liều 2.5 mg. Xem example.com/path. BS. An nói: “Ổn.” Sau đó。下一句？',
        )
        source = clean_to_verbatim(record["text"])
        atoms = extract_atoms(source, self.config)
        self.assertEqual(
            [atom.text for atom in atoms],
            ['Liều 2.5 mg.', 'Xem example.com/path.', 'BS. An nói: “Ổn.”', 'Sau đó。', '下一句？'],
        )
        for atom in atoms:
            self.assertEqual(atom.text, source[atom.start:atom.end])

    def test_fullwidth_period_is_a_natural_chinese_boundary(self) -> None:
        output = chunk_document(self.records["fullwidth_period"], self.config)
        self.assertFalse(any(child["unit_count"] > self.config.max_units for child in output["children"]))

    def test_short_heading_is_not_orphaned_at_end_of_previous_chunk(self) -> None:
        output = chunk_document(self.records["article"], self.config)
        orphan_headings = {"Chanh", "Mía", "Đừng quên tẩy tế bào chết"}
        self.assertFalse(any(child["chunk_text"].splitlines()[-1].strip() in orphan_headings for child in output["children"]))

    def test_output_is_deterministic(self) -> None:
        record = self.records["single_line"]
        self.assertEqual(chunk_document(record, self.config), chunk_document(record, self.config))

    def test_all_four_strategies_preserve_source_coverage(self) -> None:
        record = self.records["article"]
        for strategy in ("basic", "structure", "adaptive", "hybrid"):
            with self.subTest(strategy=strategy):
                output = chunk_document(record, self.config, strategy=strategy)
                self.assertEqual(output["coverage"]["non_whitespace_covered"], output["coverage"]["non_whitespace_total"])
                self.assertEqual(len({child["chunk_id"] for child in output["children"]}), len(output["children"]))

    def test_hybrid_records_overlap_or_explicit_boundary_exception(self) -> None:
        output = chunk_document(self.records["article"], self.config)
        previous_by_parent = {}
        positive = 0
        eligible = 0
        for child in output["children"]:
            previous = previous_by_parent.get(child["parent_id"])
            if previous is not None:
                eligible += 1
                positive += child["overlap_units"] > 0
                self.assertTrue(child["overlap_units"] > 0 or child["overlap_exception"])
                self.assertLessEqual(child["unit_count"], self.config.max_units)
            previous_by_parent[child["parent_id"]] = child
        self.assertGreater(eligible, 0)
        self.assertGreater(positive / eligible, 0.95)

    def test_every_short_hybrid_chunk_has_a_reason(self) -> None:
        for name in ("article", "short_qa", "headings", "giant_chinese"):
            output = chunk_document(self.records[name], self.config)
            for child in output["children"]:
                if child["unit_count"] < 100:
                    self.assertIsInstance(child["short_chunk_reason"], str)
                    self.assertTrue(child["short_chunk_reason"])

    def test_high_confidence_boilerplate_is_excluded_as_exact_spans(self) -> None:
        expected_rules = {
            "clickbait_tail": "related_arrow_tail",
            "hotline_tail": "booking_contact_tail",
            "seo_tail": "related_content_tail",
            "navigation_tail": "alphabetical_navigation_tail",
            "audio_error": "unsupported_audio_line",
            "department_navigation": "department_navigation_block",
        }
        for name, rule_id in expected_rules.items():
            with self.subTest(name=name):
                record = self.records[name]
                source = clean_to_verbatim(record["text"])
                spans = detect_boilerplate(source, record["url"])
                self.assertIn(rule_id, {span["rule_id"] for span in spans})
                output = chunk_document(record, self.config)
                self.assertIn(rule_id, {span["rule_id"] for span in output["excluded_spans"]})
                for span in output["excluded_spans"]:
                    self.assertEqual(span["text"], source[span["start_char"]:span["end_char"]])
                    self.assertFalse(span["retrieval_eligible"])

    def test_mixed_seo_and_audio_documents_keep_valid_prefix_indexed(self) -> None:
        for name, required_text, forbidden_text in (
            ("seo_tail", "食管裂孔疝能活多长时间", "其他人还在看"),
            ("audio_error", "女儿不好好吃饭怎么办", "您的浏览器不支持 audio 元素"),
        ):
            with self.subTest(name=name):
                output = chunk_document(self.records[name], self.config)
                indexed = "\n".join(child["chunk_text"] for child in output["children"])
                self.assertIn(required_text, indexed)
                self.assertNotIn(forbidden_text, indexed)
                self.assertEqual(output["coverage"]["non_whitespace_covered"], output["coverage"]["non_whitespace_total"])

    def test_structure_strategy_preserves_more_headings_than_basic(self) -> None:
        record = self.records["zh_numbered_headings"]
        basic = chunk_document(record, self.config, strategy="basic")
        structure = chunk_document(record, self.config, strategy="structure")
        self.assertLess(basic["structural_boundary_rate"], structure["structural_boundary_rate"])

    def test_numbered_sentence_is_body_not_heading(self) -> None:
        source = clean_to_verbatim(self.records["headings"]["text"])
        paragraphs = extract_paragraphs(source)
        self.assertTrue(any(item.text.startswith("7. Dưỡng sinh") and item.role == "body" for item in paragraphs))

    def test_inline_bracket_label_is_body_not_heading(self) -> None:
        source = clean_to_verbatim(self.records["inline_brackets"]["text"])
        paragraphs = extract_paragraphs(source)
        self.assertTrue(any(item.text.startswith("【救饥】采嫩叶") and item.role == "body" for item in paragraphs))

    def test_chinese_article_with_headings_keeps_parent_child_containment(self) -> None:
        output = chunk_document(self.records["zh_headings"], self.config)
        parents = {item["parent_id"]: item for item in output["parents"]}
        self.assertGreater(len(parents), 1)
        for child in output["children"]:
            parent = parents[child["parent_id"]]
            self.assertLessEqual(parent["start_char"], child["start_char"])
            self.assertLessEqual(child["end_char"], parent["end_char"])

    def test_empty_success_record_is_skipped(self) -> None:
        record = dict(self.records["failure"], success=True)
        output = chunk_document(record, self.config)
        self.assertEqual(output["status"], "skipped")
        self.assertEqual(output["reason"], "empty_text")


if __name__ == "__main__":
    unittest.main()
