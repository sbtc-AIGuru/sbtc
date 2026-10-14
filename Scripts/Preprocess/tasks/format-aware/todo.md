# Tiến độ format-aware chunking

- [x] T0: Hash/source + tests RED và xác định fixture cũ.
- [x] T1: Router/languages + protected sentence atoms.
- [x] T2: Profile blocks + exclusions có evidence.
- [x] T3: Packing/parent/overlap/additive metadata.
- [x] T4: CLI/version/resume + audit/tampering tests.
- [x] T5: 68 current regressions đạt; 20k output/audit0 + casebook32 + comparison.
- [x] T6: Review/mutation, kết quả và giới hạn trong report/docs_AI.md.

Kiểm chứng ngày14/10/2026. Output cuối `research/format-implementation-20261013/chunks-verified/`.
**Giới hạn chưa xác minh:** 3legacy classes không chạy do thiếu `datacrawl/test.jsonl`;
full discovery có3setup errors, không được gọi toàn suite xanh. Không bỏ/skip assertion.
F2/gold retrieval, full corpus, model-token budgets và forum thành công nằm ngoài phép nghiệm thu này.
