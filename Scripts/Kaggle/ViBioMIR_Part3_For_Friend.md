# Chạy phần 3 ViBioMIR từ notebook được chia sẻ trên Kaggle

Notebook: https://www.kaggle.com/code/nhminh107/vibiomir-qwen3-06b-part3-t4x2-20261024

Dataset input đã gắn sẵn:
https://www.kaggle.com/datasets/nhminh107/vibiomir-chunks-qwen3-input-3parts-20261024

## Người sở hữu cấp quyền

Dùng Share/Sharing để cấp quyền cho bạn của bạn ở **cả notebook và dataset private**.
Kaggle quản lý hai quyền riêng biệt; chỉ chia sẻ notebook chưa đủ quyền đọc input.
Không cần tải dữ liệu xuống hoặc tạo dataset mới.

## Người nhận chạy

1. Mở notebook, chọn **Copy & Edit** để có bản chạy riêng trên tài khoản của mình.
2. Kiểm tra Input có dataset nguồn đã được cấp quyền; nếu thiếu, Add Input dataset
   ở đường dẫn trên. Chỉ gắn một bản nguồn để tránh trùng manifest.
3. Chọn **GPU T4 ×2**, bật **Internet**. Giữ `CONFIG['part'] = 3` và các cấu hình khác.
4. **Save Version → Save & Run All**. Notebook tự tìm file, không phải sửa username
   hoặc đường dẫn. Không cần GitHub, API key hay output phần 1/2.

Cell preflight kiểm tra đủ input và hai T4 trước khi tải model. Mỗi GPU giữ một
model Qwen3 Embedding 0.6B riêng. Log phải có cả GPU 0 và GPU 1 cùng tiến độ xử lý.

Encoder giống phần 1/2: FP16 khi chạy, vector lưu FP32, 1024 chiều, last-token
pooling, chuẩn L2. Giữ nguyên toàn bộ ID, nội dung và metadata nguồn.

## Gửi output lại

Kết quả nằm ở `/kaggle/working/vibiomir_embeddings/part-3/`.
Chỉ coi là hoàn tất khi `manifest.json` có:

```json
{"part": 3, "complete": true, "rows": 1626231, "expected_rows": 1626231}
```

Hai worker phải có 825.755 dòng trên GPU 0 và 800.476 dòng trên GPU 1.
Tải toàn bộ output rồi gửi lại người nhờ chạy, hoặc chia sẻ dataset/output private
cho họ. Giữ đủ Parquet, receipt `*.parquet.json`, manifest và báo cáo hai GPU.
Không chỉ gửi notebook vì notebook không chứa các vector output.

Nếu `complete: false`, giữ checkpoint. Add Input output cũ, giữ dataset nguồn,
và đặt `CONFIG['resume_roots']` thành thư mục `part-3` của output cũ rồi chạy lại.
Notebook dừng nhận block mới sau 11,25 giờ để chừa thời gian lưu output.

Quyền chia sẻ theo tài liệu Kaggle: https://www.kaggle.com/docs/notebooks
