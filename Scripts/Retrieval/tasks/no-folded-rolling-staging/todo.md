# Checklist no-folded và Rolling Staging

Trạng thái 15/10/2026: **implementation v1 và C rolling full test20k đã xong; A↔C candidate comparison đã chạy; B và relevance evaluation còn thiếu**.

- [x] Khảo sát analyzer/query/schema/corpus/store/backend/capacity và test hiện có.
- [x] Đối chiếu runtime local/JAR bytecode với source Anserini 2.3.0, xác nhận append flag chưa đủ vì OpenMode.CREATE.
- [x] Soạn [đặc tả](../../SPEC-no-folded-rolling-staging.md) và [kế hoạch](plan.md); người dùng duyệt rồi yêu cầu triển khai.
- [x] RS01 Freeze profile no-folded, schema v2, fixture và cấu hình build policy.
- [x] RS02 Bỏ folded khỏi analyzer/query; fixture no-folded strict pass.
- [x] RS03 Manifest v2, fingerprint tách analysis/build policy, bulk control.
- [x] Checkpoint A: analyzer/schema chạy trên bulk và test integration nhỏ.
- [x] RS04–RS05 DirectLucenePartition/JNI, receipts, explicit append/commit/rollback và BM25 parity synthetic.
- [x] RS06–RS07 Cursor theo view, staging hard cap, registry/routing, fsync và ownership manifest.
- [x] RS08–RS09 Recovery sau partial commit, cleanup do run sở hữu, kiểm tra six partitions và atomic publish.
- [x] RS10 CLI `index` và [rolling-test.toml](../../configs/rolling-test.toml).
- [~] RS11 Disk guard/metrics có code; C run đo peak staging 249.999.677 bytes, peak RSS 891.340 KiB, free space thấp nhất theo batch metrics 13.208.588.288 bytes; low-space/ENOSPC và capacity full mới chưa chạy.
- [~] Checkpoint C/D: C full test20k đã READY, stage cap ép ba batch và cleanup thành công; recovery fault test sau một partition commit đã pass; crash matrix đầy đủ còn thiếu.
- [x] RS12 Retrieval suite 56 tests pass sau Underthesea literal regression; strict analyzer fixture 69/69 contract pass, 1 challenge mismatch `Stroke.It` được giữ nguyên báo cáo.
- [~] RS13 A↔C full test20k, 1.200 query đã so sánh; no-folded bulk B và B↔C parity chưa chạy. Không có qrels nên relevance/F2 chưa đo.
- [x] RS14 Cập nhật report, README, spec/status, docs_AI và thaydoicongnghe; báo rõ giới hạn/đánh đổi.

Không gộp các gate từ điển, dịch, reranking hoặc full corpus vào trạng thái hoàn thành C test20k. Xem [báo cáo A↔C](../../REPORT-no-folded-rolling-test20k-20261015.md); candidate thay đổi không phải bằng chứng Recall/F2 tăng.
