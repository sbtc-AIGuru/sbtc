# Đề xuất cập nhật chất lượng chunk — 2026-10-14

**Trạng thái:** Người dùng đã duyệt Gói A. Đã triển khai `format-v2`, chạy kiểm thử và đánh giá trên riêng `data_final/test_20k.jsonl`; kết quả xem `REPORT-chunk-quality-update-20261014.md`.  
**Căn cứ:** `format_chunking.py`, `chunking.py`, `chunk_cli.py` và báo cáo rà soát `REPORT-chunks-format-final-review-20261014.md`.  
**Phạm vi dữ liệu:** Khi được duyệt, mọi kiểm tra theo yêu cầu trước đây chỉ chạy trên `data_final/test_20k.jsonl`. Không sửa `final_data.jsonl` hay ghi đè `data_final/chunks_format_final/`.

## 1. Kết luận nhanh

Ba đề xuất của người dùng đều phù hợp, nhưng cần áp dụng có điều kiện để không làm mất nội dung hoặc ghép nhầm ngữ cảnh:

1. **Trang chỉ có thông báo lỗi crawl:** loại khỏi retrieval; bản ghi dẫn xuất có `text: ""`, `status: "skipped"`, lý do lỗi có mã riêng, không tạo child rỗng. Giữ `doc_id` và `url` để truy vết. Lỗi gốc trong dữ liệu crawl không bị sửa.
2. **Chunk vượt 500 units:** chia lại theo thứ tự ưu tiên đoạn/heading/list hoặc row → câu → mệnh đề an toàn. Giữ nguyên các lát cắt của nguồn, không viết lại. Nếu một atom đặc biệt không có điểm cắt an toàn, giữ nó thành ngoại lệ có cảnh báo và đưa vào báo cáo; không âm thầm cắt giữa liều thuốc, số liệu, tên hoặc mã.
3. **Chuỗi chunk dưới 50 units:** gộp các chunk ngắn kề nhau khi cùng parent, vùng ngữ nghĩa, vai trò và ngôn ngữ, đồng thời tổng độ dài nằm trong giới hạn. Không ép gộp qua heading, vùng bị loại, đổi vai trò hỏi/đáp, đổi ngôn ngữ hoặc biên cấu trúc cứng. Chunk đơn ngắn do tài liệu/section vốn ngắn được giữ lại và ghi lý do.

Ở đây `unit` là đơn vị của `count_units()` trong repo (đếm ký tự CJK và cụm chữ/số Latin), **không phải từ, token của mô hình hay byte**. Giữ `max_units=300` hiện tại làm ngưỡng đóng gói thông thường; 500 units là ngưỡng sửa chữa bắt buộc cho atom quá lớn. Chunk 301–500 units vẫn được thống kê/cảnh báo để quyết định bước kế tiếp, không tự động bẻ câu nếu không cần.

## 2. Bằng chứng và vấn đề ngoài ba yêu cầu

Các con số dưới đây là từ lần rà soát toàn bộ output hiện tại; ví dụ mẫu được nêu trong báo cáo đã lưu. Các tỷ lệ đánh giá profile là tỷ lệ trong mẫu nhỏ, không được hiểu là precision toàn corpus.

| Vấn đề | Bằng chứng trong output | Đánh giá |
|---|---|---|
| Thông báo lỗi lọt vào nội dung | 52 record chỉ có mẫu `Crawl4AI Error: This page is not fully supported...`; cả 52 được ghi `ok` và có chunk. `doc_id=128520` trỏ HelloBacsi, chunk duy nhất dài 81 units nhưng là thông báo lỗi. | Lỗi chất lượng nghiêm trọng: index sẽ coi lỗi crawler là tài liệu y khoa. |
| Atom/chunk quá lớn | 1.267 chunk trên 300 units; 21 chunk trên 2.000; lớn nhất `doc_id=4075884` dài 10.959 units. Atom `must_link_atom` gom nhiều heading/mục bệnh độc lập; cùng record có `damaged_bracket_review`. | Giữ toàn atom hiện tại bảo toàn nguồn nhưng không phù hợp truy hồi/index; cần fallback chia theo cấu trúc. |
| Chunk rất ngắn | 58.966 chunk dưới 50 units trong khoảng 4,31 triệu child. Nhóm `generic` trong mẫu thường là title-only, lỗi crawl hoặc mẩu định nghĩa ngắn. | Gộp chuỗi ngắn sẽ giảm mẩu vụn; gộp mù có thể trộn câu hỏi, section hoặc tài liệu vốn ngắn. |
| Nhận diện profile quá rộng | Trong mẫu rà, 5/7 mục `disease_drug_catalogue` là bài phổ thông; 3/7 `research_abstract` không phải abstract nghiên cứu. | Không dùng vài từ như “triệu chứng/nguy cơ/方法/结果” làm bằng chứng đủ mạnh. Cần tăng bằng chứng và giữ fallback khi chưa chắc. |
| Mục lục/UI và link hỏng | `doc_id=763103` có mục lục trước thân bài; `doc_id=2534375` còn fragment `详细>>[[起因]...](\n`. Báo cáo có 17.657 cảnh báo `incomplete_markdown_link`. | Nhiễu retrieval và có thể làm giảm đối sánh token; phải lọc theo bằng chứng template, không xóa rộng bằng regex. |
| Kích thước artefact | Output hiện tại khoảng 22 GiB. Metadata offset/atom/span làm artefact kiểm toán lớn hơn nhiều so với corpus nguồn. | Đáng tối ưu, nhưng đổi schema/export là quyết định riêng; không gộp vào lần sửa biên chunk đầu tiên. |

## 3. Phạm vi đề nghị

### Gói A — Sửa lỗi và chuẩn hóa biên chunk (đợt cập nhật đầu)

**A1. Nhận diện record lỗi**

- Nhận diện template lỗi crawler có dấu hiệu đặc hiệu (ví dụ tiền tố `Crawl4AI Error:` cùng nội dung mẫu đã thấy), không loại bài hợp lệ chỉ vì có từ “error/crawl” trong thân bài.
- Áp dụng cho cả record `success=false` và record `success=true` nhưng `text` chỉ là thông báo lỗi.
- Kết quả cho record không dùng được: giữ `doc_id`, `url`; đặt `status="skipped"`, `reason="crawl_error_placeholder"` hoặc lý do crawl hiện có, `text=""`, `parents=[]`, `children=[]`. Không phát child có `chunk_text=""`.
- Chỉ lưu mã nhận diện/nguyên nhân dạng metadata kiểm toán; không đưa nguyên văn thông báo lỗi vào chunk. Không recrawl URL trong thay đổi này.

**A2. Sửa chunk quá cỡ sau packing**

- Chạy bước hậu xử lý trên child sau `_pack`, ưu tiên tìm ranh giới tự nhiên gần giới hạn: heading/section/đoạn và mục danh sách/bảng; sau đó câu theo dấu câu đa ngôn ngữ; cuối cùng mệnh đề an toàn.
- Mỗi child mới là lát cắt liên tục `source[start_char:end_char]`. Giữ nguyên dấu câu, từ, số liệu, thứ tự và `doc_id`; đánh lại `chunk_order`, ID, span, overlap và metadata theo đúng lát cắt mới.
- Ngưỡng sửa tự động: child trên 500 units. Mục tiêu sau sửa là không quá 500 units, trừ `oversized_unresolved` có lý do rõ ràng khi không tìm được biên an toàn. Chunk 301–500 units được giữ nguyên ở đợt đầu và thống kê riêng.
- Khi ngoặc hỏng hoặc chưa đóng, không để một protected span kéo cả bài thành một atom khổng lồ nếu heading/đoạn độc lập đã tạo ranh giới an toàn. Ghi `split_reason`, `oversized_reason`/`oversized_unresolved` và số units trước/sau để truy vết.
- Nếu cần overlap, lấy nguyên câu/đoạn ở cùng vùng và không vượt 500 units; không chèn tiêu đề giả hay text tổng hợp vào `chunk_text`.

**A3. Gộp chunk ngắn có kiểm soát**

- Ngưỡng ngắn là `<50` units. Gộp chuỗi child ngắn liền kề trước; ưu tiên đạt ít nhất 50 units nhưng không vượt `max_units=300` nếu có thể. Không vượt 500 trong mọi trường hợp tự động.
- Chỉ gộp trong cùng `doc_id`, `parent_id`, region/section path, role và ngôn ngữ. Không qua excluded span, heading/section cứng, language span khác, hoặc ranh giới question/answer.
- Đợt này chỉ gộp chuỗi kề nhau mà từng chunk đều dưới 50 units. Không gộp một mẩu ngắn đơn lẻ vào chunk thường; mở rộng kiểu gộp đó cần đánh giá riêng vì có thể trộn vai trò hoặc vượt budget.
- Sau gộp, text vẫn lấy từ một lát cắt liên tục của source; tính lại kích thước, span, ID/thứ tự, overlap và metadata. Gắn lý do như `merge_reason="consecutive_short_chunks"`.
- Nếu mẩu ngắn không có hàng xóm hợp lệ để gộp (tài liệu ngắn, vùng cuối, Q/A boundary), giữ chunk và ghi `short_chunk_reason` có phân biệt nguyên nhân thay vì làm mất nó.

### Gói B — Giảm nhiễu phân loại/nguồn (đợt sau, cần chốt phạm vi riêng)

- Nâng ngưỡng evidence của `disease_drug_catalogue` và `research_abstract`; keyword đơn lẻ không đủ. Thêm kiểm tra negative evidence như trang hướng dẫn, xét nghiệm, danh sách tham khảo; khi chưa chắc dùng fallback `narrative/generic` cùng confidence thấp.
- Phát hiện TOC lặp và link/UI vỡ chỉ khi có bằng chứng cấu trúc/template mạnh; ghi `excluded_spans` và bảo đảm indexed + excluded coverage được kiểm toán. Không xóa chỉ vì đoạn ngắn hoặc nhiều link.
- Báo cáo nhóm `damaged_bracket_review`, `incomplete_markdown_link`, format confidence thấp; xem các ví dụ đã nêu trước khi thêm rule làm sạch.

Đề nghị triển khai **Gói A trước** để sửa ba vấn đề trực tiếp người dùng nêu và bổ sung metric chẩn đoán cho Gói B. Gói B ảnh hưởng classifier/cleaner rộng hơn, nên chỉ đưa vào cùng lần nếu người dùng duyệt rõ phạm vi; không thay đổi `boilerplate.py`/crawler trong Gói A nếu không có bằng chứng cần thiết.

### Ngoài phạm vi đợt đầu

- Không thay đổi crawler/recrawl, chuẩn hóa ngôn ngữ hoặc classifier ICD-10.
- Không đổi schema nộp bài hay xóa metadata kiểm toán trong output.
- Không ghi đè `data_final/chunks_format_final/`, `data_final/final_data.jsonl` hoặc dữ liệu crawl.
- Chưa tối ưu kích thước artefact 22 GiB; việc tách audit metadata khỏi retrieval export cần proposal riêng vì ảnh hưởng consumer/schema.
- Không tuyên bố cải thiện F2 nếu chưa có gold/reference chunk retrieval để đánh giá.

## 4. Tiêu chí nghiệm thu dự kiến

Sau khi đặc tả được duyệt và triển khai:

1. Error template đã biết tạo record skipped, text rỗng, không có parent/child; câu nội dung bình thường có từ “error” không bị đánh nhầm.
2. Chunk trên 500 units được chia ở ranh giới an toàn, đúng thứ tự, mỗi chunk là source slice nguyên bản; ngoại lệ không thể chia được phải có mã cảnh báo và bằng chứng.
3. Chuỗi chunk dưới 50 units cùng vùng được gộp theo chính sách; không gộp qua các biên cứng. Mẩu ngắn thật được giữ với lý do.
4. `doc_id`, URL, nguồn/hash, coverage, excluded spans và liên kết chunk-parent giữ nguyên tính đúng đắn; không có khoảng trống nội dung do bước mới tạo ra.
5. Báo cáo trước/sau có số record lỗi bị chuyển sang skipped, chunk >300/>500, `oversized_unresolved`, chunk <50, số lần gộp, phân bố theo profile/ngôn ngữ và số ngoại lệ.
6. Kiểm tra tích hợp chỉ dùng `data_final/test_20k.jsonl`, xuất sang thư mục dẫn xuất mới (đề nghị `data_final/chunks_format_v2_test20k/`). Chỉ sau khi người dùng xem kết quả test mới cân nhắc chạy full corpus vào thư mục phiên bản mới `data_final/chunks_format_v2/`.

## 5. Rủi ro và cách giảm

| Rủi ro | Ảnh hưởng | Cách xử lý đề xuất |
|---|---|---|
| Bắt nhầm text lỗi hợp lệ | Mất nội dung retrieval | Matcher đặc hiệu cho template; có test âm với bài viết bình thường nhắc tới lỗi. |
| Cắt câu/biểu thức y khoa | Mất ngữ cảnh hoặc đối sánh LCS | Chỉ cắt theo đoạn/câu trước; bảo vệ span số-liều-tên; ngoại lệ review nếu không có biên an toàn. |
| Gộp qua ngữ cảnh khác | Chunk trộn section/ngôn ngữ/hỏi-đáp | Ràng buộc cùng parent/region/role/ngôn ngữ và kiểm tra `source` liên tục. |
| Thay ID/thứ tự làm hỏng nối dữ liệu | Sai mapping document–chunk | Giữ `doc_id` nguyên bản; tạo lại chunk ID từ span/order; kiểm tra foreign key và thứ tự. |
| Chạy lại làm mất output hiện hành | Mất artefact đang dùng | Chỉ ghi thư mục version mới; từ chối thư mục output đã tồn tại/không rỗng theo quy tắc CLI. |

## 6. Kế hoạch triển khai (đã thực hiện)

1. Chốt phạm vi Gói A; Gói B để ngoài đợt này.
2. Giữ plan/checklist riêng để không ghi đè task plan đang có.
3. Thêm test cho matcher lỗi, split quá cỡ, merge-run và các biên bị cấm.
4. Chạy test và pipeline chỉ trên `data_final/test_20k.jsonl`, output vào thư mục phiên bản mới.
5. Audit source slice/coverage/ID và cập nhật docs/report.
6. Chỉ cân nhắc chạy toàn corpus sau khi người dùng review kết quả test.

## 7. Phạm vi đã chốt

Người dùng đã duyệt phương án **Gói A**, với ngưỡng 500 units là hard repair threshold, 300 units là mục tiêu đóng gói, merge dưới 50 chỉ trong cùng semantic region; chạy thử trên `test_20k.jsonl` và không ghi đè output hiện tại. Gói B (profile, TOC/UI và link hỏng) vẫn ngoài phạm vi implementation này.

## 8. Kết quả sau khi triển khai

- Không còn child trên 500 units trong test20k; max giảm từ 2.760 xuống 494. Hai crawl-error placeholder đã biết thành `skipped` với `text=""`.
- Auditor xác nhận 20.000 dòng, 0 lỗi; với tài liệu còn được index, số non-whitespace được phủ khớp đúng source.
- Không tìm được chuỗi chunk dưới 50 nào đủ điều kiện gộp theo cùng-parent/section/role/language. Số chunk dưới 50 là 2.036 → 2.037; vì vậy mục tiêu giảm short chunk **chưa đạt trên fixture**, dù helper và ràng buộc gộp đã được kiểm thử. Một mẩu 15-unit mới trong `doc_id=4057861` nằm giữa body và formula; không ghép vì chunk bên cạnh vượt budget hoặc đổi role.
- Không có gold retrieval labels trong fixture để đo Precision/Recall/F2; đánh giá là về cấu trúc, source preservation và ngữ nghĩa cục bộ, không phải điểm retrieval.
