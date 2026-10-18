# API và giao diện upload Parquet

Chạy từ thư mục gốc dự án, dùng `.venv` hiện có:

```bash
.venv/bin/python -m uvicorn BackEnd.app.api.main:app \
  --host 127.0.0.1 --port 8000 --workers 1
```

Mở **http://127.0.0.1:8000** để dùng giao diện trong `FrontEnd`.
Swagger UI: **http://127.0.0.1:8000/docs**.
Không cần Node, npm hoặc bước build frontend. Giao diện và API cùng origin.
Các dependency FastAPI/Uvicorn/python-multipart được khai báo trong
`pyproject.toml` và `uv.lock`.

## Cách sử dụng

1. Chọn hoặc kéo thả một file `.parquet`, ví dụ `query_translated.parquet`.
2. Tùy chọn **Từ dòng** / **Đến dòng**. Đây là vị trí dòng **1-based**, gồm cả
   hai đầu, không phải query ID. Để trống cả hai để chạy hết file. Chỉ nhập start
   thì chạy tới cuối; chỉ nhập end thì chạy từ dòng đầu. ID gốc vẫn được giữ.
3. Chọn số dòng mỗi batch (mặc định 16), rồi bấm **Bắt đầu xử lý**.
4. Theo dõi số dòng đã lưu. Có thể **Tạm dừng sau batch** hoặc đóng trang rồi quay
   lại. Khi tác vụ dừng/lỗi, bấm **Tiếp tục từ checkpoint**.
5. Khi hoàn tất, bấm **Tải output.zip**. ZIP chứa duy nhất `output.json` ở gốc,
   đúng schema `id`, `relevant_docs`, `relevant_chunks[{doc_id,chunk_text}]`.

Chạy một khoảng dòng chỉ tạo kết quả của khoảng đó. Bài nộp toàn bộ cuộc thi
cần xử lý tất cả các dòng. Pipeline không dịch file chỉ có truy vấn tiếng Việt:
file phải có đủ ID, query VI, English và Chinese như hợp đồng truy hồi bốn nhánh.

## Lưu trữ và checkpoint

Mỗi tác vụ có UUID và thư mục riêng, mặc định:

```text
artifacts/api-jobs/<job-id>/
  input.parquet
  state.json
  output.checkpoint.jsonl
  output.errors.json
  output.json
  output.zip
```

- Upload được sao chép theo block 1 MiB; tên file từ trình duyệt không được dùng
  làm đường dẫn lưu trữ. Kiểm tra schema/range trước khi xếp hàng chạy.
- Checkpoint lưu từng kết quả cùng vị trí dòng và chunk ID nguồn. Sau mỗi batch,
  journal được flush/fsync rồi cập nhật trạng thái đã lưu. Batch đang dở có thể
  được chạy lại; dòng đã commit không cần truy hồi lại.
- Lịch sử, file upload và checkpoint ở trên đĩa, không phụ thuộc vào tab trình
  duyệt. Đóng trang không hủy tác vụ. Khởi động lại server đánh dấu tác vụ dang
  dở thành `paused`; chọn Tiếp tục để khôi phục.
- Tạm dừng có hiệu lực tại ranh giới batch, không cắt ngang một request LLM.
  Shutdown thông thường cũng chờ batch hiện tại lưu xong. Tác vụ đang xếp hàng
  được giữ trên đĩa để tiếp tục sau lần khởi động sau.
- Lỗi từng dòng được lưu trong báo cáo lỗi; không tạo ZIP thành công giả khi
  còn dòng lỗi. Chỉ những dòng thiếu/lỗi được thử lại khi tiếp tục.
- Fingerprint kiểm tra file input, khoảng dòng và cấu hình truy hồi. Nếu đổi
  model/collection/schema, dùng tác vụ mới. Xem thêm [pipeline](../PIPELINE.md).

Server chạy một tác vụ pipeline tại một thời điểm để giới hạn tài nguyên model.
Trong từng tác vụ, pipeline vẫn dùng các worker truy hồi/LLM có giới hạn.
Khóa thư mục ngăn hai process API cùng xử lý các checkpoint. Dùng `--workers 1`;
giao diện này dành cho thao tác cục bộ, không có lớp đăng nhập nhiều người dùng.
Không dùng `--reload` khi đang chạy một batch dài.

## Cấu hình server

Giữ nguyên cấu hình Qdrant, PostgreSQL và LLM đã dùng cho pipeline. API không tạo
index, sửa database hoặc tải model. Qdrant cần hybrid GTE + BM25; GTE cần có sẵn
trong cache; LLM dùng endpoint đã cấu hình. Các biến tùy chọn bổ sung:

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `PIPELINE_JOBS_DIR` | `artifacts/api-jobs` trong dự án | Nơi lưu tác vụ |
| `PIPELINE_MAX_UPLOAD_BYTES` | `134217728` | Giới hạn upload, mặc định 128 MiB |
| `PIPELINE_DEVICE` | `cpu` | Thiết bị encoder, ví dụ `cuda:0` |
| `PIPELINE_MODEL_CACHE` | Cache trong dự án nếu có, hoặc Hugging Face cache mặc định | Nơi đã tải model GTE và code ghim revision |
| `PIPELINE_MANIFEST_PATH` | Không có | Manifest của hybrid snapshot |
| `PIPELINE_RESUME_TAG` | Chuỗi rỗng | Phiên bản dữ liệu/index khi không có manifest mới |

Thư mục tác vụ mặc định được bỏ qua trong `.gitignore`. Lỗi dịch vụ chỉ lưu loại
exception và giai đoạn xử lý; không lưu raw exception có thể chứa thông tin kết nối.

Trước khi encode, pipeline kiểm tra collection Qdrant có tồn tại và có sparse
vector BM25. Các lỗi cấu hình như `QDRANT_COLLECTION_MISSING`,
`QDRANT_HYBRID_REQUIRED`, `ENCODER_MODEL_UNAVAILABLE` hiện thông báo cụ thể trên
giao diện và dừng tác vụ ngay; không đánh dấu hàng loạt truy vấn là dữ liệu lỗi.
Sau khi sửa môi trường, tiếp tục tác vụ với cấu hình kết nối không đổi. Nếu đổi
URL/tên collection, tạo tác vụ mới để tránh trộn checkpoint khác cấu hình.

## HTTP API

| Method | Endpoint | Chức năng |
| --- | --- | --- |
| POST | `/api/jobs` | Upload multipart `file`, tùy chọn `start`, `end`, `batch_size`; trả 202 |
| GET | `/api/jobs` | Lịch sử tác vụ, mới nhất trước |
| GET | `/api/jobs/{id}` | Trạng thái, số dòng đã lưu/lỗi, URL tải kết quả |
| POST | `/api/jobs/{id}/pause` | Dừng tại checkpoint batch tiếp theo |
| POST | `/api/jobs/{id}/resume` | Xếp hàng tiếp tục tác vụ paused/failed |
| GET | `/api/jobs/{id}/download` | Tải `output.zip` khi hoàn tất; chưa xong trả 409 |
| GET | `/api/jobs/{id}/errors` | Báo cáo lỗi từng dòng nếu có |
| GET | `/api/health` | API đang hoạt động; không kiểm tra dịch vụ model/database |

```bash
curl -F 'file=@query_translated.parquet' -F start=1 -F end=20 \
  -F batch_size=8 http://127.0.0.1:8000/api/jobs
```

Các trạng thái: `queued`, `running`, `pausing`, `paused`, `failed`, `completed`.
Trình duyệt kiểm tra trạng thái mỗi hai giây (tám giây khi tab ẩn).

## Kiểm thử

```bash
.venv/bin/python -m pytest -q tests/test_api.py tests/test_pipeline.py
node --check FrontEnd/app.js
```

Tests HTTP sử dụng ASGI TestClient với pipeline thật trên Parquet nhỏ, Qdrant/LLM
transport được mock. Bao phủ upload, range, ZIP, báo cáo lỗi, tiếp tục, khôi phục
sau restart và tạm dừng đúng ranh giới batch; không chạy model hoặc truy hồi thật.
