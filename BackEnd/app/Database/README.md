# Document và Chunk trong PostgreSQL

Phần SQL nằm trong `BackEnd/app/Database`, sử dụng SQLAlchemy 2.x và Psycopg 3.
Tham khảo cách tổ chức model, engine và session từ các file PostgreSQL của
[repository mẫu](https://github.com/nhminh107/4US-1F-AIC-HCMC/tree/main/BackEnd/app/database).

## Schema

Chỉ có hai bảng `document` và `chunk`, tương ứng hai model `Document`, `Chunk`.

| Model | Dữ liệu từ `merged.json` |
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

File đầu vào phải giữ định dạng `merged.json` hiện tại: dấu `[` và `]` trên dòng
riêng, mỗi tài liệu JSON trên một dòng. Import đọc từng tài liệu và commit theo
batch, không nạp toàn bộ file 24,6 GB vào RAM.

```bash
# Thử trên một database trống riêng với 100 tài liệu.
python -m BackEnd.app.Database.import_merged --data-path data/merged.json --limit 100

# Điều chỉnh kích thước transaction.
python -m BackEnd.app.Database.import_merged \
  --data-path data/merged.json --batch-documents 100 --max-batch-chunks 5000
```

Một tài liệu luôn được import cùng toàn bộ children trong một transaction; tài
liệu lớn có thể vượt `max-batch-chunks`. RAM phụ thuộc kích thước batch và tài
liệu lớn nhất. Các lệnh INSERT được chia thành nhóm tối đa 1.000 row.

ID trùng gây lỗi và rollback **batch đang chạy**, không ghi đè dữ liệu. Các batch
đã commit vẫn còn nếu batch sau thất bại. Không chạy lại import thử trên cùng
database rồi import đầy đủ; dùng database trống riêng cho mỗi lần. Script này
chưa cung cấp chức năng resume hoặc tự bỏ qua ID đã tồn tại.

Theo kiểm tra toàn bộ file hiện tại, nếu import đầy đủ thành công sẽ có:

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
