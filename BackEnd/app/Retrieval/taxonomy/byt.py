"""BYT 2026 PDF layout candidates. All rows remain quarantined until reviewed."""
from __future__ import annotations

import bisect
import csv
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .models import FoundationError, identifier
from .native import native_node, quarantine
from .sources import SourceAdapter, SourceStore, source_ref

# Measured on the pinned 842x595 annex, verified against column numbers 1..29.
# These are extraction coordinates, never inferred semantic column meanings.
EDGES = [18.7, 30.2, 49.5, 69, 114, 157, 176, 216, 260, 280, 303, 325, 342,
         366, 387, 404, 441, 470, 488.5, 508.5, 546, 590, 641, 678, 701, 726,
         751, 778, 801, 829]


def page_candidates(words, page):
    anchors = sorted([(float(w['top']), int(w['text'])) for w in words
                      if 18.7 <= float(w['left']) < 21 and float(w['top']) > 25
                      and re.fullmatch(r'[0-9]{1,5}', w['text'])], key=lambda x: x[0])
    rows = []
    for index, (top, sequence) in enumerate(anchors):
        bottom = anchors[index + 1][0] - .5 if index + 1 < len(anchors) else 580
        cells = [[] for _ in range(29)]
        for word in words:
            x, y = float(word['left']), float(word['top'])
            if top - .5 <= y < bottom and EDGES[0] <= x < EDGES[-1]:
                column = bisect.bisect_right(EDGES, x) - 1
                cells[column].append(word)
        texts = [' '.join(w['text'] for w in sorted(cell, key=lambda w: (round(float(w['top']), 1), float(w['left']))))
                 for cell in cells]
        rows.append({'page': page, 'sequence': sequence, 'bbox': [EDGES[0], top, EDGES[-1], bottom],
                     'cells': texts,
                     'layout_profile': 'byt-06-2026-29-columns-candidate-v1'})
    return rows


class BYTPDFAdapter(SourceAdapter):
    def parse(self, snapshot):
        SourceStore.verify(snapshot)
        if snapshot['content_sha256'] != '8639f5eeb77b571363dc841923095895d2498748f9bc6620f50710a6da9159e2':
            raise FoundationError('BYT layout profile requires the exact inspected PDF SHA256', 3)
        all_rows = []
        with tempfile.TemporaryDirectory(prefix='icd10-byt-') as tmp:
            output = Path(tmp) / 'bbox.tsv'
            try:
                subprocess.run(['pdftotext', '-tsv', snapshot['local_path'], str(output)],
                               check=True, capture_output=True, timeout=180)
            except (OSError, subprocess.SubprocessError) as exc:
                raise FoundationError(f'BYT PDF extraction failed: {exc}', 3) from exc
            if output.stat().st_size > 256 * 1024 * 1024:
                raise FoundationError('BYT bbox output exceeds resource budget', 3)
            current, words = None, []
            def emit_page(page, page_words):
                rows = page_candidates(page_words, page)
                all_rows.extend(rows)
                return {'record_type': 'auxiliary', 'auxiliary_id': identifier('pdf-page', [snapshot['edition_id'], page]),
                        'kind': 'pdf_page', 'page': page, 'status': 'deferred',
                        'reason': 'pdf_page_retained_with_unverified_row_candidates',
                        'text_raw': ' '.join(w['text'] for w in sorted(page_words, key=lambda w: (float(w['top']), float(w['left'])))),
                        'candidate_rows': len(rows), 'source_refs': [source_ref(snapshot, f'page={page};layout=bbox-tsv')]}
            with output.open(encoding='utf-8') as stream:
                for word in csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE):
                    page = int(word['page_num'])
                    if current is not None and page != current:
                        yield emit_page(current, words)
                        words = []
                    current = page
                    if word['level'] == '1' and (float(word['width']) != 842 or float(word['height']) != 595):
                        raise FoundationError('BYT page geometry changed; inspect source', 3)
                    if word['level'] == '5':
                        words.append({k: word[k] for k in ('left', 'top', 'width', 'height', 'text')})
                if current is not None:
                    yield emit_page(current, words)
        counts = Counter(row['cells'][17] for row in all_rows)
        sequences = [x['sequence'] for x in all_rows]
        if len(set(sequences)) != len(sequences) or sequences != list(range(1, len(sequences) + 1)):
            raise FoundationError('BYT STT sequence has gaps/duplicates; row reconciliation failed', 3)
        for row in all_rows:
            code = row['cells'][17]
            locator = f'page={row["page"]};STT={row["sequence"]};column=18,22;bbox={row["bbox"]}'
            if not re.fullmatch(r'[A-Z][0-9]{2}(?:\.[A-Za-z0-9]+)?[†*+]?|[A-Z][0-9]{2}[†*+]', code) or counts[code] != 1 or not row['cells'][21]:
                yield quarantine(snapshot, row, locator, 'pdf_code_label_or_duplicate_requires_review')
                continue
            # Column 22 is disease name VI; English and every flag stay raw in evidence.
            # They are not promoted to official WHO labels by this extraction step.
            candidate = native_node({**snapshot, 'source_verified': False},
                {'code': code, 'level': 'other_group', 'labels': {'vi': row['cells'][21]},
                 'source_kind': 'pdf_disease_row_candidate', 'properties': row}, locator)
            candidate['parse_status'] = 'quarantined'
            candidate['extraction_warning'] = 'PDF layout candidates require row/cell review; page continuation may truncate labels'
            yield candidate
