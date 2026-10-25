"""Compare bounded preprocessing on a small local Vietnamese sample."""

import hashlib
import json
import sys
from itertools import islice
from pathlib import Path
from time import monotonic

ROOT = Path('/home/nhminh/AI_Project/sbtc')
sys.path.insert(0, str(ROOT))

from BackEnd.app.Database.elastic_search import DATA_PATH, iter_actions, read_jsonl


def main():
    sample = Path('/tmp/sbtc-es-vi-speed-sample.jsonl')
    records = (row for row in read_jsonl(DATA_PATH) if row['language'] == 'vi')
    with sample.open('w', encoding='utf-8') as output:
        for row in islice(records, 4000):
            output.write(json.dumps(row, ensure_ascii=False) + '\n')
    results = []
    for workers in (1, 4, 8):
        started = monotonic()
        digest = hashlib.sha256()
        count = 0
        for action in iter_actions(sample, workers=workers):
            digest.update(json.dumps(action, sort_keys=True, ensure_ascii=False).encode())
            count += 1
        elapsed = monotonic() - started
        result = dict(workers=workers, rows=count, seconds=round(elapsed, 2),
                      docs_per_second=round(count / elapsed, 1), sha256=digest.hexdigest())
        results.append(result)
        print(json.dumps(result), flush=True)
    assert len({row['sha256'] for row in results}) == 1
    Path(__file__).with_name('benchmark.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
