"""Compare immutable test20k runs, preserving evidence for independent review."""
import collections
import argparse
import difflib
import hashlib
import importlib.util
import json
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
TASK = Path(__file__).resolve().parent
INPUT = ROOT / 'data_final/test_20k.jsonl'
RUNS = {
    'v2': ROOT / 'data_final/chunks_format_v2_test20k',
    'v3_post': ROOT / 'data_final/chunks_format_v3_test20k',
    'v3_reserve': ROOT / 'data_final/chunks_format_v3_reserve_test20k',
}


def cleaner(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.clean_with_report


def rows(directory):
    for part in sorted(directory.glob('part-*.jsonl')):
        with part.open(encoding='utf-8') as stream:
            for line in stream:
                yield json.loads(line)


def lexical_tokens(text):
    # Compare visible letter/number sequences independent of Markdown punctuation.
    import re
    return re.findall(r'[\u3400-\u9fff]|[^\W\d_]+|\d+(?:[.,]\d+)*', text)


def residual_markers(text):
    import re
    return len(re.findall(r'\]\([^\n)]*(?=\n|$)', text))


def covered(start, end, children, source):
    intervals = [(max(start, c['start_char']), min(end, c['end_char'])) for c in children
                 if max(start, c['start_char']) < min(end, c['end_char'])]
    return all(char.isspace() or any(a <= start + i < b for a, b in intervals)
               for i, char in enumerate(source[start:end]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--post-dir', type=Path, default=RUNS['v3_post'])
    parser.add_argument('--reserve-dir', type=Path, default=RUNS['v3_reserve'])
    parser.add_argument('--output-dir', type=Path, default=TASK)
    args = parser.parse_args()
    RUNS['v3_post'], RUNS['v3_reserve'] = args.post_dir.resolve(), args.reserve_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    old_clean = cleaner(TASK / 'baseline-code/sbtc/Scripts/Clawler/verbatim.py', 'baseline_verbatim')
    new_clean = cleaner(ROOT / 'sbtc/Scripts/Clawler/verbatim.py', 'candidate_verbatim')
    manifest = json.loads((TASK / 'baseline-manifest.json').read_text())
    digest = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    if digest != manifest['input_sha256']:
        raise ValueError('Fixture SHA changed')
    stats = {}
    for label, directory in RUNS.items():
        checkpoint = json.loads((directory / 'checkpoint.json').read_text())
        if not checkpoint['done'] or checkpoint['input_sha256'] != digest:
            raise ValueError('Incomplete run or changed input')
        summary = dict(checkpoint['summary'])
        summary['output_bytes'] = sum(p.stat().st_size for p in directory.glob('part-*.jsonl'))
        summary['any_overlap_percent'] = 100 * summary['eligible_overlap_positive'] / summary['eligible_overlap_transitions']
        summary['ideal_overlap_percent'] = 100 * summary['overlap_30_50'] / summary['eligible_overlap_transitions']
        stats[label] = summary
    profiles = collections.Counter()
    removals = collections.Counter()
    residual = collections.Counter()
    residual_warning_records = collections.Counter()
    source_changes = 0
    lexical_issues = []
    order_issues = []
    errors = []
    review = []
    remainders = []
    by_language = {label: collections.defaultdict(collections.Counter) for label in RUNS}
    with INPUT.open(encoding='utf-8') as inputs:
        streams = [rows(p) for p in RUNS.values()]
        for number, values in enumerate(zip_longest(inputs, *streams), 1):
            if any(x is None for x in values):
                raise ValueError('Record count mismatch')
            raw, previous, post, reserve = values
            record = json.loads(raw)
            for label, row in zip(RUNS, (previous, post, reserve)):
                if row['doc_id'] != record['id'] or row['url'] != record['url'] or row['input_line'] != number:
                    errors.append({'line': number, 'run': label, 'issue': 'identity mismatch'})
                summary = by_language[label][row.get('source_language', 'skipped')]
                summary['records'] += 1
                seen = set()
                for c in row['children']:
                    summary['children'] += 1
                    summary['under50'] += c['unit_count'] < 50
                    if c['parent_id'] in seen:
                        summary['eligible'] += 1
                        summary['overlap_positive'] += c['overlap_units'] > 0
                        summary['overlap_30_50'] += 30 <= c['overlap_units'] <= 50
                    seen.add(c['parent_id'])
            if post.get('source_sha256') != reserve.get('source_sha256') or post.get('profile') != reserve.get('profile') or post.get('excluded_spans') != reserve.get('excluded_spans'):
                errors.append({'line': number, 'issue': 'packing policies changed source/profile/exclusions'})
            if post['status'] != 'ok':
                continue
            changed_source = previous.get('source_sha256') != post['source_sha256']
            changed_profile = previous.get('profile') != post['profile']
            toc = [s for s in post['excluded_spans'] if any(e['rule_id'] == 'verified_table_of_contents' for e in s.get('evidence', []))]
            has_remainder = any(c['unit_count'] < 50 and c.get('short_chunk_reason') == 'whole_atom_budget_remainder' for c in post['children'])
            has_link_warning = any(w['code'] == 'incomplete_markdown_link' for w in post['cleaning']['warnings'])
            if not (changed_source or changed_profile or toc or has_remainder or has_link_warning):
                continue
            source = new_clean(record['text'])[0]
            before = old_clean(record['text'])[0] if changed_source or has_link_warning else None
            if has_link_warning:
                residual_warning_records['v2'] += residual_markers(before)
                residual_warning_records['v3'] += residual_markers(source)
            item = dict(doc_id=record['id'], url=record['url'], input_line=number,
                        old_profile=previous.get('profile'), new_profile=post['profile'],
                        title=source.splitlines()[0], new_evidence=post['format_evidence'],
                        source_head=source[:800], toc_spans=toc,
                        post_file=str(RUNS['v3_post'] / f'part-{(number-1)//1000:06d}.jsonl'),
                        file_line=(number-1)%1000+1)
            if has_link_warning:
                item['repair_actions'] = post['cleaning']['actions']
                item['remaining_candidate_markers'] = residual_markers(source)
            if changed_profile:
                profiles[previous.get('profile', '?') + ' -> ' + post['profile']] += 1
            if changed_source:
                source_changes += 1
                old_tokens, new_tokens = lexical_tokens(before), lexical_tokens(source)
                removed = collections.Counter(old_tokens) - collections.Counter(new_tokens)
                added = collections.Counter(new_tokens) - collections.Counter(old_tokens)
                if old_tokens != new_tokens:
                    order_issues.append(record['id'])
                residual['v2'] += residual_markers(before)
                residual['v3'] += residual_markers(source)
                if removed or added:
                    lexical_issues.append(dict(doc_id=record['id'], removed=dict(removed), added=dict(added)))
                if new_clean(source)[0] != source:
                    errors.append({'doc_id': record['id'], 'issue': 'cleaner is not idempotent on changed record'})
                item['cleaner_diff'] = [dict(before=before[a:b], after=source[c:d],
                                             context=before[max(0,a-40):min(len(before),b+40)])
                                        for kind,a,b,c,d in difflib.SequenceMatcher(None, before, source, autojunk=False).get_opcodes()
                                        if kind != 'equal']
                item['repair_actions'] = post['cleaning']['actions']
            for span in toc:
                evidence = next(e for e in span['evidence'] if e['rule_id'] == 'verified_table_of_contents')
                removals['records'] += 1
                removals['non_whitespace_chars'] += sum(not c.isspace() for c in span['text'])
                for match in evidence['matched_entries']:
                    a, b = match['body_start_char'], match['body_end_char']
                    if source[a:b] != match['body_text'] or not covered(a, b, post['children'], source):
                        errors.append({'doc_id': record['id'], 'issue': 'TOC body counterpart lost or altered'})
                    if not span['start_char'] <= match['toc_start_char'] < match['toc_end_char'] <= span['end_char']:
                        errors.append({'doc_id': record['id'], 'issue': 'TOC duplicate offsets invalid'})
            if has_remainder:
                for index,c in enumerate(post['children']):
                    if c['unit_count'] < 50 and c.get('short_chunk_reason') == 'whole_atom_budget_remainder':
                        remainders.append(dict(doc_id=record['id'], order=index, text=c['chunk_text'], units=c['unit_count'],
                                               role=c['section_roles'], left_units=post['children'][index-1]['unit_count'] if index else None,
                                               right_units=post['children'][index+1]['unit_count'] if index+1<len(post['children']) else None,
                                               parent=c['parent_id']))
            review.append(item)
    result = dict(input_sha256=digest, runs=stats, profile_transitions=dict(profiles),
                  changed_source_records=source_changes, lexical_differences=lexical_issues,
                  lexical_order_differences=order_issues,
                  residual_marker_counts_in_changed_sources=dict(residual), toc_removals=dict(removals),
                  residual_marker_counts_on_all_warning_records=dict(residual_warning_records),
                  short_remainders=remainders, errors=errors, review_records=len(review),
                  by_source_language_prior={label:{lang:dict(c) for lang,c in groups.items()} for label,groups in by_language.items()})
    (output / 'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (output / 'review-cases.jsonl').write_text(''.join(json.dumps(item, ensure_ascii=False)+'\n' for item in review))
    lines = ['# Casebook — profile/source/TOC changes from test20k', '',
             '| doc_id | Profile | TOC spans | Link recoveries | Title |', '|---|---|---:|---:|---|']
    for item in review:
        lines.append(f"| {item['doc_id']} | {item['old_profile']} → {item['new_profile']} | {len(item['toc_spans'])} | {item.get('repair_actions',{}).get('incomplete_link_recovered',0)} | {item['title'].replace('|',' ')} |")
    (output / 'CASEBOOK.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('runs','by_source_language_prior','short_remainders')},ensure_ascii=False,indent=2))
    for label,s in stats.items():
        print(label, 'chunks',s['chunks'], 'short',s['chunk_size_distribution']['0-49'],
              'overlap',s['ideal_overlap_percent'], 'any',s['any_overlap_percent'], 'bytes',s['output_bytes'])
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
