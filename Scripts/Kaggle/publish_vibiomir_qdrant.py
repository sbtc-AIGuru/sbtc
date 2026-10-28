"""Inspect inputs, launch the prepared private CPU notebook, and read its status."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from Scripts.Kaggle.prepare_vibiomir_qdrant import CONFIG, OUTPUT, PINNED_SOURCES, REF, SOURCES


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_inputs(api):
    import requests
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest, ApiListKernelSessionOutputRequest

    reports = []
    with api.build_kaggle_client() as client:
        for part, ref in enumerate(SOURCES, 1):
            owner, slug = ref.split("/")
            status = api.kernels_status(ref)
            if str(status.status).split(".")[-1] != "COMPLETE":
                raise ValueError(f"Input is not COMPLETE: {ref}: {status.status}")
            request = ApiGetKernelRequest()
            request.user_name, request.kernel_slug = owner, slug
            metadata = client.kernels.kernels_api_client.get_kernel(request).metadata
            found = []
            token = None
            while True:
                request = ApiListKernelSessionOutputRequest()
                request.user_name, request.kernel_slug = owner, slug
                request.page_size, request.page_token = 100, token
                response = client.kernels.kernels_api_client.list_kernel_session_output(request)
                for item in response.files or []:
                    if item.file_name == f"vibiomir_embeddings/part-{part}/manifest.json":
                        result = requests.get(item.url, timeout=60)
                        result.raise_for_status()
                        found.append(result.json())
                token = response.next_page_token
                if not token:
                    break
            if len(found) != 1:
                raise ValueError(f"Expected one manifest for {ref}; found {len(found)}")
            manifest = found[0]
            expected = {1: 1_650_491, 2: 1_660_113, 3: 1_626_231}[part]
            if (not manifest["complete"] or manifest["part"] != part
                    or manifest["rows"] != expected or manifest["expected_rows"] != expected
                    or manifest["source"]["source_sha256"] != CONFIG["source_sha256"]
                    or manifest["profile_id"] != CONFIG["profile_id"]
                    or sum(f["rows"] for f in manifest["files"]) != expected):
                raise ValueError(f"Input manifest does not satisfy the corpus contract: {ref}")
            report = {"ref": ref, "version": metadata.current_version_number, "part": part,
                      "complete": True, "rows": expected, "parquet_files": len(manifest["files"]),
                      "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
                      "source_sha256": manifest["source"]["source_sha256"], "profile_id": manifest["profile_id"]}
            reports.append(report)
            print(json.dumps(report), flush=True)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "launch", "status", "logs", "pull"])
    parser.add_argument("--sdk-path", default="/home/nhminh/.local/share/pipx/venvs/kaggle/lib/python3.14/site-packages")
    args = parser.parse_args()
    sys.path.append(args.sdk_path)
    import kaggle

    api = kaggle.api
    if args.action == "inspect":
        inspect_inputs(api)
        return
    if args.action == "launch":
        if api.get_config_value(api.CONFIG_NAME_USER) != REF.split("/")[0]:
            raise ValueError("Kaggle authentication does not match the target owner")
        receipt_path = OUTPUT / "launch-receipt.json"
        if receipt_path.exists():
            raise FileExistsError("Launch receipt exists; inspect status before intentionally creating a new version")
        inputs = inspect_inputs(api)
        # Pin the expected upstream versions in the notebook config, then verify the pulled source.
        if [(r["ref"], r["version"]) for r in inputs] != [(r["ref"], r["version"]) for r in CONFIG["input_notebooks"]]:
            raise ValueError("Input versions changed; regenerate/review the notebook before launch")
        folder = OUTPUT / "kernel"
        metadata = json.loads((folder / "kernel-metadata.json").read_text())
        if not metadata["is_private"] or metadata["enable_gpu"] or metadata["kernel_sources"] != PINNED_SOURCES:
            raise ValueError("Notebook must be private, CPU-only and attach all three upstream outputs")
        result = api.kernels_push(str(folder), timeout=43_200)
        if result.error or result.invalid_kernel_sources or result.invalid_dataset_sources:
            raise RuntimeError(result.error or str(result.invalid_kernel_sources or result.invalid_dataset_sources))
        receipt = {"ref": REF, "url": result.url, "version": result.version_number,
                   "private": True, "gpu": False, "inputs": inputs,
                   "code_sha256": file_sha(folder / metadata["code_file"])}
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2), flush=True)
        return
    if args.action == "pull":
        api.kernels_pull(REF, str(OUTPUT / "remote"), metadata=True, quiet=True)
        folder = OUTPUT / "remote"
        remote_meta = json.loads((folder / "kernel-metadata.json").read_text())
        local_meta = json.loads((OUTPUT / "kernel/kernel-metadata.json").read_text())
        remote = json.loads((folder / remote_meta["code_file"]).read_text())
        local = json.loads((OUTPUT / "kernel" / local_meta["code_file"]).read_text())
        def sources(notebook):
            return ["".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in notebook["cells"]]
        # Kaggle pull omits version suffixes even when save attached versioned sources.
        returned_sources = remote_meta["kernel_sources"]
        normalized_sources = ["/".join(ref.split("/")[:2]) for ref in returned_sources]
        if (sources(remote) != sources(local) or not remote_meta["is_private"] or remote_meta["enable_gpu"]
                or sorted(normalized_sources) != sorted(SOURCES)):
            raise ValueError("Published notebook source/input/privacy settings differ")
        report = {"remote_source_verified": True, "private": True, "gpu": False,
                  "kernel_sources": returned_sources,
                  "requested_versioned_sources": PINNED_SOURCES,
                  "pull_exposes_input_versions": any(ref.count("/") > 1 for ref in returned_sources)}
        (OUTPUT / "remote-verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
        return
    status = api.kernels_status(REF)
    print(json.dumps({"ref": REF, "status": str(status.status), "failure_message": status.failure_message}), flush=True)
    if args.action == "logs":
        logs = api.kernels_logs(REF)
        (OUTPUT / "run.log").write_text(logs)
        print(logs[-16000:], flush=True)


if __name__ == "__main__":
    main()
