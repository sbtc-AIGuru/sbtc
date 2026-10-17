"""Native imports retain raw cells, explicit hierarchy and unresolved semantics."""
from __future__ import annotations

import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .models import FoundationError, LANGUAGES, LEVELS, NodeKey, identifier
from .sources import SourceAdapter, SourceStore, source_ref


def apply_source_reviews(records, decisions):
    from .crosswalk import active_decisions
    active = active_decisions(decisions)
    output = []
    for row in records:
        review = active.get(row.get('source_node_id'))
        if row['record_type'] == 'node' and review and 'extraction_verified' in review:
            accepted = review['decision'] == 'accept' and review['extraction_verified'] is True
            row = {**row, 'source_verified': accepted,
                   'parse_status': 'reviewed' if accepted else 'quarantined',
                   'source_review_decision_id': review['decision_id'],
                   'source_refs': row['source_refs'] + [r for r in review['source_refs'] if r not in row['source_refs']]}
        output.append(row)
    return output


def native_node(snapshot, row, locator):
    code, level = row.get('code'), row.get('level', 'other_group')
    if not isinstance(code, str) or not code.strip() or level not in LEVELS:
        raise FoundationError('Missing code or invalid native level', 3)
    key = NodeKey(snapshot['system'], snapshot['edition_id'], level, code)
    labels = {}
    for lang, text in row.get('labels', {}).items():
        if lang not in LANGUAGES or not isinstance(text, str) or not text.strip():
            raise FoundationError('Invalid language/label in native row', 3)
        labels[lang] = {'text': text, 'source_refs': [source_ref(snapshot, locator)]}
    if not labels:
        raise FoundationError('Native row has no supported label', 3)
    parent = row.get('parent_code')
    if parent is not None and (not isinstance(parent, str) or not parent):
        raise FoundationError('Invalid explicit native parent', 3)
    return {'record_type': 'node', 'source_node_id': key.identifier,
            'system': key.system, 'edition_id': key.edition_id, 'level': key.level, 'code': code,
            'source_code_raw': code, 'source_kind': row.get('source_kind', 'native_disease_code'),
            'parent_codes_raw': [parent] if parent else [], 'child_codes_raw': [],
            'preferred_labels': labels, 'source_refs': [source_ref(snapshot, locator)],
            'parse_status': 'parsed', 'source_verified': snapshot.get('source_verified', False),
            'hierarchy_verified': snapshot.get('hierarchy_verified', False),
            'semantic_kind': row.get('kind', 'unknown'), 'raw': row,
            'coding_attributes': {'terminal': None, 'usage': None, 'modifiers': [],
                                  'native_properties': row.get('properties', [])}}


def quarantine(snapshot, raw, locator, reason):
    return {'record_type': 'auxiliary', 'auxiliary_id': identifier('native-row', [snapshot['edition_id'], locator]),
            'kind': 'native_row', 'raw': raw, 'status': 'quarantined', 'reason': reason,
            'source_refs': [source_ref(snapshot, locator)]}


class NativeJSONAdapter(SourceAdapter):
    def parse(self, snapshot):
        SourceStore.verify(snapshot)
        path = Path(snapshot['members'][0]['local_path'])
        if path.stat().st_size > 64 * 1024 * 1024:
            raise FoundationError('Native JSON exceeds resource limit', 3)
        obj = json.loads(path.read_text(encoding='utf-8-sig'))
        rows = []
        if snapshot['format'] == 'fhir':
            if obj.get('resourceType') != 'CodeSystem' or obj.get('version') != snapshot['declared_version']:
                raise FoundationError('Wrong FHIR resource type/version', 3)
            def walk(concepts, parent=None, prefix='/concept'):
                for index, concept in enumerate(concepts):
                    pointer = f'{prefix}/{index}'
                    labels = {}
                    if concept.get('display'):
                        labels[obj.get('language', 'und')] = concept['display']
                    for designation in concept.get('designation', []):
                        # Do not silently choose among conflicting preferred designations.
                        language, value = designation.get('language'), designation.get('value')
                        if language in labels and labels[language] != value:
                            labels[language] = None
                        else:
                            labels[language] = value
                    rows.append(({'code': concept.get('code'), 'level': 'other_group', 'labels': labels,
                                  'parent_code': parent, 'properties': concept.get('property', [])}, pointer))
                    walk(concept.get('concept', []), concept.get('code'), pointer + '/concept')
            walk(obj.get('concept', []))
        else:
            if not isinstance(obj, list):
                raise FoundationError('native_json must contain a list of declared records', 3)
            rows = [(row, f'/{index}') for index, row in enumerate(obj)]
        counts = Counter((r.get('level', 'other_group'), r.get('code')) for r, _ in rows if isinstance(r, dict))
        for row, locator in rows:
            try:
                if not isinstance(row, dict):
                    raise FoundationError('Record is not an object', 3)
                if counts[(row.get('level', 'other_group'), row.get('code'))] > 1:
                    raise FoundationError('Duplicate native code: all conflicting rows quarantined', 3)
                yield native_node(snapshot, row, locator)
            except FoundationError as exc:
                yield quarantine(snapshot, row, locator, str(exc))


class PDFStagingAdapter(SourceAdapter):
    @staticmethod
    def page_records(pages, snapshot):
        return [{'record_type': 'auxiliary', 'auxiliary_id': identifier('pdf-page', [snapshot['edition_id'], index + 1]),
                 'kind': 'pdf_page', 'page': index + 1, 'text_raw': text,
                 'status': 'deferred', 'reason': 'pdf_table_layout_requires_row_review',
                 'source_refs': [source_ref(snapshot, f'page={index + 1};layout=raw;row=unresolved')]}
                for index, text in enumerate(pages)]

    def parse(self, snapshot):
        SourceStore.verify(snapshot)
        if not Path(snapshot['local_path']).read_bytes().startswith(b'%PDF-'):
            raise FoundationError('Expected PDF bytes', 3)
        with tempfile.TemporaryDirectory(prefix='icd10-pdf-') as tmp:
            output = Path(tmp) / 'layout.txt'
            try:
                subprocess.run(['pdftotext', '-layout', snapshot['local_path'], str(output)],
                               check=True, capture_output=True, timeout=180)
            except (OSError, subprocess.SubprocessError) as exc:
                raise FoundationError(f'PDF extraction failed: {exc}', 3) from exc
            if output.stat().st_size > 128 * 1024 * 1024:
                raise FoundationError('PDF text exceeds resource limit', 3)
            pages = output.read_text(encoding='utf-8').split('\f')
            if pages and not pages[-1].strip():
                pages.pop()
            if not pages:
                raise FoundationError('PDF produced no pages', 3)
            yield from self.page_records(pages, snapshot)


class XLSAdapter(SourceAdapter):
    def parse(self, snapshot):
        SourceStore.verify(snapshot)
        try:
            import xlrd
        except ImportError as exc:
            raise FoundationError('XLS source staged; optional approved xlrd dependency is unavailable', 3) from exc
        table = snapshot.get('table')
        if not table:
            raise FoundationError('XLS requires inspected sheet/header/column contract in config', 3)
        try:
            book = xlrd.open_workbook(snapshot['local_path'], on_demand=True)
            if sum(book.sheet_by_index(i).nrows for i in range(book.nsheets)) > 250000:
                raise FoundationError('XLS row resource limit exceeded', 3)
            sheet = book.sheet_by_name(table['sheet'])
            headers = [str(x) for x in sheet.row_values(table['header_row'])]
            if headers != table['headers']:
                raise FoundationError('XLS headers changed; inspect schema before parsing', 3)
            counts = Counter(str(sheet.cell_value(i, table['code_column']))
                             for i in range(table['header_row'] + 1, sheet.nrows))
            for index in range(sheet.nrows):
                cells = sheet.row_values(index)
                locator = f'sheet={sheet.name};row={index + 1};cells=1:{len(cells)}'
                if index <= table['header_row']:
                    yield {'record_type': 'auxiliary', 'auxiliary_id': identifier('xls-header', [snapshot['edition_id'], locator]),
                           'kind': 'xls_header', 'raw': cells, 'status': 'deferred',
                           'source_refs': [source_ref(snapshot, locator)]}
                    continue
                row = {'code': cells[table['code_column']], 'level': 'other_group',
                       'labels': {table['language']: cells[table['label_column']]},
                       'properties': {'raw_cells': cells, 'headers': headers}}
                try:
                    if counts[str(row['code'])] > 1:
                        raise FoundationError('Duplicate or additional-only code; preserve raw row for review', 3)
                    yield native_node(snapshot, row, locator)
                except FoundationError as exc:
                    yield quarantine(snapshot, cells, locator, str(exc))
            for other in book.sheets():
                if other.name == sheet.name:
                    continue
                for index in range(other.nrows):
                    locator = f'sheet={other.name};row={index + 1};cells=1:{other.ncols}'
                    yield {'record_type': 'auxiliary', 'auxiliary_id': identifier('xls-other-sheet', [snapshot['edition_id'], locator]),
                           'kind': 'xls_nonselected_sheet_row', 'raw': other.row_values(index),
                           'status': 'deferred', 'reason': 'different_edition_patch_or_documentation_not_merged',
                           'source_refs': [source_ref(snapshot, locator)]}
        except (xlrd.XLRDError, IndexError, KeyError) as exc:
            raise FoundationError(f'Invalid XLS/schema: {exc}', 3) from exc
        finally:
            if 'book' in locals():
                book.release_resources()
