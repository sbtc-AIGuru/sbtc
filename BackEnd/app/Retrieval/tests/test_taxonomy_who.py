import tempfile
import unittest
from pathlib import Path

from BackEnd.app.Retrieval.taxonomy.models import FoundationError
from BackEnd.app.Retrieval.taxonomy.sources import SourceStore
from BackEnd.app.Retrieval.taxonomy.who import WHOAdapter, canonical_tree, TaxonomyReader

# Synthetic hierarchy: no patient/corpus text, deliberately includes nested blocks.
XML = '''<ClaML><Title version="fixture"/><Meta name="TopLevelSort" value="II"/>
<Class code="II" kind="chapter"><SubClass code="C00-C97"/>
<Rubric kind="preferred"><Label xml:lang="en">Neoplasms</Label></Rubric></Class>
<Class code="C00-C97" kind="block"><SuperClass code="II"/><SubClass code="C00-C75"/>
<Rubric kind="preferred"><Label xml:lang="en">Malignant neoplasms</Label></Rubric></Class>
<Class code="C00-C75" kind="block"><SuperClass code="C00-C97"/><SubClass code="C00"/>
<Rubric kind="preferred"><Label xml:lang="en">Specified sites</Label></Rubric></Class>
<Class code="C00" kind="category"><SuperClass code="C00-C75"/><ModifiedBy code="M"/>
<Rubric kind="preferred"><Label xml:lang="en">Malignant neoplasm of lip</Label></Rubric>
<Rubric kind="exclusion"><Label xml:lang="en">skin<Reference code="C43.0">C43.0</Reference></Label></Rubric></Class>
<Modifier code="M"><SubClass code="0"/></Modifier></ClaML>'''


class WHOTests(unittest.TestCase):
    def test_official_d_h_ranges_belong_to_different_chapters(self):
        fixture = Path(__file__).parent / 'fixtures/taxonomy/source_fixture_who_d_h.xml'
        with tempfile.TemporaryDirectory() as t:
            snapshot = SourceStore(Path(t)).acquire({
                'source_id': 'who-d-h-fixture', 'system': 'WHO_ICD10', 'declared_version': '2019-covid-expanded',
                'format': 'claml', 'local_path': str(fixture)})
            nodes = [r for r in WHOAdapter().parse(snapshot) if r['record_type'] == 'node']
            tree = canonical_tree(nodes)
            by_id = {n['node_id']: n for n in tree}
            for code, chapter in [('D10', '02'), ('D50', '03'), ('H00', '07'), ('H60', '08')]:
                node = next(n for n in tree if n['code'] == code)
                self.assertEqual(chapter, by_id[node['chapter_id']]['code'])

    def parse(self, xml=XML):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'input.xml'
            p.write_text(xml)
            snapshot = SourceStore(Path(t) / 's').acquire({
                'source_id': 'fixture', 'declared_version': 'fixture', 'format': 'claml',
                'system': 'WHO_ICD10', 'local_path': str(p)})
            return list(WHOAdapter().parse(snapshot))

    def test_nested_blocks_and_raw_rubrics_are_retained(self):
        records = self.parse()
        nodes = [r for r in records if r['record_type'] == 'node']
        core = canonical_tree(nodes)
        child = next(x for x in core if x['code'] == 'C00')
        self.assertEqual(2, len(child['block_path']))
        self.assertEqual('02', next(x for x in core if x['level'] == 'chapter')['code'])
        self.assertEqual(3, len(TaxonomyReader(core).ancestors(child['node_id'])))
        self.assertIsNone(child['valid_from'])
        self.assertEqual(['M'], child['coding_attributes']['modifiers'])
        self.assertEqual(1, sum(x['record_type'] == 'auxiliary' for x in records))
        exclusion = next(x for x in records if x.get('rubric_kind') == 'exclusion')
        self.assertEqual('C43.0', exclusion['references'][0]['code_raw'])

    def test_conflicting_or_missing_parent_fails(self):
        for modified in [XML.replace('SuperClass code="C00-C75"', 'SuperClass code="missing"'),
                         XML.replace('<SubClass code="C00"/>', ''),
                         XML.replace('SuperClass code="C00-C75"', 'SuperClass code="C00"')]:
            with self.assertRaises(FoundationError):
                canonical_tree([r for r in self.parse(modified) if r['record_type'] == 'node'])

    def test_duplicate_code_and_entity_declaration_fail(self):
        for xml in [XML.replace('</ClaML>', '<Class code="C00" kind="category"/></ClaML>'),
                    '<!DOCTYPE x [<!ENTITY e "abc">]>' + XML]:
            with self.assertRaises(FoundationError):
                list(self.parse(xml))

    def test_no_preferred_label_cannot_become_verified(self):
        rows = self.parse(XML.replace('kind="preferred"', 'kind="inclusion"'))
        with self.assertRaises(FoundationError):
            canonical_tree([r for r in rows if r['record_type'] == 'node'])

    def test_preferred_coding_reference_is_not_part_of_disease_name(self):
        rows = self.parse(XML.replace('Malignant neoplasm of lip</Label>',
                         'Malignant neoplasm of lip<Reference code="C43.0">C43.0</Reference></Label>'))
        source = next(r for r in rows if r['record_type'] == 'node' and r['code'] == 'C00')
        self.assertEqual('Malignant neoplasm of lip', source['preferred_labels']['en']['text'])
        rubric = next(r for r in rows if r.get('source_node_id') == source['source_node_id'] and r.get('rubric_kind') == 'preferred')
        self.assertEqual('C43.0', rubric['references'][0]['code_raw'])
        self.assertIn('<Reference', rubric['text_raw'])
