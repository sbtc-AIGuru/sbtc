"""BM25 Medical Multilingual Retrieval Component.

Theo đặc tả SPEC-bm25-medical-multilingual.md:
Lexical retrieval component tối ưu hóa điểm F2 Document và Chunk chuẩn BTC ViBioMIR
trên corpus đa ngữ (Việt - Anh - Trung).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Tự động phát hiện và thiết lập JAVA_HOME nếu chạy trong conda env có OpenJDK
if "JAVA_HOME" not in os.environ:
    candidate_jvm = Path(sys.prefix) / "lib" / "jvm"
    if candidate_jvm.exists():
        os.environ["JAVA_HOME"] = str(candidate_jvm)
        os.environ["PATH"] = f"{candidate_jvm}/bin:{os.environ.get('PATH', '')}"

# Import pyserini trước để cấu hình classpath JAR cho pyjnius
try:
    import pyserini  # noqa: F401
except ImportError:
    pass

__version__ = "0.1.0"
