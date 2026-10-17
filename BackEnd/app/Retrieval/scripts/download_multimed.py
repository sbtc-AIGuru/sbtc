"""Download minimal inference weights for MultiMed-ST (EMNLP 2025) and generate SHA256 manifests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

# Competition provenance declaration
PROVENANCE = {
    "model_id": "leduckhai/MultiMed-ST",
    "revision": "fb15edd1dfc68810a7d0c75e6cfc73c3e5ed01c1",
    "license": "mit",
    "parameters": 418_000_000,
    "release_date": "2025-02-23",
    "open_weights": True,
}

REPO_ID = "leduckhai/MultiMed-ST"
REVISION = "fb15edd1dfc68810a7d0c75e6cfc73c3e5ed01c1"

INFERENCE_FILES = [
    "model.safetensors",
    "config.json",
    "generation_config.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "vocab.json",
    "special_tokens_map.json",
    "added_tokens.json",
]

DIRECTIONS = {
    "en": {
        "subfolder": "m2m100_418M-finetuned-vi-to-en/checkpoint",
        "dir_name": "vi-to-en",
        "manifest_name": "manifest_vi_en.json",
    },
    "zh": {
        "subfolder": "m2m100_418M-finetuned-vi-to-zh/checkpoint",
        "dir_name": "vi-to-zh",
        "manifest_name": "manifest_vi_zh.json",
    },
}


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def download_and_manifest(target_root: Path, directions: list[str]) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    for lang in directions:
        info = DIRECTIONS[lang]
        dest_dir = (target_root / info["dir_name"]).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n==========================================")
        print(f"Downloading MultiMed-ST VI -> {lang.upper()} into {dest_dir}...")
        print(f"==========================================")

        file_manifest = {}
        for fname in INFERENCE_FILES:
            target_file = dest_dir / fname
            if target_file.exists():
                print(f"  [Cached] {fname} ({target_file.stat().st_size:,} bytes)")
            else:
                print(f"  [Downloading] {fname} from {info['subfolder']}...")
                downloaded_path = hf_hub_download(
                    repo_id=REPO_ID,
                    subfolder=info["subfolder"],
                    filename=fname,
                    revision=REVISION,
                )
                # Copy to dest_dir
                shutil.copy2(downloaded_path, target_file)
                print(f"  -> Saved {fname} ({target_file.stat().st_size:,} bytes)")
                # Remove cached blob to save disk space
                try:
                    if os.path.exists(downloaded_path):
                        os.remove(downloaded_path)
                    blobs_dir = Path.home() / ".cache" / "huggingface" / "hub" / "blobs"
                    if blobs_dir.exists():
                        shutil.rmtree(blobs_dir, ignore_errors=True)
                except Exception:
                    pass

            digest = sha_file(target_file)
            file_manifest[fname] = digest
            print(f"     SHA256: {digest[:16]}...{digest[-8:]}")

        manifest_data = {
            "provenance": PROVENANCE,
            "local_directory": str(dest_dir),
            "target_language": lang,
            "files": file_manifest,
        }
        manifest_path = target_root / info["manifest_name"]
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False))
        print(f"Manifest written to: {manifest_path}")

        # Verification check against LocalNllbTranslator requirements
        actual_files = {p.name for p in dest_dir.iterdir() if p.is_file() and not p.name.startswith(".")}
        expected_files = set(file_manifest.keys())
        if actual_files != expected_files:
            raise ValueError(f"Directory contents mismatch: {actual_files} != {expected_files}")
        print(f"Verification successful: All {len(file_manifest)} files verified against manifest!")


def main():
    parser = argparse.ArgumentParser(description="Download MultiMed-ST weights and create manifests.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/models/MultiMed-ST"),
        help="Root directory to store model checkpoints",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        choices=["en", "zh"],
        default=["en", "zh"],
        help="Target languages to download (default: en zh)",
    )
    args = parser.parse_args()
    download_and_manifest(args.output_dir, args.languages)


if __name__ == "__main__":
    main()
