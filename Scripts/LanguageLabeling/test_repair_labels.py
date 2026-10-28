import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from Scripts.LanguageLabeling.repair_labels import apply, elastic_id, plan
from BackEnd.app.Database.elastic_search import PIPELINE


class RepairTests(unittest.TestCase):
    def make_plan(self, root):
        source, labels = root / 'source.jsonl', root / 'labels.jsonl'
        rows = [
            {'doc_id': 1, 'chunk_id': 'en-name', 'content':
             'The patient has Guillain-Barré syndrome and needs treatment.', 'token_count': 12},
            {'doc_id': 2, 'chunk_id': 'vi', 'content': 'Người bệnh cần điều trị.'},
            {'doc_id': 3, 'chunk_id': 'zh', 'content': '患者需要接受治疗。'},
        ]
        source.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
        labels.write_text(''.join(json.dumps({
            'doc_id': row['doc_id'], 'chunk_id': row['chunk_id'], 'language': lang,
        }) + '\n' for row, lang in zip(rows, ['vi', 'vi', 'zh'], strict=True)))
        original = source.read_bytes()
        output = root / 'plan'
        with contextlib.redirect_stdout(io.StringIO()):
            result = plan(source, labels, output)
        self.assertEqual(source.read_bytes(), original)
        return rows, output, result

    def test_plan_only_changes_language_and_preserves_all_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            rows, output, result = self.make_plan(Path(folder))
            labels = [json.loads(raw) for raw in (output / 'labels.v2.jsonl').read_text().splitlines()]
            changes = [json.loads(raw) for raw in (output / 'changes.jsonl').read_text().splitlines()]
            self.assertEqual([row['chunk_id'] for row in labels], [row['chunk_id'] for row in rows])
            self.assertEqual([row['language'] for row in labels], ['en', 'vi', 'zh'])
            self.assertEqual(result['transitions'], {'vi->en': 1})
            self.assertEqual(changes[0]['content'], rows[0]['content'])
            self.assertFalse(result['content_and_vectors_changed'])

    def test_preflight_refuses_stale_content_before_any_bulk_update(self):
        with tempfile.TemporaryDirectory() as folder:
            rows, output, _ = self.make_plan(Path(folder))
            client = Mock()
            client.indices.get_settings.return_value = {'test': {'settings': {'index': {'uuid': 'uuid'}}}}
            client.indices.get_mapping.return_value = {'test': {'mappings': {'_meta': {'vibiomir_pipeline': PIPELINE}}}}
            client.count.return_value = {'count': 3}
            client.mget.return_value = {'docs': [{
                '_id': elastic_id(1, 'en-name'), 'found': True, '_seq_no': 4, '_primary_term': 1,
                '_source': {**rows[0], 'content': 'changed since plan', 'lang': 'vi'},
            }]}
            with patch('BackEnd.app.Database.elastic_search.connect_elasticsearch', return_value=client), \
                    patch('elasticsearch.helpers.streaming_bulk') as bulk:
                with self.assertRaisesRegex(ValueError, 'ES differs from plan'):
                    apply(output, 'test')
                bulk.assert_not_called()
            client.close.assert_called_once()

    def test_low_evidence_foreign_name_is_deferred_instead_of_rerouted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, labels = root / 'source.jsonl', root / 'labels.jsonl'
            source.write_text(json.dumps({'doc_id': 9, 'chunk_id': 'ambiguous',
                                          'content': 'René Sempé'}, ensure_ascii=False) + '\n')
            labels.write_text(json.dumps({'doc_id': 9, 'chunk_id': 'ambiguous', 'language': 'vi'}) + '\n')
            with contextlib.redirect_stdout(io.StringIO()):
                result = plan(source, labels, root / 'plan')
            self.assertEqual(result['changed'], 0)
            self.assertEqual(result['deferred_for_review'], 1)
            self.assertEqual(json.loads((root / 'plan' / 'labels.v2.jsonl').read_text())['language'], 'vi')
            self.assertEqual(json.loads((root / 'plan' / 'review.jsonl').read_text())['chunk_id'], 'ambiguous')

    def test_language_update_preserves_text_and_removes_stale_search_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            rows, output, _ = self.make_plan(Path(folder))
            original = {**rows[0], 'doc_id': '1', 'lang': 'vi', 'language': 'vi',
                        'content_vi': 'old preprocessed text', 'extra': {'retained': True}}
            record = {'_id': elastic_id(1, 'en-name'), 'found': True,
                      '_seq_no': 4, '_primary_term': 2, '_source': original.copy()}
            client = Mock()
            client.indices.get_settings.return_value = {'test': {'settings': {'index': {'uuid': 'uuid'}}}}
            client.indices.get_mapping.return_value = {'test': {'mappings': {'_meta': {'vibiomir_pipeline': PIPELINE}}}}
            client.count.return_value = {'count': 3}
            client.mget.side_effect = lambda **kwargs: {'docs': [record]}
            captured = []

            def bulk(client_arg, actions, **kwargs):
                for action in actions:
                    captured.append(action)
                    params = action['script']['params']
                    current = record['_source']
                    for field in params['fields']:
                        current.pop(field, None)
                    current['lang'] = current['language'] = params['language']
                    current[params['field']] = params['text']
                    yield True, {'update': {'_id': record['_id'], '_seq_no': 5, '_primary_term': 2}}

            with patch('BackEnd.app.Database.elastic_search.connect_elasticsearch', return_value=client), \
                    patch('elasticsearch.helpers.streaming_bulk', side_effect=bulk), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = apply(output, 'test')
            self.assertEqual(result['updated'], 1)
            self.assertEqual(result['verified'], 1)
            self.assertEqual(captured[0]['if_seq_no'], 4)
            self.assertEqual(captured[0]['if_primary_term'], 2)
            self.assertEqual(record['_source']['content'], original['content'])
            self.assertEqual(record['_source']['extra'], original['extra'])
            self.assertEqual(record['_source']['lang'], 'en')
            self.assertNotIn('content_vi', record['_source'])
            self.assertEqual(record['_source']['content_en'], original['content'])
            saved = json.loads((output / 'es-before.jsonl').read_text())
            self.assertEqual(saved['_source'], original)


if __name__ == '__main__':
    unittest.main()
