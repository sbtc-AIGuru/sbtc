# Pipeline Qwen3 + Elasticsearch trên Kaggle

Notebook mới: `BackEnd/app/Database/Notebook/ViBioMIR_Hybrid_Qwen3_Elasticsearch_Kaggle.ipynb`.
Giữ nguyên notebook GTE cũ và các thay đổi đang có trong dự án.

18 code cell, mỗi cell một module, có mô tả tiếng Việt ngay trước cell:

1. Cấu hình.
2. Dependency của Python kernel hiện tại và cache temp.
3. Kiểm tra SHA và nạp mã pipeline gốc.
4. Ghép hai Parquet query, kiểm tra đủ ID/text/vector/weight.
5. Self-check adaptive weighted RRF.
6. Xác minh manifest + chứng nhận snapshot + dung lượng đĩa.
7. Tải/kiểm tra corpus từ Google Drive.
8. Tạo bản corpus có nhãn ngôn ngữ bằng đúng quy tắc local, kiểm tra hash nhãn/corpus và count.
9. Tải Elasticsearch 9.5.1 và SmartCN cùng phiên bản.
10. Khởi động Elasticsearch cục bộ dưới tài khoản không phải root.
11. Dựng BM25 VI/EN/ZH bằng đúng preprocessing/mapping hiện tại.
12. Restore Qdrant FP16/HNSW và kiểm tra point/payload/vector.
13. Tải reranker tùy chọn bằng `hf download` đúng revision.
14. Cấu hình adapter, deadline, ef/exact và fingerprint.
15. Smoke test tối đa ba query.
16. Chạy pipeline, checkpoint và retry lỗi retrieval.
17. Kiểm tra nguyên văn output, ID, thứ tự và ZIP.
18. Dừng dịch vụ.

## Nguồn dữ liệu

- Chunk: link Drive người dùng cung cấp, file `ViBioMIR_chunks_with_recovery.jsonl`,
  5.734.771.809 byte. Notebook dùng gdown để xử lý trang xác nhận tải file lớn,
  resume vào file `.partial`, rồi kiểm tra SHA-256
  `a45123b3de7a9b048f83418515a3ec6b3dd09e1e4491dd361429b787659a3e7f`.
  Bản này chưa có `language`; cell riêng dùng nguyên `detect_language()` của dự án
  để tạo bản có nhãn với SHA-256
  `c973c3117f917ee7c14d8e671c459d8ca5a783610c62e3c8b00141a9bfbb91ae`.
  Hash nhãn và số lượng 3.811.358 VI / 540.913 EN / 584.564 ZH phải khớp lần
  gán nhãn local trước đó. Bản raw dùng cho snapshot không bị thay đổi.
- Chứng nhận: output version 1 của
  `nhminh107/vibiomir-qdrant-snapshot-recheck-20261025`.
- Snapshot thật: output version 1 của
  `nhminh107/vibiomir-qwen3-dense-fp16-hnsw-20261025`, được chứng nhận phía trên tham chiếu.
  Snapshot raw 18.820.493.824 byte, SHA-256
  `fb8b93924f5141ae5603033ea4c1df46ee29315f0e4c2ab1541680b9ed358646`.
  Manifest recovery gốc `complete=false` không bị sửa. Runtime tạo bản manifest riêng
  sau khi xác minh chứng nhận ràng buộc đúng snapshot/signature/count.
- Dataset query riêng tư chứa nguyên byte hai Parquet, `pipeline_source.zip` và
  `source-manifest.json`. Chỉ đóng gói các file mã nguồn được liệt kê rõ;
  không đóng gói `.env`, credentials, toàn repo hoặc dữ liệu khác.
  Kaggle tự giải nén ZIP khi tạo dataset: notebook và publisher kiểm tra SHA-256
  từng file trong thư mục `pipeline_source/`, không yêu cầu ZIP gốc còn trên mount.

## Chạy trên Kaggle

Chọn **CPU + Internet**. Mặc định `RUN_PIPELINE=False`: bản upload chỉ kiểm tra
mã/query/RRF, không chạy tác vụ index lớn hoặc chiếm GPU.
Đổi `RUN_PIPELINE=True` rồi **Run All** khi muốn chạy toàn bộ.

Bản chạy version 3 theo yêu cầu tiếp theo đã bật `RUN_PIPELINE=True`,
`HNSW_EF=256`, đủ 1.200 query và output riêng `submission_ef256`.
Giữ 4 nhánh, 100 ứng viên/nhánh, top 200, tắt exact và rerank.
Lệnh đóng gói mặc định vẫn tạo bản kiểm tra nhẹ; để chủ động chạy lại bản full:

```bash
.venv/bin/python -B -m Scripts.Kaggle.prepare_hybrid_retrieval_notebook --run-full --hnsw-ef 256
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook launch --new-version --run-full
```

Không chạy lại lệnh launch khi phiên trước còn đang chạy. Mỗi lần push tạo phiên
mới, phải tải corpus/restore snapshot/dựng BM25 lại.

Notebook được tạo mới mặc định: 4 nhánh, 100 ứng viên mỗi nhánh, top 200, ef=512, rerank tắt;
6 nhánh có thể chọn ở cell cấu hình. `HNSW_EF=None` giữ mặc định index;
thay đổi ef/exact, weights, nguồn hoặc giới hạn cần output/checkpoint mới.
Cell cấu hình cũng hỗ trợ `SEARCH_MODE="3-branch"`: chỉ Dense VI/EN/ZH,
RRF `1/3` mỗi nhánh, bỏ qua `dense_weight`. Cell 07–11 được bỏ qua, không tải
corpus, gán nhãn hoặc cài/chạy/index Elasticsearch. Cell kiểm tra output đối
chiếu nguyên văn với payload Qdrant theo batch. Chọn OUTPUT_NAME/TEMP_ROOT mới
khi đổi chế độ. Bản mã nguồn mới cần được upload cùng notebook trước khi dùng
chế độ này trên Kaggle; thay đổi local không tự cập nhật phiên đã xuất bản.
Elasticsearch preprocessing dùng một worker để không phụ thuộc Python 3.14;
full import có thể kéo dài nhiều giờ trên CPU Kaggle. Không nhầm thời gian import
với thời gian truy hồi sau khi index đã sẵn sàng.

Snapshot, corpus, service storage, source và cache đặt dưới `/kaggle/temp`.
Preflight yêu cầu khoảng 78 GiB scratch theo ngân sách bảo thủ; không dùng RAM disk.
Elasticsearch chạy binary có JDK đi kèm, không dùng Docker, không sửa sysctl.
Nếu kernel là root, chỉ service Elasticsearch hạ uid/gid; không thay tài khoản kernel.

Output trong `/kaggle/working/retrieval`: JSON, ZIP, checkpoint, lỗi nếu có,
`run_report.json`, `<OUTPUT_NAME>.verified.json` và `pipeline.log`.
Log có cả dòng Qdrant dense và HTTP Elasticsearch. Dữ liệu nguồn đầy đủ trong
payload nên không cần PostgreSQL. API/UI hiện tại cũng có trong source ZIP;
thao tác notebook dùng các cell thay giao diện upload cục bộ.

Checkpoint có thể chạy lại trong cùng phiên với cùng cấu hình/nguồn. Phiên Kaggle
mới phải restore Qdrant và dựng BM25 lại; muốn tiếp tục checkpoint cũ phải tải
các file checkpoint/output đi kèm về đúng OUTPUT_DIR và giữ cấu hình nguyên vẹn.
Cell shutdown đóng dịch vụ; nếu đã chạy cell này, khởi động dịch vụ lại trước khi
truy hồi tiếp. Không coi `COMPLETE` ở chế độ validation-only là đã chạy full corpus.

## Đóng gói và upload

Dùng `.venv` hiện có; Kaggle SDK được đọc từ cài đặt pipx hiện có, không cài lại:

```bash
.venv/bin/python -B -m Scripts.Kaggle.prepare_hybrid_retrieval_notebook
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_kaggle_hybrid_notebook.py
```

Gói upload: `artifacts/kaggle-hybrid-retrieval-20261026/{queries,kernel}`.
Sau khi được phép thực hiện các lệnh ghi ngoài sandbox:

```bash
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook upload-inputs
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook dataset-status
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook verify-inputs
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook launch
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook verify-notebook
.venv/bin/python -B -m Scripts.Kaggle.publish_hybrid_retrieval_notebook status
```

Publisher tạo dataset riêng tư, giữ Parquet thay vì chuyển CSV, đọc lại để so SHA
từng file, rồi push notebook riêng tư ở chế độ kiểm tra nhẹ. Nguồn notebook,
privacy, accelerator và các input được pull/readback kiểm tra trước bàn giao.
Không ghi lên index hoặc restart API đang chạy trên máy local.

## Kết quả kiểm tra nhẹ trước khi chạy full, 26/10/2026

- Notebook riêng tư version 2, CPU + Internet, 18 code cell; mã nguồn/input/privacy
  đã được pull/readback đối chiếu với bản local.
- Dataset riêng tư version 2; cả hai Parquet và 23 file mã nguồn cùng manifest
  (26 file tổng cộng) đã được tải lại, SHA-256 khớp bản đã chuẩn bị.
- 15 kiểm thử local pass, gồm mô phỏng archive được Kaggle giải nén, ghép query,
  ràng buộc chứng nhận snapshot, gán nhãn giữ nguyên dữ liệu/hash, adapter deadline/ef,
  BM25 receipt và hạ quyền process Elasticsearch. Tất cả cell parse được bằng cú pháp Python 3.11.
- Phiên Kaggle kiểm tra nhẹ đã **COMPLETE**: đủ 1.200 dòng query được xác minh,
  hash đầu vào/mã nguồn khớp, self-check RRF pass.
- Chưa tải toàn corpus, dựng BM25 hoặc restore/chạy full retrieval trong notebook
  này; bật `RUN_PIPELINE=True` để chạy các cell đó. Chưa chạy reranker GPU.

Biên bản local nằm trong `artifacts/kaggle-hybrid-retrieval-20261026/`:
`dataset-verification.json`, `notebook-verification.json`,
`kaggle-validation-report.json`, `launch-receipt.json`.
