import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unicodedata
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from label_chunks import detect_language, label_chunks, language_decision


class LabelTests(unittest.TestCase):
    def test_three_languages(self):
        for text, expected in [('Người bệnh cần điều trị.', 'vi'),
                               ('The patient needs treatment.', 'en'),
                               ('患者需要接受治疗。', 'zh'),
                               ('患者需要接受治療。', 'zh'),
                               (unicodedata.normalize('NFD', 'Tiếng Việt có dấu'), 'vi'),
                               ('English và tiếng Việt', 'vi'),
                               ('Tiếng Việt và 中文', 'vi'), ('123', 'en')]:
            self.assertEqual(detect_language(text), expected)

    def test_foreign_names_do_not_override_english_context(self):
        for text in [
            'Guillain-Barré syndrome and serum activities.',
            'The patients were evaluated according to Sempé after treatment.',
            'Café-au-lait spots are associated with this disease.',
            'The patient named Đorđe was treated for this disease.',
            unicodedata.normalize('NFD', 'The patient has Guillain-Barré syndrome.'),
        ]:
            with self.subTest(text=text):
                self.assertEqual(detect_language(text), 'en')

    def test_vietnamese_context_with_english_medical_terms(self):
        for text in ['Bé bị táo bón.', 'Bệnh Guillain-Barré cần được điều trị.',
                     'Kết quả clinical study cho thấy người bệnh cần điều trị.',
                     'Bác sĩ giải thích thuật ngữ 糖尿病 cho người bệnh.']:
            with self.subTest(text=text):
                self.assertEqual(detect_language(text), 'vi')

    def test_dominant_script_instead_of_single_han_character(self):
        self.assertEqual(detect_language(
            'The study compared patients with diabetes (糖尿病) before and after treatment.'), 'en')
        self.assertEqual(detect_language(
            '糖尿病患者需要定期检查血糖，医生会根据检查结果调整治疗。HbA1c and glucose levels.'), 'zh')

    def test_english_title_does_not_override_non_english_body(self):
        text = ('Probing mechanisms and improving management of glaucoma.\n\n'
                "Les patients ont été étudiés. Les médicaments ont été comparés. "
                "Ces résultats sont associés à des taux d'échec plus bas. " * 4)
        # Other Latin languages are outside the three-label contract; do not
        # automatically move this legacy-accent case to the EN search field.
        self.assertTrue(language_decision(text)[1])

    def test_substantial_bilingual_body_needs_review(self):
        text = ('脑出血\n\n'
                'The patients with this disease were treated with medication. ' * 8 +
                '对于脑出血后抗凝剂及抗血小板药物的应用应当慎重，医生需要根据病情调整治疗方案。')
        self.assertTrue(language_decision(text)[1])

    def test_greek_symbols_do_not_become_latin_words(self):
        from label_chunks import LATIN_WORD
        self.assertEqual(LATIN_WORD.findall('IL-β, தமிழ், α: Barré'), ['IL', 'Barré'])

    def test_stream_preserves_source_ids_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            root = Path(folder)
            source, output, summary = root/'source.jsonl', root/'labels.jsonl', root/'summary.json'
            rows = [{'doc_id': i, 'chunk_id': f'c{i}', 'content': text}
                    for i, text in enumerate(['Người bệnh cần điều trị.', 'Clinical treatment.', '患者需要治疗。'])]
            source.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
            original = source.read_bytes()
            result = label_chunks(source, output, summary)
            labels = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([r['chunk_id'] for r in labels], [r['chunk_id'] for r in rows])
            self.assertEqual([r['language'] for r in labels], ['vi', 'en', 'zh'])
            self.assertEqual(result['total_rows'], 3)
            self.assertEqual(result['source_sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(FileExistsError):
                label_chunks(source, output, summary)
            with self.assertRaises(ValueError):
                label_chunks(source, source, root/'other.json')
            source.write_text('{"doc_id":1,"chunk_id":"x"}\n')
            with self.assertRaises(KeyError):
                label_chunks(source, root/'bad.jsonl', root/'bad.summary.json')
            self.assertFalse((root/'bad.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
