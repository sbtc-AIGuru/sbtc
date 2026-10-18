# Kế hoạch: Bộ test công bằng cho analyzer đa ngôn ngữ

## Mục tiêu

Triển khai `SPEC-fair-medical-analyzer-testset.md`: fixture tổng hợp độc lập với output hiện tại, cân bằng VI/EN/ZH, kèm runner chẩn đoán theo ngôn ngữ, nhóm rủi ro và kiểu đầu vào. Không sửa analyzer/lexicon hoặc dữ liệu corpus.

## Quyết định

- Giữ `tasks/plan.md` và `tasks/todo.md` của công việc BM25 hiện hữu; dùng plan/checklist riêng cho task này.
- Fixture JSONL chứa kỳ vọng tối thiểu có thể thay thế tương đương, negative anchors và nhãn `contract`/`challenge`; không lưu snapshot toàn bộ token output.
- Runner chạy analyzer thật ở cả hai chế độ index/query; khác biệt `broad` được phép, còn `contents`, `exact`, `anchors` cần nhất quán.
- Diagnostic mặc định luôn liệt kê mismatch nhưng exit thành công để không đánh tráo dữ liệu test thành tuyên bố code đã đạt; `--strict` fail khi có mismatch ở ca `contract`.
- Chỉ dùng thư viện và runtime Retrieval hiện tại. Không đọc `for_valid/`, không lấy ví dụ từ corpus thật, không thêm dependency.

## Các bước

1. Hoàn thiện fixture 90 ca: 30/ngôn ngữ; sáu nhóm rủi ro, sáu kiểu đầu vào, sáu concept đối chiếu ba ngôn ngữ; expectations được viết từ hợp đồng ngôn ngữ.
2. Thêm validator/runner: schema, số lượng, cân bằng, liên kết concept, assertion fields, parity hai chế độ, thống kê và mismatch chi tiết.
3. Chạy kiểm tra fixture và runner diagnostic trên analyzer hiện tại; phân loại mismatch nhưng không đổi expectation để khớp output.
4. Chạy suite Retrieval hiện có; rà diff và ghi quyết định/khó khăn/phát hiện vào `docs_AI.md`.

## Tiêu chí nghiệm thu

- Fixture có đúng 90 record hợp lệ, mỗi ngôn ngữ 30; mỗi language × risk group có 4 ca; mỗi language × style có 5 ca.
- Sáu paired concepts đều có VI/EN/ZH; ít nhất hai concept ngoài seed không bị đòi anchor hiện chưa có.
- Runner báo lỗi theo đúng ca và lát cắt, không nuốt mismatch; `--strict` trả non-zero cho contract mismatch.
- Ca diagnostic không chạy trên dữ liệu thi/for_valid/corpus, không chỉnh analyzer hoặc nguồn.
- Existing Retrieval tests và validator mới đạt; diagnostic report chỉ là đánh giá analyzer, không phải benchmark BM25/F2.

## Rủi ro

- Hệ thống tokenizer có nhiều cách phân đoạn hợp lệ: dùng alternatives cho các token thiết yếu, tránh kỳ vọng toàn bộ chuỗi token.
- Ca `challenge` có thể phơi bày thiếu hụt hiện tại: report tách riêng để không che lỗi, nhưng không sửa behavior trong task này.
- Ví dụ tổng hợp không đại diện đầy đủ web crawl: đa dạng hóa cấu trúc và nêu rõ giới hạn; bộ này không thay thế audit mẫu corpus.

## Kết quả thực hiện

- Fixture: 90/90 hợp lệ; 30 mỗi ngôn ngữ; mỗi risk group có 4 ca; mỗi input style có 5 ca/ngôn ngữ.
- Retrieval unit/integration suite: 34 tests passed.
- Diagnostic: 180 analyzer runs, 6 mismatch cases (4 contract, 2 challenge). Strict gate xác nhận exit code 1 trên contract mismatches.
- Findings và cách chạy: `../REPORT-analyzer-testset-20261015.md`; full token details: `../../../../artifacts/retrieval/analyzer-testset-20261015/report.json` from the Retrieval directory.
- Không sửa analyzer/lexicon/corpus; mismatch được giữ lại để tạo mục tiêu cải thiện riêng.
