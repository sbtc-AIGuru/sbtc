"""Verify the completed import without printing corpus contents."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/nhminh/AI_Project/sbtc')
sys.path.insert(0, str(ROOT))

from BackEnd.app.Database.elastic_search import connect_elasticsearch, search_bm25

with connect_elasticsearch() as client:
    counts = client.search(index='vibiomir_bm25', size=0, track_total_hits=True,
                           aggs={'languages': {'terms': {'field': 'lang', 'size': 3}}})
    retrieval = {}
    for lang, query in [('vi', 'suy thận'), ('en', 'insulin deficiency'), ('zh', '腎功能')]:
        hits = search_bm25(query, lang, top_k=3, client=client)
        retrieval[lang] = {'hits': len(hits), 'ids': [hit['_id'] for hit in hits]}
        if not hits or any(hit['_source']['lang'] != lang for hit in hits):
            raise RuntimeError(f'Retrieval verification failed for {lang}')

result = {
    'completed_at': datetime.now(timezone.utc).isoformat(),
    'index': 'vibiomir_bm25',
    'documents': counts['hits']['total']['value'],
    'languages': {bucket['key']: bucket['doc_count'] for bucket in counts['aggregations']['languages']['buckets']},
    'retrieval': retrieval,
}
expected = json.loads((ROOT / 'Scripts/LanguageLabeling/output/ViBioMIR_chunk_languages.summary.json').read_text())
result['expected_documents'] = expected['total_rows']
result['counts_match'] = (result['documents'] == expected['total_rows']
                          and result['languages'] == expected['language_counts'])
Path(__file__).with_name('result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False), flush=True)
if not result['counts_match']:
    raise RuntimeError('Index counts differ from the source language summary; inspect result.json')
