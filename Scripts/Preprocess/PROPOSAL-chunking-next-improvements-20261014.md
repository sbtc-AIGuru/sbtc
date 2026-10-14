# Tổng hợp đánh giá và đề xuất cải tiến chunking

Ngày: 2026-10-14. Trạng thái: đề xuất để review; chưa thay đổi thuật toán.

## Căn cứ và phạm vi số liệu

- Code hiện tại: `format_profiles.py`, `format_chunking.py`, `chunk_cli.py`, `chunk_audit.py`, `../Clawler/verbatim.py`.
- Format-v2 test: `data_final/chunks_format_v2_test20k/checkpoint.json`; chỉ phân tích output đã được sinh từ `data_final/test_20k.jsonl`.
- So sánh hybrid/format: `REPORT-format-aware-chunking-v1.md`, trên cùng tập test20k nhưng parent/chunk boundaries khác nhau.
- Các ca profile/TOC/link trong full corpus: báo cáo lịch sử `REPORT-chunks-format-final-review-20261014.md`; không phải lần chạy v2 toàn corpus mới.
- Diagnostic tính lại từ output test: `tasks/chunk-quality-update-20261014/review-synthesis-metrics.json`.

`unit` là đơn vị nội bộ của `count_units()`. Overlap 30–50 giữa hai chunk kề nhau khác với overlap LCS giữa chunk nộp và nhãn tham chiếu trong `sbtc/asked.md`. Không suy ra F2 từ tỷ lệ overlap giữa hai chunk.

## 1. Nhận xét từng đánh giá

### 1.1. Overlap lý tưởng giảm: đúng số liệu xu hướng, cần giải thích đầy đủ

Report format-v1 ghi 59,05%, hybrid 83,50%; candidate format-v2 là **59,04%** trên 34.706 chuyển tiếp trong cùng parent. Con số 59,7% không khớp các artefact này.

| Overlap trong cùng parent, format-v2 | Số chuyển tiếp | Ý nghĩa |
|---|---:|---|
| 0 | 4.411 | Không có suffix atom đủ chỗ trong budget tiếp theo |
| 1–29 units | 4.638 | Có context nhưng dưới mục tiêu |
| 30–50 units | 20.489 | Đạt mục tiêu nội bộ |
| >50 units | 5.168 | Giữ nguyên atom dài hơn mục tiêu |

Tỷ lệ có overlap bất kỳ là **87,29%**. Whole-atom overlap là một nguyên nhân chính, nhưng packing hiện còn chọn body trước rồi mới dùng phần budget còn lại để lấy overlap. Đó là một lựa chọn triển khai có thể tối ưu thêm. Một atom suffix dài 70 units không thể trở thành overlap 30–50 nếu giữ nguyên atom; kể cả giảm body để chứa nó, chỉ số lý tưởng vẫn không tăng.

Overlap lấy từ suffix của chunk trước, không phải câu bất kỳ phía sau. Các chuyển tiếp qua parent/semantic boundary không nằm trong mẫu số này. Hybrid có 30.929 parents, format-v1 có 27.778; tỷ lệ dùng cùng công thức nhưng không đo đúng cùng một tập ranh giới. Hybrid từng có 38 flags cắt numeric expression theo scanner độc lập và nhiều delimiter flags hơn; không chọn hybrid chỉ vì tỷ lệ overlap đẹp hơn.

**Kết luận:** đây chủ yếu là đánh đổi giữa budget, context lặp và biên atom. Nên thử cải thiện packing; chưa có bằng chứng cần ép về 83,5%.

### 1.2. Profile chưa chính xác: false positive có thật, tỷ lệ uncertainty không đo accuracy

Trong report full corpus, narrative chiếm 67,59% và generic 0,10%; tỷ lệ uncertainty khoảng 67,7% phù hợp với cách gắn confidence thấp cho fallback. V2 test20k có **13.068/19.898 = 65,67%** record `ok` bị gắn `uncertain_format`. Đây không phải tỷ lệ phân loại sai.

Router hiện nhận catalogue khi có ít nhất ba loại field ngắn hoặc template đặc hiệu. Các heading phổ biến của một bài sức khỏe có thể thỏa điều kiện này. Report lịch sử nêu 5/7 mẫu catalogue là bài phổ thông, gồm `doc_id=669126`, `744228`, `98656`, `276743`, `127377`. Mẫu nhỏ này là bằng chứng lỗi có tồn tại, không phải ước lượng false-positive rate toàn corpus.

Router research hiện nhận khi có **ít nhất hai lần khớp nhãn**, hoặc domain PubMed. Một từ “Outcomes” xuất hiện đúng một lần không đủ tự kích hoạt. Điều kiện hiện đếm số lần, chưa yêu cầu hai loại nhãn khác nhau, chưa phân biệt body và references. Vì vậy nhận xét về nhãn nghiên cứu trong tài liệu tham khảo là hợp lý; giải thích chỉ do một từ đơn lẻ còn thiếu căn cứ. Ca `doc_id=763103` trong report lịch sử nên được truy vết evidence cụ thể trước khi sửa.

Các ca lịch sử 5 catalogue, 3 research và link `2534375` đều không có trong test20k hiện tại. Chưa tái xác nhận các ca này bằng output v2; code routing liên quan vẫn cho thấy nguy cơ đó. Việc kiểm thử cải tiến phải tìm ca tương tự trong fixture đang được phép dùng hoặc báo rõ khoảng trống bằng chứng.

**Kết luận:** nên sửa false positive bằng evidence cấu trúc. Không nâng confidence của fallback chỉ để giảm warning. Profile sai chỉ thực sự ảnh hưởng chunking khi nó làm thay đổi role, biên hoặc exclusion; cần đánh giá cả output, không chỉ tên profile.

### 1.3. TOC/link vỡ: nhiễu có thật, nguyên nhân và số lượng cần diễn giải đúng

17.657 là tổng lượt `incomplete_markdown_link` trong checkpoint full corpus cũ, không phải 17.657 URL bị hỏng. Test20k v2 có **541 lượt trên 95 records**.

Trong `verbatim.py`, warning được phát khi parser thấy label đóng nhưng target mở bằng `(` không có dấu đóng tương ứng. Dấu hiệu này chưa chứng minh HTML gốc bị cắt cụt; lỗi có thể phát sinh từ nội dung nguồn, chuyển HTML sang Markdown hoặc quá trình lưu dữ liệu. Nếu không có HTML/raw response tương ứng thì nguyên nhân chưa xác minh.

Report lịch sử ghi `doc_id=2534375` còn fragment `详细>>[[起因] 消瘦是怎么引起的？](...`. TOC đầu bài được thấy rõ ở `doc_id=763103`. Có bằng chứng nhiễu còn sót; chưa có số liệu mới để khẳng định mức phổ biến trên mọi template YouMed/Vinmec.

**Kết luận:** nên sửa theo cấu trúc và evidence. Phải phân biệt TOC điều hướng lặp với heading thật, và link hỏng với ngoặc có nghĩa trong y khoa. Parser không thể phục hồi nội dung đã thiếu bằng cách đoán.

### 1.4. Chunk dưới 50 chưa giảm: đúng, không phải toàn bộ là lỗi phân đoạn

V2 có 2.037 child dưới 50, baseline format-v1 có 2.036. Không có merge tự nhiên thỏa policy hiện tại.

| Lý do hiện được ghi cho child <50 | Số child | Hướng xử lý |
|---|---:|---|
| `short_document` | 1.537 | Review tính đầy đủ crawl khi có evidence; không thể ghép sang tài liệu khác |
| `question_context` | 352 | Giữ vai trò question riêng; dùng quan hệ question/answer ở parent khi cần context |
| `hard_boundary_region` | 139 | Review biên có thực sự cứng; không mặc định ghép |
| `whole_atom_budget_remainder` | 9 | Nhóm đáng rà trực tiếp để cân bằng hoặc ghép an toàn |

Reason là nhãn của thuật toán, không chứng minh một tài liệu ngắn đã crawl đầy đủ. Report full corpus từng có generic title-only, cần quality review riêng.

`doc_id=4057861` có câu 15-unit `然而以上结果仍需进一步深入评价。`. Ghép vào child trước 494 units thành 509, còn child sau 304 units mang role formula. Giữ riêng hiện phù hợp với budget/role đã chốt. Có thể nghiên cứu chia lại atom trước theo biên câu an toàn để đưa câu bridge vào cùng context; đó là thay đổi chính sách với atom 301–500, cần chốt riêng.

**Kết luận:** không nên ép mọi `<50` thành chunk lớn hơn. Ưu tiên 9 budget remainders và kiểm tra nguồn thiếu nội dung. Pack hiện đã có merge/rebalance tail; cần đánh giá khả năng tận dụng bước này trước khi thêm nhiều pass gộp.

## 2. Phương án và sự đánh đổi

| Vấn đề | Phương án đề xuất | Lợi ích dự kiến | Chi phí/rủi ro | Khuyến nghị |
|---|---|---|---|---|
| Nhiễu TOC | Chỉ loại khối đầu bài có marker TOC và các entry khớp heading thật ở phần body; lưu exclusion spans/evidence | Giảm keyword noise, chừa budget cho body | Loại nhầm heading hoặc mất toàn bộ nội dung trang chỉ có mục lục | Nên triển khai với positive/negative evidence rõ |
| Link Markdown thiếu target | Parser phục hồi label hiển thị nếu label/URL fragment nhận diện chắc; bounded scan theo dòng/đoạn; giữ warning khi mơ hồ | Giảm ký tự Markdown dính token, bảo toàn chữ hiển thị | Nuốt nội dung sau link hoặc sửa ngoặc có nghĩa | Nên triển khai hẹp; không dùng regex xóa rộng |
| False-positive profile | Catalogue yêu cầu template/field structure ngoài vùng TOC; research yêu cầu nhãn bổ trợ riêng biệt trong body/abstract, giữ PubMed prior cho abstract không nhãn | Giảm áp dụng sai role/exclusion | Có thể bỏ sót tài liệu hợp lệ bị mất layout | Nên triển khai; fallback an toàn và giữ evidence |
| Overlap hạn chế | Thử pack có dành budget cho suffix atom, dịch điểm kết body theo atom nếu không tạo mẩu vụn | Tăng context overlap ở những biên hiện bị thiếu chỗ | Thêm chunks/index size, lặp text, có thể giảm precision; overlap >50 vẫn bình thường | Thử trên test20k; chưa đặt làm default chỉ theo tỷ lệ lý tưởng |
| Chunk ngắn | Rà 9 remainder; cân bằng atom trong cùng region, chỉ ghép khi policy cho phép; giữ short docs/question | Giảm các mẩu thực sự thiếu context | Nới role/parent có thể ghép sai hỏi/đáp hoặc các câu trả lời độc lập | Ưu tiên thấp hơn cleaner/router; không gộp cưỡng bức |

### Các lỗi/thiếu sót kỹ thuật cần xử lý cùng đợt

- Sentence fallback của oversized repair bổ sung regex dấu chấm với guard viết tắt riêng, trong khi scanner chính dùng `_period_is_boundary()`. Nên dùng một predicate chung có guard initials, `Dr.`, `et al.`, decimal và các scientific abbreviations. Đây là nguy cơ từ code; chưa đo số lỗi thật trên fixture.
- Bổ sung metric riêng: >300, >500, unresolved, split theo clause/whitespace, warning events và affected records. `oversized_chunks` hiện đếm mọi child có `oversized_reason`, không phân biệt soft oversize và hard unresolved.
- Merge cần ca kiểm tra đi qua output/auditor và provenance tampering. Hiện test merge thành công chủ yếu gọi helper với mẩu được chia từ một atom thật trong fixture; full test run chưa có natural merge để chứng minh end-to-end path.
- Audit dựng lại cùng analyzer nên phát hiện sai hash/span/schema; nó không tự chứng minh classifier hoặc exclusion đúng ngữ nghĩa. Coverage indexed + excluded bằng source vẫn có thể đạt 100% khi một rule loại nhầm nội dung y khoa. Review positive/negative và nhãn độc lập là cần thiết.

## 3. Đặc tả phạm vi cải tiến đề nghị

### Input, output và bất biến

- Input giữ `id`, `url`, `text`, `success` hiện hành; không thay khóa nguồn.
- Output giữ parent/child mapping và chunk text là source slice sau chuẩn hóa; bổ sung evidence/metric chỉ sau khi chốt đặc tả.
- TOC exclusion giữ nguyên span/evidence trong cleaned source. Markdown recovery chỉ giữ chữ hiển thị có trong raw, không viết lại, dịch hay bổ sung chữ thiếu.
- Giữ ngân sách 150/220/300 và hard repair 500 hiện hành cho phương án đầu. Bất kỳ việc chia thêm atom 301–500, mở rộng merge qua role/parent, hay đổi schema đều cần chốt riêng.
- Source crawler/raw/final corpus và output cũ giữ nguyên. Candidate mới dùng thư mục dẫn xuất phiên bản riêng, mọi test/diagnostic chạy trên `data_final/test_20k.jsonl`.

### Điều kiện và trường hợp biên

- Bài có TOC + body đầy đủ: loại TOC lặp, giữ heading/body thật.
- Trang chỉ có index hoặc mục lục: giữ index như nội dung hạn chế, không xóa cả tài liệu vì không tìm được heading body.
- Heading bệnh/thuốc có cấu trúc thật: giữ catalogue; bài prose có ba heading phổ biến không tự được catalogue confidence cao.
- Abstract PubMed không nhãn và multilingual: giữ prior/evidence; conference programme phải được review theo format thực tế.
- Nhãn research chỉ có trong references, lặp cùng một loại hoặc trùng tên heading bài hướng dẫn: không đủ để đặt high-confidence research.
- Link target thiếu dấu đóng nhưng label rõ: giữ đúng label, bỏ markup/URL fragment chỉ khi có evidence chắc; chặn scan vượt đoạn. Link mơ hồ, nested brackets, công thức/liều lượng và citations phải giữ chữ và warning.
- Parent/role/language/excluded boundary: không dùng overlap hoặc merge để đi qua các biên đã xác nhận là cứng.
- Không có điểm cắt an toàn >500: giữ unresolved với metric/evidence riêng; không che bằng tổng oversize chung.

## 4. Nghiệm thu và thứ tự triển khai đề nghị

1. Chuẩn hóa metrics và sentence guard; tạo casebook từ test20k cho TOC, malformed links, router positives/negatives, 9 remainders. Nếu fixture không có loại ca cần thiết, báo rõ phần chưa kiểm chứng.
2. Sửa TOC/router dựa trên evidence. Kiểm tra thủ công các span bị loại và mọi record đổi profile; giữ positives phù hợp và giảm false positives trong casebook.
3. Sửa Markdown recovery trong `Scripts/Clawler/verbatim.py` như một phạm vi cleaner riêng phải được duyệt. Source SHA thay đổi là kỳ vọng của cleaning revision; kiểm tra chữ hiển thị, numeric/bracket expressions và không nuốt body. Bump cleaner version và output/checkpoint mới.
4. Thử packing có dành budget cho overlap, giữ biên atom và budget. So sánh overlap distribution, số chunk, chi phí index, short remainder, source coverage và casebook; không chỉ so phần trăm 30–50.
5. Rà riêng remainder và giữ short-doc/QA policy hiện hành trừ ca có bằng chứng để đổi.

Các thay đổi đều cần audit source mapping/span/coverage không lỗi, protected expressions đúng và có test âm cho cleaner/router. Điều kiện kiểm toán này chưa đủ để kết luận tăng Recall/F2. Khi có gold query/reference phù hợp, so retrieval với cấu hình index/model/reranker/top-K cố định và báo theo ngôn ngữ/profile. Nếu chưa có gold, chỉ nghiệm thu correctness/quality; không tuyên bố tăng điểm.

## 5. Có nên sửa không?

**Nên triển khai một đợt có phạm vi rõ cho TOC/link recovery, false-positive router, sentence guard và diagnostic metrics.** Đây là những vấn đề có evidence hoặc đường đi lỗi rõ trong code. Sửa cleaner/router cần positive/negative examples để kiểm soát mất nội dung.

**Overlap nên làm thử có đo lường**, sau các sửa chất lượng nguồn. Giữ whole-sentence/atom, không cắt đúng 40 units để đạt tỷ lệ đẹp; một overlap 70 units có thể giữ context tốt hơn một overlap 40 units cắt câu.

**Giữ các ranh giới hỏi/đáp và tài liệu ngắn.** Chỉ xử lý remainder có evidence; không đặt mục tiêu xóa sạch `<50` hay giảm uncertainty bằng đổi confidence. Các metric này phục vụ chẩn đoán, không phải score cuộc thi.
