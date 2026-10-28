"""Package a CPU-only Kaggle check of the existing full ViBioMIR recovery snapshot."""

import json
from pathlib import Path

from Scripts.Kaggle.prepare_vibiomir_qdrant import CONFIG as BASE_CONFIG, ROOT, cell


OUTPUT = ROOT / "artifacts/vibiomir-qdrant-dense-20261025/recheck"
REF = "nhminh107/vibiomir-qdrant-snapshot-recheck-20261025"
SOURCE = "nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025/1"
NAME = "ViBioMIR_Qdrant_Snapshot_Recheck_CPU.ipynb"
CONFIG = {**BASE_CONFIG,
          "source_kernel": SOURCE,
          "collection": "vibiomir_qwen3_06b_1024_fp16_dense_recheck",
          "state_dir": "/tmp/vibiomir_qdrant_recheck_state",
          "output": "/kaggle/working/vibiomir_snapshot_recheck",
          "search_timeout_seconds": 300}


def prepare():
    folder = OUTPUT / "kernel"
    folder.mkdir(parents=True, exist_ok=True)
    names = ("read_vibiomir_outputs.py", "restore_vibiomir_qdrant.py",
             "vibiomir_qdrant_runtime.py", "check_vibiomir_snapshot.py")
    modules = {name: (ROOT / "Scripts/Kaggle" / name).read_text() for name in names}
    setup = """import importlib.util
import json
from pathlib import Path
import subprocess
import sys

packages = {'numpy': 'numpy', 'pyarrow': 'pyarrow', 'requests': 'requests', 'psutil': 'psutil'}
missing = [package for module, package in packages.items() if importlib.util.find_spec(module) is None]
if missing:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', *missing], check=True)
print('CPU-only snapshot check:', sys.version)
"""
    embed = "CONFIG = " + repr(CONFIG) + "\nMODULES = " + repr(modules) + "\n"
    embed += """runner = Path('/tmp/vibiomir_snapshot_check_runner')
runner.mkdir(parents=True, exist_ok=True)
output = Path(CONFIG['output'])
output.mkdir(parents=True, exist_ok=True)
for name, source in MODULES.items():
    compile(source, name, 'exec')
    (runner / name).write_text(source)
config_path = runner / 'config.json'
config_path.write_text(json.dumps(CONFIG, indent=2))
print(json.dumps(CONFIG, indent=2))
"""
    run = """command = [sys.executable, '-u', str(runner / 'check_vibiomir_snapshot.py'), '--config', str(config_path)]
with (output / 'recheck.log').open('w') as log:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in process.stdout:
        print(line, end='', flush=True)
        log.write(line)
        log.flush()
    returncode = process.wait()
report_path = output / 'recheck_report.json'
report = json.loads(report_path.read_text()) if report_path.exists() else {'passed': False, 'stage': 'startup'}
print('FINAL REPORT:', json.dumps({k: v for k, v in report.items() if k != 'queries'}, indent=2))
if returncode or not report.get('passed'):
    raise RuntimeError('Snapshot recheck failed; inspect recheck_report.json and qdrant.log')
"""
    notebook = {"nbformat": 4, "nbformat_minor": 5,
                "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                             "language_info": {"name": "python"},
                             "kaggle": {"isGpuEnabled": False, "isInternetEnabled": True}},
                "cells": [
                    cell("markdown", "# ViBioMIR snapshot: restore and query recheck\n\n"
                         "Attach only the dense snapshot notebook output version 1. This CPU notebook "
                         "verifies its SHA-256, restores 4,936,835 points and checks the existing HNSW, "
                         "FP16 vectors, source payloads and queries. No embedding, upsert or graph rebuild.\n\n"
                         "The original query exceeded Qdrant's default 60-second search deadline. "
                         "We test that default once and then explicitly set the server request timeout to 300 seconds. "
                         "This is a functional stored-vector test, not a semantic retrieval benchmark.\n"),
                    cell("code", setup),
                    cell("code", embed),
                    cell("markdown", "## Run the check\n\n"
                         "Scratch needs disk for the staged 18.82 GB snapshot and restored collection. "
                         "Output contains small reports and a hash-bound validation certificate. "
                         "The original recovery snapshot and original complete=false manifest remain unchanged.\n"),
                    cell("code", run),
                ]}
    for index, item in enumerate(notebook["cells"]):
        item["id"] = f"vibiomir-snapshot-check-{index:02d}"
    text = json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"
    (folder / NAME).write_text(text)
    (ROOT / "BackEnd/app/Database/Notebook" / NAME).write_text(text)
    metadata = {"id": REF, "title": "ViBioMIR Qdrant Snapshot Recheck 20261025", "code_file": NAME,
                "language": "python", "kernel_type": "notebook", "is_private": True,
                "enable_gpu": False, "enable_tpu": False, "enable_internet": True,
                "dataset_sources": [], "competition_sources": [], "kernel_sources": [SOURCE]}
    (folder / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(folder / NAME)
    return notebook


if __name__ == "__main__":
    prepare()
