# Checklist triển khai Chunk Cleaning

Feature hiện tại: [format-aware checklist](format-aware/todo.md).

Đặc tả: [SPEC](../SPEC-chunk-cleaning-pipeline.md). Kế hoạch: [plan.md](plan.md).
Hoàn tất T0–T10: cleaner verbatim-v4, 53/53 tests và full-run 20.000 record audit 0 errors. Giới hạn còn lại đã ghi trong REPORT-chunk-cleaning-pipeline.md.
Input dữ liệu duy nhất: `datacrawl/test.jsonl` (chỉ đọc).

## T0 — Chuẩn bị kế hoạch

- [x] Đọc code cleaner/chunk/audit/CLI, test conventions và trạng thái workspace.
- [x] Ghi nhận user đã duyệt đặc tả; đóng các câu hỏi phạm vi/dependency/metadata.
- [x] Khảo sát 20.000 record test ở chế độ chỉ đọc và xác định candidate regression.
- [x] Lưu kế hoạch/checklist Hybrid v3 đã hoàn tất vào `hybrid-v3/`.
- [x] Viết dependency, ma trận kiểm thử, lệnh tái lập và ghi nhật ký `docs_AI.md`.

## T1 — Fixtures và baseline

**Mục đích:** Chụp trạng thái trước thay đổi bằng dataset thật.
**Phụ thuộc:** T0. **Quy mô:** nhỏ.
**Files:** `sbtc/tests/test_chunk_cleaning.py` (fixture helpers),
output baseline mới dưới `datacrawl/derived/`.

- [x] Chọn ID/snippet đã đọc ngữ cảnh; fixture báo rõ khi source thiếu.
- [x] Ghi hash input, baseline counts/metrics và audit trước khi sửa cleaner.
- [x] Lưu baseline cleaner/version snapshot đủ để so sánh sau; không ghi vào input.

**Xác minh:** Chạy baseline CLI/audit theo plan, ghi đường dẫn tuyệt đối và kết quả.

## T2 — API cleaner và report

**Mục đích:** Có một lõi xử lý và báo cáo tái lập được.
**Phụ thuộc:** T1. **Quy mô:** nhỏ.
**Files:** `verbatim.py`, `test_chunk_cleaning.py`.

- [x] `clean_to_verbatim` và `clean_with_report` trả cùng text; giữ API hiện hành.
- [x] Report có version/hash/length/counters/warnings theo định nghĩa trong plan.
- [x] Cùng input/version có output và report giống nhau; không nhân đôi cleaning.

**Xác minh:** Focused tests import cleaner production, dùng snippet từ `test.jsonl`.

## T3 — HTML và entity

**Mục đích:** Làm sạch markup chắc chắn, giữ nội dung và ranh giới.
**Phụ thuộc:** T2. **Quy mô:** nhỏ.
**Files:** `verbatim.py`, `test_chunk_cleaning.py`.

- [x] Entity hai lượt có counters; undefined entity giữ nguyên.
- [x] Tag/alt/block boundary đúng trên wrapper; so sánh `< 300 ml` không mất.
- [x] HTML/script hỏng không xóa lan sang nội dung còn lại; có warning.

**Xác minh:** Expected từ snippet gốc độc lập với cleaner; kiểm before/after.

## Checkpoint A — API và HTML

- [x] T2–T3 focused tests đạt, hash/report đúng và medical comparison được giữ.

## T4 — Links, references và URL

**Mục đích:** Giữ nhãn hiển thị, không làm mất citation/câu kế bên.
**Phụ thuộc:** T3. **Quy mô:** nhỏ.
**Files:** `verbatim.py`, `test_chunk_cleaning.py`.

- [x] Links/images thật và destination ngoặc cân bằng được chuyển đúng.
- [x] `2066978` giữ nguyên trích dẫn hóa học; reference chỉ bóc khi definition khớp.
- [x] Malformed link/URL sát punctuation hoặc CJK không nuốt nội dung kế bên.

**Xác minh:** Positive/negative cases từ snippet thật và wrappers có ghi nguồn.

## T5 — Formatting, code và table

**Mục đích:** Bóc đúng delimiter mà giữ ký hiệu nội dung.
**Phụ thuộc:** T4. **Quy mô:** nhỏ.
**Files:** `verbatim.py`, `test_chunk_cleaning.py`.

- [x] `8*12` ở `1040581` còn nguyên; không blanket-delete `*`, `|`, `_`, `~`.
- [x] Code/escape/nested emphasis xử lý đúng ngữ cảnh; unmatched marker giữ/cảnh báo.
- [x] Table wrapper giữ thứ tự cell; pipe ngoài table không bị thay.

**Xác minh:** Regression số liệu + wrappers trên source thật; không dùng clone cleaner làm oracle.

## T6 — Unicode, whitespace và UI

**Mục đích:** Chuẩn hóa trình bày có allowlist và warning rõ.
**Phụ thuộc:** T5. **Quy mô:** nhỏ.
**Files:** `verbatim.py`, `test_chunk_cleaning.py`.

- [x] Allowlist codepoint và soft-hyphen rule có expected; không ghép token do xóa control.
- [x] Dấu tiếng Việt, CJK/fullwidth, ZWJ/ZWNJ và U+FFFD giữ theo hợp đồng.
- [x] UI rule hẹp có counters; mẫu gần giống không mất y khoa; boilerplate không xóa khỏi source.

**Xác minh:** Focused suite; đọc candidate invisible thật từ dataset.

## Checkpoint B — Cleaner

- [x] T4–T6 suites đạt; mỗi rule có case bảo toàn và case markup cần loại.

## T7 — Tích hợp chunk và audit

**Mục đích:** Một cleaned source nhất quán cho metadata và chunk.
**Phụ thuộc:** T6. **Quy mô:** vừa.
**Files:** `chunking.py`, `chunk_audit.py`, `test_chunk_cleaning.py`.

- [x] Document đã chạy cleaner có report kể cả empty-after-cleaning; raw/source hashes khớp.
- [x] `doc_id`, order, parent/excluded spans, slices và coverage đúng với source mới.
- [x] Audit phát hiện thiếu/sai version, counters/hash/report bị sửa trong bản copy.

**Xác minh:** Focused integration và suites chunking dùng `test.jsonl`.

## T8 — CLI và resume

**Mục đích:** Không trộn cleaner version trong một run.
**Phụ thuộc:** T7. **Quy mô:** nhỏ.
**Files:** `chunk_cli.py`, `test_chunk_streaming.py`.

- [x] Checkpoint/fingerprint có cleaner version và kiểm trước recovery/ghi file.
- [x] Resume thiếu/sai version bị từ chối; files/checkpoint giữ nguyên sau lỗi.
- [x] Resume cùng version, pending recovery và workers 1/2 cho output/counts tương đương.

**Xác minh:** Streaming tests dùng các record copy từ `test.jsonl`, checksum trước/sau.

## Checkpoint C — Pipeline

- [x] Suites `test_chunk_*.py` đạt; audit/resume version mismatch không false-pass.

## T9 — Full test run và đọc nội dung

**Mục đích:** Nghiệm thu trên toàn bộ test và giải thích các thay đổi.
**Phụ thuộc:** T8. **Quy mô:** vừa.
**Files:** Run mới dưới `datacrawl/derived/`, `REPORT-chunk-cleaning-pipeline.md`.

- [x] Full run 20.000 record, audit 0 errors và hash input trước/sau giống nhau.
- [x] So sánh baseline theo ID/hash/độ dài/chunk metrics; đọc toàn bộ ca rỗng mới.
- [x] Review tối thiểu 10 ca/nhóm có dữ liệu theo plan; ghi ví dụ và mẫu số/giới hạn.

**Xác minh:** CLI/audit theo plan; evidence review độc lập với assertions mapping.

## T10 — Review và tài liệu

**Mục đích:** Chốt kết quả có thể tiếp tục hoặc tái lập ở phiên sau.
**Phụ thuộc:** T9. **Quy mô:** vừa.
**Files:** Report, spec, plan/todo, `docs_AI.md`.

- [x] Review diff giữ các thay đổi có sẵn; không đổi strategy/dependency ngoài đặc tả.
- [x] Report ghi version, đường dẫn tuyệt đối, lệnh, kết quả và giới hạn dữ liệu test.
- [x] Ghi bug/fix và thiết kế vào `docs_AI.md`; chỉ đánh hoàn thành task đã kiểm chứng.

**Xác minh:** Đối chiếu từng tiêu chí chấp nhận của spec với evidence ở report.

## Checkpoint D — Hoàn thành

- [x] Tất cả gates đạt hoặc phần chưa đạt được ghi rõ; không còn lỗi bảo toàn đã xác nhận.
- [x] Spec/report/docs/checklist thống nhất với code và kết quả thực chạy.
