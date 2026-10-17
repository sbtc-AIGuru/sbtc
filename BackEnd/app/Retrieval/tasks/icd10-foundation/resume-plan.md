# Kế hoạch tiếp tục — 17/10/2026

Người dùng đã yêu cầu làm tiếp; lệnh pause cũ kết thúc. Không đổi scope/schema dữ liệu nền hoặc tích hợp retrieval.

## Bằng chứng lúc nối lại

- Run003 khớp code/data hash; cấu trúc passed, profile audit_only.
- Audit 45 ca development được thực thi với expected giữ nguyên. VI/ZH chưa có runtime verified; EN có 3 ca đếm term nằm trong tên dài hơn như một bằng chứng độc lập.
- Benchmark cũ báo RSS ~1.799 MB dù matcher chạy trong subprocess; thí nghiệm độc lập xác nhận `getrusage.ru_maxrss` giữ đỉnh từ parent qua fork/exec, còn `/proc/self/status` phản ánh address space mới. Không đổi target 500 MB.

## Các bước có kiểm chứng

1. **A — Evidence span và phép đo.** Regression trước sửa: giữ nested matches nhưng đánh dấu dependent, cùng span khác sense vẫn ambiguous; audit so target dựa primary evidence, không đổi expected để đạt. Đo VmHWM trên Linux, lưu rusage thô và nguồn đo; thêm CPU/runtime và chuỗi memory growth. Chặn metric thiếu support/NaN.
2. **B — Review/runtime gates.** Kiểm lexical review thực sự áp dụng cho direct self-link usage; kiểm source review/extraction; không auto nhận PDF/same-code crosswalk. Bổ sung regression cho source/entry/link/label decision đúng đối tượng, accepted state, projection path, ambiguity registry. Pending competitor vẫn chặn false resolve.
3. **C — CLI và freeze.** Kiểm source/code thay đổi giữa build, audit integrity, partial audit, safe paths, cùng build audit mới phải có thư mục riêng thay vì ghi đè. Fixture kiểm đường freeze thành công và bất biến release. Consumer kiểm hash/profile/normalizer. Không freeze data thật khi thiếu gate.
4. **D — Bộ đánh giá.** Đọc nguồn để chuẩn bị đủ >=200 ca và >=50 mỗi ngôn ngữ, đa dạng kinds/ambiguity/mixed script/nguồn thực; expected không được lấy từ matcher. Bộ này là bản ứng viên local, tách 45 ca development; không tự ghi approved_by hoặc gọi là independent approved holdout. Chỉ dataset được duyệt mới đủ gate release.
5. **E — Build/audit thật và bàn giao.** Chốt code rồi build run mới, đối soát đủ nguồn, chạy unit/contract suite và audit; giải thích lỗi/coverage chưa đạt. README, source catalog, implementation report, docs_AI.md/thaydoicongnghe.md; checklist phân biệt code hoàn tất với dataset còn chờ review.

## Giới hạn

Giữ nguyên source bytes, corpus và run001–003; dữ liệu mới vào run mới. Không dùng for_valid/official queries. Không gọi closed LLM để sinh dữ liệu production hoặc tự ký quyết định chuyên môn. Các test/gold local chưa được duyệt không tự biến thành nguồn official, training data hoặc nhãn dự đoán.
