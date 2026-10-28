"""Thêm nhãn đã kiểm chứng vào JSONL gốc, giữ bản sao trước khi thay file."""
import argparse
from collections import Counter
import hashlib
from itertools import zip_longest
import json
import os
from pathlib import Path
import shutil
import time

import orjson

ROOT = Path(__file__).resolve().parent


def apply_labels(source, labels, verification, output_dir):
    source, labels, verification, output_dir = map(Path, (source, labels, verification, output_dir))
    expected = json.loads(verification.read_text())
    stage = output_dir / (source.name + '.with_language.partial')
    backup = output_dir / (source.name + '.before_language.bak')
    report = output_dir / 'applied_to_source.json'
    for path in (stage, backup, report):
        if path.exists():
            raise FileExistsError(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source_hash, labels_hash = hashlib.sha256(), hashlib.sha256()
    counts = Counter()
    rows = 0
    with source.open('rb') as src, labels.open('rb') as lab, stage.open('xb') as dst:
        for rows, (raw, prediction) in enumerate(zip_longest(src, lab), 1):
            if raw is None or prediction is None:
                raise ValueError(f'Số dòng không khớp tại dòng {rows}')
            row, label = orjson.loads(raw), orjson.loads(prediction)
            for key in ('doc_id', 'chunk_id'):
                if type(row[key]) is not type(label[key]) or row[key] != label[key]:
                    raise ValueError(f'{key} không khớp tại dòng {rows}')
            language = label['language']
            if language not in ('vi', 'en', 'zh') or 'language' in row:
                raise ValueError(f'Nhãn không hợp lệ hoặc đã tồn tại tại dòng {rows}')
            source_hash.update(raw)
            labels_hash.update(prediction)
            row['language'] = language
            dst.write(orjson.dumps(row) + b'\n')
            counts[language] += 1
            if rows % 1000000 == 0:
                print(f'Đã bổ sung {rows:,} dòng', flush=True)
    if (source_hash.hexdigest() != expected['source_sha256'] or
            labels_hash.hexdigest() != expected['labels_sha256'] or
            rows != expected['rows'] or dict(counts) != expected['counts']):
        raise ValueError('Nguồn hoặc bảng nhãn đã thay đổi so với lần kiểm chứng')

    # Read the staged file back and compare every original field before replacement.
    before_hash, after_hash = hashlib.sha256(), hashlib.sha256()
    checked = 0
    with source.open('rb') as src, stage.open('rb') as dst:
        for checked, (raw, enriched) in enumerate(zip_longest(src, dst), 1):
            if raw is None or enriched is None:
                raise ValueError('File mới không đủ số dòng')
            row = orjson.loads(enriched)
            if row.pop('language') not in ('vi', 'en', 'zh') or row != orjson.loads(raw):
                raise ValueError(f'Trường dữ liệu gốc bị thay đổi tại dòng {checked}')
            before_hash.update(raw)
            after_hash.update(enriched)
    if checked != rows or before_hash.hexdigest() != expected['source_sha256']:
        raise ValueError('Nguồn thay đổi trong lúc xử lý')
    shutil.copymode(source, stage)
    os.link(source, backup)
    os.replace(stage, source)
    result = {'status': 'complete', 'source': str(source.resolve()), 'rows': rows,
              'language_counts': dict(counts), 'all_original_fields_verified': True,
              'source_sha256_before': before_hash.hexdigest(),
              'source_sha256_after': after_hash.hexdigest(), 'backup': str(backup.resolve()),
              'elapsed_seconds': round(time.monotonic() - started, 2)}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parents[1] / 'datav3/ViBioMIR_chunks_with_recovery.jsonl')
    parser.add_argument('--labels', type=Path, default=ROOT / 'output/ViBioMIR_chunk_languages.jsonl')
    parser.add_argument('--verification', type=Path, default=ROOT / 'output/verification.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output')
    args = parser.parse_args()
    apply_labels(args.source, args.labels, args.verification, args.output_dir)
