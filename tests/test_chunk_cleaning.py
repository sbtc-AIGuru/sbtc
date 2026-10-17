"""Cleaning regression tests sourced exclusively from datacrawl/test.jsonl.

Markup/error cases wrap original snippets in memory; medical content is never
invented and the input file is never modified.
"""

from __future__ import annotations

import hashlib
import copy
import html
import json
import re
from pathlib import Path
import unittest

from sbtc.Scripts.Clawler import verbatim
from sbtc.Scripts.Preprocess.chunking import ChunkConfig, chunk_document
from sbtc.Scripts.Preprocess.chunk_audit import _check_record


DATASET = Path(__file__).resolve().parents[2] / "datacrawl/test.jsonl"


def load_records() -> dict[int, dict]:
    wanted = {118639, 1040581, 1032046, 2066978, 115283, 104719, 766444, 103925, 204811}
    records = {}
    with DATASET.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["id"] in wanted:
                records[row["id"]] = row
            if records.keys() == wanted:
                break
    if records.keys() != wanted:
        raise AssertionError(f"Missing dataset fixtures: {wanted - records.keys()}")
    return records


class ChunkCleaningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_records()
        cls.label = cls.records[118639]["text"].splitlines()[0].strip()
        cls.comparison = next(line.strip() for line in cls.records[118639]["text"].splitlines() if "< 300 ml" in line)

    def test_report_is_deterministic_and_matches_string_api(self):
        source = self.records[118639]["text"]
        cleaned, report = verbatim.clean_with_report(source)
        self.assertEqual(cleaned, verbatim.clean_to_verbatim(source))
        self.assertEqual((cleaned, report), verbatim.clean_with_report(source))
        self.assertEqual(report["version"], verbatim.CLEANER_VERSION)
        self.assertEqual(report["input_sha256"], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(report["output_sha256"], hashlib.sha256(cleaned.encode()).hexdigest())
        self.assertEqual(report["input_chars"], len(source))
        self.assertEqual(report["output_chars"], len(cleaned))
        self.assertTrue(all(type(value) is int and value >= 0 for value in report["actions"].values()))

    def test_html_preserves_math_and_paragraph_boundaries(self):
        wrapped = f'<p>{html.escape(self.label)}</p><p>{html.escape(self.comparison)}</p>'
        cleaned, report = verbatim.clean_with_report(wrapped)
        self.assertEqual(cleaned, self.label + "\n\n" + self.comparison)
        self.assertGreater(report["actions"].get("html_tag", 0), 0)
        self.assertEqual(verbatim.clean_to_verbatim(self.label + "<div>" + self.comparison + "</div>"), self.label + "\n\n" + self.comparison)

    def test_image_alt_is_read_before_stripping_tags(self):
        wrapped = f'<img src="https://example.invalid/a.png" alt="{html.escape(self.label, quote=True)}">'
        self.assertEqual(verbatim.clean_to_verbatim(wrapped), self.label)

    def test_incomplete_script_keeps_source_and_warns(self):
        cleaned, report = verbatim.clean_with_report("<script>" + self.label)
        self.assertIn(self.label, cleaned)
        self.assertTrue(report["warnings"])

    def test_entities_decode_two_layers_and_preserve_unknown(self):
        encoded = html.escape(html.escape(self.comparison))
        cleaned, report = verbatim.clean_with_report(encoded)
        self.assertEqual(cleaned, self.comparison)
        self.assertEqual(report["actions"].get("html_entity_pass"), 2)
        self.assertEqual(verbatim.clean_to_verbatim(self.label + " &unknownentity;"), self.label + " &unknownentity;")

    def test_real_medical_multiplication_is_not_formatting(self):
        self.assertIn("8*12", verbatim.clean_to_verbatim(self.records[1040581]["text"]))

    def test_nested_link_labels_and_parentheses_keep_visible_text(self):
        label = self.label + " [" + self.label + "]"
        self.assertEqual(verbatim.clean_to_verbatim(f'[{label}](https://example.invalid/a(b(c)))'), label)
        self.assertEqual(verbatim.clean_to_verbatim(f'[**{self.label}**](https://example.invalid/a "title (x)")'), self.label)

    def test_real_nested_image_link_has_only_its_visible_alt(self):
        match = re.search(r'\[!\[([^\]\n]*)\]\([^\n]*\)\]\([^\n]*\)', self.records[204811]["text"])
        self.assertIsNotNone(match)
        self.assertEqual(verbatim.clean_to_verbatim(match.group(0)), match.group(1))

    def test_reference_links_require_matching_definition(self):
        wrapped = f'[{self.label}][ref]\n[ref]: https://example.invalid/a'
        self.assertEqual(verbatim.clean_to_verbatim(wrapped), self.label)
        citation = re.search(r'\[[^\]\n]+\]\[2,5\]', self.records[2066978]["text"]).group()
        self.assertEqual(verbatim.clean_to_verbatim(citation), citation)
        self.assertEqual(verbatim.clean_to_verbatim(f'[{self.label}][missing]'), f'[{self.label}][missing]')

    def test_ambiguous_plain_text_parenthesis_is_not_a_link_target(self):
        unit = re.search(r"\bml\b", self.comparison).group()
        literal = f"[{unit}]({unit})"
        self.assertEqual(verbatim.clean_to_verbatim(literal), literal)
        self.assertEqual(verbatim.clean_to_verbatim(f"[{self.label}](/article)"), self.label)

    def test_bare_url_preserves_adjacent_punctuation_and_chinese(self):
        label = self.records[766444]["text"].splitlines()[0].strip()
        self.assertEqual(verbatim.clean_to_verbatim('https://example.invalid/a。' + label), '。' + label)
        self.assertEqual(verbatim.clean_to_verbatim('https://example.invalid/a). ' + self.label), '). ' + self.label)
        self.assertEqual(verbatim.clean_to_verbatim('data:image/png;base64,AAAA。' + label), '。' + label)

    def test_malformed_link_keeps_label_and_following_source(self):
        source = f'[{self.label}](https://example.invalid/a\n{self.comparison}'
        cleaned, report = verbatim.clean_with_report(source)
        self.assertIn(self.label, cleaned)
        self.assertIn(self.comparison, cleaned)
        self.assertTrue(report["warnings"])

    def test_code_content_and_literal_symbols_are_preserved(self):
        payload = "**" + self.label + "** https://example.invalid/a"
        tick = chr(96)
        self.assertEqual(verbatim.clean_to_verbatim(tick + payload + tick), payload)
        self.assertEqual(verbatim.clean_to_verbatim(tick * 3 + "\n" + payload + "\n" + tick * 3), payload)
        self.assertEqual(verbatim.clean_to_verbatim("\\*" + self.label + "\\*"), "*" + self.label + "*")
        self.assertEqual(verbatim.clean_to_verbatim("_**" + self.label + "**_"), self.label)
        self.assertEqual(verbatim.clean_to_verbatim(tick + self.label), tick + self.label)

    def test_table_delimiters_are_removed_only_in_recognized_tables(self):
        table = f"| {self.label} | {self.label} |\n| :--- | ---: |\n| {self.label} | {self.label} |"
        row = self.label + " " + self.label
        self.assertEqual(verbatim.clean_to_verbatim(table), row + "\n" + row)

    def test_pipe_outside_table_and_leading_comparison_are_kept(self):
        literal = self.label + "|" + self.label
        self.assertEqual(verbatim.clean_to_verbatim(literal), literal)
        self.assertEqual(verbatim.clean_to_verbatim("> 8*12 " + self.label), "> 8*12 " + self.label)

    def test_unicode_controls_never_merge_tokens(self):
        source = "\ufeff" + self.label + "\x00" + self.label + "\u200d\ufeff\ufffd"
        cleaned, report = verbatim.clean_with_report(source)
        self.assertEqual(cleaned, self.label + " " + self.label + "\u200d\ufeff\ufffd")
        self.assertTrue(report["warnings"])
        invisible = next(line.strip() for line in self.records[115283]["text"].splitlines() if "\u00ad" in line)
        self.assertEqual(verbatim.clean_to_verbatim(invisible), invisible.replace("\u00ad", ""))

    def test_unicode_spaces_and_fullwidth_punctuation(self):
        self.assertEqual(verbatim.clean_to_verbatim(self.label + "\u202f\u205f" + self.label), self.label + " " + self.label)
        line = next(line.strip() for line in self.records[766444]["text"].splitlines() if "：" in line)
        self.assertEqual(verbatim.clean_to_verbatim(line), line)

    def test_known_ui_is_exact_and_unknown_entities_are_retained(self):
        self.assertEqual(verbatim.clean_to_verbatim("Kích thước chữ\nMặc định\nLớn hơn\n" + self.label), self.label)
        self.assertEqual(verbatim.clean_to_verbatim(self.label + " &notarealentity;"), self.label + " &notarealentity;")

    def test_document_report_and_chunks_share_one_clean_source(self):
        record = self.records[118639]
        source, report = verbatim.clean_with_report(record["text"])
        output = chunk_document(record)
        self.assertEqual(output["cleaning"], report)
        self.assertEqual(output["raw_sha256"], report["input_sha256"])
        self.assertEqual(output["source_sha256"], report["output_sha256"])
        for child in output["children"]:
            self.assertEqual(child["doc_id"], record["id"])
            self.assertEqual(child["chunk_text"], source[child["start_char"]:child["end_char"]])
        output["input_line"] = 1
        self.assertEqual(_check_record(record, output, 1, ChunkConfig()), [])

    def test_empty_after_cleaning_retains_report_for_audit(self):
        record = dict(self.records[118639], text="[](https://example.invalid/a)")
        output = chunk_document(record)
        self.assertEqual(output["reason"], "empty_after_cleaning")
        self.assertEqual(output["cleaning"]["output_chars"], 0)
        output["input_line"] = 1
        self.assertEqual(_check_record(record, output, 1, ChunkConfig()), [])

    def test_markup_only_records_do_not_produce_zero_content_chunks(self):
        for markup in (chr(96) * 3 + "\n***\n| --- |", "https://example.invalid/a."):
            with self.subTest(markup=markup):
                record = dict(self.records[118639], text=markup)
                output = dict(chunk_document(record), input_line=1)
                self.assertEqual(output.get("reason"), "empty_after_cleaning")
                self.assertEqual(output["children"], [])
                self.assertEqual(_check_record(record, output, 1, ChunkConfig()), [])

    def test_audit_rejects_report_tampering_and_unknown_version(self):
        record = self.records[118639]
        output = dict(chunk_document(record), input_line=1)
        changed = copy.deepcopy(output)
        changed["cleaning"] = {"version": "unknown"}
        self.assertTrue(any("cleaner version" in error for error in _check_record(record, changed, 1, ChunkConfig())))
        changed = copy.deepcopy(output)
        changed["cleaning"]["actions"]["line_whitespace"] = True
        self.assertTrue(any("cleaning report" in error for error in _check_record(record, changed, 1, ChunkConfig())))

    def test_dosage_interval_and_intra_word_underscore_are_preserved(self):
        self.assertIn("每天3~6餐", verbatim.clean_to_verbatim(self.records[1032046]["text"]))
        literal = self.label + "_" + self.label
        self.assertEqual(verbatim.clean_to_verbatim(literal), literal)

    def test_literal_protection_does_not_collide_with_original_characters(self):
        source = "\ue0000\ue000" + "\\*" + self.label + "\\*"
        self.assertEqual(verbatim.clean_to_verbatim(source), "\ue0000\ue000*" + self.label + "*")
        escaped = "\\*" + self.label + "\\*"
        self.assertEqual(verbatim.remove_link_targets(escaped), escaped)
        tick = chr(96)
        self.assertEqual(verbatim.clean_to_verbatim("\ufeff" + tick * 3 + "\n" + self.label + "\n" + tick * 3), self.label)

    def test_failed_records_skip_cleaning_and_wrong_types_are_rejected(self):
        output = chunk_document(dict(self.records[118639], success=False))
        self.assertNotIn("cleaning", output)
        self.assertEqual(output["reason"], "crawl_failed")
        with self.assertRaises(TypeError):
            verbatim.clean_with_report(self.records[118639])
        with self.assertRaises(ValueError):
            chunk_document(dict(self.records[118639], id=True))

    def test_ui_near_match_and_unknown_html_are_preserved(self):
        near_match = "Kích thước chữ\n" + self.label + "\nLớn hơn"
        self.assertEqual(verbatim.clean_to_verbatim(near_match), near_match)
        wrapped = "<biomarker>" + self.label + "</biomarker>"
        self.assertEqual(verbatim.clean_to_verbatim(wrapped), wrapped)
        cleaned, report = verbatim.clean_with_report("<br" + self.label)
        self.assertIn(self.label, cleaned)
        self.assertTrue(report["warnings"])


if __name__ == "__main__":
    unittest.main()
