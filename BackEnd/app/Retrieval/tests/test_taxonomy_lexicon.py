import unittest

from BackEnd.app.Retrieval.taxonomy.lexicon import LexiconReader, curate_senses, make_entry, apply_lexical_reviews
from BackEnd.app.Retrieval.taxonomy.models import FoundationError
from BackEnd.app.Retrieval.taxonomy.normalize import Normalizer


class LexiconTests(unittest.TestCase):
    def setUp(self):
        self.norm = Normalizer()

    def entry(self, term, *, lang='en', sense='one', kind='disease_or_condition', usage='topic_candidate', accepted=True, sensitive=False):
        return make_entry(term, lang, sense, kind, usage, self.norm,
                          source_refs=[{'locator': 'fixture'}], accepted=accepted,
                          case_sensitive=sensitive, links=[{'target_node_id': sense, 'usage': usage,
                          'relation': 'exact_concept', 'source_refs': [{'locator': 'fixture'}],
                          'projection_ids': [], 'review_decision_id': None}])

    def test_normalization_preserves_accents_case_and_is_idempotent(self):
        for lang, raw in [('vi', '  ĐÁI THÁO ĐƯỜNG  '), ('zh', '發熱２型'), ('en', '&amp;lt; HbA1c μg')]:
            views = self.norm.views(raw, lang)
            self.assertEqual(views, self.norm.views(views['case_preserved'], lang))
        self.assertEqual('đái tháo đường', self.norm.views('ĐÁI THÁO ĐƯỜNG', 'vi')['normalized'])
        self.assertEqual('发热2型', self.norm.views('發熱２型', 'zh')['normalized'])
        self.assertIn('&amp;lt;', self.norm.views('&amp;lt;', 'en')['normalized'])

    def test_pending_competitor_blocks_false_resolution(self):
        rows = [self.entry('PSA', sense='biomarker', kind='biomarker', usage='context_only'),
                self.entry('PSA', sense='sedation', kind='procedure', usage='context_only', accepted=False)]
        verified, groups, _ = curate_senses(rows, self.norm)
        reader = LexiconReader(verified, groups, self.norm)
        out = reader.lookup('PSA', 'en')
        self.assertEqual('ambiguous_candidates', out['status'])
        self.assertEqual(2, len(out['mentions'][0]['sense_candidates']))

    def test_code_adjacent_to_han_and_case_sensitive_units(self):
        code = self.entry('J18.9')
        code['matching_policy']['boundary_policy'] = 'code_literal'
        marker = self.entry('MS', sensitive=True)
        verified, groups, _ = curate_senses([code, marker], self.norm)
        reader = LexiconReader(verified, groups, self.norm)
        self.assertEqual('resolved_candidate', reader.lookup('诊断J18.9肺炎', 'en')['status'])
        for text in ['XJ18.9', 'J18.90', 'mS', 'xMS', 'MS_abc']:
            self.assertEqual('no_match', reader.lookup(text, 'en')['status'], text)
        self.assertEqual('resolved_candidate', reader.lookup('MS', 'en')['status'])

    def test_same_sense_merges_provenance_homonyms_stay_separate(self):
        one = self.entry('test')
        two = self.entry('test')
        two['source_refs'] = [{'locator': 'other'}]
        verified, groups, _ = curate_senses([one, two, self.entry('test', sense='two')], self.norm)
        self.assertEqual(2, len(verified))
        self.assertEqual(2, len(next(x for x in verified if x['sense_id'] == 'one')['source_refs']))
        self.assertEqual(1, len(groups))

    def test_context_is_preserved_and_negation_does_not_delete_topic(self):
        rows = [self.entry('metformin', kind='drug_substance', usage='context_only'),
                self.entry('pneumonia')]
        entries, groups, _ = curate_senses(rows, self.norm)
        reader = LexiconReader(entries, groups, self.norm)
        self.assertEqual('context_only', reader.lookup('metformin', 'en')['status'])
        self.assertEqual('resolved_candidate', reader.lookup('no pneumonia', 'en')['status'])
        self.assertEqual('no_match', reader.lookup('missing term', 'en')['status'])

    def test_invalid_runtime_entry_or_profile_is_rejected(self):
        one = self.entry('term', accepted=False)
        with self.assertRaises(FoundationError):
            LexiconReader([one], [], self.norm)
        one = self.entry('term')
        one['normalization_profile'] = 'different'
        with self.assertRaises(FoundationError):
            LexiconReader([one], [], self.norm)

    def test_link_usage_can_only_restrict_entry_usage(self):
        for usage, status in [('abstain', 'ambiguous_candidates'), ('context_only', 'context_only')]:
            one = self.entry('term')
            one['links'][0]['usage'] = usage
            entries, groups, _ = curate_senses([one], self.norm)
            self.assertEqual(status, LexiconReader(entries, groups, self.norm).lookup('term', 'en')['status'])

    def test_nested_term_is_retained_but_not_an_independent_topic(self):
        rows = [self.entry('whooping cough', sense='A37'),
                self.entry('cough', sense='R05', kind='symptom_sign')]
        entries, groups, _ = curate_senses(rows, self.norm)
        result = LexiconReader(entries, groups, self.norm).lookup('Whooping cough', 'en')
        self.assertEqual(2, len(result['mentions']))
        primary = [m for m in result['mentions'] if m['independent_evidence']]
        nested = [m for m in result['mentions'] if not m['independent_evidence']]
        self.assertEqual(['A37'], [m['sense_candidates'][0]['sense_id'] for m in primary])
        self.assertEqual('context_only', nested[0]['status'])
        self.assertEqual([primary[0]['entry_id']], nested[0]['covered_by_entry_ids'])
        # The symptom is separate evidence when mentioned elsewhere as well.
        other = LexiconReader(entries, groups, self.norm).lookup('Whooping cough; persistent cough', 'en')
        self.assertEqual(2, sum(m['independent_evidence'] for m in other['mentions']))

    def test_same_span_homonyms_remain_ambiguous_primary_evidence(self):
        rows = [self.entry('PSA', sense='lab', kind='biomarker', usage='context_only'),
                self.entry('PSA', sense='sedation', kind='procedure', usage='context_only')]
        entries, groups, _ = curate_senses(rows, self.norm)
        result = LexiconReader(entries, groups, self.norm).lookup('PSA', 'en')
        self.assertEqual('ambiguous_candidates', result['status'])
        self.assertTrue(all(m['independent_evidence'] for m in result['mentions']))

    def test_nested_sensitive_term_aligns_after_expanding_lowercase(self):
        rows = [self.entry('test HbA1c', sense='test', kind='diagnostic_test', usage='context_only'),
                self.entry('HbA1c', sense='marker', kind='biomarker', usage='context_only', sensitive=True)]
        entries, groups, _ = curate_senses(rows, self.norm)
        result = LexiconReader(entries, groups, self.norm).lookup('İ: test HbA1c', 'en')
        nested = next(m for m in result['mentions'] if m['kind'] == 'biomarker')
        self.assertFalse(nested['independent_evidence'])
        self.assertEqual('normalized_case_preserved', nested['offset_space'])
        self.assertEqual(nested['start'] + 1, nested['evidence_start'])

    def test_accepted_native_sense_review_releases_its_direct_link_usage(self):
        entry = self.entry('native label', kind='unknown', usage='abstain')
        decision = {'decision_id': 'review', 'object_id': entry['entry_id'], 'decision': 'accept',
                    'reviewer': 'synthetic-reviewer', 'method': 'manual', 'source_refs': [{'locator': 'scope'}],
                    'rationale': 'read exact source concept', 'kind': 'disease_or_condition', 'usage': 'topic_candidate'}
        reviewed = apply_lexical_reviews([entry], [decision])[0]
        self.assertEqual('topic_candidate', reviewed['links'][0]['usage'])
        self.assertEqual('review', reviewed['links'][0]['review_decision_id'])
        entries, groups, _ = curate_senses([reviewed], self.norm)
        self.assertEqual('resolved_candidate', LexiconReader(entries, groups, self.norm).lookup('native label', 'en')['status'])

    def test_unknown_kind_does_not_erase_source_verification(self):
        entry = self.entry('raw source', kind='unknown')
        self.assertEqual('source_verified', entry['verification']['extraction_status'])
        self.assertEqual('unverified', entry['verification']['semantic_status'])
        self.assertEqual('quarantined', entry['verification']['acceptance'])

    def test_review_requires_kind_usage_and_extraction_evidence(self):
        entry = self.entry('candidate', accepted=False, kind='unknown')
        decision = {'decision_id': 'd', 'object_id': entry['entry_id'], 'decision': 'accept',
                    'reviewer': 'synthetic-reviewer', 'method': 'manual', 'source_refs': [{'locator': 'source'}],
                    'rationale': 'read source meaning', 'kind': 'diagnostic_test', 'usage': 'context_only'}
        with self.assertRaises(FoundationError):
            apply_lexical_reviews([entry], [decision])
        decision['extraction_verified'] = True
        reviewed = apply_lexical_reviews([entry], [decision])[0]
        self.assertEqual('diagnostic_test', reviewed['kind'])
        self.assertEqual('independently_reviewed', reviewed['verification']['semantic_status'])
