# ViBioMIR — 3 phiên Qwen3 Embedding 0.6B, mỗi phiên T4 ×2

Toàn bộ **4.936.835 chunk** được chia thành **3 phần độc lập**, cân bằng theo tổng
`token_count` gốc. Mỗi phần gồm hai dải dòng liên tục, mỗi GPU xử lý một dải.
Phần 1 và 2 được đưa lên Kaggle. Phần 3 có notebook và gói input riêng để tự chạy.
Không cần output của phần trước để chạy phần sau. Chưa tạo/nạp Qdrant ở bước này.

## Cấu hình và thời gian

- Settings: **GPU T4 ×2**, **Internet On**. Không chọn P100 hoặc một GPU.
- `torchrun --nproc_per_node=2`: hai tiến trình, mỗi GPU giữ một model replica.
  Runtime bắt buộc nhìn thấy đúng hai T4, không tự rơi về một GPU/CPU.
- Model `Qwen/Qwen3-Embedding-0.6B`, revision cố định
  `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`.
- FP16, SDPA, left padding, last-token pooling, L2 normalization, vector 1024 chiều.
  Giữ PyTorch/CUDA có sẵn của Kaggle; notebook cài các thư viện Python cần thiết.
  Không cài FlashAttention 2 trên T4.
- Chỉ embedding nguyên trường `content`, không thêm prompt/chat template.
  Tokenize không truncation; nếu vượt 4096 token thì báo lỗi, không cắt văn bản.
- Sắp theo độ dài trong block, tối đa 64 chunk/batch và 16.384 padded token.
  Batch OOM được chia đôi. Khi ghi output, trả về đúng thứ tự nguồn.
- Tối đa 8.192 dòng/file Parquet, nén Zstandard. Không gom mọi vector vào RAM.
- Dừng nhận block mới sau **11,25 giờ** từ cell cấu hình, hoàn tất block đang chạy
  và lưu checkpoint, chừa thời gian xuất output trước giới hạn 12 giờ.
- Ghi tốc độ/ETA thực tế riêng mỗi GPU. Chưa đo trên Kaggle thì chưa thể cam kết
  hoàn tất trong một phiên; nếu chưa xong, tiếp tục từ checkpoint như bên dưới.

## Tải và setup phần 3 trên Kaggle

Gói `ViBioMIR_Part3_Kaggle.zip` chứa:

```text
ViBioMIR_Qwen3_06B_Part3_T4x2.ipynb
README.md
input/
  chunks-04.jsonl.zst
  chunks-05.jsonl.zst
  source_manifest.json
```

1. Tải gói ZIP về máy và giải nén. Giữ nguyên hai file `.jsonl.zst`; **không cần
   giải nén JSONL**. Chỉ cần hai shard này cho phần 3, không cần phần 1 và 2.
2. Trong Kaggle, vào **Datasets → New Dataset**. Upload hai file `.jsonl.zst` và
   `source_manifest.json` trong thư mục `input/`, chọn **Private**, rồi Create.
   Không upload notebook hoặc ZIP bao ngoài làm dataset input.
3. Vào **Code → New Notebook → File → Import Notebook**, chọn
   `ViBioMIR_Qwen3_06B_Part3_T4x2.ipynb` đã giải nén.
4. **Add Input** dataset phần 3 vừa tạo. Nếu dùng cùng tài khoản `nhminh107`, có thể
   gắn dataset nguồn 3 phần đã upload sẵn thay cho việc tạo dataset mới.
   Chỉ attach một dataset có `source_manifest.json` tương ứng để tránh bị trùng.
5. Settings: **Accelerator → GPU T4 ×2**, **Internet → On**.
6. Giữ `CONFIG['part'] = 3`, rồi **Save Version → Save & Run All**.
7. Trong log phải thấy cả `[GPU 0] Tesla T4` và `[GPU 1] Tesla T4`, sau đó có tiến độ
   `gpu: 0` và `gpu: 1`. Nếu thiếu GPU, runtime báo lỗi trước khi tải mô hình.
8. Khi hoàn tất, kiểm tra `manifest.json`: **`complete: true`** và
   **`rows == expected_rows`**. Lưu output version này để Add Input về sau.

Input giữ nguyên record nguồn theo byte. Manifest liệt kê sáu shard là bình thường:
notebook phần 3 chỉ đọc shard 04 và 05. Tính duy nhất của toàn bộ `chunk_id` đã được
kiểm tra bằng SQLite trên đĩa, cùng SHA-256 của toàn bộ JSONL gốc.

## Output và metadata

Trong `/kaggle/working/vibiomir_embeddings/part-N/`:

- `pN-gpuG-XXXXXXXXX.parquet`: vector và metadata từng block.
- `*.parquet.json`: receipt ghi SHA-256, số dòng, dải dòng nguồn và profile.
- `progress-gpu0.json`, `progress-gpu1.json`: số dòng, tốc độ, ETA và bộ nhớ GPU.
- `worker-gpu*.json`: số chunk thực sự xử lý/khôi phục trên mỗi GPU.
- `manifest.json`: trạng thái hoàn thành, danh sách file, source và encoder profile.
- `README.md`: hướng dẫn này.

| Cột Parquet | Ý nghĩa |
| --- | --- |
| `point_id` | UUID5 từ namespace cố định và `chunk_id`; chạy lại giữ ID |
| `chunk_id`, `doc_id` | ID nguồn giữ nguyên kiểu string/int64 |
| `source_line`, `source_byte` | Dòng **1-based**, byte **0-based** trong JSONL gốc chưa nén |
| `content`, `content_origin`, `token_count` | Văn bản nguyên gốc, nguồn recovery, số token gốc |
| `input_token_count` | Số token thực sự đưa vào Qwen |
| `content_sha256` | SHA-256 UTF-8 của văn bản chính xác đã embedding |
| `payload_json` | Toàn bộ record gốc và trường bổ sung `_embedding` |
| `vector` | Fixed-size list float32, 1024 chiều, chuẩn L2 bằng 1 |

`payload_json` giữ đầy đủ mọi trường metadata gốc. `_embedding` gồm model/revision,
profile ID, hash nguồn/nội dung, số dòng/byte, phần, GPU, độ dài input và
`truncated=false`. Metadata schema của Parquet cũng lưu đầy đủ encoder profile.
Không bỏ chunk recovery, không đổi ID, không làm tròn vector sang FP16 khi lưu.

Mỗi phần có khoảng 6,7 GB vector float32 thô cộng payload; Parquet nén giúp giảm
văn bản. Không tạo ZIP thứ hai của output trong working.

## Tiếp tục nếu chưa hoàn tất

1. Lưu output phiên đã dừng. Tạo version mới của **cùng notebook/phần**.
2. Add Input output phiên cũ hoặc dataset chứa nguyên thư mục output.
3. Trong cell cấu hình, đặt `CONFIG['resume_roots']` thành danh sách thư mục `part-N`
   chứa các file `*.parquet.json`, ví dụ
   `['/kaggle/input/your-previous-output/vibiomir_embeddings/part-3']`.
4. Giữ nguyên nguồn và cấu hình encoder. Run All.

Runtime kiểm tra checksum, dimension, vector, thứ tự dòng và fingerprint trước khi
khôi phục, rồi sao chép block hoàn tất vào output mới để version mới tự đủ dữ liệu.
File `.partial` và Parquet chưa có receipt không được coi là checkpoint hoàn tất.
Trong cùng phiên bị gián đoạn, có thể chạy lại cell launcher để tiếp tục file đã ghi.

## Add Input để dùng vector về sau

Khi cả ba manifest đều có `complete: true`, Add Input ba output vào notebook xử lý
bước tiếp theo. Nếu chạy bằng tài khoản Kaggle khác, tải output phần 3 về rồi upload
thành dataset private trên tài khoản đích, hoặc cấp quyền truy cập phù hợp.

Ví dụ đọc theo batch, không nạp toàn bộ dữ liệu vào RAM:

```python
from pathlib import Path
import json
import pyarrow.parquet as pq

part = Path('/kaggle/input/YOUR-OUTPUT/vibiomir_embeddings/part-3')
manifest = json.loads((part / 'manifest.json').read_text())
assert manifest['complete'] and manifest['rows'] == manifest['expected_rows']

for item in manifest['files']:
    for batch in pq.ParquetFile(part / item['file']).iter_batches(batch_size=128):
        rows = batch.to_pydict()
        # rows['vector'], rows['point_id'], rows['chunk_id'], rows['doc_id']
        # metadata đầy đủ: json.loads(rows['payload_json'][i])
```

Giữ đủ manifest/receipt/Parquet để kiểm tra checksum và ba phần cùng profile.
Đầu ra có ID hợp lệ và payload đầy đủ để dùng với hệ lưu trữ ở bước sau.

## Tạo lại gói local

```sh
.venv/bin/python Scripts/Kaggle/prepare_vibiomir_embeddings.py
# Sau khi sửa runtime/tài liệu, không chia lại dữ liệu:
.venv/bin/python Scripts/Kaggle/prepare_vibiomir_embeddings.py --notebook-only
# Chỉ chuẩn bị lại phần 3 để gửi bạn bè, không đổi notebook phần 1/2:
.venv/bin/python Scripts/Kaggle/prepare_vibiomir_embeddings.py --notebook-only --parts 3 --manual-bundle
```

Gói upload: `artifacts/vibiomir-qwen3-3parts-20261024/`.
Chỉ publish/run phần 1 và 2; phần 3 do người dùng tự chạy. Mặc định private,
accelerator `NvidiaTeslaT4`, timeout 43.200 giây.

Nguồn kỹ thuật: [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
[Kaggle metadata](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md).
