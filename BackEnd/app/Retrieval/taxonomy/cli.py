from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from .audit import semantic_audit
from .build import build, code_hashes, load_bundle, protected_hashes
from .io import read_jsonl, sha_file, write_json
from .models import FoundationError, canonical_json, digest
from .normalize import Normalizer
from .sources import SourceStore
from .validation import ReleaseValidator


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def verify_run(run_dir):
    state = read_json(run_dir / 'build_manifest.json')
    if state['code_hashes'] != code_hashes():
        raise FoundationError('Implementation changed since build; use a new run', 5)
    for name, descriptor in state['artifacts'].items():
        path = run_dir / name
        if not path.is_file() or sha_file(path) != descriptor['sha256']:
            raise FoundationError(f'Run artifact integrity failed: {name}', 5)
    if read_json(run_dir / 'protected-production-hashes.json') != protected_hashes():
        raise FoundationError('Protected production files differ from build snapshot', 4)
    return state


def fetch(args):
    config = read_json(args.sources)
    if config.get('schema_version') != 1 or not isinstance(config.get('sources'), list):
        raise FoundationError('Source config schema_version=1 and sources list required')
    source_ids = [x['source_id'] for x in config['sources']]
    if len(set(source_ids)) != len(source_ids):
        raise FoundationError('Duplicate configured source IDs')
    config_sha = digest(canonical_json(config))
    path = args.run_dir / 'source_manifest.json'
    if path.exists():
        manifest = read_json(path)
        if manifest['config_sha256'] != config_sha:
            raise FoundationError('Incompatible source config for existing run', 5)
        for source in manifest['sources']:
            SourceStore.verify(source)
        return {'sources': len(manifest['sources']), 'failures': manifest['failures'], 'resumed': True}
    sources, failures = [], []
    store = SourceStore(args.source_root)
    for original in config['sources']:
        source = dict(original)
        if args.cache_dir and not source.get('local_path'):
            cached = args.cache_dir / unquote(Path(urlparse(source['download_url']).path).name)
            if cached.is_file():
                source['local_path'] = str(cached)
        try:
            sources.append(store.acquire(source))
        except (FoundationError, OSError) as exc:
            failures.append({'source_id': original['source_id'], 'status': 'source_unavailable', 'error': str(exc)})
    if not sources:
        raise FoundationError(f'No sources acquired: {failures}', 3)
    write_json(path, {'schema_version': 1, 'config_sha256': config_sha, 'sources': sources, 'failures': failures})
    return {'sources': len(sources), 'failures': failures, 'resumed': False}


def validate(run_dir):
    state = verify_run(run_dir)
    bundle = load_bundle(run_dir)
    audit_path = run_dir / 'audit/semantic.json'
    if audit_path.exists():
        audit_manifest = read_json(run_dir / 'audit/audit_manifest.json')
        for name, expected in audit_manifest['files'].items():
            if sha_file(run_dir / name) != expected:
                raise FoundationError(f'Audit artifact changed: {name}', 4)
        audit = read_json(audit_path)
        if audit.get('build_fingerprint') != state['fingerprint']:
            raise FoundationError('Semantic audit belongs to a different build', 4)
        bundle['semantic_audit'] = audit
    return ReleaseValidator().validate(bundle, normalizer=Normalizer())


def audit(args):
    state = verify_run(args.run_dir)
    bundle = load_bundle(args.run_dir)
    cases = list(read_jsonl(args.gold))
    gold_manifest = read_json(args.gold_manifest)
    if gold_manifest.get('cases_sha256') != sha_file(args.gold):
        raise FoundationError('Gold manifest does not match cases SHA256', 4)
    result = semantic_audit(bundle, cases, gold_manifest)
    child = subprocess.run([sys.executable, '-m', 'BackEnd.app.Retrieval.taxonomy.performance',
                            str(args.run_dir), str(args.gold)], check=True, capture_output=True,
                           text=True, timeout=180)
    perf = json.loads(child.stdout)
    result.update(performance_passed=perf['passed'], build_fingerprint=state['fingerprint'],
                  gold_sha256=sha_file(args.gold), gold_manifest_sha256=sha_file(args.gold_manifest))
    write_json(args.run_dir / 'audit/performance.json', perf)
    write_json(args.run_dir / 'audit/semantic.json', result)
    write_json(args.run_dir / 'audit/gold-manifest.json', gold_manifest)
    write_json(args.run_dir / 'audit/audit_manifest.json', {
        'build_fingerprint': state['fingerprint'],
        'files': {name: sha_file(args.run_dir / name) for name in
                  ('audit/semantic.json', 'audit/performance.json', 'audit/gold-manifest.json')}})
    return {'semantic_passed': result['passed'], 'performance_passed': perf['passed'],
            'gold_approved': result['gold_approved'], 'holdout': result['holdout'], 'cases': len(cases)}


def freeze(args):
    if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.-]*', args.release_id):
        raise FoundationError('Unsafe release ID')
    state = verify_run(args.run_dir)
    report = validate(args.run_dir)
    if report['profile'] not in {'pilot_partial', 'core_ready'}:
        raise FoundationError(f'Release blocked: profile={report["profile"]}; independent approved semantic gate required', 4)
    # This command creates a local immutable bundle, not a public publication.
    # Unknown rights remain explicit and do not become an inferred blanket licence.
    sources = read_json(args.run_dir / 'source_manifest.json')['sources']
    destination = args.release_root / args.release_id
    if destination.exists():
        raise FoundationError('Immutable release destination already exists', 5)
    temporary = args.release_root / ('.' + args.release_id + '.tmp')
    if temporary.exists():
        raise FoundationError('Partial release found; inspect and choose a new release ID', 5)
    temporary.mkdir(parents=True)
    files = {}
    for name in state['artifacts']:
        original = args.run_dir / name
        target = temporary / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        sha = sha_file(target)
        if sha != state['artifacts'][name]['sha256']:
            raise FoundationError('Release copy hash mismatch', 5)
        files[name] = {'sha256': sha, 'bytes': target.stat().st_size,
                       'rows': sum(1 for _ in target.open(encoding='utf-8')) if name.endswith('.jsonl') else None}
    for name in ('audit/semantic.json', 'audit/performance.json', 'audit/audit_manifest.json', 'audit/gold-manifest.json', 'build_manifest.json'):
        target = temporary / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.run_dir / name, target)
        files[name] = {'sha256': sha_file(target), 'bytes': target.stat().st_size}
    write_json(temporary / 'release_manifest.json', {'schema_version': 1, 'release_id': args.release_id,
               'profile': report['profile'], 'build_fingerprint': state['fingerprint'], 'git_commit': None,
               'code_hashes': state['code_hashes'], 'normalization_profile': state['normalization_profile'],
               'editions': [x['edition_id'] for x in sources], 'artifacts': files, 'coverage': report['coverage'],
               'distribution': {'local_bundle': True,
                   'public_distribution_allowed': all(x.get('rights', {}).get('status') in
                       {'redistribution_permitted', 'public_domain'} for x in sources),
                   'source_rights': {x['source_id']: x.get('rights', {'status': 'unknown'}) for x in sources}}})
    temporary.rename(destination)
    return {'release': str(destination), 'profile': report['profile']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Isolated ICD taxonomy/lexicon foundation')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('fetch', 'build', 'validate', 'audit', 'freeze'):
        p = sub.add_parser(command)
        p.add_argument('--run-dir', type=Path, required=True)
        if command == 'fetch':
            p.add_argument('--sources', type=Path, required=True)
            p.add_argument('--source-root', type=Path, default=Path('artifacts/taxonomy/sources'))
            p.add_argument('--cache-dir', type=Path)
        elif command == 'build':
            p.add_argument('--decisions', type=Path)
        elif command == 'audit':
            p.add_argument('--gold', type=Path, required=True)
            p.add_argument('--gold-manifest', type=Path, required=True)
        elif command == 'freeze':
            p.add_argument('--release-id', required=True)
            p.add_argument('--release-root', type=Path, default=Path('artifacts/taxonomy/releases'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch':
            result = fetch(args)
            exit_code = 3 if result['failures'] else 0
        elif args.command == 'build':
            bundle = build(args.run_dir, decisions_path=args.decisions)
            result = {'taxonomy_nodes': len(bundle['taxonomy']), 'source_nodes': len(bundle['source_nodes']),
                      'verified_senses': len(bundle['lexicon.verified'])}
            exit_code = 0
        elif args.command == 'validate':
            result = validate(args.run_dir)
            write_json(args.run_dir / 'audit/validation-latest.json', result, replace=True)
            exit_code = 0 if result['passed'] else 4
        elif args.command == 'audit':
            result = audit(args)
            exit_code = 0 if result['semantic_passed'] and result['performance_passed'] else 4
        else:
            result = freeze(args)
            exit_code = 0
        print(json.dumps({'exit_code': exit_code, 'result': result}, ensure_ascii=False))
        return exit_code
    except (FoundationError, OSError, ValueError, KeyError, ImportError, subprocess.SubprocessError) as exc:
        exit_code = exc.code if isinstance(exc, FoundationError) else (2 if args.command == 'fetch' else 3)
        print(json.dumps({'exit_code': exit_code, 'error': str(exc)}, ensure_ascii=False))
        return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
