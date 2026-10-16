# Checklist: Bộ test công bằng cho analyzer

- [x] Soạn 90 synthetic cases cân bằng theo ngôn ngữ, nhóm rủi ro và kiểu văn bản.
- [x] Thêm runner/validator hỗ trợ diagnostic và `--strict`, kiểm tra cả index/query mode.
- [x] Chạy schema/balance validation và diagnostic; lưu lại mismatch theo lát cắt.
- [x] Chạy Retrieval unit/integration suite hiện có.
- [x] Rà soát thay đổi và ghi design/fixes/findings trong `docs_AI.md`.

Kết quả: 34 Retrieval tests đạt. Diagnostic chạy 180 analyzer passes trên 90 ca: 4/69 contract mismatches và 2/21 challenge mismatches. Báo cáo: `Scripts/Retrieval/REPORT-analyzer-testset-20261015.md` và `artifacts/retrieval/analyzer-testset-20261015/report.json`. Analyzer chưa được sửa.
