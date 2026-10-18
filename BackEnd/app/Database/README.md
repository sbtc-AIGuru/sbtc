# Document và Chunk trong PostgreSQL

Phần SQL nằm trong `BackEnd/app/Database`, sử dụng SQLAlchemy 2.x và Psycopg 3.
Tham khảo cách tổ chức model, engine và session từ các file PostgreSQL của
[repository mẫu](https://github.com/nhminh107/4US-1F-AIC-HCMC/tree/main/BackEnd/app/database).

## Schema

Chỉ có hai bảng `document` và `chunk`, tương ứng hai model `Document`, `Chunk`.

| Model | Dữ liệu từ `merged.json` hoặc `merged.jsonl` |
| --- | --- |
| `Document` | `doc_id`, `url`, `status`, `parents`, `strategy`, `version`, `doc_type`, `classification_reason`, `classification_confidence`, `raw_sha256`, `source_sha256`, `source_length`, `source_units`, `excluded_spans`, `coverage`, `structural_boundary_rate`, `input_line`, `reason` |
| `Chunk` | `chunk_id`, `doc_id`, `parent_id`, `chunk_order`, `start_char`, `end_char`, `chunk_text`, `unit_count`, `oversized_reason`, `boundary_type`, `short_chunk_reason`, `overlap_units`, `overlap_exception`, `retrieval_eligible` |

`Document.doc_id` là khóa chính; `Chunk.chunk_id` là khóa chính và `Chunk.doc_id`
là khóa ngoại. Không dùng URL làm khóa duy nhất, vì các tài liệu khác nhau có thể
cùng URL. Khóa ngoại chặn việc xóa document khi còn chunk.

`parents`, `excluded_spans`, `coverage`, `extra_data`, `source_fields` sử dụng
JSONB trên PostgreSQL. Toàn bộ các field bên trong mỗi parent được giữ nguyên
trong `Document.parents`; không thêm bảng Parent. `parent_id` của child được kiểm
tra với danh sách parent khi import. Những field ngoài schema được giữ trong
`extra_data`. `source_fields` giữ danh sách key gốc, phân biệt key vắng mặt và key
có giá trị JSON `null`; `source_position` giữ thứ tự của mảng `children`.

Importer giữ **mọi tài liệu và mọi child**, bao gồm `status="skipped"`, chunk rỗng
và `retrieval_eligible=false`. Các trường `reason` tùy chọn cũng được lưu.
`get_document()` khôi phục record có cấu trúc giống JSON gốc, không tự ghép
`chunk_text` để suy ra một nội dung tài liệu mới.

## Kết nối và import

Chạy từ thư mục gốc của project, trong môi trường `DL_Env`. SQLAlchemy và Psycopg
được khai báo trong `pyproject.toml`; không có lệnh tự cài thư viện khi import.
PostgreSQL server và database đích phải được chuẩn bị trước.

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/DATABASE_NAME'
python -m BackEnd.app.Database.import_merged --data-path data/merged.json
```

Thay placeholder bằng cấu hình thật trên máy, không đưa thông tin đăng nhập vào
source hoặc commit. Module đọc biến môi trường `DATABASE_URL`, không tự đọc `.env`.
URL `postgresql://...` cũng được chuyển sang driver Psycopg 3.

Importer tạo bảng chưa tồn tại bằng `Base.metadata.create_all()`, không tạo
database, xóa bảng hay migrate schema hiện có. Có thể dùng `postgre_script.sql`
để tạo schema tương đương trong database trống thay cho `init_db()`.

Script hỗ trợ `.jsonl`/`.ndjson` với mỗi dòng là một tài liệu JSON, và định dạng
`merged.json` cũ với dấu `[` và `]` trên dòng riêng, mỗi tài liệu JSON trên một
dòng. Import đọc từng tài liệu và commit theo batch, không nạp toàn bộ file vào RAM.

```bash
# Thử trên một database trống riêng với 100 tài liệu.
python -m BackEnd.app.Database.import_merged --data-path data/merged.json --limit 100

# Điều chỉnh kích thước transaction.
python -m BackEnd.app.Database.import_merged \
  --data-path data/merged.json --batch-documents 100 --max-batch-chunks 5000
```

### Import bộ dữ liệu datav2 theo từng chunk

Chạy từ `/home/nhminh/AI_Project/sbtc`, sau khi cấu hình `DATABASE_URL`:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
python -m BackEnd.app.Database.import_merged \
  --data-path /home/nhminh/AI_Project/sbtc/datav2/merged.jsonl \
  --batch-documents 100 \
  --max-batch-chunks 5000
```

Mỗi phần tử `children[]` được ghi thành **một dòng riêng trong bảng `chunk`**,
với `chunk_id` là khóa chính, `chunk_text` là nội dung và `doc_id` liên kết về
bảng `document`. Một tài liệu có nhiều children sẽ tạo nhiều dòng chunk.
Metadata mới của datav2 như `boundary_reason`, `section_paths`,
`content_languages` và `protected_span_checks` được giữ trong `chunk.extra_data`;
metadata cấp tài liệu được giữ trong các cột tương ứng hoặc `document.extra_data`.
Không lọc bỏ chunk có `retrieval_eligible=false`.

Nếu nhập vào hai bảng trống và hoàn tất toàn bộ datav2, số lượng dự kiến là
**1.220.598 document**, **4.342.218 chunk** và **1.632.801 parent** trong
`document.parents`. Có thể kiểm tra sau khi nhập:

```sql
SELECT COUNT(*) AS documents FROM document;
SELECT COUNT(*) AS chunks FROM chunk;

SELECT c.chunk_id, c.doc_id, d.url, c.parent_id, c.chunk_text,
       c.retrieval_eligible, c.extra_data
FROM chunk AS c
JOIN document AS d ON d.doc_id = c.doc_id
ORDER BY c.doc_id, c.source_position
LIMIT 10;
```

Các số lượng này áp dụng cho datav2; bộ `data/merged.json` cũ có số lượng khác.

Một tài liệu luôn được import cùng toàn bộ children trong một transaction; tài
liệu lớn có thể vượt `max-batch-chunks`. RAM phụ thuộc kích thước batch và tài
liệu lớn nhất. Các lệnh INSERT được chia thành nhóm tối đa 1.000 row.

ID trùng gây lỗi và rollback **batch đang chạy**, không ghi đè dữ liệu. Các batch
đã commit vẫn còn nếu batch sau thất bại. Không chạy lại import thử trên cùng
database rồi import đầy đủ; dùng database trống riêng cho mỗi lần. Script này
chưa cung cấp chức năng resume hoặc tự bỏ qua ID đã tồn tại.

Với bộ `data/merged.json` cũ, theo kiểm tra toàn bộ file, nếu import đầy đủ thành công sẽ có:

- **3.472.347 document**, gồm 142.164 tài liệu `skipped`.
- **19.157.144 chunk**.
- **7.383.780 parent** được giữ trong trường JSONB `Document.parents`.

## Sử dụng trong Python

```python
from pathlib import Path

from BackEnd.app.Database import PostgreManager
from BackEnd.app.Database.import_merged import iter_merged_documents

manager = PostgreManager()  # DATABASE_URL
try:
    manager.init_db()
    first_document = next(iter_merged_documents(Path("data/merged.json")))
    manager.add_document(first_document)
    restored = manager.get_document(first_document["doc_id"])
    assert restored == first_document
    chunks = manager.get_chunks_by_document(first_document["doc_id"], limit=20)
    if chunks:
        one_chunk = manager.get_chunk(chunks[0]["chunk_id"])
finally:
    manager.close()
```

Các thao tác ghi dùng `session_factory.begin()` để commit/rollback theo
transaction. Module không tạo kết nối khi chỉ import package, và không sửa FAISS
index hay các notebook hiện có.

## Kiểm tra

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
pytest -q tests/test_postgre_database.py
```

Test mặc định dùng SQLite trong RAM để kiểm tra round-trip JSON, transaction và
ràng buộc. Để kiểm tra JSONB và DDL PostgreSQL, đặt `SBTC_TEST_DATABASE_URL` tới
một **database test riêng** rồi chạy cùng lệnh. Các test tạo schema có tên riêng,
không xóa schema hiện có. Không dùng database production để chạy test.

## Truy vấn Qdrant dense và hybrid

`qdrant_db.py` cung cấp `QdrantManager`, sử dụng REST và connection pool của
`requests`. Constructor không kết nối mạng hoặc tải model. Các phương thức chỉ
đọc dữ liệu; không tạo collection, sparse index hoặc sửa snapshot.

Snapshot dense-only cũ trên VM dùng collection `sbtc_gte_multilingual`, vector
dense **không có tên**, 768 chiều, Cosine. Notebook hybrid mới dùng hai tên
`dense` và `bm25`; client nhận ra tên `dense` hoặc đọc chính xác từ manifest.
`search_dense()` dùng được với cả hai schema. `search()`
thực hiện hybrid bằng hai nhánh `prefetch` dense/sparse rồi fusion RRF mặc định;
có thể chọn `fusion="dbsf"`. Kết quả là danh sách point `{id, score, payload}`
theo thứ tự Qdrant trả về; payload mặc định chứa `chunk_text` và metadata gốc.
Score hybrid là fusion score, không phải cosine hoặc xác suất relevance.

`search()` nhận **vector đã encode**. `search_text(dense_vector, query_text)`
nhận câu hỏi cho nhánh native BM25, vẫn cần dense vector đã encode. Dense query phải
dùng đúng `Alibaba-NLP/gte-multilingual-base`, revision
`9bbca17d9273fd0d03d5725c7a4b0f6b45142062`, code revision
`40ced75c3017eb27626c9d4ea981bde21a2662f4`, CLS pooling và L2 normalization theo
manifest. Sparse query dạng `{"indices": [...], "values": [...]}` phải dùng cùng
encoder, token IDs và quy tắc trọng số với dữ liệu sparse đã index. Không chuyển
trực tiếp score/hit BM25 Lucene thành sparse query vector.

Với output notebook hybrid, nên dùng manifest để giữ đúng BM25 options:

```python
with QdrantManager.from_manifest("snapshot_manifest.json") as database:
    hits = database.search_text(dense_query_vector, query_text, top_k=20)
```

Xem hướng dẫn đầy đủ tại `Scripts/Qdrant/README_HYBRID_RESTORE.md`; notebook
đóng gói bản hướng dẫn này thành `README_RESTORE.md` cùng client và query mẫu.

```python
import json
from pathlib import Path
from BackEnd.app.Database import QdrantManager

# File do bước encode query của ứng dụng tạo: dense là mảng 768 số.
vectors = json.loads(Path("query_vectors.json").read_text(encoding="utf-8"))

with QdrantManager() as database:
    dense_hits = database.search_dense(vectors["dense"], top_k=20)

    # Chỉ chạy khi collection đã có sparse vector "bm25" được nạp dữ liệu.
    hybrid_hits = database.search(
        vectors["dense"], vectors["bm25"], top_k=20, prefetch_limit=200,
        query_filter={"must": [{"key": "source_language", "match": {"value": "vi"}}]},
    )
```

Collection dense-only cũ chưa có sparse vector. Gọi `search()` lúc này báo lỗi rõ ràng,
không tự trả dense dưới tên hybrid. Sau khi quản trị viên thêm và nạp sparse
index, gọi `refresh_collection()` hoặc tạo manager mới để cập nhật schema cache.
Chỉ khai báo sparse vector trong schema chưa đủ; cần nạp vector cho các điểm.

Cấu hình qua constructor hoặc biến môi trường:

| Biến | Mặc định |
|---|---|
| `QDRANT_URL` | `http://127.0.0.1:6333` |
| `QDRANT_COLLECTION` | `sbtc_gte_multilingual` |
| `QDRANT_DENSE_VECTOR_NAME` | Không đặt; dùng unnamed hoặc tự nhận tên `dense` |
| `QDRANT_SPARSE_VECTOR_NAME` | `bm25` |
| `QDRANT_API_KEY` | Không đặt |

Qdrant trên VM chỉ bind localhost. Nếu ứng dụng chạy trên máy cá nhân, mở tunnel
trong terminal riêng rồi đặt `QDRANT_URL=http://127.0.0.1:16333`:

```bash
ssh -N -L 127.0.0.1:16333:127.0.0.1:6333 \
  -p 58431 ezycloudx-admin@14.226.225.67
```

Kiểm tra offline, không cần Qdrant server hoặc model:

```bash
.venv/bin/python -m pytest tests/test_qdrant_db.py -q
```

Các test xác minh schema có/không có sparse, unnamed/named vectors, fusion,
filter ở cả hai nhánh, payload, native BM25 query options, validation và lỗi HTTP.
Integration snapshot/restore của notebook dùng binary thật qua
`QDRANT_TEST_BINARY` trong `tests/test_gte_qdrant.py`; test đó dùng fixture nhỏ,
không chạy embedding full hoặc đổi collection trên VM.
