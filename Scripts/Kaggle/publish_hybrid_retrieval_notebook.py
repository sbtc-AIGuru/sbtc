"""Publish the reviewed private paired-query dataset and modular notebook."""

import argparse
import ast
import json
from pathlib import Path
import sys
import zipfile

from Scripts.Kaggle.prepare_hybrid_retrieval_notebook import DATASET, INPUT_KERNELS, NAME, OUTPUT, REF, digest

SDK_PATH = "/home/nhminh/.local/share/pipx/venvs/kaggle/lib/python3.14/site-packages"


def check_package(*, allow_full=False):
    manifest = json.loads((OUTPUT / "package-manifest.json").read_text())
    metadata = json.loads((OUTPUT / "kernel/kernel-metadata.json").read_text())
    if (metadata["id"] != REF or
            not metadata["is_private"] or metadata["enable_gpu"] or
            metadata["kernel_sources"] != INPUT_KERNELS or metadata["dataset_sources"] != [DATASET] or
            digest(OUTPUT / "kernel" / NAME) != manifest["notebook_sha256"]):
        raise ValueError("Prepared private package changed")
    for name, expected in manifest["input_hashes"].items():
        if digest(OUTPUT / "queries" / name) != expected:
            raise ValueError(f"Prepared dataset input changed: {name}")
    notebook = json.loads((OUTPUT / "kernel" / NAME).read_text())
    configuration = next(cell["source"] for cell in notebook["cells"] if cell["id"] == "configuration")
    settings = {node.targets[0].id: ast.literal_eval(node.value)
                for node in ast.parse(configuration).body if isinstance(node, ast.Assign)}
    if (settings["RUN_PIPELINE"] != manifest["default_run_pipeline"] or
            settings["HNSW_EF"] != manifest.get("hnsw_ef")):
        raise ValueError("Notebook run settings differ from package manifest")
    if settings["RUN_PIPELINE"] and not allow_full:
        raise ValueError("Full indexing requires explicit --run-full authorization")
    return manifest, metadata


def dataset_details(api):
    from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetRequest

    with api.build_kaggle_client() as client:
        request = ApiGetDatasetRequest()
        request.owner_slug, request.dataset_slug = DATASET.split("/")
        dataset = client.datasets.dataset_api_client.get_dataset(request)
        if not dataset.is_private:
            raise ValueError("Query dataset must remain private")
        return {"ref": DATASET, "private": dataset.is_private,
                "version": dataset.current_version_number}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["upload-inputs", "update-inputs", "dataset-status", "verify-inputs", "launch", "status", "verify-notebook", "logs"])
    parser.add_argument("--new-version", action="store_true", help="Intentionally publish a revised reviewed notebook version")
    parser.add_argument("--run-full", action="store_true", help="Authorize launching the prepared full corpus run")
    args = parser.parse_args()
    manifest, metadata = check_package(allow_full=args.run_full or args.action in {"status", "logs", "verify-notebook"})
    sys.path.append(SDK_PATH)
    import kaggle

    api = kaggle.api
    if api.get_config_value(api.CONFIG_NAME_USER) != REF.split("/")[0]:
        raise ValueError("Kaggle account does not match the intended owner")
    if args.action == "upload-inputs":
        receipt = OUTPUT / "dataset-upload-receipt.json"
        if receipt.exists():
            raise FileExistsError("Dataset upload receipt exists; inspect/verify it before another upload")
        result = api.dataset_create_new(str(OUTPUT / "queries"), public=False, convert_to_csv=False, quiet=True)
        if result.error:
            raise RuntimeError(result.error)
        data = {"ref": DATASET, "url": result.url, "private": True,
                "input_hashes": manifest["input_hashes"]}
        receipt.write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data, indent=2))
    elif args.action == "update-inputs":
        dataset_details(api)
        result = api.dataset_create_version(str(OUTPUT / "queries"),
            "Preserve local language enrichment module before Elasticsearch indexing", quiet=True,
            convert_to_csv=False, delete_old_versions=False)
        if result.error:
            raise RuntimeError(result.error)
        (OUTPUT / "dataset-update-receipt.json").write_text(json.dumps({"ref": DATASET,
            "private": True, "input_hashes": manifest["input_hashes"]}, indent=2) + "\n")
        print("Uploaded reviewed source update; existing dataset remains private")
    elif args.action == "dataset-status":
        print(api.dataset_status(DATASET, format="json"))
    elif args.action == "verify-inputs":
        details = dataset_details(api)
        destination = OUTPUT / "remote-inputs"
        destination.mkdir(exist_ok=True)
        expanded = json.loads((OUTPUT / "queries/source-manifest.json").read_text())["sources"]
        files = {name: expected for name, expected in manifest["input_hashes"].items() if name != "pipeline_source.zip"}
        files.update({"pipeline_source/" + name: expected for name, expected in expanded.items()})
        for name, expected in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            api.dataset_download_file(DATASET, name, path=str(path.parent), quiet=True, force=True)
            if not path.exists() and path.with_suffix(path.suffix + ".zip").exists():
                with zipfile.ZipFile(path.with_suffix(path.suffix + ".zip")) as archive:
                    if archive.namelist() != [name]:
                        raise ValueError("Unexpected downloaded dataset archive")
                    path.write_bytes(archive.read(name))
            if digest(path) != expected:
                raise ValueError(f"Uploaded dataset file changed bytes: {name}")
        details["all_files_sha256_verified"] = True
        details["verified_files"] = len(files)
        (OUTPUT / "dataset-verification.json").write_text(json.dumps(details, indent=2) + "\n")
        print(json.dumps(details, indent=2))
    elif args.action == "launch":
        verified = json.loads((OUTPUT / "dataset-verification.json").read_text())
        if not verified["all_files_sha256_verified"] or not verified["private"]:
            raise ValueError("Verify all uploaded inputs before notebook launch")
        receipt = OUTPUT / "launch-receipt.json"
        if receipt.exists() and not args.new_version:
            raise FileExistsError("Launch receipt already exists; inspect the current notebook version")
        result = api.kernels_push(str(OUTPUT / "kernel"), timeout="43200")
        if result.error or result.invalid_kernel_sources or result.invalid_dataset_sources:
            raise RuntimeError(result.error or str(result.invalid_kernel_sources or result.invalid_dataset_sources))
        data = {"ref": REF, "url": result.url, "version": result.version_number, "private": True,
                "gpu": False, "run_pipeline": manifest["default_run_pipeline"],
                "hnsw_ef": manifest.get("hnsw_ef"), "code_sha256": manifest["notebook_sha256"]}
        if receipt.exists():
            previous = json.loads(receipt.read_text())
            (OUTPUT / f"launch-v{previous['version']}.json").write_text(receipt.read_text())
        receipt.write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data, indent=2))
    elif args.action == "verify-notebook":
        folder = OUTPUT / "remote-notebook"
        api.kernels_pull(REF, str(folder), metadata=True, quiet=True)
        remote_meta = json.loads((folder / "kernel-metadata.json").read_text())
        remote = json.loads((folder / remote_meta["code_file"]).read_text())
        local = json.loads((OUTPUT / "kernel" / NAME).read_text())
        def sources(notebook):
            return ["".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
                    for cell in notebook["cells"]]
        if (sources(remote) != sources(local) or not remote_meta["is_private"] or remote_meta["enable_gpu"] or
                sorted("/".join(ref.split("/")[:2]) for ref in remote_meta["kernel_sources"]) !=
                sorted("/".join(ref.split("/")[:2]) for ref in INPUT_KERNELS) or
                remote_meta["dataset_sources"] != [DATASET]):
            raise ValueError("Remote notebook source/input/privacy differs from the prepared package")
        report = {"remote_source_verified": True, "private": True, "gpu": False,
                  "code_cells": sum(cell["cell_type"] == "code" for cell in remote["cells"])}
        (OUTPUT / "notebook-verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    else:
        status = api.kernels_status(REF)
        print(json.dumps({"ref": REF, "status": str(status.status), "failure_message": status.failure_message}))
        if args.action == "logs":
            logs = api.kernels_logs(REF)
            (OUTPUT / "run.log").write_text(logs)
            print(logs[-10000:])


if __name__ == "__main__":
    main()
