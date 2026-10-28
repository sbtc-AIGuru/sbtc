"""Prepare language-only corrections; apply to Elasticsearch after explicit approval."""

import argparse
from collections import Counter
import hashlib
from itertools import islice, zip_longest
import json
from pathlib import Path
import sys
import time

import orjson

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Scripts.LanguageLabeling.label_chunks import RULE_VERSION, language_decision


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plan(source, old_labels, output):
    source, old_labels, output = map(Path, (source, old_labels, output))
    output.mkdir(parents=True, exist_ok=True)
    labels = output / 'labels.v2.jsonl'
    delta = output / 'changes.jsonl'
    review = output / 'review.jsonl'
    report = output / 'plan.json'
    for path in (labels, delta, review, report):
        if path.exists():
            raise FileExistsError(path)
    before, after, transitions = Counter(), Counter(), Counter()
    source_hash, old_hash = hashlib.sha256(), hashlib.sha256()
    rows = changed = deferred = 0
    started = time.monotonic()
    rule_hash = file_hash(Path(__file__).with_name('label_chunks.py'))
    with source.open('rb') as src, old_labels.open('rb') as old, \
            labels.open('xb') as dst, delta.open('xb') as changes, review.open('xb') as uncertain:
        for rows, (raw, previous) in enumerate(zip_longest(src, old), 1):
            if raw is None or previous is None:
                raise ValueError(f'Row count mismatch at {rows}')
            row, label = orjson.loads(raw), orjson.loads(previous)
            for key in ('doc_id', 'chunk_id'):
                if type(row[key]) is not type(label[key]) or row[key] != label[key]:
                    raise ValueError(f'{key} mismatch at {rows}')
            old_language = label['language']
            if old_language not in ('vi', 'en', 'zh'):
                raise ValueError(f'Invalid old label at {rows}')
            language, needs_review = language_decision(row['content'])
            if needs_review:
                uncertain.write(orjson.dumps({
                    'doc_id': row['doc_id'], 'chunk_id': row['chunk_id'],
                    'old': old_language, 'suggested': language, 'content': row['content'],
                }) + b'\n')
                language = old_language
                deferred += 1
            before[old_language] += 1
            after[language] += 1
            dst.write(orjson.dumps({
                'doc_id': row['doc_id'], 'chunk_id': row['chunk_id'], 'language': language,
            }) + b'\n')
            if language != old_language:
                changed += 1
                transitions[f'{old_language}->{language}'] += 1
                changes.write(orjson.dumps({
                    'doc_id': row['doc_id'], 'chunk_id': row['chunk_id'],
                    'old': old_language, 'new': language, 'source_line': rows,
                    'content_sha256': hashlib.sha256(row['content'].encode()).hexdigest(),
                    'content': row['content'],
                }) + b'\n')
            source_hash.update(raw)
            old_hash.update(previous)
            if rows % 500000 == 0:
                print(f'{rows:,} rows; {changed:,} changes; {dict(transitions)}', flush=True)
    result = {
        'status': 'planned', 'rule_version': RULE_VERSION,
        'rule_sha256': rule_hash,
        'source': str(source.resolve()), 'source_sha256': source_hash.hexdigest(),
        'old_labels': str(old_labels.resolve()), 'old_labels_sha256': old_hash.hexdigest(),
        'rows': rows, 'changed': changed, 'before': dict(before), 'after': dict(after),
        'deferred_for_review': deferred,
        'transitions': dict(transitions), 'labels_sha256': file_hash(labels),
        'changes_sha256': file_hash(delta), 'elapsed_seconds': round(time.monotonic() - started, 2),
        'content_and_vectors_changed': False,
    }
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return result


def batches(stream, size=200):
    while batch := list(islice(stream, size)):
        yield batch


def elastic_id(doc_id, chunk_id):
    identity = json.dumps([str(doc_id), chunk_id], ensure_ascii=False)
    return hashlib.sha256(identity.encode()).hexdigest()


def apply(output, index):
    from BackEnd.app.Database.elastic_search import PIPELINE, connect_elasticsearch, prepare_text
    from elasticsearch.helpers import streaming_bulk

    output = Path(output)
    manifest = json.loads((output / 'plan.json').read_text())
    if (manifest['rule_version'] != RULE_VERSION or
            manifest['rule_sha256'] != file_hash(Path(__file__).with_name('label_chunks.py')) or
            manifest['changes_sha256'] != file_hash(output / 'changes.jsonl')):
        raise ValueError('Plan or detector changed; generate a new plan')
    backup, actions = output / 'es-before.jsonl', output / 'es-actions.jsonl'
    applied, result_path = output / 'es-applied.jsonl', output / 'es-result.json'
    for path in (backup, actions, applied, result_path):
        if path.exists():
            raise FileExistsError(f'{path}; inspect previous application before retrying')
    client = connect_elasticsearch()
    try:
        index_uuid = client.indices.get_settings(index=index)[index]['settings']['index']['uuid']
        mapping = client.indices.get_mapping(index=index)[index]['mappings']
        if mapping.get('_meta', {}).get('vibiomir_pipeline') != PIPELINE:
            raise ValueError('Index preprocessing differs from this application')
        before_count = client.count(index=index)['count']
        if before_count != manifest['rows']:
            raise ValueError(f'Index count {before_count} differs from source {manifest["rows"]}')
        checked = 0
        # Validate every affected record and save a rollback copy before the first write.
        with (output / 'changes.jsonl').open('rb') as stream, \
                backup.open('xb') as saved, actions.open('xb') as prepared:
            for batch in batches(stream):
                changes = [orjson.loads(raw) for raw in batch]
                ids = [elastic_id(row['doc_id'], row['chunk_id']) for row in changes]
                records = client.mget(index=index, ids=ids)['docs']
                for change, record in zip(changes, records, strict=True):
                    if not record.get('found'):
                        raise ValueError(f'Missing ES chunk {change["chunk_id"]}')
                    original = record['_source']
                    if (str(original['doc_id']) != str(change['doc_id']) or
                            original['chunk_id'] != change['chunk_id'] or
                            original['lang'] != change['old'] or
                            hashlib.sha256(original['content'].encode()).hexdigest() != change['content_sha256']):
                        raise ValueError(f'ES differs from plan: {change["chunk_id"]}')
                    saved.write(orjson.dumps(record) + b'\n')
                    prepared.write(orjson.dumps({
                        '_op_type': 'update', '_index': index, '_id': record['_id'],
                        'if_seq_no': record['_seq_no'], 'if_primary_term': record['_primary_term'],
                        'script': {
                            'lang': 'painless',
                            'source': '''for (def field : params.fields) { ctx._source.remove(field); }
                                ctx._source.lang = params.language;
                                if (ctx._source.containsKey('language')) { ctx._source.language = params.language; }
                                ctx._source[params.field] = params.text;''',
                            'params': {'fields': ['content_vi', 'content_en', 'content_zh'],
                                       'language': change['new'], 'field': 'content_' + change['new'],
                                       'text': prepare_text(original['content'], change['new'])},
                        },
                    }) + b'\n')
                    checked += 1
        if checked != manifest['changed']:
            raise ValueError('Incomplete preflight')
        settings = client.indices.get_settings(index=index)[index]['settings']['index']
        if settings['uuid'] != index_uuid:
            raise ValueError('Index changed during preflight')
        succeeded = 0
        with actions.open('rb') as stream, applied.open('xb') as log:
            for ok, item in streaming_bulk(
                    client, (orjson.loads(raw) for raw in stream), chunk_size=200,
                    raise_on_error=False, raise_on_exception=True, max_retries=0):
                log.write(orjson.dumps({'ok': ok, 'item': item}) + b'\n')
                log.flush()
                if not ok:
                    raise RuntimeError(f'ES update failed; inspect {applied} and {backup}')
                succeeded += 1
        client.indices.refresh(index=index)
        verified = 0
        with (output / 'changes.jsonl').open('rb') as stream, backup.open('rb') as saved:
            for batch in batches(stream):
                changes = [orjson.loads(raw) for raw in batch]
                records = client.mget(index=index, ids=[elastic_id(r['doc_id'], r['chunk_id']) for r in changes])['docs']
                originals = [orjson.loads(next(saved))['_source'] for _ in changes]
                for change, record, original in zip(changes, records, originals, strict=True):
                    current = record['_source']
                    expected = prepare_text(change['content'], change['new'])
                    if (current['content'] != change['content'] or current['lang'] != change['new'] or
                            ('language' in current and current['language'] != change['new']) or
                            current.get('content_' + change['new']) != expected or
                            any('content_' + lang in current for lang in ('vi', 'en', 'zh') if lang != change['new'])):
                        raise ValueError(f'Post-update mismatch: {change["chunk_id"]}')
                    changed_fields = {'lang', 'language', 'content_vi', 'content_en', 'content_zh'}
                    if ({k: v for k, v in current.items() if k not in changed_fields} !=
                            {k: v for k, v in original.items() if k not in changed_fields}):
                        raise ValueError(f'Unrelated fields changed: {change["chunk_id"]}')
                    verified += 1
        after_count = client.count(index=index)['count']
        if after_count != before_count:
            raise ValueError('Document count changed')
        result = {'status': 'complete', 'index': index, 'index_uuid': index_uuid,
                  'updated': succeeded, 'verified': verified, 'count_before': before_count,
                  'count_after': after_count, 'rule_version': RULE_VERSION,
                  'changes_sha256': manifest['changes_sha256'], 'backup': str(backup.resolve()),
                  'content_and_vectors_changed': False}
        result_path.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2), flush=True)
        return result
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('plan')
    prepare.add_argument('--source', type=Path, required=True)
    prepare.add_argument('--old-labels', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    update = commands.add_parser('apply')
    update.add_argument('--output', type=Path, required=True)
    update.add_argument('--index', default='vibiomir_bm25')
    args = parser.parse_args()
    if args.command == 'plan':
        plan(args.source, args.old_labels, args.output)
    else:
        apply(args.output, args.index)
