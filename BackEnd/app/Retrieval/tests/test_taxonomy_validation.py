import copy
import unittest
import tempfile
from pathlib import Path

from BackEnd.app.Retrieval.taxonomy.validation import ReleaseValidator, release_profile
from BackEnd.app.Retrieval.taxonomy.models import FoundationError, identifier
from BackEnd.app.Retrieval.taxonomy.sources import SourceStore
from BackEnd.app.Retrieval.taxonomy.build import build
from BackEnd.app.Retrieval.taxonomy.io import write_json
from BackEnd.app.Retrieval.taxonomy.normalize import Normalizer
from BackEnd.app.Retrieval.taxonomy.lexicon import curate_senses
from BackEnd.app.Retrieval.tests.test_taxonomy_who import XML


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        source = root / 'source.xml'
        source.write_text(XML)
        snapshot = SourceStore(root / 'store').acquire({'source_id': 'test', 'system': 'WHO_ICD10',
            'declared_version': 'fixture', 'format': 'claml', 'local_path': str(source)})
        run = root / 'run'
        write_json(run / 'source_manifest.json', {'sources': [snapshot], 'failures': [], 'config_sha256': 'a' * 64})
        cls.bundle = build(run)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_valid_bundle_passes_and_corrupted_contracts_fail(self):
        self.assertTrue(ReleaseValidator().validate(self.bundle, normalizer=Normalizer())['passed'])
        def foreign_projection(b):
            row = b['lexicon.verified'][0]
            projection = next(p for p in b['topic_projections'] if p['source_node_id'] != row['sense_id'])
            row['links'][0]['projection_ids'] = [projection['projection_id']]
        def missing_alias_review(b):
            row = b['lexicon.verified'][0]
            row.update(lexical_relation='synonym', review_decision_ids=['does-not-exist'])
            row['entry_id'] = identifier('lex', [row['language'], row['term_raw'], row['sense_id'], 'synonym'])
            row['verification']['semantic_status'] = 'independently_reviewed'
        mutations = [
            lambda b: b['taxonomy'][0].update(schema_version=True),
            lambda b: b['taxonomy'][0].update(parent_id=b['taxonomy'][0]['node_id']),
            lambda b: b['taxonomy'][0].update(valid_from='2019'),
            lambda b: b['taxonomy'][0]['labels']['en'].update(text='fabricated preferred label'),
            lambda b: b['lexicon.verified'][0]['verification'].update(semantic_status='unverified'),
            lambda b: b['lexicon.verified'][0].update(source_refs=[]),
            lambda b: b['reconciliation']['sources'][0].update(input_units=0),
            lambda b: b['topic_projections'].pop(),
            foreign_projection,
            missing_alias_review,
            lambda b: b['lexicon.verified'][0].update(ambiguity_group_id='unrelated'),
        ]
        for index, mutation in enumerate(mutations):
            bundle = copy.deepcopy(self.bundle)
            mutation(bundle)
            self.assertFalse(ReleaseValidator().validate(bundle, normalizer=Normalizer())['passed'], index)

    def test_label_cannot_borrow_a_review_for_an_unrelated_object(self):
        bundle = copy.deepcopy(self.bundle)
        source = bundle['source_nodes'][0]
        bundle['review_decisions'] = [{'decision_id': 'unrelated-review', 'object_id': 'unrelated',
            'decision': 'accept', 'reviewer': 'fixture', 'method': 'manual', 'rationale': 'different object',
            'source_refs': source['source_refs']}]
        bundle['taxonomy'][0]['labels']['vi'] = {
            'text': 'Nhãn không có căn cứ', 'language': 'vi', 'origin': 'equivalent_crosswalk',
            'native_node_id': source['source_node_id'], 'source_refs': source['source_refs'],
            'crosswalk_edge_ids': [], 'review_decision_id': 'unrelated-review'}
        self.assertFalse(ReleaseValidator().validate(bundle, normalizer=Normalizer())['passed'])

    def test_pending_competitor_cannot_be_marked_rejected_only_in_registry(self):
        bundle = copy.deepcopy(self.bundle)
        one = bundle['lexicon.verified'][0]
        pending = copy.deepcopy(one)
        pending['sense_id'] = next(n['source_node_id'] for n in bundle['source_nodes']
                                   if n['source_node_id'] != one['sense_id'])
        pending['entry_id'] = identifier('lex', [pending['language'], pending['term_raw'], pending['sense_id'], pending['lexical_relation']])
        pending['verification'].update(acceptance='quarantined', semantic_status='unverified')
        verified, groups, issues = curate_senses([one, pending], Normalizer())
        bundle['lexicon.verified'] = [r if r['entry_id'] != one['entry_id'] else verified[0] for r in bundle['lexicon.verified']]
        bundle['ambiguity_groups'].extend(groups)
        bundle['review_queue'].extend(issues)
        self.assertTrue(ReleaseValidator().validate(bundle, normalizer=Normalizer())['passed'])
        competitor = next(s for s in groups[0]['senses'] if s['entry_id'] == pending['entry_id'])
        competitor['status'] = 'rejected'
        self.assertFalse(ReleaseValidator().validate(bundle, normalizer=Normalizer())['passed'])
    def test_semantic_gate_never_uses_target_as_measured_score(self):
        coverage = {'core_multilingual_complete': False}
        self.assertEqual('audit_only', release_profile([], coverage, None))
        audit = {'passed': True, 'gold_approved': True, 'holdout': True, 'cases': 199,
                 'gold_contract_complete': True,
                 'language_counts': {'vi': 50, 'en': 99, 'zh': 50},
                 'official_mapping_precision': 1, 'resolved_precision': 1,
                 'performance_passed': True}
        self.assertEqual('audit_only', release_profile([], coverage, audit))
        audit.update(cases=200, language_counts={'vi': 50, 'en': 100, 'zh': 50})
        self.assertEqual('pilot_partial', release_profile([], coverage, audit))
        self.assertEqual('core_ready', release_profile([], {'core_multilingual_complete': True}, audit))
        self.assertEqual('rejected', release_profile([{'severity': 'error'}], coverage, audit))
        audit['gold_approved'] = False
        self.assertEqual('audit_only', release_profile([], coverage, audit))

    def test_empty_bundle_is_rejected_not_ready(self):
        report = ReleaseValidator().validate({'taxonomy': [], 'source_nodes': [], 'source_manifest': {'sources': []}})
        self.assertFalse(report['passed'])
        self.assertEqual('rejected', report['profile'])
        self.assertTrue(report['errors'])

    def test_nonfinite_and_duplicate_are_schema_errors(self):
        for bundle in [{'taxonomy': [{'node_id': 'same'}, {'node_id': 'same'}]},
                       {'taxonomy': [], 'score': float('nan')}]:
            report = ReleaseValidator().validate(copy.deepcopy(bundle))
            self.assertFalse(report['passed'])
