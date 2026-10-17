# Kế hoạch BM25 mới — 15/10/2026

## Bỏ folded và Rolling Staging — triển khai theo profile mới

Người dùng đã duyệt đặc tả/kế hoạch và sau đó yêu cầu triển khai. Runtime hiện có analyzer no-folded, bulk đối chứng, rolling writer/CLI, schema v2 và recovery. Xem [SPEC-no-folded-rolling-staging.md](../SPEC-no-folded-rolling-staging.md), [kế hoạch RS01–RS14](no-folded-rolling-staging/plan.md), [checklist](no-folded-rolling-staging/todo.md). Full 20k A/B/C và capacity gate vẫn chưa chạy do dung lượng cần xác minh; đây chưa phải release full-ready.

Yêu cầu mới trực tiếp cho phép triển khai từ đầu; không đọc/tái sử dụng BM25 cũ. Nguồn yêu cầu là SPEC-bm25-recall-first.md, nội dung dán mới và asked.md. `for_valid` ngoài quy trình. Mọi corpus test dùng test20k.

## Dependency và checkpoints

```text
runtime/asset contracts → lexicon + analyzer → prepare/registry → Lucene build
                                      → query projector → channel search → fusion
registry + fusion → candidates for reranker → explicit BTC export
```

Không đổi crawler/chunker, không xóa data/outputs. Những phần thiếu resource production được báo trạng thái thiếu, không làm giả feature.

## Tasks

### T01 — Runtime và hợp đồng

- Files: `requirements.txt`, `.gitignore`, `models.py`, `__init__.py`.
- Tiêu chí: runtime riêng Python/Java compatible; DTO cho analysis/hits; không import legacy.
- Kiểm tra: actual package/JVM versions; import component.
- Phụ thuộc: không.

### T02 — Lexicon có provenance

- Files: `lexicon.py`, `resources/concepts.json`, `resources/README.md`, `tests/test_analyzers.py`.
- Tiêu chí: namespace không giả CUI; multilingual aliases, ambiguity/case rules; adapter để thay starter dictionary.
- Kiểm tra: phrase boundaries, ambiguous acronym, concepts cùng ID ba ngôn ngữ; hash drift.
- Phụ thuộc: T01.

### T03 — Normalization và analyzer VI/ZH

- Files: `analyzers.py`, `tests/test_analyzers.py`.
- Tiêu chí lịch sử ban đầu: compound/broad/folded/exact tách fields, units và IDs không mất; asymmetry index/query rõ; OpenCC chỉ trên copy. Runtime hiện hành dùng `contents/broad/exact/anchors/title` theo profile no-folded mới.
- Kiểm tra: từ ghép và subphrase, punctuation boundary, Unicode width, microgram; source text unchanged.
- Phụ thuộc: T02.

### T04 — Analyzer EN

- Files: `analyzers.py`, `tests/test_analyzers.py`.
- Tiêu chí: Krovetz + mapping nguyên từ, protected literal trước lowercase, clinical intent/negation còn; không promiscuous medical acronym grounding.
- Kiểm tra: ALL/all, biomarkers, inflection, μg/mg, spelling variants; actual Lucene analyzer.
- Phụ thuộc: T01–T03.

### Checkpoint A

Chạy tests analyzer thực, version/resource evidence; cập nhật docs_AI trước chuyển index. Không nới tests để chạy xanh.

### T05 — Pointer store và streaming corpus preparation

- Files: `corpus.py`, `store.py`, `tests/test_corpus.py`.
- Tiêu chí: source membership ID/URL, preserve order/hash, dedup overlap, record bytes khác char offsets, skip audit.
- Kiểm tra: actual test20k extracts và read-back selected source chunks; duplicate/mismatch/source mutation errors.
- Phụ thuộc: T04.

### T06 — Resume và capacity

- Files: `corpus.py`, `store.py`, `tests/test_corpus.py`.
- Tiêu chí: atomically staged shard + metadata transaction; resume fingerprints; no duplicate; estimates staging/JVM/disk headroom.
- Kiểm tra: interrupt/mutation/restart fixtures test20k, no writes source files.
- Phụ thuộc: T05.

### T07 — Lucene six-partition build

- Files: `backend.py`, `cli.py`, `configs/test.toml`, `tests/test_integration.py`.
- Tiêu chí: fields searchable, pretokenized exact terms, bag-of-words norms; completed snapshots immutable.
- Kiểm tra: build test20k-derived corpus; counts/TF query matches, original hydration.
- Phụ thuộc: T06.

### T08 — Query projection và translation cache

- Files: `query.py`, `tests/test_query.py`, `resources/README.md`.
- Tiêu chí: VI original/intent + multilingual aliases/exact/anchors; cached EN/ZH with query hash/provenance; missing translation disclosed.
- Kiểm tra: stale cache rejected, context retained, no qrels imports; term alternatives bounded.
- Phụ thuộc: T02/T04.

### T09 — Candidate retrieval và fusion

- Files: `engine.py`, `backend.py`, `tests/test_engine.py`.
- Tiêu chí: independent global chunk/doc search, normalized language contribution, channel evidence, doc-collapse best hit; wide candidates without relevance cutoff.
- Kiểm tra: native search/batch parity, absent channel, rescue ranking, no raw cross-language score comparison.
- Phụ thuộc: T07/T08.

### Checkpoint B

End-to-end test20k search + candidate artifact. Báo kỹ thuật/resource; không tự gọi là điểm BTC hoặc Recall thực khi không có nhãn độc lập.

### T10 — Reranker contract và BTC export

- Files: `engine.py`, `export.py`, `cli.py`, `tests/test_export.py`.
- Tiêu chí: candidate JSONL không buộc lấy top-small; hydrate API; explicit final budget; đủ expected query IDs, source text/order, JSON/ZIP đúng format.
- Kiểm tra: original hash, invalid/missing IDs, streaming arrays, no debug in submission.
- Phụ thuộc: T09.

### T11 — Tài nguyên y khoa mở rộng

- Files dự kiến: `SPEC-medical-lexicon-enrichment.md`, source catalog/manifest/report ở artifacts của Retrieval, resource importer/manifest và resource README thuộc Retrieval.
- Phạm vi nguồn: VI gồm VN Core FHIR, train VietBioNER, train En-ViMedNER, catalogue VietENT-Text; VI SNOMED/LOINC/ICD-10 là conditional rights-gated. EN gồm English designation trong FHIR và NLM MeSH 2026. ZH gồm PKU Medical Segmentation Dictionary + THUOCL medical. VietMedCSS/VietMed/CMeSH/UMLS không trích term khi quyền hoặc artifact chưa đủ rõ.
- T11.1 — Source registry và sơ duyệt rights: ghi publisher, URL/DOI, version/split/artifact, license/notice, attribution, upstream caveat và điều kiện dùng. Không coi dataset-card license tự động bao trùm nguồn upstream; quyền chưa rõ được đánh dấu blocked.
- T11.2 — Pin và lấy artifacts: chỉ lấy nguồn có căn cứ đủ để tạo local candidate staging; ghi revision/commit, file name/size/hash, ngày lấy và source metadata. Rights clearance cuối là điều kiện riêng trước khi phân phối hoặc `loadable=true`. Dữ liệu gốc/read-only; mỗi lần chạy dùng staging mới.
- T11.3 — Parser theo nguồn: trích đúng fields/split được liệt kê tại mục 3.2 SPEC; kiểm schema, language, code/status, span offsets và split counts. Không lấy câu synthetic, UMLS concept assets, definitions hoặc validation/test ngoài quy định.
- T11.4 — Chuẩn hóa và provenance: giữ literal surface; tạo NFKC/case/space normalized key; dedupe theo language+key nhưng giữ toàn bộ code, category và source refs. Phân luồng candidate/review/rejected/blocked_license/loadable.
- T11.5 — Audit và báo cáo: tạo `source_manifest.json`, `SOURCE_CATALOG.md`, per-source count report, hashes, unique/overlap/status counts và stratified review; giải thích count drift.
- T11.6 — Nạp thử/ablation: chỉ dùng loadable term, benchmark analyzer theo ngôn ngữ trên bộ fair fixture và tập `test.jsonl` được chỉ rõ; không dùng `for_valid`. Không replace root Resources hoặc rebuild index cho tới khi có quality/legal gate và phê duyệt riêng.
- Tiêu chí: 100% loadable term có provenance/license/attribution; quyền chưa xác minh không được xuất runtime; source counts và unique/loadable counts tách riêng; mapping đa ngữ không được suy ra từ chuỗi trùng.
- Kiểm tra: hash/source immutability, counts per-source/split, schema, span offsets, exact-dedup, cross-source overlap, ambiguous mappings, analyzer regression và resource footprint.
- Phụ thuộc: T02; sơ duyệt rights và pin source artifact là điều kiện trước local candidate extraction. Legal clearance cuối và semantic review là blockers trước phân phối, `loadable=true`, analyzer ablation hoặc production resource gate; không mặc định starter lexicon đủ.

**Tiến độ 15/10/2026:** T11.1 source registry/rights declarations đã ghi; read-only parse và candidate staging đã thực hiện ở `artifacts/retrieval/medical-lexicon-staging/20261015-run-08/`. Parse/hash/schema/span checks đạt cho artifacts đã thu thập. Còn blocked: quyền tái phân phối/semantic review, PKU download endpoint HTTP 500, nguồn SNOMED/LOINC/ICD-10/CMeSH/Meddict chưa có artifact/quyền đủ rõ, và chưa có `data_final/test.jsonl` được chỉ định. Không có term nào loadable; chưa sửa resource/analyzer hoặc chạy BM25 ablation. Checklist chi tiết ở `tasks/todo.md`, kết quả ở `SPEC-medical-lexicon-enrichment.md` và run `REPORT.md`.

### T12 — Local translation model và full readiness

- Files: local translator adapter/config/model manifest của Retrieval.
- Tiêu chí: model mở ≤15B, released trước cutoff, batch/cached translation bảo toàn terms; capacity full/index input audit đạt.
- Kiểm tra: identity/symbol/number/negation ca độc lập; source/model/candidate metrics; không cam kết 80 ms cold inference.
- Phụ thuộc: T10/T11. Full build dùng thư mục mới sau preflight, không overwrite nguồn; test vẫn trên test20k.

## Nghiệm thu

Core: analyzer + registry + Lucene candidate retrieval chạy thật; integrity/resume checks đạt; explicit boundary giữa candidates/reranker/submission. Production: assets/translation/capacity đủ, không silent degraded feature. Relevance score chỉ kết luận từ independent labels được phép dùng sau freezing configs, ngoài task phân tích `for_valid`.

Thay đổi và khó khăn thực tế ghi `docs_AI.md`; tiến độ chi tiết tại `tasks/todo.md`. User đã yêu cầu triển khai mới nên không yêu cầu duyệt lại hướng cũ.
