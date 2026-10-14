# Kết quả triển khai cải thiện chunking — format-v3 / verbatim-v5

Ngày: 14/10/2026. Bản chốt: **r3**. Trạng thái: triển khai, benchmark, đối chiếu và hai full audit đã hoàn tất.

Phạm vi theo đề xuất đã được người dùng duyệt: TOC, malformed links, routing theo cấu trúc, sentence guard, diagnostics, merge provenance và thử nghiệm packing có dành budget overlap. Dữ liệu duy nhất dùng cho kiểm thử/benchmark là `data_final/test_20k.jsonl`; không chạy lại full corpus, không sửa dữ liệu gốc hoặc output cũ.

## 1. Benchmark trên toàn bộ 20.000 dòng test

| Chỉ số | Baseline format-v2 | r3 post_pack (mặc định) | r3 reserve (opt-in) |
|---|---:|---:|---:|
| Record xử lý | 20.000 | 20.000 | 20.000 |
| OK / skipped | 19.898 / 102 | 19.898 / 102 | 19.898 / 102 |
| Lỗi runtime | 0 | 0 | 0 |
| Child chunks | 62.483 | 62.505 | 62.941 |
| Parents | 27.777 | 27.817 | 27.817 |
| Overlap 30–50 units, trong cùng parent | 59,04% | 59,02% | **61,44%** |
| Có overlap, trong cùng parent | 87,29% | 87,29% | **91,81%** |
| Chunk <50 units | 2.037 | 2.084 | 2.083 |
| Chunk >300 / >500 units | 22 / 0 | 23 / 0 | 23 / 0 |
| Chunk lớn nhất | 494 | 494 | 494 |
| Tổng kích thước JSONL shards | 322,49 MiB | 322,30 MiB | 322,95 MiB |
| Thời gian CLI, 2 workers | Không đo lại | 188,38 giây | 189,04 giây |

`unit` theo `count_units()`, không phải tokenizer của embedding model hay cách BTC tách token theo khoảng trắng. Mẫu số overlap là chuyển tiếp trong cùng parent: v2=34.706; r3 post=34.728; r3 reserve=35.124. Hai policy có ranh giới khác nhau, nên không diễn giải thành độ chính xác truy hồi.

`reserve` tăng 2,42 điểm phần trăm overlap 30–50 và 4,51 điểm phần trăm positive overlap so với r3 post. Chi phí: thêm **436 chunks (+0,70%)**, JSONL thêm **0,20%**. Vẫn giữ nguyên atom, source slices và parent/semantic boundaries. Thời gian hai lượt là quan sát một lần, không phải benchmark hiệu năng nhiều lần có độ lệch chuẩn.

102 record skipped gồm 100 `crawl_failed` và hai placeholder lỗi đã được v2 nhận diện. Output giữ `text=""`, không có children cho nhóm này; ID/URL vẫn bảo toàn. Không sửa bản crawl nguồn.

## 2. Làm sạch: tốt hơn ở các lỗi đã có bằng chứng

- **508 recovery actions** trên malformed Markdown links; 76 tài liệu có cleaned-source hash thay đổi. So sánh chuỗi chữ/số giữa cleaner v4 và v5 ở toàn bộ 76 tài liệu: **không có khác biệt số lượng hoặc thứ tự**, không phát hiện mất label hoặc body. Cleaner idempotent ở các source đã đổi.
- Trên 95 record có cảnh báo link vỡ, scanner residual syntax giảm **540→32**. Đây là phép đo cú pháp nghi vấn, không phải kết luận cả 32 vị trí đều là lỗi. Raw warning vẫn giữ **541 events/95 records** để truy vết; không dùng số warning nguyên thủy để đo số lỗi còn lại sau recovery.
- Recovery có giới hạn 4.096 ký tự trên cùng dòng; target mơ hồ, biểu thức hóa học/đơn vị và link quá dài được giữ lại để review. Regression phát hiện URL dính chữ Trung bị nuốt và Unicode ignorecase xử lý sai ASCII `i`; đã sửa, test giữ được chữ Trung, số/đơn vị và body dòng sau.

## 3. TOC: loại navigation có bằng chứng, giữ body

Loại **47 khối mục lục**, tương ứng **16.946 ký tự không phải whitespace**. Điều kiện: marker explicit ở đầu, ≥3 entries, ≥60% entry khớp heading ở body theo đúng thứ tự, có paragraph thực sự. Trang index-only không bị xóa; TOC khai báo vẫn được mask khỏi routing để không làm giả evidence body.

Evidence chứa **614 entries**, trong đó **607** có heading body khớp sau chuẩn hóa số thứ tự/whitespace/case. Bộ đối chiếu độc lập xác nhận các heading body được trỏ tới đều còn nguyên trong source và được children bao phủ. Bảy entries chưa khớp nằm ở bốn tài liệu:

| doc_id | Entry chưa khớp | Nhận xét từ source |
|---|---|---|
| 762937 | Hai nhãn kèm số chú thích `4 5` | Khác marker chú thích với heading body |
| 292115 | `Cách nhận biết kiến ba khoang` lặp hai lần | Nhãn navigation không có heading trùng nguyên cách viết |
| 761429 | `2. Codein1 3` | Số chú thích dính nhãn |
| 292348 | `Ngộ độc thực phẩm là gì?` lặp hai lần | Navigation có biến thể nhãn |

Review không thấy prose paragraph bị nuốt trong các khối này. Tuy nhiên detector vẫn là heuristic có ngưỡng, không chứng minh tuyệt đối mọi entry là duplicate; giữ evidence để truy vết.

**Đánh đổi:** số short <50 tăng 47 ở post_pack vì tiêu đề trước mục lục trở thành một vùng nguồn riêng. Không ghép tiêu đề vượt khoảng source đã loại: child phải là contiguous source slice. Giữ tiêu đề và `title_span` giúp bảo toàn thông tin; phía retrieval cần quyết định cách dùng metadata khi embed/rerank. Chưa có bằng chứng pipeline embedding hiện đã sử dụng metadata này.

## 4. Router: chặn tín hiệu yếu, giữ cấu trúc thật

| Chuyển profile v2→r3 | Số record |
|---|---:|
| disease_drug_catalogue→narrative_article | 201 |
| narrative_article→disease_drug_catalogue | 21 |
| research_abstract→narrative_article | 6 |

Catalogue yêu cầu field/template đặc hiệu hoặc bằng chứng body của monograph; research yêu cầu nhóm nhãn bổ trợ ở body trước references, giữ prior PubMed. Không dùng TOC/references làm evidence body. Tên profile đổi không đồng nghĩa nội dung chắc chắn bị chia khác hoặc accuracy đã được đo.

Các ca kiểm chứng bằng source thật trong test20k:

| doc_id | Kết quả | Điều được kiểm chứng |
|---|---|---|
| 239736 | Catalogue→narrative | Bài huyết áp thấp có heading chung, không phải catalogue chỉ vì từ khóa |
| 2520397 | Research→narrative | Bài xét nghiệm Trung ngữ có nhãn lặp, thiếu cấu trúc abstract bổ trợ |
| 279805 | Giữ catalogue | Template nhiều field lặp với marker rõ, không loại nhầm positive |
| 759366, 193224, 182511 | Giữ catalogue | Acyclovir, Celecoxib, Fluoxetine có evidence body thuốc |
| 764534 | Narrative→catalogue | Dermovate có nhóm field thuốc rõ ngoài mục lục |
| 499246 | Giữ narrative | `Thành phần` trong công thức thực phẩm không được coi là hoạt chất thuốc |
| 566375, 1736699 | Giữ research | Abstract có nhãn bổ trợ, không phụ thuộc riêng domain PubMed |

Review trial r1 phát hiện demotion monograph VI; r2 bổ sung drug identity/body fields. Review r2 phát hiện công thức thực phẩm bị route nhầm vì `Thành phần:`; r3 giới hạn identity vào hoạt chất/nhà sản xuất/dạng bào chế hoặc title thuốc cùng nhiều loại field. Thêm test regression trước sửa cho cả hai lỗi, giữ các trial/snapshot riêng.

21 ca narrative→catalogue trong casebook đều có nội dung thuốc/dược liệu. Một số là bài tư vấn thuốc hoặc thảo dược (ví dụ 565011 “Cây xạ đen…”), không phải monograph chuẩn; cần review tiếp nếu định nghĩa profile được thu hẹp. Chưa có tập nhãn profile đủ lớn để báo accuracy/false-positive rate.

`uncertain_format` tăng **13.068→13.254** (65,67%→66,61% số record OK) do đưa nhiều bài về narrative fallback. Đây là cảnh báo confidence, không phải tỷ lệ sai. Không nâng confidence chỉ để làm đẹp số liệu.

## 5. Ranh giới câu, short chunks và lỗi còn lại

- Main scanner và oversized fallback dùng period guard thống nhất. Ca thật **6269502** giữ `H. Lester` liền nhau; trước đây fallback có thể cắt sau `H.`. Giữ atom author-list tạo thêm một child **330 units**, nên số >300 là 23 thay vì 22. Trần repair 500 vẫn đạt, max toàn output 494, unresolved=0. Không tuyên bố mọi child đều ≤300.
- Không ép gộp QA question/answer hoặc khác parent/role/path/language để giảm short count. Provenance gộp được audit cả ID, thứ tự, source atom boundaries, units, context và union spans. Integration test dùng source thật 7239974 với hai mẩu được tạo từ atom nguồn; fixture tự nhiên chưa có run đủ điều kiện gộp để đo lợi ích trên corpus.
- Post còn 9 short budget remainders, reserve còn 8; reserve xử lý được ca 427504 qua re-packing. Các câu hỏi rất ngắn và các tài liệu ngắn vẫn được giữ.
- **4057861** còn câu 15 units giữa child 494 và formula 304 units. Ghép trái vượt500, ghép phải vượt300 và khác role. Giữ riêng có lý do, không bỏ câu để giảm số đếm.
- **4053159** còn footer taxonomy 15 units; **4061665** còn navigation/footer 38 units. Đây là phần cleaning theo template còn thiếu, nên nghiên cứu rule riêng có positive/negative evidence; không ghép chúng vào medical body để che nhiễu.
- Oversized clause/whitespace fallback cũ vẫn có rủi ro coherence cục bộ trong nội dung multilingual khó (như 6884288). Đợt này không chứng minh đã loại hết mọi biên kém tự nhiên.

Overlap lý tưởng theo `source_language` prior:

| Prior ngôn ngữ | r3 post | r3 reserve |
|---|---:|---:|
| vi | 64,37% | 66,19% |
| en | 65,06% | 66,93% |
| zh | 48,49% | 52,27% |
| und | 61,66% | 63,67% |

Đây là domain/source prior, không phải nhãn ngôn ngữ thật của từng chunk; không dùng làm hard language filter.

## 6. Kiểm thử và tính nguyên vẹn

- **97/97 unittest PASS**, 12,796 giây: format (58), streaming (17), new improvements (22). Log: `tasks/chunking-next-improvements-20261014/tests-r3.log`.
- Bộ đối chiếu final r3: 20.000 record khớp ID/URL/input_line, hai policy dùng cùng cleaned source/profile/exclusions, 368 record trong casebook, **0 comparison errors**. Không có lexical/count/order differences trên 76 source thay đổi.
- Full audits final r3: **0 errors ở cả hai output**, mỗi audit 20.000 record/19.898 checked/102 skipped; không có example lỗi. JSON: `results-r3/audit-post.json`, `results-r3/audit-reserve.json`.
- SHA-256 input giữ nguyên: `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
- Code fingerprint final r3: `7208edbdbb00ce480e74f48768762ccbc4151356c1dd6c73a70b78bf5d6e88a6`. Snapshot `code-r3/`, hashes `code-r3-manifest.json`.
- Kiểm tra cuối: source SHA không đổi, không có code drift so với manifest, hai checkpoint `done=true` khớp code fingerprint; `git diff --check` exit0. Tổng hợp hashes bằng chứng tại `results-r3/final-verification.json`.
- Legacy cleaning suites phụ thuộc `datacrawl/test.jsonl` không chạy trong task này; không thay/skip assertions để che fixture cũ thiếu hoặc đưa vào số 97 PASS.

Auditor dùng chung analyzer không tự phát hiện semantic exclusion sai. Independent TOC/body/source comparison và các regression source thật bổ sung bằng chứng; chưa có gold chunk/retrieval labels để kết luận F2, Precision, Recall tăng hoặc không mất ngữ nghĩa tuyệt đối.

## 7. Output và cách tái lập

Đường dẫn tuyệt đối của hai kết quả cuối:

- `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v3_r3_test20k/`
- `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v3_r3_reserve_test20k/`

Mỗi thư mục có 20 shards `part-000000.jsonl` đến `part-000019.jsonl` và `checkpoint.json`. Log/metrics/audits/368-case casebook nằm tại:

`/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/tasks/chunking-next-improvements-20261014/results-r3/`

Baseline v2, trial r1 và r2 được giữ nguyên. r1 đã audit, r2 được supersede sau review recipe; không dùng chúng làm release cuối. Khi chạy lại, chọn tên output **chưa tồn tại**, không ghi đè hay resume folder khác fingerprint:

```bash
python -m unittest sbtc.tests.test_chunk_formats sbtc.tests.test_chunk_format_streaming sbtc.tests.test_chunk_next_improvements

python -m sbtc.Scripts.Preprocess.chunk_cli data_final/test_20k.jsonl data_final/chunks_format_v3_new_run_test20k --strategy format --format-overlap-policy reserve --workers 2 --progress-every 2000

python -m sbtc.Scripts.Preprocess.chunk_audit data_final/test_20k.jsonl data_final/chunks_format_v3_r3_test20k
python -m sbtc.Scripts.Preprocess.chunk_audit data_final/test_20k.jsonl data_final/chunks_format_v3_r3_reserve_test20k

python sbtc/Scripts/Preprocess/tasks/chunking-next-improvements-20261014/benchmark_review.py --post-dir data_final/chunks_format_v3_r3_test20k --reserve-dir data_final/chunks_format_v3_r3_reserve_test20k --output-dir /tmp/chunk-v3-review-new
```

Khuyến nghị: giữ **post_pack là default** hiện tại; dùng **r3 reserve** để thử retrieval/reranking trên gold khi có, vì cấu trúc overlap cải thiện với chi phí nhỏ. Tiếp tục review footer còn sót và phân biệt bài tư vấn thuốc với monograph trước khi mở rộng rules. Không chạy full corpus chỉ dựa vào proxy overlap.
