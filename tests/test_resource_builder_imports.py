"""Resource preparation remains importable after removing the archive."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("entrypoint", ["script", "module"])
def test_resource_builder_imports_without_archive(tmp_path, entrypoint):
    repository = tmp_path / "sbtc"
    files = [
        "Scripts/build_expanded_base_resources.py",
        "BackEnd/__init__.py",
        "BackEnd/app/__init__.py",
        "BackEnd/app/Retrieval/__init__.py",
        "BackEnd/app/Retrieval/lexicon_data.py",
    ]
    for name in files:
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)

    script = repository / files[0]
    if entrypoint == "script":
        load = f"import runpy; builder = runpy.run_path({str(script)!r})"
    else:
        load = "import importlib; builder = vars(importlib.import_module('Scripts.build_expanded_base_resources'))"
    probe = load + "\n" + f"""
from pathlib import Path
from BackEnd.app.Retrieval import lexicon_data
assert Path(lexicon_data.__file__).resolve() == Path({str(repository / files[-1])!r})
for name in ('DISEASE_CONCEPTS', 'DRUG_CONCEPTS', 'TCM_CONCEPTS', 'COLLOQUIAL_CONCEPTS', 'LAB_CONCEPTS'):
    assert builder[name] is getattr(lexicon_data, name)
    assert builder[name]
assert builder['repo_root'] == Path({str(tmp_path)!r})
assert not Path({str(repository / 'Archive')!r}).exists()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(repository)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not (repository / "Resources").exists()
    assert not (tmp_path / "artifacts").exists()
