"""Structural validation and explicit release gates; coverage is not accuracy."""
from __future__ import annotations

from collections import Counter
from datetime import date
import re

from .crosswalk import CrosswalkResolver, active_decisions, who_projections
from .lexicon import KINDS, USAGES, LexiconReader
from .models import FoundationError, LANGUAGES, NodeKey, canonical_json, identifier
from .sources import SourceStore
from .who import TaxonomyReader


def release_profile(errors, coverage, audit):
    if errors:
        return 'rejected'
    if not audit or not all(audit.get(k) is True for k in ('passed', 'gold_approved', 'holdout', 'performance_passed', 'gold_contract_complete')):
        return 'audit_only'
    if (audit.get('cases', 0) < 200 or any(audit.get('language_counts', {}).get(x, 0) < 50 for x in LANGUAGES)
            or audit.get('official_mapping_precision', 0) < .99 or audit.get('resolved_precision', 0) < .98):
        return 'audit_only'
    return 'core_ready' if coverage['core_multilingual_complete'] else 'pilot_partial'


def coverage_report(nodes, entries, groups):
    levels = {}
    for level in sorted({x['level'] for x in nodes}):
        subset = [x for x in nodes if x['level'] == level]
        levels[level] = {'denominator': len(subset), 'labels': {}}
        for lang in LANGUAGES:
            missing = sorted(x['node_id'] for x in subset if not x['labels'].get(lang))
            levels[level]['labels'][lang] = {'numerator': len(subset) - len(missing),
                                            'denominator': len(subset), 'missing_node_ids': missing}
    return {'levels': levels, 'editions': sorted({x['edition_id'] for x in nodes}),
            'core_multilingual_complete': bool(nodes) and all(
                levels.get(level, {}).get('denominator', 0) > 0 and all(
                    not levels[level]['labels'][lang]['missing_node_ids'] for lang in LANGUAGES)
                for level in ('chapter', 'block')),
            'lexicon': {'accepted_senses': len(entries),
                        'distinct_surfaces': len({(x['language'], x['term_normalized']) for x in entries}),
                        'languages': dict(Counter(x['language'] for x in entries)),
                        'kinds': dict(Counter(x['kind'] for x in entries)),
                        'usages': dict(Counter(x['usage'] for x in entries)),
                        'links': dict(Counter(y['relation'] for x in entries for y in x['links'])),
                        'ambiguity_groups': len(groups)}}


class ReleaseValidator:
    def validate(self, bundle, *, normalizer=None, verify_sources=True):
        errors, warnings = [], []
        def check(condition, gate, detail):
            if not condition:
                errors.append({'gate': gate, 'severity': 'error', 'detail': detail})
        try:
            canonical_json(bundle)
            nodes = bundle.get('taxonomy', [])
            source_nodes = bundle.get('source_nodes', [])
            entries = bundle.get('lexicon.verified', [])
            rubrics = bundle.get('source_rubrics', [])
            edges = bundle.get('crosswalk_edges', [])
            projections = bundle.get('topic_projections', [])
            groups = bundle.get('ambiguity_groups', [])
            decisions = bundle.get('review_decisions', [])
            snapshots = bundle.get('source_manifest', {}).get('sources', [])
            check(bool(nodes) and bool(source_nodes) and bool(snapshots), 'F01', 'Empty taxonomy/source bundle')
            tables = [('taxonomy', nodes, 'node_id'), ('source_nodes', source_nodes, 'source_node_id'),
                      ('source_auxiliary', bundle.get('source_auxiliary', []), 'auxiliary_id'),
                      ('review_queue', bundle.get('review_queue', []), 'issue_id'),
                      ('rejected', bundle.get('rejected', []), 'object_id'),
                      ('lexicon', entries, 'entry_id'), ('rubrics', rubrics, 'rubric_id'),
                      ('edges', edges, 'edge_id'), ('projections', projections, 'projection_id'),
                      ('ambiguity', groups, 'ambiguity_group_id'), ('decisions', decisions, 'decision_id')]
            for name, rows, field in tables:
                check(len({x[field] for x in rows}) == len(rows), 'F01', f'Duplicate {name} IDs')
            source_by_id = {x['source_node_id']: x for x in source_nodes}
            canonical = {x['node_id']: x for x in nodes}
            snapshots_by_hash = {(x['source_id'], x['content_sha256']): x for x in snapshots}
            if verify_sources:
                for snapshot in snapshots:
                    SourceStore.verify(snapshot)

            def valid_refs(refs):
                if not isinstance(refs, list) or not refs:
                    return False
                for ref in refs:
                    snap = snapshots_by_hash.get((ref.get('source_id'), ref.get('snapshot_sha256')))
                    if (not snap or ref.get('member_sha256') not in {m['content_sha256'] for m in snap['members']}
                            or not isinstance(ref.get('locator'), str) or not ref['locator'].strip()):
                        return False
                return True

            active = active_decisions(decisions)
            by_decision = {d['decision_id']: d for d in decisions}
            def accepted_review(object_id, decision_id):
                decision = active.get(object_id)
                return (decision is not None and decision['decision'] == 'accept'
                        and decision['decision_id'] == decision_id)
            edges_by_id = {e['edge_id']: e for e in edges}
            reader = TaxonomyReader(nodes)
            keys = set()
            for node in nodes:
                key = NodeKey(node['system'], node['edition_id'], node['level'], node['code'])
                check(key.identifier == node['node_id'] and key not in keys and node['schema_version'] == 1,
                      'F01', f'Invalid node identity/schema: {node["node_id"]}')
                keys.add(key)
                check(type(node['schema_version']) is int, 'F01', 'Schema version must be an integer, not boolean')
                grammar = {'chapter': r'(0[1-9]|1[0-9]|2[0-2])', 'block': r'[A-Z][0-9]{2}-[A-Z][0-9]{2}',
                           'category': r'[A-Z][0-9]{2}', 'subcategory': r'[A-Z][0-9]{2}\.[A-Za-z0-9]+'}
                check(node['level'] not in grammar or re.fullmatch(grammar[node['level']], node['code']) is not None,
                      'F01', 'Invalid canonical code/placeholder')
                for field in ('valid_from', 'valid_to'):
                    if node[field] is not None:
                        check(isinstance(node[field], str) and date.fromisoformat(node[field]).isoformat() == node[field],
                              'F01', 'Invalid source validity date')
                check(key.system == 'WHO_ICD10', 'F01', 'Canonical node is not WHO')
                check(node['code_status'] in {'active', 'inactive', 'deprecated', 'unknown'}, 'F01', 'Unknown code status')
                source = source_by_id.get(node['node_id'])
                check(source is not None, 'F06', 'Canonical node missing native WHO evidence')
                check(source and source.get('source_verified') is True, 'F06', 'Canonical source extraction is not verified')
                ancestors = list(reversed(reader.ancestors(node['node_id'])))
                check(all(x['edition_id'] == node['edition_id'] and x['system'] == node['system'] for x in ancestors),
                      'F02', 'Ancestor edition/system mismatch')
                blocks = [x['node_id'] for x in ancestors if x['level'] == 'block']
                chapter = node if node['level'] == 'chapter' else (ancestors[0] if ancestors else None)
                check(chapter and chapter['level'] == 'chapter' and chapter['node_id'] == node['chapter_id']
                      and blocks == node['block_path'] and node['nearest_block_id'] == (blocks[-1] if blocks else None),
                      'F02', f'Incorrect hierarchy metadata: {node["code"]}')
                check(valid_refs(node['source_refs']), 'F06', 'Node has invalid provenance')
                check(node['verification']['status'] == 'accepted', 'F06', 'Unaccepted canonical node')
                en = node['labels'].get('en')
                check(en and source and en['text'] == source['preferred_labels'].get('en', {}).get('text'),
                      'F07', f'Preferred EN differs from WHO source: {node["code"]}')
                check(set(node['labels']) == set(LANGUAGES), 'F01', 'Missing language slots')
                for lang, assertion in node['labels'].items():
                    if assertion is None:
                        continue
                    check(assertion['language'] == lang and valid_refs(assertion['source_refs']), 'F06', 'Invalid label assertion')
                    check(isinstance(assertion['text'], str) and bool(assertion['text'].strip())
                          and assertion['origin'] in {'official_source', 'equivalent_crosswalk', 'reviewed_display_label'},
                          'F01', 'Invalid label text/origin')
                    if assertion['origin'] == 'official_source':
                        check(lang == 'en' and assertion['native_node_id'] == node['node_id']
                              and all(ref in source['preferred_labels']['en']['source_refs'] for ref in assertion['source_refs']),
                              'F06', 'Official WHO label borrows unrelated native evidence')
                    elif assertion['origin'] == 'equivalent_crosswalk':
                        assertions = [edges_by_id.get(key) for key in assertion['crosswalk_edge_ids']]
                        valid = bool(assertions) and all(e and e['verification']['status'] == 'accepted'
                            and e['relation'] == 'equivalent' and e['target_node_id'] == node['node_id']
                            and source_by_id[e['source_node_id']]['preferred_labels'].get(lang, {}).get('text') == assertion['text']
                            and source_by_id[e['source_node_id']].get('source_verified') is True for e in assertions)
                        check(valid and assertion['native_node_id'] in {e['source_node_id'] for e in assertions if e}
                              and assertion['review_decision_id'] in {e['review_decision_id'] for e in assertions if e},
                              'F06', 'Multilingual label lacks equivalent crosswalk for this node/language/scope')
                    else:
                        review = active.get(node['node_id'])
                        check(review and accepted_review(node['node_id'], assertion['review_decision_id'])
                              and review.get('label_assertion') == {'language': lang, 'text': assertion['text']},
                              'F06', 'Reviewed display label borrows an unrelated review')
            for source in source_nodes:
                key = NodeKey(source['system'], source['edition_id'], source['level'], source['code'])
                check(key.identifier == source['source_node_id'] and valid_refs(source['source_refs']), 'F06', 'Invalid native node')
                snapshot = snapshots_by_hash.get((source['source_refs'][0]['source_id'], source['source_refs'][0]['snapshot_sha256']))
                check(snapshot and snapshot['system'] == source['system'] and snapshot['edition_id'] == source['edition_id'],
                      'F06', 'Source node namespace differs from its snapshot')
                check(type(source.get('source_verified')) is bool, 'F01', 'Source verification is not boolean')
                if source['system'] != 'WHO_ICD10' and source.get('source_verified') is True and snapshot.get('source_verified') is not True:
                    review_id = source.get('source_review_decision_id')
                    check(accepted_review(source['source_node_id'], review_id)
                          and by_decision.get(review_id, {}).get('extraction_verified') is True,
                          'F06', 'Native extraction promoted without source review')
                if source['system'] == 'WHO_ICD10' and source['level'] in {'chapter', 'block', 'category', 'other_group'}:
                    check(source['source_node_id'] in canonical, 'F03', 'WHO core node omitted')
            for row in rubrics:
                check(row['source_node_id'] in source_by_id and valid_refs(row['source_refs']), 'F05', 'Invalid rubric FK/provenance')
            for row in bundle.get('source_auxiliary', []):
                check(valid_refs(row['source_refs']), 'F06', 'Invalid retained source evidence')
            resolver = CrosswalkResolver(edges, decisions, nodes, set(source_by_id),
                                         [x for x in source_nodes if x['system'] != 'WHO_ICD10'])
            expected_projections = resolver.projections() + who_projections([x for x in source_nodes if x['system'] == 'WHO_ICD10'], nodes)
            check(sorted(expected_projections, key=lambda x: x['projection_id']) == sorted(projections, key=lambda x: x['projection_id']),
                  'F04', 'Projection table differs from reviewed ancestry paths')
            for decision in decisions:
                check(valid_refs(decision['source_refs']), 'F06', 'Review evidence is not a pinned source reference')
            pids = {x['projection_id'] for x in projections}
            projections_by_id = {p['projection_id']: p for p in projections}
            group_ids = {x['ambiguity_group_id'] for x in groups}
            groups_by_id = {g['ambiguity_group_id']: g for g in groups}
            for group in groups:
                check(len({s['sense_id'] for s in group['senses']}) > 1, 'F09', 'Ambiguity group has fewer than two senses')
                check(group['ambiguity_group_id'] == identifier('ambiguity', [group['normalization_profile'], group['language'], group['term_normalized']]),
                      'F09', 'Invalid ambiguity identity')
                check(group['language'] in LANGUAGES and (normalizer is None or group['normalization_profile'] == normalizer.profile_id),
                      'F09', 'Ambiguity registry normalization/language incompatible')
            # Reconcile runtime registry against pending competitor senses in the review ledger.
            all_senses = {}
            ledger_entries = {}
            for row in entries:
                all_senses.setdefault((row['language'], row['term_normalized']), set()).add(row['sense_id'])
                ledger_entries[row['entry_id']] = row
            for problem in bundle.get('review_queue', []):
                for candidate in problem.get('candidates', []):
                    if isinstance(candidate, dict) and 'entry_id' in candidate and 'sense_id' in candidate:
                        all_senses.setdefault((candidate['language'], candidate['term_normalized']), set()).add(candidate['sense_id'])
                        ledger_entries[candidate['entry_id']] = candidate
            groups_by_surface = {(g['language'], g['term_normalized']): g for g in groups}
            for surface, senses in all_senses.items():
                if len(senses) > 1:
                    group = groups_by_surface.get(surface)
                    check(group and senses <= {x['sense_id'] for x in group['senses']}, 'F09', 'Pending competitor omitted from ambiguity registry')
            for group in groups:
                for sense in group['senses']:
                    candidate = ledger_entries.get(sense['entry_id'])
                    check(candidate and candidate['sense_id'] == sense['sense_id']
                          and candidate['verification']['acceptance'] == sense['status'],
                          'F09', 'Ambiguity state differs from accepted/pending review ledger')
            for row in entries:
                check(row['entry_id'] == identifier('lex', [row['language'], row['term_raw'], row['sense_id'], row['lexical_relation']]),
                      'F01', 'Invalid lexical identity')
                check(row['kind'] in KINDS - {'unknown'} and row['usage'] in USAGES, 'F10', 'Invalid runtime kind/usage')
                check(row['language'] in LANGUAGES and type(row['schema_version']) is int and row['schema_version'] == 1,
                      'F01', 'Invalid lexical language/schema')
                policy = row['matching_policy']
                check(policy['case_policy'] in {'sensitive', 'insensitive'} and policy['boundary_policy'] in
                      {'latin_token', 'cjk_phrase', 'code_literal', 'exact_surface'}, 'F01', 'Invalid matching policy')
                check(row['verification']['acceptance'] == 'accepted'
                      and row['verification']['extraction_status'] == 'source_verified'
                      and row['verification']['semantic_status'] in {'direct_official_label', 'source_supported', 'independently_reviewed'},
                      'F10', 'Unverified sense leaked to runtime')
                check(valid_refs(row['source_refs']), 'F06', 'Invalid lexical evidence')
                check(row['ambiguity_group_id'] is None or row['ambiguity_group_id'] in group_ids, 'F09', 'Missing ambiguity registry')
                group = groups_by_id.get(row['ambiguity_group_id'])
                expected_group = groups_by_surface.get((row['language'], row['term_normalized']))
                check((not expected_group and group is None) or (group and expected_group is group
                      and any(s['entry_id'] == row['entry_id'] and s['sense_id'] == row['sense_id']
                              and s['status'] == 'accepted' for s in group['senses'])), 'F09', 'Lexical entry attached to wrong ambiguity group')
                for decision_id in row['review_decision_ids']:
                    check(decision_id in by_decision and by_decision[decision_id]['object_id'] == row['entry_id'],
                          'F06', 'Lexical review references unrelated/missing decision')
                if row['verification']['semantic_status'] == 'independently_reviewed' or row['lexical_relation'] not in {'official_label', 'context_term'}:
                    check(any(accepted_review(row['entry_id'], key) for key in row['review_decision_ids']),
                          'F06', 'Lexical sense lacks an active acceptance decision')
                if row['lexical_relation'] == 'official_label':
                    source = source_by_id.get(row['sense_id'])
                    check(source and source['preferred_labels'].get(row['language'], {}).get('text') == row['term_raw'],
                          'F05', 'Official lexical label not present in preferred source rubric')
                    check(source and source.get('source_verified') is True, 'F06', 'Unverified source used as official lexical label')
                for link in row['links']:
                    check(link['target_node_id'] in source_by_id and valid_refs(link['source_refs'])
                          and link['relation'] in {'exact_concept', 'narrower_concept', 'topic_association', 'supporting_evidence'}
                          and link['usage'] in USAGES and set(link['projection_ids']) <= pids,
                          'F04', 'Invalid lexical link')
                    for projection_id in link['projection_ids']:
                        projection = projections_by_id.get(projection_id)
                        check(projection and projection['source_node_id'] in {row['sense_id'], link['target_node_id']},
                              'F04', 'Link borrows another sense projection')
                    direct = link['target_node_id'] == row['sense_id'] and link['relation'] == 'exact_concept'
                    if link.get('review_decision_id'):
                        review = by_decision.get(link['review_decision_id'])
                        check(review and accepted_review(review['object_id'], review['decision_id'])
                              and (direct and review['object_id'] == row['entry_id'] or
                                   review.get('link_assertion') == {'entry_id': row['entry_id'], 'target_node_id': link['target_node_id'],
                                                                  'relation': link['relation'], 'usage': link['usage']}),
                              'F04', 'Link review does not accept this association')
                    else:
                        check(direct and row['lexical_relation'] == 'official_label', 'F04', 'Inferred lexical link lacks review')
                if normalizer:
                    views = normalizer.views(row['term_raw'], row['language'])
                    check(views['normalized'] == row['term_normalized'] and views['case_preserved'] == row['term_case_preserved']
                          and views == normalizer.views(views['case_preserved'], row['language']), 'F08', 'Normalization mismatch/not idempotent')
            if normalizer:
                LexiconReader(entries, groups, normalizer)
            reconciliation = bundle.get('reconciliation', {})
            unit_counts = Counter(ref['source_id'] for table in (source_nodes, rubrics, bundle.get('source_auxiliary', []))
                                  for row in table for ref in row['source_refs'][:1])
            for source in reconciliation.get('sources', []):
                check(source['input_units'] == sum(source[k] for k in ('accepted', 'quarantined', 'rejected', 'deferred')),
                      'F03', 'Unreconciled source units')
                check(source['input_units'] == unit_counts[source['source_id']], 'F03', 'Source units differ from retained records')
            check(bool(reconciliation.get('sources')), 'F03', 'Reconciliation ledger missing')
            failed = bundle.get('source_manifest', {}).get('failures', [])
            if failed:
                warnings.append({'gate': 'F03', 'detail': 'Some configured sources unavailable', 'sources': failed})
            coverage = coverage_report(nodes, entries, groups)
            if not coverage['core_multilingual_complete']:
                warnings.append({'gate': 'F07', 'detail': 'VI/ZH chapter/block preferred labels incomplete; see coverage ledger'})
        except (FoundationError, KeyError, TypeError, ValueError, AttributeError) as exc:
            errors.append({'gate': 'F01-F10', 'severity': 'error', 'detail': str(exc)})
            coverage = {}
        return {'schema_version': 1, 'passed': not errors, 'errors': errors, 'warnings': warnings,
                'coverage': coverage, 'profile': release_profile(errors, coverage, bundle.get('semantic_audit')),
                'gate_notes': {'F11': 'deterministic rebuild checked by build fingerprint and end-to-end tests',
                               'F12': 'isolated module; protected production hashes captured by orchestration'}}
