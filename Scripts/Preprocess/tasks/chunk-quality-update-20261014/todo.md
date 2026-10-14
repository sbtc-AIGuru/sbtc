# Checklist — Chunk quality update

- [x] T0 — Baseline format-v1 trên `data_final/test_20k.jsonl`; lưu SHA, summary, audit và nhóm ca cần so sánh.
- [x] T1 — Regression tests dùng record thật từ `test_20k.jsonl`; xác nhận đỏ trước sửa.
- [x] T2 — Error placeholders tạo `skipped`, `text=""`; auditor kiểm tra status/reason mới.
- [x] T3 — Repair atom trên 500 units theo biên an toàn; unresolved có provenance tường minh.
- [x] Checkpoint A — Placeholder và oversize đạt source/identity/coverage invariants.
- [x] T4 — Short-merge helper chỉ gộp chuỗi `<50` cùng semantic signature, tối đa 300 units. Kết quả trên fixture: không có chuỗi đủ điều kiện; short count 2.036 → 2.037 nên chỉ tiêu giảm chưa đạt.
- [x] Checkpoint B — Test kiểm tra không gộp qua parent/role; auditor kiểm tra provenance, spans và source continuity.
- [x] T5 — V2 đủ 20.000 dòng; auditor `0 errors`; đánh giá 7 record quá cỡ và placeholder thật. Không có merge tự nhiên để đọc.
- [x] T6 — Báo cáo, đề xuất, `docs_AI.md` và summary được cập nhật; dữ liệu nguồn và output cũ giữ nguyên.

## Kết quả kiểm thử / đánh giá

- `python -m unittest sbtc.tests.test_chunk_formats sbtc.tests.test_chunk_format_streaming`: 75 tests, PASS.
- V2: 20.000 records, 19.898 ok, 102 skipped, 0 runtime errors; audit `checked=19.898`, `skipped=102`, `errors=0`.
- Output: `data_final/chunks_format_v2_test20k/`; baseline: `data_final/chunks_format_v2_baseline_test20k/`. Cả hai dùng duy nhất `data_final/test_20k.jsonl` với SHA-256 `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
- So sánh số liệu và giới hạn diễn giải tại `comparison-summary.json` và `../../REPORT-chunk-quality-update-20261014.md`.
