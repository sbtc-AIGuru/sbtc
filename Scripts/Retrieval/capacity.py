"""Estimate capacity from measured artifacts; never treat this as a guarantee."""
import json
import shutil
import sqlite3
from pathlib import Path


def tree_bytes(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.exists() else 0


def estimate(root: Path, *, expected_documents: int, expected_chunks: int):
    manifest=json.loads((root/'manifest.json').read_text())
    counts=manifest['counts']
    if not manifest.get('prepared') or len(manifest.get('indexes',{}))!=6:
        raise ValueError('Capacity estimate requires a complete measured six-index snapshot')
    if min(expected_documents,expected_chunks,counts['records'],counts['chunks'])<=0:
        raise ValueError('Capacity sample/target counts must be positive')
    factor=max(expected_documents/counts['records'],expected_chunks/counts['chunks'])
    staging=tree_bytes(root/'prepared');indexes=tree_bytes(root/'indexes')
    registry=(root/'metadata.sqlite').stat().st_size
    with sqlite3.connect(f'file:{root / "metadata.sqlite"}?mode=ro',uri=True) as db:
        # The test registry already holds the entire chosen corpus whitelist.
        fixed_whitelist=db.execute("SELECT coalesce(sum(pgsize),0) FROM dbstat WHERE name='corpus'").fetchone()[0]
    # Conservative estimate: target staging+registry and twice index bytes for merge/build scratch.
    required=int(1.3*(fixed_whitelist+factor*(staging+registry-fixed_whitelist+2*indexes)))
    free=shutil.disk_usage(root).free
    return {'sample':counts,'expected_documents':expected_documents,'expected_chunks':expected_chunks,'scale_factor':factor,
            'measured_bytes':{'staging':staging,'indexes':indexes,'registry':registry,'fixed_whitelist':fixed_whitelist},
            'estimated_additional_free_bytes_required':required,'free_bytes':free,'disk_gate_passed':free>=required,
            'assumptions':['Target token/language distribution resembles test20k; use larger pilot if different.',
                           '30% headroom plus one extra full index for merge scratch; source data already on disk.',
                           'Single JVM heap defaults to 2 GiB; tokenizer/Python/native memory is additional.'],
            'production_ready':False,'reason':'Disk estimate alone cannot certify semantic coverage, translation resources, or RAM.'}
