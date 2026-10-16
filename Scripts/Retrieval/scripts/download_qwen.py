"""Download minimal inference weights for Qwen2.5-1.5B-Instruct and generate SHA256 provenance manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from huggingface_hub import hf_hub_download

PROVENANCE = {
    "model_id": "Qwen/Qwen2.5-1.5B-Instruct",
    "revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
    "license": "apache-2.0",
    "parameters": 1_540_000_000,
    "release_date": "2024-09-18",
    "open_weights": True,
}

REPO_ID = "Qwen/Qwen2.5-1.5B-Instruct"
REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"

INFERENCE_FILES = [
    "model.safetensors",
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def download_qwen(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Qwen2.5-1.5B-Instruct files to {target_dir}...")
    manifest_files = {}

    t0 = time.time()
    for fname in INFERENCE_FILES:
        print(f"  Fetching {fname}...")
        downloaded = hf_hub_download(
            repo_id=REPO_ID,
            filename=fname,
            revision=REVISION,
            local_dir=str(target_dir),
        )
        local_path = Path(downloaded)
        fsize = local_path.stat().st_size
        fsha = sha_file(local_path)
        manifest_files[fname] = {
            "size_bytes": fsize,
            "sha256": fsha,
        }
        print(f"    Done {fname}: {fsize / 1e6:.1f} MB, sha256={fsha[:12]}...")

    manifest = {
        "provenance": PROVENANCE,
        "files": manifest_files,
        "download_duration_sec": round(time.time() - t0, 2),
    }

    manifest_path = target_dir / "manifest_qwen.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nManifest successfully written to {manifest_path}")
    print(f"Total download time: {time.time() - t0:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Download Qwen2.5-1.5B-Instruct inference bundle.")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("artifacts/models/Qwen2.5-1.5B-Instruct"),
        help="Target directory for downloaded weights",
    )
    args = parser.parse_args()
    download_qwen(args.target_dir)


if __name__ == "__main__":
    main()
