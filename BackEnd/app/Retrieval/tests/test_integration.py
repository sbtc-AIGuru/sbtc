import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer
from BackEnd.app.Retrieval.backend import LuceneBackend, build_indexes
from BackEnd.app.Retrieval.corpus import CorpusPreparer
from BackEnd.app.Retrieval.engine import CandidateEngine
from BackEnd.app.Retrieval.export import export_submission
from BackEnd.app.Retrieval.lexicon import Lexicon
from BackEnd.app.Retrieval.query import QueryProjector
from BackEnd.app.Retrieval.rolling import RollingIndexer
from BackEnd.app.Retrieval.store import TextStore


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        import pyarrow.parquet as pq
        cls.temp = tempfile.TemporaryDirectory(prefix='bm25-test20k-')
        cls.path = Path(cls.temp.name)
        cls.records = {}
        failed = None
        for shard in sorted(Path('data_final/chunks_format_v3_r3_reserve_test20k').glob('part-*.jsonl')):
            with shard.open() as f:
                for line in f:
                    r=json.loads(line)
                    if r['status'] != 'ok' and failed is None: failed=r
                    lang=r.get('source_language')
                    if lang in ('vi','en','zh') and lang not in cls.records and r['status']=='ok' and r['children']:
                        cls.records[lang]=r
                    if len(cls.records)==3 and failed is not None: break
            if len(cls.records)==3 and failed is not None: break
        if len(cls.records)!=3: raise RuntimeError('Missing actual three-language test20k fixtures')
        cls.input=cls.path/'input';cls.input.mkdir()
        cls.source=cls.input/'part-000000.jsonl'
        cls.source.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in [*cls.records.values(),failed]))
        cls.corpus=cls.path/'corpus.parquet'
        pq.write_table(pa.Table.from_pylist([{'id':r['doc_id'],'url':r['url']} for r in [*cls.records.values(),failed]]),cls.corpus)
        cls.root=cls.path/'run'
        cls.analyzer=MedicalAnalyzer(Lexicon())
        cls.prepare=CorpusPreparer(cls.analyzer)
        cls.manifest=cls.prepare.prepare(cls.input,cls.root,cls.corpus)
        build_indexes(cls.root)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_actual_three_language_indexes(self):
        b=LuceneBackend(self.root)
        try:
            for lang,r in self.records.items():
                fields=self.analyzer.analyze(r['children'][0]['chunk_text'],lang,index_mode=False).fields
                hits=b.search('chunks',lang,{'contents':fields['contents'][:30]},k=20)
                self.assertIn(r['children'][0]['chunk_id'],[h.identifier for h in hits])
        finally:b.close()

    def test_rolling_matches_bulk_on_actual_test20k_sample(self):
        rolling_root = self.path / 'rolling-actual-sample'
        manifest = RollingIndexer(
            self.analyzer,
            staging_target_bytes=10_000,
            staging_max_bytes=1_000_000,
            control_reserve_bytes=16_384,
            writer_ram_buffer_mib=1,
            disk_reserve_bytes=0,
        ).run(self.input, rolling_root, self.corpus)
        self.assertEqual(manifest['status'], 'READY')
        for key in set(manifest['counts']) | set(self.manifest['counts']):
            self.assertEqual(manifest['counts'].get(key, 0), self.manifest['counts'].get(key, 0), key)
        self.assertEqual(len(manifest['indexes']), 6)

        bulk = LuceneBackend(self.root)
        rolling = LuceneBackend(rolling_root)
        try:
            for language, record in self.records.items():
                query_text = record['children'][0]['chunk_text']
                analyzed = self.analyzer.analyze(query_text, language, index_mode=False).fields
                fields = {name: analyzed[name] for name in ('contents', 'broad', 'exact', 'anchors', 'title') if analyzed.get(name)}
                for granularity in ('documents', 'chunks'):
                    expected = bulk.search(granularity, language, fields, k=20)
                    actual = rolling.search(granularity, language, fields, k=20)
                    self.assertEqual([hit.identifier for hit in actual], [hit.identifier for hit in expected])
                    for got, want in zip(actual, expected):
                        self.assertAlmostEqual(got.score, want.score, delta=1e-5)
        finally:
            bulk.close()
            rolling.close()

        with TextStore(rolling_root / 'metadata.sqlite') as store:
            for record in self.records.values():
                for child in record['children']:
                    if child.get('retrieval_eligible', True) and child['chunk_text'].strip():
                        self.assertEqual(store.get(child['chunk_id'])['chunk_text'], child['chunk_text'])

    def test_parallel_search_partition_and_rank_parity(self):
        from concurrent.futures import ThreadPoolExecutor
        b=LuceneBackend(self.root)
        queries={lang:self.analyzer.analyze(r['children'][0]['chunk_text'],lang,index_mode=False).fields['contents'][:20] for lang,r in self.records.items()}
        jobs=[(g,l) for _ in range(20) for g,l in b.searchers]
        def run(job):
            g,language=job
            return b.search(g,language,{'contents':queries[language]},k=10)
        try:
            serial=[run(job) for job in jobs]
            with ThreadPoolExecutor(4) as pool:parallel=list(pool.map(run,jobs))
            self.assertEqual(parallel,serial)
            for (granularity,_),hits in zip(jobs,parallel):
                self.assertTrue(all((':' in hit.identifier)==(granularity=='chunks') for hit in hits))
        finally:b.close()

    def test_pointer_verbatim_and_order(self):
        with TextStore(self.root/'metadata.sqlite') as store:
            for r in self.records.values():
                for child in r['children']:
                    if child.get('retrieval_eligible',True) and child['chunk_text'].strip():
                        hydrated=store.get(child['chunk_id'])
                        self.assertEqual(hydrated,{'doc_id':str(r['doc_id']),'chunk_order':child['chunk_order'],'chunk_text':child['chunk_text']})

    def test_resume(self):
        before=self.manifest['counts']
        self.assertEqual(self.prepare.prepare(self.input,self.root,self.corpus)['counts'],before)
        build_indexes(self.root)
        with TextStore(self.root/'metadata.sqlite') as s:
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],4)

    def test_source_mutation_rejected(self):
        import os
        stat=self.source.stat()
        os.utime(self.source,ns=(stat.st_atime_ns,stat.st_mtime_ns+1_000_000))
        try:
            with TextStore(self.root/'metadata.sqlite') as store:
                with self.assertRaisesRegex(RuntimeError,'SourceChanged'):store.validate_sources()
        finally:os.utime(self.source,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_record_hash_rejected_even_if_stat_restored(self):
        import os
        payload=self.source.read_bytes();stat=self.source.stat()
        # Work only on the temporary source copy, never the original corpus.
        modified=payload.replace(b'http',b'xttp',1)
        self.assertNotEqual(modified,payload)
        self.source.write_bytes(modified)
        os.utime(self.source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        try:
            with TextStore(self.root/'metadata.sqlite') as store:
                child=next(iter(self.records.values()))['children'][0]['chunk_id']
                with self.assertRaisesRegex(RuntimeError,'hash mismatch'):store.get(child)
        finally:
            self.source.write_bytes(payload)
            os.utime(self.source,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_mapping_errors_fail(self):
        import copy
        record=next(iter(self.records.values()))
        cases={
            'url':lambda r:r.update(url='https://invalid.example/not-source'),
            'foreign-key':lambda r:r['children'][0].update(doc_id=r['doc_id']+1),
            'order':lambda r:r['children'][0].update(chunk_order=-1),
            'offset':lambda r:r['children'][0].update(end_char=r['children'][0]['end_char']-1),
        }
        for name,mutate in cases.items():
            with self.subTest(name=name):
                broken=copy.deepcopy(record);mutate(broken)
                input_dir=self.path/('invalid-'+name);input_dir.mkdir()
                (input_dir/'part-000000.jsonl').write_text(json.dumps(broken,ensure_ascii=False)+'\n')
                with self.assertRaises(ValueError):self.prepare.prepare(input_dir,self.path/('run-'+name),self.corpus)

    def test_fingerprint_changes_rejected(self):
        from BackEnd.app.Retrieval.lexicon import DEFAULT_LEXICON
        data=json.loads(DEFAULT_LEXICON.read_text());data['metadata']['version']='changed-contract-fixture'
        p=self.path/'changed-lexicon.json';p.write_text(json.dumps(data))
        changed=CorpusPreparer(MedicalAnalyzer(Lexicon(p)))
        with self.assertRaisesRegex(RuntimeError,'fingerprint changed'):
            changed.prepare(self.input,self.root,self.corpus)

    def test_index_publish_recovery(self):
        from BackEnd.app.Retrieval.utils import atomic_json
        path=self.root/'manifest.json';manifest=json.loads(path.read_text())
        manifest['indexes'].pop('documents/vi');atomic_json(path,manifest)
        recovered=build_indexes(self.root)
        self.assertEqual(len(recovered['indexes']),6)

    def test_engine_batch_export(self):
        engine=CandidateEngine(LuceneBackend(self.root),QueryProjector(self.analyzer),TextStore(self.root/'metadata.sqlite'),per_language_docs=10,per_language_chunks=20,max_docs=20,max_chunks=30)
        try:
            query={'id':1,'query':'đái tháo đường metformin'}
            one=engine.search(query)
            batch=list(engine.search_batch([query,{'id':2,'query':''}]))
            self.assertEqual(one['documents'],batch[0]['documents'])
            self.assertEqual(one['chunks'],batch[0]['chunks'])
            self.assertEqual(batch[1]['chunks'],[])
            path=self.path/'candidates.jsonl';path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in batch))
            out=self.path/'submission.json';z=self.path/'submission.zip'
            export_submission(path,out,engine.store,{1,2},docs=10,chunks=20,zip_path=z)
            self.assertEqual(len(json.loads(out.read_text())),2)
            with zipfile.ZipFile(z) as archive:self.assertEqual(archive.namelist(),['submission.json'])
            with self.assertRaisesRegex(ValueError,'Missing'):
                export_submission(path,self.path/'missing.json',engine.store,{1,2,3},docs=10,chunks=20)
        finally:engine.close()

if __name__=='__main__':unittest.main()
