import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from sbtc.Scripts.Retrieval.taxonomy.models import FoundationError, digest
from sbtc.Scripts.Retrieval.taxonomy.sources import SourceStore, safe_members


def archive(name, data=b'<ClaML/>'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr(name, data)
    return stream.getvalue()


class SourceTests(unittest.TestCase):
    def test_archive_rejects_traversal_and_resource_limit(self):
        for name in ('../escape', '/absolute', 'a/../../escape', 'a\\escape'):
            with self.assertRaises(FoundationError):
                safe_members(archive(name))
        with self.assertRaises(FoundationError):
            safe_members(archive('large', b'x' * 100), max_bytes=20)

    def test_snapshot_is_pinned_idempotent_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'input.zip'
            source.write_bytes(archive('icd.xml'))
            config = {'source_id': 'who-fixture', 'system': 'WHO_ICD10',
                      'declared_version': 'fixture', 'format': 'claml_zip',
                      'local_path': str(source), 'sha256': digest(source.read_bytes()),
                      'authority': 'synthetic', 'rights': {'status': 'test_only'}}
            store = SourceStore(root / 'sources')
            first = store.acquire(config)
            self.assertEqual(first, store.acquire(config))
            store.verify(first)
            Path(first['members'][0]['local_path']).write_bytes(b'tampered')
            with self.assertRaises(FoundationError):
                store.verify(first)

    def test_wrong_hash_and_unsafe_source_id_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'input'
            p.write_bytes(b'abc')
            config = {'source_id': 'x', 'declared_version': 'v', 'local_path': str(p),
                      'sha256': '0' * 64, 'format': 'native_json'}
            store = SourceStore(Path(tmp) / 'sources')
            with self.assertRaises(FoundationError):
                store.acquire(config)
            config['source_id'] = '../x'
            with self.assertRaises(FoundationError):
                store.acquire(config)
