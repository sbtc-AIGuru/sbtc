# Đặc tả cải thiện Hybrid Chunking v3

Trạng thái: **Đã được người dùng phê duyệt và triển khai ngày 2026-10-08**.
Kết quả kiểm chứng nằm tại `REPORT-hybrid-chunking-v3.md`. Tài liệu này đánh
giá các phát hiện trên output `paragraph-v2` và là hợp đồng hành vi cho phiên
bản v3.

## 1. Mục tiêu và phạm vi

Cải thiện đơn vị retrieval để giảm mất ngữ cảnh ở biên chunk, giảm chunk quá
ngắn có thể tránh được, xử lý paragraph quá dài và hạn chế boilerplate trong
vector index. Phiên bản mới phải tiếp tục bảo toàn `doc_id`, văn bản nguyên bản,
offset kiểm toán được, xử lý streaming và khả năng resume.

Phạm vi gồm phân đoạn câu/mệnh đề, packing và overlap, xử lý chunk ngắn, nhận
diện span boilerplate và các metric kiểm chứng. Embedding, retrieval, reranking
và sinh file nộp bài nằm ngoài phạm vi.

## 2. Giả định cần người dùng phê duyệt

1. `datacrawl/test.jsonl` tiếp tục là tập duy nhất được dùng cho phát triển,
   kiểm thử và benchmark; file này chỉ được đọc.
2. Quyết định cũ “không tách câu hoàn toàn” sẽ được thay bằng phân đoạn theo
   ranh giới câu/mệnh đề tự nhiên khi paragraph vượt giới hạn hoặc cần overlap.
3. Boilerplate không bị xóa khỏi `source_text`. Mỗi span bị loại khỏi index vẫn
   được giữ nguyên cùng offset, rule và lý do để audit hoặc bật lại.
4. Mốc 150–300 units và overlap mục tiêu 30–50 units là chuẩn thiết kế nội bộ
   của repo. `sbtc/asked.md` cho đội tự thiết kế cách phân đoạn và không nêu
   trực tiếp stride 30–50; vì vậy không mô tả đây là luật chính thức của BTC.
5. Chưa có nhãn relevance/ground truth chunk, nên metric cấu trúc chỉ dùng làm
   quality gate kỹ thuật, không được dùng để tuyên bố F2 sẽ tăng.

## 3. Đánh giá các nhận xét đã cung cấp

### 3.1. Overlap thường bằng 0

**Kết luận: đúng về lỗi cơ chế, cần sửa cách diễn giải số liệu.**

- Code hiện tại chỉ lấy trọn paragraph trước đó. Nếu paragraph đó vượt
  `overlap_units=40`, vòng lặp dừng ngay và overlap bằng 0.
- Trên output `paragraph-v2`, có 137.242 child. Nếu tính mọi child sau child
  đầu tiên của mỗi tài liệu, 50.104/119.719 child có overlap, tương đương
  **41,85%**. Nếu chỉ tính 86.384 chuyển tiếp đủ điều kiện trong cùng parent,
  tỷ lệ có overlap là **58,00%**.
- Trong 36.280 chuyển tiếp cùng parent không có overlap, 34.616 trường hợp do
  paragraph trước dài hơn 40 units; 1.664 trường hợp do thêm overlap sẽ vượt
  `max_units=300`.
- Nhận xét “hầu hết paragraph dài hơn 40 units” không đúng nếu áp dụng cho toàn
  bộ dữ liệu: chỉ 154.132/951.939 paragraph (**16,19%**) vượt 40 units. Nó đúng
  hơn khi nói riêng về paragraph nằm ngay trước các biên chunk bị mất overlap.
- Nguy cơ làm yếu embedding tại biên là hợp lý. Kết luận chắc chắn mất điểm F2
  chưa có bằng chứng: với LCS chuẩn hóa theo `|g|`, một phần ở một phía vẫn có
  thể vượt 40%, và hiện chưa có ground truth để đo ảnh hưởng thực tế.

**Quyết định đề xuất:** chấp nhận sửa bằng các atom câu/mệnh đề nguyên bản và
packing có chừa ngân sách overlap. Không đặt mục tiêu 95% trên mọi child vì
child đầu parent không có predecessor hợp lệ; metric phải nêu rõ mẫu số.

### 3.2. Chunk quá ngắn

**Kết luận: vấn đề có thật; backward merge đơn thuần chưa đủ.**

- Dải `0–49` có 9.668 chunk (**7,04%**). Dải `50–99` có 12.555 chunk
  (**9,15%**). Vì vậy tổng số chunk `<100` là **22.223 (16,19%)**, không phải
  12.555.
- 20.639/22.223 chunk `<100` nằm cuối parent; 15.589 không có chunk trước trong
  cùng parent. Chỉ 4.276 trường hợp có thể gộp trực tiếp với chunk trước trong
  cùng parent mà tổng không vượt 300 units.
- 1.968 tài liệu vốn chỉ có một chunk `<100`; trong đó 658 tài liệu `<50`.
  Không thể làm chúng dài hơn bằng backward merge mà không trộn tài liệu.
- Ba ví dụ được ghi bằng số trong slug URL, không phải `doc_id` thật. Mapping
  đúng là `d176679 → doc_id 101154`, `d198083 → doc_id 101679`, và
  `d192246 → doc_id 102077`. Đặc tả và test phải dùng `doc_id` thật.
- Lập luận `20/200 < 40%` đúng về cận trên nếu ground truth thật sự dài 200
  token. Giả định “ground truth thường dài 150–250 từ” chưa có bằng chứng trong
  repo, nên không được xem chunk ngắn là chắc chắn điểm 0.

**Quyết định đề xuất:** dùng lookahead và rebalance trước khi đóng chunk; phân
biệt chunk ngắn có thể tránh với `short_document`, `atomic_section`, `qa_atomic`
và span boilerplate. Không gộp mù qua section hoặc Q&A boundary.

### 3.3. Paragraph quá dài

**Kết luận: lỗi retrieval nghiêm trọng và có khả năng sửa cao.**

- Có 2.659 chunk `>300`, gồm 415 chunk `>500`, 59 chunk `>1.000`, cực đại
  9.289 units. Các số liệu này khớp checkpoint.
- 2.639/2.659 paragraph quá dài (**99,25%**) có ít nhất một dấu kết thúc
  câu/mệnh đề theo detector đơn giản, nên sentence fallback có tiềm năng xử lý
  phần lớn trường hợp.
- `doc_id 1429888` không phải toàn bài nằm trong đúng một chunk. Văn bản sạch
  có 12.522 ký tự/10.881 units và tạo ba child: 9, 9.289 và 1.583 units. Hai
  child sau đều quá dài; kết luận về rủi ro truncation vẫn đúng.
- Giới hạn “mọi model embedding đều 512 tokens” là khái quát quá mức. Ngưỡng
  phải đo bằng tokenizer và cấu hình của model thực tế. Custom units không
  đồng nhất với model tokens.

**Quyết định đề xuất:** cho phép tách paragraph dài theo câu rồi mệnh đề. Chỉ
cho phép vượt max khi một atom không còn ranh giới tự nhiên hợp lệ; mọi ngoại
lệ ghi `oversized_atom` và số model tokens khi model đã được chọn.

### 3.4. Boilerplate, hotline và SEO spam

**Kết luận: mẫu lỗi được xác nhận; số lượng tổng chưa thể xem là ground truth.**

- Các mẫu ở `doc_id 103925`, `2443608`, `2991145`, `942223` tồn tại trong
  source và output. Chúng có thể làm loãng embedding hoặc chiếm top-K.
- Các số 1.047/149/297/87 phụ thuộc định nghĩa regex và phạm vi match chưa đi
  kèm báo cáo, nên cần tái lập bằng detector có version trước khi dùng làm
  baseline chính thức.
- Xóa chuỗi theo keyword trên toàn tài liệu có thể làm mất nội dung y khoa hợp
  lệ, đặc biệt số điện thoại cấp cứu, hướng dẫn liên hệ, danh mục thuốc và Q&A
  ngắn có một dòng lỗi audio.
- Thay đổi trực tiếp `source_text` làm hỏng offset và provenance. Cắt toàn bộ
  chunk hỗn hợp như `doc_id 2443608` cũng làm mất câu hỏi hợp lệ đứng trước
  marker SEO.

**Quyết định đề xuất:** detector trả về span, confidence và rule. Chỉ span
high-confidence ở vùng tail hoặc sau marker cấu trúc mới mặc định không được
embed. Low-confidence vẫn được index. `source_text` và raw text không đổi.

## 4. Hành vi Hybrid v3

### 4.1. Mô hình span và provenance

- Dùng `source_text = clean_to_verbatim(raw_text)` làm nguồn offset duy nhất.
- Tạo atom theo thứ tự ưu tiên: heading/Q&A marker → paragraph/line → sentence
  → clause. Mỗi atom là exact slice `[start_char:end_char]` của `source_text`.
- Sentence boundary gồm `。！？!?；;` và dấu `.` đã loại trừ decimal, domain,
  abbreviation và các trường hợp y khoa phổ biến. Dấu đóng ngoặc/ngoặc kép đi
  cùng câu trước.
- Không thay từ, dịch, tóm tắt hoặc nối các span không liền nhau thành một
  `chunk_text`.

### 4.2. Packing và overlap

- Giá trị mặc định: min 150, target 220, max 300, overlap target 40, khoảng
  overlap mong muốn 30–50 units.
- Packer phải chừa ngân sách overlap trước khi thêm nội dung mới. Một child
  gồm trailing atom của child trước và các atom mới, vẫn là một exact slice
  liên tục và không vượt max.
- Nếu trailing sentence vượt 50, thử clause boundary. Nếu atom cuối vẫn vượt
  50, dùng một atom nguyên vẹn và ghi `overlap_exception=oversized_atom`; không
  âm thầm trả overlap 0.
- Nếu overlap làm chunk vượt max, rebalance atom mới giữa hai chunk trước khi
  giảm overlap. Nếu vẫn không thể, ghi `overlap_exception=max_capacity`.
- Không tạo overlap qua document. Qua parent boundary chỉ được thực hiện nếu
  parent span được mở rộng để cả child vẫn nằm trong đúng một parent; nếu không,
  ghi `overlap_exception=parent_boundary`.

### 4.3. Rebalance chunk ngắn

- Trước khi chốt một parent, packer nhìn trước ít nhất một atom.
- Với residual `<100`, ưu tiên theo thứ tự: phân phối lại atom từ chunk trước;
  gộp khi union `<=300`; gộp section nhỏ kề nhau vào cùng parent nếu không phá
  Q&A/heading mạnh; cuối cùng giữ nguyên và ghi lý do ngoại lệ.
- Không ép tài liệu ngắn hoặc Q&A ngắn lên 100 units bằng nội dung ngoài tài
  liệu. Các lý do hợp lệ gồm `short_document`, `qa_atomic`, `atomic_section`,
  `oversized_neighbor`, `parent_boundary`, `excluded_boilerplate`.
- Chunk `<100` không có lý do hợp lệ là lỗi audit.

### 4.4. Boilerplate và retrieval eligibility

- Detector chạy trên các span có offset và xuất:
  `rule_id`, `start_char`, `end_char`, `confidence`, `reason`,
  `retrieval_eligible`.
- Rule high-confidence ban đầu chỉ bao gồm marker SEO rõ ràng
  (`其他人还在看`, related-page tail), thông báo browser/audio đơn độc, navigation
  A–Z có mật độ link-term cao, và block booking/hotline ở tail có ít nhất hai
  tín hiệu đồng thời.
- Keyword hotline đơn lẻ, số điện thoại nằm trong nội dung y khoa, tên thuốc
  trùng navigation và Q&A ngắn hỗn hợp không được tự động loại.
- Khi marker nằm giữa một span hỗn hợp, tách tại marker: prefix hợp lệ vẫn được
  chunk/index; suffix được giữ trong `excluded_spans` hoặc child có
  `retrieval_eligible=false`.
- Audit yêu cầu hợp của span được index và span bị loại phủ toàn bộ ký tự không
  trắng của nguồn. Không có ký tự nào biến mất mà không có reason.

## 5. Output và tương thích

- Đổi version thành `paragraph-v3`; checkpoint/output v2 không được resume vào
  v3 và chunk ID thay đổi theo version.
- Giữ các trường v2. Bổ sung trên child:
  `retrieval_eligible`, `short_chunk_reason`, `overlap_units`,
  `overlap_exception`, `boundary_type`.
- Bổ sung cấp document: `excluded_spans`, tổng atom theo loại, số chunk ngắn có
  lý do, số oversized atom và histogram overlap.
- Parent/child vẫn mang `doc_id` nguyên bản. Mỗi `chunk_text` vẫn bằng chính xác
  `source_text[start_char:end_char]`.

## 6. Kiểm thử và benchmark

Mọi kiểm thử và benchmark chỉ đọc `datacrawl/test.jsonl`; output ghi vào thư
mục dẫn xuất mới.

Ca bắt buộc:

1. Regression theo `doc_id` thật: 101154, 101679, 102077, 1429888, 103925,
   2443608, 2991145, 942223.
2. Dấu chấm trong decimal, domain, abbreviation; punctuation Trung/Việt/Anh;
   ngoặc kép; câu và mệnh đề đơn vượt max.
3. Overlap paragraph ngắn/dài, thiếu capacity, parent boundary và deterministic
   output với 1 hoặc nhiều worker.
4. Residual ngắn có thể rebalance, tài liệu ngắn hợp lệ, Q&A ngắn, heading đơn,
   boilerplate tail và block hỗn hợp valid-prefix/spam-suffix.
5. Audit exact slice, `doc_id`, parent containment, coverage gồm included +
   excluded, stable ID, resume và source hash.

Benchmark v2/v3 phải báo cùng lúc:

- số chunk theo các bucket `<50`, `50–99`, `100–149`, `150–219`, `220–300`,
  `>300`;
- overlap trên hai mẫu số: mọi child sau child đầu của document và chỉ các
  chuyển tiếp đủ điều kiện trong cùng parent;
- histogram overlap units và reason của mọi overlap bằng 0;
- số chunk ngắn theo từng exception; số oversized theo atomic boundary;
- số/ký tự span bị loại theo từng rule/confidence/domain;
- throughput, peak RSS, coverage và audit errors.

## 7. Tiêu chí chấp nhận

1. `datacrawl/test.jsonl` giữ nguyên SHA-256
   `5a0036c791ea2057f8761bb49808b5b8b4dd47b8806fed0e22e789d643765583`.
2. 100% child và excluded span có `doc_id` đúng, offset hợp lệ và exact slice;
   included + excluded phủ 100% ký tự không trắng.
3. Ít nhất 95% chuyển tiếp đủ điều kiện trong cùng parent có overlap; mọi
   trường hợp còn lại có `overlap_exception`. Báo riêng tỷ lệ 30–50 units,
   không đánh tráo với tỷ lệ overlap khác 0.
4. Không còn chunk `<100` có thể rebalance mà thiếu `short_chunk_reason`.
   Tài liệu ngắn và atom cấu trúc ngắn được phép giữ nguyên với reason.
5. Không còn `oversized_paragraph`. Chunk `>300` chỉ hợp lệ khi atom câu/mệnh
   đề đơn lẻ tự nó vượt max và phải ghi `oversized_atom`.
6. Boilerplate high-confidence chỉ bị loại khỏi retrieval index, không mất khỏi
   source/audit. Trên bộ review thủ công phân tầng tối thiểu 200 span, false
   positive của nhóm high-confidence không vượt 2%.
7. Kết quả deterministic giữa worker count, resume khớp run liên tục, audit
   20.000/20.000 record không lỗi.
8. Không tuyên bố cải thiện F2 trước khi có ground truth hoặc submission/eval
   so sánh cùng retrieval pipeline.

## 8. Rủi ro khi cập nhật và khi giữ nguyên

| Lựa chọn | Lợi ích | Rủi ro chính | Kiểm soát |
|---|---|---|---|
| Giữ v2 | Provenance và vận hành đã ổn định | 41,85% overlap theo document-level; 22.223 chunk `<100`; 2.659 oversized; rác vào index | Giữ làm baseline để so sánh |
| Sentence/clause fallback | Giảm truncation và tạo overlap khả dụng | Tách sai decimal/domain/abbreviation; nhiều chunk hơn | Boundary fixtures đa ngôn ngữ, exact-slice audit |
| Rebalance chunk ngắn | Giảm slot retrieval lãng phí | Trộn section hoặc Q&A không liên quan | Strong-boundary policy và reason bắt buộc |
| Boilerplate suppression | Giảm nhiễu embedding/top-K | False positive làm mất recall | Không xóa source, confidence tier, review thủ công |
| Chuyển toàn bộ sang v3 ngay | Một pipeline duy nhất | Khó quy nguyên nhân nếu retrieval giảm | Chạy song song v2/v3 và so sánh từng thay đổi |

## 9. Ngoài phạm vi và câu hỏi mở

- Chọn tokenizer/model embedding và ngưỡng model-token sẽ thuộc đặc tả indexing.
- Chọn v3 cho production chỉ sau benchmark cấu trúc và, khi có thể, đánh giá
  retrieval/F2. Bản spec này đề xuất giữ v2 làm baseline trong giai đoạn đó.
- Cần người dùng xác nhận việc đảo quyết định cũ về sentence splitting và cho
  phép span boilerplate không được đưa vào vector index trước khi lập kế hoạch
  triển khai.
