import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from sbtc.Scripts.Retrieval.taxonomy.cli import main as cli_main
from sbtc.Scripts.Retrieval.taxonomy.io import sha_file
from sbtc.Scripts.Retrieval.tests.test_taxonomy_who import XML


def main(args):
    with contextlib.redirect_stdout(io.StringIO()):
        return cli_main(args)


class CLITests(unittest.TestCase):
    def test_build_validate_resume_and_block_unreviewed_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xml = root / 'input.xml'
            xml.write_text(XML)
            config = root / 'sources.json'
            config.write_text(json.dumps({'schema_version': 1, 'sources': [{
                'source_id': 'fixture', 'system': 'WHO_ICD10', 'declared_version': 'fixture',
                'format': 'claml', 'authority': 'synthetic', 'local_path': str(xml),
                'rights': {'status': 'test_only'}}]}))
            run = root / 'runs/run'
            common = ['--run-dir', str(run)]
            self.assertEqual(0, main(['fetch', '--sources', str(config), '--source-root', str(root / 'sources'), *common]))
            self.assertEqual(0, main(['build', *common]))
            sha = sha_file(run / 'taxonomy.jsonl')
            self.assertEqual(0, main(['build', *common]))
            self.assertEqual(sha, sha_file(run / 'taxonomy.jsonl'))
            self.assertEqual(0, main(['validate', *common]))
            self.assertEqual(4, main(['freeze', '--release-id', 'no-gold', *common]))
            self.assertFalse((root / 'releases/no-gold/release_manifest.json').exists())
            (run / 'taxonomy.jsonl').write_text('tampered')
            self.assertEqual(5, main(['build', *common]))

    def test_missing_config_is_clean_error(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(2, main(['fetch', '--sources', t + '/missing', '--run-dir', t + '/run'] ))

    def test_fresh_builds_have_identical_data_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input.xml').write_text(XML)
            config = root / 'source.json'
            config.write_text(json.dumps({'schema_version': 1, 'sources': [{
                'source_id': 'fixture', 'system': 'WHO_ICD10', 'declared_version': 'fixture',
                'format': 'claml', 'local_path': str(root / 'input.xml')}]}))
            runs = [root / 'first', root / 'second']
            for run in runs:
                self.assertEqual(0, main(['fetch', '--sources', str(config), '--source-root', str(root / 'store'), '--run-dir', str(run)]))
                self.assertEqual(0, main(['build', '--run-dir', str(run)]))
            for p in runs[0].glob('*.jsonl'):
                self.assertEqual(p.read_bytes(), (runs[1] / p.name).read_bytes(), p.name)
