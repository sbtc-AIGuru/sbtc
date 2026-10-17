"""Retain WHO tabular rows and explain differences from the ClaML snapshot."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .models import FoundationError, identifier
from .sources import SourceStore, source_ref


def tabular_records(snapshot):
    SourceStore.verify(snapshot)
    for member in snapshot['members']:
        data = Path(member['local_path']).read_bytes()
        try:
            text = data.decode('utf-8-sig')
            encoding = 'utf-8-sig'
        except UnicodeDecodeError:
            text = data.decode('cp1252')
            encoding = 'cp1252'
        kind = next((x for x in ('chapters', 'groups', 'codes') if x in member['role']), None)
        if kind is None:
            raise FoundationError('Unrecognized WHO tabular member', 3)
        for index, fields in enumerate(csv.reader(io.StringIO(text), delimiter=';'), 1):
            if not fields:
                raise FoundationError('Unexpected empty tabular row', 3)
            expected = {'chapters': 2, 'groups': 4, 'codes': 17}[kind]
            if len(fields) != expected:
                raise FoundationError(f'Tabular schema mismatch {member["role"]}:{index}', 3)
            yield {'record_type': 'auxiliary', 'auxiliary_id': identifier('tabular-row', [snapshot['edition_id'], member['role'], index]),
                   'kind': f'tabular_{kind}', 'raw_fields': fields, 'encoding': encoding,
                   'status': 'deferred', 'reason': 'supporting_snapshot_crosscheck_not_canonical',
                   'source_refs': [source_ref(snapshot, f'{member["role"]}:row={index}', member)]}


def reconcile_tabular(records, who_nodes):
    by_code = {x['source_code_raw']: x for x in who_nodes}
    chapter_codes = {x['code']: x for x in who_nodes if x['level'] == 'chapter'}
    block_codes = {x['code']: x for x in who_nodes if x['level'] == 'block'}
    comparisons = []
    observed = set()
    for row in records:
        fields, kind = row['raw_fields'], row['kind']
        if kind == 'tabular_chapters':
            code, label = fields
            match = chapter_codes.get(code)
        elif kind == 'tabular_groups':
            # This actual snapshot includes BOTH endpoints; no inferred end range.
            code, label = fields[0] + '-' + fields[1], fields[3]
            match = block_codes.get(code)
        else:
            code, label = fields[6], fields[8]
            match = by_code.get(code)
            if match:
                observed.add(code)
        if not match:
            status = 'tabular_only_modifier_expansion_or_snapshot_difference_requires_review'
        elif label != match['preferred_labels']['en']['text']:
            status = 'label_difference_requires_review'
        else:
            status = 'exact_label_match'
        comparisons.append({'comparison_id': identifier('comparison', row['auxiliary_id']), 'source_row_id': row['auxiliary_id'],
                            'code': code, 'status': status, 'tabular_label': label,
                            'claml_label': match['preferred_labels']['en']['text'] if match else None,
                            'source_refs': row['source_refs'] + (match['source_refs'] if match else [])})
    missing = sorted(code for code, node in by_code.items()
                     if node['level'] in {'category', 'subcategory'} and code not in observed)
    return {'comparisons': comparisons, 'claml_codes_not_in_tabular': missing,
            'policy': 'differences retained; no inferred modifier expansion or silent merge'}
