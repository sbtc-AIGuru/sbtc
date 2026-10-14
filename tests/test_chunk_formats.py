"""Format-aware regressions from the immutable data_final/test_20k.jsonl sample.

The medical text comes from real records, rather than fabricated narratives.
Metadata tampering cases only mutate derived chunk output or schema fields.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unittest

from sbtc.Scripts.Clawler.verbatim import clean_with_report
from sbtc.Scripts.Preprocess.chunk_audit import _check_record
from sbtc.Scripts.Preprocess.chunking import ChunkConfig, chunk_document, count_units
from sbtc.Scripts.Preprocess.format_profiles import analyse_format


DATASET = Path(__file__).resolve().parents[2] / "data_final/test_20k.jsonl"
DATASET_SHA256 = "9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43"
REVIEW_IDS = {
    211401, 6333519, 5714388, 6480634, 7147848, 269380, 1067218,
    2335124, 279805, 5846763, 7156587, 6248072, 4265827, 4271202,
    264212, 6954391, 1128713, 218831, 6329186, 7139291, 1138672, 5180531, 5294437, 7286850,
    283585, 263670, 259400, 5467809, 2531165, 4050109, 3078554,
    223012, 244904,
}
QUALITY_RECORD_IDS = {
    543907, 1309894, 5756127, 6269502, 6884288, 529733, 1100056, 4057861, 4107923,
}
ERROR_LINE_NUMBERS = {543907: 12129, 1309894: 16904}
PROFILES = {
    "narrative_article", "research_abstract", "qa", "disease_drug_catalogue",
    "tcm_book", "structured_list", "generic",
}


def fixture_records(ids: set[int]) -> dict[int, dict]:
    """Load selected records from the approved test source and verify its identity."""
    records = {}
    digest = hashlib.sha256()
    with DATASET.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            record = json.loads(raw)
            if record["id"] in ids:
                if record["id"] in records:
                    raise AssertionError(f"Duplicate fixture id {record['id']}")
                records[record["id"]] = record
    if digest.hexdigest() != DATASET_SHA256:
        raise AssertionError("Approved test_20k.jsonl content changed")
    if ids - records.keys():
        raise AssertionError(f"Missing reviewed records: {ids - records.keys()}")
    return records


def review_records() -> dict[int, dict]:
    return fixture_records(REVIEW_IDS)


def fixture_line_numbers(ids: set[int]) -> dict[int, int]:
    line_numbers = {}
    with DATASET.open(encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, 1):
            doc_id = json.loads(raw)["id"]
            if doc_id in ids and doc_id not in line_numbers:
                line_numbers[doc_id] = line_number
    if ids - line_numbers.keys():
        raise AssertionError(f"Missing fixture line numbers: {ids - line_numbers.keys()}")
    return line_numbers


class FormatChunkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = review_records()
        cls.quality_records = fixture_records(QUALITY_RECORD_IDS)
        cls.sources = {
            doc_id: clean_with_report(record["text"])[0]
            for doc_id, record in cls.records.items()
        }
        cls.quality_sources = {
            doc_id: clean_with_report(record["text"])[0]
            for doc_id, record in cls.quality_records.items()
        }
        cls.config = ChunkConfig()

    def output(self, doc_id: int) -> dict:
        return chunk_document(self.records[doc_id], self.config, strategy="format")

    def quality_output(self, doc_id: int) -> dict:
        return chunk_document(self.quality_records[doc_id], self.config, strategy="format")

    def assert_no_boundary_inside(self, output: dict, start: int, end: int) -> None:
        for child in output["children"]:
            for key in ("start_char", "end_char"):
                position = child[key]
                self.assertFalse(
                    start < position < end,
                    f"doc {output['doc_id']} child {child['chunk_order']} {key} "
                    f"{position} cuts reviewed source span [{start}, {end})",
                )

    def assert_expression_intact(self, doc_id: int, expression: str) -> None:
        source = self.sources[doc_id]
        output = self.output(doc_id)
        matches = list(re.finditer(re.escape(expression), source))
        self.assertTrue(matches, f"Reviewed expression absent: {doc_id} {expression}")
        for match in matches:
            self.assert_no_boundary_inside(output, match.start(), match.end())
            self.assertTrue(any(
                child["start_char"] <= match.start() < match.end() <= child["end_char"]
                for child in output["children"]
            ), f"Protected medical expression was excluded: {doc_id} {expression}")

    def test_reviewed_records_keep_original_ids_urls_and_cleaned_slices(self) -> None:
        for doc_id, record in self.records.items():
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                source = self.sources[doc_id]
                self.assertEqual(output["doc_id"], record["id"])
                self.assertIs(type(output["doc_id"]), int)
                self.assertEqual(output["url"], record["url"])
                self.assertEqual(output["status"], "ok")
                parents = {parent["parent_id"]: parent for parent in output["parents"]}
                for order, child in enumerate(output["children"]):
                    self.assertEqual(child["doc_id"], doc_id)
                    self.assertEqual(child["chunk_order"], order)
                    start, end = child["start_char"], child["end_char"]
                    self.assertEqual(child["chunk_text"], source[start:end])
                    parent = parents[child["parent_id"]]
                    self.assertLessEqual(parent["start_char"], start)
                    self.assertLessEqual(end, parent["end_char"])
                self.assertEqual(
                    output["coverage"]["non_whitespace_covered"],
                    sum(not char.isspace() for char in source),
                )

    def test_format_metadata_is_evidenced_and_children_keep_context_roles(self) -> None:
        for doc_id in (6333519, 2335124, 279805, 4271202, 6248072, 264212):
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                source = self.sources[doc_id]
                self.assertIn(output["profile"], PROFILES)
                self.assertEqual(output["profile_version"], "format-v2")
                self.assertIn(output["format_confidence"], ("high", "medium", "low"))
                self.assertTrue(output["format_evidence"])
                self.assertIsInstance(output["source_language"], str)
                self.assertTrue(output["atom_spans"])
                for atom in output["atom_spans"]:
                    self.assertGreaterEqual(atom["start_char"], 0)
                    self.assertLess(atom["start_char"], atom["end_char"])
                    self.assertLessEqual(atom["end_char"], len(source))
                    self.assertTrue(atom["role"])
                    self.assertTrue(atom["boundary_type"])
                for child in output["children"]:
                    self.assertEqual(child["profile"], output["profile"])
                    self.assertTrue(child["section_roles"])
                    self.assertTrue(child["content_languages"])
                    self.assertTrue(child["boundary_reason"])
                    self.assertIn("protected_span_checks", child)

    def test_numeric_decimal_comma_is_not_a_chunk_boundary(self) -> None:
        self.assert_expression_intact(211401, "37,5")

    def test_randomisation_ratio_is_not_split_at_colon(self) -> None:
        self.assert_expression_intact(6333519, "(1:1)")

    def test_currency_thousands_separator_is_not_split(self) -> None:
        self.assert_expression_intact(5714388, "$10,100")

    def test_french_and_spanish_decimal_comma_is_preserved(self) -> None:
        self.assert_expression_intact(6480634, "11,6")

    def test_balanced_statistical_expression_is_not_split_at_colon_or_semicolon(self) -> None:
        source = self.sources[7147848]
        start = source.index("(ES:")
        end = source.index(")", start) + 1
        self.assert_no_boundary_inside(self.output(7147848), start, end)

    def test_sentence_that_fits_budget_remains_whole_even_when_overlap_is_long(self) -> None:
        source = self.sources[6333519]
        start = source.index("A centralised randomisation used")
        end = source.index("analogues only.", start) + len("analogues only.")
        self.assertGreater(count_units(source[start:end]), 50)
        self.assertLessEqual(count_units(source[start:end]), self.config.max_units)
        self.assert_no_boundary_inside(self.output(6333519), start, end)

    def test_scientific_abbreviations_do_not_end_a_chunk_mid_sentence(self) -> None:
        for doc_id, abbreviation, continuation in (
            (5180531, "Koes et al.", "[33] reviewed the randomized trials"),
            (5294437, "and i.v.", "Nytroglicerin"),
            (7286850, "platform vs.", "laparoscopic"),
        ):
            with self.subTest(doc_id=doc_id):
                source = self.sources[doc_id]
                start = source.index(abbreviation)
                body_start = source.index(continuation, start)
                output = self.output(doc_id)
                self.assertFalse(any(child["chunk_text"].rstrip().endswith(abbreviation) for child in output["children"]))
                self.assertTrue(any(child["start_char"] <= start and child["end_char"] > body_start for child in output["children"]))

    def test_narrative_colon_label_is_with_its_following_body(self) -> None:
        source = self.sources[269380]
        label = "Cảm giác tội lỗi:"
        start = source.index(label)
        following_body = source.index("Tích cực độc hại sẽ khiến", start)
        output = self.output(269380)
        self.assertFalse(any(child["chunk_text"].rstrip().endswith(label) for child in output["children"]))
        self.assertTrue(any(
            child["start_char"] <= start and child["end_char"] > following_body
            for child in output["children"]
        ))

    def test_lead_in_sentence_inside_a_long_paragraph_is_not_a_dangling_chunk_end(self) -> None:
        for doc_id, lead_in in (
            (223012, "Dưới đây là một số công dụng vô cùng tiêu biểu có thể kể tới của sản phẩm này:"),
            (244904, "Ở trẻ nhỏ có hệ miễn dịch suy yếu, bé hay bị ốm do các nguyên nhân sau:"),
        ):
            with self.subTest(doc_id=doc_id):
                source = self.sources[doc_id]
                start = source.index(lead_in)
                body_start = start + len(lead_in)
                while source[body_start].isspace():
                    body_start += 1
                self.assertLess(body_start, len(source), "Fixture must contain the promised following body")
                output = self.output(doc_id)
                self.assertFalse(any(child["chunk_text"].rstrip().endswith((":", "："))
                                     for child in output["children"]))
                self.assertTrue(any(
                    child["start_char"] <= start and child["end_char"] > body_start
                    for child in output["children"]
                ))

    def test_qa_analysis_and_advice_labels_are_not_orphaned(self) -> None:
        output = self.output(1067218)
        source = self.sources[1067218]
        for label in ("病情分析：", "指导意见："):
            start = source.index(label)
            body_start = start + len(label)
            while source[body_start].isspace():
                body_start += 1
            self.assertFalse(any(child["chunk_text"].rstrip().endswith(label) for child in output["children"]))
            self.assertTrue(any(
                child["start_char"] <= start and child["end_char"] > body_start
                for child in output["children"]
            ))

    def test_qa_answer_context_references_source_question_without_rewriting_chunks(self) -> None:
        output = self.output(1067218)
        self.assertEqual(output["profile"], "qa")
        question_spans = [parent["question_span"] for parent in output["parents"] if parent.get("question_span")]
        self.assertTrue(question_spans, "Answer parents need source question context")
        for span in question_spans:
            self.assertLess(span["start_char"], span["end_char"])
            self.assertIn("糖尿病", self.sources[1067218][span["start_char"]:span["end_char"]])

    def test_patient_greeting_to_doctor_is_question_content(self) -> None:
        source = self.sources[1138672]
        start = source.index("你好，医生，我是一名高三的学生")
        first_answer = source.index("病情分析：")
        output = self.output(1138672)
        self.assertTrue(any(span["start_char"] <= start < span["end_char"] for span in output["question_spans"]))
        self.assertTrue(all(span["start_char"] >= first_answer for span in output["answer_spans"]))

    def test_explicit_doctor_bio_is_excluded_but_the_answer_is_indexed(self) -> None:
        source = self.sources[2335124]
        start = source.index("【医生信息】")
        end = source.index("【医生回复】")
        output = self.output(2335124)
        self.assertTrue(any(
            span["start_char"] <= start < end <= span["end_char"]
            for span in output["excluded_spans"]
        ))
        for child in output["children"]:
            self.assertFalse(max(start, child["start_char"]) < min(end, child["end_char"]))
        self.assertTrue(any("肠系膜脂肪炎的症状包括腹痛" in child["chunk_text"] for child in output["children"]))

    def test_excluded_navigation_has_source_provenance_and_high_confidence(self) -> None:
        for doc_id in (2335124, 4265827, 279805):
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                self.assertTrue(output["excluded_spans"])
                for span in output["excluded_spans"]:
                    self.assertEqual(span["doc_id"], doc_id)
                    self.assertIs(span["retrieval_eligible"], False)
                    self.assertEqual(span["confidence"], "high")
                    self.assertTrue(span["reason"])
                    self.assertTrue(span["rule_id"])
                    self.assertEqual(span["text"], self.sources[doc_id][span["start_char"]:span["end_char"]])

    def test_catalogue_toc_does_not_produce_heading_only_chunks(self) -> None:
        output = self.output(279805)
        self.assertEqual(output["profile"], "disease_drug_catalogue")
        toc_labels = {"Triệu chứng", "Nguyên nhân", "Nguy cơ", "Tìm hiểu chung"}
        self.assertFalse(any(child["chunk_text"].strip() in toc_labels for child in output["children"]))
        self.assertTrue(any("Viêm là một phần" in child["chunk_text"] for child in output["children"]))

    def test_title_and_date_between_catalogue_menus_are_context_metadata(self) -> None:
        output = self.output(279805)
        title = self.sources[279805].splitlines()[0]
        self.assertTrue(output.get("title_spans"))
        for child in output["children"]:
            self.assertNotEqual(child["chunk_text"].strip(), title)
            self.assertNotEqual(child["chunk_text"].strip(), title + "\n\n12/08/2025")

    def test_research_title_longer_than_120_characters_is_not_a_child_by_itself(self) -> None:
        source = self.sources[5846763]
        title = source.splitlines()[0]
        self.assertGreater(len(title), 120)
        output = self.output(5846763)
        self.assertEqual(output["profile"], "research_abstract")
        self.assertFalse(any(child["chunk_text"].strip() == title for child in output["children"]))

    def test_bilingual_abstract_has_distinct_language_regions_without_cross_overlap(self) -> None:
        source = self.sources[7156587]
        transition = source.index("目的:")
        output = self.output(7156587)
        languages = {span["language"] for span in output["content_language_spans"]}
        self.assertTrue({"en", "zh"}.issubset(languages))
        self.assertFalse(any(child["start_char"] < transition < child["end_char"] for child in output["children"]))
        self.assertTrue(any(child["start_char"] >= transition for child in output["children"]))
        for child in output["children"]:
            if child["start_char"] >= transition:
                self.assertIn("zh", child["content_languages"])

    def test_source_and_content_language_metadata_have_valid_source_offsets(self) -> None:
        for doc_id in (211401, 7156587, 6480634, 6329186, 6248072):
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                spans = output["content_language_spans"]
                self.assertTrue(spans)
                for span in spans:
                    self.assertGreaterEqual(span["start_char"], 0)
                    self.assertLess(span["start_char"], span["end_char"])
                    self.assertLessEqual(span["end_char"], len(self.sources[doc_id]))
                    self.assertIsInstance(span["language"], str)

    def test_romanian_names_and_serbian_diacritics_do_not_force_vietnamese(self) -> None:
        for doc_id in (6248072, 6329186, 7139291):
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                self.assertNotEqual(output["source_language"], "vi")
                self.assertNotIn("vi", {span["language"] for span in output["content_language_spans"]})

    def test_conference_proceedings_are_routed_by_entry_shape(self) -> None:
        output = self.output(6248072)
        self.assertEqual(output["profile"], "structured_list")
        source = self.sources[6248072]
        entries = list(re.finditer(r"(?<!\w)[OP]\d+\s+", source))
        self.assertGreater(len(entries), 20)
        for index, entry in enumerate(entries):
            end = entries[index + 1].start() if index + 1 < len(entries) else len(source)
            if count_units(source[entry.start():end]) <= self.config.max_units:
                trimmed_end = entry.start() + len(source[entry.start():end].rstrip())
                self.assert_no_boundary_inside(output, entry.start(), trimmed_end)

    def test_tcm_page_turn_arrows_are_not_indexed(self) -> None:
        output = self.output(4265827)
        self.assertEqual(output["profile"], "tcm_book")
        self.assertFalse(any("方向键翻页" in child["chunk_text"] for child in output["children"]))
        self.assertTrue(any("维生素B12" in child["chunk_text"] for child in output["children"]))

    def test_tcm_original_text_cross_references_keep_their_quoted_medical_content(self) -> None:
        output = self.output(4271202)
        source = self.sources[4271202]
        reference_start = source.index("原文 →")
        quotation_start = source.index("产后忿怒气逆", reference_start)
        self.assertTrue(any(
            child["start_char"] <= quotation_start < child["end_char"]
            for child in output["children"]
        ))
        self.assertTrue(any("quoted_snippet" in child["section_roles"] for child in output["children"]))

    def test_decimal_dose_line_is_not_an_enumerated_heading(self) -> None:
        source = self.sources[264212]
        position = source.index("24.7mg")
        output = self.output(264212)
        relevant = [atom for atom in output["atom_spans"] if atom["start_char"] <= position < atom["end_char"]]
        self.assertTrue(relevant)
        self.assertFalse(any(atom["role"] in ("heading", "title") for atom in relevant))
        self.assert_expression_intact(264212, "24.7mg")

    def test_cross_line_inline_anchor_parentheses_are_not_chunk_boundaries(self) -> None:
        for doc_id, expression in (
            (283585, "(\n\nMRSA\n\n)"),
            (263670, "(đặc biệt là\n\ntiêu chảy\n\n)"),
        ):
            with self.subTest(doc_id=doc_id):
                self.assert_expression_intact(doc_id, expression)

    def test_numeric_unit_guard_does_not_consume_first_letter_of_next_heading(self) -> None:
        source = self.sources[259400]
        heading_start = source.index("Gợi ý ghi nhớ:")
        number_start = source.rfind("2,2", 0, heading_start)
        self.assertGreaterEqual(number_start, 0)
        output = self.output(259400)
        relevant = [span for span in output["protected_spans"]
                    if span["start_char"] <= number_start < span["end_char"]]
        self.assertTrue(relevant)
        self.assertTrue(all(span["end_char"] <= number_start + len("2,2") for span in relevant))

    def test_broken_parenthesis_is_not_paired_with_an_unrelated_french_section(self) -> None:
        source = self.sources[5467809]
        opening = source.index("versions of this guideline (") + len("versions of this guideline ")
        first_section_end = source.index("\n\nRECOMMENDATIONS:", opening)
        output = self.output(5467809)
        self.assertFalse(any(
            span["kind"] == "bracket_expression" and span["start_char"] == opening
            and span["end_char"] > first_section_end
            for span in output["protected_spans"]
        ), "A damaged link parenthesis cannot protect thousands of characters across another abstract")

    def test_foreign_abstract_blocks_remain_unknown_until_language_evidence_exists(self) -> None:
        output = self.output(6480634)
        source = self.sources[6480634]
        for marker in ("RÉSULTATS::", "RESULTADOS::"):
            start = source.index(marker)
            span = next(span for span in output["content_language_spans"]
                        if span["start_char"] <= start < span["end_char"])
            self.assertNotEqual(span["language"], "en")
            self.assertIn(span["language"], ("und", "fr", "es"))

    def test_chinese_body_does_not_keep_unknown_language_of_its_short_title(self) -> None:
        output = self.output(4271202)
        first_body = self.sources[4271202].index("妇人之病")
        child = next(child for child in output["children"] if child["start_char"] <= first_body < child["end_char"])
        self.assertIn("zh", child["content_languages"])
        atoms = [atom for atom in output["atom_spans"] if atom["start_char"] <= first_body < atom["end_char"]]
        self.assertTrue(atoms)
        self.assertTrue(all(atom["language"] == "zh" for atom in atoms))

    def test_flattened_disease_table_rows_preserve_three_column_relationship(self) -> None:
        output = self.output(2531165)
        source = self.sources[2531165]
        self.assertIn("可能疾病 伴随症状 就诊科室", source)
        for row in (
            "口腔溃疡 嗳气时有腐败鸡蛋的气味容易上火 口腔科",
            "咽食管憩室 嗳气时有腐败鸡蛋的气味容易上火 口腔科",
        ):
            with self.subTest(row=row):
                start = source.index(row)
                end = start + len(row)
                self.assert_no_boundary_inside(output, start, end)
                atoms = [atom for atom in output["atom_spans"]
                         if atom["start_char"] <= start < end <= atom["end_char"]]
                self.assertTrue(atoms, "A table row needs one source atom")
                self.assertTrue(any(atom["role"] == "table_row" for atom in atoms))
                self.assertTrue(all(atom["unit_count"] <= self.config.max_units for atom in atoms))

    def test_drug_manufacturer_records_are_whole_and_do_not_form_one_unbounded_body_atom(self) -> None:
        output = self.output(4050109)
        self.assertEqual(output["profile"], "disease_drug_catalogue")
        source = self.sources[4050109]
        records = list(re.finditer(
            r"(?m)^阿司匹林肠溶片\n生产企业：[^\n]+\n批准字号：[^\n]+\n包装规格：[^\n]+", source,
        ))
        self.assertGreater(len(records), 5)
        for record in records[:3]:
            with self.subTest(start=record.start()):
                self.assert_no_boundary_inside(output, record.start(), record.end())
                atoms = [atom for atom in output["atom_spans"]
                         if atom["start_char"] <= record.start() < record.end() <= atom["end_char"]]
                self.assertTrue(atoms, "Manufacturer, registration and package belong to the same record")
                self.assertTrue(all(atom["unit_count"] <= self.config.max_units for atom in atoms),
                                "Many independent manufacturer records must not fuse into one oversized body")

    def test_drug_name_prefix_does_not_hide_dosage_or_adverse_effect_sections(self) -> None:
        output = self.output(4050109)
        labels = {span["label"] for span in output["section_spans"]}
        self.assertIn("阿司匹林肠溶片的副作用（不良反应）", labels)
        self.assertIn("阿司匹林肠溶片的用法用量", labels)

    def test_dense_icd_wiki_navigation_is_excluded_while_disease_body_stays_indexed(self) -> None:
        output = self.output(3078554)
        menu_marker = "国际疾病与相关健康问题统计分类第十版"
        self.assertTrue(any(menu_marker in span["text"] for span in output["excluded_spans"]))
        self.assertFalse(any(menu_marker in child["chunk_text"] for child in output["children"]))
        self.assertTrue(any("盘尾丝虫病是致盲的重要原因" in child["chunk_text"] for child in output["children"]))

    def test_tcm_formula_ingredients_and_doses_are_structural_records(self) -> None:
        output = self.output(4271202)
        source = self.sources[4271202]
        ingredients = "川芎（二钱） 白当归（四钱） 炙甘草（五分） 炒黑干姜（四分） 单桃仁（十粒，去皮尖）"
        start = source.index(ingredients)
        end = start + len(ingredients)
        self.assert_no_boundary_inside(output, start, end)
        atoms = [atom for atom in output["atom_spans"] if atom["start_char"] <= start < end <= atom["end_char"]]
        self.assertTrue(atoms)
        self.assertTrue(any(atom["role"] == "formula" for atom in atoms))
        self.assertTrue(all(atom["unit_count"] <= self.config.max_units for atom in atoms))

    def test_short_structured_abstract_preserves_one_complete_chunk(self) -> None:
        output = self.output(6954391)
        self.assertEqual(output["profile"], "research_abstract")
        self.assertEqual(len(output["children"]), 1)
        self.assertEqual(output["children"][0]["chunk_text"], self.sources[6954391])

    def assert_abstract_section_metadata(self, record: dict, required_labels: set[str]) -> dict:
        source = clean_with_report(record["text"])[0]
        output = chunk_document(record, self.config, strategy="format")
        spans = output["section_spans"]
        labels = {span["label"].upper() for span in spans}
        self.assertTrue(required_labels.issubset(labels))
        for span in spans:
            start, label_end, end = span["start_char"], span["label_end_char"], span["end_char"]
            self.assertGreaterEqual(start, 0)
            self.assertLess(start, label_end)
            self.assertLessEqual(label_end, end)
            self.assertLessEqual(end, len(source))
            self.assertEqual(source[start:label_end].strip().rstrip(":：").upper(), span["label"].upper())
        for child in output["children"]:
            expected = {span["label"].upper() for span in spans
                        if span["label"].upper() in required_labels
                        and max(child["start_char"], span["start_char"]) < min(child["end_char"], span["end_char"])}
            actual = {label.upper() for path in child["section_paths"] for label in path
                      if label.upper() in required_labels}
            self.assertEqual(actual, expected,
                             f"Child {child['chunk_order']} must describe all source abstract sections it intersects")
        return output

    def test_short_abstract_inline_labels_keep_all_section_metadata_in_one_chunk(self) -> None:
        for inline in (False, True):
            with self.subTest(inline=inline):
                record = dict(self.records[6954391])
                if inline:
                    # Preserve every clinical word while exercising source layout
                    # where section labels are inline rather than new paragraphs.
                    record["text"] = record["text"].replace("\n\n", " ")
                output = self.assert_abstract_section_metadata(
                    record, {"INTRODUCTION", "METHODS", "RESULTS", "CONCLUSION"},
                )
                self.assertEqual(len(output["children"]), 1)
                self.assertEqual(output["children"][0]["chunk_text"], clean_with_report(record["text"])[0])

    def test_long_abstract_inline_labels_attach_sections_to_each_intersecting_chunk(self) -> None:
        for inline in (False, True):
            with self.subTest(inline=inline):
                record = dict(self.records[7147848])
                if inline:
                    record["text"] = record["text"].replace("\n\n", " ")
                output = self.assert_abstract_section_metadata(record, {"OBJECTIVE", "METHODS", "RESULTS", "CONCLUSIONS"})
                self.assertGreater(len(output["children"]), 1)

    def test_lancet_trial_findings_interpretation_and_funding_are_not_labelled_methods(self) -> None:
        output = self.assert_abstract_section_metadata(
            self.records[6333519], {"BACKGROUND", "METHODS", "FINDINGS", "INTERPRETATION", "FUNDING"},
        )
        source = self.sources[6333519]
        ratio_start = source.index("(1:1)")
        self.assert_no_boundary_inside(output, ratio_start, ratio_start + len("(1:1)"))
        self.assertTrue(any("(1:1)" in child["chunk_text"] for child in output["children"]))

    def test_short_question_and_answer_preserve_one_complete_chunk(self) -> None:
        output = self.output(1128713)
        self.assertEqual(output["profile"], "qa")
        self.assertEqual(len(output["children"]), 1)
        self.assertEqual(output["children"][0]["chunk_text"], self.sources[1128713])

    def test_known_good_narrative_keeps_complete_sentences_and_coverage(self) -> None:
        output = self.output(218831)
        self.assertEqual(output["profile"], "narrative_article")
        self.assertGreater(len(output["children"]), 1)
        # The real source and baseline both end in "thuốc nhé!". A complete
        # sentence may end in an exclamation/question mark as well as a period.
        self.assertTrue(all(child["chunk_text"].rstrip().endswith((".", "!", "?")) for child in output["children"]))
        self.assertEqual(output["coverage"]["non_whitespace_total"], output["coverage"]["non_whitespace_covered"])

    def test_every_short_or_oversized_chunk_has_evidenced_reason(self) -> None:
        for doc_id in REVIEW_IDS:
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                for child in output["children"]:
                    if child["unit_count"] < 100:
                        self.assertTrue(child["short_chunk_reason"])
                        self.assertTrue(child["short_reason_evidence"])
                    if child["unit_count"] > self.config.max_units:
                        self.assertIn(child["oversized_reason"], ("oversized_sentence", "oversized_structural_atom", "oversized_unresolved"))
                    if child["overlap_units"] and not 30 <= child["overlap_units"] <= 50:
                        self.assertTrue(child["overlap_exception"])

    def test_known_crawl_error_placeholders_are_skipped_with_empty_text(self) -> None:
        for doc_id in (543907, 1309894):
            with self.subTest(doc_id=doc_id):
                record = self.quality_records[doc_id]
                self.assertTrue(record["success"])
                output = self.quality_output(doc_id)
                self.assertEqual(output["status"], "skipped")
                self.assertEqual(output["reason"], "crawl_error_placeholder")
                self.assertEqual(output["text"], "")
                self.assertEqual(output["parents"], [])
                self.assertEqual(output["children"], [])
                output["input_line"] = ERROR_LINE_NUMBERS[doc_id]
                self.assertEqual(_check_record(record, output, ERROR_LINE_NUMBERS[doc_id], self.config), [])

    def test_error_matcher_does_not_match_ordinary_medical_text(self) -> None:
        from sbtc.Scripts.Preprocess.format_profiles import is_crawl_error_placeholder

        self.assertFalse(is_crawl_error_placeholder(self.sources[211401]))

    def test_oversized_test_records_are_repaired_without_losing_source_or_protected_spans(self) -> None:
        split_seen = False
        line_numbers = fixture_line_numbers(set(QUALITY_RECORD_IDS))
        for doc_id in (5756127, 6269502, 6884288, 529733, 1100056, 4057861, 4107923):
            with self.subTest(doc_id=doc_id):
                record = self.quality_records[doc_id]
                source = self.quality_sources[doc_id]
                output = self.quality_output(doc_id)
                analysis = analyse_format(source, record["url"])
                self.assertTrue(output["children"])
                self.assertEqual(output["coverage"]["non_whitespace_total"], output["coverage"]["non_whitespace_covered"])
                for child in output["children"]:
                    split_seen |= bool(child.get("oversized_split_reasons"))
                    self.assertLessEqual(child["unit_count"], 500)
                    self.assertEqual(child["chunk_text"], source[child["start_char"]:child["end_char"]])
                    for span in analysis["protected_spans"]:
                        for boundary in (child["start_char"], child["end_char"]):
                            self.assertFalse(span["start_char"] < boundary < span["end_char"])
                output["input_line"] = line_numbers[doc_id]
                self.assertEqual(_check_record(record, output, line_numbers[doc_id], self.config), [])
        self.assertTrue(split_seen)

    def test_short_chunk_merge_helper_joins_adjacent_source_atoms_only_within_same_context(self) -> None:
        from sbtc.Scripts.Preprocess.format_chunking import _merge_short_children

        doc_id = 7156587
        source = self.sources[doc_id]
        analysis = analyse_format(source, self.records[doc_id]["url"])
        split_case = None
        for atom in analysis["atoms"]:
            for match in re.finditer(r"\s+", source[atom.start:atom.end]):
                split = atom.start + match.end()
                if not atom.start < split < atom.end:
                    continue
                left_units = count_units(source[atom.start:split])
                right_units = count_units(source[split:atom.end])
                if not (0 < left_units < 50 and 0 < right_units < 50):
                    continue
                if any(span["start_char"] < split < span["end_char"] for span in analysis["protected_spans"]):
                    continue
                split_case = atom, split
                break
            if split_case:
                break
        self.assertIsNotNone(split_case)
        atom, split = split_case

        def child(atom, start, end, order):
            paths = [[section["label"]] for section in analysis["section_spans"]
                     if max(start, section["start_char"]) < min(end, section["end_char"])]
            return {
                "chunk_id": f"{doc_id}:c:{order}:{start}:{end}:format-v2",
                "doc_id": doc_id, "chunk_order": order, "parent_id": f"{doc_id}:p:0",
                "start_char": start, "end_char": end, "chunk_text": source[start:end],
                "unit_count": count_units(source[start:end]), "profile": analysis["metadata"]["profile"],
                "section_roles": [atom.role], "section_paths": paths, "content_languages": [atom.language],
                "overlap_units": 0, "overlap_exception": "test_fixture_atom_boundary",
            }

        left, right = child(atom, atom.start, split, 0), child(atom, split, atom.end, 1)
        self.assertEqual(left["section_paths"], right["section_paths"])
        merged = _merge_short_children([left, right], source, self.config)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["start_char"], atom.start)
        self.assertEqual(merged[0]["end_char"], atom.end)
        self.assertEqual(merged[0]["chunk_text"], source[atom.start:atom.end])
        self.assertLess(merged[0]["unit_count"], 100)
        self.assertEqual(merged[0]["merge_reason"], "consecutive_short_chunks")

        right["parent_id"] = "different-parent"
        self.assertEqual(len(_merge_short_children([left, right], source, self.config)), 2)

    def test_format_output_is_deterministic(self) -> None:
        self.assertEqual(self.output(6333519), self.output(6333519))

    def test_failed_source_never_produces_format_chunks(self) -> None:
        record = dict(self.records[1128713], success=False)
        output = chunk_document(record, self.config, strategy="format")
        self.assertEqual(output["status"], "skipped")
        self.assertEqual(output["children"], [])
        self.assertEqual(output["parents"], [])
        self.assertEqual(output["text"], "")

    def test_invalid_id_does_not_replace_original_manifest_id(self) -> None:
        for invalid_id in (True, "1128713", 1128713.0, None):
            with self.subTest(invalid_id=invalid_id):
                record = dict(self.records[1128713], id=invalid_id)
                with self.assertRaises(ValueError):
                    chunk_document(record, self.config, strategy="format")

    def test_auditor_accepts_valid_format_output(self) -> None:
        for doc_id in (6333519, 2335124, 7156587, 6248072, 4265827):
            with self.subTest(doc_id=doc_id):
                output = self.output(doc_id)
                output["input_line"] = 1
                self.assertEqual(_check_record(self.records[doc_id], output, 1, self.config), [])

    def test_auditor_rejects_tampered_identity_source_or_format_metadata(self) -> None:
        record = self.records[6333519]
        output = self.output(6333519)
        output["input_line"] = 1
        mutations = {
            "document id": lambda result: result.update(doc_id=record["id"] + 1),
            "url": lambda result: result.update(url=self.records[6954391]["url"]),
            "source hash": lambda result: result.update(source_sha256="0" * 64),
            "child text": lambda result: result["children"][0].update(chunk_text=""),
            "chunk order": lambda result: result["children"][0].update(chunk_order=99),
            "profile version": lambda result: result.update(profile_version="unrecognised-version"),
            "language offset": lambda result: result["content_language_spans"][0].update(end_char=len(self.sources[6333519]) + 1),
        }
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                tampered = deepcopy(output)
                mutate(tampered)
                self.assertTrue(_check_record(record, tampered, 1, self.config), f"Auditor trusted tampered {name}")

    def test_auditor_detects_protected_cut_even_with_forged_atom_metadata(self) -> None:
        record = self.records[6333519]
        source = self.sources[6333519]
        output = self.output(6333519)
        output["input_line"] = 1
        cut = source.index("(1:1)") + 3
        original = next(child for child in output["children"] if child["start_char"] < cut < child["end_char"])
        left, right = deepcopy(original), deepcopy(original)
        left.update(end_char=cut, chunk_text=source[left["start_char"]:cut])
        right.update(start_char=cut, chunk_text=source[cut:right["end_char"]], overlap_units=0, overlap_exception="forged_boundary")
        left["unit_count"] = count_units(left["chunk_text"])
        right["unit_count"] = count_units(right["chunk_text"])
        index = output["children"].index(original)
        output["children"][index:index + 1] = [left, right]
        for order, child in enumerate(output["children"]):
            child["chunk_order"] = order
            parts = child["chunk_id"].split(":")
            parts[2:5] = [str(order), str(child["start_char"]), str(child["end_char"])]
            child["chunk_id"] = ":".join(parts)
        for atom in list(output["atom_spans"]):
            if atom["start_char"] < cut < atom["end_char"]:
                before, after = deepcopy(atom), deepcopy(atom)
                before["end_char"], after["start_char"] = cut, cut
                atom_index = output["atom_spans"].index(atom)
                output["atom_spans"][atom_index:atom_index + 1] = [before, after]
        issues = _check_record(record, output, 1, self.config)
        self.assertTrue(any("protected" in issue.lower() for issue in issues), issues)

    def test_auditor_rejects_forged_parent_question_context(self) -> None:
        record = self.records[1067218]
        output = self.output(1067218)
        output["input_line"] = 1
        parent = next(parent for parent in output["parents"] if parent.get("question_span"))
        parent["question_span"] = {"start_char": len(self.sources[1067218]) + 1,
                                   "end_char": len(self.sources[1067218]) + 2}
        issues = _check_record(record, output, 1, self.config)
        self.assertTrue(issues, "Question context may not point outside its original source")
        self.assertTrue(any("parent" in issue.lower() or "question" in issue.lower() for issue in issues), issues)

    def test_auditor_rejects_arbitrary_short_reason_and_invented_evidence(self) -> None:
        record = self.records[2335124]
        output = self.output(2335124)
        output["input_line"] = 1
        short_child = next(child for child in output["children"] if child["unit_count"] < 100)
        self.assertTrue(short_child["short_chunk_reason"])
        self.assertTrue(short_child["short_reason_evidence"])
        for key, forged_value in (
            ("short_chunk_reason", "anything"),
            ("short_reason_evidence", {"invented": True}),
        ):
            with self.subTest(field=key):
                tampered = deepcopy(output)
                tampered["children"][short_child["chunk_order"]][key] = forged_value
                issues = _check_record(record, tampered, 1, self.config)
                self.assertTrue(issues, "A nonempty short-chunk explanation is not sufficient evidence")
                self.assertTrue(any("short" in issue.lower() or "evidence" in issue.lower() for issue in issues), issues)

    def test_parent_initializes_with_icd_topic_field(self) -> None:
        for doc_id in (7156587, 1067218, 218831, 279805, 4265827):
            output = self.output(doc_id)
            self.assertTrue(output["parents"], f"Doc {doc_id} should produce parents")
            for parent in output["parents"]:
                self.assertIn("topic", parent)
                self.assertIsNone(parent["topic"], "Topic should initialize as None for late binding")

    def test_parent_topic_supports_late_binding_icd_payload(self) -> None:
        record = self.records[7156587]
        output = self.output(7156587)
        output["input_line"] = 1
        icd_payload = {
            "system": "ICD-10",
            "chapters": ["XI"],
            "blocks": ["K20-K31"],
            "codes": ["K21", "K29"],
            "description": "Diseases of the digestive system",
            "confidence": 0.95,
        }
        output["parents"][0]["topic"] = icd_payload
        # Verify JSON serialization succeeds
        serialized = json.dumps(output, ensure_ascii=False)
        self.assertIn('"ICD-10"', serialized)
        # Verify children and chunk_text remain completely unchanged
        original_output = self.output(7156587)
        self.assertEqual(output["children"], original_output["children"])
        # Verify auditor accepts valid dict topic
        issues = _check_record(record, output, 1, self.config)
        self.assertFalse(issues, f"Auditor should accept valid topic payload: {issues}")
        # Verify auditor rejects non-dict topic
        output["parents"][0]["topic"] = "invalid_string_topic"
        invalid_issues = _check_record(record, output, 1, self.config)
        self.assertTrue(any("topic" in issue.lower() for issue in invalid_issues))

    def test_children_map_consistently_to_parent_topic(self) -> None:
        output = self.output(1067218)
        parents_by_id = {p["parent_id"]: p for p in output["parents"]}
        for child in output["children"]:
            self.assertIn(child["parent_id"], parents_by_id)
            parent = parents_by_id[child["parent_id"]]
            self.assertIn("topic", parent)


if __name__ == "__main__":
    unittest.main()
