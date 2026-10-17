# Trạng thái tạm dừng — 17/10/2026

**Người dùng yêu cầu tạm dừng. Không tiếp tục build, test, nghiên cứu hay chỉnh code cho đến khi người dùng yêu cầu chạy tiếp.**

## Task đang làm

Triển khai `SPEC-icd10-foundation.md` đã được duyệt: chuẩn bị taxonomy WHO ICD-10 và lexicon đa ngữ có provenance, ưu tiên chapter/block. Kế hoạch: `plan.md`, checklist: `todo.md` cùng thư mục này.

Phạm vi độc lập `sbtc/Scripts/Retrieval/taxonomy/`. Không sửa tokenizer/BM25 hiện hành, `resources/concepts.json`, segmentation files, corpus, query/gold; không train/tag corpus. Không tự dùng các subagent cũ của task validation cho task này.

## Điểm dừng chính xác

- Build `artifacts/taxonomy/runs/foundation-20261017-003` đã hoàn tất **exit 0** ngay trong lúc nhận yêu cầu dừng; có `build_manifest.json` và `validation.json`. Session 23472 đã kết thúc; không tiếp tục audit sau đó.
- Log được lưu bền tại `build-003-before-pause.log`.
- Kết quả build: **2.386 core nodes = 22 chapter + 274 block + 2.090 category**; **62.090 source nodes**, **11.539 verified senses** (EN/WHO).
- Source nodes gồm WHO 11.539 (có 9.153 subcategory trực tiếp), NHC 34.708, BYT 15.843 ứng viên. BYT có thêm 1 dòng không được nhận làm node do raw code bất thường; vẫn giữ đầy đủ trong auxiliary/quarantine.
- Run 001 và 002 là các lần trước, có code khác; giữ nguyên để truy vết, không dùng thay bản mới nhất và không sửa tại chỗ.
- Bộ kiểm thử mới nhất: **43 tests PASS**, lệnh `.runtime-taxonomy/bin/python -m unittest discover -s sbtc/Scripts/Retrieval/tests -p 'test_taxonomy_*.py' -v`; log `focused-tests-before-pause.log`.
- Chưa chạy audit semantic/performance trên run 003; chưa freeze, chưa phát hành hoặc tích hợp.

## Code đã có

- `models.py`, `io.py`, `sources.py`: NodeKey/edition ID từ hash; snapshot nguồn bất biến; archive có giới hạn, chặn traversal/entity; atomic write và kiểm tra hash/resume.
- `who.py`: ClaML theo hierarchy thực, block lồng nhau, rubric/references và modifiers chưa khai triển; reader node/ancestors.
- `tabular.py`: giữ toàn bộ metadata rows, đối soát và giữ khác biệt thay vì gộp snapshot.
- `native.py`: JSON/FHIR/XLS, explicit header contract; các sheet cũ/patch/stopped giữ deferred. Không đoán native hierarchy/canonical mapping.
- `byt.py`: trích xuất PDF 29 cột theo tọa độ của đúng file đã pin; giữ page evidence và STT rows **chưa được xác minh**, không auto nhận làm labels verified.
- `crosswalk.py`: candidates từ cùng mã/prefix không có relation được duyệt; review supersession; accepted equivalent/narrower chỉ project lên ancestor. Có direct WHO ancestry projections và label transfer chỉ qua equivalent được duyệt.
- `normalize.py`, `lexicon.py`: NFKC/OpenCC + case-preserved/lower views, Aho lookup, sense identity, pending ambiguity registry, context/abstain và reviewed lexical decisions.
- `validation.py`: kiểm cấu trúc/identity/source/hierarchy/projection/provenance/registry/runtime/reconciliation; release profiles.
- `build.py`, `cli.py`, `audit.py`, `performance.py`: fetch/build/validate/audit/freeze; deterministic hashes, protected production hashes, standalone matcher performance process, semantic metrics có support/CI. Chưa chứng minh tất cả đường audit/freeze thành công; cần review và kiểm thêm khi resume.
- Config thật: `sbtc/Scripts/Retrieval/configs/taxonomy.sources.json`.

## Nguồn và môi trường

- Snapshot nguồn ở `artifacts/taxonomy/sources/`; bytes tải ban đầu ở `artifacts/taxonomy/downloads/`. Giữ nguyên cả hai.
- WHO ClaML: `https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip`, archive SHA `344c571aa9aed3b9ad1c80261b7828c45cfb5fc0b1a5da64aecef354dff5b3d9`; embedded version `2019-covid-expanded`, Identifier `icd10_20210322`.
- WHO tabular: `https://icdcdn.who.int/icd10/meta/icd102019enMeta.zip`, SHA `a9fa787fa79076e199e46ca645bbc076449853e93e62cd3b2050b96dc96bbc1d`.
- BYT: `https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/06-byt-kem.pdf`, SHA `8639f5eeb77b571363dc841923095895d2498748f9bc6620f50710a6da9159e2`.
- NHC via Fujian: `https://wjw.fj.gov.cn/jggk/csxx/yzc/gzdt_33135/202106/P020210603544738447753.xls`, SHA `63ac67ec5b350df1b2d3e8b6c17f173628654505e8ec7869e80c49e9f6ffe1de`.
- Môi trường riêng `.runtime-taxonomy/bin/python` (3.12.15, system-site-packages của Conda bm25); OpenCC 0.1.7, pyahocorasick 2.2.0, requests hiện hành 2.34.2. **Người dùng đã duyệt thêm xlrd 2.0.2**; đã cài trong môi trường này, không sửa Conda BM25. Poppler `pdftotext` 26.01.0 có sẵn.
- Network sandbox không resolve được DNS; các lần tải dùng quyền mạng được duyệt. Không cần tải lại khi resume vì nguồn đã pin đủ bốn snapshot.
- Nguồn FHIR JSON cũ trả 404; Downloads/package cũ không còn. Không lấy package cộng đồng thay cho nguồn pháp lý.

## Phát hiện và sửa lỗi đã ghi nhận

- ClaML chứa 46 Modifier + 243 ModifierClass: giữ deferred, không khai triển thành mã giả.
- Preferred labels có Reference coding xen trong Label, ví dụ A06.4 kèm K77.0. Đã tách Reference khỏi tên lookup, giữ XML và references; có regression test.
- PDF BYT có **1.271 trang**, STT **1..15.844** liên tục. Parser ban đầu bỏ dòng đầu các trang vì y>40; đã xác định dòng đầu y=35.41, sửa guard và thêm regression test. Không đổi expected count để test xanh.
- Raw code tại **trang 1.258 / STT 15.750 là `U13/9`**; label nhắc U13.9. Giữ quarantine, không tự sửa mã.
- Sheet NHC `2.0`: 34.708 mã chính, 2.581 dòng chỉ có mã phụ. Tổng workbook sáu sheet 75.025 dòng, đều giữ lại và reconciliation.
- Đã sửa conflation extraction/semantic acceptance: native unknown-kind vẫn có thể source_verified ở chiều extraction nhưng tiếp tục quarantine về semantic.
- Đã thêm rule lấy mức usage chặt hơn giữa entry/link; guard chưa hỗ trợ tiếp tục abstain; native pending competitor không bị che vì thiếu runtime export.
- Build có chặn code taxonomy thay đổi trong lúc build; không chứng nhận output theo code hash cuối khi thực tế chạy bằng code cũ.
- Freeze chỉ tạo bundle cục bộ; rights chưa rõ được giữ nguyên trong manifest và không tự cấp quyền phát hành công khai. Không có quyền phân phối được suy từ việc tải thành công.

## Dữ liệu kiểm tra và phần còn thiếu

- `tests/fixtures/taxonomy/source_fixture_who_d_h.xml` + provenance: source fixture thật, kiểm D10/D50 và H00/H60 thuộc các chapter khác nhau.
- `tests/fixtures/taxonomy/semantic_development.jsonl`: **45 ca development, mỗi ngôn ngữ 15 ca**, expected được lập từ nguồn đọc, không từ matcher output. Manifest đi kèm pin SHA.
- Các ca VI/ZH positive nhằm thể hiện coverage còn thiếu, **không đổi expected thành no_match để che việc chưa curated**. Các safety predicates cho phép no_match/context/ambiguous, không ép một format duy nhất.
- Bộ 45 ca chưa được chạy audit tại thời điểm pause; **không phải holdout độc lập >=200 ca và không được người dùng duyệt làm gold release**. Chưa có căn cứ tuyên bố precision 98/99%, tốc độ hay đủ chuẩn 3 ngôn ngữ.
- Preferred labels VI/ZH canonical chưa được xác minh; native semantics/crosswalk còn pending; runtime verified hiện chỉ WHO EN. Coarse kind rule dựa chapter cần review/audit, không phải clinical coding model.

## Thứ tự tiếp tục (chỉ khi người dùng yêu cầu)

1. Đọc lại file pause, AGENTS và scoped plan; kiểm code/resource hashes của run 003. Không tự rebuild/overwrite khi code đã đổi; dùng run mới nếu fingerprint lệch.
2. Rà soát code còn lại và thêm regression cho code-change-during-build, review acceptance, audit integrity, successful freeze trong fixture; test hiện có chưa chứng minh mọi gate là đủ.
3. Khi code ổn định, chạy audit development và standalone benchmark, giữ nguyên expected, giải thích fails/coverage; dùng đúng run/hash. Nếu cần sửa code thì build run mới trước audit.
4. Chuẩn bị/đánh giá holdout đa dạng >=200 ca, >=50 mỗi ngôn ngữ với nguồn và đáp án độc lập; không dùng 45 ca development thay gate hoặc tự ghi approved_by.
5. Tiếp tục review PDF row/cell, loại thuật ngữ native, canonical crosswalk/labels VI/ZH; không tự nâng staging/prefix thành verified. Duyệt scope dữ liệu trước khi freeze nếu còn thiếu.
6. Hoàn thiện README, SOURCE_CATALOG, báo cáo implementation/source counts/coverage/performance/limitations, checklist và docs bắt buộc. Không chạy BM25/retrieval hoặc sửa module khác để hoàn tất foundation.

Không tự tiếp tục vì hết thời gian chờ. Người dùng sẽ nói khi nào chạy tiếp.
