import unittest
from unittest.mock import patch

from BackEnd.app.Retrieval.taxonomy.audit import semantic_audit, wilson
from BackEnd.app.Retrieval.taxonomy import audit
from BackEnd.app.Retrieval.taxonomy.lexicon import make_entry
from BackEnd.app.Retrieval.taxonomy.normalize import Normalizer


class AuditTests(unittest.TestCase):
    def test_small_development_set_never_becomes_approved_holdout(self):
        n = Normalizer()
        entry = make_entry('pneumonia', 'en', 'J18', 'disease_or_condition', 'topic_candidate', n,
                           accepted=True, source_refs=[{'locator': 'synthetic'}], links=[{
                           'target_node_id': 'J18', 'usage': 'topic_candidate', 'relation': 'exact_concept',
                           'source_refs': [{'locator': 'synthetic'}], 'projection_ids': [], 'review_decision_id': None}])
        bundle = {'lexicon.verified': [entry], 'ambiguity_groups': [], 'source_nodes': [{'source_node_id': 'J18', 'code': 'J18'}]}
        cases = [{'id': 'independent-fixture', 'language': 'en', 'text': 'pneumonia',
                  'category': 'official_mapping', 'evidence_refs': ['synthetic'],
                  'expected': {'status': 'resolved_candidate', 'kinds': ['disease_or_condition'], 'target_codes': ['J18']}}]
        report = semantic_audit(bundle, cases, {'split': 'development', 'approved_by': None})
        self.assertTrue(report['passed'])
        self.assertFalse(report['gold_approved'])
        self.assertFalse(report['holdout'])
        self.assertEqual(1, report['metrics']['resolved']['support'])
        self.assertEqual(1, report['resolved_precision'])
        self.assertLess(report['metrics']['resolved']['wilson_95'][0], .3)

    def test_wilson_requires_support(self):
        self.assertIsNone(wilson(0, 0))
        self.assertEqual(2, len(wilson(99, 100)))

    def test_linux_peak_uses_new_address_space_not_inherited_rusage(self):
        with patch.object(audit.Path, 'read_text', return_value='VmHWM:\t65536 kB\nVmRSS:\t32768 kB\n'), \
             patch.object(audit.resource, 'getrusage') as usage:
            usage.return_value.ru_maxrss = 2 * 1024 * 1024
            result = audit.memory_measurement()
        self.assertEqual(64, result['process_peak_rss_mb'])
        self.assertEqual(2048, result['rusage_lifetime_peak_mb'])
        self.assertEqual('/proc/self/status:VmHWM', result['rss_measurement_source'])
