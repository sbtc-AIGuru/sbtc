"""Next chunking regressions from immutable test20k and source-derived wrappers."""
from copy import deepcopy
import re
import tempfile
from pathlib import Path
import json
import unittest

from sbtc.tests.test_chunk_formats import fixture_records
from sbtc.Scripts.Clawler.verbatim import clean_with_report
from sbtc.Scripts.Preprocess.chunking import ChunkConfig, chunk_document, count_units
from sbtc.Scripts.Preprocess.format_profiles import analyse_format, select_profile, _oversized_split_points
from sbtc.Scripts.Preprocess.chunk_audit import _check_record


IDS = {763924, 760963, 764534, 570700, 239736, 252279, 4050109, 2531165,
       566375, 1736699, 2520397, 3109918, 732683, 474770, 6269502,
       7156587, 1128713, 6333519, 4057861, 211401, 218831, 7239974,
       759366, 193224, 182511, 499246}


class NextChunkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = fixture_records(IDS)
        cls.sources = {k: clean_with_report(r['text'])[0] for k, r in cls.records.items()}

    def test_verified_toc_excludes_only_duplicate_navigation(self):
        for did in (763924, 760963, 764534):
            with self.subTest(doc_id=did):
                source = self.sources[did]
                analysis = analyse_format(source, self.records[did]['url'])
                toc = [s for s in analysis['excluded_spans'] if s['rule_id'] == 'verified_table_of_contents']
                self.assertEqual(len(toc), 1)
                span = toc[0]
                self.assertIn('Nội dung bài viết', span['text'])
                matches = span['evidence'][0]['matched_entries']
                self.assertGreaterEqual(len(matches), 3)
                for item in matches:
                    self.assertLess(item['toc_start_char'], span['end_char'])
                    self.assertGreaterEqual(item['body_start_char'], span['end_char'])
                    self.assertEqual(source[item['body_start_char']:item['body_end_char']], item['body_text'])
                out = chunk_document(self.records[did], strategy='format')
                self.assertEqual(out['coverage']['non_whitespace_covered'], out['coverage']['non_whitespace_total'])
                self.assertFalse(any('Nội dung bài viết' in c['chunk_text'] for c in out['children']))

    def test_toc_without_body_and_two_entry_list_are_retained(self):
        source = self.sources[763924]
        marker = source.index('Nội dung bài viết')
        end = source.index('\n\n', marker)
        partial = source[:end]
        self.assertFalse(any(s['rule_id'] == 'verified_table_of_contents'
                             for s in analyse_format(partial, self.records[763924]['url'])['excluded_spans']))
        self.assertFalse(any(s['rule_id'] == 'verified_table_of_contents'
                             for s in analyse_format(self.sources[570700], self.records[570700]['url'])['excluded_spans']))

    def test_general_health_articles_are_not_catalogues(self):
        for did in (239736, 252279):
            with self.subTest(doc_id=did):
                self.assertEqual(select_profile(self.sources[did], self.records[did]['url'])['profile'], 'narrative_article')

    def test_catalogue_positives_keep_drug_and_table_structure(self):
        for did in (4050109, 2531165):
            with self.subTest(doc_id=did):
                self.assertEqual(select_profile(self.sources[did], self.records[did]['url'])['profile'], 'disease_drug_catalogue')

    def test_vietnamese_drug_monographs_keep_catalogue_outside_navigation(self):
        for did in (759366, 764534, 193224, 182511):
            with self.subTest(doc_id=did):
                analysis = analyse_format(self.sources[did], self.records[did]['url'])
                self.assertEqual(analysis['metadata']['profile'], 'disease_drug_catalogue')
                evidence = analysis['metadata']['format_evidence'][0]['vi_drug_fields']
                self.assertIn('dosing', evidence['roles'])
                self.assertGreaterEqual(len(evidence['roles']), 3)
                for span in evidence['spans']:
                    self.assertFalse(any(x['start_char'] <= span['start_char'] < x['end_char']
                                         for x in analysis['excluded_spans'] if x['rule_id'] == 'verified_table_of_contents'))

    def test_drug_navigation_without_body_is_not_catalogue_evidence(self):
        source = self.sources[759366]
        marker = source.index('Nội dung bài viết')
        end = source.index('\n\n', marker)
        partial = source[:end]
        self.assertNotEqual(select_profile(partial, self.records[759366]['url'])['profile'], 'disease_drug_catalogue')
        self.assertFalse(any(s['rule_id'] == 'verified_table_of_contents'
                             for s in analyse_format(partial, self.records[759366]['url'])['excluded_spans']))

    def test_food_recipe_ingredients_do_not_count_as_drug_identity(self):
        self.assertIn('Thành phần', self.sources[499246])
        self.assertEqual(select_profile(self.sources[499246], self.records[499246]['url'])['profile'], 'narrative_article')

    def test_repeated_single_research_label_does_not_route_clinical_guides(self):
        for did in (2520397, 3109918):
            with self.subTest(doc_id=did):
                self.assertNotEqual(select_profile(self.sources[did], self.records[did]['url'])['profile'], 'research_abstract')

    def test_real_research_with_complementary_labels_stays_research(self):
        for did in (566375, 1736699, 6333519):
            with self.subTest(doc_id=did):
                self.assertEqual(select_profile(self.sources[did], self.records[did]['url'])['profile'], 'research_abstract')

    def test_reference_only_labels_do_not_route_the_document(self):
        # All clinical words are from the positive record; only a section wrapper is added.
        title = self.sources[566375].splitlines()[0]
        abstract = self.sources[566375][self.sources[566375].index('Abstract'):]
        wrapped = title + '\n\nReferences\n' + abstract
        self.assertNotEqual(select_profile(wrapped, self.records[566375]['url'])['profile'], 'research_abstract')

    def test_broken_empty_target_keeps_visible_label_and_following_body(self):
        raw = self.records[732683]['text']
        match = re.search(r'\[\[([^\n]+)\]\]\([ \t]*(?=\n|$)', raw)
        self.assertIsNotNone(match)
        source, report = clean_with_report(raw)
        self.assertIn('[' + match.group(1) + ']', source)
        self.assertNotIn(match.group(0), source)
        self.assertGreater(report['actions'].get('incomplete_link_recovered', 0), 0)
        self.assertEqual(clean_with_report(source)[0], source)
        following = raw[match.end():].splitlines()
        for line in following:
            if len(line.strip()) > 80 and '[' not in line and 'http' not in line:
                self.assertIn(clean_with_report(line)[0], source)
                break

    def test_broken_url_recovery_is_bounded_by_newline(self):
        label = self.sources[211401].splitlines()[0]
        body = next(line for line in self.sources[211401].splitlines() if '37,5' in line)
        wrapped = '[' + label + '](https://example.invalid/article\n' + body
        source, report = clean_with_report(wrapped)
        self.assertEqual(source, label + '\n' + body)
        self.assertEqual(report['actions']['incomplete_link_recovered'], 1)
        self.assertEqual(clean_with_report(source)[0], source)

    def test_ambiguous_unit_parenthesis_and_code_are_retained(self):
        unit = re.search(r'\bmg\b', self.sources[4057861], re.I).group()
        literal = '[' + unit + '](' + unit + ')'
        self.assertEqual(clean_with_report(literal)[0], literal)
        self.assertEqual(clean_with_report('`' + literal + '`')[0], literal)
        self.assertEqual(clean_with_report('[' + unit + '](\n' + unit)[0], '[' + unit + '](\n' + unit)

    def test_oversize_fallback_does_not_cut_author_initials(self):
        source = self.sources[6269502]
        match = re.search(r'\bH\.\s+Lester', source)
        self.assertIsNotNone(match)
        points = _oversized_split_points(source, 0, len(source), 'sentence', [], [], [])
        self.assertNotIn(match.start() + 2, points)

    def test_diagnostic_counts_distinguish_events_records_and_hard_size(self):
        from sbtc.Scripts.Preprocess.chunk_cli import _empty_summary, _add_result
        summary = _empty_summary()
        row = chunk_document(self.records[474770], strategy='format')
        _add_result(summary, row)
        events = sum(w['count'] for w in row['cleaning']['warnings'] if w['code'] == 'incomplete_markdown_link')
        if events:
            self.assertEqual(summary['cleaning_warning_record_counts']['incomplete_markdown_link'], 1)
            self.assertEqual(summary['cleaning_warnings']['incomplete_markdown_link'], events)
        self.assertEqual(summary['chunks_over_500'], sum(c['unit_count'] > 500 for c in row['children']))
        self.assertEqual(sum(summary['overlap_size_distribution'].values()), summary['eligible_overlap_transitions'])

    def test_reserve_policy_keeps_exact_source_coverage_and_budget(self):
        config = ChunkConfig(format_overlap_policy='reserve')
        for did in (218831, 6333519, 4057861, 566375):
            with self.subTest(doc_id=did):
                out = chunk_document(self.records[did], config, strategy='format')
                source = self.sources[did]
                self.assertEqual(out['coverage']['non_whitespace_total'], out['coverage']['non_whitespace_covered'])
                for c in out['children']:
                    self.assertEqual(c['chunk_text'], source[c['start_char']:c['end_char']])
                    self.assertLessEqual(c['unit_count'], 500)
                out['input_line'] = 1
                self.assertEqual(_check_record(self.records[did], out, 1, config), [])
                if did == 566375:
                    control = chunk_document(self.records[did], ChunkConfig(), strategy='format')
                    self.assertEqual(len(out['children']), len(control['children']))
                    self.assertGreater(sum(c['overlap_units'] > 0 for c in out['children']),
                                       sum(c['overlap_units'] > 0 for c in control['children']))
        disabled = chunk_document(self.records[218831], ChunkConfig(overlap_units=0, format_overlap_policy='reserve'), strategy='format')
        self.assertTrue(all(c['overlap_units'] == 0 for c in disabled['children']))

    def test_source_derived_merge_roundtrips_through_auditor_and_detects_tampering(self):
        from sbtc.Scripts.Preprocess.format_chunking import _merge_short_children
        from sbtc.Scripts.Preprocess.format_profiles import PROFILE_VERSION
        did = 7239974
        source = self.sources[did]
        row = chunk_document(self.records[did], strategy='format')
        self.assertEqual(len(row['children']), 1)
        original = row['children'][0]
        self.assertEqual(original['unit_count'], 52)
        atoms = row['atom_spans']
        cut = atoms[1]['end_char']
        left, right = deepcopy(original), deepcopy(original)
        for child, order, start, end in ((left, 0, original['start_char'], cut),
                                         (right, 1, atoms[2]['start_char'], original['end_char'])):
            child.update(start_char=start, end_char=end, chunk_order=order, chunk_text=source[start:end],
                         unit_count=count_units(source[start:end]),
                         chunk_id=f'{did}:c:{order}:{start}:{end}:{PROFILE_VERSION}')
            self.assertLess(child['unit_count'], 50)
        row['children'] = _merge_short_children([left, right], source, ChunkConfig())
        self.assertEqual(row['children'][0]['chunk_text'], original['chunk_text'])
        row['input_line'] = 1
        self.assertEqual(_check_record(self.records[did], row, 1, ChunkConfig()), [])
        invalid = deepcopy(row)
        invalid['children'][0]['merged_from_chunk_ids'][0] = 'wrong-source-id'
        self.assertTrue(_check_record(self.records[did], invalid, 1, ChunkConfig()))
        invalid = deepcopy(row)
        invalid['children'][0]['merged_from_chunks'][0]['unit_count'] = 50
        self.assertTrue(_check_record(self.records[did], invalid, 1, ChunkConfig()))
        invalid = deepcopy(row)
        invalid['children'][0]['merged_from_chunks'].reverse()
        self.assertTrue(_check_record(self.records[did], invalid, 1, ChunkConfig()))

    def test_overlap_policy_cannot_resume_into_a_different_checkpoint(self):
        from sbtc.Scripts.Preprocess.chunk_cli import run_chunking
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'test.jsonl'
            source.write_text(json.dumps(self.records[566375], ensure_ascii=False) + '\n')
            out = root / 'out'
            run_chunking(source, out, strategy='format', progress_every=0)
            before = (out / 'checkpoint.json').read_bytes()
            with self.assertRaises(ValueError):
                run_chunking(source, out, ChunkConfig(format_overlap_policy='reserve'), strategy='format', resume=True, progress_every=0)
            self.assertEqual((out / 'checkpoint.json').read_bytes(), before)

    def test_complete_links_and_numeric_literal_survive_cleaner_revision(self):
        label = self.sources[211401].splitlines()[0]
        self.assertEqual(clean_with_report('[' + label + '](https://example.invalid/a)')[0], label)
        body = next(line for line in self.sources[211401].splitlines() if '37,5' in line)
        wrapped = '[' + label + '](https://example.invalid/a ' + body
        cleaned, report = clean_with_report(wrapped)
        self.assertIn(body, cleaned)
        self.assertIn(label, cleaned)
        self.assertEqual(report['actions']['incomplete_link_recovered'], 1)

    def test_too_long_unclosed_target_is_not_recovered_by_scanning_into_body(self):
        label = self.sources[211401].splitlines()[0]
        body = next(line for line in self.sources[211401].splitlines() if '37,5' in line)
        wrapped = '[' + label + '](https://example.invalid/' + 'x' * 4100 + '\n' + body
        cleaned, report = clean_with_report(wrapped)
        self.assertEqual(report['actions'].get('incomplete_link_recovered', 0), 0)
        self.assertIn(body, cleaned)

    def test_broken_url_never_swallows_adjacent_chinese_source(self):
        label = self.sources[211401].splitlines()[0]
        chinese = self.sources[4057861].splitlines()[0]
        raw = '[' + label + '](https://example.invalid/a。' + chinese
        cleaned, _ = clean_with_report(raw)
        self.assertIn('。' + chinese, cleaned)

    def test_reserve_with_small_budget_still_keeps_oversized_source_atoms(self):
        config = ChunkConfig(min_units=30, target_units=45, max_units=60, overlap_units=10,
                             format_overlap_policy='reserve')
        row = chunk_document(self.records[6333519], config, strategy='format')
        self.assertTrue(any(c['unit_count'] > 60 for c in row['children']))
        row['input_line'] = 1
        self.assertEqual(_check_record(self.records[6333519], row, 1, config), [])


if __name__ == '__main__':
    unittest.main()
