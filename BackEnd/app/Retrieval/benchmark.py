"""Engineering benchmark on test20k; not a labeled relevance benchmark."""
from __future__ import annotations

import argparse
import json
import resource
import statistics
import time
from pathlib import Path

from .analyzers import MedicalAnalyzer
from .backend import LuceneBackend
from .corpus import fingerprint
from .engine import CandidateEngine
from .lexicon import Lexicon
from .query import QueryProjector
from .store import TextStore
from .utils import atomic_json

QUERIES=('Điều trị đái tháo đường bằng metformin', 'Triệu chứng tăng huyết áp',
         'Điều trị suy thận mạn', 'Viêm phổi mắc phải cộng đồng ở trẻ em',
         'Nhồi máu cơ tim cấp', 'Bệnh phổi tắc nghẽn mạn tính',
         'Paracetamol 500 mg', 'Amoxicillin điều trị viêm phổi',
         'Vai trò BRCA1 và HER2 trong ung thư vú', 'HbA1c trong bệnh đái tháo đường',
         'Trẻ em sốt cao co giật sau tiêm vắc xin', '')


def run(root: Path,output: Path,*,count=1200):
    if count<1 or output.exists():raise ValueError('Count must be positive; use new report path')
    lexicon=Lexicon();analyzer=MedicalAnalyzer(lexicon)
    manifest=json.loads((root/'manifest.json').read_text())
    if fingerprint(lexicon)!=manifest['spec']['fingerprint']:raise ValueError('Analyzer snapshot mismatch')
    store=TextStore(root/'metadata.sqlite');store.validate_sources()
    engine=CandidateEngine(LuceneBackend(root),QueryProjector(analyzer),store)
    durations=[];rows=[];returned_docs=returned_chunks=warnings=0
    started=time.perf_counter()
    output.parent.mkdir(parents=True,exist_ok=True)
    sample=output.with_suffix('.samples.jsonl')
    if sample.exists():raise ValueError('Sample report already exists')
    try:
        with sample.open('x',encoding='utf-8') as f:
            for i,result in enumerate(engine.search_batch({'id':i+1,'query':QUERIES[i%len(QUERIES)]} for i in range(count))):
                durations.append(result['seconds']);returned_docs+=len(result['documents']);returned_chunks+=len(result['chunks']);warnings+=bool(result['warnings'])
                if i<len(QUERIES):
                    f.write(json.dumps(result,ensure_ascii=False)+'\n')
                    rows.append({'query':result['query'],'documents':len(result['documents']),'chunks':len(result['chunks']),'warnings':result['warnings']})
                if (i+1)%100==0:print(json.dumps({'queries':i+1,'seconds':time.perf_counter()-started}),flush=True)
        total=time.perf_counter()-started
        ordered=sorted(durations)
        atomic_json(output,{'queries':count,'distinct_queries':len(QUERIES),'wall_seconds':total,'queries_per_second':count/total,
                            'p50_seconds':statistics.median(durations),'p95_seconds':ordered[min(len(ordered)-1,int(.95*len(ordered)))],
                            'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            'total_returned_documents':returned_docs,'total_returned_chunks':returned_chunks,'queries_with_warnings':warnings,
                            'first_cycle':rows,'snapshot_spec_hash':manifest['spec_hash'],'relevance_metrics':None,
                            'limits':['Repeated 12 mechanical/user-example queries; warm tokenizer cache, not query diversity or cold-model workload.',
                                      'Actual six-index search every query; no qrels/for_valid; no translations/model inference.',
                                      'Linux peak RSS includes Python/native/JVM in this process, not full-corpus production memory.']})
    finally:engine.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--count',type=int,default=1200)
    args=parser.parse_args();run(args.run_dir,args.output,count=args.count)
