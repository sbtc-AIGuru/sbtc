# Báo cáo cập nhật chất lượng chunk — 2026-10-14

## Kết luận

Gói A đã được triển khai thành profile `format-v2` và kiểm tra trên duy nhất `data_final/test_20k.jsonl`. Hai mục tiêu chính đạt: placeholder lỗi crawl không còn được index và child trên 500 units được sửa hết. Auditor kiểm tra đủ 20.000 dòng, không báo lỗi; các chunk hợp lệ là lát cắt nguyên văn từ cleaned source và coverage non-whitespace đầy đủ.

Mục tiêu gộp chunk dưới 50 units **chưa cải thiện được trên fixture**. Không có chuỗi liên tiếp đủ điều kiện theo cùng parent, section, role, ngôn ngữ và budget. Số chunk dưới 50 tăng nhẹ 2.036 → 2.037 vì một câu bridge 15-unit trong `doc_id=4057861` được giữ riêng tại ranh giới nội dung. Không nới điều kiện gộp để làm đẹp chỉ số vì các chunk kề có giới hạn budget hoặc khác role.

Không có gold labels để tính Precision, Recall hoặc F2. Vì vậy báo cáo xác nhận chất lượng cấu trúc và bảo toàn nguồn; chưa kết luận điểm retrieval có tăng.

## Phạm vi và bảo toàn dữ liệu

- Nguồn duy nhất: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl`.
- SHA-256 trước/sau: `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
- Baseline: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v2_baseline_test20k/`.
- V2: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v2_test20k/`.
- Dữ liệu crawl gốc, `data_final/final_data.jsonl` và `data_final/chunks_format_final/` không bị sửa hay ghi đè. Đây chưa phải lần chạy toàn corpus.
- Số units là đơn vị `count_units()` của repo, không đồng nhất với từ, token mô hình hay byte.

## Thay đổi triển khai

1. `chunking.py`: đầu ra skipped có `text=""`; format strategy nhận diện template Crawl4AI lỗi đặc hiệu và bỏ record khỏi parent/child retrieval, vẫn giữ `doc_id`, URL, hash và lý do.
2. `format_profiles.py`: tăng profile lên `format-v2`; chia atom trên 500 units theo vùng/heading/đoạn/câu/dòng/mệnh đề/whitespace theo thứ tự fallback, chỉ lấy lát cắt nguồn và không cắt protected span. Trường hợp không tìm được biên được giữ rõ bằng `oversized_unresolved`. Giới hạn false protection: bracket expression rất dài/hỏng không còn bảo vệ toàn đoạn vô điều kiện.
3. `format_chunking.py`: thêm bước gộp chuỗi chunk dưới 50 units nếu chúng liền nhau, cùng parent/profile/role/section path/ngôn ngữ và tổng span không quá 300 units; tạo provenance để kiểm toán. Không gộp một chunk ngắn đơn lẻ vào chunk thường.
4. `chunk_audit.py`: dựng lại profile/span từ input, kiểm tra source slice, coverage, protected cut, reason, phiên bản/checkpoint và provenance merge.
5. `tests/test_chunk_formats.py` và `tests/test_chunk_format_streaming.py`: regression cho 2 placeholder lỗi thật, matcher âm, 7 record quá cỡ, merge helper với mẩu nguồn lấy từ fixture, cùng các bất biến streaming.

## So sánh trước / sau

| Chỉ số | Baseline `format-v1` | Candidate `format-v2` | Nhận xét |
|---|---:|---:|---|
| Records | 20.000 | 20.000 | Cùng input và thứ tự |
| `ok` / `skipped` | 19.900 / 100 | 19.898 / 102 | Hai placeholder lỗi chuyển từ `ok` sang `skipped`; 100 crawl failures giữ nguyên trạng thái |
| Runtime errors / audit errors | 0 / 0 | 0 / 0 | Auditor candidate: 19.898 checked, 102 skipped |
| Tổng child | 62.465 | 62.483 | Tăng 18 do chia atom lỗi quá cỡ |
| Child >300 units | 24 | 22 | Hai child ít hơn; các 22 child còn lại nằm trong 301–494 units |
| Child >500 units | 7 | 0 | Không còn chunk vượt hard repair threshold |
| Kích thước lớn nhất | 2.760 | 494 | Giảm 82,1%; đơn vị là `count_units()` |
| Child <50 units | 2.036 | 2.037 | Không giảm; không có merge tự nhiên đủ điều kiện |
| Non-whitespace coverage | 37.334.226 | 37.333.358 | Candidate bỏ đúng 868 ký tự non-whitespace thuộc 2 template lỗi (434 mỗi record); phần còn lại được phủ đầy đủ |
| Indexed + excluded | 37.334.226 | 37.333.358 | Candidate: 37.147.376 indexed + 185.982 excluded = 37.333.358 source |
| Thời gian chạy chunking | — | 190,4 giây | 2 workers, 20 shards |

Phân bố candidate: `<50`: 2.037; `50–99`: 2.421; `100–149`: 2.864; `150–219`: 12.060; `220–300`: 43.079; `>300`: 22. Merge count tự nhiên: 0.

Trong nhóm `<50` của candidate, 1.537 là short-document, 139 là hard-boundary region, 352 là question context và 9 là budget remainder. Đây là các lý do bảo toàn nguyên tắc ngữ nghĩa; không phải tất cả đều là mẩu lỗi có thể ghép.

## Đánh giá các ca quá cỡ và ngữ nghĩa

Auditor xác nhận `chunk_text == cleaned_source[start_char:end_char]`, các span không cắt vùng protected, và tổng số ký tự non-whitespace được phủ khớp với source. Do đó, ở 19.898 record `ok`, repair không làm mất hoặc viết lại văn bản. Hai record bị loại là thông báo lỗi crawler, không phải nội dung tài liệu.

Đã đọc các record thực từng có child trên 500 units:

| `doc_id` | Dạng nội dung | Baseline max | V2 max / kết quả | Nhận xét biên |
|---:|---|---:|---:|---|
| 5756127 | PubMed abstract tiếng Anh | 580 | 279; 8 child | Chia theo mệnh đề ở vùng abstract dài; còn overlap ngữ cảnh |
| 6269502 | Chương trình hội nghị PubMed | 590 | 300; 4 child | Ranh giới sau mục/câu của chương trình |
| 6884288 | PubMed abstract đa ngôn ngữ (Anh/Thái/Tây Ban Nha) | 661 | 299; 8 child | Có fallback whitespace ở đoạn Thái; không cắt token, nhưng đây là nhóm biên có nguy cơ giảm mạch câu cao nhất |
| 529733 | Bài tiếng Việt có danh sách mức đóng BHYT | 502 | 298; 10 child | Bảng/list được chia thành mẩu nhỏ hơn; source còn nguyên |
| 1100056 | Hỏi đáp y khoa tiếng Trung | 735 | 424; 8 child | Tách atom lớn; còn soft oversize 301–500 theo chính sách đã duyệt |
| 4057861 | Bài y khoa/bách khoa tiếng Trung | 2.760 | 494; 38 child | Long bracket trước đó làm atom kéo dài; giới hạn bracket đã được sửa. Có một câu bridge 15-unit giữa body và formula nên giữ riêng |
| 4107923 | Bài y khoa tiếng Trung | 1.063 | 299; 38 child | Các atom quá cỡ được phân nhỏ, không vượt 500 |

### Mẩu ngắn 15 units ở `doc_id=4057861`

Mẩu nguồn là `然而以上结果仍需进一步深入评价。` (“Tuy nhiên, các kết quả trên vẫn cần được đánh giá thêm.”). Chunk body liền trước dài 494 units; ghép thêm câu sẽ thành 509, vượt hard cap 500. Chunk kế tiếp dài 304 units và mang role `formula`; ghép sẽ thành 319, vượt budget 300 và trộn role. Giữ câu 15 units riêng là lựa chọn ít rủi ro hơn. Đây cũng là nguyên nhân duy nhất làm số `<50` tăng một.

## Kiểm thử

Lệnh:

```bash
python -m unittest sbtc.tests.test_chunk_formats sbtc.tests.test_chunk_format_streaming
python -m sbtc.Scripts.Preprocess.chunk_cli data_final/test_20k.jsonl data_final/chunks_format_v2_test20k --strategy format --workers 2 --progress-every 2000
python -m sbtc.Scripts.Preprocess.chunk_audit data_final/test_20k.jsonl data_final/chunks_format_v2_test20k
```

Kết quả: 75 tests PASS; CLI xử lý 20.000 dòng, 0 runtime errors; audit `{"records": 20000, "checked": 19898, "skipped": 102, "errors": 0}`.

## Các giới hạn còn lại

- Việc gộp short chunk đã có helper, test và auditor, nhưng chưa có hiệu quả đo được trên fixture do không có chuỗi tự nhiên vượt qua các ràng buộc semantic. Không gộp qua section, parent, Q/A hoặc role để ép giảm count.
- 301–500 units là soft oversize, được giữ nguyên trừ khi atom lớn hơn 500. Nếu muốn mọi chunk ≤300, cần một yêu cầu riêng vì phải chia thêm nội dung hiện còn là một atom/câu dài.
- Fallback mệnh đề/whitespace có thể làm ranh giới ngữ cảnh chưa tự nhiên dù không mất chữ; ca đa ngôn ngữ `doc_id=6884288` nên được xem là điểm cần review nếu có gold retrieval query phù hợp.
- Không suy ra Precision/Recall/F2 từ coverage hoặc audit; chưa có nhãn tham chiếu trong tập kiểm thử này.

## Artefact và lệnh tái lập

- Summary baseline: `tasks/chunk-quality-update-20261014/baseline-summary.json`.
- So sánh/audit: `tasks/chunk-quality-update-20261014/comparison-summary.json`.
- Plan/checklist: `tasks/chunk-quality-update-20261014/plan.md`, `tasks/chunk-quality-update-20261014/todo.md`.
- Output candidate: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v2_test20k/`.
- Output baseline: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v2_baseline_test20k/`.

Đánh giá bổ sung về overlap, profile, TOC/link vỡ, short chunks và các phương án đánh đổi được lưu tại [PROPOSAL-chunking-next-improvements-20261014.md](PROPOSAL-chunking-next-improvements-20261014.md). Số liệu diagnostic của đợt review nằm trong `tasks/chunk-quality-update-20261014/review-synthesis-metrics.json`; đây là phân tích output test20k đã có, không phải một lượt chạy thuật toán mới.

Đợt triển khai kế tiếp đã hoàn tất trên test20k với format-v3/verbatim-v5: [REPORT-chunking-next-improvements-20261014.md](REPORT-chunking-next-improvements-20261014.md), 97 tests PASS, hai full audit final r3 0 errors. Số liệu v2 trong báo cáo này được giữ làm lịch sử đối chiếu.
