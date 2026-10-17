# ICD-10 foundation — tiến độ

**Đã tiếp tục theo yêu cầu người dùng ngày 17/10/2026.** Checkpoint trước khi tiếp tục: [PAUSED.md](PAUSED.md). Phần việc còn lại theo [resume-plan.md](resume-plan.md).

- [x] P00: người dùng duyệt đặc tả và yêu cầu triển khai; lập plan scoped riêng.
- [x] T01: DTO/identity, source snapshots và tests (9 ca identity/source đã qua).
- [x] T02: WHO parser/canonical tree; full snapshot parse, hierarchy reciprocal đúng; tabular giữ chênh lệch để audit.
- [ ] T03: native adapters/candidate crosswalk/accepted projection và tests.
- [ ] T04: lexicon senses/normalization/ambiguity/lookup và tests.
- [ ] T05: F01–F12 validator, coverage, semantic/performance audit và release gates.
- [ ] T06: CLI end-to-end, source thật, resumability/integrity và data report.
- [ ] T07: code review, regression suite, README, source catalog và nhật ký bắt buộc.

Chỉ đánh hoàn tất từng task khi có bằng chứng/lệnh kiểm tra. Dữ liệu chưa đủ gate ghi đúng trạng thái; không tự tích hợp vào tokenizer/BM25.

Checkpoint khi dừng: code các T03–T06 đã được viết và có kiểm thử từng phần; chưa đánh xong vì còn audit/review/đánh giá đầu ra. Build mới nhất `artifacts/taxonomy/runs/foundation-20261017-003` exit 0; 43 unit/contract tests PASS. Chưa audit semantic/performance, chưa có holdout >=200 được duyệt, chưa freeze và chưa tích hợp. T07 chưa hoàn tất.
