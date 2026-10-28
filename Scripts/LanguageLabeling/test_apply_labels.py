import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_labels import apply_labels


class ApplyTests(unittest.TestCase):
    def test_apply_preserves_fields_and_backup(self):
        self.check_apply(mismatch=False)

    def test_mismatch_keeps_source_unchanged(self):
        self.check_apply(mismatch=True)

    def check_apply(self, mismatch):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            root = Path(folder)
            source, labels, verification = root/'data.jsonl', root/'labels.jsonl', root/'verification.json'
            rows = [{'doc_id': i, 'chunk_id': f'c{i}', 'content': text, 'token_count': 2,
                     'content_origin': 'test'} for i, text in enumerate(['Tiếng Việt', 'English', '中文'])]
            predictions = [{'doc_id': i, 'chunk_id': f'c{i}', 'language': lang}
                           for i, lang in enumerate(['vi', 'en', 'zh'])]
            if mismatch:
                predictions[1]['chunk_id'] = 'wrong'
            source.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows))
            labels.write_text(''.join(json.dumps(row)+'\n' for row in predictions))
            original = source.read_bytes()
            verification.write_text(json.dumps({'source_sha256': hashlib.sha256(original).hexdigest(),
                'labels_sha256': hashlib.sha256(labels.read_bytes()).hexdigest(), 'rows': 3,
                'counts': {'vi': 1, 'en': 1, 'zh': 1}}))
            if mismatch:
                with self.assertRaises(ValueError):
                    apply_labels(source, labels, verification, root/'output')
                self.assertEqual(source.read_bytes(), original)
                return
            result = apply_labels(source, labels, verification, root/'output')
            enriched = [json.loads(line) for line in source.read_text().splitlines()]
            self.assertEqual(enriched, [dict(row, language=lang) for row, lang in zip(rows, ['vi','en','zh'])])
            self.assertEqual(Path(result['backup']).read_bytes(), original)
            self.assertTrue(result['all_original_fields_verified'])


if __name__ == '__main__':
    unittest.main()
