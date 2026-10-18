# Kế hoạch triển khai bỏ folded và Rolling Staging

Ngày: 15/10/2026. **Implementation v1 và C rolling full test20k đã hoàn tất; A↔C đã so sánh 1.200 query; B no-folded bulk và đánh giá relevance còn thiếu**.

Nguồn yêu cầu: [đặc tả](../../SPEC-no-folded-rolling-staging.md). Checklist riêng: [todo.md](todo.md). Các mục từ điển/dịch/reranking chưa hoàn thành vẫn giữ nguyên.

## Tiến độ implementation

| Nhóm | Trạng thái và bằng chứng |
|---|---|
| RS01–RS03: profile/schema/bulk control | Hoàn thành; analyzer fixture no-folded strict, bulk integration field check |
| RS04–RS05: direct writer/receipt | Hoàn thành ở smoke scope; 5 writer tests và bulk/rolling parity trên sample 4 record lấy từ test20k |
| RS06–RS09: staging, registry, recovery, cleanup/publish | Hoàn thành ở smoke scope; cap 5.000 bytes ép nhiều batch; fault injection sau commit partition đầu tiên resume không trùng IDs |
| RS10: CLI/config | Hoàn thành; `index` full test20k `READY`; config trỏ đến run đã xác minh |
| RS11–RS12: capacity/metrics/test matrix | Full run đo staging/RSS/free space; low-space/ENOSPC và crash matrix đầy đủ còn thiếu |
| RS13: 20k A/B/C + 1.200 queries | Một phần: A↔C đủ 1.200 query; B no-folded bulk và B↔C parity chưa chạy; không có qrels |
| RS14: tài liệu/bàn giao | Cập nhật report A↔C, README/spec/task status, docs_AI và thaydoicongnghe |

Kiểm tra implementation: py_compile 31 file module/test pass; sau fix regex literal, `unittest discover -s sbtc/Scripts/Retrieval/tests -v` 56 tests pass. Analyzer fixture strict: 69/69 contract cases đạt; 1 challenge mismatch `Stroke.It`. Rolling bulk-parity vẫn được xác nhận trên 6 record synthetic và 4 source records nhỏ. Benchmark full C chạy riêng trên 20k; không thay thế phép so B↔C.

## 1. Phạm vi và dependency

```text
RS01 khảo sát/schema/fixtures
  ├─ RS02 no-folded analyzer/query → RS03 schema/fingerprint/bulk control
  └─ RS04 direct writer spike → RS05 incremental commit receipts
RS03 + RS05 → RS06 event cursor + bounded staging
           → RS07 durable registry + stage seal
           → RS08 coordinator + recovery
           → RS09 cleanup + publish
           → RS10 CLI + run mode
           → RS11 capacity/metrics
           → RS12 fault injection/integrity
           → RS13 benchmark A/B/C + RS14 báo cáo/bàn giao
```

Làm tuần tự ở các file dùng chung; không khởi tạo agent hay chạy công việc song song trong kế hoạch này. Checkpoint sau từng nhóm chỉ chuyển khi gate kỹ thuật đạt, không nới test để qua. Gặp hướng cần Java helper/dependency khác thì ghi phát hiện và trình phương án trước khi đổi.

## 2. Các lát triển khai

### RS01 — Đóng băng căn cứ và hợp đồng profile

- Công việc: ghi source/query/resource/JAR hashes và counts của baseline; xác định schema v2, build-policy fingerprint và bảng mapping kỳ vọng fixture no-folded. Không sửa fixture cũ để đổi lịch sử benchmark.
- Files: `SPEC-no-folded-rolling-staging.md`, `tests/test_analyzer_fixture.py`, fixture profile mới dưới `tests/fixtures/` (tối đa 3 file).
- Acceptance: contract phủ năm text fields, biến mất của folded, scope/routing/identity giữ nguyên; mọi thay đổi expectation có lý do từ đặc tả.
- Verification sau triển khai: đối chiếu hashes baseline/cursor conventions; review expectation cho vi-24 và các required_any có folded.
- Phụ thuộc: đặc tả được duyệt. Scope: S/M.

### RS02 — Bỏ folded khỏi analysis và query

- Files: `analyzers.py`, `query.py`, `tests/test_core.py`, `tests/analyze_fixture.py` (M).
- Công việc: bỏ producer/fold helper/field output, bỏ folded khỏi query broad; cập nhật runner theo profile rõ ràng; giữ text và các expectations còn hiệu lực.
- Acceptance: không output folded; contents/broad/exact/anchors giữ output tương ứng trước thay đổi; không dấu được ghi là khả năng không còn rescue, không sinh restoration mới.
- Verification: focused CoreTests và analyzer fixture profile mới; thử query dài để kiểm warning/128-term allocation; lưu mismatch legacy riêng.
- Phụ thuộc: RS01.

### RS03 — Đồng bộ schema, bulk control và fingerprint

- Files: `models.py`, `backend.py`, `corpus.py`, `tests/test_integration.py`, `tests/test_contracts.py` (M).
- Công việc: năm text fields gồm cả title trong hợp đồng mới, bỏ folded boost; manifest version/profile mới; tách analysis-schema fingerprint và build-policy fingerprint để B/C so sánh được.
- Acceptance: bulk no-folded chạy e2e trên bản dẫn xuất test20k nhỏ; index thật không có folded; code từ chối index/profile cũ hoặc run-mode sai.
- Verification: integration field inspection, unchanged source/hydration, hash drift errors; trước kiểm toàn20k phải qua disk gate.
- Phụ thuộc: RS02.

### Checkpoint A — Profile no-folded chạy được

Các bước no-folded phải chạy được bằng bulk trước khi ghép rolling. Lưu output analyzer khác biệt, không coi test v1 vẫn đủ để chứng nhận profile mới. Nếu field khác folded đổi ngoài dự kiến thì sửa nguyên nhân trước.

### RS04 — Chứng minh direct writer trong runtime pin

- Files: `index_writer.py` (mới), `tests/test_index_writer.py` (mới), `runtime.py` nếu cần expose thông tin pin (M).
- Công việc: gọi JsonCollection.Document.fromString, generator, IndexWriter với cùng field options; initial CREATE ở run trống; APPEND ở run đã có; commit user data/read-back; setCommitOnClose(false).
- Acceptance: thêm batch thứ hai không mất batch đầu; ID/docvalues/norms/TF/DF giống IndexCollection bulk trên cùng input; exception không tự commit.
- Verification: integration thật trên bản sao record VI/EN/ZH của test20k, kiểm Java overload và reopen; ghi runtime/JAR/Lucene version.
- Phụ thuộc: RS01; dùng schema RS03 khi kiểm full parity.
- Rủi ro: JNI overload/generator generic signature. Đây là task fail-fast; không thay bằng `-append` CLI.

### RS05 — Receipt và chính sách writer

- Files: `index_writer.py`, `tests/test_index_writer.py` (S).
- Công việc: sáu writer/lock tuần tự; 16 MiB buffer mỗi writer; serial merge; setLiveCommitData gồm batch identity/hash/count; empty partition có marker; rollback chưa commit.
- Acceptance: receipt đọc từ committed index, có batch/routing/schema identity; marker không dùng sequence number làm durable key; không forceMerge mỗi batch.
- Verification: commit 0/1/N records; reopen last commit; counter drift/stale marker/error-close bị phát hiện; so normal merge vs bulk score/norm parity.
- Phụ thuộc: RS04.

### Checkpoint B — Không đánh đổi tính đúng để có append

Chứng minh local writer không reset dữ liệu và không làm lệch field semantics. Nếu không đạt thì dừng tích hợp coordinator, cập nhật lựa chọn kiến trúc để người dùng xem.

### RS06 — Reader event/cursor và staging byte-bounded

- Files: `corpus.py`, `rolling.py` (mới), `tests/test_rolling.py` (mới) (M).
- Công việc: tách validation/source reader khỏi bulk orchestration; event ordinal deterministic; batch target250 MB/max300 MB; quota tính toàn staging root; split giữa prepared views và serialize có giới hạn.
- Acceptance: tiếp tục giữa source record tạo cùng events/bytes; một source shard lớn không phá cap; oversize output record fail có identity, không partial JSONL/skip.
- Verification: UTF-8/byte-vs-char, metadata-only/skipped batches, multi-language doc, short shard và record vượt cap; test dùng cap nhỏ để ép nhiều batch trên test20k extracts.
- Phụ thuộc: RS03.

### RS07 — Registry v2 và seal batch durable

- Files: `store.py`, `rolling.py`, `utils.py`, `tests/test_rolling.py` (M).
- Công việc: routing mask và bảng batches/receipts/progress trong DB run mới; transaction metadata + PREPARED; fsync files/parent dirs; ownership manifest; duplicate input vs replay phân biệt bằng source+offset/hash.
- Acceptance: stage và ledger có giao thức phục hồi rõ, không giữ token trong DB; source pointer TextStore không đổi; batch PREPARING chưa durable có thể làm lại.
- Verification: lỗi trước/sau SQLite commit, fsync/rename failures, duplicate doc/chunk từ vị trí khác, registry schema mismatch, source mutation.
- Phụ thuộc: RS06.

### RS08 — Coordinator và partial-commit recovery

- Files: `rolling.py`, `index_writer.py`, `tests/test_rolling.py`, `tests/test_index_writer.py` (M).
- Công việc: một batch vào sáu partition; reconcile SQLite và marker Lucene; skip batch/partition có receipt đúng, ingest phần chưa commit; không advance cursor khi sáu partition chưa đủ.
- Acceptance: crash sau 1/3/5 partition commits và trước receipt SQLite không thêm trùng; mismatch ledger/index fail rõ; no-op resume khi đã hoàn thành.
- Verification: injected crash ở mỗi ranh giới trong SPEC §7.1; restart process thật cho đường critical sau commit; so IDs/counts/postings với cold build.
- Phụ thuộc: RS05 + RS07.

### Checkpoint C — Dữ liệu sống qua restart

Kiểm số lượng không đủ: cần cả source identity, unique live IDs, term stats và cursor giữa source record. Chưa cleanup nếu còn case commit ambiguity chưa có bằng chứng xử lý đúng.

### RS09 — Cleanup có ownership và publish snapshot

- Files: `rolling.py`, `store.py`, `tests/test_rolling.py`, `tests/test_integration.py` (M).
- Công việc: chỉ xóa active batch COMMITTED do run mới sở hữu; xử lý cleanup một phần; kiểm toàn routing/IDs/schema; rename cả cây indexes.building rồi READY.
- Acceptance: không đổi source/old artifact; max một batch; PREPARED mất stage không bị bỏ qua; search không thấy snapshot partial; hydrate vẫn đúng sau cleanup.
- Verification: crash trong unlink/rename/READY, symlink/path traversal, ownership mất/sai, copy read-only test20k hashes; toàn bộ eligible child hydrate ở full20k gate sau.
- Phụ thuộc: RS08.

### RS10 — CLI, cấu hình và chế độ run

- Files: `cli.py`, `configs/rolling-test.toml` (mới), `backend.py`, `tests/test_integration.py` (M).
- Công việc: command index cho rolling, routing bulk/rolling explicit; run-dir mới; search/export chỉ nhận completed compatible snapshot; cấu hình byte limits và writer policy.
- Acceptance: lệnh mới resume cùng config và no-op READY; sai mode/policy/fingerprint rejected; default full không chạy tự động.
- Verification: parser/config conflicts, nonempty unknown directories, lock concurrent writers, existing candidate output protection, six partitions kể cả empty.
- Phụ thuộc: RS09.

### RS11 — Capacity, metric và dừng khi thiếu đĩa

- Files: `capacity.py`, `rolling.py`, `cli.py`, `tests/test_rolling.py` (M).
- Công việc: capacity tách stage/index/merge/registry/journal/log; guard trước batch và commit; đo high-water staging logical/allocated bytes, peak disk/RSS/timings; bounded logs.
- Acceptance: không dùng full-staging formula cho rolling, không double-count disk khi resume; low disk dừng có thể phục hồi; số300 MB không được mô tả là whole-job bound.
- Verification: mock low-space/ENOSPC trên temp copies; công thức đối chiếu measured artifacts và capacity cũ giữ nguyên; source paths không bao giờ là cleanup targets.
- Phụ thuộc: RS10.

### Checkpoint D — E2E nhỏ với giới hạn thật

Một lệnh index chạy qua prepare/index/commit/cleanup; cap nhỏ ép nhiều batch; failpoints/restart đạt. Xác nhận direct writer không mở thêm JVM worker và tổng RSS được đo, không suy từ heap flags.

### RS12 — Bộ kiểm thử integrity/recovery đầy đủ

- Files: `tests/test_rolling.py`, `tests/test_index_writer.py`, `tests/test_integration.py`, `tests/test_analyzer_fixture.py` (M).
- Công việc: hoàn thiện matrix SPEC §10 với record/shards sao từ test20k; không thêm framework; dùng unittest hiện có.
- Acceptance: mọi fault case critical qua; tests cũ còn hiệu lực vẫn đạt; báo riêng intentional capability removal và challenge `Stroke.It` cũ.
- Verification: lệnh focused rồi toàn Retrieval suite, runner profile mới; ghi command/exits, không xóa assertion/skip chỉ để xanh.
- Phụ thuộc: RS11. Các test cục bộ đã làm ở RS02–RS11; RS12 là gate tổng hợp, không đợi cuối mới kiểm.

### RS13 — Benchmark test20k A/B/C

- Files: script benchmark mới thuộc Retrieval/tests hoặc research của Retrieval, config/report của task (tối đa 3–5 file).
- Điều kiện: đủ disk cho B/C, input20k/queries/resources/JAR hashes đã freeze. A lấy artifact baseline sẵn có; B no-folded bulk; C no-folded rolling. Không xóa A/B hoặc data khác để giải phóng chỗ khi chưa duyệt cleanup riêng.
- Acceptance: B/C counts và identity/TF/DF/norm parity đạt; BM25 tolerance abs1e-5 + rel1e-6 và tie policy như spec; hydrate 62.941/62.941; staging C <= cap.
- Verification: chạy 1.200 queries B/C, báo A↔B và B↔C riêng; index/stage/metadata bytes, minimum free, build/search timing, RSS, warning/query-term-budget. Không coi candidate counts là relevance.
- Phụ thuộc: RS12.
- Nếu disk không đủ: hoàn tất report phần đã đo, ghi gate thiếu chỗ và yêu cầu storage/cleanup cụ thể; không tự thu nhỏ phạm vi rồi báo full20k đã đạt.

### RS14 — Tài liệu vận hành và bàn giao

- Files: `README.md`, spec/task status, `docs_AI.md`, `thaydoicongnghe.md`, report task mới (chia hai patch tài liệu nếu >5 file).
- Công việc: mô tả lệnh index mới, resume/cleanup/rollback và schema mismatch; ghi kết quả thật/giới hạn, links artifacts, capacity đã đo và chưa xác minh.
- Acceptance: không đánh dấu full-ready khi còn gate; docs tách no-folded effect khỏi rolling equivalence; tasklist chưa đạt không được tick.
- Verification: cross-check paths/commands/figures với artifacts; kiểm diff chỉ thuộc Retrieval và hai log bắt buộc.
- Phụ thuộc: RS13; cập nhật log phát hiện khó khăn liên tục, không chờ RS14 mới ghi.

## 3. Lệnh kiểm tra và vận hành

```bash
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m unittest sbtc.Scripts.Retrieval.tests.test_core -v
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m unittest sbtc.Scripts.Retrieval.tests.test_index_writer -v
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m unittest sbtc.Scripts.Retrieval.tests.test_rolling -v
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m unittest discover -s sbtc/Scripts/Retrieval/tests -v
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m sbtc.Scripts.Retrieval.cli index --config sbtc/Scripts/Retrieval/configs/rolling-test.toml
```

`test_index_writer`, `test_rolling`, command `index` và rolling-test config đã được thêm. Test suite dùng unittest sẵn trong repo. Không có lint/typechecker riêng được cấu hình cho module; không thêm framework trong task.

Lệnh `index --config ...rolling-test.toml` là đường chạy full test20k và cần disk preflight trước; trong implementation task này không chạy full.

## 4. Rủi ro và điều kiện dừng

| Rủi ro | Giảm thiểu/gate |
|---|---|
| Mất dữ liệu do CREATE | Writer chỉ CREATE run/partition mới có ownership; APPEND thiếu index phải fail |
| Partial six-index/SQLite commit | Durable receipt từng partition + global COMMITTED trước cleanup |
| Stage cap đẹp nhưng merge hết đĩa | Capacity toàn job, normal merge reserve, low-disk guard |
| Replay duplicate hoặc sai stats BM25 | Không replay committed partition, fault tests và cold/resumed parity |
| Token/field lệch khi đổi writer | Reuse pinned Anserini generator, kiểm postings/norms/scores với bulk |
| Bỏ folded làm mất query không dấu | Báo riêng A/B, không gọi đó là bug rolling hoặc giấu giới hạn |
| JNI nhiều writer/merge chậm | Một JVM, serialized JNI, buffer explicit, đo throughput/RSS; không tự thêm worker |
| Không đủ chỗ chạy B/C | Không xóa snapshot cũ; báo storage gate và phương án cần duyệt riêng |

Không đổi corpus, source chunks, snapshots/index cũ hoặc fixture lịch sử. Test e2e tạo artifacts trong `TemporaryDirectory` và xóa cùng test runner; chưa tạo rolling run test20k lâu dài.
