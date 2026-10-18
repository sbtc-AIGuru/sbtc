import unittest

from BackEnd.app.Retrieval.taxonomy.crosswalk import CrosswalkResolver, active_decisions, attach_equivalent_labels
from BackEnd.app.Retrieval.taxonomy.models import FoundationError


class CrosswalkTests(unittest.TestCase):
    def setUp(self):
        self.core = [{'node_id': 'chapter', 'parent_id': None, 'level': 'chapter'},
                     {'node_id': 'block', 'parent_id': 'chapter', 'level': 'block'},
                     {'node_id': 'category', 'parent_id': 'block', 'level': 'category'}]
        self.edge = {'edge_id': 'edge', 'source_node_id': 'native', 'target_node_id': 'category',
                     'relation': 'equivalent', 'source_refs': [{'locator': 'both-scopes'}],
                     'mapping_method': 'source_grounded_review', 'review_decision_id': 'd',
                     'verification': {'status': 'accepted'}}
        self.decision = {'decision_id': 'd', 'object_id': 'edge', 'decision': 'accept',
                         'relation': 'equivalent', 'reviewer': 'test-fixture', 'method': 'manual',
                         'source_refs': [{'locator': 'both-scopes'}], 'rationale': 'Same scope in fixture',
                         'supersedes': None}

    def test_pending_code_match_never_projects(self):
        edge = {**self.edge, 'verification': {'status': 'candidate'}, 'relation': None}
        resolver = CrosswalkResolver([edge], [], self.core, {'native'})
        self.assertEqual(1, len(resolver.candidates('native')))
        self.assertEqual([], resolver.projections())

    def test_reviewed_equivalent_projects_only_ancestors(self):
        resolver = CrosswalkResolver([self.edge], [self.decision], self.core, {'native'})
        self.assertEqual({'chapter', 'block', 'category'},
                         {x['target_node_id'] for x in resolver.projections()})
        for relation in ('broader_than', 'related_to'):
            edge = {**self.edge, 'relation': relation}
            decision = {**self.decision, 'relation': relation}
            self.assertEqual([], CrosswalkResolver([edge], [decision], self.core, {'native'}).projections())

    def test_prefix_or_missing_review_cannot_accept(self):
        for edges, decisions in [([self.edge], []),
                                 ([{**self.edge, 'mapping_method': 'code_prefix'}], [self.decision])]:
            with self.assertRaises(FoundationError):
                CrosswalkResolver(edges, decisions, self.core, {'native'})

    def test_verified_native_ancestor_can_project_leaf_without_equivalence(self):
        nodes = [{'source_node_id': 'native', 'system': 'BYT_ICD10', 'edition_id': 'test',
                  'code': 'parent', 'source_verified': True, 'hierarchy_verified': True,
                  'parent_codes_raw': [], 'source_refs': [{'locator': 'parent'}]},
                 {'source_node_id': 'leaf', 'system': 'BYT_ICD10', 'edition_id': 'test',
                  'code': 'leaf', 'source_verified': True, 'hierarchy_verified': True,
                  'parent_codes_raw': ['parent'], 'source_refs': [{'locator': 'leaf'}]}]
        r = CrosswalkResolver([self.edge], [self.decision], self.core, {'native', 'leaf'}, nodes)
        leaf = [x for x in r.projections() if x['source_node_id'] == 'leaf']
        self.assertEqual(3, len(leaf))
        self.assertTrue(all(x['path'][0] == 'native' for x in leaf))
        nodes[1]['hierarchy_verified'] = False
        self.assertEqual([], [x for x in r.projections() if x['source_node_id'] == 'leaf'])

    def test_review_supersession_is_not_file_order(self):
        old = {**self.decision, 'decision_id': 'old'}
        new = {**self.decision, 'decision_id': 'new', 'supersedes': 'old', 'decision': 'reject'}
        for rows in ([new, old], [old, new]):
            self.assertEqual('new', active_decisions(rows)['edge']['decision_id'])
        with self.assertRaises(FoundationError):
            active_decisions([old, {**new, 'supersedes': None}])
        with self.assertRaises(FoundationError):
            active_decisions([{**old, 'supersedes': 'new'}, new])

    def test_narrower_native_label_never_becomes_broad_preferred_translation(self):
        core = [{'node_id': 'category', 'labels': {'vi': None}}]
        native = [{'source_node_id': 'native', 'source_verified': True,
                   'preferred_labels': {'vi': {'text': 'Bệnh cụ thể', 'source_refs': [{'locator': 'native'}]}}}]
        edge = {**self.edge, 'relation': 'narrower_than'}
        self.assertEqual([], attach_equivalent_labels(core, native, [edge]))
        self.assertIsNone(core[0]['labels']['vi'])
        attach_equivalent_labels(core, native, [self.edge])
        self.assertEqual('equivalent_crosswalk', core[0]['labels']['vi']['origin'])

    def test_accepted_crosswalk_cannot_project_unverified_source_extraction(self):
        native = [{'source_node_id': 'native', 'system': 'BYT_ICD10', 'edition_id': 'test',
                   'code': 'A00', 'source_verified': False}]
        with self.assertRaises(FoundationError):
            CrosswalkResolver([self.edge], [self.decision], self.core, {'native'}, native)
