"""Configure Java before any Pyjnius imports; do not modify caller's cwd."""
from __future__ import annotations

import os
from pathlib import Path


def configure_java() -> None:
    if "JAVA_HOME" not in os.environ:
        candidates = sorted((Path(__file__).parent / ".runtime/jdk").glob("*/bin/java"))
        if not candidates:
            raise RuntimeError("Full Java 21 missing: set JAVA_HOME (jdk.incubator.vector required)")
        os.environ["JAVA_HOME"] = str(candidates[0].parent.parent)
    os.environ.setdefault("JAVA_TOOL_OPTIONS", "-Xmx2g")
    if not (Path(os.environ["JAVA_HOME"]) / "bin/java").exists():
        raise RuntimeError("JAVA_HOME does not contain bin/java")
    java_bin = str(Path(os.environ["JAVA_HOME"]) / "bin")
    if java_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = java_bin + os.pathsep + os.environ.get("PATH", "")
