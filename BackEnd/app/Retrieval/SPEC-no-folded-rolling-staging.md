# Đặc tả bỏ folded và Rolling Staging cho BM25

Ngày: 15/10/2026. Trạng thái: **profile `medical-no-folded-v1` đã chạy full test20k bằng rolling và search đủ 1.200 query; mới có đối chiếu A↔C, chưa hoàn tất A/B/C hoặc đo relevance**. Báo cáo: [REPORT-no-folded-rolling-test20k-20261015.md](REPORT-no-folded-rolling-test20k-20261015.md).

Yêu cầu: bỏ trường tìm kiếm tiếng Việt không dấu `folded`, chuyển việc dựng index sang một batch staging có giới hạn byte và có thể phục hồi sau lỗi. Người dùng đã duyệt đặc tả và kế hoạch, sau đó yêu cầu triển khai. Tài liệu dưới đây ghi hợp đồng đã triển khai; các giới hạn kiểm chứng hiện tại được ghi ở §12.

Kế hoạch: [tasks/no-folded-rolling-staging/plan.md](tasks/no-folded-rolling-staging/plan.md). Checklist: [todo.md](tasks/no-folded-rolling-staging/todo.md).

## 1. Mục tiêu, phạm vi và bất biến

| Capability | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `no-folded` | Loại bỏ folded khỏi analyzer, prepared fields, query và index schema mới | Không |
| `rolling-staging` | Prepare → index → commit → kiểm tra → xóa batch dẫn xuất, rồi mới tạo batch kế | Hợp đồng fields và fingerprint đã ổn định |

Thứ tự: chốt schema no-folded → chứng minh writer tương thích → batch/cursor → commit/recovery → CLI/capacity → benchmark test20k.

Bất biến:

- Giữ `doc_id` nguyên bản, `chunk_id`, `chunk_order`, URL, offsets, hash và nội dung nguyên văn; `TextStore` vẫn đọc các chunk nguồn.
- Giữ định tuyến ngôn ngữ hiện tại theo `content_languages`, `source_language` và fallback trong `languages()`. Không áp dụng đề xuất ép tất cả theo ngôn ngữ nguồn.
- Giữ sáu index logic documents/chunks × vi/en/zh, thống kê BM25 trên toàn partition, query channels/RRF/budgets/k1/b ngoài ảnh hưởng trực tiếp của việc bỏ folded.
- Chỉ cleanup file staging do job mới tạo trong run directory mới. Không xóa source shards, dữ liệu crawl, thư mục lexicon staging, snapshots/index/candidates đã có.
- Không nạp bộ medical lexicon mới, sửa lỗi `Stroke.It`, thêm translation/reranker hoặc thay chunking trong task này.
- Corpus whitelist vẫn là snapshot 1.220.598 URL người dùng đã chọn. Chỉ benchmark trên test20k và query hiện có; không đọc `for_valid/`, không chạy full trong bước triển khai thử.
- Chưa cam kết Recall/F2 hoặc khả năng chạy full chỉ từ dung lượng staging thấp.

## 2. Khảo sát code và số đo có sẵn

| Thành phần hiện tại | Bằng chứng | Vấn đề khi thay đổi |
|---|---|---|
| `analyzers.py` | VI tạo syllables/shingles và folded; NFD là bước trung gian bỏ dấu | Phải xóa cả producer, không chỉ bỏ field lúc build |
| `models.py`, `query.py`, `backend.py` | FIELDS chứa folded; broad query có folded; boost 0.2 | Đồng bộ index/query và ngân sách 128 clauses |
| `corpus.py` | Prepare toàn bộ source shards, tạo JSONL theo sáu partition; tasks lưu path/hash | Xóa stage hiện tại sẽ làm resume cần file đã mất |
| `backend.py` | Một IndexCollection subprocess/partition, toàn bộ stage phải có trước build | Không có vòng prepare/index/cleanup theo byte |
| `store.py` | SQLite trỏ về source shard/record, không trỏ về prepared JSONL | Có thể xóa prepared sau commit mà vẫn hydrate nguyên văn |
| `utils.py` | Có flock, temp-write/fsync/replace cho JSON | Cần thêm durability của thư mục và recovery ledger |
| `capacity.py` | Dự phóng giữ toàn bộ staging | Không dùng lại công thức cũ để chứng nhận rolling |

Đọc trực tiếp snapshot `artifacts/retrieval/analyzer-fix-eval-20261015/candidate-final/` trong lượt phân tích trước:

- 20.000 source records, 19.898 document đủ nội dung, 62.941 chunks.
- Document views VI/EN/ZH: 10.689/4.520/4.770; chunk views: 34.377/6.385/22.179. Chỉ 81 document có hai view; mọi chunk có một view. Các count này phải giữ nguyên nếu input/routing không đổi.
- Prepared JSONL: 595.548.579 bytes; bỏ key/value folded theo cùng kiểu serialize giảm 29.463.305 bytes (~4,95%). Đây là byte staging, không phải số tiết kiệm Lucene đã đo.
- Dự phóng capacity cũ: ~81,8 GB. Thay staging toàn bộ bằng 300 MB, giữ cùng ước lượng index/registry/merge/headroom: ~28,9 GB. Chưa có index no-folded/rolling thật để xác nhận số này.

### 2.1. Phát hiện quan trọng về append

Runtime local có Pyserini 2.4.0, Anserini 2.3.0, Lucene 10.5.0, JDK 21. JAR SHA-256: `375848a9bb0a7514d2a8fe13df20086961570991bf20343abf0e5312af977def`.

`IndexCollection.Args` khai báo `append`, nhưng constructor trong tag 2.3.0 vẫn đặt `OpenMode.CREATE`. Đã đối chiếu bằng `javap -c` trên JAR local. Do đó **không dùng việc thêm `-append` vào command cũ làm giải pháp rolling**. Đây là căn cứ chọn writer trực tiếp, cần kiểm tra thực tế ở bước đầu triển khai.

Nguồn: [IndexCollection 2.3.0](https://github.com/castorini/anserini/blob/anserini-2.3.0/src/main/java/io/anserini/index/IndexCollection.java), [POM của tag](https://github.com/castorini/anserini/blob/anserini-2.3.0/pom.xml).

## 3. Hợp đồng bỏ folded

Schema mới có đúng năm text fields: `contents`, `broad`, `exact`, `anchors`, `title`; vẫn có field ID nội bộ của Anserini. `folded` không xuất hiện trong `Analysis.fields`, serialized prepared record, query fields, field boosts hoặc Lucene FieldInfos của snapshot mới. Không giữ field rỗng và không âm thầm thay bằng ascii-folding trong trường khác.

Các token còn lại giữ cách tạo hiện tại: VI compound/syllables/shingles còn dấu; EN Krovetz và surface alternatives; ZH Jieba/OpenCC/bigram; exact/anchors/title như cũ. Bỏ hàm `fold()` nếu không còn caller, không bỏ normalization cần cho phần khác.

Query `original-broad` của VI chỉ truy vấn `broad`; với một field, backend có thể dùng tối đa 128 terms thay vì chia 64/64 cho broad/folded. Vẫn giữ thứ tự term, dedupe và warning theo giới hạn thực tế. Không tạo thêm channel hoặc điều chỉnh RRF để bù.

Đánh đổi được chấp nhận trong thiết kế đề nghị: không còn kênh rescue có dấu ↔ không dấu. Query không dấu vẫn được phân tích theo literal của nó, nhưng không đảm bảo khớp tài liệu có dấu. Benchmark phải báo tác động này riêng, không gọi là chất lượng tăng mặc định.

Fixture hiện có chứa kỳ vọng folded, đặc biệt `vi-24`. Giữ nguyên fixture/profile cũ làm tài liệu regression; tạo profile kỳ vọng no-folded có truy vết từng khác biệt. Ca không dấu vẫn phải giữ nguyên text và kiểm tra token gốc ở broad; thêm kiểm tra không tự sinh token bỏ dấu từ text có dấu. Không xóa ca khó, không tính chức năng đã bỏ là thành công của benchmark cũ.

## 4. Phương án writer và ranh giới module

| Phương án | Lợi ích | Nhược điểm/quyết định |
|---|---|---|
| Thêm `-append` vào IndexCollection | Ít code | Không được chọn: OpenMode.CREATE trong runtime local |
| Build index nhỏ cho từng batch rồi addIndexes | Tái dùng CLI hiện có | Tăng JVM startup, index tạm/copy/merge; không phải phương án mặc định |
| Lucene IndexWriter qua PyJNIus hiện có | Ghi vào cùng sáu partition, commit user data, không thêm dependency | **Đề nghị chọn**; cần chứng minh JNI và field parity trước |

`DirectLucenePartition` trong `index_writer.py` dùng class đã có trong fatjar; `JsonCollection.Document.fromString()` → `DefaultLuceneDocumentGenerator(Args)` → `IndexWriter.addDocument()`. Generator tạo `id`/doc values và `contents`; các field phụ được thêm rõ ràng bằng `FieldType` tương đương tùy chọn Anserini (`DOCS_AND_FREQS`, norms bật, không lưu text). PyJNIus không nhận trực tiếp Python list vào Java `String[] Args.fields`; lần thử đầu tiên vì thế chỉ index `contents` và làm lệch truy hồi. Thêm fields thủ công qua `StringReader` cho phép writer WhitespaceAnalyzer tạo token đúng, đồng thời giữ generator cho ID/contents. Kiểm thử synthetic xác nhận BM25 score và top IDs trùng bulk trong ngưỡng §10; full corpus parity chưa chạy.

Writer dùng WhitespaceAnalyzer, BM25Similarity cùng cấu hình indexing hiện hành, `useCompoundFile=false`. Khởi tạo index mới chỉ ở đường dẫn trống có ownership marker; resume dùng **APPEND**, index mất phải báo lỗi, không CREATE_OR_APPEND để che mất partition. Mỗi partition được tạo initial empty commit có run/spec identity trước batch đầu; partition không có record vẫn hợp lệ.

Bootstrap có trạng thái INITIALIZING riêng. Nếu chết trước khi tạo đủ sáu initial commits, chỉ được tạo lại scratch partition chưa có initial commit khi ownership đúng, chưa có batch PREPARED/receipt và expected count bằng 0. Partition đã initial-commit thì xác minh/giữ lại. Sau khi INITIALIZED đã durable, mất bất kỳ partition nào phải fail; không dùng ngoại lệ bootstrap để dựng lại index đã có dữ liệu.

Giữ tối đa sáu writer trong cùng JVM đã dùng cho English analyzer, thao tác Java tuần tự qua lock riêng dùng chung với `JAVA_SEARCH_LOCK`; không tuyên bố threads cho phép chạy JNI song song. RAM buffer đề nghị 16 MiB/writer (~96 MiB cộng dồn, không phải tổng RSS), serial merge scheduler để tránh sáu merge đồng thời; normal merge policy, không forceMerge cuối batch. Ghi cấu hình này vào fingerprint, đo RSS/throughput trước khi chọn production.

`setCommitOnClose(false)` và explicit commit/rollback là bắt buộc. Gặp lỗi thì rollback những thay đổi chưa commit; không dùng close có thể tự commit dữ liệu chưa có receipt. Có regression cho close/rollback, append nhiều batch, identity sai và commit dở một partition; parity đã đạt trên fixture synthetic VI/EN/ZH nhỏ. Full corpus merge/segment parity còn là gate.

Public boundary đề nghị:

- `CorpusEventReader`: validate source, tạo event có cursor/metadata và prepared view theo thứ tự xác định.
- `BatchStager`: một batch byte-bounded, hashes/counts và ownership; không biết Lucene.
- `LuceneBatchWriter`: ingest/commit/read receipt/rollback, không được xóa stage.
- `RollingBuildCoordinator`: sở hữu lock, ledger, resume, kiểm tra, cleanup và publish.
- `TextStore`: nguồn hydrate như hiện tại; bổ sung thông tin routing/ledger trong registry mới.

Không đổi API CandidateEngine/SearchBackend hoặc format candidate/submission. Dùng type hints, dataclass/Protocol khi có interface thực, Path và helper atomic hiện có; tránh thêm framework/plugin.

## 5. Batch theo byte và cursor

Giá trị cấu hình đề nghị, byte thập phân:

```toml
build_mode = "rolling"
staging_target_bytes = 250000000
staging_max_bytes = 300000000
writer_ram_buffer_mib = 16
disk_reserve_bytes = 2000000000
```

`staging_target_bytes` là ngưỡng chốt batch mong muốn; `staging_max_bytes` là trần cứng tổng file dưới `run/staging/`, bao gồm file `.tmp`, JSONL và control/ownership manifest. Reserve tối đa 1 MB cho control files, giới hạn độ dài path/control schema; luôn tính quota thực tế trước khi ghi. Validate 0 < target <= max - control_reserve. Chỉ một batch PREPARING/PREPARED/COMMITTING tồn tại, không prefetch batch kế trên đĩa. Empty partition không cần JSONL rỗng nhưng vẫn có receipt.

Không dùng số source records hoặc kích thước file raw làm giới hạn staging. Batch có thể chứa nhiều shard nhỏ hoặc một phần shard lớn. Gặp input record lớn thì chia batch **giữa các prepared view hoàn chỉnh**, không cắt `chunk_text`, không chia đôi JSONL output record. Một document và các chunk của nó được phép đi qua nhiều batch, nhưng view document chỉ được index một lần.

Cursor ổn định: `(source_index, binary_record_offset, next_event_ordinal)`. Thứ tự events được version hóa: eligible child theo thứ tự nguồn, từng language theo `languages()`; cuối cùng document views; event metadata-only cho skipped/error-status records. Cursor cuối source trỏ sang shard kế/EOF. Resume giữa một source record có thể đọc và phân tích lại record đó rồi bỏ qua các ordinal trước cursor; không cần lưu object Python lâu dài.

Đo kích thước prepared record ở lượt streaming đầu tiên, không ghép trường token thành một string/JSON khổng lồ. Nếu record không vừa phần còn lại thì chốt batch hiện tại; lượt sau serialize record theo các mảnh tối đa 8 KiB, record chưa ghi được tạo lại từ cursor ở batch kế. Nếu riêng một prepared record vượt hard limit trừ control reserve: dừng với `PreparedRecordExceedsBudget`, ghi doc/chunk/partition, byte limit và size đã thấy; không ghi phần vượt quota, không silently skip hoặc tăng trần. Test so byte đầu ra với `Analysis.record`/JSON chuẩn, kể cả chuỗi Unicode và escape.

Có thể chốt batch sớm theo giới hạn số metadata events (đề nghị 10.000) để batch gồm nhiều record bị skip không giữ SQLite transaction quá lâu. Đây là giới hạn giao dịch phụ, không thay giới hạn byte. Source line limit 64 MiB hiện có vẫn áp dụng; không tuyên bố staging bound đồng nghĩa RAM bound.

## 6. Schema mới và độ bền

Chỉ tạo registry/schema mới trong run directory mới; không ALTER hoặc migrate tự động SQLite snapshot cũ.

Manifest đề nghị có `manifest_format_version=2`, `index_schema_version=2`, `analyzer_profile="medical-no-folded-v1"`, `build_mode`, `run_id`, trạng thái, input/routing/resource/code/runtime fingerprints, build policy và counts. Hash writer/rolling/models/runtime/serialization policy phải được bao gồm ngoài bốn file hiện có trong fingerprint; search kiểm tra phần fingerprint phục vụ analysis/schema, resume kiểm tra cả build policy.

Registry mới giữ bảng nguồn/documents/chunks và bổ sung:

| Đối tượng | Dữ liệu cần giữ |
|---|---|
| documents/chunks | Routing mask bit VI=1, EN=2, ZH=4; 0 với document không index; không sửa text/IDs |
| build_batches | batch ID, start/end cursor, counters delta, stage hashes/counts/digests, trạng thái |
| partition_receipts | batch ID + partition, commit generation, cumulative/added count, stage/spec hashes |
| build_progress | cursor batch đã COMMITTED, aggregate counters, EOF/publish state |

Routing mask giúp đối chiếu đúng các view đa ngữ khi staging đã bị xóa. Tránh lưu toàn bộ token hoặc một danh sách IDs lớn vào SQLite. Mỗi cặp batch/partition chỉ có một receipt, mỗi source ID/chunk ID duy nhất; replay cùng source+offset+hash được kiểm tra, cùng ID ở vị trí nguồn khác bị từ chối.

SQLite dùng foreign keys và synchronous FULL, transaction ngắn theo batch, không WAL tăng vô hạn. Có thể giữ rollback journal theo mặc định hiện có; nếu chọn WAL ở triển khai phải đưa WAL/checkpoint vào dung lượng và đo riêng. Manifest/ownership/checkpoint được fsync file và parent directory sau rename; bổ sung helper durability có phạm vi rõ, không thay dữ liệu gốc.

## 7. State machine và giao thức commit

```text
PREPARING → PREPARED → COMMITTING → COMMITTED → CLEANED
                  (receipt độc lập cho sáu partition)
```

1. Giữ flock toàn run. Xác minh input/resource/code/policy và đối chiếu receipt đang có trước khi ghi.
2. PREPARING: stream source từ cursor; ghi stage và metadata trong SQLite transaction. Chưa bắt đầu Lucene ingest cho batch chưa PREPARED.
3. Flush/fsync tất cả stage, atomic seal ownership/control manifest, fsync thư mục; commit transaction gồm metadata, cursor range và trạng thái PREPARED. Nếu chết trước bước này thì batch chưa durable, quay về cursor trước batch.
4. Với từng partition theo thứ tự cố định: xác minh stage hash; nếu marker đã chứng minh batch này committed thì đối chiếu và bỏ qua ingest; nếu marker ở batch trước thì ingest tất cả record của partition.
5. Trước commit đặt `setLiveCommitData` gồm `run_id`, `spec_hash`, `batch_id`, `partition`, stage SHA, event digest, cumulative live count. Commit, mở committed reader kiểm receipt/counts rồi mới ghi SQLite receipt. Partition rỗng cũng commit marker để sáu receipt cùng batch.
6. Khi sáu partition đã có committed receipt khớp dữ liệu, SQLite ghi COMMITTED + cursor/counters. Không coi sáu index và SQLite là một transaction phân tán atomic.
7. Cleanup payload JSONL đúng danh sách trong ownership manifest; giữ control/ownership marker tới khi SQLite ghi CLEANED durable. Sau đó mới gỡ marker/thư mục batch và fsync parent; hoàn tất phần này rồi mới tạo batch kế. Nếu crash ở khoảng CLEANED nhưng control file còn, resume chỉ dọn nốt control đã được ledger cho phép. COMMITTED còn một phần payload là trạng thái phục hồi hợp lệ.
8. EOF: đối chiếu toàn bộ IDs/live counts/routing/schema với SQLite, đóng writer có kiểm tra lỗi, tạo completion marker; publish cả cây `indexes.building/` thành `indexes/` bằng rename cùng filesystem; sau cùng manifest đặt READY. Không search run đang build.

Idempotence đến từ durable commit marker và xử lý batch tuần tự, **không replay addDocument mù** và không mặc định updateDocument để che duplicate input. Internal Lucene document number/sequence number không được dùng thay source ID hoặc durable batch ID.

### 7.1. Bảng phục hồi bắt buộc

| Điểm gián đoạn | Hành vi resume |
|---|---|
| Bootstrap chưa có đủ initial empty commits | Xác minh ownership/zero expected count và điều kiện INITIALIZING; chỉ tạo lại scratch partition chưa durable |
| File tạm có nhưng PREPARED transaction chưa tồn tại | Xóa phần dẫn xuất PREPARING có ownership đúng, quay về cursor cuối đã commit |
| PREPARED, chưa partition nào commit | Validate stage, ingest từ đầu batch; writer uncommitted được rollback |
| Một số partition đã commit | Đọc marker thật, skip partition đã commit, ingest phần còn lại |
| Lucene commit xong, SQLite receipt chưa ghi | Reconcile từ commit user data; không ingest lần hai |
| SQLite receipt báo committed nhưng Lucene marker sai/mất | Fail closed; không tự CREATE hoặc đánh dấu hoàn thành |
| Sáu commit xong, chưa ghi COMMITTED global | Validate sáu marker, hoàn tất checkpoint rồi cleanup |
| COMMITTED, xóa được một phần staging | Cleanup tiếp file còn lại; file đã xóa hợp lệ; không reprepare/reindex batch |
| CLEANED nhưng ownership/control file chưa gỡ | Đối chiếu ledger, dọn nốt control; không tạo batch thứ hai trước khi hoàn tất |
| PREPARED/COMMITTING bị mất hoặc đổi stage | Báo lỗi; không đoán dữ liệu hoặc xóa phần còn lại |
| Rename publish xong, READY manifest chưa ghi | Kiểm completion marker và sáu index ở cây đã publish rồi hoàn tất READY |
| READY | Chạy lại index là validate/no-op; không thay index |

`SIGINT`/exception phải rollback writer chưa committed, đóng handles, giữ batch PREPARED phục hồi được. Hard kill được xử lý bằng marker/ledger khi khởi động lại; không phụ thuộc finally đã chạy.

## 8. Cleanup và dung lượng

Danh sách được phép xóa chỉ gồm JSONL/control/temporary files có ownership đúng dưới **run mới** `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/staging/`. Run test20k đã hoàn tất: ba batch lần lượt được commit và cleanup; cuối run chỉ còn ownership marker 133 bytes. Các e2e dùng `TemporaryDirectory` riêng và tự cleanup. Code từ chối symlink/path traversal/path nằm ngoài run; không recursively delete thư mục người dùng đưa tùy ý. Mất ownership marker bất ngờ phải báo lỗi. Source/lexicon/index cũ không thuộc danh sách cleanup.

Giới hạn 300 MB là staging bytes, không phải index peak, SQLite journal, RAM hoặc toàn job. Số filesystem allocated bytes có thể lớn hơn logical bytes; ghi cả hai khi đo. Log theo batch, không log toàn bộ token/text; log quay vòng/giới hạn, registry/journal và log bytes phải xuất hiện trong báo cáo.

Capacity mới ghi riêng final index estimate, metadata+routing/ledger, active staging cap, normal merge reserve, log/journal, filesystem free/headroom. Dùng số đo pilot no-folded/rolling mới; khi đang resume tính phần tăng còn lại để không double-count index đã nằm trên đĩa. Bản capacity cũ giữ nguyên.

Preflight full đánh giá đích tổng thể; runtime guard trước batch/ingest/commit kiểm free space và merge reserve theo policy. Mức `disk_reserve_bytes` 2 GB là ngưỡng dừng khẩn tối thiểu, không thay đủ dung lượng merge và phần còn lại của index. Low disk/ENOSPC/OOM dừng có lỗi và giữ checkpoint hợp lệ; không tự xóa output khác.

## 9. CLI và tương thích đề nghị

Command `index` thực hiện pipeline rolling trọn vẹn. `configs/rolling-test.toml` tham chiếu test20k/scope/corpus và snapshot C đã xác minh; lệnh trên READY snapshot là no-op. CLI cũ `prepare`/`build` vẫn dùng bulk làm đối chứng no-folded, từ chối gọi chéo chế độ trên một run. Dependencies không đổi; muốn dựng snapshot mới phải chọn run-dir mới và đạt disk gate.

Các lệnh chạy lại snapshot đã xác minh (index trả no-op khi READY) và search:

```bash
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m sbtc.Scripts.Retrieval.cli index --config sbtc/Scripts/Retrieval/configs/rolling-test.toml
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m sbtc.Scripts.Retrieval.cli search --config sbtc/Scripts/Retrieval/configs/rolling-test.toml --queries newcorpus/query.parquet --output artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/candidates.jsonl
sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m unittest discover -s sbtc/Scripts/Retrieval/tests -v
```

Format candidate/export không đổi. Snapshot có folded trước đây không sửa/xóa; code mới từ chối fingerprint/schema không tương thích với thông báo cần run mới. Rollback vận hành bằng snapshot và phiên bản code cũ tương ứng, không giả định code no-folded sẽ search index cũ giống trước.

## 10. Nghiệm thu và kiểm thử dự kiến

| Nhóm | Điều kiện đạt |
|---|---|
| No-folded | Field không tồn tại từ analysis tới FieldInfos/query; năm field còn lại khớp output cũ đã bỏ folded |
| Source fidelity | Input/corpus hashes giữ nguyên, tất cả 62.941 chunk hydrate đúng doc/order/text/hash |
| Routing | Giữ nguyên unique counts và sáu partition view counts test20k nêu ở mục 2 |
| Staging | Tối đa một batch; tổng logical bytes dưới staging <= configured hard limit cả khi lỗi/resume |
| Commit/recovery | Inject lỗi trước/sau mọi ranh giới ở bảng 7.1; crash sau 1/3/5 partition commit; resume cùng IDs/counts/postings và không duplicate |
| Schema/locking | Run cũ sai fingerprint/mode bị từ chối; hai writers bị chặn; empty partition/empty indexed batch/EOF đều hoàn thành đúng |
| Bulk/rolling parity | Cùng no-folded/schema/routing: cùng live IDs, term DF/TF/norms, hydration, BM25 scores trong abs 1e-5 + rel 1e-6 |
| Ranking | Với A/C, candidate set đổi ở 1.200 query; top-20 overlap 75,40% docs / 73,16% chunks. Không có relevance labels để đánh giá tốt/xấu |
| Publish/cleanup | Không READY trước full verification; resume sau cleanup/publish đúng; không file nguồn hoặc output cũ bị xóa |

Thêm edge cases: UTF-8 bytes khác char count; source record sinh nhiều views chia qua batch; một output record vượt cap; skipped-status-only batches; duplicate ID khác source offset; stage/hash/source mutation; receipt mất; SQLite journal; cleanup fail; merge failure/ENOSPC. Test nguồn dùng bản dẫn xuất test20k; fixtures synthetic chỉ kiểm hợp đồng cơ học, không làm qrels relevance.

Thiết kế benchmark ba run:

- A: baseline folded/bulk có sẵn `analyzer-fix-eval-20261015/candidate-final` và candidates tương ứng; giữ artifacts/hash.
- B: no-folded/bulk trên cùng input/queries/resources, run mới.
- C: no-folded/rolling trên cùng input/queries/resources, run mới.

A↔B đo ảnh hưởng bỏ folded; B↔C cô lập thay đổi cách build. B và C có cùng field/analyzer fingerprint phục vụ search, khác build-policy fingerprint. Báo byte từng field/index/registry, staging peak, free-space minimum, RSS Python/JVM, build/commit/merge durations, queries/sec/p50/p95, top-K overlap/candidate counts/warnings. Có tập query có dấu/không dấu minh họa giữ riêng, không dùng để gán điểm corpus. Không có independent qrels thì `relevance_metrics=null`; không tuyên bố F2 tăng.

Đã chạy A↔C: A là `analyzer-fix-eval-20261015/candidate-final`, C là `no-folded-rolling-test20k-after-regex-fix`; cả hai dùng cùng 20 shard, scope, corpus, lexicon snapshot và 1.200 query. A cũ có field `folded`, C không có. A/C không cô lập riêng no-folded vì query `broad` nhận term budget khác nhau và C dùng rolling writer cùng bản fix Underthesea literal. **B no-folded bulk chưa chạy**, nên parity full20k B↔C và tác động riêng của từng yếu tố chưa đo. Chi tiết ở report đã dẫn đầu tài liệu.

Không giữ B và C đầy đủ đồng thời nếu disk gate không đạt. Output nào cần cleanup bổ sung ngoài staging mới phải liệt kê chính xác và xin duyệt riêng; có thể dùng storage đủ dung lượng. Không tự xóa baseline để lấy chỗ.

## 11. Nguồn kỹ thuật

- [Anserini DefaultLuceneDocumentGenerator 2.3.0](https://github.com/castorini/anserini/blob/anserini-2.3.0/src/main/java/io/anserini/index/generator/DefaultLuceneDocumentGenerator.java): đối chiếu field options và ID representation với bulk.
- [Lucene 10.5.0 IndexWriter](https://lucene.apache.org/core/10_5_0/core/org/apache/lucene/index/IndexWriter.html): commit user data và rollback dùng làm receipt/recovery; flush riêng không đủ durable. Không coi sequence number của một writer instance là checkpoint qua restart.
- [Lucene 10.5.0 IndexWriterConfig](https://lucene.apache.org/core/10_5_0/core/org/apache/lucene/index/IndexWriterConfig.html): explicit open mode, commit-on-close, RAM/merge configuration.

## 12. Trạng thái kiểm chứng sau implementation

- `py_compile` 31 file module/test: pass. Sau fix lexicon literal trên dữ liệu thật, `unittest discover -s sbtc/Scripts/Retrieval/tests -v`: 56 tests passed.
- Rolling e2e dùng 6 record synthetic VI/EN/ZH, cap staging 5.000 bytes và target 700 bytes: tạo nhiều batch, không vượt hard cap, cleanup sạch batch, giữ route/hydration và khớp top IDs/BM25 scores với bulk trong tolerance. Thêm smoke so sánh trên 4 source records được trích từ test20k (3 document có chunk VI/EN/ZH và 1 record lỗi), ép target 10 KB; counts/routing, doc/chunk top IDs/scores và source hydration khớp bulk. JSON serializer đo size theo luồng và ghi từng mảnh không quá 8 KiB, không tạo một joined-string theo field.
- Fault injection đã kiểm tra interruption sau commit partition đầu tiên rồi resume; không duplicate doc/chunk. Writer có regression cho explicit commit, append, failed identity, CREATE không overwrite và close/rollback không implicit commit.
- Fixture strict: 90 cases × 2 modes; 69/69 contract cases pass, 0 contract mismatch. 1 challenge mismatch là `en-07 Stroke.It`; challenge không tính là pass/fail acceptance.
- C rolling full test20k đã hoàn tất `READY`; toàn bộ counts/6 partition khớp nguồn và A; 1.200 query đã search. Peak staging 249.999.677 bytes, cuối run còn 133-byte ownership marker. A↔C candidate comparison đã ghi trong report; B no-folded bulk, full capacity estimate mới, và qrels relevance metrics chưa có. Rolling giới hạn staging chứ không xóa nhu cầu final index/merge/registry. Không tuyên bố Recall/F2 tăng.
- Một lần chạy `compileall` vô tình duyệt cả `.runtime/uv-cache` và bị dừng để tránh tiếp tục compile dependency cache; sau đó chỉ py_compile 31 file trực tiếp trong Retrieval và tests, thành công.

Đặc tả này thay field profile cũ cho snapshot mới. Kết quả test/benchmark profile cũ không được gắn sang profile mới. Tất cả build/test đã dùng temporary run directories; không sửa hoặc xóa source chunks, snapshots/index cũ hay corpus.
