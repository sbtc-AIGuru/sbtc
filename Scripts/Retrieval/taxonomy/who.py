"""WHO ClaML adapter. Source relations, never code prefixes, define the tree."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import FoundationError, NodeKey, identifier
from .sources import SourceAdapter, SourceStore, source_ref

ROMAN = ('I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI XXII'.split())


def label_text(element, *, omit_references=False) -> str:
    # Markup boundaries matter for Fragment/Para/Reference; preserve full XML separately.
    parts = []
    def walk(node):
        if node.text:
            parts.append(node.text)
        for child in node:
            if not (omit_references and child.tag == 'Reference'):
                walk(child)
            if child.tail:
                parts.append(child.tail)
    walk(element)
    return ' '.join(' '.join(parts).split())


class WHOAdapter(SourceAdapter):
    def parse(self, snapshot: dict):
        SourceStore.verify(snapshot)
        members = [x for x in snapshot['members'] if x['role'].endswith('.xml')]
        if snapshot['format'] == 'claml':
            members = snapshot['members']
        if len(members) != 1:
            raise FoundationError('Exactly one ClaML XML member required', 3)
        member = members[0]
        data = Path(member['local_path']).read_bytes()
        if len(data) > 64 * 1024 * 1024:
            raise FoundationError('XML entities/resource limit prohibited', 3)
        try:
            text = data.decode('utf-8-sig')
            if '<!ENTITY' in text.upper():
                raise FoundationError('XML entity declarations prohibited', 3)
            # stdlib ElementTree does not fetch the external ClaML.dtd.
            root = ET.fromstring(data)
        except (ET.ParseError, UnicodeDecodeError) as exc:
            raise FoundationError(f'Invalid ClaML XML: {exc}', 3) from exc
        if root.tag != 'ClaML' or root.find('Title') is None:
            raise FoundationError('Not a ClaML classification', 3)
        title = dict(root.find('Title').attrib)
        if title.get('version') != snapshot['declared_version']:
            raise FoundationError('Declared and embedded WHO version differ', 3)
        classes = root.findall('Class')
        codes = [x.get('code') for x in classes]
        if None in codes or len(set(codes)) != len(codes):
            raise FoundationError('Missing/duplicate ClaML class code', 3)
        keys = {}
        for element in classes:
            raw, kind = element.get('code'), element.get('kind')
            if kind == 'chapter':
                if raw not in ROMAN:
                    raise FoundationError('Unrecognized chapter identifier', 3)
                code, level = f'{ROMAN.index(raw) + 1:02}', 'chapter'
            elif kind == 'block':
                code, level = raw, 'block'
            elif kind == 'category' and re.fullmatch(r'[A-Z][0-9]{2}(?:\.[A-Za-z0-9]+)?', raw):
                code = raw
                level = 'category' if len(raw) == 3 else 'subcategory'
            else:
                raise FoundationError(f'Unsupported class kind/code {kind}/{raw}', 3)
            keys[raw] = NodeKey('WHO_ICD10', snapshot['edition_id'], level, code)
        for element in classes:
            raw = element.get('code')
            key = keys[raw]
            ref = source_ref(snapshot, f"/ClaML/Class[@code='{raw}']", member)
            labels, rubrics = {}, []
            for number, rubric in enumerate(element.findall('Rubric')):
                locator = ref['locator'] + f'/Rubric[{number + 1}]'
                refs = [source_ref(snapshot, locator, member)]
                for lang_index, label in enumerate(rubric.findall('Label')):
                    language = label.get('{http://www.w3.org/XML/1998/namespace}lang', 'en')
                    text = label_text(label, omit_references=rubric.get('kind') == 'preferred')
                    row = {'record_type': 'rubric', 'rubric_id': identifier('rubric', [key.identifier, number, lang_index]),
                           'source_node_id': key.identifier, 'rubric_kind': rubric.get('kind'),
                           'language': language, 'text_raw': ET.tostring(label, encoding='unicode'),
                           'text': text, 'source_rubric_id': rubric.get('id'), 'source_refs': refs,
                           'references': [{'code_raw': x.get('code'), 'text_raw': label_text(x),
                                           'attributes': dict(x.attrib)} for x in label.iter('Reference')]}
                    rubrics.append(row)
                    if rubric.get('kind') == 'preferred':
                        if language in labels or not text:
                            raise FoundationError('Missing/duplicate preferred label', 3)
                        labels[language] = {'text': text, 'source_refs': refs}
            parents = [x.get('code') for x in element.findall('SuperClass')]
            children = [x.get('code') for x in element.findall('SubClass')]
            yield {'record_type': 'node', 'source_node_id': key.identifier,
                   'system': key.system, 'edition_id': key.edition_id, 'level': key.level, 'code': key.code,
                   'source_code_raw': raw, 'source_kind': element.get('kind'),
                   'parent_codes_raw': parents, 'child_codes_raw': children,
                   'preferred_labels': labels, 'source_refs': [ref], 'parse_status': 'parsed',
                   'source_verified': True, 'declared_title': title,
                   'coding_attributes': {'meta': [dict(x.attrib) for x in element.findall('Meta')],
                                         'usage': element.get('usage'),
                                         'modifiers': [x.get('code') for x in element.findall('ModifiedBy')],
                                         'terminal': None, 'modifier_expansion': 'not_expanded'}}
            yield from rubrics
        for number, element in enumerate(root):
            if element.tag in {'Modifier', 'ModifierClass'}:
                yield {'record_type': 'auxiliary', 'auxiliary_id': identifier('aux', [snapshot['edition_id'], number]),
                       'kind': element.tag, 'code_raw': element.get('code'),
                       'text_raw': ET.tostring(element, encoding='unicode'),
                       'status': 'retained_not_expanded',
                       'source_refs': [source_ref(snapshot, f'/ClaML/*[{number + 1}]', member)]}


def canonical_tree(source_nodes: list[dict]) -> list[dict]:
    if not source_nodes:
        raise FoundationError('Empty WHO taxonomy', 3)
    raw = {x['source_code_raw']: x for x in source_nodes}
    if len(raw) != len(source_nodes) or len({x['edition_id'] for x in source_nodes}) != 1:
        raise FoundationError('Duplicate WHO code/mixed editions', 3)
    parents = {}
    for code, row in raw.items():
        pp = row['parent_codes_raw']
        if ((row['level'] == 'chapter' and pp)
                or (row['level'] != 'chapter' and len(pp) != 1)):
            raise FoundationError(f'Invalid parent cardinality: {code}', 3)
        parents[code] = pp[0] if pp else None
        for p in pp:
            if p not in raw or code not in raw[p]['child_codes_raw']:
                raise FoundationError(f'Missing/conflicting parent: {code}/{p}', 3)
        for c in row['child_codes_raw']:
            if c not in raw or raw[c]['parent_codes_raw'] != [code]:
                raise FoundationError(f'Missing/conflicting child: {code}/{c}', 3)
    output = []
    for code, row in raw.items():
        chain, visited = [], {code}
        parent = parents[code]
        while parent is not None:
            if parent in visited:
                raise FoundationError(f'Hierarchy cycle at {code}', 3)
            visited.add(parent)
            chain.append(raw[parent])
            parent = parents[parent]
        chain.reverse()
        chapter = row if row['level'] == 'chapter' else (chain[0] if chain else None)
        if chapter is None or chapter['level'] != 'chapter' or 'en' not in row['preferred_labels']:
            raise FoundationError(f'Missing chapter/preferred EN: {code}', 3)
        blocks = [x['source_node_id'] for x in chain if x['level'] == 'block']
        en = row['preferred_labels']['en']
        output.append({'schema_version': 1, 'node_id': row['source_node_id'],
                       **{k: row[k] for k in ('system', 'edition_id', 'level', 'code', 'source_code_raw', 'source_kind')},
                       'parent_id': raw[parents[code]]['source_node_id'] if parents[code] else None,
                       'chapter_id': chapter['source_node_id'], 'block_path': blocks,
                       'nearest_block_id': blocks[-1] if blocks else None,
                       'labels': {'en': {'text': en['text'], 'language': 'en', 'origin': 'official_source',
                                        'native_node_id': row['source_node_id'], 'source_refs': en['source_refs'],
                                        'crosswalk_edge_ids': [], 'review_decision_id': None},
                                  'vi': None, 'zh': None},
                       'code_status': 'unknown', 'valid_from': None, 'valid_to': None,
                       'coding_attributes': row['coding_attributes'], 'source_refs': row['source_refs'],
                       'verification': {'status': 'accepted', 'method': 'direct_source',
                                        'evidence_refs': en['source_refs']}})
    return output


class TaxonomyReader:
    def __init__(self, nodes):
        nodes = list(nodes)
        self.nodes = {x['node_id']: x for x in nodes}
        if len(self.nodes) != len(nodes):
            raise FoundationError('Duplicate taxonomy node IDs', 4)

    def node(self, node_id: str):
        return self.nodes.get(node_id)

    def ancestors(self, node_id: str) -> list[dict]:
        if node_id not in self.nodes:
            raise FoundationError(f'Unknown node: {node_id}')
        result, seen = [], {node_id}
        current = self.nodes[node_id]['parent_id']
        while current is not None:
            if current not in self.nodes or current in seen:
                raise FoundationError('Missing ancestor/cycle', 4)
            seen.add(current)
            result.append(self.nodes[current])
            current = self.nodes[current]['parent_id']
        return result
