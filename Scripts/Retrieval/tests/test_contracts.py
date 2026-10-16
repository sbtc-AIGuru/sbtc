import json
import tempfile
import unittest
from pathlib import Path

from sbtc.Scripts.Retrieval.analyzers import MedicalAnalyzer
from sbtc.Scripts.Retrieval.evaluation import evaluate, matches_chunk
from sbtc.Scripts.Retrieval.lexicon import Lexicon
from sbtc.Scripts.Retrieval.query import QueryProjector
from sbtc.Scripts.Retrieval.translation import validate_provenance, write_translation_cache
from sbtc.Scripts.Retrieval.utils import sha_bytes


class ContractTests(unittest.TestCase):
    def test_lcs_subsequence_and_boundary(self):
        self.assertTrue(matches_chunk('a x c','a b c d e'))
        self.assertFalse(matches_chunk('a','a b c d e'))
        self.assertFalse(matches_chunk('c a','a b c d e'))
        self.assertTrue(matches_chunk('糖尿病','糖尿病'))
        self.assertFalse(matches_chunk('患有糖尿病','糖尿病'))

    def test_many_to_many_doc_scope_macro(self):
        gold=[{'id':1,'relevant_docs':['583'],'relevant_chunks':[{'doc_id':'583','chunk_text':'a b c d e'},{'doc_id':'583','chunk_text':'a x c y z'}]},
              {'id':2,'relevant_docs':['684'],'relevant_chunks':[{'doc_id':'684','chunk_text':'one two three four five'}]}]
        pred=[{'id':1,'relevant_docs':['583','999'],'relevant_chunks':[{'doc_id':'583','chunk_text':'a c'},{'doc_id':'999','chunk_text':'a b c d e'}]},
              {'id':2,'relevant_docs':[],'relevant_chunks':[]}]
        result=evaluate(pred,gold)
        self.assertAlmostEqual(result['macro']['documents']['precision'],.25)
        self.assertAlmostEqual(result['macro']['documents']['recall'],.5)
        self.assertAlmostEqual(result['macro']['documents']['f2'],5/12)
        self.assertEqual(result['per_query'][0]['chunks']['recall'],1)
        self.assertEqual(result['per_query'][0]['chunks']['precision'],.5)

    def test_model_manifest_limits(self):
        valid={'model_id':'contract-fixture-not-model','revision':'a'*40,'license':'test-only','parameters':100,'release_date':'2020-01-01','open_weights':True}
        validate_provenance(valid)
        for key,value in [('parameters',15_000_000_001),('open_weights',False),('release_date','2026-08-01'),('revision','main')]:
            with self.assertRaises(ValueError):validate_provenance({**valid,key:value})

    def test_cache_contract_and_numeric_guard(self):
        # A fake translator tests the cache contract only; not model correctness.
        class FixtureTranslator:
            provenance={'model_id':'contract-fixture-not-model','revision':'a'*40,'license':'test-only','parameters':100,'release_date':'2020-01-01','open_weights':True}
            def translate(self,texts):return [{'en':'diabetes 500 mg','zh':'糖尿病 500 mg'} for text in texts]
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'cache.jsonl'
            count=write_translation_cache(iter([{'query':'đái tháo đường 500 mg'},{'query':'đái tháo đường 500 mg'}]),FixtureTranslator(),p,batch_size=1)
            self.assertEqual(count,1)
            a=MedicalAnalyzer(Lexicon())
            runs,warnings=QueryProjector(a,p).project('đái tháo đường 500 mg')
            self.assertTrue(any(channel.startswith('translation') for _,channel,_ in runs))
            self.assertEqual(warnings,[])
            item=json.loads(p.read_text());item['translations']['zh']='糖尿病';p.write_text(json.dumps(item))
            _,warnings=QueryProjector(a,p).project('đái tháo đường 500 mg')
            self.assertTrue(any('number_guard' in warning for warning in warnings))
            item['query_sha256']=sha_bytes(b'different');p.write_text(json.dumps(item))
            with self.assertRaises(ValueError):QueryProjector(a,p)

if __name__=='__main__':unittest.main()
