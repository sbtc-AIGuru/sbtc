"""Split the corpus without changing records and package three standalone notebooks."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import zstandard as zstd


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/vibiomir-qwen3-3parts-20261024"
SOURCE = ROOT / "datav3/ViBioMIR_chunks_with_recovery.jsonl"
MODEL = "Qwen/Qwen3-Embedding-0.6B"
REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
EXPECTED_ROWS = 4_936_835
EXPECTED_TOKENS = 1_083_801_672
EXPECTED_SHA = "a45123b3de7a9b048f83418515a3ec6b3dd09e1e4491dd361429b787659a3e7f"
DATASET = "nhminh107/vibiomir-chunks-qwen3-input-3parts-20261024"
PARTS = 3


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_data():
    folder = OUTPUT / "dataset"
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "source_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["source_sha256"] != EXPECTED_SHA:
            raise ValueError("Existing manifest belongs to another corpus")
        for shard in manifest["shards"]:
            if sha256(folder / shard["file"]) != shard["compressed_sha256"]:
                raise ValueError(f"Corrupt input shard: {shard['file']}")
        return manifest

    # A disk-backed uniqueness check avoids keeping five million IDs in RAM.
    database = OUTPUT / "prepare_ids.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("DROP TABLE IF EXISTS ids")
    connection.execute("CREATE TABLE ids (id TEXT PRIMARY KEY) WITHOUT ROWID")
    shards = []
    source_hash = hashlib.sha256()
    total_tokens = 0
    byte_offset = 0
    line_number = 0
    source = SOURCE.open("rb")
    for index in range(PARTS * 2):
        path = folder / f"chunks-{index:02d}.jsonl.zst"
        raw_hash = hashlib.sha256()
        shard = dict(file=path.name, part=index // 2 + 1, gpu=index % 2,
                     start_line=line_number + 1, start_byte=byte_offset, rows=0, tokens=0)
        with path.open("wb") as compressed:
            with zstd.ZstdCompressor(level=3).stream_writer(compressed, closefd=False) as writer:
                for line in source:
                    row = json.loads(line)
                    if not isinstance(row.get("content"), str) or not row["content"].strip():
                        raise ValueError(f"Empty content at line {line_number + 1}")
                    if not isinstance(row.get("chunk_id"), str) or not row["chunk_id"]:
                        raise ValueError(f"Invalid chunk_id at line {line_number + 1}")
                    if not isinstance(row.get("doc_id"), int):
                        raise ValueError(f"Invalid doc_id at line {line_number + 1}")
                    connection.execute("INSERT INTO ids VALUES (?)", (row["chunk_id"],))
                    writer.write(line)
                    raw_hash.update(line)
                    source_hash.update(line)
                    line_number += 1
                    byte_offset += len(line)
                    tokens = row["token_count"]
                    total_tokens += tokens
                    shard["rows"] += 1
                    shard["tokens"] += tokens
                    if index < PARTS * 2 - 1 and total_tokens >= EXPECTED_TOKENS * (index + 1) / (PARTS * 2):
                        break
        shard.update(end_line=line_number, end_byte=byte_offset,
                     raw_sha256=raw_hash.hexdigest(), compressed_sha256=sha256(path),
                     compressed_bytes=path.stat().st_size)
        shards.append(shard)
        connection.commit()
        print(json.dumps(shard), flush=True)
    source.close()
    connection.close()
    database.unlink()
    if (line_number, total_tokens, source_hash.hexdigest()) != (EXPECTED_ROWS, EXPECTED_TOKENS, EXPECTED_SHA):
        raise ValueError("Corpus changed; recompute the expected counts and SHA before packaging")
    manifest = dict(schema_version="vibiomir-source-v1", source_file=SOURCE.name,
                    source_sha256=EXPECTED_SHA, source_bytes=byte_offset,
                    total_rows=line_number, total_tokens=total_tokens,
                    unique_chunk_ids=True, num_parts=PARTS,
                    partition="six contiguous token-balanced ranges",
                    shards=shards)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (folder / "dataset-metadata.json").write_text(json.dumps(dict(
        id=DATASET, title="ViBioMIR chunks Qwen3 input 3parts 20261024",
        licenses=[dict(name="unknown")],
        description="Private processing copy of ViBioMIR_chunks_with_recovery.jsonl. "
                    "Original records retained byte-for-byte in six Zstandard shards. "
                    "Original rights remain with the respective authors. See source_manifest.json.",
    ), indent=2) + "\n")
    return manifest


def cell(source, kind="code", number=0):
    result = dict(cell_type=kind, id=f"cell-{number:02d}", metadata={}, source=source)
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def prepare_notebooks(manifest, parts=None):
    runtime = (ROOT / "Scripts/Kaggle/vibiomir_embedding_runtime.py").read_text()
    readme = (ROOT / "Scripts/Kaggle/ViBioMIR_Embeddings.md").read_text()
    for part in parts or range(1, PARTS + 1):
        output_readme = ((ROOT / "Scripts/Kaggle/ViBioMIR_Part3_For_Friend.md").read_text()
                         if part == 3 else readme)
        folder = OUTPUT / f"part-{part}"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"ViBioMIR_Qwen3_06B_Part{part}_T4x2.ipynb"
        config = dict(part=part, model_id=MODEL, revision=REVISION, dimension=1024,
                      max_length=4096, dtype="float16", pooling="last_token",
                      normalize=True, document_prompt="", vector_name="qwen3_dense",
                      output_rows=8192, max_batch_size=64, padded_token_budget=16384,
                      max_hours=11.25, expected_source_sha256=EXPECTED_SHA,
                      input_root="/kaggle/input", output_root="/kaggle/working/vibiomir_embeddings",
                      resume_roots=[], require_t4=True)
        description = f"""# ViBioMIR · Qwen3 Embedding 0.6B · phần {part}/3 · T4 ×2

Chọn **GPU T4 ×2**, bật Internet, **Save Version → Save & Run All**.
Notebook dùng **2 tiến trình, 2 bản mô hình**, bắt buộc nhìn thấy hai T4.
Ba phần độc lập, không cần output của phần khác. Dataset input đã được gắn.

Embedding nguyên trường `content`, không thêm prompt tài liệu; last-token pooling,
L2 normalization, 1024 chiều. FP16 trên T4, SDPA; không cài FlashAttention 2.
Tokenize không truncation: nếu vượt 4096 token thì dừng và báo lỗi, không cắt nội dung.

Mỗi file Parquet chứa vector float32, UUID, ID chunk/doc, văn bản và `payload_json`
giữ **toàn bộ record gốc**, kèm `_embedding` để đối chiếu nguồn và mô hình.
Kết quả trong `/kaggle/working/vibiomir_embeddings/part-{part}/`.
Chỉ dùng bộ output có `manifest.json` ghi `complete: true` để nhập Qdrant.

Dừng có checkpoint sau 11,25 giờ tính từ cell cấu hình, chừa thời gian lưu output.
ETA tính từ tốc độ thực, chưa phải cam kết hoàn thành trong một phiên.
Nếu chưa xong: Add Input output phiên cũ, điền đường dẫn thư mục chứa manifest vào
`CONFIG['resume_roots']`; chạy lại cùng cấu hình. File hoàn tất được kiểm tra checksum
và sao chép vào output mới. Chỉ attach đúng phần tương ứng, tránh input trùng.

Sau khi **cả ba phần** hoàn tất: Add Input các output để sử dụng vector/metadata.
Hướng dẫn tải và tự chạy phần 3 trong `README.md`.
"""
        if part == 3:
            description = """# ViBioMIR · phần 3/3 · chạy trên tài khoản Kaggle của bạn

Notebook tự chứa toàn bộ mã, xử lý **1.626.231 chunk** bằng **hai GPU T4**.
Dataset nguồn đã gắn sẵn trên Kaggle; không cần tải/upload lại dữ liệu,
GitHub, token Hugging Face hoặc output phần 1/2.

**Người sở hữu:** cấp quyền truy cập cho bạn ở cả notebook này và dataset private
`nhminh107/vibiomir-chunks-qwen3-input-3parts-20261024` (hai quyền độc lập).

**Người nhận:**
1. Mở notebook được chia sẻ. Để chạy bản riêng trên tài khoản của bạn, chọn **Copy & Edit**.
2. Kiểm tra dataset nguồn vẫn có trong bảng Input. Nếu cần, **Add Input** dataset
   đã được cấp quyền; chỉ gắn một bản của nguồn này.
3. Chọn **GPU T4 ×2**, bật **Internet**, giữ nguyên cấu hình.
4. **Save Version → Save & Run All**. Không phải sửa đường dẫn hay username.

Cell kiểm tra đầu vào sẽ dừng sớm nếu thiếu file, gắn trùng nguồn hoặc không đủ hai T4.
Mỗi GPU giữ một bản mô hình Qwen3 Embedding 0.6B, xử lý một dải dữ liệu riêng.
Giữ nguyên `CONFIG['part'] = 3` và cấu hình encoder để output khớp phần 1/2.

Kết quả: `/kaggle/working/vibiomir_embeddings/part-3/`, Parquet float32 1024 chiều,
giữ toàn bộ ID/metadata gốc. Dừng có checkpoint sau 11,25 giờ nếu chưa xong.
Chỉ báo hoàn tất khi `manifest.json` có `complete: true`, `rows: 1626231`.

**Gửi kết quả lại:** tải toàn bộ output sau khi version chạy xong, bao gồm Parquet,
receipt `*.parquet.json`, `manifest.json` và báo cáo hai GPU. Không chỉ gửi notebook.
Hướng dẫn chi tiết và cách tiếp tục checkpoint có trong `README.md` đi kèm.
"""
        preflight = """# Không cần sửa username hoặc tên dataset khi chuyển sang tài khoản khác.
import torch

if CONFIG['part'] != 3:
    raise ValueError('Notebook bàn giao này chỉ chạy phần 3; giữ CONFIG[part] = 3.')
if not torch.cuda.is_available() or torch.cuda.device_count() != 2:
    raise RuntimeError('Hãy chọn Accelerator = GPU T4 ×2 trước khi chạy.')
devices = [torch.cuda.get_device_name(index) for index in (0, 1)]
if any('T4' not in name for name in devices):
    raise RuntimeError(f'Cần hai T4; GPU hiện tại: {devices}')

matches = []
for candidate in Path(CONFIG['input_root']).rglob('source_manifest.json'):
    data = json.loads(candidate.read_text())
    if data.get('source_sha256') == CONFIG['expected_source_sha256']:
        matches.append((candidate, data))
if len(matches) != 1:
    raise ValueError('Cần được cấp quyền dataset nguồn và Add Input đúng một bản chứa '
                     'source_manifest.json, chunks-04.jsonl.zst và chunks-05.jsonl.zst.')
source_manifest_path, source_info = matches[0]
part_shards = [item for item in source_info['shards'] if item['part'] == 3]
if (sorted(item['gpu'] for item in part_shards) != [0, 1]
        or sum(item['rows'] for item in part_shards) != 1626231):
    raise ValueError('Manifest không khớp phần 3 đã chia sẵn.')
missing = [item['file'] for item in part_shards
           if not (source_manifest_path.parent / item['file']).is_file()]
if missing:
    raise FileNotFoundError(f'Dataset thiếu file: {missing}. Upload đủ ba file trong input/.')
print(json.dumps({'part': 3, 'expected_rows': 1626231, 'gpus': devices,
                  'input': str(source_manifest_path.parent)}, ensure_ascii=False, indent=2))
"""
        bootstrap = """# Giữ PyTorch/CUDA có sẵn của Kaggle, chỉ pin các thư viện cần thiết.
import os
os.environ['HF_HOME'] = '/kaggle/temp/vibiomir-hf'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
import subprocess
import sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                'transformers==4.57.1', 'huggingface-hub==0.36.0',
                'tokenizers==0.22.1', 'pyarrow==20.0.0', 'zstandard==0.23.0',
                'safetensors==0.6.2'], check=True)
"""
        configure = ("import time\nimport json\nfrom pathlib import Path\n"
                     f"CONFIG = json.loads({json.dumps(config)!r})\n"
                     "CONFIG['deadline_unix'] = time.time() + CONFIG['max_hours'] * 3600\n"
                     "# RESUME: điền thư mục part-N của output cũ đã Add Input.\n"
                     "# CONFIG['resume_roots'] = ['/kaggle/input/.../vibiomir_embeddings/part-"
                     f"{part}']\n")
        package = ("runtime_path = Path('/kaggle/working/vibiomir_embedding_runtime.py')\n"
                   f"runtime_path.write_text({runtime!r})\n"
                   "output = Path(CONFIG['output_root']) / f\"part-{CONFIG['part']}\"\n"
                   "output.mkdir(parents=True, exist_ok=True)\n"
                   f"(output / 'README.md').write_text({output_readme!r})\n"
                   "config_path = Path('/kaggle/working/vibiomir_config.json')\n"
                   "config_path.write_text(json.dumps(CONFIG, indent=2))\n")
        launch = """# torchrun tạo đúng 2 worker; runtime kiểm tra tên GPU và số chunk từng GPU.
import uuid
CONFIG['run_id'] = str(uuid.uuid4())
config_path.write_text(json.dumps(CONFIG, indent=2))
subprocess.run([sys.executable, '-m', 'torch.distributed.run',
                '--standalone', '--nproc_per_node=2', str(runtime_path),
                '--config', str(config_path)], check=True)
"""
        final = """report = json.loads((output / 'manifest.json').read_text())
print(json.dumps({k: report[k] for k in ('part', 'complete', 'rows', 'expected_rows',
                                       'elapsed_seconds')}, indent=2))
print(json.dumps([{k: worker[k] for k in ('gpu', 'device', 'rows', 'new_rows',
                                          'resumed_rows', 'peak_allocated_gib')}
                  for worker in report['gpu_workers']], indent=2))
if report['complete']:
    print('HOÀN TẤT phần', CONFIG['part'], '— có thể Add Input output này để nạp Qdrant.')
else:
    print('CHƯA HOÀN TẤT. Đã lưu checkpoint. Add Input output này và đặt resume_roots để tiếp tục.')
"""
        if part == 3:
            final = final.replace('— có thể Add Input output này để nạp Qdrant.',
                                  '— tải toàn bộ output và gửi lại cho người nhờ chạy.')
        sources = [(description, "markdown"), (configure, "code"), (bootstrap, "code"),
                   (package, "code"), (launch, "code"), (final, "code")]
        if part == 3:
            sources.insert(2, (preflight, "code"))
        notebook = dict(cells=[cell(s, k, i) for i, (s, k) in enumerate(sources)],
                        metadata=dict(kernelspec=dict(display_name="Python 3", language="python", name="python3"),
                                      language_info=dict(name="python", version="3.11"),
                                      accelerator="GPU", kaggle=dict(isGpuEnabled=True, isInternetEnabled=True,
                                                                     dataSources=[])),
                        nbformat=4, nbformat_minor=5)
        (folder / name).write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n")
        target = ROOT / "BackEnd/app/Database/Notebook" / name
        target.write_bytes((folder / name).read_bytes())
        metadata = dict(id=f"nhminh107/vibiomir-qwen3-06b-part{part}-t4x2-20261024",
                        title=f"ViBioMIR Qwen3 06B Part{part} T4x2 20261024", code_file=name,
                        language="python", kernel_type="notebook", is_private=True,
                        enable_gpu=True, machine_shape="NvidiaTeslaT4", enable_internet=True,
                        dataset_sources=[DATASET], kernel_sources=[], competition_sources=[], model_sources=[])
        (folder / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Packaged: {target}")


def prepare_manual_bundle():
    path = OUTPUT / "ViBioMIR_Part3_Kaggle.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as bundle:
        name = "ViBioMIR_Qwen3_06B_Part3_T4x2.ipynb"
        bundle.write(OUTPUT / "part-3" / name, name)
        bundle.write(ROOT / "Scripts/Kaggle/ViBioMIR_Part3_For_Friend.md", "README.md")
        for name in ("chunks-04.jsonl.zst", "chunks-05.jsonl.zst", "source_manifest.json"):
            bundle.write(OUTPUT / "dataset" / name, f"input/{name}")
    print(f"Manual part 3: {path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook-only", action="store_true")
    parser.add_argument("--manual-bundle", action="store_true")
    parser.add_argument("--parts", nargs="+", type=int, choices=range(1, PARTS + 1))
    args = parser.parse_args()
    if args.notebook_only:
        manifest = json.loads((OUTPUT / "dataset/source_manifest.json").read_text())
    else:
        manifest = prepare_data()
    prepare_notebooks(manifest, args.parts)
    if args.manual_bundle:
        prepare_manual_bundle()
