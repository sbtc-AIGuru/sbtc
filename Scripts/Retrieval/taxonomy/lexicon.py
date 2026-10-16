"""Sense-aware lexicon and audit matcher, separate from the BM25 Lexicon API."""
from __future__ import annotations

import unicodedata

from .models import FoundationError, canonical_json, digest, identifier, issue

KINDS = {'disease_or_condition', 'symptom_sign', 'diagnostic_test', 'drug_substance',
         'procedure', 'anatomy', 'biomarker', 'context_modifier', 'tcm_pattern', 'unknown'}
USAGES = {'topic_candidate', 'context_only', 'abstain'}


def apply_lexical_reviews(candidates, decisions):
    from .crosswalk import active_decisions
    active = active_decisions(decisions)
    output = []
    for row in candidates:
        decision = active.get(row['entry_id'])
        if not decision:
            output.append(row)
            continue
        row = {**row, 'verification': dict(row['verification'])}
        row['review_decision_ids'] = [decision['decision_id']]
        row['source_refs'] = _unique(row['source_refs'] + decision['source_refs'])
        if decision['decision'] == 'accept':
            if decision.get('kind') not in KINDS - {'unknown'} or decision.get('usage') not in USAGES:
                raise FoundationError('Accepted lexical review must declare kind and usage', 4)
            if row['verification']['extraction_status'] != 'source_verified' and decision.get('extraction_verified') is not True:
                raise FoundationError('Staged lexical extraction requires explicit source verification', 4)
            row.update(kind=decision['kind'], usage=decision['usage'])
            # Reviewing a direct source sense also reviews its self-link; unrelated
            # associations retain their own, possibly stricter, link policies.
            row['links'] = [{**link, 'usage': decision['usage'],
                             'review_decision_id': decision['decision_id']}
                            if link['target_node_id'] == row['sense_id'] and link['relation'] == 'exact_concept'
                            else link for link in row['links']]
            row['verification'] = {'extraction_status': 'source_verified', 'semantic_status': 'independently_reviewed', 'acceptance': 'accepted'}
        elif decision['decision'] == 'reject':
            row['verification']['acceptance'] = 'rejected'
        output.append(row)
    return output


def make_entry(term, language, sense_id, kind, usage, normalizer, *, source_refs,
               accepted=False, links=(), case_sensitive=False, lexical_relation='official_label'):
    if kind not in KINDS or usage not in USAGES or not source_refs or not term.strip():
        raise FoundationError('Invalid lexical sense')
    views = normalizer.views(term, language)
    source_verified = bool(accepted)
    accepted = source_verified and kind != 'unknown'
    return {'schema_version': 1, 'entry_id': identifier('lex', [language, term, sense_id, lexical_relation]),
            'sense_id': sense_id, 'language': language, 'term_raw': term,
            'term_normalized': views['normalized'], 'term_case_preserved': views['case_preserved'],
            'normalization_profile': normalizer.profile_id, 'kind': kind, 'lexical_relation': lexical_relation,
            'native_concept_ids': [sense_id], 'links': list(links), 'ambiguity_group_id': None,
            'matching_policy': {'case_policy': 'sensitive' if case_sensitive else 'insensitive',
                                'boundary_policy': 'cjk_phrase' if language == 'zh' else 'latin_token',
                                'context_rule_id': None},
            'usage': usage, 'source_refs': list(source_refs), 'review_decision_ids': [],
            'verification': {'extraction_status': 'source_verified' if source_verified else 'staged',
                             'semantic_status': 'direct_official_label' if accepted else 'unverified',
                             'acceptance': 'accepted' if accepted else 'quarantined'}}


def _unique(values):
    return [value for _, value in sorted({canonical_json(x): x for x in values}.items())]


def curate_senses(candidates, normalizer):
    by_id, problems = {}, []
    for row in sorted(candidates, key=lambda x: canonical_json(x)):
        row = {**row, 'verification': dict(row['verification'])}
        key = row['entry_id']
        if key in by_id:
            previous = by_id[key]
            if any(previous[field] != row[field] for field in ('kind', 'usage', 'matching_policy', 'verification')):
                previous['verification']['acceptance'] = 'quarantined'
                previous['verification']['semantic_status'] = 'conflict'
                problems.append(issue('same_sense_semantic_conflict', key,
                                      candidates=[previous, row], evidence=previous['source_refs'] + row['source_refs']))
            previous['source_refs'] = _unique(previous['source_refs'] + row['source_refs'])
            previous['links'] = _unique(previous['links'] + row['links'])
        else:
            by_id[key] = row
    surfaces = {}
    for row in by_id.values():
        surfaces.setdefault((row['language'], row['term_normalized']), []).append(row)
    groups = []
    for (language, surface), rows in sorted(surfaces.items()):
        sense_ids = {r['sense_id'] for r in rows}
        if len(sense_ids) > 1:
            group_id = identifier('ambiguity', [normalizer.profile_id, language, surface])
            senses = _unique([{'sense_id': r['sense_id'], 'entry_id': r['entry_id'],
                               'status': r['verification']['acceptance'],
                               'decision_refs': r['review_decision_ids']} for r in rows])
            groups.append({'ambiguity_group_id': group_id, 'language': language,
                           'normalization_profile': normalizer.profile_id,
                           'term_normalized': surface, 'senses': senses, 'status': 'unresolved'})
            for row in rows:
                row['ambiguity_group_id'] = group_id
        for row in rows:
            if row['verification']['acceptance'] != 'accepted':
                problems.append(issue('lexical_sense_requires_review', row['entry_id'],
                                      candidates=[row], evidence=row['source_refs']))
    verified = [x for x in by_id.values() if x['verification']['acceptance'] == 'accepted']
    return sorted(verified, key=lambda x: x['entry_id']), groups, problems


def latin_character(char):
    return char == '_' or char.isdigit() or 'LATIN' in unicodedata.name(char, '')


def boundary_ok(text, start, end, policy):
    if policy in {'latin_token', 'code_literal'}:
        if (start and latin_character(text[start - 1])) or (end < len(text) and latin_character(text[end])):
            return False
        if policy == 'code_literal' and end + 1 < len(text) and text[end] == '.' and text[end + 1].isdigit():
            return False
        return True
    if policy == 'exact_surface':
        return start == 0 and end == len(text)
    return policy == 'cjk_phrase'


def group_evidence(mentions, views):
    """Retain subterms as dependent evidence, preserving equal-span homonyms."""
    lower_edges = [0]
    for character in views['case_preserved']:
        lower_edges.append(lower_edges[-1] + len(character.lower()))
    if lower_edges[-1] != len(views['normalized']):
        raise FoundationError('Cannot align normalized case views safely', 4)
    for mention in mentions:
        if mention['offset_space'] == 'normalized_case_preserved':
            start, end = lower_edges[mention['start']], lower_edges[mention['end']]
        else:
            start, end = mention['start'], mention['end']
        mention.update(evidence_start=start, evidence_end=end,
                       evidence_offset_space='normalized_lower')
    active = []
    for mention in sorted(mentions, key=lambda m: (m['evidence_start'], -m['evidence_end'], m['entry_id'])):
        start, end = mention['evidence_start'], mention['evidence_end']
        active = [outer for outer in active if outer['evidence_end'] > start]
        containers = [outer for outer in active if outer['evidence_start'] <= start
                      and outer['evidence_end'] >= end and
                      (outer['evidence_start'], outer['evidence_end']) != (start, end)]
        mention['independent_evidence'] = not containers
        mention['covered_by_entry_ids'] = sorted({m['entry_id'] for m in containers})
        if containers:
            mention['intrinsic_status'] = mention['status']
            mention['status'] = 'context_only'
        active.append(mention)


class LexiconReader:
    def __init__(self, entries, ambiguity_groups, normalizer):
        import ahocorasick
        self.normalizer = normalizer
        self.entries = {}
        self.groups = {x['ambiguity_group_id']: x for x in ambiguity_groups}
        self.automata = {}
        buckets = {}
        for row in entries:
            if (row['verification']['acceptance'] != 'accepted' or row['kind'] == 'unknown'
                    or row['verification']['semantic_status'] in {'unverified', 'conflict'}
                    or row['normalization_profile'] != normalizer.profile_id):
                raise FoundationError('Unaccepted/incompatible entry in runtime lexicon', 4)
            if row['entry_id'] in self.entries:
                raise FoundationError('Duplicate runtime lexical ID', 4)
            if row['ambiguity_group_id'] and row['ambiguity_group_id'] not in self.groups:
                raise FoundationError('Runtime requires complete ambiguity registry', 4)
            self.entries[row['entry_id']] = row
            sensitive = row['matching_policy']['case_policy'] == 'sensitive'
            view = 'case_preserved' if sensitive else 'normalized'
            term = row['term_case_preserved'] if sensitive else row['term_normalized']
            buckets.setdefault((row['language'], view), {}).setdefault(term, []).append(row['entry_id'])
        for key, words in buckets.items():
            automaton = ahocorasick.Automaton()
            for term, ids in words.items():
                automaton.add_word(term, (len(term), tuple(sorted(ids))))
            automaton.make_automaton()
            self.automata[key] = automaton

    def lookup(self, surface, language, context=None):
        views = self.normalizer.views(surface, language)
        mentions = []
        for view, text in views.items():
            automaton = self.automata.get((language, view))
            if automaton is None:
                continue
            for last, (length, entry_ids) in automaton.iter(text):
                start, end = last - length + 1, last + 1
                for entry_id in entry_ids:
                    entry = self.entries[entry_id]
                    policy = entry['matching_policy']
                    if not boundary_ok(text, start, end, policy['boundary_policy']):
                        continue
                    group = self.groups.get(entry['ambiguity_group_id'])
                    senses = group['senses'] if group else [{'sense_id': entry['sense_id'], 'status': 'accepted',
                                                            'entry_id': entry_id, 'decision_refs': []}]
                    ambiguous = len({s['sense_id'] for s in senses if s['status'] != 'rejected'}) > 1
                    usages = {entry['usage'], *(x['usage'] for x in entry['links'])}
                    ambiguous = ambiguous or 'abstain' in usages or bool(policy.get('context_rule_id'))
                    if ambiguous:
                        status = 'ambiguous_candidates'
                    elif 'context_only' in usages or entry['kind'] not in {'disease_or_condition', 'symptom_sign'}:
                        status = 'context_only'
                    else:
                        status = 'resolved_candidate'
                    mentions.append({'start': start, 'end': end, 'offset_space': f'normalized_{view}',
                                     'text_sha256': digest(text.encode()), 'entry_id': entry_id,
                                     'sense_candidates': senses, 'kind': entry['kind'], 'status': status,
                                     'links': entry['links'], 'usage': entry['usage']})
        group_evidence(mentions, views)
        statuses = {x['status'] for x in mentions if x['independent_evidence']}
        status = next((s for s in ('ambiguous_candidates', 'resolved_candidate', 'context_only') if s in statuses), 'no_match')
        return {'status': status, 'normalization_profile': self.normalizer.profile_id,
                'mentions': sorted(mentions, key=lambda x: (x['offset_space'], x['start'], x['end'], x['entry_id'])),
                'context': context, 'interpretation': 'topic_evidence_only_not_patient_diagnosis'}
