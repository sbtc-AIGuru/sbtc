# Bàn giao dữ liệu và output ViBioMIR — Qwen3 Embedding 0.6B

Tài liệu dành cho agent tiếp nhận các công việc phân tích, xây dựng chỉ mục, truy
xuất hoặc nạp dữ liệu sau này. Có thể dùng tài liệu này mà không cần đọc lại lịch
sử chat. Các thao tác xử lý tiếp theo phải theo yêu cầu cụ thể của người dùng.

**Ngày bàn giao:** 25/10/2026, múi giờ Asia/Ho_Chi_Minh (UTC+7).
**Trạng thái Part 3 được kiểm tra lúc:** 10:38:33 ngày 25/10/2026.
Trạng thái trong tài liệu là ảnh chụp tại thời điểm kiểm tra; khi tiếp nhận, đối
chiếu lại version và manifest của output thực tế.

## 1. Đọc nhanh trước khi làm việc

- Bộ nguồn có **4.936.835 chunk**, chia thành **3 part không trùng dải dòng**.
- Mỗi dòng output tương ứng **một chunk và một vector**; không phải một tài liệu.
- Model: `Qwen/Qwen3-Embedding-0.6B`, **1024 chiều**, inference **FP16**,
  vector lưu **FP32**, last-token pooling, chuẩn hóa L2.
- **Vector và toàn bộ metadata nguồn nằm cùng dòng Parquet.** Không phải ghép
  vector với các file JSON checkpoint để tìm văn bản/ID.
- `manifest.json` là danh mục file chính thức của từng part. Đọc file theo
  `manifest['files']`, không quét và ghép tùy ý mọi file trong Output.
- Part 1 và 2 đã hoàn tất và đã vượt qua kiểm tra **Add Input thực tế trên Kaggle**:
  **406 Parquet, 3.310.604 vector**, SHA-256 mọi file đúng, không thiếu dòng nguồn,
  tất cả vector hợp lệ; đối chiếu mẫu metadata ở từng file.
- Part 3 đang **RUNNING** tại thời điểm trên; chưa nằm trong kết quả kiểm tra 406 file.
- Muốn dùng toàn bộ corpus, phải có đủ **3 manifest `complete: true`**, cùng source
  và encoder profile, tổng **4.936.835 dòng**. Kaggle báo `COMPLETE` chưa đủ để kết
  luận corpus hoàn tất: phiên có thể dừng có checkpoint và `complete: false`.
- Qdrant/chỉ mục truy xuất chưa được tạo từ bộ output này. Có một script Qdrant
  cũ còn giả định 2 part; xem mục 11 trước khi dùng mã trong repository.

## 2. Tài nguyên và version cần biết

| Tài nguyên | Đường dẫn | Ghi nhận |
| --- | --- | --- |
| Input nén + manifest nguồn | [Dataset ViBioMIR](https://www.kaggle.com/datasets/nhminh107/vibiomir-chunks-qwen3-input-3parts-20261024) | Private; sáu shard input của ba part |
| Notebook Part 1 | [Part 1](https://www.kaggle.com/code/nhminh107/vibiomir-qwen3-06b-part1-t4x2-20261024) | Version 1 đã hoàn tất, output được kiểm chứng |
| Notebook Part 2 | [Part 2](https://www.kaggle.com/code/nhminh107/vibiomir-qwen3-06b-part2-t4x2-20261024) | Version 1 đã hoàn tất, output được kiểm chứng |
| Notebook Part 3 | [Part 3](https://www.kaggle.com/code/nhminh107/vibiomir-qwen3-06b-part3-t4x2-20261024) | Lượt khởi chạy được ghi nhận: version 3, lúc 07:15:46 ngày 25/10/2026 |
| Notebook đọc/kiểm tra output | [CPU Output Check](https://www.kaggle.com/code/nhminh107/vibiomir-embedding-output-check-20261025) | Version 1, `COMPLETE`, đã Add Input Part 1 và 2 |

Part 3 từng có lượt chạy lỗi khi **Internet Off** làm pip không truy cập được
PyPI. Version 3 đã bật Internet và xác nhận hai worker Tesla T4 khởi động. Không
dùng output của version lỗi hoặc quick-save ban đầu thay cho output hoàn tất.

Các tài nguyên giữ private. Khi làm trên tài khoản Kaggle khác, cần được cấp
quyền cho notebook và dataset private liên quan; hai quyền được quản lý riêng.
Khi chuyển giao kết quả, ghi lại version đã chọn, `source_sha256` và `profile_id`.

## 3. Nguồn dữ liệu và ý nghĩa ID

Nguồn local tính từ repository root `/home/nhminh/AI_Project/sbtc`:

```text
datav3/ViBioMIR_chunks_with_recovery.jsonl
```

| Thuộc tính | Giá trị |
| --- | --- |
| Số dòng/chunk | `4936835` |
| Số byte JSONL gốc | `5734771809` |
| Tổng `token_count` nguồn | `1083801672` |
| Số part | `3` |
| `schema_version` của manifest nguồn | `vibiomir-source-v1` |
| SHA-256 JSONL gốc | `a45123b3de7a9b048f83418515a3ec6b3dd09e1e4491dd361429b787659a3e7f` |

Mỗi record nguồn hiện có:

| Trường | Kiểu nguồn | Ý nghĩa |
| --- | --- | --- |
| `doc_id` | integer | ID tài liệu; nhiều chunk có thể cùng `doc_id` |
| `chunk_id` | string | ID chunk gốc; giữ như chuỗi opaque, không ép thành số |
| `content` | string | Văn bản chính xác được đưa vào embedding |
| `token_count` | integer | Số token đã có từ bước tạo chunk; không đồng nhất mặc định với tokenizer Qwen |
| `content_origin` | string | Nhãn nguồn nội dung/recovery, gồm `hf_sqlite`, `postgresql_sbtc`, `linked_pdf` |

Toàn bộ `chunk_id` đã được kiểm tra duy nhất bằng SQLite trên đĩa trong bước
chuẩn bị input. Không lọc chunk, không bỏ nguồn recovery và không đổi nội dung.
Các file input Zstandard giữ nguyên byte JSONL của từng dải nguồn.

**Quy tắc ID:**

- Giữ nguyên `doc_id` và `chunk_id`; không dùng `doc_id` làm khóa duy nhất cho chunk.
- `point_id` là UUID5 ổn định từ `chunk_id`, có thể dùng làm ID điểm ở bước lưu trữ.
- Công thức chính xác:

```python
import uuid

namespace = uuid.uuid5(uuid.NAMESPACE_URL, 'https://vibiomir.org/chunks')
point_id = str(uuid.uuid5(namespace, chunk_id))
```

Namespace có giá trị `ba368b92-593b-53e5-9fca-f889a83f6f8f`.
`point_id` không chứa model/revision: một profile embedding khác có thể tạo lại
cùng ID cho chunk đó. Khi lưu nhiều profile, phải quản lý chúng tách biệt rõ ràng.

### 3.1. Truy về tài liệu nguồn và giới hạn của `parent_id`

Đã kiểm tra mã tạo chunk tại `/data/DataCrawler/vibiomir_chunking/pipeline.py`:
`doc_id` được lấy trực tiếp từ `btc_id` của corpus ViBioMIR. Đây là **ID tài liệu
chính thức BTC**, không phải ID đoạn cha của pipeline SBTC cũ. JSONL nguồn chỉ có
năm trường trong bảng trên và vốn không có `parent_id`; bước embedding giữ nguyên
metadata nguồn, không phải làm mất quan hệ cha đã có.

Các phép nối có bằng chứng ở upstream:

| Nhu cầu | Nguồn đối chiếu | Khóa nối |
| --- | --- | --- |
| URL của tài liệu BTC | `/data/DataCrawler/links_corpus_vi_en_zh.parquet` (`id`, `url`) | Output `doc_id` = bảng nguồn `id` |
| URL, title, thông tin trích xuất của chunk production ban đầu | `documents.parquet` trong các bundle production của `/data/DataCrawler/vibiomir_chunking/kaggle_outputs/` | `doc_id`; chọn đúng run/bundle production, tránh smoke hoặc bản sao |
| Provenance của tài liệu recovery | `/data/DataCrawler/vibiomir_chunking/local_recovery/recovery_ledger.parquet` | `doc_id`; chọn record recovery được chấp nhận |

Ví dụ đã đối chiếu trực tiếp: `doc_id=4421055` tương ứng URL
`https://pubmed.ncbi.nlm.nih.gov/11197/`. Các bảng upstream này **không tự xuất hiện
trong output embedding khi Add Input**; nếu công việc sau cần URL/title thì phải
đưa thêm bảng metadata phù hợp vào input hoặc chuẩn bị sidecar theo `doc_id`.

Trong pipeline cũ (`Scripts/Preprocess/format_chunking.py`), một tài liệu có nhiều
đoạn cha; `parent_id` có dạng
`{doc_id}:p:{parent_order}:{start_char}:{end_char}:{PROFILE_VERSION}`. ViBioMIR chia
chunk lại, có thêm context và không lưu offsets/quan hệ cha này. Vì vậy:

- Không gán `parent_id = doc_id`, không diễn giải các đoạn hash trong `chunk_id`
  thành offsets hoặc ID cha cũ. UUID `point_id` cũng không khôi phục được quan hệ đó.
- Muốn có **đúng parent cũ**, cần dữ liệu cha/con cũ và mapping tài liệu, sau đó
  đối chiếu nội dung/phiên bản. Không mặc định mỗi chunk ViBioMIR khớp đúng một
  parent cũ; có thể không khớp hoặc phủ nhiều đoạn cha.
- Nếu cần parent theo tài liệu, có thể định nghĩa trường mới như
  `parent_doc_id = doc_id`, kèm kho tài liệu để lấy nội dung. Đây là quan hệ mới,
  không có nghĩa tương đương `parent_id` cũ.
- Có thể bổ sung URL/title hoặc mapping cha đã kiểm chứng bằng sidecar theo
  `doc_id`/`chunk_id`/`point_id`, không cần chạy embedding lại khi `content` và
  encoder không thay đổi. Nếu đổi nội dung chunk thì phải tính lại embedding.

## 4. Cách chia ba part và hai GPU

Chia thành sáu dải dòng liên tục, cân bằng theo tổng `token_count` nguồn. Mỗi
notebook chạy `torchrun --nproc_per_node=2`; mỗi worker có một model replica trên
một T4 và xử lý một dải riêng. Đây không phải tensor parallel chia một model.

Các số dòng bên dưới là **1-based, inclusive** trong JSONL gốc:

| Part | GPU | Input shard | Dòng đầu | Dòng cuối | Số chunk |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | 0 | `chunks-00.jsonl.zst` | 1 | 823445 | 823445 |
| 1 | 1 | `chunks-01.jsonl.zst` | 823446 | 1650491 | 827046 |
| 2 | 0 | `chunks-02.jsonl.zst` | 1650492 | 2512113 | 861622 |
| 2 | 1 | `chunks-03.jsonl.zst` | 2512114 | 3310604 | 798491 |
| 3 | 0 | `chunks-04.jsonl.zst` | 3310605 | 4136359 | 825755 |
| 3 | 1 | `chunks-05.jsonl.zst` | 4136360 | 4936835 | 800476 |
| **Tổng** | | | **1** | **4936835** | **4936835** |

Tổng mỗi part: **1650491**, **1660113**, **1626231** chunk.
Part 1 và 2 thực chạy khoảng 5 giờ 55 phút và 6 giờ 10 phút. Đây là số đo của
các lượt đã hoàn tất, không phải cam kết thời gian cho lượt chạy khác.

## 5. Hợp đồng encoder

| Thiết lập | Giá trị |
| --- | --- |
| Model ID | `Qwen/Qwen3-Embedding-0.6B` |
| Revision cố định | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` |
| Kích thước vector | `1024` |
| Kiểu chạy mô hình | `float16` / FP16 trên T4 |
| Kiểu vector xuất file | `float32` / FP32 |
| Pooling | Hidden state của token cuối; `last_token` |
| Padding | Bên trái; `left` |
| Attention | `sdpa` |
| Chuẩn hóa | L2, bằng float32 trước khi lưu |
| Văn bản tài liệu | Nguyên `content` |
| Prompt tài liệu | Chuỗi rỗng; không thêm chat template/instruction |
| Tokenize | `add_special_tokens=True`, `truncation=False` |
| Giới hạn an toàn của pipeline | `4096` token; vượt giới hạn thì báo lỗi, không cắt ngầm |
| `vector_name` trong profile | `qwen3_dense` |

`qwen3_dense` là nhãn cấu hình cho bước lưu trữ sau này. Cột Parquet thực tế có
tên **`vector`**; không có cột mang tên `qwen3_dense`.

Fingerprint encoder chung của các part:

```text
5d92039674725126e3757ac85a2fe632ed301cc19eeab4db0ddc2e6df6519087
```

`profile_id = SHA256(json.dumps(encoder, sort_keys=True).encode())` theo mã runtime.
Toàn bộ object `encoder` nằm trong manifest; nên so sánh object và fingerprint
thay vì tự tái tạo từ vài trường trong bảng trên.

Để tái lập môi trường notebook, bootstrap đã pin Transformers `4.57.1`,
Hugging Face Hub `0.36.0`, Tokenizers `0.22.1`, PyArrow `20.0.0`, Zstandard
`0.23.0`, Safetensors `0.6.2`; giữ PyTorch/CUDA có sẵn của Kaggle.
Đọc Parquet không cần tải model hoặc cài Transformers; bộ đọc dùng NumPy/PyArrow.

## 6. Cấu trúc output và file nào cần đọc

Ví dụ cấu trúc trong working của notebook Part 1:

```text
/kaggle/working/
  vibiomir_config.json
  vibiomir_embedding_runtime.py
  vibiomir_embeddings/
    part-1/
      manifest.json
      p1-gpu0-000000001.parquet
      p1-gpu0-000000001.parquet.json
      ...
      progress-gpu0.json
      progress-gpu1.json
      worker-gpu0.json
      worker-gpu1.json
      README.md
```

Sau Add Input, prefix `/kaggle/working` trở thành một đường dẫn dưới
`/kaggle/input/...`. Không hardcode tên thư mục mount hoặc username. Phần đuôi
`vibiomir_embeddings/part-N/` được giữ trong output đã kiểm chứng.

| File | Vai trò |
| --- | --- |
| `manifest.json` | Điểm bắt đầu: trạng thái, số dòng, encoder, source, danh sách Parquet chính thức |
| `pN-gpuG-XXXXXXXXX.parquet` | Dữ liệu chính: vector + ID + văn bản + metadata cùng dòng |
| `*.parquet.json` | Receipt/checkpoint: checksum và phạm vi nguồn; không phải metadata văn bản tách rời |
| `worker-gpu*.json` | Báo cáo kết quả mỗi GPU, số dòng mới/khôi phục và danh sách receipt |
| `progress-gpu*.json` | Snapshot tốc độ/ETA; không dùng để xác nhận hoàn tất |
| `README.md`, runtime, config, log | Tài liệu và thông tin tái lập; không phải bảng vector |
| `*.partial` | File chưa commit; không dùng làm kết quả hoàn tất |

Tên Parquet chứa part, GPU và **dòng nguồn đầu tiên**, ví dụ
`p1-gpu0-000000001.parquet` bắt đầu ở dòng 1. Mỗi file tối đa **8192 dòng**,
row group 1024, nén Zstandard. File cuối của mỗi GPU có thể ít dòng hơn.
Có nhiều file để lưu checkpoint theo block, tránh phải tính lại toàn bộ khi gián đoạn.

Part 1 thực có **202 Parquet**, Part 2 có **204 Parquet**. Cùng với receipt và
báo cáo, số file hiển thị khá lớn; không cộng receipt vào số file dữ liệu.
Chưa xác nhận số file thực xuất của Part 3 tại thời điểm bàn giao.

Khi tải/chuyển output, giữ thư mục riêng cho mỗi part. Không làm phẳng ba thư mục
vào một nơi gây ghi đè ba file cùng tên `manifest.json`. Giữ Parquet, manifest,
receipt và báo cáo GPU để còn kiểm tra hoặc khôi phục.

## 7. Schema Parquet chính xác

| Cột | Kiểu Arrow | Ý nghĩa |
| --- | --- | --- |
| `point_id` | `string` | UUID5 ổn định từ `chunk_id` |
| `chunk_id` | `string` | ID chunk nguyên gốc |
| `doc_id` | `int64` | ID tài liệu nguyên gốc |
| `source_line` | `int64` | Dòng 1-based trong JSONL gốc, không reset ở mỗi part |
| `source_byte` | `int64` | Offset byte 0-based trong JSONL gốc chưa nén |
| `content` | `large_string` | Văn bản được embedding, nguyên văn |
| `content_origin` | `string` | Nhãn nguồn/recovery |
| `token_count` | `int32` | Số token của bước tạo chunk nguồn |
| `input_token_count` | `int32` | Số token thực đưa vào Qwen tokenizer |
| `content_sha256` | `string` | SHA-256 UTF-8 của `content` |
| `payload_json` | `large_string` | JSON string của toàn bộ record nguồn + `_embedding` |
| `vector` | `fixed_size_list<float32>[1024]` | Vector chuẩn hóa L2 |

`payload_json` phải được `json.loads()` trước khi sử dụng như object. Đó là bản
giữ toàn bộ trường nguồn; không xây lại payload chỉ từ vài cột đang cần cho một tác vụ.

Object `_embedding` trong payload chứa đúng các trường provenance sau:

```text
source_file, source_sha256, source_line, source_byte, content_sha256,
profile_id, model_id, revision, part, gpu, input_token_count, truncated
```

`truncated` là `false`. Dimension/dtype/attention/pooling đầy đủ nằm ở encoder
trong manifest và schema metadata, không phải tất cả đều có ở từng `_embedding`.

Arrow schema metadata có key byte **`b'vibiomir_embedding'`**, value là JSON UTF-8:
`schema_version`, `encoder`, `profile_id`, `source_sha256`, `part`, `gpu`.

Offset `source_byte` chỉ dùng seek trực tiếp vào **JSONL gốc chưa nén** đúng hash;
không seek offset đó vào `.zst`. Dùng chế độ binary khi đối chiếu byte:

```python
import hashlib
import json

with open('datav3/ViBioMIR_chunks_with_recovery.jsonl', 'rb') as source:
    source.seek(row['source_byte'])
    original = json.loads(source.readline())
assert original['chunk_id'] == row['chunk_id']
assert hashlib.sha256(original['content'].encode('utf-8')).hexdigest() == row['content_sha256']
```

Đoạn này giả định `row` là một dòng Parquet đã đọc và file JSONL đúng source hash.

## 8. Manifest và receipt

Các key cấp cao của output manifest:

```text
schema_version, part, complete, rows, expected_rows,
source, encoder, profile_id, gpu_workers, files, elapsed_seconds
```

- `schema_version` phải là `vibiomir-embedding-v1`.
- `source` là manifest nguồn, chứa đủ sáu dải của ba part; điều này bình thường.
- `rows` là số dòng output; đối chiếu `expected_rows` và dải nguồn của đúng part.
- `files` là danh sách receipt. Chỉ đọc mỗi file trong danh sách này **một lần**;
  `gpu_workers[*].files` lặp lại thông tin để báo cáo, không phải bộ dữ liệu khác.
- Resolve đường dẫn bằng `manifest_path.parent / entry['file']`.
- Sắp danh sách theo `start_line` nếu cần thứ tự toàn bộ nguồn.

Receipt có các trường:

```text
file, rows, sha256, start_line, end_line, start_byte,
part, gpu, source_sha256, profile_id, min_tokens, max_tokens
```

`sha256` là hash toàn bộ file Parquet đã ghi xong. `min_tokens`/`max_tokens` là
độ dài input tokenizer trong file đó. `end_line` inclusive; số dòng phải bằng
`end_line - start_line + 1`.

## 9. Cách đọc sau Add Input

### Trên Kaggle, dùng notebook đã được chạy kiểm chứng

1. Mở [CPU Output Check](https://www.kaggle.com/code/nhminh107/vibiomir-embedding-output-check-20261025),
   Copy & Edit khi cần bản riêng.
2. Đã gắn sẵn output Part 1 và 2. Khi Part 3 hoàn tất, Add Input output version
   hoàn tất của Part 3 và đặt `REQUIRED_PARTS = [1, 2, 3]`.
3. Notebook đã nhúng bộ đọc, không cần clone repository hoặc tải encoder.
4. `catalog` chứa danh sách file đã đối chiếu manifest. Hàm
   `iter_embedding_batches(catalog, batch_size=128, columns=None)` trả về Arrow
   RecordBatch; có thể dùng tiếp cho tác vụ người dùng yêu cầu.

Mặc định hiện tại của notebook kiểm tra là `[1, 2]`. Chỉ Add Input Part 3 mà không
đổi biến này sẽ chưa đọc Part 3. Chỉ gắn một output version cho mỗi part.

### Trong repository hoặc sau khi tải output về máy

Chạy từ repository root, dùng Python environment hiện có của project. Bộ đọc:
`Scripts/Kaggle/read_vibiomir_outputs.py`.

```python
import json
from Scripts.Kaggle.read_vibiomir_outputs import (
    discover_outputs, iter_embedding_batches, verify_outputs,
)

# /kaggle/input trên Kaggle; ở máy khác thay bằng thư mục cha chứa các output.
catalog = discover_outputs('/kaggle/input', required_parts=(1, 2, 3))

# Kiểm tra toàn bộ file/vector; đọc tuần tự, không nạp toàn bộ corpus vào RAM.
report = verify_outputs(catalog, verify_checksums=True)
assert report['passed'] and catalog['rows'] == 4936835

# Ví dụ đọc MỘT batch. Với tác vụ toàn bộ corpus, lặp iterator này đến hết.
batch = next(iter_embedding_batches(catalog, batch_size=128))
vector_column = batch.column(batch.schema.get_field_index('vector'))
vectors = vector_column.flatten().to_numpy().reshape(batch.num_rows, 1024)
chunk_ids = batch.column(batch.schema.get_field_index('chunk_id')).to_pylist()
payloads = [json.loads(value) for value in
            batch.column(batch.schema.get_field_index('payload_json')).to_pylist()]
assert len(vectors) == len(chunk_ids) == len(payloads)
```

Nếu chỉ xử lý hai part đã kiểm chứng, dùng `required_parts=(1, 2)` và số dòng
mong đợi `3310604`. Đây là tập con của corpus; không đánh dấu toàn bộ corpus hoàn tất.
Hàm thư viện mặc định yêu cầu `(1, 2, 3)` nếu không truyền `required_parts`.

Giữ vector, ID và payload trên cùng batch/dòng khi lọc, sắp xếp hoặc xuất lại.
Các thao tác `read_table()`/`to_pylist()` trên toàn bộ corpus có thể tốn nhiều RAM;
ưu tiên iterator và giới hạn batch. Mảng vector FP32 toàn bộ corpus riêng nó đã
chiếm **20221276160 byte, khoảng 18,83 GiB**, chưa tính metadata/copy trung gian.

## 10. Bằng chứng kiểm tra và giới hạn

Notebook CPU ở trên đã chạy `COMPLETE` với Part 1 và 2 Add Input trực tiếp.
Report đã lưu:

```json
{
  "passed": true,
  "parts": [1, 2],
  "full_corpus": false,
  "parquet_files": 406,
  "vector_rows_checked": 3310604,
  "metadata_rows_sampled": 51968,
  "all_file_checksums_verified": true,
  "dimension": 1024,
  "dtype": "float32",
  "normalized": true
}
```

`full_corpus: false` ở report này là đúng: chỉ hai trong ba part được gắn.
Report đầy đủ còn ghi `source_sha256` và `profile_id` trùng các giá trị trong tài liệu.

Phạm vi kiểm tra:

- Kiểm tra source/profile giữa các part, file tồn tại, schema, số dòng và dải
  nguồn của **mọi file** được manifest liệt kê.
- SHA-256 **mọi file Parquet** của Part 1 và 2.
- **Toàn bộ 3.310.604 vector**: không NaN/Inf, chuẩn L2 trong tolerance `2e-5`,
  source line liên tục và đúng thứ tự.
- **128 dòng đầu mỗi Parquet**, tổng 51.968 dòng: đối chiếu ID, UUID, nội dung,
  content hash và provenance. Không diễn giải thành kiểm tra semantic metadata
  trên mọi dòng hoặc đánh giá chất lượng retrieval.
- Tính duy nhất `chunk_id` toàn bộ nguồn đã kiểm tra tại bước chuẩn bị; lượt CPU
  không chạy lại phép kiểm tra duy nhất toàn bộ ID.

Khi Part 3 hoàn tất, cần chạy lại kiểm tra với đủ ba output trước khi công bố bộ
vector đầy đủ hoặc nạp toàn corpus. Handoff này không xác nhận Part 3 đã hoàn tất.

## 11. Mã nguồn, artifact và các chỗ dễ dùng nhầm

Mọi đường dẫn dưới đây tương đối với repository root.

| Đường dẫn | Vai trò/giới hạn |
| --- | --- |
| `Scripts/Kaggle/vibiomir_embedding_runtime.py` | Mã encoder/writer/receipt; nguồn chính để hiểu dữ liệu được tạo thế nào |
| `Scripts/Kaggle/read_vibiomir_outputs.py` | Bộ đọc/kiểm tra đã chạy trên Add Input; hỗ trợ danh sách part yêu cầu |
| `Scripts/Kaggle/prepare_vibiomir_embeddings.py` | Chia input và đóng gói notebook; không cần chạy lại khi chỉ sử dụng output |
| `Scripts/Kaggle/publish_vibiomir_embeddings.py` | Công cụ xuất bản; `publish` có thể chạy GPU, không gọi để chỉ đọc dữ liệu |
| `BackEnd/app/Database/Notebook/ViBioMIR_Qwen3_06B_Part{1,2,3}_T4x2.ipynb` | Bản local của các notebook embedding; đối chiếu version remote nếu đã có chỉnh sửa |
| `Scripts/Kaggle/import_vibiomir_qdrant.py` | **Script cũ còn yêu cầu đúng 2 part và toàn nguồn. Không dùng nguyên trạng cho bộ 3 part hiện tại** |
| `artifacts/vibiomir-qwen3-3parts-20261024/dataset/source_manifest.json` | Manifest nguồn chính thức của phương án 3 part |
| `artifacts/vibiomir-qwen3-3parts-20261024/output-audit-20261025/report/verification_report.json` | Report Add Input đã PASS cho Part 1 và 2 |
| `artifacts/vibiomir-qwen3-3parts-20261024/output-audit-20261025/kernel/Verify_ViBioMIR_Outputs.ipynb` | Bản local notebook CPU kiểm tra |
| `artifacts/vibiomir-qwen3-3parts-20261024/part-3-launch-20261025/launch-receipt.json` | Bằng chứng khởi chạy Part 3 version 3 |
| `artifacts/vibiomir-qwen3-3parts-20261024/publish-receipt.json` | Lịch sử publish; mục Part 3 còn ghi quick-save version 1, không dùng riêng file này để suy ra lượt chạy mới nhất |
| `artifacts/vibiomir-qwen3-20261024/` | Artifact phương án **2 part ban đầu**, đã được thay thế; không trộn input với bộ 3 part |

README tổng quát và một số gói bàn giao cũ có hướng dẫn tự upload phần 3. Luồng
hiện dùng notebook/dataset đã có trên Kaggle. Tài liệu này và output manifest ưu
tiên khi mô tả hợp đồng dữ liệu; trạng thái thực tế ưu tiên kiểm tra version live.

## 12. Nguyên tắc cho công việc tiếp theo

1. Xác định người dùng yêu cầu tập con hay toàn bộ corpus; kiểm tra đúng danh sách part.
2. Xác nhận version output, `complete`, counts, source hash và encoder profile.
3. Đọc theo manifest/batch; bảo toàn ID, vector và payload cùng dòng.
4. Tạo kết quả mới ở vị trí riêng, giữ output embedding gốc làm nguồn đối chiếu.
5. Nếu làm retrieval, query encoder phải tương thích model/revision/pooling/
   normalize/dimension của bộ này. Query vector GTE/BGE của các pipeline khác
   trong repository không thể coi là tương thích chỉ dựa vào số chiều.
6. Nếu người dùng yêu cầu Qdrant sau này, dùng `point_id` làm ID ổn định và object
   giải mã từ `payload_json` làm nền payload; giữ provenance. Adapt bộ đọc cho đủ
   ba part trước, không gọi importer cũ rồi bỏ qua lỗi số part/số dòng.
7. Báo rõ phạm vi đã xử lý/kiểm tra và trạng thái part còn thiếu. Không chạy lại
   embedding chỉ để đổi tên, gom file hoặc làm gọn giao diện Output.
