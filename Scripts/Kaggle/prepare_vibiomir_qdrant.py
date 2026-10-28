"""Package the CPU-only three-part ViBioMIR FP16 dense snapshot notebook."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/vibiomir-qdrant-dense-20261025"
NOTEBOOK_NAME = "ViBioMIR_Qwen3_Dense_FP16_HNSW_Snapshot_CPU.ipynb"
REF = "nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025"
SOURCES = [f"nhminh107/vibiomir-qwen3-06b-part{part}-t4x2-20261024" for part in (1, 2, 3)]
PINNED_SOURCES = [f"{ref}/{version}" for ref, version in zip(SOURCES, (1, 1, 3))]
CONFIG = {
    "input_root": "/kaggle/input", "expected_chunks": 4_936_835,
    "source_sha256": "a45123b3de7a9b048f83418515a3ec6b3dd09e1e4491dd361429b787659a3e7f",
    "profile_id": "5d92039674725126e3757ac85a2fe632ed301cc19eeab4db0ddc2e6df6519087",
    "dimension": 1024, "batch_size": 128,
    "collection": "vibiomir_qwen3_06b_1024_fp16_dense",
    "state_dir": "/tmp/vibiomir_qdrant_state", "binary": "/tmp/vibiomir_qdrant_bin/qdrant",
    "port": 6333, "qdrant_url": "http://127.0.0.1:6333",
    "hnsw_m": 32, "ef_construction": 100, "indexing_threshold_kb": 10_000,
    "index_timeout_seconds": 18_000, "index_poll_seconds": 15,
    "ingest_stop_seconds": 14_400,
    "output": "/kaggle/working/vibiomir_qdrant_dense_export",
    "output_budget_root": "/kaggle/working", "output_limit_bytes": 18 * 1024**3,
    "resume_from": None,
    "input_notebooks": [{"ref": ref, "version": version} for ref, version in zip(SOURCES, (1, 1, 3))],
}

README = """# Restore ViBioMIR Qwen3 dense FP16

Keep the entire export together. `snapshot_manifest.json` distinguishes complete
exports from recovery-only exports. Kaggle COMPLETE alone is not sufficient.

## Restore

1. Use a disk-backed machine with Docker, curl and Python (numpy, requests).
2. Run `python restore_qdrant_snapshot.py --folder .`. The helper checks SHA-256,
   unpacks .gz if needed, and prints Docker/curl commands. Review/run those commands
   using a new empty storage directory. Use the exact Qdrant version in the manifest.
3. Run `python restore_qdrant_snapshot.py --folder . --verify-url http://127.0.0.1:6333`.
   This verifies exact count, FP16 schema, source payload/vector samples and lookups.

Allow disk for the compressed export, unpacked snapshot, restored collection and
temporary restore files. The snapshot is single-node and excludes collection aliases.

## Query

```python
from qdrant_db import QdrantDenseClient
client = QdrantDenseClient.from_manifest('snapshot_manifest.json')
hits = client.search_dense(query_vector, top_k=10, hnsw_ef=128)
chunk = client.lookup_chunk('original-chunk-id')
page = client.scroll_document(123, limit=100)
# To continue: client.scroll_document(123, offset=page['next_page_offset'])
client.close()
```

Query vectors must use Qwen/Qwen3-Embedding-0.6B revision
97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3, 1024 dimensions, left padding,
last-token pooling and FP32 L2 normalization. For question retrieval, use the
Qwen retrieval prompt `Instruct: {task_description}\nQuery: {query}` with a fixed
task description suitable for biomedical retrieval. Document embeddings have no
instruction. Refer to encoder_profile.json for the exact document encoder profile.
The notebook does not download model weights. dense_query_example.json uses an
existing vector only as a restore smoke test; it is not a new encoded question.

Payload is the complete decoded source payload_json, including content and
_embedding provenance. doc_id identifies the source document, not a parent passage.
No parent_id mapping or complete parent/document text is created by this notebook.
No sparse vector or full-text scoring index is created.

## Resume

Attach the same three input outputs and the previous complete recovery export.
Set CONFIG['resume_from'] to its export folder; use fresh state/output folders.
Only the checkpoint embedded in that snapshot's manifest is trusted. Stable UUIDs
allow replay of the last uncommitted batch without duplicate points. Resume rejects
different source/profile, file receipts, collection, FP16 schema and HNSW settings.

After ingest, a pre-index snapshot is kept in runtime scratch to avoid keeping two
full snapshots inside the limited Output quota. It is NOT durable across sessions.
Controlled stop/failure attempts to export a recovery snapshot with its matching
checkpoint. A sudden runtime kill can lose state since the last saved export.
Do not treat an ingestion checkpoint JSON alone as a database backup.

Pipeline states and errors are in pipeline_status.json. A complete export requires
exactly 4,936,835 points, successful indexing and a real snapshot restore check.
FP32 source embeddings are preserved in the original input outputs; Qdrant stores
FP16 and the verifier tolerates only expected rounding error on sampled vectors.
"""


def cell(kind, source):
    result = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def prepare():
    folder = OUTPUT / "kernel"
    folder.mkdir(parents=True, exist_ok=True)
    source_dir = ROOT / "Scripts/Kaggle"
    modules = {name: (source_dir / name).read_text() for name in (
        "read_vibiomir_outputs.py", "restore_vibiomir_qdrant.py", "vibiomir_qdrant_runtime.py")}
    setup = """import importlib.util
import json
from pathlib import Path
import subprocess
import sys

required = {'numpy': 'numpy', 'pyarrow': 'pyarrow==20.0.0', 'requests': 'requests', 'psutil': 'psutil'}
missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
if missing:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', *missing], check=True)
print('CPU runtime:', sys.version)
"""
    configure = "CONFIG = " + repr(CONFIG) + "\n\n" + """# For resume only: attach a matching recovery export and set resume_from.
runner_dir = Path('/tmp/vibiomir_qdrant_runner')
runner_dir.mkdir(parents=True, exist_ok=True)
output = Path(CONFIG['output'])
output.mkdir(parents=True, exist_ok=True)
config_path = runner_dir / 'config.json'
config_path.write_text(json.dumps(CONFIG, indent=2))
print(json.dumps(CONFIG, indent=2))
"""
    embedded = "MODULES = " + repr(modules) + "\n"
    embedded += "RESTORE_README = " + repr(README) + "\n"
    embedded += """for name, source in MODULES.items():
    compile(source, name, 'exec')
    (runner_dir / name).write_text(source, encoding='utf-8')
(output / 'restore_qdrant_snapshot.py').write_text(MODULES['restore_vibiomir_qdrant.py'], encoding='utf-8')
(output / 'qdrant_db.py').write_text(MODULES['restore_vibiomir_qdrant.py'], encoding='utf-8')
(output / 'README_RESTORE.md').write_text(RESTORE_README, encoding='utf-8')
(output / 'run_config.json').write_text(json.dumps(CONFIG, indent=2))
(output / 'vibiomir_qdrant_runtime.py').write_text(MODULES['vibiomir_qdrant_runtime.py'], encoding='utf-8')
(output / 'read_vibiomir_outputs.py').write_text(MODULES['read_vibiomir_outputs.py'], encoding='utf-8')
(output / 'restore_vibiomir_qdrant.py').write_text(MODULES['restore_vibiomir_qdrant.py'], encoding='utf-8')
"""
    run = """command = [sys.executable, '-u', str(runner_dir / 'vibiomir_qdrant_runtime.py'), '--config', str(config_path)]
with (output / 'pipeline.log').open('a', encoding='utf-8') as log:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in process.stdout:
        print(line, end='', flush=True)
        log.write(line)
        log.flush()
    returncode = process.wait()
status_path = output / 'pipeline_status.json'
status = json.loads(status_path.read_text()) if status_path.exists() else {'success': False, 'stage': 'startup'}
print('PIPELINE STATUS:', json.dumps(status, indent=2))
if returncode or not status.get('success'):
    # End normally so Kaggle can preserve a recovery export. COMPLETE is not success.
    print('RECOVERY / FAILURE: inspect pipeline_status.json and snapshot_manifest.json.')
else:
    manifest = json.loads((output / 'snapshot_manifest.json').read_text())
    assert manifest['complete'] and manifest['restore_verification']['verified']
    print('SUCCESS:', manifest['points'], 'points; snapshot:', manifest['snapshot_file'])
"""
    notebook = {"nbformat": 4, "nbformat_minor": 5,
                "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                             "language_info": {"name": "python"},
                             "kaggle": {"isGpuEnabled": False, "isInternetEnabled": True}},
                "cells": [
        cell("markdown", "# ViBioMIR Qwen3 → Qdrant dense FP16 HNSW snapshot\n\n"
             "CPU-only; reads all three completed embedding outputs. Expected: **4,936,835 points**. "
             "Dense `qwen3_dense`, 1024 dimensions, Cosine, FP16, HNSW m=32/ef_construct=100. "
             "Preserves the complete source payload and provenance. No model inference is needed.\n\n"
             "Use **Internet On**, **Accelerator None**, then Save & Run All. All three notebook outputs "
             "must be attached once. Missing/incomplete inputs stop preflight.\n"),
        cell("code", setup),
        cell("markdown", "## Configuration\n\n"
             "State/snapshot scratch must use disk. Output budget is 18 GiB; actual snapshot size is "
             "checked before publishing a complete manifest. FP16 vectors alone use about 9.42 GiB. "
             "The budget also needs text, metadata and HNSW; fit is not guaranteed.\n"),
        cell("code", configure),
        cell("markdown", "## Standalone reader, runner and restore helper\n\n"
             "Input checksums, source/profile/coverage and per-row metadata are checked. "
             "Progress commits only after successful upsert. On completion the snapshot is restored "
             "into a separate temporary collection and count/schema/vector/payload/search are checked.\n"),
        cell("code", embedded),
        cell("markdown", "## Run and preserve recovery output\n\n"
             "Stages: validate inputs → resource checks → real small FP16/snapshot smoke test → "
             "stream ingest → build HNSW → verify → snapshot/restore → export. "
             "A controlled failure attempts recovery export and is recorded as success=false. "
             "Kaggle COMPLETE alone does not mean the full collection succeeded.\n"),
        cell("code", run),
        cell("markdown", "## Restore and search\n\n"
             "Keep all of `vibiomir_qdrant_dense_export`. Follow README_RESTORE.md; use Qdrant 1.19.2 "
             "and new empty storage. The snapshot contains dense vectors, graph, text and metadata. "
             "`doc_id` maps to the source document; parent-passage mappings are not present in these inputs. "
             "New questions require a compatible Qwen3 query encoder.\n")
    ]}
    for index, item in enumerate(notebook["cells"]):
        item["id"] = f"vibiomir-dense-{index:02d}"
    text = json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"
    (folder / NOTEBOOK_NAME).write_text(text)
    (ROOT / "BackEnd/app/Database/Notebook" / NOTEBOOK_NAME).write_text(text)
    metadata = {"id": REF, "title": "ViBioMIR Qwen3 Dense FP16 HNSW 20261025", "code_file": NOTEBOOK_NAME,
                "language": "python", "kernel_type": "notebook", "is_private": True,
                "enable_gpu": False, "enable_tpu": False, "enable_internet": True,
                "dataset_sources": [], "competition_sources": [], "kernel_sources": PINNED_SOURCES}
    (folder / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(folder / NOTEBOOK_NAME)
    return notebook


if __name__ == "__main__":
    prepare()
