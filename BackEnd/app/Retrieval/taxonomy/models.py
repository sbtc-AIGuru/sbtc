from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


LEVELS = {'chapter', 'block', 'category', 'subcategory', 'other_group'}
SYSTEMS = {'WHO_ICD10', 'BYT_ICD10', 'NHC_ICD10_CLINICAL', 'NHSA_ICD10_INSURANCE'}
LANGUAGES = ('vi', 'en', 'zh')


class FoundationError(ValueError):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identifier(namespace: str, value) -> str:
    return namespace + ':' + digest(canonical_json(value))


def edition_id(version: str, members: list[dict]) -> str:
    if not isinstance(version, str) or not version.strip() or version.lower() == 'unknown':
        raise FoundationError('A declared source version is required')
    if not members:
        raise FoundationError('Source bundle is empty')
    normalized = []
    for item in members:
        role, sha = item.get('role'), item.get('content_sha256')
        if not isinstance(role, str) or not role or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise FoundationError('Invalid source role/SHA256')
        normalized.append({'role': role, 'content_sha256': sha})
    normalized.sort(key=lambda x: (x['role'], x['content_sha256']))
    if len({x['role'] for x in normalized}) != len(normalized):
        raise FoundationError('Duplicate source member role')
    return version + '@sha256:' + digest(canonical_json(normalized))


@dataclass(frozen=True)
class NodeKey:
    system: str
    edition_id: str
    level: str
    code: str

    def __post_init__(self):
        if self.system not in SYSTEMS or self.level not in LEVELS:
            raise FoundationError('Unknown taxonomy system/level')
        if not all(isinstance(x, str) and x.strip() for x in (self.edition_id, self.code)):
            raise FoundationError('Empty/non-string edition or code')

    @property
    def identifier(self) -> str:
        return identifier('icdnode', [self.system, self.edition_id, self.level, self.code])


def issue(reason: str, object_id: str, *, candidates=(), evidence=(), detail='') -> dict:
    key = [reason, object_id]
    return {'issue_id': identifier('issue', key), 'object_id': object_id,
            'reason': reason, 'candidates': list(candidates), 'evidence_refs': list(evidence),
            'detail': detail, 'status': 'open'}
