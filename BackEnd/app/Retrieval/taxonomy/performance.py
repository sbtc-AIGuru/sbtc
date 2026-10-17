"""Standalone benchmark so RSS measures matcher data, not the source audit bundle."""
import json
import sys
from pathlib import Path

from .audit import performance_audit
from .io import read_jsonl


def main():
    run, gold = map(Path, sys.argv[1:])
    bundle = {name: list(read_jsonl(run / (name + '.jsonl')))
              for name in ('lexicon.verified', 'ambiguity_groups')}
    print(json.dumps(performance_audit(bundle, list(read_jsonl(gold))), ensure_ascii=False))


if __name__ == '__main__':
    main()
