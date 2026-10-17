"""Audit against independently authored cases; never generates expected answers."""
from __future__ import annotations

import math
import platform
import os
import resource
import statistics
import time
import tracemalloc
from collections import Counter, defaultdict
from pathlib import Path

from .lexicon import LexiconReader
from .models import FoundationError
from .normalize import Normalizer


def wilson(success, total):
    if not total:
        return None
    z = 1.96
    p = success / total
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [max(0, center - margin), min(1, center + margin)]


def metric(success, total):
    return {'success': success, 'support': total, 'value': success / total if total else None,
            'wilson_95': wilson(success, total)}


def memory_measurement():
    lifetime = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    lifetime_mb = lifetime / (1024 * 1024 if platform.system() == 'Darwin' else 1024)
    try:
        fields = {line.split(':', 1)[0]: line.split(':', 1)[1].strip()
                  for line in Path('/proc/self/status').read_text().splitlines() if ':' in line}
        peak, unit = fields['VmHWM'].split()
        current, current_unit = fields['VmRSS'].split()
        if unit != 'kB' or current_unit != 'kB':
            raise ValueError('Unknown /proc RSS units')
        return {'process_peak_rss_mb': int(peak) / 1024, 'current_rss_mb': int(current) / 1024,
                'rss_measurement_source': '/proc/self/status:VmHWM', 'rusage_lifetime_peak_mb': lifetime_mb}
    except (OSError, KeyError, ValueError):
        # Keep the unscoped lifetime value for diagnosis; do not claim the RAM gate passed.
        return {'process_peak_rss_mb': None, 'current_rss_mb': None,
                'rss_measurement_source': 'unavailable', 'rusage_lifetime_peak_mb': lifetime_mb}


def semantic_audit(bundle, cases, gold_manifest):
    normalizer = Normalizer()
    reader = LexiconReader(bundle['lexicon.verified'], bundle['ambiguity_groups'], normalizer)
    source = {x['source_node_id']: x for x in bundle['source_nodes']}
    entries = {x['entry_id']: x for x in bundle['lexicon.verified']}
    ids = set()
    details, breakdown = [], defaultdict(lambda: [0, 0])
    resolved_correct = resolved_total = official_correct = official_total = 0
    complete_contract = True
    sense_hits = sense_total = kind_correct = kind_total = 0
    for case in cases:
        if (not isinstance(case.get('id'), str) or case['id'] in ids or case.get('language') not in {'vi', 'en', 'zh'}
                or not isinstance(case.get('text'), str) or not isinstance(case.get('expected'), dict)
                or not case.get('evidence_refs')):
            raise FoundationError('Gold cases require unique IDs, language, text, independent expectations and evidence', 4)
        ids.add(case['id'])
        expected = case['expected']
        result = reader.lookup(case['text'], case['language'])
        primary = [m for m in result['mentions'] if m['independent_evidence']]
        actual_kinds = sorted({x['kind'] for x in primary})
        actual_codes = sorted({source[l['target_node_id']]['code'] for m in primary for l in m['links']})
        actual_targets = []
        for mention in primary:
            for link in mention['links']:
                node = source[link['target_node_id']]
                target = {k: node.get(k) for k in ('system', 'edition_id', 'level', 'code')}
                target.update(relation=link['relation'], usage=link['usage'])
                if target not in actual_targets:
                    actual_targets.append(target)
        if 'status' in expected:
            checks = [result['status'] == expected['status']]
        elif expected.get('status_in'):
            checks = [result['status'] in expected['status_in']]
            complete_contract = False  # Predicate safety tests are development, not exact semantic gold.
        else:
            raise FoundationError('Expected status or status_in is required', 4)
        if expected.get('forbid_topic'):
            checks.append(not any(m['status'] == 'resolved_candidate' for m in result['mentions']))
        if 'kinds' in expected:
            checks.append(actual_kinds == sorted(expected['kinds']))
            kind_total += 1
            kind_correct += checks[-1]
        if 'target_codes' in expected:
            checks.append(actual_codes == sorted(expected['target_codes']))
        if 'targets' in expected:
            typed = expected['targets']
            if not isinstance(typed, list) or any(set(t) != {'system', 'edition_id', 'level', 'code', 'relation', 'usage'} for t in typed):
                raise FoundationError('Holdout targets require full system/edition/level/code/relation/usage', 4)
            checks.append(all(t in actual_targets for t in typed) and all(t in typed for t in actual_targets))
            sense_total += len(typed)
            sense_hits += sum(t in actual_targets for t in typed)
        else:
            complete_contract = False
        if 'kinds' not in expected:
            complete_contract = False
        passed = all(checks)
        for axis in ('language', 'category'):
            key = axis + ':' + case.get(axis, 'unclassified')
            breakdown[key][0] += passed
            breakdown[key][1] += 1
        if result['status'] == 'resolved_candidate':
            resolved_total += 1
            resolved_correct += passed
        if case.get('category') == 'official_mapping' and (expected.get('targets') or expected.get('target_codes')):
            official_total += 1
            official_correct += passed
        details.append({'id': case['id'], 'passed': passed, 'expected': expected,
                        'actual': {'status': result['status'], 'kinds': actual_kinds, 'target_codes': actual_codes,
                                   'targets': actual_targets},
                        'supported_senses': sorted({entries[x['entry_id']]['sense_id'] for x in result['mentions']})})
    supported_cases = [c for c in cases if c['expected'].get('status') not in {None, 'no_match'}]
    supported_hits = sum(d['actual']['status'] != 'no_match' for c, d in zip(cases, details)
                         if c['expected'].get('status') not in {None, 'no_match'})
    ambiguous_cases = [d for d in details if d['expected'].get('status') == 'ambiguous_candidates']
    return {'schema_version': 1, 'passed': bool(cases) and all(x['passed'] for x in details),
            'cases': len(cases), 'language_counts': dict(Counter(x['language'] for x in cases)),
            'gold_approved': bool(gold_manifest.get('approved_by')) and gold_manifest.get('expected_origin') == 'independent_source_review',
            'holdout': gold_manifest.get('split') == 'holdout',
            'gold_contract_complete': complete_contract,
            'official_mapping_precision': official_correct / official_total if official_total else 0,
            'resolved_precision': resolved_correct / resolved_total if resolved_total else 0,
            'metrics': {'official_mapping': metric(official_correct, official_total),
                        'resolved': metric(resolved_correct, resolved_total),
                        'supported_case_recall': metric(supported_hits, len(supported_cases)),
                        'supported_sense_recall': metric(sense_hits, sense_total),
                        'kind_accuracy': metric(kind_correct, kind_total),
                        'ambiguity_preservation': metric(sum(d['passed'] for d in ambiguous_cases), len(ambiguous_cases)),
                        'abstain_rate': metric(sum(d['actual']['status'] in {'no_match', 'ambiguous_candidates'} for d in details), len(cases))},
            'breakdown': {k: metric(*value) for k, value in sorted(breakdown.items())},
            'details': details, 'limitations': ['Source-fixture correctness is not corpus recall or retrieval F2.',
                                                'No holdout approval or missing support prevents release.']}


def performance_audit(bundle, cases):
    normalizer = Normalizer()
    reader = LexiconReader(bundle['lexicon.verified'], bundle['ambiguity_groups'], normalizer)
    queries = [(x['text'], x['language']) for x in cases if len(x['text']) <= 256]
    if not queries:
        raise FoundationError('At least one independently specified short query required for performance audit', 4)
    for text, language in queries:
        reader.lookup(text, language)
    timings = []
    memory_samples = []
    tracemalloc.start()
    start_memory = tracemalloc.get_traced_memory()[0]
    for index in range(10000):
        text, language = queries[index % len(queries)]
        started = time.perf_counter_ns()
        reader.lookup(text, language)
        # Do not accumulate responses; record timings only outside measured leak samples.
        if index < 1000:
            timings.append((time.perf_counter_ns() - started) / 1e6)
        if (index + 1) % 1000 == 0:
            current, peak = tracemalloc.get_traced_memory()
            memory_samples.append({'iteration': index + 1, 'traced_current_bytes': current,
                                   'traced_peak_bytes': peak})
    end_memory, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # Throughput/timings without tracemalloc overhead, measured separately.
    warm = []
    started = time.perf_counter()
    for index in range(10000):
        text, language = queries[index % len(queries)]
        one = time.perf_counter_ns()
        reader.lookup(text, language)
        warm.append((time.perf_counter_ns() - one) / 1e6)
    elapsed = time.perf_counter() - started
    p95 = sorted(warm)[int(len(warm) * .95)]
    memory = memory_measurement()
    peak_mb = memory['process_peak_rss_mb']
    growth = end_memory - start_memory
    return {'queries': len(queries), 'iterations': 10000, 'warm': True,
            'p95_ms': p95, 'median_ms': statistics.median(warm), 'throughput_qps': 10000 / elapsed,
            **memory, 'traced_peak_bytes': traced_peak, 'traced_growth_bytes': growth,
            'memory_samples': memory_samples,
            'memory_growth_check': 'bounded <=1MB (including 1000 timing samples)',
            'passed': p95 < 10 and 10000 / elapsed >= 500 and peak_mb is not None and peak_mb < 500 and growth < 1024 * 1024,
            'hardware': {'platform': platform.platform(), 'processor': platform.processor(),
                         'logical_cpus': os.cpu_count(), 'python': platform.python_version()},
            'dictionary_senses': len(bundle['lexicon.verified']), 'normalization_profile': normalizer.profile_id,
            'scope': 'isolated audit matcher short queries + runtime lexicon/ambiguity; parent tagging not measured'}
