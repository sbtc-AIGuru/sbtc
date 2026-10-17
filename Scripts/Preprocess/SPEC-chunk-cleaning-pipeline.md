# Đặc tả mở rộng làm sạch văn bản trong pipeline chunking

Trạng thái: **Đã được người dùng duyệt và triển khai ngày 2026-10-13**.
Cleaner nghiệm thu: `verbatim-v4`.
Kết quả: [REPORT-chunk-cleaning-pipeline.md](REPORT-chunk-cleaning-pipeline.md).
Kế hoạch chi tiết: [tasks/plan.md](tasks/plan.md).
Checklist tiến độ: [tasks/todo.md](tasks/todo.md).

## 1. Mục tiêu

Mở rộng bước làm sạch chạy trước khi chunk để loại cú pháp trình bày và nhiễu
kỹ thuật một cách xác định, đồng thời bảo toàn từ ngữ, số liệu, dấu câu và thứ
tự nội dung y khoa đa ngôn ngữ. Mỗi chunk vẫn phải là lát cắt chính xác của
`source_text` đã làm sạch; không tóm tắt, dịch, viết lại hoặc tự tạo nội dung.

## 2. Hiện trạng đã khảo sát

- `chunk_document()` kiểm tra kiểu bản ghi, gọi `clean_to_verbatim(raw_text)`
  trước khi phân đoạn, rồi lưu SHA-256 của văn bản gốc và văn bản sạch. Offset
  của parent, child và span boilerplate đều quy chiếu về văn bản sạch.
- `clean_to_verbatim()` hiện xử lý entity HTML hai lượt, một số khoảng trắng
  Unicode, script/style/comment, thẻ HTML nhận diện được, link/ảnh/URL, tiêu đề,
  blockquote, bảng Markdown, emphasis, inline code và một cụm UI Long Châu.
  Các sửa chữa về mã y sinh có `_`, khoảng liều có `~`, so sánh `<`/`>` và dấu
  câu toàn giác đã được ghi trong `docs_AI.md`.
- `detect_boilerplate()` chạy sau làm sạch, trả span có offset/lý do để loại
  khỏi retrieval; nó không xóa các span khỏi `source_text`.
- `chunk_audit.py` tái tạo cleaner rồi xác minh hash, offset, lát cắt và coverage.
- Khoảng trống còn lại: cleaner dùng regex cho một phần cú pháp Markdown nên
  chưa phân biệt đầy đủ cú pháp lồng nhau, code span, link reference và markup
  lỗi; một số phép thay ký tự áp dụng rộng (ví dụ `|`) có thể đụng ký hiệu nội
  dung; chưa có metadata cho biết phiên bản cleaner và nhóm phép biến đổi đã
  xảy ra. Nguồn Markdown có grammar lồng nhau nên regex đơn giản không thể đại
  diện toàn bộ CommonMark ([CommonMark specification](https://spec.commonmark.org/current/)).

## 3. Phạm vi

### Bao gồm

1. Rà soát và hoàn thiện hợp đồng của `clean_to_verbatim()` cho nội dung
   Crawl4AI Markdown/plain text đã trích xuất.
2. Làm sạch cú pháp markup và ký tự trình bày đã nhận diện chắc chắn, giữ nội
   dung hiển thị và cấu trúc dòng/đoạn cần cho chunking.
3. Bổ sung metadata kiểm toán theo phiên bản cho lần làm sạch trong kết quả
   chunk và xác minh metadata đó bằng audit.
4. Thêm regression cases trong phạm vi cleaner/chunking, chỉ đọc dữ liệu từ
   `datacrawl/test.jsonl` theo quy tắc kiểm thử hiện hành.

### Không bao gồm

- Sửa dữ liệu đầu vào, dữ liệu crawl, corpus, shard hoặc checkpoint đã có.
- Sửa crawler, quy tắc trích xuất DOM, chiến lược chunk, boilerplate detector,
  embedding, retrieval, reranking hoặc định dạng nộp bài.
- Dịch, sửa chính tả, chuẩn hóa từ vựng, viết lại câu, xóa nội dung chỉ vì lặp
  lại hoặc suy đoán đó là quảng cáo.
- Dùng LLM hay dịch vụ bên ngoài để quyết định nội dung nào cần giữ.

## 4. Hợp đồng xử lý đề xuất

### Đầu vào

- Bản ghi chunking hợp lệ như hiện tại: `id` là `int`, `text` và `url` là
  `str`, `success` là `bool`.
- Cleaner nhận một chuỗi văn bản, không sửa chuỗi hoặc bản ghi đầu vào tại chỗ.

### Các lớp làm sạch

1. **Giải mã và markup:** Giải mã entity theo số lượt được quy định/version hóa;
   bỏ script/style/comment và thẻ HTML nhận diện chắc chắn; giữ nguyên các
   biểu thức y khoa như `< 0.05`, `pH > 7.35`, `0 < x < 10`.
2. **Markdown:** Giữ nhãn hiển thị của link và alt text ảnh, bỏ đích URL và
   marker trình bày đã nhận diện; giữ nguyên nội dung bên trong inline/fenced
   code, công thức, mã gene và văn bản trong ngoặc. Với cú pháp lỗi hoặc mơ hồ,
   ưu tiên giữ ký tự/nội dung thay vì xóa một vùng văn bản rộng.
3. **Khoảng trắng và ký tự điều khiển:** Chuẩn hóa các loại khoảng trắng đã
   xác định về dấu cách ASCII; gộp khoảng trắng ngang trên từng dòng và giới
   hạn dòng trống lặp. Chỉ bỏ ký tự vô hình/điều khiển trong danh sách được
   đặc tả và có kiểm thử; không xóa ký tự chỉ vì nó thuộc Unicode ngoài ASCII.
4. **Nhiễu giao diện đã xác nhận:** Chỉ bỏ mẫu UI có rule hẹp, có tên và có
   kiểm thử. Boilerplate có tính nội dung tiếp tục đi qua detector span riêng,
   không bị cleaner xóa khỏi nguồn.
5. **Không chuẩn hóa ngữ nghĩa:** Không lower-case, bỏ dấu, chuẩn hóa từ y khoa
   hoặc áp dụng NFKC trên toàn bộ `source_text`. NFKC là phép biến đổi văn bản,
   có thể gộp ký tự tương thích; chuẩn hóa phục vụ đối sánh của BTC không đồng
   nghĩa với việc thay đổi văn bản chunk nộp ([Unicode UAX #15](https://unicode.org/reports/tr15/)).

### Đầu ra

- Giữ tương thích: `clean_to_verbatim(text) -> str` tiếp tục trả về chuỗi sạch.
- Chunking ghi thêm object `cleaning` ở cấp document gồm tối thiểu:
  `version`, `input_sha256`, `output_sha256`, `input_chars`, `output_chars`,
  `actions` (counter theo nhóm biến đổi) và `warnings` cho markup đáng ngờ còn
  lại. Không lưu lại hoặc ghi đè văn bản gốc trong output chunk.
- `source_sha256` hiện có tiếp tục bằng hash của văn bản sạch; `chunk_text`
  vẫn phải bằng chính xác `source_text[start_char:end_char]`.
- Audit tính lại kết quả từ đúng input tương ứng, kiểm tra metadata cleaner,
  hash, offset và coverage. Chênh lệch phiên bản cleaner phải báo lỗi audit rõ
  ràng, không âm thầm so sánh bằng cleaner khác.

## 5. Quy tắc bảo toàn và trường hợp biên

- Giữ nguyên chính tả, thứ tự token, chữ hoa/thường, dấu tiếng Việt, chữ Hán,
  ký hiệu Greek, đơn vị, số thập phân, khoảng liều, mã gene/xét nghiệm, dấu
  gạch dưới nằm trong mã, dấu so sánh toán học và dấu câu fullwidth.
- Ví dụ bắt buộc không bị biến dạng: `IL_6`, `TNF_alpha`, `miR_21_5p`,
  `3~5 ngày`, `0.5~1.0 mg/kg`, `p < 0.05`, `HBeAg_positive`, `pH > 7.35`,
  `维生素C：用法．注意事项`.
- Empty/whitespace-only input tiếp tục được skip theo lý do hiện hành; crawl
  thất bại không sinh chunk. Loại/kiểu dữ liệu sai tiếp tục thành lỗi validation,
  không được tự ép sang chuỗi.
- Nếu làm sạch khiến văn bản rỗng, document được skip với lý do cụ thể. Không
  sinh chunk từ nội dung chỉ còn marker hoặc URL.
- Cleaner phải deterministic trên cùng phiên bản và đầu vào. Metadata phải
  cho phép nhận ra output được tạo bằng phiên bản nào.

## 6. Ranh giới file dự kiến

- `sbtc/Scripts/Clawler/verbatim.py`: hoàn thiện cleaner dùng chung, giữ API
  chuỗi hiện có.
- `sbtc/Scripts/Preprocess/chunking.py`: tích hợp metadata làm sạch trước khi
  tính hash/offset và chunk.
- `sbtc/Scripts/Preprocess/chunk_audit.py`: xác minh metadata cleaner mới.
- `sbtc/Scripts/Preprocess/chunk_cli.py`: đưa phiên bản cleaner vào fingerprint
  và checkpoint, kiểm tra trước recovery để tránh resume trộn hai cách làm sạch.
- `sbtc/tests/`: regression tests thuộc cleaner/chunking; dữ liệu đầu vào duy
  nhất cho thao tác test là `datacrawl/test.jsonl`.
- `docs_AI.md`: ghi quyết định thiết kế, lỗi tìm được, cách sửa và kết quả sau
  khi triển khai theo quy tắc repo.

Không thêm thư viện parser mới trong phương án khuyến nghị; giới hạn phần nhận
diện markup vào dạng Crawl4AI đang sinh ra và giữ nguyên cú pháp không chắc chắn.
Nếu cần tuân thủ đầy đủ CommonMark cho Markdown tùy ý, phải chốt riêng việc thêm
dependency vì parser chuẩn sẽ thay đổi stack và semantics của cleaner.

## 7. Tiêu chí chấp nhận

1. Các ví dụ bảo toàn ở mục 5 không mất ký tự/từ có ý nghĩa.
2. Link, ảnh, HTML thông dụng, entity, table, heading, quote, emphasis, code và
   khoảng trắng được xử lý theo đúng hợp đồng; cú pháp mơ hồ không làm mất đoạn
   y khoa xung quanh.
3. Mỗi chunk là lát cắt chính xác của cleaned source; `doc_id`, `chunk_order`,
   offset, coverage và các hash được audit.
4. Cleaning report mô tả cùng một phiên bản và được tái lập từ input.
5. Các thao tác chạy dữ liệu/test chỉ dùng `datacrawl/test.jsonl`; không ghi vào
   file dữ liệu hoặc output crawl hiện có.
6. Kết quả và mọi bug/fix được ghi vào `docs_AI.md`.

## 8. Các quyết định đã duyệt

1. Hoàn thiện cleaner dùng chung tại `sbtc/Scripts/Clawler/verbatim.py` và
   tích hợp trong module Preprocess, bảo toàn các thay đổi đang có trong workspace.
2. Dùng standard library hiện tại, xử lý bảo thủ markup của Crawl4AI và giữ
   nội dung mơ hồ. Không thêm dependency parser mới.
3. Bổ sung object `cleaning` ở cấp document để lưu phiên bản, hash, counters
   và cảnh báo; giữ API chuỗi `clean_to_verbatim(text) -> str`.
4. Chi tiết bảo vệ checkpoint/resume thuộc cùng module và cần thiết cho
   tính nhất quán source/offset. Run hoặc output lịch sử thiếu/sai phiên bản
   cleaner phải báo không thể tái lập/resume bằng phiên bản hiện tại, không
   tự sửa checkpoint và không diễn giải thành lỗi ID nguồn.
