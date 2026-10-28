"""Gán nhãn vi/en/zh theo ngữ cảnh từ và chữ viết, đọc/ghi theo dòng."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import unicodedata

import orjson

ROOT = Path(__file__).resolve().parent
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]')
VI = re.compile('[àáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]', re.I)
VI_DISTINCTIVE = re.compile('[ăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]', re.I)
LATIN_WORD = re.compile(r'[a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u1e00-\u1eff]+', re.I)
VI_WORDS = frozenset('''và là của có không được những các một trong với cho khi thì
    đã đang sẽ này đó để từ hoặc nhưng về cũng như do nên cần bị bệnh người thuốc
    tôi em cháu bác sĩ bé trẻ mẹ bố bà má đau táo bón cúm ho sốt da khám điều trị
    kết quả nghiên cứu triệu chứng sức khỏe'''.split())
EN_WORDS = frozenset('''the and or of to in is are was were with without for from
    by at as this that these those which who not no has have had be been can may
    patients patient study studies results methods conclusion conclusions clinical
    treatment syndrome disease symptoms risk serum levels children adults compared
    between after before during reported associated'''.split())
EN_CONTEXT = frozenset('''the and of to in is are was were with without for from
    by at as this that these those which who not no has have had be been can may
    between after before during'''.split())
RULE_VERSION = 'context-script-v2.2'


def language_decision(content):
    """Return a routing label and whether the three-language rule needs review."""
    text = unicodedata.normalize('NFC', content)
    han = HAN.findall(text)
    accented = VI.search(text)
    if not han and not accented:
        return 'en', False
    words = LATIN_WORD.findall(text.lower())
    vi_words = sum(word in VI_WORDS for word in words)
    distinctive = sum(bool(VI_DISTINCTIVE.search(word)) for word in words)
    vi_evidence = vi_words + distinctive
    # EN evidence cannot exceed the word count, so this cannot pass the EN test.
    if not han and 2 * vi_evidence >= len(words):
        return 'vi', False
    en_words = sum(word in EN_WORDS for word in words)
    en_context = sum(word in EN_CONTEXT for word in words)
    english_context = en_context >= 2 and en_context >= 0.08 * len(words)
    if han:
        latin_letters = sum(map(len, words))
        # A translated term or citation must not route an otherwise Latin article to ZH.
        if len(han) >= 0.2 * (len(han) + latin_letters):
            return 'zh', False
        if not vi_words and not distinctive and en_words < 2:
            return 'zh', True
    # Shared accents in names (Barré, Sempé, café) are not Vietnamese evidence.
    if english_context and en_words > 2 * vi_evidence:
        body = text.split('\n\n', 1)[-1]
        # Preserve the existing route for substantial bilingual passages pending review.
        return 'en', bool(han and len(HAN.findall(body)) >= 20)
    if en_words and not vi_evidence and len(words) <= 8:
        return 'en', False
    if han and not accented and not vi_words:
        return 'zh', True
    return ('vi' if accented or vi_words else 'en'), not bool(vi_evidence)


def detect_language(content):
    return language_decision(content)[0]


def label_chunks(source, output, summary, limit=None, progress_every=500000):
    source, output, summary = map(lambda p: Path(p).resolve(), (source, output, summary))
    partial = output.with_name(output.name + '.partial')
    summary_partial = summary.with_name(summary.name + '.partial')
    paths = [source, output, summary, partial, summary_partial]
    if len(set(paths)) != len(paths):
        raise ValueError('Đường dẫn nguồn và đầu ra phải khác nhau')
    for path in paths[1:]:
        if path.exists():
            raise FileExistsError(f'Đã tồn tại: {path}')
    if limit is not None and limit < 0:
        raise ValueError('limit phải >= 0')
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter({'vi': 0, 'en': 0, 'zh': 0})
    digest = hashlib.sha256()
    rows, complete, review_rows = 0, True, 0
    started = time.monotonic()
    with source.open('rb') as src, partial.open('xb') as dst:
        for raw in src:
            if limit is not None and rows >= limit:
                complete = False
                break
            record = orjson.loads(raw)
            language, needs_review = language_decision(record['content'])
            if needs_review:
                language = record.get('language',
                                      'zh' if HAN.search(record['content']) else
                                      'vi' if VI.search(record['content']) else 'en')
            review_rows += needs_review
            dst.write(orjson.dumps({'doc_id': record['doc_id'], 'chunk_id': record['chunk_id'],
                                    'language': language}) + b'\n')
            digest.update(raw)
            counts[language] += 1
            rows += 1
            if progress_every and rows % progress_every == 0:
                print(f'{rows:,} chunks | {dict(counts)}', file=sys.stderr, flush=True)
    result = {'status': 'complete' if complete else 'limited', 'total_rows': rows,
              'language_counts': dict(counts),
              'source_sha256': digest.hexdigest() if complete else None,
              'processed_bytes_sha256': digest.hexdigest(),
              'elapsed_seconds': round(time.monotonic() - started, 2),
              'rule_version': RULE_VERSION,
              'review_rows': review_rows,
              'rule': 'NFC; dominant Han; otherwise Vietnamese word/letter evidence versus English context; accented fallback'}
    with summary_partial.open('x', encoding='utf-8') as dst:
        json.dump(result, dst, ensure_ascii=False, indent=2)
        dst.write('\n')
    partial.rename(output)
    summary_partial.rename(summary)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT.parents[1] / 'datav3/ViBioMIR_chunks_with_recovery.jsonl')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/ViBioMIR_chunk_languages.v2.jsonl')
    parser.add_argument('--summary', type=Path, default=ROOT / 'output/ViBioMIR_chunk_languages.v2.summary.json')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--progress-every', type=int, default=500000)
    args = parser.parse_args()
    print(json.dumps(label_chunks(args.input, args.output, args.summary, args.limit, args.progress_every),
                     ensure_ascii=False, indent=2))
