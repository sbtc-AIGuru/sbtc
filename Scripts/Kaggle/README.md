# Truy xuất CPU trên Kaggle

Notebook: `BackEnd/app/Database/Notebook/Kaggle_Retrieval_CPU.ipynb`.
Cell đầu chứa toàn bộ cấu hình: mặc định Qwen tắt, 4 nhánh, 100 ứng viên/nhánh,
top-k 150, 2 workers, batch 8, timeout 300 giây. `LIMIT=None` chạy toàn bộ query.
Chọn CPU, bật Internet, rồi **Run All** hoặc **Save Version → Save & Run All**.
Query deadline phía Qdrant cũng được đặt theo timeout này, chừa 10 giây để client
nhận phản hồi; chỉ tăng timeout client không kéo dài deadline của server.

Notebook gói nguyên mã pipeline hiện tại, không clone repository hay đọc `.env`.
Không tải encoder GTE: dùng vector và `dense_weight` từ Parquet. Chỉ adapter lưu trữ
được thêm: Qdrant trả `chunk_id`; SQLite tra vị trí byte trong JSONL để đọc đúng
`doc_id` và `chunk_text` nguyên văn. Không sao chép 23,7 GB corpus vào SQLite/RAM.
SHA-256 nguồn phải trùng manifest của snapshot; không lọc lại corpus.
Trong cùng lượt quét tạo SQLite, corpus được sao chép nguyên byte vào temp để mọi
lần đọc ngẫu nhiên lấy từ đĩa local. Bản sao tốn thêm khoảng 22,1 GiB đĩa temp;
SQLite vị trí byte khoảng 228 MiB, cache văn bản bị giới hạn 32 MiB.

Tất cả dữ liệu lớn đặt trong `/kaggle/temp/sbtc-retrieval`: Qdrant storage, snapshot
giải nén, thư mục restore tạm, bản sao corpus, SQLite, binary, source code và cache. Chế độ
`low_memory_mode=no_populate` giữ cách đặt vector/HNSW/sparse/payload trên đĩa của
snapshot; tắt optimizer trong phiên chỉ đọc để tránh dựng lại chỉ mục.
Không đổi tham số HNSW, BM25, weighted RRF hay quy tắc chọn/export của pipeline.

Inputs tự gắn bằng `kernel-metadata.json`:

- `nhminh107/sbtc-datav2-etl-20261016` (`merged.jsonl`).
- Output `nhminh107/sbtc-gte-qdrant-snapshot-2gpu-20261017`.
- Dataset riêng tư `nhminh107/sbtc-query-embeddings-weighted-20261021` với Parquet gốc.

Kết quả trong `/kaggle/working/retrieval`: `submission.json`, `submission.zip`,
checkpoint theo query, danh sách lỗi, `run_report.json`, và log. Giữ schema hiện tại
`integer-doc-ids-v1`: ID query/doc là số nguyên; mỗi chunk có `doc_id`, `chunk_text`.
Thứ tự query theo Parquet, thứ tự tài liệu/chunk theo pipeline hiện tại.

Notebook chạy 6 kiểm tra adapter nhỏ ngay trên Kaggle, rồi đối chiếu trên 3 query.
Hai lượt truy vấn live phải giữ nguyên điểm theo từng hạng và điểm của mọi ứng viên
chung; chỉ cho phép đổi chỗ trong nhóm đồng điểm. Nếu khác ứng viên tại ngưỡng
top-k, truy vấn đối chứng lấy toàn bộ hợp ứng viên của 4 nhánh phải chứng minh mọi
ứng viên thay thế cùng điểm ngưỡng; mọi khác biệt trên ngưỡng đều bị từ chối.
Sau đó phát lại chính danh sách hit có thứ tự của lượt payload gốc,
chỉ giữ `chunk_id`, để yêu cầu JSON hydration tạo kết quả giống hệt cả nội dung và
thứ tự. Không sắp xếp lại kết quả production hoặc thay đổi tie-break của Qdrant.
Các lượt đối chiếu dùng một worker để ghép trace theo thứ tự; lượt chạy toàn bộ
vẫn dùng `WORKERS` cấu hình ở cell đầu. Cuối phiên,
kiểm tra toàn bộ ID, checkpoint, văn bản từng chunk và nội dung ZIP. Không chạy các
kiểm tra này hoặc pipeline trên máy người dùng. `PARITY_QUERIES` có thể tăng để mở
rộng đối chiếu; 3 query không phải đánh giá chất lượng relevance.
Kết quả/checkpoint/lỗi đối chiếu nằm trong `retrieval/checks/<OUTPUT_NAME>/`; nếu có
lỗi, `run_report.json` ghi rõ query và giai đoạn lỗi, log ghi HTTP status từ Qdrant.
Trace request/hit cũng được lưu tại đây để kiểm tra điểm và thứ tự ứng viên.

Trong cùng phiên, nếu truy xuất gián đoạn, chạy lại cell truy xuất với `RESUME=True`,
giữ nguyên cấu hình/đầu vào và checkpoint. Nếu đổi cấu hình, dùng `OUTPUT_NAME` mới.
Mặc định `QUERY_RETRIES=2` tự thử lại lỗi kết nối/timeout ở giai đoạn truy xuất qua
checkpoint trong cùng phiên; các query đã đạt được giữ nguyên. Lỗi dữ liệu và lỗi
khác vẫn dừng phiên và lưu báo cáo.
Phiên Kaggle mới khôi phục snapshot và tạo SQLite lại từ input; checkpoint của phiên
cũ không tự được gắn vào phiên mới. Nếu chạy lại cell restore trong phiên còn server,
dừng server cũ bằng `stop_qdrant(process, qdrant_log)` và chọn `TEMP_ROOT` mới.

Chuẩn bị lại notebook sau khi sửa pipeline (chỉ đóng gói, không kiểm thử):

```sh
.venv/bin/python Scripts/Kaggle/prepare_retrieval_notebook.py
```

Thư mục upload nằm trong `artifacts/kaggle-retrieval/{queries,kernel}`.
Kaggle CLI phải upload Parquet với `--keep-tabular` để giữ metadata/vector kiểu gốc.
