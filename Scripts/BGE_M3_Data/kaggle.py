"""Package a private, self-contained Kaggle notebook without credentials or source data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .common import load_config, write_json
from .pipeline import default_holdouts


def notebook_document(code: dict[str, str], expected_size: int,
                      expected_sha256: str | None) -> dict[str, Any]:
    """Embed only an explicit code/holdout allowlist and use preinstalled packages."""
    setup = (
        "from pathlib import Path\nimport hashlib, json, os, subprocess, sys\n"
        'os.environ["HF_HOME"] = "/tmp/bge-m3-huggingface"\n'
        'os.environ["TOKENIZERS_PARALLELISM"] = "false"\n'
        'ROOT = Path("/kaggle/working/bge-m3-runtime")\n'
        'WORK = Path("/kaggle/working/bge_m3_data")\n'
        f"CODE = {code!r}\n"
        "for relative, content in CODE.items():\n"
        "    target = ROOT / relative\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text(content, encoding='utf-8')\n"
        "sys.path.insert(0, str(ROOT))\n"
        "from Scripts.BGE_M3_Data.models import preflight\n"
        "print(json.dumps(preflight(), indent=2))\n"
        f"candidates = [p for p in Path('/kaggle/input').rglob('merged.json') if p.stat().st_size == {expected_size}]\n"
        "if len(candidates) != 1:\n"
        "    raise RuntimeError(f'Expected one original merged.json, found {len(candidates)}')\n"
        "SOURCE = candidates[0]\n"
        "print('Source:', SOURCE, 'bytes:', SOURCE.stat().st_size)\n"
    )
    run = (
        "command = [sys.executable, '-m', 'Scripts.BGE_M3_Data.pipeline', 'all',\n"
        "           '--input', str(SOURCE), '--work', str(WORK),\n"
        "           '--config', str(ROOT / 'Scripts/BGE_M3_Data/config.json')]\n"
        + (f"command.extend(['--expected-sha256', {expected_sha256!r}])\n" if expected_sha256 else "")
        + "subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONUNBUFFERED='1'), check=True)\n"
        "report = json.loads((WORK / 'dataset/report.json').read_text())\n"
        "assert report['dataset_complete'], 'Partial or undersized dataset; inspect report'\n"
        "print(json.dumps(report, ensure_ascii=False, indent=2))\n"
        "print('Dataset archive:', WORK / 'bge_m3_dataset.zip')\n"
    )
    return {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                         "language_info": {"name": "python"}},
            "cells": [
                {"cell_type": "markdown", "id": "description", "metadata": {},
                 "source": "# BGE-M3 evidence-grounded data generation\n\n"
                 "Private resumable run: source checksum, balanced corpus, duplicate-group splits, "
                 "Qwen question generation and evidence verification, BGE dense + SQLite BM25 mining, "
                 "cross-encoder teacher scores, negative verification and FlagEmbedding exports. "
                 "Labels are synthetic silver. No package installation or CPU fallback is performed."},
                *[{"cell_type": "code", "id": identity, "metadata": {}, "execution_count": None,
                   "outputs": [], "source": content} for identity, content in (("setup", setup), ("pipeline", run))],
            ]}


def build_bundle(output: Path, config_path: Path, dataset: str, kernel: str,
                 expected_size: int, expected_sha256: str | None = None) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite an existing Kaggle bundle: {output}")
    if len(dataset.split("/")) != 2 or len(kernel.split("/")) != 2:
        raise ValueError("Kaggle identifiers must have owner/slug format")
    config = load_config(config_path)
    if any(config[f"{name}_revision"] == "main" for name in ("generator", "embedder", "reranker")):
        raise ValueError("Pin public model revisions before building a reproducible Kaggle run")
    source_root = Path(__file__).resolve().parent
    code = {f"Scripts/BGE_M3_Data/{path.name}": path.read_text(encoding="utf-8")
            for path in sorted(source_root.glob("*.py"))}
    code["Scripts/BGE_M3_Data/config.json"] = json.dumps(config, ensure_ascii=False, indent=2)
    for path in default_holdouts():
        code[f"BackEnd/tests/{path.name}"] = path.read_text(encoding="utf-8")
    output.mkdir(parents=True)
    metadata = {"id": kernel, "title": kernel.split("/", 1)[1].replace("-", " "),
                "code_file": "notebook.ipynb", "language": "python", "kernel_type": "notebook",
                "is_private": True, "enable_gpu": True, "enable_tpu": False,
                "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
                "dataset_sources": [dataset], "competition_sources": [], "kernel_sources": [], "model_sources": []}
    write_json(output / "kernel-metadata.json", metadata)
    write_json(output / "notebook.ipynb", notebook_document(code, expected_size, expected_sha256))
    report = {"kernel": kernel, "dataset": dataset, "expected_source_size": expected_size,
              "expected_source_sha256": expected_sha256,
              "code_sha256": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in code.items()},
              "models": {name: {"name": config[f"{name}_model"], "revision": config[f"{name}_revision"]}
                         for name in ("generator", "embedder", "reranker")}}
    write_json(output / "bundle-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--kernel", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256")
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.output, args.config, args.dataset, args.kernel,
                                  args.source.stat().st_size, args.source_sha256), indent=2))


if __name__ == "__main__":
    main()
