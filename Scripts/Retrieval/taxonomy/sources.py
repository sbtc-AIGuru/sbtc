"""Bounded, immutable source acquisition. No executable source content is loaded."""
from __future__ import annotations

import io
import json
import re
import zipfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .io import atomic_bytes, sha_file, write_json
from .models import FoundationError, canonical_json, digest, edition_id

MAX_SOURCE_BYTES = 256 * 1024 * 1024


def safe_members(data: bytes, *, max_bytes=128 * 1024 * 1024) -> dict[str, bytes]:
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if len(z.infolist()) > 64 or sum(x.file_size for x in z.infolist()) > max_bytes:
                raise FoundationError('Archive resource limit exceeded', 3)
            for item in z.infolist():
                name = item.filename
                if ('\\' in name or PurePosixPath(name).is_absolute()
                        or '..' in PurePosixPath(name).parts or ':' in name):
                    raise FoundationError('Unsafe archive path', 3)
                if item.is_dir():
                    continue
                if name in result:
                    raise FoundationError('Duplicate archive member', 3)
                result[name] = z.read(item)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise FoundationError(f'Invalid archive: {exc}', 3) from exc
    if not result:
        raise FoundationError('Empty archive', 3)
    return result


class SourceAdapter(ABC):
    @abstractmethod
    def parse(self, snapshot: dict):
        """Yield source records; adapters retain unresolved source facts."""


class SourceStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def acquire(self, config: dict) -> dict:
        source_id = config.get('source_id', '')
        if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.-]*', source_id):
            raise FoundationError('Unsafe/missing source ID')
        if config.get('local_path'):
            path = Path(config['local_path'])
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise FoundationError('Local source exceeds resource limit', 3)
            data = path.read_bytes()
            transport = {'origin': 'local', 'local_input_path': str(path.resolve()),
                         'redirect_url': None, 'media_type': None}
        else:
            import requests
            url = config.get('download_url', '')
            if not url.startswith('https://'):
                raise FoundationError('HTTPS download URL required')
            data = None
            last_error = None
            for _ in range(2):
                try:
                    with requests.get(url, stream=True, timeout=(15, 60)) as response:
                        response.raise_for_status()
                        if not response.url.startswith('https://'):
                            raise FoundationError('Refusing non-HTTPS download redirect', 3)
                        body = bytearray()
                        for chunk in response.iter_content(1024 * 1024):
                            body.extend(chunk)
                            if len(body) > MAX_SOURCE_BYTES:
                                raise FoundationError('Download exceeds resource limit', 3)
                        data = bytes(body)
                        transport = {'origin': 'https', 'redirect_url': response.url,
                                     'media_type': response.headers.get('Content-Type')}
                    break
                except requests.RequestException as exc:
                    last_error = str(exc)
            if data is None:
                raise FoundationError(f'Download failed: {last_error}', 3)
        sha = digest(data)
        if config.get('sha256') and sha != config['sha256']:
            raise FoundationError('Source SHA256 mismatch', 3)
        folder = self.root / source_id / sha
        manifest = folder / 'snapshot.json'
        if manifest.exists():
            existing = json.loads(manifest.read_text())
            if {k: existing.get(k) for k in config if k != 'local_path'} != {k: v for k, v in config.items() if k != 'local_path'}:
                raise FoundationError('Snapshot config changed; use a new source ID', 5)
            self.verify(existing)
            return existing
        files = safe_members(data) if config['format'].endswith('_zip') else {'source': data}
        members = []
        for name, content in sorted(files.items()):
            # Use the content digest as the disk name, retain original member name separately.
            p = folder / 'members' / digest(content)
            atomic_bytes(p, content)
            members.append({'role': name, 'content_sha256': digest(content),
                            'bytes': len(content), 'local_path': str(p)})
        archive = folder / 'source.bin'
        atomic_bytes(archive, data)
        snapshot = {**config, **transport, 'schema_version': 1,
                    'config_sha256': digest(canonical_json(config)),
                    'content_sha256': sha, 'bytes': len(data), 'local_path': str(archive),
                    'members': members, 'edition_id': edition_id(config['declared_version'], members),
                    'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
        write_json(manifest, snapshot)
        return snapshot

    @staticmethod
    def verify(snapshot: dict):
        for row in [snapshot, *snapshot['members']]:
            p = Path(row['local_path'])
            if not p.is_file() or p.stat().st_size != row['bytes'] or sha_file(p) != row['content_sha256']:
                raise FoundationError(f'Source missing or hash changed: {p}', 3)
        if snapshot['edition_id'] != edition_id(snapshot['declared_version'], snapshot['members']):
            raise FoundationError('Edition/member identity mismatch', 3)


def source_ref(snapshot: dict, locator: str, member: dict | None = None) -> dict:
    return {'source_id': snapshot['source_id'], 'snapshot_sha256': snapshot['content_sha256'],
            'member_sha256': (member or snapshot['members'][0])['content_sha256'],
            'locator': locator}
