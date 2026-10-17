# Kế hoạch triển khai ICD-10 foundation

Ngày 16/10/2026. Người dùng đã duyệt SPEC-icd10-foundation.md và yêu cầu lập kế hoạch, thực hiện trong cùng lượt. Task list tại todo.md trong thư mục này; không ghi đè các kế hoạch BM25 còn mở.

## Phạm vi và nguyên tắc

Module mới `Retrieval/taxonomy/`, tests `test_taxonomy_*.py`, config nguồn riêng. Giữ corpus, resources/tokenizer và BM25 hiện hành. Download/derived data vào `artifacts/taxonomy/` với content hashes; không sửa source đã có. Chưa có evidence thì mapping/alias vẫn pending, không đủ gate thì chỉ audit_only/pilot_partial, không tự công bố core_ready.

## Dependency và thứ tự

T01 source acquisition proof + DTO/identity → T02 WHO parser/tree → T03 native adapters/crosswalk → T04 lexical senses/lookup → T05 validation/audit → T06 CLI/real-source build → T07 review/report. Kiểm tra từng lát bằng unittest có sẵn, tests lỗi/biên viết trước hành vi. Không dùng official queries/for_valid để tune.

## Các lát triển khai

1. **T01 — Source snapshot và identity.** Kiểm tra runtime bm25, khả năng truy cập official endpoints; lập cấu hình source đúng URL. Viết tests hash/edition/ID, source integrity, bounded archive path và refusal overwrite. Tạo models/source store; code trong 2–3 file và 1 test. Gate: pin source bytes, không giả hash/license/source availability.
2. **T02 — WHO vertical slice.** XML fixture độc lập chứa nested groups, inclusion/exclusion, reference và missing parent. Parse WHO ClaML/tabular, giữ raw/source nodes/rubrics, tạo canonical hierarchy/labels EN. Test cycles/orphans/D/H/chapter mapping/duplicate/modifier status. Gate: reconciliation toàn snapshot, không dựng parent theo prefix.
3. **T03 — Native source và mapping.** Adapter FHIR/structured JSON, bảng tabular native và PDF staging có locator; đọc XLS chỉ khi runtime đã có dependency phù hợp. Candidate matching chỉ tạo review queue. Crosswalk resolver kiểm accepted decisions/relations/projection paths. Gate: native source và canonical namespaces không bị trộn; unsupported format ghi failure thật.
4. **T04 — Lexicon và lookup.** Tạo official labels, lexical candidates có kind/usage, immutable reviews; hai normalization views, ambiguity registry, context/case/boundary guards. Tests đồng âm pending, casing, mixed Han/Latin, phủ định, nguồn exclusion. Gate: pending sense ngăn resolve giả; context-only không thành positive.
5. **T05 — Validation và audit.** F01–F12, coverage denominators, source reconciliation, runtime verified chỉ accepted, schema/normalization/review/FK checks. Semantic fixture tách development checks và holdout; dữ liệu do đọc nguồn xác lập, không lấy actual output làm expected. Performance đo cấu hình/timing thật, không dùng target làm kết quả. Gate: không freeze nếu thiếu semantic gold hoặc P0.
6. **T06 — CLI end-to-end.** fetch/build/validate/audit/freeze, resume fingerprint, atomic write, strict exit codes. Dùng các source thực có thể tải, tạo full-size data audit và review queues; smoke CLI bằng temp sources cùng test dữ liệu. Gate: thay input/hash/decision thì từ chối resume, output rõ incomplete/audit-only khi chưa đủ bằng chứng.
7. **T07 — Review và bàn giao.** Chạy focused suite rồi suite Retrieval nếu runtime cho phép, xem diff/module boundaries, kiểm nguồn/hash/count và đọc các record tiêu biểu. Báo cáo chỉ số thực/điểm còn thiếu, docs_AI.md/thaydoicongnghe.md, README/source catalog và lệnh tái lập. Giữ release gate, không gọi chưa reviewed là verified production.

## Rủi ro và cách xử lý

- URL WHO/BYT/NHC thay đổi hoặc bị chặn: discovery qua official landing page; lưu HTTP error, không dùng mirror lặng lẽ. Các phần không phụ thuộc vẫn triển khai/kiểm tra.
- XLS/PDF không máy đọc được: adapter giữ row/raw locator và quarantine; không đoán các cột hoặc quan hệ cha. Xem dependency hiện có trước khi cần thêm.
- Chỉ có raw label mà chưa có semantic crosswalk: source lexical entry có thể valid, nhưng canonical topic mapping tiếp tục abstain/pending.
- Test semantic chưa độc lập hoặc chưa đủ 200 ca: không giảm gate, audit ghi chưa đạt, freeze phải chặn.
- Repo sbtc có module Retrieval và nhiều file khác đang untracked: không switch/reset/commit toàn bộ working tree; chỉ sửa phạm vi mới và docs bắt buộc.

## Kiểm tra

Runtime dự kiến: `/home/tran-nhat-truong/miniconda3/envs/bm25/bin/python`, xác minh trước khi dùng. Lệnh focused: `python -m unittest discover -s sbtc/Scripts/Retrieval/tests -p 'test_taxonomy_*.py' -v`. Lệnh suite: `python -m unittest discover -s sbtc/Scripts/Retrieval/tests -p 'test_*.py'`; không đổi framework. CLI thật sẽ được ghi vào README sau khi có implementation.
