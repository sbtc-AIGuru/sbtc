import json
import tempfile
import unittest
from pathlib import Path

from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer, exact_tokens
from BackEnd.app.Retrieval.corpus import union_body, languages
from BackEnd.app.Retrieval.engine import fuse
from BackEnd.app.Retrieval.export import btc_normalized
from BackEnd.app.Retrieval.lexicon import Lexicon
from BackEnd.app.Retrieval.models import Hit
from BackEnd.app.Retrieval.query import QueryProjector, iter_queries
from BackEnd.app.Retrieval.utils import source_id, sha_bytes


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lexicon = Lexicon()
        cls.analyzer = MedicalAnalyzer(cls.lexicon)

    def test_integer_identity(self):
        self.assertEqual(source_id(7156587), 7156587)
        for invalid in (True, 1.0, '583', -1, 2**63):
            with self.assertRaises(ValueError): source_id(invalid)

    def test_micrograms(self):
        self.assertIn('10mcg', exact_tokens('10 μg'))
        self.assertIn('10mcg', exact_tokens('10 µg'))
        self.assertIn('10mg', exact_tokens('10 mg'))
        self.assertNotIn('10mg', exact_tokens('10 μg'))

    def test_identifiers(self):
        tokens = exact_tokens('J18.9 HbA1c HLA-B*15:02 BRCA-1')
        for token in ('j18.9', 'hba1c', 'hla-b*15:02', 'brca-1', 'brca1'):
            self.assertIn(token, tokens)

    def test_unicode_boundaries_keep_literals_adjacent_to_han(self):
        tokens = exact_tokens(
            '诊断编码J18.9；给予阿莫西林500 mg。检查IL-6及SpO2；'
            '血糖5.17 mmol/L，剂量10 μg/kg。'
        )
        for token in ('j18.9', '500mg', 'il-6', 'il6', 'spo2', '5.17mmol/l', '10mcg/kg'):
            self.assertIn(token, tokens)
        self.assertNotIn('17mmol/l', tokens)

    def test_dose_after_list_separator_is_kept_without_splitting_decimal(self):
        tokens = exact_tokens('血糖5.17mmol/L，下一项,5 mg')
        self.assertIn('5.17mmol/l', tokens)
        self.assertIn('5mg', tokens)
        self.assertNotIn('17mmol/l', tokens)

    def test_unicode_width_is_normalized_before_literal_extraction(self):
        tokens = exact_tokens('诊断编码Ｊ１８．９；剂量５００ｍｇ')
        self.assertIn('j18.9', tokens)
        self.assertIn('500mg', tokens)

    def test_acronym_case_not_grounding(self):
        self.assertIn('case_upper_all', exact_tokens('ALL'))
        self.assertNotIn('case_upper_all', exact_tokens('all'))
        self.assertEqual(self.lexicon.anchors('ALL COLD MI OR WAS', 'en'), ())

    def test_english_section_headings_do_not_get_acronym_markers(self):
        tokens = exact_tokens('ABSTRACT BACKGROUND METHODS RESULTS SETTING OUTCOME CASE')
        for heading in ('abstract', 'background', 'methods', 'results', 'setting', 'outcome', 'case'):
            self.assertNotIn(f'case_upper_{heading}', tokens)

    def test_mixed_han_and_known_english_medical_term_is_searchable(self):
        for index_mode in (False, True):
            fields = self.analyzer.analyze('糖尿病患者服用metformin', 'zh', index_mode=index_mode).fields
            self.assertIn('metformin', fields['exact'])
            self.assertIn('local:diabetes', fields['anchors'])
            self.assertIn('local:metformin', fields['anchors'])

    def test_unknown_latin_word_adjacent_to_han_is_not_promoted_or_grounded(self):
        fields = self.analyzer.analyze('糖尿病患者服用newdrug', 'zh', index_mode=True).fields
        self.assertNotIn('newdrug', fields['exact'])
        self.assertNotIn('case_upper_newdrug', fields['exact'])
        self.assertNotIn('local:newdrug', fields['anchors'])

    def test_concept_across_languages(self):
        for language, text in [('vi','đái tháo đường'), ('en','diabetes mellitus'), ('zh','糖尿病')]:
            self.assertIn('local:diabetes', self.lexicon.anchors(text, language))
        self.assertNotIn('local:metformin', self.lexicon.anchors('premetforminized','en'))

    def test_traditional_conversion(self):
        self.assertIn('local:hypertension', self.lexicon.anchors('高血壓', 'zh'))

    def test_vietnamese_granularity(self):
        fields = self.analyzer.analyze('Bệnh nhân suy thận mạn.', 'vi', index_mode=True).fields
        self.assertIn('suy_thận_mạn', fields['contents'])
        self.assertIn('suy_thận', fields['broad'])
        self.assertNotIn('folded', fields)
        self.assertFalse({'than', 'man'} & set(fields['broad']))

    def test_vietnamese_fixed_word_with_unmatched_parenthesis_is_literal(self):
        analysis = self.analyzer.analyze('Xenlulo (chứa trong thực vật).', 'vi', index_mode=True)
        self.assertIn('thực', analysis.fields['broad'])
        self.assertIn('vật', analysis.fields['broad'])

    def test_vietnamese_unaccented_query_has_no_folded_rescue(self):
        from BackEnd.app.Retrieval.models import FIELDS
        self.assertNotIn('folded', FIELDS)
        runs, _ = QueryProjector(self.analyzer).project('tang huyet ap')
        self.assertFalse(any('folded' in fields for _, _, fields in runs))
        accented = self.analyzer.analyze('tăng huyết áp', 'vi', index_mode=True).fields
        self.assertFalse({'tang', 'huyet', 'ap'} & set(accented['broad']))
        self.assertIn('tăng', accented['broad'])

    def test_sentence_boundary_shingles(self):
        fields = self.analyzer.analyze('viêm phổi. Điều trị tốt.', 'vi', index_mode=True).fields
        self.assertNotIn('phổi_điều', fields['broad'])

    def test_chinese_index_query(self):
        text = '社区获得性肺炎 无发热'
        index = self.analyzer.analyze(text, 'zh', index_mode=True).fields
        query = self.analyzer.analyze(text, 'zh', index_mode=False).fields
        self.assertIn('社区获得性肺炎', index['contents'])
        self.assertIn('肺炎', index['broad'])
        self.assertTrue(set(query['contents']) <= set(index['contents']))
        self.assertIn('发热', query['broad'])

    def test_english_intent_negation(self):
        fields = self.analyzer.analyze('No evidence of haemoglobin abnormalities in BRCA-1 patients.', 'en', index_mode=True).fields
        self.assertIn('no', fields['contents'])
        self.assertIn('hemoglobin', fields['broad'])
        self.assertIn('brca-1', fields['exact'])
        self.assertNotIn('mg', fields['exact'])

    def test_union_overlap(self):
        def c(start,text): return {'start_char':start,'end_char':start+len(text),'chunk_text':text}
        self.assertEqual(union_body([c(0,'abcdef'),c(3,'defghi'),c(1,'bc')]),'abcdefghi')
        self.assertEqual(union_body([c(0,'abc'),c(5,'xyz')]),'abc\n\nxyz')
        with self.assertRaises(ValueError): union_body([c(0,'abc'),c(2,'Xyz')])

    def test_languages(self):
        self.assertEqual(languages('糖尿病'), ('zh',))
        self.assertEqual(languages('đái tháo đường'), ('vi',))
        self.assertEqual(languages('abc'), ('en','vi'))

    def test_rank_fusion(self):
        a = fuse([('vi','one',[Hit('x',100,1)]),('vi','two',[Hit('x',2,1)]),('zh','one',[Hit('y',1,1)])],maximum=5)
        self.assertAlmostEqual(a[0]['fusion_score'],a[1]['fusion_score'])
        self.assertEqual(len(a),2)
        b = fuse([('vi','one',[Hit('x',1,1),Hit('x',1,1)])],maximum=5)
        self.assertAlmostEqual(b[0]['fusion_score'],1/61)

    def test_btc_normalization_order(self):
        self.assertEqual(btc_normalized(' Ａ &amp; B\nC '),'a & b c')

    def test_projection_preserves_intent(self):
        runs,warnings = QueryProjector(self.analyzer).project('điều trị đái tháo đường 500 mg')
        self.assertTrue(any(lang=='en' for lang,_,_ in runs))
        self.assertTrue(any(lang=='zh' for lang,_,_ in runs))
        self.assertTrue(any('điều_trị' in fields.get('contents',()) for lang,_,fields in runs if lang=='vi'))
        self.assertTrue(warnings)
        self.assertEqual(QueryProjector(self.analyzer).project(' '),([],[]))

    def test_invalid_cache_and_duplicate_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'cache.jsonl'
            p.write_text(json.dumps({'query_sha256':sha_bytes(b'foo'),'translations':{'en':'foo'},'provenance':{'model_id':'closed'}}))
            with self.assertRaises(ValueError): QueryProjector(self.analyzer,p)
            p=Path(temp)/'queries.jsonl';p.write_text('{"id":1,"query":"x"}\n{"id":1,"query":"y"}\n')
            with self.assertRaises(ValueError): list(iter_queries(p))

    def test_segmentation_terms_loaded_without_hallucinating_anchors(self):
        # 1. Segmentation terms are loaded
        vi_terms = self.lexicon.segmentation_terms("vi")
        zh_terms = self.lexicon.segmentation_terms("zh")
        self.assertGreater(len(vi_terms), 1000)
        self.assertGreater(len(zh_terms), 1000)

        # 2. Chinese segmentation term guides cut without creating fake concept anchor
        zh_text = "患者患有重症肌无力。"
        zh_analysis = self.analyzer.analyze(zh_text, "zh", index_mode=True)
        self.assertIn("重症肌无力", zh_analysis.fields["contents"])
        # Ensure '重症肌无力' (which is not in concepts.json) did NOT invent a fake anchor
        self.assertNotIn("local:重症肌无力", zh_analysis.fields["anchors"])

        # 3. Vietnamese segmentation term guides compound tokenization without fake anchor
        vi_text = "bệnh nhân bị suy hô hấp và viêm màng não"
        vi_analysis = self.analyzer.analyze(vi_text, "vi", index_mode=True)
        self.assertIn("suy_hô_hấp", vi_analysis.fields["contents"])
        self.assertIn("viêm_màng_não", vi_analysis.fields["contents"])
        self.assertNotIn("local:suy_hô_hấp", vi_analysis.fields["anchors"])

        # 4. English segmentation term guides compound bonding without fake anchor
        en_terms = self.lexicon.segmentation_terms("en")
        self.assertGreater(len(en_terms), 100000)
        en_text = "Patient with acute myeloid leukemia and triple negative breast cancer."
        en_analysis = self.analyzer.analyze(en_text, "en", index_mode=True)
        self.assertIn("acute_myeloid_leukemia", en_analysis.fields["contents"])
        self.assertIn("triple_negative_breast_cancer", en_analysis.fields["contents"])
        self.assertIn("acute", en_analysis.fields["broad"])
        self.assertIn("leukemia", en_analysis.fields["broad"])
        self.assertNotIn("local:acute_myeloid_leukemia", en_analysis.fields["anchors"])

    def test_longest_first_segmentation_greedy_order(self):
        matches = self.lexicon.segmentation_matches("bệnh nhân đái tháo đường typ 2", "vi")
        if "đái tháo đường typ 2" in matches and "đái tháo đường" in matches:
            idx_long = matches.index("đái tháo đường typ 2")
            idx_short = matches.index("đái tháo đường")
            self.assertLess(idx_long, idx_short)


if __name__ == '__main__': unittest.main()
