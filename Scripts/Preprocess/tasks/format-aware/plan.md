# Kế hoạch triển khai chunking theo format

Đã được người dùng duyệt ngày 13/10/2026 qua yêu cầu lập kế hoạch, triển khai và test.
Đặc tả: `../../SPEC-format-aware-chunking.md`. Kế hoạch cleaning cũ đã hoàn thành được giữ nguyên.

## Phạm vi và đầu vào

- Python stdlib, dùng cleaner hiện có; không đổi crawler hay dữ liệu nguồn.
- Strategy mới `format`, version `format-v1`; giữ `hybrid` làm baseline và cho phép đối chiếu.
- Mọi test và benchmark lấy từ `data_final/test_20k.jsonl`; SHA-256
  `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
- Output mới: `research/format-implementation-20261013/`; baseline cũ giữ nguyên.
- Không khẳng định tăng F2 khi chưa có nhãn truy hồi. Forum không có mẫu thành công: fallback và ghi thiếu coverage.

## Các bước và điều kiện đạt

1. **T0 — Cố định nguồn và test tái hiện.** Lưu hash/config, đọc ca thật; viết test số liệu,
   nhãn–body, abstract ngắn, QA, bilingual, chương sách, conference. Chạy RED trước sửa.
   Test cũ tham chiếu tập đã mất: không bỏ assertion; xác định fixture tương đương từ tập hiện tại.
2. **T1 — Router và atom nguyên bản.** Detector theo evidence trong text, domain chỉ hỗ trợ;
   source language tách content language. Giữ sentence, dấu ngoặc, số và label–body; không chẻ clause cho overlap.
   Test: các ca `37,5`, `(1:1)`, `$10,100`, `11,6`, `ES:` không bị cắt; `24.7mg` không thành heading.
3. **T2 — Profile và exclusions.** Narrative/research/QA/catalogue/book/structured list/fallback.
   Bio bác sĩ có marker đôi; TOC/menu chỉ loại theo layout rõ; quote `原文 →` giữ lại.
   Test: provenance exact slice, không mất body, không tạo title/label riêng, entries không bị cắt.
4. **T3 — Packing và metadata.** Parent theo vùng liên tục, không băng exclusions, answer hoặc language boundary.
   Giữ span thật, title/question metadata riêng; merge phần nhỏ nếu không có hard boundary.
   Sentence/structural atom >300 giữ nguyên và đánh dấu; overlap whole sentence có lý do khi ngoài 30–50.
5. **T4 — CLI và audit.** Version/fingerprint/checkpoint; reject resume khác version trước recovery.
   Audit offset/hash/ID/coverage/atom/protected span/metadata và các output bị sửa có chủ ý.
   Test streaming workers 1/2, resume/pending recovery, schema lỗi và input malformed.
6. **T5 — Regression và chạy 20k.** Chạy toàn bộ suite chunk liên quan; chunk 20k vào folder mới,
   audit toàn bộ, so sánh baseline theo profile/ngôn ngữ/size/overlap/oversize/boundary.
   Rà ca tốt/xấu thật; lưu casebook trước–sau và danh sách còn cần review.
7. **T6 — Review và tài liệu.** Review code và output, sửa nguyên nhân lỗi, ghi `docs_AI.md`.
   Report có lệnh chạy, đường dẫn, kết quả, nhược điểm và phạm vi chưa kiểm chứng.

## Các bất biến bắt buộc

- ID nguyên bản là int; `chunk_order` liên tục; mapping URL/doc_id chính xác.
- `chunk_text == cleaned_source[start:end]`, không thêm title/question vào text.
- Union children + exclusions phủ toàn bộ ký tự không trắng; exclusions có evidence/provenance.
- Không cắt giữa expression, label–body hay sentence atom; oversized phải có lý do kiểm được.
- Output và resume deterministic; bản nguồn và baseline không thay đổi hash.
- Router không suy ra Vietnamese chỉ vì tên người có `ă`/`đ`; unknown dùng `und`.

## Ca lỗi/biên

Failed/empty/cleaned-empty, id bool/string, raw malformed, version mismatch, tampered chunks,
zero overlap có lý do, overlap=0 theo config, parent budget nhỏ, sentence quá dài,
unbalanced brackets, bilingual changes, flattened table/TOC thiếu body, uncertain duplicate,
quoted snippets, title dài và abstract/QA ngắn.
