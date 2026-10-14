"""Read full JSONL for URL-family lengths and PubMed script signals only."""
import argparse
from array import array
from collections import Counter
import json
from pathlib import Path
import time

from audit_profile import family, CJK, SECTIONS, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    p, root = args.input, args.output
    root.mkdir(parents=True, exist_ok=True)
    initial = p.stat()
    started = time.time()
    groups, pubmed, missing = {}, Counter(), Counter()
    with p.open('rb') as stream:
        for n, line in enumerate(stream, 1):
            record = json.loads(line)
            url = record['url']
            domain = url.split('/')[2].split(':')[0]
            path = '/' + '/'.join(url.split('/')[3:])
            key = family(domain, path)
            if key not in groups:
                groups[key] = {'records': 0, 'success': 0, 'failed': 0,
                               'chars': array('I'), 'words': array('I')}
            group = groups[key]
            group['records'] += 1
            group['success'] += record['success']
            group['failed'] += not record['success']
            if record['success']:
                text = record['text']
                group['chars'].append(len(text))
                group['words'].append(len(text.split()))
                if domain == 'pubmed.ncbi.nlm.nih.gov':
                    count = len(CJK.findall(text))
                    pubmed['success'] += 1
                    pubmed['CJK_20plus'] += count >= 20
                    pubmed['CJK_any'] += count > 0
                    pubmed['labeled_sections_2plus'] += len(SECTIONS.findall(text)) >= 2
                if key in {'other_health_news', 'tcm_book_dictionary'} and any(
                        d in domain for d in ('zysjonline.com', 'qihuangzhishu.com', 'people.com.cn')):
                    missing[domain] += 1
            if n % 300000 == 0:
                print('source profiles', n, round(time.time() - started, 1), flush=True)
    current = p.stat()
    report = {
        'input': str(p.resolve()),
        'input_stat_unchanged': (initial.st_size, initial.st_mtime_ns) ==
                                (current.st_size, current.st_mtime_ns),
        'families': {
            key: {'records': value['records'], 'success': value['success'],
                  'failed': value['failed'], 'chars': stats(value['chars']),
                  'whitespace_tokens': stats(value['words']),
                  'bins': dict(Counter('1-299' if x < 300 else '300-799' if x < 800
                               else '800-2499' if x < 2500 else '2500-5999' if x < 6000
                               else '6000+' for x in value['chars']))}
            for key, value in groups.items()},
        'pubmed_script_and_section_counters': dict(pubmed),
        'domains_missing_from_sampler_zh_list': dict(missing),
        'seconds': time.time() - started,
    }
    (root / 'corpus_source_profiles.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('done', report['pubmed_script_and_section_counters'])


if __name__ == '__main__':
    main()
