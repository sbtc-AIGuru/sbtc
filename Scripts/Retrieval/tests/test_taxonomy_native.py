import json
import tempfile
import unittest
from pathlib import Path

from sbtc.Scripts.Retrieval.taxonomy.native import NativeJSONAdapter, PDFStagingAdapter
from sbtc.Scripts.Retrieval.taxonomy.sources import SourceStore
from sbtc.Scripts.Retrieval.taxonomy.byt import page_candidates
from sbtc.Scripts.Retrieval.taxonomy import native


class NativeTests(unittest.TestCase):
    def test_extraction_review_changes_only_verification_not_native_label_or_identity(self):
        row = {'source_node_id': 'native', 'record_type': 'node', 'system': 'BYT_ICD10',
               'code': 'A00', 'preferred_labels': {'vi': {'text': 'Bệnh tả'}},
               'source_verified': False, 'parse_status': 'quarantined', 'source_refs': [{'locator': 'page=1'}]}
        review = {'decision_id': 'review', 'object_id': 'native', 'decision': 'accept', 'extraction_verified': True,
                  'reviewer': 'synthetic-reviewer', 'method': 'manual', 'rationale': 'read page and cells',
                  'source_refs': [{'locator': 'page=1;cell=22'}]}
        out = native.apply_source_reviews([row], [review])[0]
        self.assertTrue(out['source_verified'])
        self.assertEqual('review', out['source_review_decision_id'])
        self.assertFalse(row['source_verified'])
        for key in ['source_node_id', 'code', 'preferred_labels']:
            self.assertEqual(row[key], out[key])
    def test_pdf_candidate_columns_keep_row_boundaries_and_remain_unverified(self):
        def word(text, x, y):
            return {'text': text, 'left': str(x), 'top': str(y), 'width': '5', 'height': '5'}
        words = [word('1', 24.2, 80), word('1', 19.25, 100), word('A00', 473, 100),
                 word('Bệnh', 591, 100), word('tả', 601, 106),
                 word('2', 19.25, 140), word('A01', 473, 140), word('Bệnh thương hàn', 591, 140)]
        rows = page_candidates(words, 7)
        self.assertEqual([1, 2], [r['sequence'] for r in rows])
        self.assertEqual('A00', rows[0]['cells'][17])
        self.assertEqual('Bệnh tả', rows[0]['cells'][21])
        self.assertEqual('Bệnh thương hàn', rows[1]['cells'][21])
        # Real annex pages after page 1 start data at y=35.41, before the old y>40 guard.
        first = page_candidates([word('23', 19.25, 35.41), word('A00', 473, 35.41), word('Bệnh', 591, 35.41)], 2)
        self.assertEqual([23], [x['sequence'] for x in first])
    def test_duplicate_and_malformed_rows_are_quarantined_not_lost(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'native.json'
            p.write_text(json.dumps([
                {'code': 'E11.000', 'level': 'subcategory', 'labels': {'zh': '2型糖尿病'}},
                {'code': 'E11.000', 'level': 'subcategory', 'labels': {'zh': 'Different scope'}},
                {'code': '', 'labels': {'zh': 'invalid'}},
                {'code': 'A00', 'level': 'category', 'labels': {'vi': 'Bệnh tả'}}]))
            snapshot = SourceStore(Path(t) / 'store').acquire({
                'source_id': 'native', 'system': 'BYT_ICD10', 'declared_version': 'test',
                'format': 'native_json', 'local_path': str(p), 'source_verified': False})
            rows = list(NativeJSONAdapter().parse(snapshot))
            self.assertEqual(4, len(rows))
            self.assertEqual(1, sum(x['record_type'] == 'node' for x in rows))
            self.assertEqual(3, sum(x.get('status') == 'quarantined' for x in rows))
            self.assertFalse(next(x for x in rows if x['record_type'] == 'node')['source_verified'])

    def test_fhir_preserves_native_hierarchy_designations_and_flags(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'fhir.json'
            p.write_text(json.dumps({'resourceType': 'CodeSystem', 'version': 'test', 'language': 'vi',
                'concept': [{'code': 'P', 'display': 'Nhóm', 'property': [{'code': 'inactive', 'valueBoolean': True}],
                             'concept': [{'code': 'C', 'display': 'Bệnh',
                                          'designation': [{'language': 'en', 'value': 'Condition'}]}]}]}))
            snapshot = SourceStore(Path(t) / 'store').acquire({
                'source_id': 'fhir', 'system': 'BYT_ICD10', 'declared_version': 'test',
                'format': 'fhir', 'local_path': str(p), 'source_verified': False})
            rows = list(NativeJSONAdapter().parse(snapshot))
            child = next(x for x in rows if x['code'] == 'C')
            self.assertEqual(['P'], child['parent_codes_raw'])
            self.assertEqual('Condition', child['preferred_labels']['en']['text'])
            self.assertIsNone(child['coding_attributes']['terminal'])

    def test_pdf_pages_are_staging_evidence_not_verified_labels(self):
        pages = PDFStagingAdapter.page_records(['raw page one', 'raw page two'], {
            'source_id': 'pdf', 'edition_id': 'fixture', 'content_sha256': 'a' * 64,
            'members': [{'content_sha256': 'b' * 64}]})
        self.assertEqual(2, len(pages))
        self.assertTrue(all(x['status'] == 'deferred' for x in pages))
        self.assertIn('page=2', pages[1]['source_refs'][0]['locator'])
