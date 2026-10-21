"""Read source data; write derived audit artifacts only in this directory."""
import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import numpy as np
import orjson
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DOWNLOADS = Path('/home/nhminh/Downloads')
SOURCE = ROOT / '.backfill/kaggle_merged_upload_20261016_fw646a7p/merged.jsonl'
RUN = ROOT / 'artifacts/kaggle-retrieval/v6-completed/retrieval'


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def distribution(values):
    a = np.asarray(values)
    return dict(n=len(a), minimum=float(a.min()), maximum=float(a.max()),
                mean=float(a.mean()), **{f'p{p}': float(np.percentile(a, p)) for p in (5, 25, 50, 75, 90, 95, 99)})


def query_audit():
    from tokenizers import Tokenizer
    tokenizer_path = next((ROOT / 'artifacts/model-cache/models--Alibaba-NLP--gte-multilingual-base/snapshots').glob('*/tokenizer.json'))
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    files = list(DOWNLOADS.glob('*query*.parquet'))
    files += list((ROOT / 'artifacts/query-embeddings').glob('*.parquet'))
    versions, tables = {}, {}
    for path in files:
        table = pq.read_table(path)
        columns = [c for c in ('id', 'query', 'english', 'chinese', 'dense_weight') if c in table.column_names]
        rows = table.select(columns).to_pylist()
        tables[path.name] = {r['id']: r for r in rows}
        versions[path.name] = {'path': str(path), 'rows': len(rows),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'schema': str(table.schema), 'nulls': {c: table[c].null_count for c in columns},
            'duplicate_ids': len(rows) - len({r['id'] for r in rows})}
    rows = list(tables['query_rewritten_weighted.parquet'].values())
    original = tables['query.parquet']
    stats = {}
    per_query = []
    for col in ('query', 'english', 'chinese'):
        texts = [r[col] for r in rows]
        lengths = [len(s) for s in texts]
        token_lengths = [len(e.ids) for e in tokenizer.encode_batch(texts, add_special_tokens=False)]
        counts = Counter(texts)
        stats[col] = {'characters': distribution(lengths), 'gte_tokens_no_special': distribution(token_lengths),
            'whitespace_units': distribution([len(s.split()) for s in texts]),
            'blank': sum(not s.strip() for s in texts),
            'duplicate_excess': sum(n-1 for n in counts.values()),
            'duplicate_groups': [[r['id'] for r in rows if r[col] == s] for s,n in counts.items() if n > 1],
            'replacement_character': sum('\ufffd' in s for s in texts),
            'control_characters': sum(any(ord(c)<32 and c not in '\n\r\t' for c in s) for s in texts)}
        for row, length, tokens in zip(rows, lengths, token_lengths):
            if col == 'query':
                per_query.append({'id':row['id'], 'characters':length, 'gte_tokens':tokens,
                    'original_changed':row['query'] != original[row['id']]['query']})
    baseline = tables['query_rewritten_weighted.parquet']
    comparisons = {}
    for name, other in tables.items():
        common = baseline.keys() & other.keys()
        comparisons[name] = {col: [i for i in sorted(common) if baseline[i].get(col) != other[i].get(col)]
                            for col in ('query', 'english', 'chinese', 'dense_weight') if col in next(iter(other.values()))}
    weighted = pq.read_table(ROOT / 'artifacts/query-embeddings/query_rewritten_final_embeddings_weighted.parquet')
    vector_stats = {}
    for col in ('vector_original', 'vector_english', 'vector_chinese'):
        a = np.asarray(weighted[col].to_pylist(), dtype=np.float32)
        vector_stats[col] = {'shape':list(a.shape), 'nonfinite':int((~np.isfinite(a)).sum()),
                             'norms':distribution(np.linalg.norm(a, axis=1))}
    save('query_stats.json', {'versions':versions, 'text':stats, 'comparisons_to_attached':comparisons,
        'dense_weights':dict(sorted(Counter(str(r['dense_weight']) for r in rows).items())),
        'id_min':min(baseline), 'id_max':max(baseline), 'missing_ids':sorted(set(range(1,1201))-baseline.keys()),
        'vectors':vector_stats, 'tokenizer_path':str(tokenizer_path),
        'tokenizer_sha256':hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()})
    save('query_lengths.json', per_query)


def corpus_audit():
    started = time.monotonic()
    predictions = orjson.loads((RUN / 'submission.json').read_bytes())
    needed = {(c['doc_id'], hashlib.blake2b(c['chunk_text'].encode(), digest_size=16).digest())
              for p in predictions for c in p['relevant_chunks']}
    need_count = len(needed)
    pred_doc_ids = {d for p in predictions for d in p['relevant_docs']}
    pred_meta = {}
    docs, chunks = Counter(), Counter()
    langs, chunk_langs, content_langs, types, profiles, domains, statuses, eligibility = [Counter() for _ in range(8)]
    missing = Counter()
    lengths, units, doc_ids = array('I'), array('I'), array('q')
    chunk_hashes, text_hashes, raw_hashes = bytearray(), bytearray(), bytearray()
    bands = defaultdict(Counter)
    digest = hashlib.sha256()
    examples = []
    with SOURCE.open('rb') as stream:
        for raw in stream:
            digest.update(raw)
            d = orjson.loads(raw)
            did = d['doc_id']; doc_ids.append(did)
            lang = d.get('source_language') or '<missing>'
            domain = urlsplit(d.get('url') or '').hostname or '<missing>'
            langs[lang] += 1; domains[domain] += 1
            types[str(d.get('doc_type'))] += 1; profiles[str(d.get('profile'))] += 1
            statuses[str(d.get('status'))] += 1
            band = '>=5000000' if did >= 5000000 else '<5000000'
            bands[band]['documents'] += 1; bands[band]['chunks'] += len(d['children'])
            bands[band]['language:' + lang] += 1
            docs['total'] += 1
            docs['zero_chunks'] += not bool(d['children'])
            if did in pred_doc_ids:
                pred_meta[did] = {'language':lang, 'domain':domain, 'chunks':len(d['children'])}
            if d.get('raw_sha256'):
                raw_hashes.extend(bytes.fromhex(d['raw_sha256'])[:16])
            else:
                missing['document_raw_sha256'] += 1
            for field in ('url', 'source_language', 'doc_type', 'profile', 'source_sha256'):
                missing['document:' + field] += d.get(field) is None or d.get(field) == ''
            parent_ids = {p['parent_id'] for p in d['parents']}
            per_doc_ids = set()
            for c in d['children']:
                cid, text = c['chunk_id'], c['chunk_text']
                chunks['total'] += 1; chunk_langs[lang] += 1
                content_langs['+'.join(sorted(c.get('content_languages') or [])) or '<missing>'] += 1
                eligibility[str(c.get('retrieval_eligible'))] += 1
                lengths.append(len(text)); units.append(c.get('unit_count') or 0)
                chunks['empty_text'] += not text.strip()
                chunks['doc_id_mismatch'] += c.get('doc_id') != did
                chunks['parent_missing'] += c.get('parent_id') not in parent_ids
                chunks['id_prefix_mismatch'] += not cid.startswith(str(did) + ':c:')
                chunks['duplicate_id_within_document'] += cid in per_doc_ids
                chunks['offset_length_mismatch'] += c['end_char'] - c['start_char'] != len(text)
                per_doc_ids.add(cid)
                th = hashlib.blake2b(text.encode(), digest_size=16).digest()
                chunk_hashes.extend(hashlib.blake2b(cid.encode(), digest_size=16).digest())
                text_hashes.extend(th)
                needed.discard((did, th))
            if did >= 5000000 and len(examples) < 5:
                examples.append({'doc_id':did, 'language':lang, 'domain':domain,
                    'chunk_id':d['children'][0]['chunk_id'] if d['children'] else None,
                    'excerpt':d['children'][0]['chunk_text'][:250] if d['children'] else None})
            if docs['total'] % 200000 == 0:
                print(f"Scanned {docs['total']} documents / {chunks['total']} chunks in {time.monotonic()-started:.1f}s", flush=True)
    def hash_duplicates(buffer):
        a = np.frombuffer(buffer, dtype='V16')
        _, n = np.unique(a, return_counts=True)
        return {'excess':int((n-1).sum()), 'groups':int((n>1).sum()), 'largest_group':int(n.max())}
    per_query = []
    for p in predictions:
        dl = Counter(pred_meta.get(d, {}).get('language', '<absent>') for d in p['relevant_docs'])
        cl = Counter(pred_meta.get(c['doc_id'], {}).get('language', '<absent>') for c in p['relevant_chunks'])
        per_query.append({'id':p['id'], 'docs':len(p['relevant_docs']), 'chunks':len(p['relevant_chunks']),
            'doc_languages':dict(dl), 'chunk_languages':dict(cl),
            'docs_ge_5m':sum(d>=5000000 for d in p['relevant_docs']),
            'chunks_ge_5m':sum(c['doc_id']>=5000000 for c in p['relevant_chunks']),
            'duplicate_doc_ids':len(p['relevant_docs'])-len(set(p['relevant_docs'])),
            'chunks_outside_docs':sum(c['doc_id'] not in p['relevant_docs'] for c in p['relevant_chunks'])})
    save('corpus_stats.json', {'source':str(SOURCE), 'source_bytes':SOURCE.stat().st_size,
        'sha256':digest.hexdigest(), 'documents':dict(docs), 'chunks':dict(chunks),
        'doc_languages':dict(langs), 'chunk_source_languages':dict(chunk_langs),
        'chunk_content_languages':dict(content_langs), 'doc_types':dict(types), 'profiles':dict(profiles),
        'domains':dict(domains.most_common()), 'statuses':dict(statuses), 'retrieval_eligible':dict(eligibility),
        'missing':dict(missing), 'id_bands':{k:dict(v) for k,v in bands.items()},
        'id_min':min(doc_ids), 'id_max':max(doc_ids),
        'duplicate_doc_id_excess':len(doc_ids)-len(np.unique(np.asarray(doc_ids))),
        'duplicate_chunk_ids_hash':hash_duplicates(chunk_hashes),
        'duplicate_exact_chunk_text_hash':hash_duplicates(text_hashes),
        'duplicate_document_raw_hash':hash_duplicates(raw_hashes),
        'chunk_characters':distribution(lengths), 'chunk_source_units':distribution(units),
        'predicted_unique_doc_ids':len(pred_doc_ids), 'predicted_doc_ids_absent':sorted(pred_doc_ids-pred_meta.keys()),
        'predicted_unique_doc_text_pairs':need_count, 'predicted_pairs_not_in_source':len(needed),
        'ge_5m_examples':examples, 'seconds':time.monotonic()-started})
    save('output_per_query.json', per_query)
    save('output_document_metadata.json', pred_meta)
    print('Finished corpus scan',time.monotonic()-started, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('part', choices=['query','corpus'])
    args = parser.parse_args()
    query_audit() if args.part == 'query' else corpus_audit()
