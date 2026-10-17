from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .models import FoundationError, canonical_json


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def atomic_bytes(path: Path, data: bytes, *, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        if path.read_bytes() != data:
            raise FoundationError(f'Refusing to overwrite incompatible data: {path}', 5)
        return
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp, path)
        else:
            # link() gives atomic no-clobber publication if another process won.
            os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path: Path, value, *, replace=False):
    atomic_bytes(path, canonical_json(value) + b'\n', replace=replace)


def write_jsonl(path: Path, rows, *, key: str):
    values = sorted(rows, key=lambda row: row[key])
    data = b''.join(canonical_json(row) + b'\n' for row in values)
    atomic_bytes(path, data)


def read_jsonl(path: Path):
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            try:
                yield json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            except ValueError as exc:
                raise FoundationError(f'Invalid JSON {path}:{number}: {exc}', 4) from exc
