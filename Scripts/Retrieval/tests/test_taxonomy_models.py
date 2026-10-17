import json
import unittest

from sbtc.Scripts.Retrieval.taxonomy.models import (
    FoundationError, NodeKey, canonical_json, digest, edition_id, identifier,
)


class IdentityTests(unittest.TestCase):
    def test_canonical_bytes_preserve_unicode_and_sort_keys(self):
        self.assertEqual(canonical_json({'z': 'đái tháo đường', 'a': 1}),
                         '{"a":1,"z":"đái tháo đường"}'.encode())

    def test_nonfinite_numbers_rejected(self):
        for value in [float('nan'), float('inf'), float('-inf')]:
            with self.assertRaises((ValueError, FoundationError)):
                canonical_json({'score': value})

    def test_edition_is_order_independent_and_content_sensitive(self):
        one = {'role': 'claml', 'content_sha256': digest(b'a')}
        two = {'role': 'tabular', 'content_sha256': digest(b'b')}
        self.assertEqual(edition_id('2019', [one, two]), edition_id('2019', [two, one]))
        self.assertNotEqual(edition_id('2019', [one]), edition_id('2019', [two]))
        with self.assertRaises(FoundationError):
            edition_id('unknown', [one])
        with self.assertRaises(FoundationError):
            edition_id('2019', [{'role': 'claml', 'content_sha256': 'guessed'}])

    def test_node_identity_uses_system_edition_level_and_code(self):
        key = NodeKey('WHO_ICD10', 'pinned-edition', 'category', 'E11')
        expected = 'icdnode:' + digest(canonical_json([
            'WHO_ICD10', 'pinned-edition', 'category', 'E11']))
        self.assertEqual(key.identifier, expected)
        self.assertNotEqual(key.identifier, NodeKey('WHO_ICD10', 'pinned-edition', 'block', 'E11').identifier)
        self.assertNotEqual(key.identifier, NodeKey('BYT_ICD10', 'pinned-edition', 'category', 'E11').identifier)

    def test_source_provenance_does_not_change_lexical_identity(self):
        fields = ['vi', 'tiểu đường', 'sense:diabetes-group', 'colloquial_alias']
        self.assertEqual(identifier('lex', fields), 'lex:' + digest(canonical_json(fields)))
        self.assertNotEqual(identifier('lex', fields), identifier('lex', [*fields[:2], 'sense:other', fields[3]]))

    def test_invalid_level_and_empty_key_rejected(self):
        for args in [('WHO_ICD10', '', 'category', 'E11'),
                     ('WHO_ICD10', 'e', 'guess', 'E11'),
                     ('WHO_ICD10', 'e', 'category', '')]:
            with self.assertRaises(FoundationError):
                NodeKey(*args)


if __name__ == '__main__':
    unittest.main()
