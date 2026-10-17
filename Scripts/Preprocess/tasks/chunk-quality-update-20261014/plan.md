# Kế hoạch triển khai — Chunk quality update (2026-10-14)

## Mục tiêu

Triển khai Gói A đã được duyệt theo đề xuất: loại placeholder lỗi crawler khỏi retrieval, sửa atom/chunk trên 500 units bằng các biên an toàn, gộp chunk dưới 50 units trong cùng vùng ngữ nghĩa; sau đó so sánh với baseline trên duy nhất `data_final/test_20k.jsonl` và đánh giá bảo toàn nội dung/ngữ nghĩa.

**Ngoài phạm vi:** Gói B (sửa classifier profile, TOC/UI và malformed link), recrawl, thay schema nộp bài, chạy lại toàn corpus. Không sửa/xóa `data_final/final_data.jsonl` hoặc `data_final/chunks_format_final/`.

## Khảo sát hiện trạng

- `chunking.py` giữ record failed crawl ở trạng thái `skipped`, nhưng không có trường `text: ""`; placeholder nằm trong `text` với `success=true` vẫn được chunk.
- `format_profiles.py` tạo sentence/structural atoms; bước nối `must_link_atom` có thể làm atom rất dài. `format_chunking.py` chỉ pack atom, nên atom vượt max có thể phát ra thành oversized child.
- Ngưỡng pack hiện là `ChunkConfig.max_units=300`; `count_units()` đếm chữ CJK và chuỗi alphanumeric, không phải word/token.
- `chunk_audit.py` tái tạo format atoms và yêu cầu biên child khớp atom; cần cập nhật auditor để kiểm tra các atom đã được repair, merge short, placeholder skipped và schema version mới.
- `test_20k.jsonl` có 20.000 records, 100 `success=false` và 2 record `success=true` chứa template `Crawl4AI Error:`. Đây là fixture duy nhất cho baseline, test, E2E và review.
- `tasks/plan.md` và `tasks/todo.md` đang có thay đổi/ghi nhận task trước; kế hoạch này nằm trong thư mục riêng để không ghi đè.

## Quyết định thiết kế

1. Tăng `PROFILE_VERSION` lên `format-v2`; giữ `ChunkConfig` 150/220/300/40 hiện hành. Checkpoint cũ không được resume vào code mới; mỗi lần chạy dùng output directory mới.
2. Matcher crawl lỗi chỉ nhận diện template đặc hiệu đã xuất hiện trong dữ liệu (prefix chính xác và các marker thân lỗi), không match chung từ “error”. Áp dụng marker placeholder cho strategy `format`.
3. Atom trên 500 units được chia theo thứ tự: heading/đoạn → câu → mệnh đề dấu câu an toàn ngoài protected span. Không tự cắt token số/liều/mã. Nếu không có biên an toàn, ghi `oversized_unresolved` rõ ràng, giữ nguyên source.
4. Atom 301–500 units không bị bẻ thêm ở đợt này; theo dõi riêng như soft oversize.
5. Gộp cặp/chuỗi ngắn dưới 50 khi cùng `parent_id`, `section_paths`, `section_roles`, `content_languages`; kết quả không vượt 300 units. Không qua Q/A, heading/section, ngôn ngữ, parent hoặc excluded region. Tài liệu/ngữ cảnh ngắn thật được giữ với lý do.
6. Chunk luôn là lát cắt liên tục verbatim từ cleaned source. Sau split/merge phải tính lại text, offsets, `chunk_order`, IDs, size, overlaps, short/oversize reasons và metadata. Auditor dựng lại atoms bằng cùng luật từ source, không tin metadata output làm bằng chứng.
7. Output ghi ở `data_final/chunks_format_v2_baseline_test20k/` (baseline trước sửa) và `data_final/chunks_format_v2_test20k/` (sau sửa). Hai thư mục này phải chưa tồn tại/đang rỗng; không ghi đè. Chỉ dùng full-corpus output nếu có yêu cầu riêng.

## Dependency graph

```text
Snapshot baseline (test_20k)
        ↓
Regression cases from test_20k
        ↓
Error placeholder handling ───────────┐
Oversized atom repair ─────────────────┼→ Output/auditor v2 → Test_20k rerun → Semantic review/report
Short chunk merge ─────────────────────┘
```

## Task list

### T0 — Baseline trước thay đổi (hoàn tất)

- Ghi input SHA-256 và chạy format pipeline hiện hành trên `data_final/test_20k.jsonl` vào thư mục baseline mới.
- Lưu summary/audit và trích các record có error marker, child >300/>500, child <50 để so sánh.
- **Files/artifacts:** `data_final/chunks_format_v2_baseline_test20k/`, baseline summary JSON dưới thư mục task này.
- **Kiểm tra:** 20.000 records, `errors=0`, auditor báo `checked=19.900`, `skipped=100`, `errors=0`; input SHA không đổi.
- **Kết quả:** xem [`baseline-summary.json`](baseline-summary.json). Baseline có 2 error placeholders vẫn `ok`, 7 record có child >500 (tối đa 2.760), 24 child >300 và 2.036 child <50. Không có cặp child <50 đủ điều kiện gộp trong fixture nếu giữ ràng buộc cùng parent/path/role/language; sẽ kiểm tra merge helper trên các atom kề nhau trích từ record thật.

### T1 — Regression tests từ fixture thật

- Thêm test cho hai placeholder lỗi thật, record failed crawl, các atom >500 và các chuỗi chunk ngắn tìm được trong baseline.
- Ghi trước các invariants source slice, `doc_id`, URL, thứ tự, coverage và biên không cắt protected spans.
- **Files:** `tests/test_chunk_formats.py`.
- **Kiểm tra:** focused unittest trên records được đọc từ `data_final/test_20k.jsonl`; test mới phải đỏ trước implementation.

### T2 — Error placeholder và empty text

- Thêm matcher template hẹp; với format run, cả `success=false` và placeholder `success=true` thành skipped với `text=""`, không parent/child.
- Cập nhật auditor nhận diện lỗi từ input raw/cleaned source và xác nhận empty text/reason, identity và không có chunks.
- **Files:** `Scripts/Preprocess/chunking.py`, `Scripts/Preprocess/format_profiles.py` hoặc helper format phù hợp, `Scripts/Preprocess/chunk_audit.py`, `tests/test_chunk_formats.py`.
- **Kiểm tra:** T1 error tests chuyển xanh; mẫu nội dung thường không bị matcher coi là lỗi; input raw không đổi.

### T3 — Sửa atom quá cỡ

- Chia atom >500 tại paragraph/heading/câu; chỉ dùng clause fallback khi mỗi phần vẫn giữ protected expressions. Atom không chia an toàn phải được ghi `oversized_unresolved`.
- Cập nhật atom metadata/version và auditor để xác minh phân đoạn được tái tạo từ source, không dựa vào cờ output giả.
- **Files:** `Scripts/Preprocess/format_profiles.py`, `Scripts/Preprocess/chunk_audit.py`, `tests/test_chunk_formats.py`.
- **Kiểm tra:** mọi oversize trong fixture giảm hoặc được gắn unresolved; source slices phủ đủ nội dung; không boundary nào cắt protected span.

### T4 — Gộp chuỗi chunk dưới 50

- Post-process child ngắn chỉ trong semantic signature tương thích, union liên tục và tổng ≤300 units; giữ mẩu ngắn thật có reason.
- Cập nhật metadata offsets/ID/order/overlap/reasons và auditor.
- **Files:** `Scripts/Preprocess/format_chunking.py`, `Scripts/Preprocess/chunk_audit.py`, `tests/test_chunk_formats.py`.
- **Kiểm tra dự kiến:** giảm số child dưới 50 so với baseline mà không vượt biên region/role/language/section. **Kết quả thực tế:** không có chuỗi tự nhiên đủ điều kiện trong fixture; helper được unit test nhưng count `<50` là 2.036 → 2.037 do một câu 15-unit được tạo/giữ riêng trong `doc_id=4057861`. Chỉ tiêu giảm short chunk không đạt và được báo riêng, không nới semantic guards.

### T5 — Tái chạy, audit và so sánh ngữ nghĩa

- Chạy format v2 trên tất cả 20.000 dòng, audit toàn bộ; tạo phân bố và so sánh baseline trước/sau.
- Đọc các record thực bị split/merge và các exception; xác nhận text là source slice, không mất mệnh đề/section và không có mẩu heading/context bị tách sai.
- **Artifacts:** `data_final/chunks_format_v2_test20k/`, summary/audit và report `REPORT-chunk-quality-update-20261014.md`.
- **Kiểm tra:** 20.000 record, 0 audit errors, hash fixture giữ nguyên; báo riêng F2 chưa đánh giá nếu thiếu gold labels.

### T6 — Tài liệu và review

- Cập nhật đề xuất thành trạng thái triển khai; ghi các quyết định, lỗi/fix, tradeoff vào `docs_AI.md`; lưu lệnh tái lập/đường dẫn output tuyệt đối trong report.
- Rà diff chỉ gồm phạm vi Gói A; giữ nguyên thay đổi có sẵn của người dùng và không stage/commit.
- **Kiểm tra:** spec/plan/report/docs khớp implementation và test output; không sửa full-corpus artefact.

## Kết quả thực hiện

- T1–T3: regression test lấy dữ liệu thật; test RED trước code, sau đó matcher lỗi, repair quá cỡ và empty-text audit đều PASS.
- T4: merge helper và auditor provenance PASS; không có merge thật đủ điều kiện trong 20k fixture. Short chunk count không cải thiện.
- T5: CLI format-v2 xử lý 20.000 dòng trong 190,4 giây; 19.898 `ok`, 102 `skipped`, 0 runtime errors. Auditor: `checked=19898`, `skipped=102`, `errors=0`.
- Kích thước lớn nhất 2.760 → 494 units; child >500: 7 → 0; child >300: 24 → 22. Covered non-whitespace bằng source cho các record còn index; hai error placeholder bị bỏ khỏi index có tổng 868 ký tự non-whitespace.
- Bộ test đã chạy: `python -m unittest sbtc.tests.test_chunk_formats sbtc.tests.test_chunk_format_streaming` — 75 tests PASS. Summary đầy đủ trong `comparison-summary.json`; nhận xét ví dụ và giới hạn ngữ nghĩa trong `../../REPORT-chunk-quality-update-20261014.md`.
- Profile-v2 output chỉ là derived test artifact. Không sửa `data_final/final_data.jsonl`, `data_final/chunks_format_final/` hoặc dữ liệu crawl; chưa chạy toàn corpus. Chưa có gold labels để xác định F2.

## Rà soát rủi ro

| Rủi ro | Cách kiểm soát |
|---|---|
| False positive error matcher | Match prefix + signature hẹp; kiểm tra record thường trong cùng test fixture. |
| Bẻ câu/biểu thức y khoa | Paragraph/heading trước; sentence; clause cuối; bảo vệ số-liều/ngoặc; unresolved review nếu không an toàn. |
| Merge làm mất ranh giới | Cùng parent/path/role/language; giới hạn union ≤300; auditor kiểm coverage và source slice. |
| Không đo được cải thiện retrieval | Dùng proxy chất lượng cấu trúc/coverage và đọc ngữ cảnh; không tuyên bố F2 khi không có gold. |
| Output test ghi đè dữ liệu | Hai thư mục version mới, preflight bắt buộc vắng/rỗng; raw/output hiện hành chỉ đọc. |

## Lệnh dự kiến

```bash
python -m sbtc.Scripts.Preprocess.chunk_cli \
  data_final/test_20k.jsonl data_final/chunks_format_v2_baseline_test20k \
  --strategy format --workers 2 --progress-every 2000

python -m sbtc.Scripts.Preprocess.chunk_cli \
  data_final/test_20k.jsonl data_final/chunks_format_v2_test20k \
  --strategy format --workers 2 --progress-every 2000

python -m sbtc.Scripts.Preprocess.chunk_audit \
  data_final/test_20k.jsonl data_final/chunks_format_v2_test20k
```

Chạy command với đường dẫn tuyệt đối sau khi kiểm tra output directory chưa có. Không chạy full test suite trên corpus khác; các focused test mới phải đọc fixture duy nhất này.
