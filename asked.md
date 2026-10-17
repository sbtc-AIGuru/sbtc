# Overview:

## Bối cảnh bài toán
Tri thức y sinh hiện nay được phân bố không đồng đều giữa các ngôn ngữ. Mặc dù nguồn dữ liệu tiếng Việt ngày càng được mở rộng, nguồn này vẫn còn hạn chế về chiều sâu và chuyên môn. Trong khi đó, tiếng Anh và tiếng Trung sở hữu kho tài nguyên y sinh đồ sộ. Sự chênh lệch này tạo ra một “khoảng cách thông tin y tế” đáng kể, khiến người dùng sử dụng tiếng Việt gặp nhiều trở ngại trong việc tiếp cận các bằng chứng y học được công bố bằng ngôn ngữ khác.

Xuất phát từ thực trạng đó, cuộc thi hướng tới xây dựng các hệ thống AI có khả năng truy hồi thông tin y sinh đa ngôn ngữ từ các nguồn tiếng Việt, tiếng Anh và tiếng Trung. Với mỗi truy vấn bằng tiếng Việt, hệ thống cần xác định các tài liệu và nội dung liên quan, không phụ thuộc vào ngôn ngữ của nguồn. Ban Tổ chức cung cấp các nguồn dữ liệu để các đội chủ động thu thập, xử lý và xây dựng cơ sở tri thức phục vụ truy hồi. Kết quả được đánh giá ở hai mức độ: tài liệu (document) và đoạn nội dung (chunk), qua đó phản ánh cả khả năng xác định đúng tài liệu liên quan và khả năng định vị chính xác phần nội dung chứa thông tin cần tìm.

Nhiệm vụ có thể được hình thức hoá như sau: Cho tập truy vấn Q = {q₁, q₂, …, qₙ} bằng tiếng Việt và tập các nguồn dữ liệu y sinh đa ngôn ngữ do Ban Tổ chức cung cấp hoặc chỉ định. Các đội tự thiết kế quy trình xây dựng cơ sở tri thức, bao gồm thu thập dữ liệu, tiền xử lý, phân đoạn, lập chỉ mục và truy xuất. Với mỗi truy vấn qᵢ, hệ thống cần tìm và xếp hạng các tài liệu hoặc nội dung liên quan từ các nguồn tiếng Việt, tiếng Anh và tiếng Trung.

## Mục tiêu cuộc thi
Các đội thi cần xây dựng hệ thống AI có khả năng:

1. Truy hồi chính xác ở cấp tài liệu
   - Xác định đúng các tài liệu liên quan đến truy vấn từ các nguồn dữ liệu y sinh đa ngôn ngữ.
   - Thực hiện truy hồi xuyên ngôn ngữ giữa tiếng Việt, tiếng Anh và tiếng Trung thay vì chỉ dựa trên so khớp từ khoá.
2. Truy hồi chính xác ở cấp đoạn nội dung
   - Xác định được các đoạn nội dung thực sự chứa thông tin y khoa liên quan đến truy vấn.
   - Cách phân đoạn tài liệu và tổ chức các đơn vị truy hồi do từng đội tự thiết kế.
3. Hiểu truy vấn y khoa bằng tiếng Việt
   - Hiểu ngôn ngữ tự nhiên tiếng Việt về các thuật ngữ, khái niệm y khoa và lâm sàng.
   - Xử lý được truy vấn chứa nhiều thông tin khác nhau trong cùng một câu hỏi.

## Các mốc thời gian quan trọng
- 01 tháng 10, 2026: Phát hành tập kiểm thử công khai (public test)
- 31 tháng 10, 2026: Hạn chót nộp bài cho tập kiểm thử công khai
- 01 tháng 11, 2026: Giai đoạn kiểm thử riêng (private test)
- 04 tháng 11, 2026: Hạn chót nộp hệ thống
- 11 tháng 11, 2026: Công bố kết quả chung cuộc
Lưu ý: Tất cả các hạn chót đều là 23:59 theo giờ Việt Nam (UTC+07:00).

## Quy định về dữ liệu bên ngoài và mô hình ngôn ngữ huấn luyện trước (PLMs)
Để đảm bảo sự công bằng trong cuộc thi, người tham gia phải cung cấp nguồn dữ liệu. Người tham gia được phép sử dụng dữ liệu từ các nguồn bên ngoài, tuy nhiên phải trích dẫn rõ ràng và cung cấp đầy đủ thông tin về nguồn gốc dữ liệu để Ban tổ chức có thể kiểm tra, xác minh khi cần thiết.

Người tham gia có thể sử dụng các mô hình ngôn ngữ huấn luyện trước và các LLM có dữ liệu huấn luyện và/hoặc mô hình được công khai (ví dụ: Hugging Face hoặc các trang tương tự), nhưng không được sử dụng các LLM có mô hình đóng (ví dụ: GPT-4o, Gemini, ...). Ngoài ra, người tham gia chỉ được sử dụng các mô hình được phát hành trước ngày 1 tháng 8 năm 2026 (giờ Việt Nam) có kích thước nhỏ hơn hoặc bằng 15B.

# evaluation:

## Phương pháp đánh giá
Hiệu suất hệ thống trên nhiệm vụ truy hồi được đánh giá ở hai cấp độ: tài liệu và đoạn nội dung, bằng các chỉ số Độ chính xác (Precision), Độ bao phủ (Recall) và F2. Các chỉ số được tính riêng cho từng truy vấn, sau đó lấy trung bình trên toàn bộ tập câu hỏi (macro-average).

### 3.1 Truy hồi tài liệu (cấp document)
Với mỗi truy vấn, gọi D là tập tài liệu được truy hồi và G là tập tài liệu liên quan theo nhãn tham chiếu.

Precision =	|D ∩ G| / |D|
Recall =	|D ∩ G| / |G|

### 3.2. Quy tắc xác định một đoạn văn bản được truy hồi đúng
Mỗi chunk đội thi nộp được đối chiếu với các đoạn tham chiếu thuộc cùng câu hỏi và cùng doc_id.

Trước khi đối chiếu, văn bản hai phía được chuẩn hóa theo các bước sau:

- Chuẩn hóa Unicode theo NFKC.
- Giải mã HTML entity, chuyển văn bản về chữ thường, gộp các khoảng trắng liên tiếp và bỏ khoảng trắng ở đầu, cuối đoạn.
Gọi c là chunk đội thi nộp và g là chunk tham chiếu. Sau bước chuẩn hóa văn bản, độ trùng khớp được tính như sau:

overlap(c,g) =	LCStokens(c,g) / |g|
Trong đó, LCStokens(c,g) là độ dài của dãy token con chung dài nhất giữa c và g, trong đó thứ tự token được giữ nguyên nhưng các token không bắt buộc phải liên tiếp.

Một chunk được tính là đúng nếu overlap với ít nhất một chunk tham chiếu đạt từ 40% trở lên.

### 3.3. Đánh giá ở cấp đoạn nội dung
Precision =	Số chunk được tính là đúng
Tổng số chunk đội thi nộp
Recall =	Số chunk tham chiếu đã được tìm thấy
Tổng số chunk tham chiếu

### 3.4. Điểm F2
Ở mỗi cấp đánh giá, với từng câu hỏi, F2 được tính từ Precision và Recall:

F2 =	5 × Precision × Recall / 
4 × Precision + Recall
Precision, Recall và F2 cuối cùng ở mỗi cấp đánh giá được tính bằng trung bình cộng giá trị tương ứng trên toàn bộ câu hỏi (macro-average).

# submition instruction:

## Dashboard kết quả
Các đội thi nộp kết quả dự đoán trực tiếp trên hệ thống Dashboard chính thức của cuộc thi. Mỗi lần nộp bài cần đảm bảo các yêu cầu sau:
- Định dạng file: kết quả được nộp dưới dạng file chuẩn theo mẫu do Ban Tổ chức quy định, với cấu trúc trường dữ liệu tuân thủ đúng đặc tả.
- Nội dung file: bao gồm kết quả trả lời cho toàn bộ câu hỏi trong bộ dữ liệu kiểm thử. Bài nộp bị thiếu câu hoặc không đúng định dạng sẽ không được đánh giá.
- Số lần nộp: mỗi đội được giới hạn số lần nộp bài mỗi ngày nhằm đảm bảo tính công bằng và tránh hiện tượng dò đáp án.

## Định dạng nộp bài
Thí sinh phải nộp file kết quả truy hồi ở định dạng .json. File phải tuân theo cấu trúc sau:
```json
[ { "id": <integer>, "relevant_docs": ["<id_tài_liệu>"], "relevant_chunks": [ { "doc_id": "<id_tài_liệu>", "chunk_text": "<nội_dung_chunk>" } ] }, ... ]
```
Trong đó:
- id: Mã định danh của câu hỏi, kiểu số nguyên (integer).
- relevant_docs: Danh sách mã định danh của các tài liệu được dự đoán là liên quan. Trong phiên bản dữ liệu đánh giá này, sử dụng trường id kiểu số nguyên trong links_corpus.parquet.
- relevant_chunks: Danh sách các đoạn nội dung được dự đoán là liên quan. Mỗi đoạn cần chỉ rõ tài liệu nguồn qua doc_id và nội dung của đoạn qua chunk_text.
- doc_id: Mã định danh của tài liệu gốc chứa đoạn nội dung, là trường id kiểu số nguyên tương ứng trong links_corpus.parquet.
- chunk_text: Nội dung của đoạn văn bản được hệ thống truy hồi từ tài liệu tương ứng với doc_id. chunk_text phải là nội dung được trích xuất từ tài liệu gốc, không phải nội dung được viết lại hoặc sinh mới bởi hệ thống.
- chunk_order: Trường tùy chọn. Nếu cung cấp, giá trị phải là số nguyên không âm. Nếu bỏ qua, hệ thống sử dụng vị trí của chunk trong mảng relevant_chunks.

### Ví dụ bài nộp:
```json
[ { "id": 1, "relevant_docs": [ "doc_id1", "doc_id2" ], "relevant_chunks": [ { "doc_id": "doc_id1", "chunk_text": "Đoạn nội dung liên quan thứ nhất được trích từ tài liệu doc_id1." }, { "doc_id": "doc_id1", "chunk_text": "Đoạn nội dung liên quan thứ hai được trích từ một vị trí khác trong tài liệu doc_id1." }, { "doc_id": "doc_id2", "chunk_text": "Đoạn nội dung liên quan được trích từ tài liệu doc_id2." } ] } ]
```
Nếu hệ thống không dự đoán được kết quả ở một mức, thí sinh vẫn phải cung cấp trường tương ứng với danh sách rỗng.
Thí sinh nộp kết quả cho toàn bộ 1.200 truy vấn đã phát hành ở cả hai giai đoạn. Hệ thống tự chọn các truy vấn thuộc public hoặc private phase để chấm; không cần biết trước cách chia phase.
Sau đó, nén file .json, vào mục My Submissions trên [leaderboard.aiguru.com.vn](https://leaderboard.aiguru.com.vn/) và tải lên file ZIP.
### Lưu ý:
- Tất cả các file kết quả phải được nén trong một file ZIP, chỉ chứa duy nhất một file (không nằm trong thư mục con).
- Xin lưu ý rằng các bài nộp bị thiếu file hoặc thiếu câu sẽ không được đánh giá và sẽ không bị tính vào số lần nộp tối đa cho phép.

## Quy định nộp bài
- Mỗi đội được phép nộp tối đa 10 bài mỗi ngày.
- Số bài nộp tối đa cho mỗi người dùng trong Vòng riêng (Private Phase) là 5 bài tổng cộng. Vì vậy, hãy chọn lựa các bài nộp ở Vòng riêng một cách cẩn thận.
- Mỗi đội cần có một tên người dùng đại diện.
- Kết quả cuối cùng sẽ không được xem là chính thức cho đến khi một bài báo mô tả phương pháp (working notes paper) với mô tả đầy đủ về các phương pháp được nộp.
- Ban Tổ chức Cuộc thi có toàn quyền, theo quyết định riêng của mình, loại bất kỳ thí sinh nào có bài nộp không tuân thủ tất cả các yêu cầu.

# Data:

## Dữ liệu cuộc thi
Nguồn dữ liệu chính thức của cuộc thi:Bạn có thể truy cập và tải toàn bộ Dataset trên HuggingFace tại đây:[Truy cập HuggingFace Dataset (ViBioMIR)](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR)
Ban Tổ chức cung cấp:
- Danh sách nguồn dữ liệu: Các liên kết trong links_corpus.parquet để các đội chủ động thu thập, xử lý và xây dựng cơ sở tri thức phục vụ truy hồi.
- Bộ dữ liệu kiểm thử (test set): Tập câu hỏi bằng tiếng Việt, được sử dụng làm căn cứ chấm điểm và đánh giá hệ thống của các đội thi.
Ban Tổ chức không cung cấp quy trình embedding/indexing sẵn có. Các đội thi được toàn quyền chủ động trong việc:
- Xây dựng hoặc lựa chọn mô hình embedding đa ngôn ngữ phù hợp với dữ liệu y học.
- Thiết kế chiến lược lập chỉ mục và tìm kiếm.
- Xây dựng cơ chế reranking, hậu xử lý.
- Các tập dữ liệu mở khác về y học mà đội thi có thể hợp pháp sử dụng để huấn luyện/đánh giá bổ trợ.

### Tập câu hỏi truy vấn
Tập câu hỏi truy vấn được cung cấp trong tệp query.parquet, gồm:
- - id: Mã định danh của truy vấn, kiểu số nguyên (integer).
- query: Nội dung truy vấn y khoa bằng tiếng Việt, kiểu chuỗi (string).
```json
{ "id": <integer>, "query": "<string>" }
```
Ví dụ:
```json
{ "id": 1, "query": "Cần làm gì đối với tình trạng tắc nghẽn đường tiết niệu do sỏi thận?" }
```

### Nguồn dữ liệu được cung cấp
Ban Tổ chức cung cấp danh sách URL của các bài viết y khoa trong tệp links_corpus.parquet, gồm:
- - id: Mã định danh của nguồn, kiểu số nguyên (integer).
- url: URL dẫn tới bài viết gốc, kiểu chuỗi (string).
```json
{ "id": <integer>, "url": "<string>" }
```
Ví dụ:
```json
{ "id": 1, "url": "https://example.com/article" }
```
Các đội tự thực hiện việc thu thập nội dung từ các URL được cung cấp, tiền xử lý, phân đoạn và xây dựng cơ sở tri thức phục vụ truy hồi.
Trong phiên bản đánh giá này, mọi nhãn tài liệu đều sử dụng trường id kiểu số nguyên có trong links_corpus.parquet. Tài liệu nằm ngoài danh sách này không được tính là nhãn dương.

### Cập nhật nguồn corpus sau Mentor Day 2 (12/10/2026)

Thông báo BTC được đội cung cấp xác định snapshot corpus dùng cho giai đoạn hiện tại là **1.194.469 URL**: tiếng Việt **714.469**, tiếng Trung **240.000**, tiếng Anh **240.000**. BTC nêu tiếng Việt giữ nguyên, tiếng Trung được rút gọn và bổ sung 240.000 URL tiếng Anh; ID tài liệu không đổi. Tệp tại `newcorpus/links_corpus_vi_en_zh.parquet` có đúng 1.194.469 dòng và SHA-256 `9e34cb4b7d6424b80ed2634ada581ea9e2d97da69c245d80bdbb31413a78e8ce`. `newcorpus/query.parquet` có cùng SHA-256 với `sbtc/data/query.parquet` (`ce13508b893bbd6b9169679d540630bc37eb5950cad08b4d5e0e5d7063670c08`), nên bộ 1.200 truy vấn cục bộ không đổi.

**Có lệch phiên bản cần BTC/đội xác nhận trước khi chuyển pipeline:** tại lần kiểm tra ngày 13/10/2026, nhánh `main` của [dataset ViBioMIR trên Hugging Face](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR) có file `links_corpus_vi_en_zh.parquet` gồm **1.220.598 URL**: tiếng Việt **740.598**, tiếng Trung **240.000**, tiếng Anh **240.000**. Bản tải đối chiếu có SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`. So với snapshot trong thông báo và thư mục `newcorpus/`, bản `main` thêm **26.129 URL `www.vinmec.com`**, không xóa ID và không đổi URL trên ID chung. Các URL thêm nằm giữa danh sách, làm thay đổi `row_index` của 487.189 ID chung; `id` vẫn là khóa định danh. Trang cuộc thi chính thức `https://leaderboard.aiguru.com.vn/competitions/15/` không truy cập được trong lần đối chiếu này. Vì vậy, `asked.md` ghi nhận cả hai snapshot; chưa coi bản `main` mới hơn là thay thế snapshot thông báo cho đến khi đội/BTC xác nhận phiên bản nộp cần dùng.

| Snapshot | Tổng URL | VI | ZH | EN | Trạng thái cục bộ |
|---|---:|---:|---:|---:|---|
| Thông báo Mentor Day 2 / `newcorpus/` | 1.194.469 | 714.469 | 240.000 | 240.000 | Đang được `data_final/` bao phủ đầy đủ theo ID và URL |
| Hugging Face `main` tại lần kiểm tra 13/10/2026 | 1.220.598 | 740.598 | 240.000 | 240.000 | Thêm 26.129 URL Vinmec; chưa hợp nhất vào dữ liệu đích |

Parquet chỉ có `id,url`, không có cột ngôn ngữ theo từng dòng. Quy tắc domain trong `sbtc/Scripts/Clawler/audit_datacrawl_vs_newcorpus.py` hiện phân loại snapshot cục bộ thành VI 735.584, ZH 218.885, EN 240.000; lệch đúng 21.115 URL giữa VI và ZH so với phân bổ BTC. Không dùng kết quả phân loại này làm chuẩn ngôn ngữ cho retrieval cho đến khi hoàn chỉnh và kiểm chứng mapping domain; các tổng theo ngôn ngữ ở bảng trên là số BTC công bố.

Thông báo cũng cập nhật lịch Stage 3: **31/10/2026** kết thúc Vòng 1, **01–10/11/2026** Vòng 2 mentoring/tối ưu sản phẩm, **11/11/2026** Demo Day. Các mốc nộp bài/kiểm thử đã có ở phần trên của tài liệu được giữ như yêu cầu submission hiện hành cho đến khi có xác nhận rằng lịch Stage 3 thay thế chúng; thông báo Mentor Day không nêu rõ thay đổi hạn nộp trên Dashboard.

# quy ddinhj chung:
**Quyền hủy bỏ, sửa đổi hoặc loại tư cách.** Ban Tổ chức Cuộc thi có toàn quyền theo quyết định riêng của mình để chấm dứt, sửa đổi hoặc tạm ngưng cuộc thi.
Khi nộp kết quả cho cuộc thi này, bạn đồng ý cho phép công bố công khai điểm số của mình tại hội thảo của Cuộc thi và trong các kỷ yếu liên quan, theo quyết định của ban tổ chức nhiệm vụ. Điểm số có thể bao gồm nhưng không giới hạn ở các đánh giá định lượng tự động và thủ công, các đánh giá định tính, cùng các chỉ số khác mà ban tổ chức nhiệm vụ cho là phù hợp. Bạn chấp nhận rằng quyết định cuối cùng về việc lựa chọn chỉ số và giá trị điểm số thuộc về ban tổ chức nhiệm vụ.
Khi tham gia cuộc thi, bạn đã chấp nhận các điều khoản và điều kiện của Điều khoản Tham gia và Thỏa thuận Sử dụng Dữ liệu của Nhiệm vụ chung R2AI2026 TRUY HỒI TÀI LIỆU Y KHOA ĐA NGÔN NGỮ, đã được gửi đến email của bạn.
Khi tham gia cuộc thi, bạn khẳng định và thừa nhận rằng bạn đồng ý tuân thủ các luật và quy định hiện hành, và bạn không được xâm phạm bất kỳ bản quyền, tài sản trí tuệ hoặc bằng sáng chế nào của bên khác đối với phần mềm bạn phát triển trong quá trình diễn ra cuộc thi, và sẽ không vi phạm bất kỳ luật và quy định hiện hành nào liên quan đến kiểm soát xuất khẩu cũng như quyền riêng tư và bảo vệ dữ liệu.
Giải thưởng phụ thuộc vào việc Ban Tổ chức Cuộc thi xem xét và xác minh tư cách hợp lệ của thí sinh cũng như sự tuân thủ các quy định này, cùng với sự tuân thủ của các bài nộp thắng giải đối với các yêu cầu nộp bài.
Người tham gia trao cho Ban Tổ chức Cuộc thi quyền sử dụng các bài nộp thắng giải cùng mã nguồn và dữ liệu được tạo ra cho và dùng để tạo ra bài nộp đó vì bất kỳ mục đích nào và không cần phê duyệt thêm.


# Lưu ý khi crawl hay tạo bản nộp bài:
I. NHỮNG YẾU TỐ BẮT BUỘC ĐỂ NỘP BÀI HỢP LỆ (SUBMISSION INTEGRITY)
Theo đặc tả của BTC, một bài nộp hợp lệ phải đáp ứng các tiêu chuẩn khắt khe:

1. id nguyên bản từ links_corpus.parquet (Primary Key bất biến)
Quy định BTC: Hệ thống chấm điểm chỉ đối chiếu nhãn dựa trên id kiểu số nguyên trong file links_corpus.parquet.
Cạm bẫy:
File links_corpus.parquet có ID chạy từ 583 đến 4.420.561 (không bắt đầu từ 0 và có nhiều ID bị khuyết).
Tuyệt đối không dùng số thứ tự dòng (row index) làm ID.
Trong mọi quá trình crawl, lưu trữ, chunking và embedding, trường id phải luôn đi kèm và được bảo toàn 100%. Nếu mất hoặc lệch mapping id, bài nộp sẽ lập tức nhận điểm 0.
2. chunk_text nguyên bản (Verbatim Text Extraction)
Quy định BTC: "chunk_text phải là nội dung được trích xuất từ tài liệu gốc, không phải nội dung được viết lại hoặc sinh mới bởi hệ thống."
Yêu cầu đối với bước crawl:
Khi bóc tách nội dung từ HTML, phải giữ nguyên văn bản gốc của bài viết (nguyên từ ngữ, cấu trúc câu).
Cấm tóm tắt (summarize), dịch lại (translate) hay dùng LLM viết lại text khi lưu vào kho chunk phục vụ nộp bài. Nếu chunk bị biến đổi, độ trùng khớp LCS tokens(c,g) sẽ tụt xuống dưới 40%
khiến chunk bị tính là sai hoàn toàn.
3. Khớp nối chính xác giữa doc_id và chunk_text
Quy tắc chấm của BTC: "Mỗi chunk đội thi nộp được đối chiếu với các đoạn tham chiếu thuộc cùng câu hỏi và cùng doc_id."
Ý nghĩa: Dù đoạn văn bạn nộp có đúng nội dung 100% nhưng gán nhầm doc_id (ví dụ do quá trình crawl lưu lẫn lộn ID giữa các bài), chunk đó vẫn bị chấm là SAI. Do đó, mỗi chunk khi sinh ra phải lưu cứng khóa ngoại doc_id.
