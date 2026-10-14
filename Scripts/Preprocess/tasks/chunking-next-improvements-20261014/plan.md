# Kế hoạch triển khai cải thiện chunking tiếp theo

Người dùng duyệt ngày 2026-10-14 theo `PROPOSAL-chunking-next-improvements-20261014.md`, bao gồm phạm vi cleaner `Scripts/Clawler/verbatim.py`. Dữ liệu test duy nhất: `data_final/test_20k.jsonl`, SHA-256 `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.

## Hợp đồng thực hiện

- Giữ document ID/URL, source slices và budget150/220/300/40; hard repair500. Không thay dữ liệu crawl/corpus hoặc ghi đè output hiện có.
- Cleaner mới `verbatim-v5`, profile mới `format-v3`; checksum/checkpoint tách các phiên bản. Snapshot v2 và checkpoint nằm trong `baseline-code/`, `baseline-manifest.json`.
- TOC detector nhận khối có marker explicit và ít nhất3entry lặp lại ở body theo thứ tự; phải có body thực sự, không xóa trang index-only. Evidence/span lưu trong exclusion hiện có.
- Research router dùng loại nhãn bổ trợ trong body trước references, hoặc prior PubMed; catalogue yêu cầu field/template evidence ngoài TOC, không dựa chỉ trên3heading phổ biến VI.
- Link recovery chỉ unwrap label khi phần target bị vỡ rõ là URL/anchor. Scan tối đa4096ký tự trên cùng dòng; giữ text sau newline, dấu/công thức ngoặc mơ hồ và warning.
- Scanner chính và oversized fallback dùng một guard period chung; không thêm nội dung vào chunk.
- Thêm diagnostic counters (over300/over500/unresolved, fallback, warning affected records, short-under50 và overlap bins). Auditor kiểm tra provenance merge nghiêm hơn.
- Experiment packing: thêm `format_overlap_policy` cuối `ChunkConfig`, mặc định `post_pack`; CLI `--format-overlap-policy post_pack|reserve`. Giá trị được fingerprint bằng config; legacy strategies giữ packing hiện tại. Reserve chỉ re-pack nguyên atom cùng parent, không tạo mẩu<50 mới khi có thể tránh, không nới hard boundaries/max300.
- Benchmark hai candidate v3 cùng code: `data_final/chunks_format_v3_test20k/` (post_pack), `data_final/chunks_format_v3_reserve_test20k/` (reserve). Output directories phải chưa có; baseline là output v2 đang tồn tại với fingerprint khớp code đầu task.

## Các bước và kiểm tra

1. **Khảo sát/snapshot:** xác nhận baseline fingerprint; tìm positive/negative cases trong test20k cho TOC, refs-only labels, catalogue, broken links, sentence abbreviations,9remainders. Lưu inventory/casebook IDs; báo riêng những historical IDs vắng fixture.
2. **Regression RED:** thêm suite riêng `tests/test_chunk_next_improvements.py` từ fixture thật hoặc markup/schema mutation có ghi rõ. Test giữ cả ca không được strip/route/merge; không đổi test cũ để che behavior sai.
3. **Slice guard/metrics:** unify period predicate; diagnostics split/unresolved/warning-docs/overlap; audit source-invariant và merge provenance; chạy focused tests.
4. **Slice structure/router:** TOC scan/exclusion + classifier evidence; chạy positives/negatives và current format suite; đọc source các case đổi profile hoặc loại span.
5. **Slice cleaner:** bounded recovery malformed URL targets, version bump và test idempotence/label preservation/body/non-link parentheses. Shared cleaner ảnh hưởng legacy strategies nên giữ tests regression nguồn test20k, không sửa fixture legacy đang thiếu.
6. **Slice overlap experiment:** reserve packing + meaningful fixture-derived tests, source-coverage/parent/budget checks. Giữ default post_pack để experimental policy opt-in; không quyết định default chỉ theo metric overlap.
7. **Kiểm tra tích hợp:** chạy unittest format + streaming + new suite. Chạy CLI20k hai candidate, audit đầy đủ bằng code hiện tại. Không mixed/resume giữa versions.
8. **Benchmark/review:** so3outputs (v2/v3post/v3reserve), profile transitions, cleaned-source differences, TOC removed text, link repairs, overlap distribution/chunk count/bytes/runtime/shortness. Kiểm tra source slice, coverage, token/numeric conservation ở từng nhóm; đọc mọi case đổi profile/exclusion qua compact casebook. F2 chưa có gold nên báo quality proxies, không gọi là retrieval benchmark có nhãn.
9. **Docs/release review:** report + manifests + plan/todo +docs_AI; đề xuất policy mặc định dựa evidence, không stage/commit trong task này.

## Ca kiểm thử tối thiểu

- TOC+body lặp, marker-only/index-only, short headings là nội dung thật, English/VI markers, punctuation/number prefixes, body tự tham chiếu không phải TOC.
- Catalogue drug monograph positive, health prose có heading chung negative; research distinct roles positive, repeated single label/ref labels negative, PubMed unstructured positive.
- URL target thiếu`)` có label rõ; target mơ hồ không phải URL; newline/body preserved; nested/escaped/code/chemical brackets; cleaner idempotence; warning event vs document count.
- Period abbreviations/initials/decimal từ corpus; fallback không đảo guard scientific abbreviations; preserved numeric spans/source slices.
- Reserve whole-atom overlap khi body capacity cần dịch, zero-overlap config, custom small budgets, oversized atom, parent boundary, no new uncovered text hoặc infinite progress loop.
- Merge valid source-derived output được auditor chấp nhận; IDs/order/span/context/source count/provenance bị sửa được từ chối.

## Nghiệm thu

- Hash fixture nguyên vẹn;20krecords mỗi candidate;0runtime/audit errors; mọi child từ đúng source/doc, mọi protected span giữ đúng.
- Cleaner changes có evidence, label/body còn nguyên và không strip syntax mơ hồ. TOC exclusions có duplicate-body mapping kiểm chứng độc lập; index-only không bị xóa.
- Profile fixes có testcases labeledmanual, báo toàn bộ transition counts và exceptions; uncertainty chỉ chẩn đoán, không đặt targetgiảm giả.
- Reserve báo cả lợi ích overlap và chi phí chunk count/bytes, giữ defaultpost_pack nếu chưa chứng minh quality tradeoff tốt.
- Những mục không có natural fixture coverage/gold được nêu rõ, không tuyên bố F2 tăng.

## Những điều chỉnh có bằng chứng trong triển khai

- Link vỡ thực tế có nhiều `[[label]](` target rỗng. Recovery thêm điều kiện label narrative rõ/nested, giữ literal đơn vị/ngoặc mơ hồ. Warning raw vẫn giữ để truy vết; metric riêng theo dõi recovery và residual syntax.
- Bước router đầu từng làm sai positive279805; giữ lại catalogue khi có marker Bệnh thường gặp/Nội dung chính và ít nhất3field lặp thành template, vẫn chặn prose chỉ có heading thông thường.
- Review run01 phát hiện monograph thuốc VI bị fallback quá mức. Revision r2 thêm evidence hoạt chất/nhà sản xuất/bào chế + dosing/adverse/interactions/contraindications ở body, cùng positive fixtures759366/764534/193224/182511. Mask declaredTOC khỏi routing dù chưa có đủ body để loại khỏi retrieval; index-only vẫn giữ source.96tests PASS sau sửa.
- Run01 giữ nguyên tại `chunks_format_v3_test20k/`, `chunks_format_v3_reserve_test20k/`, snapshot `code-release/` và các JSON ở task root. Kết quả r2 ghi riêng `chunks_format_v3_r2_test20k/`, `chunks_format_v3_r2_reserve_test20k/`, `results-r2/`, snapshot `code-r2/`; không resume/ghi đè run01.
- Review r2 phát hiện food recipe499246 dùng `Thành phần:` gây falsepositive drugidentity. R3 giới hạn identity thuốc, thêm regression negative;97tests PASS. Final outputs: `data_final/chunks_format_v3_r3_test20k/`, `data_final/chunks_format_v3_r3_reserve_test20k/`; final snapshots `code-r3/`, `code-r3-manifest.json`; evidence `results-r3/`. R1/r2 được giữ để review, r3 thay chúng làm candidate cuối.
- Kết quả benchmark và các đánh đổi được ghi tại `../../REPORT-chunking-next-improvements-20261014.md`; hai fullaudit finalr3 đạt0errors,20.000records mỗi output. Source/code/checkpoint hashes khớp;97testsPASS và diff--checkexit0. Defaultpost_pack giữ nguyên; reserve là candidateopt-in, chưa có gold để chọn policy theo retrievalF2.
