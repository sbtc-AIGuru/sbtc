# Gán nhãn ngôn ngữ Chunk

Định dạng nhãn hiện hỗ trợ Việt (`vi`), Anh (`en`), Trung (`zh`). Nội dung và ID nguồn được giữ nguyên.

Quy tắc `context-script-v2.2`: chuẩn hóa NFC; nhận diện chữ Hán chiếm tỷ lệ đáng kể; với văn bản Latin, đối chiếu từ ngữ cảnh Anh với từ và ký tự đặc trưng Việt. Một chữ `é` trong `Barré`/`Sempé` không còn tự động thắng ngữ cảnh tiếng Anh. Một trích dẫn chữ Hán ngắn cũng không tự động đổi cả đoạn Việt/Anh thành Trung.

Đây là quy tắc cho ba nhãn, không phải bộ nhận diện mọi ngôn ngữ. Các đoạn thiếu bằng chứng, có thể thuộc ngôn ngữ Latin khác, hoặc phần thân song ngữ có ít nhất 20 chữ Hán dù nghiêng về tiếng Anh được đánh dấu cần rà soát. Khi sửa bảng nhãn có sẵn, chúng giữ nhãn cũ và đi vào `review.jsonl`, không được tự động chuyển field tìm kiếm. Các đoạn chỉ gồm ASCII vẫn giữ fallback EN theo định dạng cũ; không tuyên bố tất cả các đoạn đó đã được xác nhận tiếng Anh.

Kết quả chạy mới: `output/ViBioMIR_chunk_languages.v2.jsonl`, gồm `doc_id`, `chunk_id`, `language`, giữ nguyên thứ tự nguồn. Thống kê, phiên bản quy tắc, số đoạn cần rà và checksum ở `output/ViBioMIR_chunk_languages.v2.summary.json`. Các file không có hậu tố v2 là kết quả lịch sử của quy tắc cũ, không bị ghi đè.

File nguồn hiện còn trong workspace là `output/ViBioMIR_chunks_with_recovery.jsonl.before_language.bak`; thư mục `datav3` đang trống. Truyền `--input` tường minh khi tạo nhãn mới:

```bash
.venv/bin/python Scripts/LanguageLabeling/label_chunks.py \
  --input Scripts/LanguageLabeling/output/ViBioMIR_chunks_with_recovery.jsonl.before_language.bak
```

Chạy kiểm thử:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover \
  -s Scripts/LanguageLabeling -p 'test_*.py'
```

Đối chiếu toàn bộ ID, thứ tự và checksum:

```bash
.venv/bin/python Scripts/LanguageLabeling/verify_labels.py \
  --source Scripts/LanguageLabeling/output/ViBioMIR_chunks_with_recovery.jsonl.before_language.bak \
  --labels Scripts/LanguageLabeling/output/ViBioMIR_chunk_languages.v2.jsonl \
  --report Scripts/LanguageLabeling/output/verification.v2.json
```

## Sửa nhãn đã index

Tạo bảng nhãn mới và danh sách thay đổi, không kết nối hoặc sửa database:

```bash
.venv/bin/python Scripts/LanguageLabeling/repair_labels.py plan \
  --source Scripts/LanguageLabeling/output/ViBioMIR_chunks_with_recovery.jsonl.before_language.bak \
  --old-labels Scripts/LanguageLabeling/output/ViBioMIR_chunk_languages.jsonl \
  --output artifacts/language-repair-20261027/final-v2.2
```

Thư mục kết quả chứa `plan.json`, `labels.v2.jsonl`, `changes.jsonl` và `review.jsonl`. `changes.jsonl` chỉ có các quyết định không yêu cầu rà soát. So mẫu trước khi áp dụng. Lệnh từ chối ghi đè kết quả đã tồn tại.

Sau khi được phép sửa Elasticsearch đang chạy:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python Scripts/LanguageLabeling/repair_labels.py apply \
  --output artifacts/language-repair-20261027/final-v2.2 \
  --index vibiomir_bm25
```

Lệnh kiểm tra hash quy tắc/delta, pipeline analyzer, ID, nội dung và nhãn cũ của toàn bộ chunk bị tác động trước khi ghi. Nó lưu bản ghi gốc vào `es-before.jsonl`, sau đó dùng optimistic concurrency để cập nhật `lang`, `language` nếu có, xóa các field `content_vi/en/zh` cũ và tạo đúng field mới bằng preprocessing hiện hành. Sau cập nhật, đọc lại mọi chunk bị tác động, đối chiếu cả các field không liên quan và kiểm tra tổng số bản ghi.

`es-applied.jsonl` lưu phản hồi cập nhật; `es-result.json` chỉ được tạo khi toàn bộ kiểm chứng hoàn tất. Nếu lỗi giữa chừng, dừng và kiểm tra log/bản sao trước khi chạy tiếp; không chạy đè lại một cách mù quáng. Không ghi lại nội dung gốc, chunk ID hoặc vector; không dựng lại toàn index. Qdrant hiện không có field nhãn ngôn ngữ trong payload nên không cần cập nhật Qdrant.

`apply_labels.py` là công cụ cũ ghép bảng nhãn vào một JSONL chưa có `language`; công cụ này thay file nguồn và tạo backup, không dùng trực tiếp trên bản backup lịch sử hiện tại. Các báo cáo cũ trong `output/` và log Agy vẫn giữ để truy vết lần gán nhãn ban đầu.
