"""Check every sidecar row against its original chunk without loading the corpus."""

import argparse
from collections import Counter
import hashlib
from itertools import zip_longest
import json
from pathlib import Path


def verify(source, labels):
    source_hash = hashlib.sha256()
    labels_hash = hashlib.sha256()
    counts = Counter()
    rows = 0
    with source.open("rb") as originals, labels.open("rb") as predictions:
        for rows, (original, prediction) in enumerate(
            zip_longest(originals, predictions), 1
        ):
            if original is None or prediction is None:
                raise ValueError(f"Different row counts at line {rows}")
            source_hash.update(original)
            labels_hash.update(prediction)
            chunk = json.loads(original)
            label = json.loads(prediction)
            for key in ("doc_id", "chunk_id"):
                if type(chunk[key]) is not type(label[key]) or chunk[key] != label[key]:
                    raise ValueError(f"{key} mismatch at line {rows}")
            if label["language"] not in ("vi", "en", "zh"):
                raise ValueError(f"Unexpected language at line {rows}")
            counts[label["language"]] += 1
    return {
        "verified": True,
        "rows": rows,
        "counts": dict(counts),
        "source_sha256": source_hash.hexdigest(),
        "labels_sha256": labels_hash.hexdigest(),
        "checks": ["equal_row_counts", "all_ids_and_types", "original_order", "three_labels_only"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.source, args.labels)
    if args.report.resolve() in (args.source.resolve(), args.labels.resolve()):
        parser.error("Report must be separate from source and labels")
    with args.report.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
