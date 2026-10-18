"""Reviewed cross-system links and conservative topic projections."""
from __future__ import annotations

from .models import FoundationError, identifier
from .who import TaxonomyReader, canonical_tree

RELATIONS = {'equivalent', 'narrower_than', 'broader_than', 'related_to'}


def who_projections(source_nodes, canonical):
    """Direct source hierarchy evidence, distinct from a cross-system equivalence."""
    full = canonical_tree(source_nodes)
    reader = TaxonomyReader(full)
    core_ids = {n['node_id'] for n in canonical}
    result = []
    for node in full:
        path = []
        for ancestor in [node, *reader.ancestors(node['node_id'])]:
            path.append(ancestor['node_id'])
            if ancestor['node_id'] not in core_ids or ancestor['level'] not in {'chapter', 'block', 'category'}:
                continue
            result.append({'projection_id': identifier('who-ancestry', [node['node_id'], ancestor['node_id']]),
                           'source_node_id': node['node_id'], 'target_node_id': ancestor['node_id'],
                           'scope': ancestor['level'], 'path': path.copy(), 'status': 'accepted',
                           'source_refs': node['source_refs'] + ancestor['source_refs'],
                           'review_decision_id': None, 'method': 'direct_who_hierarchy'})
    return result


def attach_equivalent_labels(canonical, native_nodes, edges):
    native = {n['source_node_id']: n for n in native_nodes}
    by_target = {n['node_id']: n for n in canonical}
    candidates, problems = {}, []
    for edge in edges:
        if edge['verification']['status'] != 'accepted' or edge['relation'] != 'equivalent':
            continue
        source = native[edge['source_node_id']]
        if not source.get('source_verified'):
            continue
        for lang, label in source['preferred_labels'].items():
            if lang not in {'vi', 'zh'}:
                continue
            candidates.setdefault((edge['target_node_id'], lang), []).append((edge, source, label))
    from .models import issue
    for (target_id, lang), choices in candidates.items():
        if len({label['text'] for _, _, label in choices}) != 1:
            problems.append(issue('preferred_translation_conflict', target_id + ':' + lang,
                                  candidates=[{'edge_id': e['edge_id'], 'label': l} for e, _, l in choices]))
            continue
        choices.sort(key=lambda x: x[0]['edge_id'])
        edge, source, label = choices[0]
        by_target[target_id]['labels'][lang] = {
            'text': label['text'], 'language': lang, 'origin': 'equivalent_crosswalk',
            'native_node_id': source['source_node_id'],
            'source_refs': [ref for _, _, l in choices for ref in l['source_refs']],
            'crosswalk_edge_ids': [e['edge_id'] for e, _, _ in choices],
            'review_decision_id': edge['review_decision_id']}
    return problems


def active_decisions(rows: list[dict]) -> dict[str, dict]:
    by_id = {row['decision_id']: row for row in rows}
    if len(by_id) != len(rows):
        raise FoundationError('Duplicate review decision ID', 4)
    replaced = set()
    for row in rows:
        if (row.get('decision') not in {'accept', 'reject', 'defer'}
                or not all(row.get(k) for k in ('reviewer', 'method', 'rationale', 'source_refs'))):
            raise FoundationError('Incomplete review decision', 4)
        seen = {row['decision_id']}
        parent = row.get('supersedes')
        if parent:
            if parent in replaced:
                raise FoundationError('Forked decision supersession', 4)
            replaced.add(parent)
        while parent:
            if parent not in by_id or parent in seen or by_id[parent]['object_id'] != row['object_id']:
                raise FoundationError('Broken/cyclic review supersession', 4)
            seen.add(parent)
            parent = by_id[parent].get('supersedes')
    result = {}
    for key, row in by_id.items():
        if key not in replaced:
            if row['object_id'] in result:
                raise FoundationError('Conflicting active decisions', 4)
            result[row['object_id']] = row
    return result


def propose_edges(native_nodes: list[dict], canonical: list[dict]) -> list[dict]:
    # Candidates have no inferred semantic relation, even for identical code strings.
    by_code = {}
    for node in canonical:
        by_code.setdefault(node['code'], []).append(node)
    result = []
    for source in native_nodes:
        code = source['code']
        potential = [(code, 'code_equality')]
        if len(code) > 3:
            potential.append((code[:3], 'code_prefix'))
        seen = set()
        for proposed, method in potential:
            for target in by_code.get(proposed, []):
                if target['node_id'] in seen:
                    continue
                seen.add(target['node_id'])
                result.append({'edge_id': identifier('crosswalk', [source['source_node_id'], target['node_id']]),
                               'source_node_id': source['source_node_id'], 'target_node_id': target['node_id'],
                               'relation': None, 'verification': {'status': 'candidate'},
                               'source_refs': source['source_refs'] + target['source_refs'],
                               'mapping_method': method, 'review_decision_id': None})
    return result


def apply_edge_reviews(edges: list[dict], decisions: list[dict]) -> list[dict]:
    active = active_decisions(decisions)
    output = []
    for edge in edges:
        decision = active.get(edge['edge_id'])
        if decision:
            edge = {**edge, 'review_decision_id': decision['decision_id'],
                    'source_refs': edge['source_refs'] + decision['source_refs'],
                    'verification': {'status': {'accept': 'accepted', 'reject': 'rejected', 'defer': 'candidate'}[decision['decision']]}}
            if decision['decision'] == 'accept':
                edge.update(relation=decision.get('relation'), mapping_method='source_grounded_review')
        output.append(edge)
    return output


class CrosswalkResolver:
    def __init__(self, edges, decisions, canonical, source_ids, native_nodes=()):
        self.edges = edges
        self.reader = TaxonomyReader(canonical)
        self.active = active_decisions(decisions)
        self.by_source = {}
        self.native = {x['source_node_id']: x for x in native_nodes}
        self.native_codes = {}
        for node in native_nodes:
            self.native_codes.setdefault((node['system'], node['edition_id'], node['code']), []).append(node)
        ids = set()
        for edge in edges:
            if edge['edge_id'] in ids:
                raise FoundationError('Duplicate crosswalk edge', 4)
            ids.add(edge['edge_id'])
            if edge['source_node_id'] not in source_ids or not self.reader.node(edge['target_node_id']):
                raise FoundationError('Crosswalk has missing source/target', 4)
            status = edge['verification']['status']
            if status not in {'candidate', 'accepted', 'rejected'}:
                raise FoundationError('Invalid crosswalk status', 4)
            if status == 'accepted':
                if edge['source_node_id'] in self.native and self.native[edge['source_node_id']].get('source_verified') is not True:
                    raise FoundationError('Accepted crosswalk uses unverified native source extraction', 4)
                decision = self.active.get(edge['edge_id'])
                if (edge.get('relation') not in RELATIONS or not edge.get('source_refs')
                        or edge.get('mapping_method') not in {'source_grounded_review', 'official_crosswalk'}
                        or not decision or decision['decision'] != 'accept'
                        or decision['decision_id'] != edge.get('review_decision_id')
                        or decision.get('relation') != edge['relation']):
                    raise FoundationError('Accepted crosswalk lacks reviewed semantic evidence', 4)
            self.by_source.setdefault(edge['source_node_id'], []).append(edge)

    def candidates(self, source_node_id):
        return list(self.by_source.get(source_node_id, []))

    def projections(self):
        result = []
        paths = [(edge['source_node_id'], [], [], edge) for edge in self.edges]
        # Explicit, verified native parent edges can project a leaf via its ancestor.
        # The resulting projection never claims the leaf itself is equivalent.
        for source_id, source in self.native.items():
            current, seen, native_path, refs = source, {source_id}, [], []
            while current.get('source_verified') and current.get('hierarchy_verified'):
                parents = current.get('parent_codes_raw', [])
                if len(parents) != 1:
                    break
                choices = self.native_codes.get((current['system'], current['edition_id'], parents[0]), [])
                if len(choices) != 1:
                    break
                parent = choices[0]
                if parent.get('source_verified') is not True:
                    break
                parent_id = parent['source_node_id']
                if parent_id in seen:
                    raise FoundationError('Cycle in verified native hierarchy', 4)
                seen.add(parent_id)
                native_path.append(parent_id)
                refs.extend(current['source_refs'])
                for edge in self.by_source.get(parent_id, []):
                    paths.append((source_id, native_path.copy(), refs.copy(), edge))
                current = parent
        for source_id, native_path, native_refs, edge in paths:
            if edge['verification']['status'] != 'accepted' or edge['relation'] not in {'equivalent', 'narrower_than'}:
                continue
            target = self.reader.node(edge['target_node_id'])
            path = native_path + [edge['edge_id']]
            for node in [target, *self.reader.ancestors(target['node_id'])]:
                path.append(node['node_id'])
                if node['level'] not in {'chapter', 'block', 'category'}:
                    continue
                result.append({'projection_id': identifier('projection', [source_id, native_path, edge['edge_id'], node['node_id']]),
                               'source_node_id': source_id, 'target_node_id': node['node_id'],
                               'scope': node['level'], 'path': path.copy(), 'status': 'accepted',
                               'source_refs': native_refs + edge['source_refs'], 'review_decision_id': edge['review_decision_id']})
        return result
