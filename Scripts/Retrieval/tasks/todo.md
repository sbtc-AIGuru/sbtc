# Tiến độ BM25 mới

## Bỏ folded và Rolling Staging — implementation v1

- [x] Khảo sát code/runtime; đặc tả và kế hoạch được duyệt.
- [x] No-folded profile/schema v2, direct Lucene writer, byte-bounded rolling stage, durable receipts, recovery, CLI/config.
- [x] Unit/integration suite và strict analyzer fixture trên code hiện tại.
- [ ] Full test20k bulk-vs-rolling A/B/C + 1.200-query comparison, nếu disk gate đạt.
- [ ] Đo capacity/RAM/throughput full-scale; qrels relevance metrics chỉ khi có bộ nhãn độc lập được phép dùng.
- Tài liệu: [đặc tả](../SPEC-no-folded-rolling-staging.md), [plan](no-folded-rolling-staging/plan.md), [todo riêng](no-folded-rolling-staging/todo.md). Full benchmark/capacity gate chưa hoàn tất.

## Tiến độ nền đã có

- [x] Viết đặc tả và kế hoạch từ thông tin mới; không đọc/import BM25 archive.
- [x] T01 Runtime riêng, DTO/interfaces, Python 3.12/full JDK21.
- [x] T02 Lexicon provenance + Aho-Corasick; 12 local seed concepts.
- [x] T03 VI/ZH multi-granularity, OpenCC, bảo toàn IDs/units.
- [x] T04 EN Krovetz, selected inflection/spelling aliases, literal acronym/biomarker.
- [x] T05 Pointer/stream/identity/source hashes; giữ nguyên source text/order.
- [x] T06 Resume/fingerprint/atomic shard commit, capacity estimator.
- [x] T07 Build sáu Lucene partitions; integration search thật trên ba ngôn ngữ test20k.
- [x] T08 Query projection + translation-cache provenance, missing-translation/numeric warnings.
- [x] T09 Candidate search độc lập/channels/RRF + batch API.
- [x] T10 Reranker hydrate API/export JSON+ZIP; evaluator BTC chuẩn LCS/macro.
- [x] Checkpoint B1: prepare/build đủ test20k release, six partitions counts khớp; integrity 62.941 chunks đạt.
- [x] Checkpoint B2: 1.200 searches/12 mechanical queries, báo cáo REPORT-bm25-new-test20k.md và candidate/demo export artifacts. Không phải relevance benchmark.
- [ ] T11 Từ điển y khoa production đủ coverage có giấy phép và ontology review. Starter không đủ.
- [x] T12a Adapter local NLLB, checksum/offline/eligibility/cache contract; chưa provision model thật.
- [ ] T12b Inference model/cache thật, kiểm ngữ nghĩa và benchmark latency; dependencies neural riêng chưa lock.
- [x] T12c1 Người dùng chốt whitelist active **1.220.598 URL** ngày 15/10/2026 cho full và xuất bài; hash khớp index test20k hiện có.
- [ ] T12c2 Capacity/RAM/full readiness: disk gate chưa đạt; chưa chạy full corpus.

Kiểm thử hiện tại: 30 tests đạt, log `artifacts/retrieval/tests-final.log` (13,785 giây), gồm race regression, hash/stat mutation, ID/URL/FK/order/offset failures, publish recovery. Integrity toàn bộ 62.941 chunks release đạt. Không đọc `for_valid`; không suy diễn Recall/F2 từ test cơ học. Thiết kế/khó khăn/fixes ghi `docs_AI.md`.
## Curation resource đa ngữ

- [x] C01 Đặc tả được người dùng duyệt; giữ nguyên sáu nguồn.
- [x] C02 Converter deterministic sinh terms_vi/en/zh, aligned candidates, ID map, external ID review, seed comparison, manifest và report.
- [x] C03 Rà mẫu candidate; mở rộng rule để các mẩu câu/ngữ cảnh đã phát hiện nằm trong review.
- [x] C04 Validation record/ID/JSONL/SHA-256; cập nhật docs_AI.md.
- [ ] C05 Chờ thẩm định ngữ nghĩa, provenance/license và ICD/QID trước khi cho phép tích hợp.
- [ ] C06 Nếu được duyệt sau C05, ablation riêng trên test20k rồi mới cân nhắc rebuild index.

Kết quả C01–C04: xem resources/curated/20261015/REPORT.md và manifest.json. Bộ dẫn xuất hiện chưa được nạp vào BM25.

## Mở rộng lexicon y khoa VI/EN/ZH — T11

- [x] T11.1 Ghi source registry, field/split extraction plan, expected counts, rights gates và định dạng báo cáo trong `SPEC-medical-lexicon-enrichment.md`.
- [x] T11.1b Ghi lý do/nguồn bổ sung và giới hạn vào `docs_AI.md`.
- [~] T11.2 Rà khai báo license/notice, pin revision/file/hash cho nguồn đã lấy; PKU metadata CC0 nhưng endpoint lỗi; quyền upstream của FHIR và quyền nguồn conditional vẫn chờ xác minh. Nguồn chưa đủ điều kiện được ghi blocked, không gán loadable.
- [~] T11.3 Tải/đọc read-only và staging các nguồn đủ điều kiện thu thập ở run08; PKU không tải được, SNOMED/LOINC/ICD-10/CMeSH/Meddict không tải do rights/artifact gate. Không ghi root Resources.
- [x] T11.4 Parse đúng trường/split của các nguồn đã lấy; kiểm raw counts, schema, language, span offsets và malformed records.
- [x] T11.5 Chuẩn hóa key, dedupe theo language+key, giữ provenance; xuất candidate/review/rejected/loadable counts theo ngôn ngữ. Loadable = 0.
- [~] T11.6 Tạo sample phân tầng và rà mẫu nguồn/nhóm; đã phát hiện dạng câu/list, lỗi span tái dựng, MeSH entry heading/dạng comma và nhánh từ vựng không lâm sàng. Audit FHIR sơ bộ trước đó lệch 1 key so với run08 (4.064 so với 4.063 unique VI); cần xác định record gây lệch. Cần thẩm định người có chuyên môn cho toàn bộ tập review.
- [x] T11.7 Sinh `SOURCE_CATALOG.md`, manifest, counts, hashes và `REPORT.md`; xác nhận output khớp manifest, toàn bộ 27.013 En-ViMedNER file hashes và 8 FHIR CodeSystem hashes.
- [~] T11.8 Đã thêm subset hẹp 80 concept VI/EN cùng code vào `concepts.json` theo yêu cầu trực tiếp; rights review độc lập và ablation trên `data_final/test.jsonl` vẫn chưa hoàn tất. Không tích hợp phần candidate còn lại của run08.

Run canonical để tiếp tục: `artifacts/retrieval/medical-lexicon-staging/20261015-run-08/`. Candidate counts VI/EN/ZH lần lượt 47.058/267.768/18.749; loadable cả ba = 0. Đây là staging cho các nguồn đã thu thập, chưa phải danh mục nguồn đầy đủ hoặc production-ready. Run trước giữ nguyên; không xóa/ghi đè.

## T11 — Bổ sung subset concept VI/EN có code chung

- [x] Đọc toàn bộ 81 mục VN Core FHIR communicable-disease; chọn 80 cặp VI/EN cùng `CodeSystem + code`, loại A15 là nhóm chưa rõ tác nhân.
- [x] Bổ sung vào `resources/concepts.json` theo schema v1, giữ source hash, attribution/copyright notice và `production_ready=false`; giữ nguyên 12 seed.
- [x] Kiểm tra JSON, 92 ID duy nhất, 80 mục mới, trường ngôn ngữ/source/license và không có normalized collision trong tập đã thêm.
- [ ] Rà quyền độc lập ở cấp resource trước khi phát hành; package khai báo CC-BY-4.0 nhưng source catalog còn đánh dấu rights review pending.
- [ ] Bổ sung nguồn có concept ID chung cho tiếng Trung; không dùng THUOCL term đơn ngữ để gán concept giả.
- [ ] Re-prepare/rebuild test index with the updated concepts hash, then run ablation on the designated retrieval test set; this turn did not run tests/benchmark and does not claim a retrieval-score gain.

## Analyzer literal sát chữ Hán và acronym heading — 2026-10-15

- [x] Sửa boundary mã/liều/biomarker theo script; test sát Han, full-width, decimal, dấu phẩy danh sách và mixed Han/Latin có lexicon.
- [x] Loại case marker cho structural headings; giữ acronym hiện hành, không gán anchor từ chữ hoa đơn thuần.
- [x] Chạy Retrieval unit/integration tests: 40 passed; fair fixture strict: 69/69 contract đạt, 1 challenge `Stroke.It` mismatch.
- [x] Dựng baseline mới và candidate cuối từ cùng `test20k`, đủ sáu index partitions; chạy đủ 1.200 query và tạo comparison + audit report.
- [ ] Đo Precision/Recall/F2 sau khi có qrels độc lập được phép dùng. Hiện chỉ có candidate generation metrics; không dùng `for_valid/`.
- Báo cáo: `sbtc/Scripts/Retrieval/REPORT-analyzer-literal-acronym-fixes-20261015.md`; artifact: `artifacts/retrieval/analyzer-fix-eval-20261015/` (`candidate-final/` là snapshot cuối).

## LLM manual term-span và retrieval diagnostic — 2026-10-15

- [x] Preview 100 chunk đã được duyệt; snapshot 34/33/33 route VI/EN/ZH, 100 doc riêng, khớp source/index hashes.
- [x] Tạo 100 query tiếng Việt và 100 known-positive qrels; freeze hash trước analyzer/search.
- [x] Chạy analyzer `medical-no-folded-v1` trên 100 mẫu, lưu fields `contents/broad/exact/anchors`.
- [x] Chạy CandidateEngine trên index READY test20k; tính seed-target Hit@K/MRR theo language/profile và term-span proxies.
- [x] Ghi report, manifest, source/annotation caveats và các mẫu lỗi vào `docs_AI.md`, `thaydoicongnghe.md`.
- [ ] Đợt benchmark đầy đủ segmentation: gắn ranh giới cho toàn bộ token, có annotator/auditor độc lập và sample holdout mới trước khi xem analyzer output.
- [ ] Blind-judge candidate pool nếu cần Precision/Recall/F2 diagnostic; không dùng candidate chưa judge làm negative.
- Báo cáo hiện tại: `sbtc/Scripts/Retrieval/REPORT-llm-manual-tokenization-retrieval-eval-20261015.md`; artifact run: `artifacts/retrieval/llm-manual-eval-20261015/`. Điểm hiện tại không phải F2 BTC.
