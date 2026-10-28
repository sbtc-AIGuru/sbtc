"""Publish the prepared private dataset and two T4x2 notebooks using existing Kaggle auth."""

import argparse
import json
from pathlib import Path
import sys
import time

from Scripts.Kaggle.prepare_vibiomir_embeddings import DATASET, OUTPUT, sha256


def save_part3_without_running(api, receipt, receipt_path):
    from kagglesdk.kernels.types.kernels_api_service import ApiSaveKernelRequest
    from kagglesdk.kernels.types.kernels_enums import KernelExecutionType

    folder = OUTPUT / "part-3"
    metadata = json.loads((folder / "kernel-metadata.json").read_text())
    notebook_path = folder / metadata["code_file"]
    request = ApiSaveKernelRequest()
    request.slug = metadata["id"]
    request.new_title = metadata["title"]
    request.text = notebook_path.read_text()
    request.language = "python"
    request.kernel_type = "notebook"
    request.is_private = True
    request.enable_gpu = True
    request.machine_shape = "NvidiaTeslaT4"
    request.enable_internet = True
    request.dataset_data_sources = metadata["dataset_sources"]
    request.kernel_execution_type = KernelExecutionType.QUICK_SAVE
    with api.build_kaggle_client() as client:
        result = client.kernels.kernels_api_client.save_kernel(request)
    if result.error or result.invalid_dataset_sources:
        raise RuntimeError(result.error or str(result.invalid_dataset_sources))
    receipt["part-3"] = dict(ref=metadata["id"], url=result.url, version=result.version_number,
                             code_sha256=sha256(notebook_path), private=True,
                             accelerator="NvidiaTeslaT4", execution_type="QUICK_SAVE")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt["part-3"]), flush=True)
    downloaded = OUTPUT / "part-3-remote"
    api.kernels_pull(metadata["id"], str(downloaded), metadata=True, quiet=True)
    remote_metadata = json.loads((downloaded / "kernel-metadata.json").read_text())
    remote_notebook = json.loads((downloaded / remote_metadata["code_file"]).read_text())
    local_notebook = json.loads(notebook_path.read_text())
    def sources(notebook):
        return ["".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
                for cell in notebook["cells"]]
    if sources(remote_notebook) != sources(local_notebook):
        raise ValueError("Saved Kaggle notebook differs from the prepared notebook")
    if DATASET not in remote_metadata["dataset_sources"] or not remote_metadata["is_private"]:
        raise ValueError("Saved Kaggle notebook is missing its private input/settings")
    print(json.dumps(dict(remote_source_verified=True, dataset_sources=remote_metadata["dataset_sources"],
                          private=remote_metadata["is_private"])), flush=True)


def main(action, sdk_path):
    # Reuse the installed CLI's SDK from the project's Python; install nothing.
    if sdk_path:
        sys.path.append(sdk_path)
    import kaggle
    from requests.exceptions import HTTPError

    api = kaggle.api
    username = api.get_config_value(api.CONFIG_NAME_USER)
    if username != DATASET.split('/')[0]:
        raise ValueError("Kaggle authentication is missing or belongs to another account")
    receipt_path = OUTPUT / "publish-receipt.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    if action == "save-part3":
        save_part3_without_running(api, receipt, receipt_path)
        return
    if action == "publish":
        source = json.loads((OUTPUT / "dataset/source_manifest.json").read_text())
        for shard in source["shards"]:
            if sha256(OUTPUT / "dataset" / shard["file"]) != shard["compressed_sha256"]:
                raise ValueError("Prepared source shard checksum differs")
        try:
            status = api.dataset_status(DATASET)
        except HTTPError as error:
            # Kaggle may return 403 for a not-yet-created private dataset.
            # create_new below cannot replace an existing dataset.
            if error.response.status_code not in (403, 404):
                raise
            status = None
        if status is None and not receipt.get("dataset"):
            result = api.dataset_create_new(str(OUTPUT / "dataset"), public=False,
                                             quiet=True, convert_to_csv=False)
            if result.error:
                raise RuntimeError(result.error)
            receipt["dataset"] = dict(ref=DATASET, url=result.url,
                                      source_sha256=source["source_sha256"])
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt["dataset"]), flush=True)
        elif receipt.get("dataset", {}).get("source_sha256") != source["source_sha256"]:
            raise ValueError("Dataset already exists without a matching local publishing receipt; not overwriting")
        readiness_deadline = time.monotonic() + 900
        while True:
            try:
                status = api.dataset_status(DATASET)
            except HTTPError as error:
                if error.response.status_code not in (403, 404) or time.monotonic() >= readiness_deadline:
                    raise
                status = "processing-or-not-indexed"
            print(json.dumps(dict(dataset=DATASET, status=status)), flush=True)
            if status == "ready":
                break
            if status in ("error", "failed"):
                raise RuntimeError("Kaggle dataset processing failed")
            time.sleep(20)
        for part in (1, 2):
            folder = OUTPUT / f"part-{part}"
            metadata = json.loads((folder / "kernel-metadata.json").read_text())
            name = f"part-{part}"
            code_hash = sha256(folder / metadata["code_file"])
            if receipt.get(name, {}).get("code_sha256") == code_hash:
                print(json.dumps(dict(part=part, already_published=True)), flush=True)
                continue
            result = api.kernels_push(str(folder), timeout=43200, acc="NvidiaTeslaT4")
            if result.error or result.invalid_dataset_sources:
                raise RuntimeError(result.error or str(result.invalid_dataset_sources))
            receipt[name] = dict(ref=metadata["id"], url=result.url, version=result.version_number,
                                 code_sha256=code_hash, accelerator="NvidiaTeslaT4", private=True)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt[name]), flush=True)
    for part in (1, 2):
        name = f"part-{part}"
        if name not in receipt:
            continue
        ref = receipt[name]["ref"].removeprefix("/code/")
        status = api.kernels_status(ref)
        print(json.dumps(dict(ref=ref, status=str(status.status), failure_message=status.failure_message)), flush=True)
        if action == "logs":
            logs = api.kernels_logs(ref)
            (OUTPUT / f"{name}-run.log").write_text(logs)
            print(logs[-16000:], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["publish", "status", "logs", "save-part3"])
    parser.add_argument("--sdk-path")
    arguments = parser.parse_args()
    main(arguments.action, arguments.sdk_path)
