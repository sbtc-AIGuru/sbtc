# Khảo sát dữ liệu và chất lượng chunking theo format

Ngày khảo sát: 13/10/2026. Trạng thái: đã đo baseline và viết đề xuất; chưa triển khai thuật toán mới.

Đề xuất cần đọc tiếp: [SPEC-format-aware-chunking.md](SPEC-format-aware-chunking.md).
Ví dụ thật, có dòng input/output và URL: [CASEBOOK.md](research/format-audit-20261013/CASEBOOK.md).

## 1. Kết luận từ bằng chứng

Hybrid hiện tại là nền tảng tốt để phát triển: deterministic, giữ ID, offset,
exact source slice, parent/child và checkpoint. Trên test hiện tại, audit 20.000
record đạt 0 lỗi, coverage gồm phần indexed và excluded đạt 100%; chỉ 2/71.203
chunk vượt 300 custom units. Không có căn cứ để thay toàn bộ bằng LLM chunking.

Điểm cần sửa trước là quyết định biên: dấu phẩy thập phân/hàng nghìn, dấu hai
chấm trong tỷ lệ và thống kê vẫn bị dùng để cắt; có marker câu dẫn nằm cuối
parent. Sau đó cần nhận diện format và vai trò của block. URL cùng domain không
đảm bảo cùng format: PubMed có abstract nhiều ngôn ngữ và chương trình hội nghị;
Long Châu có bài diễn giải và trang bệnh có mục lục; trang Trung y có chương sách,
thuốc, trích dẫn và điều hướng.

Khuyến nghị: giữ lõi span/cleaner/streaming, bổ sung router nhận diện nội dung và
profile phân đoạn theo format. Mục tiêu chất lượng gồm đủ ngữ cảnh, biên tự
nhiên, ít nhiễu và chi phí xử lý phù hợp; số liệu size/overlap đơn lẻ không chứng
minh F2 tăng. Repo chưa có ground truth relevance để so sánh F2 cho các profile.

## 2. Phạm vi, snapshot và cách đo

- Đọc toàn bộ `data_final/final_data.jsonl` để thống kê và đối chiếu ID/URL.
  Không chạy chunking trên toàn corpus.
- Chỉ chạy chunking/audit trên `data_final/test_20k.jsonl` hiện tại. Bộ
  `datacrawl/test.jsonl` và các output cũ trong `datacrawl/` không còn trên đĩa;
  không dùng các số liệu cũ thay cho lần đo mới.
- Input test: 20.000 record, 19.900 thành công, 100 thất bại, 85 domain.
  SHA-256 `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
- Manifest đang có trên đĩa: 1.220.598 dòng, SHA-256
  `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`.
- Full corpus: SHA-256
  `46a828ab7b9e5ca28bc4094e51ce8849d2a889f01d4fa339504004bf0bdd4510`;
  1.213.768 thành công, 6.830 thất bại, 94 domain; 0 ID trùng, 0 ID ngoài
  manifest, 0 cặp ID–URL lệch, 0 record success có text rỗng.
- Chunker `paragraph-v3`, cleaner `verbatim-v4`, hybrid mặc định
  min/target/max/overlap/parent = 150/220/300/40/1200 custom units.
- Hash input test, manifest và năm file component trước/sau khớp. File nguồn
  full corpus giữ nguyên size/mtime trong các lượt đọc. Không sửa dữ liệu nguồn.

`sbtc/asked.md` vẫn có đoạn nói bản 1.220.598 chưa hợp nhất; trạng thái file trên
đĩa và `docs_AI.md` đã khác: manifest/data hiện đều 1.220.598 và khớp mapping.
Báo cáo này ghi nhận trạng thái đo trực tiếp, không sửa quy định hoặc nguồn crawl.
Trang cuộc thi chính thức không truy cập được trong lần khảo sát này; quy định
nộp và đối chiếu tiếp tục tham chiếu `sbtc/asked.md`.

## 3. Độ dài, ngôn ngữ và nhóm URL

### 3.1. Phải phân biệt ba đơn vị

- **Ký tự:** độ dài raw `text`; dùng để hiểu quy mô và hình dạng tài liệu.
- **Whitespace tokens:** `text.split()`; rất khác giữa VI/EN và ZH.
- **Custom units:** một ký tự CJK hoặc một cụm Latin/số theo `count_units()`;
  đây là ngân sách của chunker, không phải số token của embedding model.

Ví dụ toàn corpus: PubMed có median 207 whitespace tokens; Q&A Trung Quốc có
median chỉ 10 whitespace tokens dù median text dài 270 ký tự. Không được gọi
270 ký tự Trung Quốc là 270 từ, hoặc coi 300 units là 300 model tokens.
Embedding model/tokenizer chưa được chọn trong component này.

### 3.2. Độ dài toàn corpus theo nhóm URL

Độ dài trong bảng là raw ký tự, chỉ trên record success. Nhóm là quy tắc từ
domain/path phục vụ khảo sát, chưa phải nhãn format ground truth. `other_health_news`
còn chứa các website khác và một số trang Trung Quốc bị bộ sampler bỏ sót.

| Nhóm URL | Tổng URL | Success | Median ký tự | P95 ký tự | Success trong test |
|---|---:|---:|---:|---:|---:|
| Tin/bài và website khác | 623.327 | 617.846 | 2.995 | 7.668 | 4.861 |
| Bệnh viện: Medlatec/Bạch Mai/108 | 27.545 | 27.488 | 6.128 | 7.553 | 700 |
| Long Châu `/bai-viet/` | 78.075 | 78.022 | 6.094 | 8.690 | 2.508 |
| Long Châu path khác | 1.523 | 1.523 | 819 | 1.946 | 1.492 |
| Vinmec | 26.129 | 25.649 | 5.235 | 10.115 | 1.300 |
| PubMed | 240.000 | 239.974 | 1.429 | 2.417 | 4.475 |
| Bài y khoa Trung Quốc | 72.024 | 71.967 | 1.192 | 5.156 | 911 |
| Q&A: 120ask/ask.39 | 130.932 | 130.902 | 270 | 930 | 1.800 |
| Bách khoa: A-hospital/Trung y/Wujue | 11.470 | 11.463 | 1.647 | 10.098 | 1.472 |
| Sách/từ điển Trung y | 6.795 | 6.795 | 698 | 4.099 | 290 |
| Forum iiyi | 734 | 95 | 2.539 | 5.575 | 0 |
| Bệnh/triệu chứng jbk.39 | 2.033 | 2.033 | 2.432 | 8.290 | 91 |
| Baidu | 11 | 11 | 150 | 11.003 | 0 |

Nhóm cùng domain có thể chứa format khác nhau. `zhongyibaodian.net/a/124051.html`
(doc 4050109) là thuốc aspirin với 42.955 ký tự, không phải chương sách Trung y.
PubMed doc 6248072 là danh mục chương trình hội nghị, không phải một abstract
nghiên cứu thông thường.

Histogram raw ký tự trên record success:

| Dải ký tự | Toàn corpus | Test 20k |
|---|---:|---:|
| 1–299 | 96.831 | 2.994 |
| 300–799 | 125.012 | 5.025 |
| 800–2.499 | 445.085 | 6.143 |
| 2.500–5.999 | 403.811 | 3.022 |
| ≥6.000 | 143.029 | 2.716 |

Đuôi độ dài rất rộng: doc 123043, trang đặt tên bé trai trên HelloBacsi, có
400.565 ký tự; doc 495559 về 990 dịch vụ y tế dự phòng có 246.814 ký tự.
Trong test, max là 90.672 ký tự, doc 427504 về quản lý rác thải sinh hoạt.
Vì vậy, corpus không chỉ có đoạn y khoa diễn giải ngắn; có danh sách dài,
quy định và nguồn ngoài chủ đề bệnh. ICD-10 null không phải lý do tự động loại.

### 3.3. Ngôn ngữ: nguồn và nội dung là hai metadata khác nhau

Phân bổ nguồn BTC được ghi trong context: VI 740.598, EN 240.000, ZH 240.000.
Parquet không có cột language từng dòng. Manifest test ghi 10.950 VI, 4.475 EN,
4.475 ZH và 100 failures; đó là nhãn dựa vào domain của sampler.

Đối chiếu script văn bản phát hiện:

- 253 record `zysjonline.com`, 3 `qihuangzhishu.com`, 2 `health.people.com.cn`
  trong test được sampler xếp VI nhưng có nội dung Trung Quốc. Ví dụ doc
  4265827, test dòng 13.393, là chương sách `脊髓亚急性合并变性`.
- Trên toàn bộ PubMed success có **710 record chứa ≥20 ký tự CJK**; test có
  **38** record như vậy. Không suy ra mọi record này chỉ có tiếng Trung.
  Doc 7156587 có cả abstract Anh và Trung; chunk order 1 đang trộn hai phần.
- Doc 6329186 và 7139291 có abstract Anh và Serbia. Doc 6480634 có đoạn Pháp.
  Một heuristic coi chữ `đ`/`ă` là tiếng Việt đã gán nhầm hai abstract Serbia
  và tên tác giả Romania ở doc 6248072. Những heuristic này không phải LID
  ground truth; số `language_proxy` trong JSON chỉ là cờ để tìm case cần đọc.
- NLM xác nhận PubMed có abstract ngôn ngữ khác do nhà xuất bản cung cấp, và
  ngôn ngữ bài báo khác ngôn ngữ abstract. [PubMed Help](https://pubmed.ncbi.nlm.nih.gov/help/#abstracts)

Đề xuất lưu `source_language` và `content_language_spans` riêng; đoạn không chắc
để `und`, kiểm tra theo nội dung, không chỉ theo domain hoặc một vài dấu chữ.
Không dịch hoặc bỏ abstract nguyên bản tiếng khác để ép vào một nhãn ngôn ngữ.

### 3.4. Giới hạn của bộ test hiện tại

Đây là bộ stratified/stress test, có ưu tiên đoạn rất ngắn, rất dài và biểu thức
so sánh; không phải mẫu ngẫu nhiên phản ánh tỷ lệ sản xuất.

Một minh chứng rõ: test đã chứa 1.492/1.523 URL Long Châu ngoài `/bai-viet/`
(97,96% nhóm này), nhưng chỉ 2.508/78.022 bài `/bai-viet/` success (3,21%).
Do đó tỷ lệ lỗi/chunk ngắn tổng trên test không thể nhân thẳng lên 1,22 triệu.
Phải báo chỉ số từng format và tách đánh giá ca biên khỏi đánh giá đại diện.

Test có 18 URL forum nhưng đều thất bại, không có chunk forum để nghiệm thu;
không có Baidu. Không tuyên bố các profile này đã được kiểm chứng.

## 4. Baseline hybrid: điểm tốt và giới hạn

| Chỉ số | Kết quả |
|---|---:|
| Input / success / skipped | 20.000 / 19.900 / 100 |
| Lỗi pipeline / lỗi audit | 0 / 0 |
| Parent / child | 30.929 / 71.203 |
| Mean / min / max units mỗi child | 202,93 / 1 / 425 |
| Child 150–300 units | 58.389 (82,00%) |
| Child <100 units | 6.707 (9,42%) |
| Child >300 units | 2 (cùng doc 3078554, đều 425) |
| Chuyển tiếp cùng parent có overlap | 99,78% |
| Chuyển tiếp cùng parent overlap 30–50 | 33.630/40.274 (83,50%) |
| Coverage non-whitespace, gồm excluded | 37.334.226/37.334.226 (100%) |
| Structural boundary theo detector hiện tại | 98,82% |

### 4.1. Điểm tốt có ví dụ thật

- **Giữ nguyên nội dung và mapping:** audit xác minh ID, thứ tự, hash,
  parent containment, source slice và coverage trên toàn test. Đây là nền tảng
  cần giữ nguyên khi thêm profiles.
- **Bài diễn giải thông thường được pack tốt:** doc 218831, test dòng 4.583,
  tạo 5 chunk, tất cả trong 150–300 units và đều kết thúc bằng dấu hết câu.
  Không cần tách thành một thuật toán ngữ nghĩa khác chỉ vì đây là Long Châu.
- **Abstract ngắn giữ nguyên hợp lý:** doc 6954391, dòng 102, một chunk 228
  units giữ title và toàn abstract, gồm nhiều nhãn mục. Việc chứa METHODS/
  RESULTS/CONCLUSION ở đây không phải lỗi; tách cứng sẽ làm vụn abstract.
- **Q&A ngắn được giữ đủ:** doc 1128713, dòng 15.530, một chunk 159 units
  giữ mô tả vấn đề, bối cảnh và câu trả lời.
- **Cleaner có provenance và bảo thủ:** 0 source rỗng mới trong input success;
  ký tự hỏng được cảnh báo thay vì đoán chữ. Đánh giá này chỉ áp dụng các dữ
  liệu đã đọc, không chứng minh mọi hình dạng Markdown/HTML đều được xử lý.

### 4.2. Các điểm đáng chê: dẫn chứng và nguyên nhân

Các chuỗi có ký hiệu `⟦CUT⟧` bên dưới là vị trí cắt trong source, không phải
ký tự thật trong output. Chunk sau có thể bắt đầu sớm hơn do overlap; overlap
giúp giữ thêm nội dung nhưng không làm biên của chunk trước trở thành đúng.

| Vấn đề | Ví dụ thật | Vì sao cần sửa |
|---|---|---|
| Cắt số thập phân VI | doc **211401**, dòng 5.277, child 0: `37,⟦CUT⟧5 độ C` | Clause delimiter chưa bảo vệ dấu phẩy thập phân. |
| Cắt tỷ lệ | doc **6333519**, dòng 481, child 0: `(1:⟦CUT⟧1)` | Hai chấm trong tỷ lệ bị coi là điểm cắt. |
| Cắt số tiền | doc **5714388**, dòng 676, child 0: `$10,⟦CUT⟧100)` | Dấu phẩy hàng nghìn chưa được bảo vệ. |
| Cắt nhóm thống kê | doc **7147848**, dòng 243, child 0: `(ES:⟦CUT⟧ 0.51, 95% CI...)` | Tách tên thống kê khỏi giá trị trong ngoặc. |
| Nhãn nằm cuối parent | doc **269380**, dòng 4.580, child 5: `Cảm giác tội lỗi:⟦CUT⟧` | `_looks_like_lead_in()` loại các chuỗi kết thúc bằng `:`; nội dung giải thích sang parent kế tiếp. |
| Marker trả lời nằm cuối chunk | doc **1067218**, dòng 15.526, child 0 kết thúc `病情分析：` | QA hiện chỉ là một vùng chung, chưa định nghĩa answer blocks và gắn marker với body. |
| Bio bác sĩ làm nhiễu bệnh | doc **2335124**, dòng 15.533, child 0 có `【医生信息】`, kèm tăng huyết áp, đái tháo đường, nốt tuyến giáp... | Những tên bệnh là chuyên môn bác sĩ, không phải chủ đề câu trả lời; có thể làm nhiễu embedding/ICD/entity metadata. |
| Mục lục tạo chunk rỗng ý nghĩa | doc **279805**, dòng 4.881, children 2/4/6/8 chỉ `Triệu chứng` (2 units) | Heading được ngắt thành parent riêng; chưa phân biệt TOC lặp với heading của body. |
| Title dài bị cô lập | doc **5846763**, dòng 3.754, child 0 chỉ title 15 units | Title dài 122 ký tự vượt ngưỡng 120, không nhận là heading; parent budget tách nó khỏi abstract. |
| Nhiều abstract trong một window | doc **7156587**, dòng 101, child 1 gồm Anh và Trung | Thiếu language spans và format nghiên cứu; một kiểu domain không mô tả hết record. |
| PubMed có format danh mục | doc **6248072**, dòng 4.304, thân có `O1`, `O2`, `P1`... | Bảng chương trình/tác giả được coi như prose abstract, chưa có entry boundaries. |
| Nav/menu được index | doc **2996442**, dòng 17.326, child 2 có danh sách giải độc/thuật ngữ/footer | Cần role nav riêng, không chỉ marker boilerplate phổ quát. |
| Oversized do menu lặp | doc **3078554**, dòng 17.393, children 12 và 26, mỗi child 425 units | Cùng menu bách khoa lặp; chia nhỏ menu tiếp không giải quyết nhiễu nguồn. |
| Nguồn hiển thị lặp | doc **2531165**, dòng 17.345, nguyên mô tả triệu chứng lặp hai lần | Đây là vấn đề block nguồn và bản render, không phải mất coverage hoặc lỗi ID. |
| Nav lật chương lẫn nội dung | doc **4265827**, dòng 13.393, child 1 có `← → 方向键翻页` và tên chương bên cạnh | Book profile cần giữ chapter body và nhận diện navigation. |
| Số đo bị nhận nhầm heading | doc **264212**, dòng 4.605: `24.7mg` thành heading | Regex số+dấu chấm chưa phân biệt thập phân và số thứ tự. Chunk vẫn giữ vitamin C cùng liều; lỗi ở phân loại cấu trúc. |

Toàn văn excerpt, URL và đường dẫn shard của tất cả ví dụ:
[CASEBOOK.md](research/format-audit-20261013/CASEBOOK.md).

Nguyên nhân nền trong code:

1. `_paragraph_atoms()` chia câu thành clause khi câu >50 units, để có
   trailing atom nhỏ cho overlap. Do đó kể cả câu vừa ngân sách vẫn có thể bị
   cắt ở comma/colon. Cần tách chính sách biên chunk khỏi mục tiêu overlap.
2. `_sections()` bỏ qua segmentation theo heading trong QA. `doc_type` chỉ
   `qa/article/other`; chưa có responder, research section, table/list, chapter.
3. `_extract_paragraphs()` coi mỗi dòng non-empty là paragraph và dùng heading
   regex hẹp. Break do inline link và line/table flattening không phải luôn
   ranh giới ngữ nghĩa.
4. Audit kiểm tra boundary theo chính atom detector đang dùng. Cắt hợp lệ theo
   detector không đồng nghĩa câu/số liệu còn nguyên nghĩa. `atomic_section` là
   lý do ngoại lệ, chưa phải bằng chứng rằng đoạn ngắn là không tránh được.

### 4.3. Cờ tự động: dùng để chọn ví dụ, không phải nhãn lỗi

- 17 biên nằm trong biểu thức số/ratio ở 14 document; những ví dụ trong bảng
  đã được đọc và xác nhận. Không suy ra mọi dấu phẩy đều là biểu thức số.
- 472 biên delimiter có ngoặc đang mở; bao gồm nguồn có ngoặc lỗi. Đây là cờ
  nghi ngờ, không tuyên bố 472 lỗi đều được xác nhận.
- 8.828 child không cuối source kết thúc ở một delimiter comma/colon/semicolon/
  CJK enumeration. Bao gồm paragraph, câu dẫn và dấu `;` hợp lệ.
- 863 document lặp paragraph ≥100 ký tự. Một số lặp có thể là dẫn chứng hợp lệ;
  không xóa tự động chỉ vì trùng văn bản.
- 1.636 chunk <50 units trong doc ≥150 units; trong đó 556 chunk 1–9 units.
  Có case heading/nav rõ ràng, không coi mọi chunk ngắn là sai.
- 1.405 chunk khớp một trong các marker nav/bio khảo sát. Bao gồm trích dẫn
  Trung y có nội dung; không đồng nhất marker với boilerplate cần bỏ.
- 1.354 PubMed chunk chứa ≥2 section labels đầu dòng. Case 6954391 cho thấy
  nhiều mục trong một abstract ngắn là hợp lý; không dùng số này làm số lỗi.

6.707 child <100 units gồm 3.190 `short_document`, 94 `qa_atomic`, 3.421
`atomic_section`, 2 `oversized_neighbor`. Tài liệu gốc quá ngắn phải giữ nguyên;
không tăng độ dài bằng cách ghép tài liệu, thêm title lặp hoặc viết lại.

## 5. Đánh giá baseline theo nhóm format

| Nhóm URL trong test | Doc success | Child | Child 150–300 | Child <100 | Overlap 30–50 trên chuyển tiếp cùng parent |
|---|---:|---:|---:|---:|---:|
| PubMed | 4.475 | 6.636 | 66,59% | 1.373 | 82,56% |
| Long Châu `/bai-viet/` | 2.508 | 16.010 | 91,16% | 586 | 84,22% |
| Long Châu path khác | 1.492 | 1.733 | 66,19% | 211 | 80,91% |
| Tin/bài khác | 4.861 | 15.517 | 76,84% | 2.133 | 81,70% |
| Vinmec | 1.300 | 4.382 | 78,34% | 390 | 82,66% |
| Bệnh viện | 700 | 4.241 | 85,12% | 324 | 82,18% |
| Bài y khoa Trung Quốc | 911 | 4.780 | 79,75% | 561 | 86,75% |
| Q&A | 1.800 | 7.153 | 89,04% | 245 | 81,48% |
| Bách khoa | 1.472 | 8.781 | 84,91% | 689 | 84,94% |
| Sách/từ điển Trung y | 290 | 798 | 63,41% | 186 | 79,53% |
| jbk bệnh/triệu chứng | 91 | 1.172 | 95,48% | 9 | 91,48% |

Tỷ lệ đạt size cao ở Q&A/bách khoa không chứng minh không có nhiễu. Ngược lại,
abstract ngắn nằm dưới 150 có thể rất tốt. Cần nghiệm thu biên, vai trò block,
ngữ cảnh và retrieval riêng; không dùng chỉ tiêu tất cả chunk phải 150–300.

Scorer trong `asked.md` tokenizes bằng whitespace. Với chuỗi CJK không có
khoảng trắng, cắt câu/clause/paragraph khác nhau có thể tạo token khác với g,
dù nghĩa gần nhau. Đây là rủi ro có điều kiện theo ground truth, chưa đo được
điểm mất. Cần thêm kiểm tra retrieval và nguyên paragraph/parent từ source,
không tự thêm khoảng trắng cho CJK hoặc thay văn bản để làm token khớp.

## 6. Web đối chiếu và giới hạn

Đã thử mở 11 URL: trang cuộc thi, 10 trang nguồn cụ thể; thành công đọc body của
3 trang VI (Long Châu, Vinmec, Sức khỏe & Đời sống). PubMed PMID 36544416 chỉ
trả footer trong công cụ web; 7 URL còn lại không truy cập/robots unreachable.
Không kết luận nguyên nhân mạng là WAF từ những lỗi này.

Công cụ web có trả nội dung đã crawl/cache từ các thời điểm trước (ví dụ
8–11 tháng với một số trang VI); đây không phải kiểm thử DOM bằng browser
runtime trực tiếp trong lượt này.

- [Long Châu bài hạt lanh](https://nhathuoclongchau.com.vn/bai-viet/hat-lanh-lam-mon-gi-goi-y-4-mon-ngon-tu-hat-lanh-70139.html): có H2/H3, danh sách bước, ảnh và footer. Stored text của doc 236542 có ngắt dòng ở inline link; profile không được coi mọi dòng ngắn là section mới.
- [Vinmec doc 752978](https://www.vinmec.com/vie/bai-viet/thai-nhi-thanh-hinh-va-phat-trien-nao-trong-tu-cung-vi): body có inline anchors; crawler đã bỏ phần đặt lịch ở tail nhưng còn dòng mời đăng ký video ở đầu. Tối ưu body phải theo vị trí/role, không chỉ tail.
- [Sức khỏe & Đời sống doc 539836](https://suckhoedoisong.vn/phai-dep-muon-gi-trong-khi-sex-16996855.htm): có các mục đánh số; đó là một shape trong narrative, không phải mỗi số thứ tự đều cần chunk riêng.
- [NLM PubMed Help](https://pubmed.ncbi.nlm.nih.gov/help/#abstracts): hỗ trợ nhiều abstract/ngôn ngữ; không đồng nhất domain với ngôn ngữ nội dung.
- [JATS Abstract](https://jats.nlm.nih.gov/archiving/tag-library/1.4/element/abstract.html): thể hiện abstract có section và nhiều abstract. Đây là cơ sở tham khảo cho metadata, không khẳng định tất cả XML PubMed dùng JATS.

Các nhận xét Q&A/Trung y/bách khoa dựa vào snapshot dữ liệu thật đang lưu;
chưa xác minh DOM hiện tại của các website không truy cập được. Test không có
Markdown pipe table còn nguyên; bảng nguồn có thể đã flatten, thiếu dấu phân
cột. Component chunking không khôi phục cấu trúc HTML đã mất.

## 7. Artifact và lệnh tái lập

Thư mục kết quả mới:
`sbtc/Scripts/Preprocess/research/format-audit-20261013/`.

| Artifact | Nội dung |
|---|---|
| [corpus_profile.json](research/format-audit-20261013/corpus_profile.json) | Full count/hash/domain/ngôn ngữ proxy và URL prefixes |
| [corpus_source_profiles.json](research/format-audit-20261013/corpus_source_profiles.json) | Quantiles/histogram theo nhóm URL và PubMed script signals |
| [test_profile.json](research/format-audit-20261013/test_profile.json) | Profile sample; heuristic language không phải ground truth |
| [test_rows.csv](research/format-audit-20261013/test_rows.csv) | 20.000 ID, dòng nguồn, domain, nhóm, độ dài và URL |
| [baseline_summary.json](research/format-audit-20261013/baseline_summary.json) | Summary của CLI thực tế |
| [baseline_audit.json](research/format-audit-20261013/baseline_audit.json) | 19.900 checked, 100 skipped, 0 errors |
| [chunk_metrics.json](research/format-audit-20261013/chunk_metrics.json) | Size/overlap theo format và cờ rủi ro |
| [CASEBOOK.md](research/format-audit-20261013/CASEBOOK.md) | 19 ví dụ đã chọn để đọc, gồm 3 điểm tốt |
| [review_cases.json](research/format-audit-20261013/review_cases.json) | Ví dụ cờ tự động; không phải labels lỗi |
| [baseline_chunks/](research/format-audit-20261013/baseline_chunks/) | 20 shards; mỗi dòng là một document, children chứa chunk |
| [input_code_integrity.json](research/format-audit-20261013/input_code_integrity.json) | Hash input/component trước/sau |
| [code_snapshot/](research/format-audit-20261013/code_snapshot/) | Mã dùng cho lần đo, giữ nguyên code workspace |

Chạy từ AIGuru. Output rerun phải là thư mục mới, không ghi đè baseline:

```bash
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_cli \
  data_final/test_20k.jsonl \
  sbtc/Scripts/Preprocess/research/format-audit-rerun/baseline_chunks \
  --strategy hybrid --workers 2 --progress-every 2000
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_audit \
  data_final/test_20k.jsonl \
  sbtc/Scripts/Preprocess/research/format-audit-rerun/baseline_chunks
```

Các helper khảo sát được lưu trong artifact directory, không tích hợp vào
component sản xuất. Timing chỉ là runtime của khảo sát có chạy đồng thời các
job đọc, không phải benchmark throughput kiểm soát tải. Chưa chạy full corpus
chunking, chưa nghiệm thu format mới và chưa đo retrieval/F2.
