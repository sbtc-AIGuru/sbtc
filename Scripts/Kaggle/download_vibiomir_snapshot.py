"""Download the verified ViBioMIR export with streaming HTTP Range resume."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

import requests


REF = "nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025"
PREFIX = "vibiomir_qdrant_dense_export/"
EXPECTED_SIZE = 18_820_493_824
EXPECTED_SHA = "fb8b93924f5141ae5603033ea4c1df46ee29315f0e4c2ab1541680b9ed358646"
SNAPSHOT_NAME = "RECOVERY_vibiomir_qwen3_dense.snapshot"
SDK = "/home/nhminh/.local/share/pipx/venvs/kaggle/lib/python3.14/site-packages"


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


class KaggleFiles:
    def __init__(self):
        sys.path.append(SDK)
        import kaggle
        self.api = kaggle.api
        self.urls = {}

    def refresh(self):
        from kagglesdk import KaggleCredentials
        from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest

        # The installed SDK otherwise tolerates an already expired OAuth token for 30 minutes.
        if str(self.api.get_config_value(self.api.CONFIG_NAME_AUTH_METHOD)) == "OAUTH":
            with self.api.build_kaggle_client() as client:
                credentials = KaggleCredentials.load(client=client)
                if (credentials and credentials._access_token_expiration
                        and credentials._access_token_expiration <= datetime.now(timezone.utc) + timedelta(minutes=2)):
                    credentials.refresh_access_token()
            self.api.authenticate()
        urls = {}
        token = None
        with self.api.build_kaggle_client() as client:
            while True:
                request = ApiListKernelSessionOutputRequest()
                request.user_name, request.kernel_slug = REF.split("/")
                request.page_size, request.page_token = 100, token
                response = client.kernels.kernels_api_client.list_kernel_session_output(request)
                for item in response.files or []:
                    if item.file_name.startswith(PREFIX):
                        name = item.file_name.removeprefix(PREFIX)
                        if not name or Path(name).name != name:
                            raise ValueError("Unexpected nested export filename")
                        urls[name] = item.url
                token = response.next_page_token
                if not token:
                    break
        self.urls = urls

    def url(self, name, refresh=False):
        if refresh or name not in self.urls:
            self.refresh()
        return self.urls[name]


def stream_ranges(url_provider, partial, total, chunk_bytes=256 * 1024**2,
                  max_failures=12, session=None, progress=None):
    """Persist partial data before retries; refuse responses that cannot resume safely."""
    partial = Path(partial)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > total:
        raise ValueError("Partial file is larger than the expected snapshot")
    session = session or requests.Session()
    failures = 0
    started, initial = time.monotonic(), offset
    while offset < total:
        end = min(total - 1, offset + chunk_bytes - 1)
        try:
            with session.get(url_provider(), headers={"Range": f"bytes={offset}-{end}",
                             "Accept-Encoding": "identity"}, stream=True, timeout=(30, 90)) as response:
                if response.status_code in (401, 403):
                    url_provider(refresh=True)
                    raise requests.ConnectionError("Signed download URL needs refresh")
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    raise requests.ConnectionError(f"Temporary HTTP {response.status_code}")
                if response.status_code != 206:
                    raise RuntimeError(f"HTTP {response.status_code}: server did not honor the requested byte range")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or tuple(map(int, match.groups())) != (offset, end, total):
                    raise RuntimeError("Content-Range differs from the requested snapshot range")
                with partial.open("ab") as output:
                    try:
                        for block in response.iter_content(1024**2):
                            if block:
                                if offset + len(block) > end + 1:
                                    raise RuntimeError("Server sent more bytes than the requested range")
                                output.write(block)
                                offset += len(block)
                    finally:
                        output.flush()
                        os.fsync(output.fileno())
                if offset != end + 1:
                    raise requests.ConnectionError("Byte range ended prematurely")
            failures = 0
            seconds = max(0.001, time.monotonic() - started)
            speed = (offset - initial) / seconds
            state = {"state": "downloading", "bytes": offset, "total_bytes": total,
                     "percent": round(offset / total * 100, 2),
                     "mib_per_second": round(speed / 1024**2, 2),
                     "eta_seconds": round((total - offset) / speed) if speed else None}
            if progress:
                progress(state)
            print(json.dumps(state), flush=True)
        except requests.RequestException as error:
            offset = partial.stat().st_size if partial.exists() else 0
            failures += 1
            if failures > max_failures:
                raise RuntimeError(f"Download interrupted repeatedly; {offset} bytes preserved in {partial}") from None
            print(json.dumps({"state": "retrying", "attempt": failures, "resume_byte": offset,
                              "reason": type(error).__name__}), flush=True)
            time.sleep(min(15, 2 ** min(failures - 1, 4)))
    return offset


def download(folder):
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / SNAPSHOT_NAME
    partial = final.with_suffix(final.suffix + ".partial")
    if final.exists() and final.stat().st_size == EXPECTED_SIZE:
        if checksum(final) != EXPECTED_SHA:
            raise ValueError("Existing full-size snapshot has a different SHA-256; preserved unchanged")
        print("Snapshot already complete and SHA-256 verified", flush=True)
        return
    if final.exists() and final.stat().st_size > 0:
        if partial.exists():
            raise ValueError("Both a nonempty final file and partial exist; preserved both for inspection")
        final.replace(partial)
    offset = partial.stat().st_size if partial.exists() else 0
    remaining = EXPECTED_SIZE - offset
    if shutil.disk_usage(folder).free < remaining + 1024**3:
        raise RuntimeError("Not enough disk space for the remaining snapshot plus 1 GiB headroom")
    files = KaggleFiles()
    files.refresh()
    manifest_response = requests.get(files.url("snapshot_manifest.json"), timeout=60)
    manifest_response.raise_for_status()
    manifest = manifest_response.json()
    if (manifest["snapshot_file"] != SNAPSHOT_NAME or manifest["snapshot_bytes"] != EXPECTED_SIZE
            or manifest["snapshot_sha256"] != EXPECTED_SHA or manifest["raw_snapshot_sha256"] != EXPECTED_SHA
            or manifest["points"] != 4_936_835):
        raise ValueError("Kaggle export differs from the snapshot validated by the recheck notebook")
    for name in sorted(files.urls):
        if name == SNAPSHOT_NAME:
            continue
        response = requests.get(files.url(name), timeout=(30, 90))
        if not response.ok:
            raise RuntimeError(f"Cannot download export metadata {name}: HTTP {response.status_code}")
        destination = folder / name
        if destination.exists():
            if destination.read_bytes() != response.content:
                raise ValueError(f"Existing metadata differs; preserved unchanged: {destination}")
            continue
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
    receipt = folder / "download_progress.json"
    callback = lambda value: write_json(receipt, {**value, "expected_sha256": EXPECTED_SHA})
    stream_ranges(lambda refresh=False: files.url(SNAPSHOT_NAME, refresh), partial,
                  EXPECTED_SIZE, progress=callback)
    callback({"state": "verifying_sha256", "bytes": EXPECTED_SIZE, "total_bytes": EXPECTED_SIZE})
    print("All bytes downloaded; verifying SHA-256", flush=True)
    actual = checksum(partial)
    if actual != EXPECTED_SHA:
        callback({"state": "checksum_failed", "bytes": partial.stat().st_size, "actual_sha256": actual})
        raise ValueError("Snapshot SHA-256 mismatch; partial preserved for inspection")
    partial.replace(final)
    callback({"state": "complete", "bytes": EXPECTED_SIZE, "total_bytes": EXPECTED_SIZE,
              "sha256": actual, "snapshot": str(final)})
    # Keep the independent recheck evidence beside the unchanged original recovery manifest.
    results = Path(__file__).resolve().parents[2] / "artifacts/vibiomir-qdrant-dense-20261025/recheck/results/vibiomir_snapshot_recheck"
    for name in ("snapshot_validation.json", "recheck_report.json"):
        source = results / name
        destination = folder / name
        if source.exists() and not destination.exists():
            shutil.copyfile(source, destination)
    print(json.dumps({"complete": True, "snapshot": str(final), "bytes": EXPECTED_SIZE, "sha256": actual}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default="~/Downloads/qdrant_kaggle/vibiomir_qdrant_dense_export")
    args = parser.parse_args()
    try:
        download(args.folder)
    except requests.RequestException as error:
        # Signed download URLs are credentials: never include their query strings in logs.
        raise SystemExit(f"Kaggle/network request failed ({type(error).__name__}); rerun the same command to resume") from None
