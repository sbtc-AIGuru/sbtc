"""Prepare the public Parquet source and Chromium before running the crawler on Kaggle."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen


SOURCE_URL = (
    "https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/"
    "resolve/main/links_corpus.parquet"
)
SOURCE_SHA256 = "dee1153f5b9d9010dea18e1b7724b4915ff847b711d036bec8b933486802a971"
SOURCE_PATH = Path("data/links_corpus.parquet")
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def file_sha256(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_source() -> None:
    """Download the exact Parquet version used for local range validation."""
    if SOURCE_PATH.exists():
        if file_sha256(SOURCE_PATH) != SOURCE_SHA256:
            raise ValueError(f"Unexpected Parquet checksum: {SOURCE_PATH}")
        return

    SOURCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    partial = SOURCE_PATH.with_suffix(".parquet.part")
    request = Request(SOURCE_URL, headers={"User-Agent": "ViBioMIR-crawler/1.0"})
    print("[Source] Downloading links_corpus.parquet", flush=True)
    with urlopen(request, timeout=120) as response, partial.open("wb") as handle:
        while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
            handle.write(chunk)
    if file_sha256(partial) != SOURCE_SHA256:
        raise ValueError("Downloaded Parquet checksum does not match the local source")
    partial.rename(SOURCE_PATH)


def main() -> None:
    ensure_source()
    print("[Browser] Ensuring Chromium and its system libraries are installed", flush=True)
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
        check=True,
    )

    from crawl import main as crawl_main

    crawl_main()


if __name__ == "__main__":
    main()
