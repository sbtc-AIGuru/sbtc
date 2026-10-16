"""Deterministic foundation build from pinned sources; never reads corpus/gold."""
from __future__ import annotations

import json
import importlib.metadata
import subprocess
from collections import Counter
from pathlib import Path

from . import VERSION
from .byt import BYTPDFAdapter
from .crosswalk import CrosswalkResolver, apply_edge_reviews, propose_edges, who_projections, attach_equivalent_labels
from .io import read_jsonl, sha_file, write_json, write_jsonl
from .lexicon import curate_senses, make_entry, apply_lexical_reviews
from .models import FoundationError, canonical_json, digest, issue
from .native import NativeJSONAdapter, XLSAdapter, apply_source_reviews
from .normalize import Normalizer
from .sources import SourceStore
from .tabular import reconcile_tabular, tabular_records
from .validation import ReleaseValidator
from .who import WHOAdapter, canonical_tree

TABLE_KEYS = {'source_nodes': 'source_node_id', 'source_rubrics': 'rubric_id',
              'source_auxiliary': 'auxiliary_id', 'taxonomy': 'node_id',
              'crosswalk_edges': 'edge_id', 'topic_projections': 'projection_id',
              'lexicon.verified': 'entry_id', 'ambiguity_groups': 'ambiguity_group_id',
              'review_queue': 'issue_id', 'review_decisions': 'decision_id', 'rejected': 'object_id'}


def code_hashes():
    return {p.name: sha_file(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def protected_hashes():
    root = Path(__file__).parents[1]
    paths = [*root.glob('*.py'), *root.glob('resources/concepts.json'), *root.glob('resources/**/segmentation_*.txt')]
    return {str(p.relative_to(root)): sha_file(p) for p in sorted(paths)}


def parser_environment(manifest):
    result = {'python': __import__('platform').python_version()}
    if any(x['format'] == 'pdf_staging' for x in manifest['sources']):
        probe = subprocess.run(['pdftotext', '-v'], capture_output=True, text=True, timeout=10, check=True)
        result['pdftotext'] = (probe.stderr or probe.stdout).splitlines()[0]
    if any(x['format'] == 'xls' for x in manifest['sources']):
        result['xlrd'] = importlib.metadata.version('xlrd')
    return result


def build(run_dir: Path, *, decisions_path: Path | None = None):
    manifest = json.loads((run_dir / 'source_manifest.json').read_text())
    normalizer = Normalizer()
    decisions = sorted(read_jsonl(decisions_path), key=lambda x: x['decision_id']) if decisions_path else []
    for snapshot in manifest['sources']:
        SourceStore.verify(snapshot)
    environment = parser_environment(manifest)
    initial_code_hashes = code_hashes()
    fingerprint = digest(canonical_json({'sources': [(x['source_id'], x['edition_id']) for x in manifest['sources']],
                                         'config': manifest['config_sha256'], 'code': initial_code_hashes,
                                         'normalizer': normalizer.profile_id, 'decisions': decisions, 'parsers': environment}))
    state_path = run_dir / 'build_manifest.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['fingerprint'] != fingerprint:
            raise FoundationError('Incompatible resume: code/config/source/review changed; use a new run', 5)
        for name, expected in state['artifacts'].items():
            p = run_dir / name
            if not p.is_file() or sha_file(p) != expected['sha256']:
                raise FoundationError(f'Build artifact changed: {name}', 5)
        return load_bundle(run_dir)
    if any((run_dir / (name + '.jsonl')).exists() for name in TABLE_KEYS):
        raise FoundationError('Uncommitted partial build found; use a new run directory', 5)
    before = protected_hashes()
    nodes, rubrics, auxiliary, queue, reconciliation = [], [], [], [], []
    for snapshot in manifest['sources']:
        fmt = snapshot['format']
        adapter = {'claml': WHOAdapter, 'claml_zip': WHOAdapter, 'fhir': NativeJSONAdapter,
                   'native_json': NativeJSONAdapter, 'pdf_staging': BYTPDFAdapter, 'xls': XLSAdapter}.get(fmt)
        if fmt == 'tabular_zip':
            records = list(tabular_records(snapshot))
        elif adapter:
            records = list(adapter().parse(snapshot))
        else:
            raise FoundationError(f'Unsupported source format: {fmt}', 3)
        records = apply_source_reviews(records, decisions)
        counts = Counter()
        for row in records:
            if row['record_type'] == 'node':
                nodes.append(row)
                counts['quarantined' if row.get('parse_status') == 'quarantined' else 'accepted'] += 1
            elif row['record_type'] == 'rubric':
                rubrics.append(row)
                counts['accepted'] += 1
            else:
                auxiliary.append(row)
                status = row.get('status')
                disposition = status if status in {'rejected', 'quarantined'} else 'deferred'
                counts[disposition] += 1
                if row['kind'] != 'xls_nonselected_sheet_row' and not row['kind'].startswith('tabular_'):
                    queue.append(issue(row.get('reason', 'source_auxiliary_not_expanded'), row['auxiliary_id'], evidence=row['source_refs']))
        reconciliation.append({'source_id': snapshot['source_id'], 'input_units': len(records),
                               'unit': 'parsed class + rubric + modifier' if fmt.startswith('claml') else
                                       ('PDF page + unverified STT row candidate' if fmt == 'pdf_staging' else 'physical row'),
                               **{k: counts[k] for k in ('accepted', 'quarantined', 'rejected', 'deferred')},
                               'record_types': dict(Counter(x['record_type'] for x in records)),
                               'raw_row_count_known': fmt != 'pdf_staging'})
    who_nodes = [x for x in nodes if x['system'] == 'WHO_ICD10']
    full_tree = canonical_tree(who_nodes)
    core = [x for x in full_tree if x['level'] != 'subcategory']
    full_by_id = {x['node_id']: x for x in full_tree}
    native = [x for x in nodes if x['system'] != 'WHO_ICD10']
    edges = apply_edge_reviews(propose_edges(native, core), decisions)
    projections = CrosswalkResolver(edges, decisions, core, {x['source_node_id'] for x in nodes}, native).projections()
    projections.extend(who_projections(who_nodes, core))
    queue.extend(attach_equivalent_labels(core, native, edges))
    projection_ids = {}
    for projection in projections:
        projection_ids.setdefault(projection['source_node_id'], []).append(projection['projection_id'])
    for edge in edges:
        if edge['verification']['status'] == 'candidate':
            queue.append(issue('crosswalk_semantics_unverified', edge['edge_id'], candidates=[edge], evidence=edge['source_refs']))
    # Source-supported coarse kind rule; not a clinical diagnosis or language-model inference.
    # ICD chapters XX/XXI are external causes/contact factors, XVIII signs/findings.
    chapters = {x['node_id']: x['code'] for x in full_tree if x['level'] == 'chapter'}
    candidates = []
    for node in nodes:
        who = full_by_id.get(node['source_node_id'])
        if who:
            chapter = chapters[who['chapter_id']]
            kind = 'context_modifier' if chapter in {'20', '21'} else ('symptom_sign' if chapter == '18' else 'disease_or_condition')
            usage = 'context_only' if kind == 'context_modifier' else 'topic_candidate'
        else:
            kind, usage = node.get('semantic_kind', 'unknown'), 'abstain'
        for lang, label in node['preferred_labels'].items():
            link = {'target_node_id': node['source_node_id'], 'relation': 'exact_concept',
                    'usage': usage, 'projection_ids': sorted(projection_ids.get(node['source_node_id'], [])),
                    'source_refs': label['source_refs'], 'review_decision_id': None}
            candidates.append(make_entry(label['text'], lang, node['source_node_id'], kind, usage, normalizer,
                                         source_refs=label['source_refs'], accepted=node['source_verified'], links=[link]))
    candidates = apply_lexical_reviews(candidates, decisions)
    known_review_objects = ({x['source_node_id'] for x in nodes} | {x['edge_id'] for x in edges}
                            | {x['entry_id'] for x in candidates})
    for decision in decisions:
        if decision['object_id'] not in known_review_objects:
            raise FoundationError(f'Review decision targets an unknown/unsupported object: {decision["object_id"]}', 4)
    verified, groups, lexical_issues = curate_senses(candidates, normalizer)
    queue.extend(lexical_issues)
    # Inclusion text may contain lists/references. Preserve as review candidates, never copy exclusions.
    for row in rubrics:
        if row['rubric_kind'] == 'inclusion':
            queue.append(issue('inclusion_requires_term_and_scope_review', row['rubric_id'], evidence=row['source_refs']))
    bundle = {'source_manifest': manifest, 'source_nodes': nodes, 'source_rubrics': rubrics,
              'source_auxiliary': auxiliary, 'taxonomy': core, 'crosswalk_edges': edges,
              'topic_projections': projections, 'lexicon.verified': verified,
              'ambiguity_groups': groups, 'review_queue': queue, 'review_decisions': decisions,
              'rejected': [{'object_id': x['edge_id'], 'reason': 'review_rejected', 'decision_id': x['review_decision_id']}
                           for x in edges if x['verification']['status'] == 'rejected'] +
                          [{'object_id': x['entry_id'], 'reason': 'lexical_review_rejected',
                            'decision_id': x['review_decision_ids'][-1]} for x in candidates
                           if x['verification']['acceptance'] == 'rejected'],
              'reconciliation': {'sources': reconciliation}, 'normalization': normalizer.profile}
    report = ReleaseValidator().validate(bundle, normalizer=normalizer)
    after = protected_hashes()
    if before != after:
        raise FoundationError('Protected production resource/code changed during build', 4)
    if initial_code_hashes != code_hashes():
        raise FoundationError('Taxonomy implementation changed during build; use a new run after code settles', 5)
    report['production_hashes_unchanged'] = True
    for name, key in TABLE_KEYS.items():
        write_jsonl(run_dir / (name + '.jsonl'), bundle[name], key=key)
    for name, value in [('coverage', report['coverage']), ('reconciliation', bundle['reconciliation']),
                        ('normalization', normalizer.profile), ('validation', report),
                        ('ambiguity_report', {'groups': len(groups), 'policy': 'pending competitors retained'}),
                        ('protected-production-hashes', before)]:
        write_json(run_dir / (name + '.json'), value)
    crosscheck = reconcile_tabular([x for x in auxiliary if x['kind'].startswith('tabular_')], who_nodes)
    write_json(run_dir / 'audit/tabular-reconciliation.json', crosscheck)
    state = {'schema_version': 1, 'version': VERSION, 'fingerprint': fingerprint,
             'parser_environment': environment,
             'code_hashes': initial_code_hashes, 'normalization_profile': normalizer.profile_id,
             'artifacts': {}}
    for path in sorted(run_dir.rglob('*')):
        if path.is_file() and path.name != 'build_manifest.json':
            state['artifacts'][str(path.relative_to(run_dir))] = {'sha256': sha_file(path), 'bytes': path.stat().st_size}
    write_json(state_path, state)
    if not report['passed']:
        raise FoundationError(f'Build retained for audit but validation failed: {report["errors"][:3]}', 4)
    return bundle


def load_bundle(run_dir):
    bundle = {name: list(read_jsonl(run_dir / (name + '.jsonl'))) for name in TABLE_KEYS}
    for name in ('source_manifest', 'reconciliation', 'normalization'):
        bundle[name] = json.loads((run_dir / (name + '.json')).read_text())
    return bundle
