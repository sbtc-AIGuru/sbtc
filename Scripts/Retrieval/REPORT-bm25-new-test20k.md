# Báo cáo BM25 mới — 15/10/2026

## Kết quả thực tế

BM25 mới từ đầu trong `sbtc/Scripts/Retrieval/`; không đọc/import code archive, không đọc `for_valid`, không ghi đè corpus/chunks nguồn. SPEC, kế hoạch, README và review nằm trong module; thay đổi/khó khăn/fixes ghi root `docs_AI.md`.

| Kiểm tra | Kết quả |
|---|---:|
| Unit + actual Lucene integration | 30 tests đạt, 13,785s |
| Input test20k root records | 20.000 |
| OK documents / status skipped | 19.898 / 102 |
| Eligible chunks | 62.941 |
| Index documents VI / EN / ZH | 10.689 / 4.520 / 4.770 |
| Index chunks VI / EN / ZH | 34.377 / 6.385 / 22.179 |
| Source hydration/hash/FK/order | 62.941/62.941 đạt, 6,23s |
| Actual batch searches | 1200 |
| Batch wall time | 253.78s |
| Queries/second | 4.73 |
| Search p50 / p95 | 0.230s / 0.349s |
| Linux peak RSS Python + native + JVM | 801.6 MiB |

Mixed-language source có thể có nhiều index views nên không cộng views thành unique documents/chunks. Corpus snapshot ở đây là toàn bộ chunk test20k còn lại; raw `data_final/test_20k.jsonl` không tồn tại ở vị trí cũ. Scope ID/URL dẫn xuất lưu riêng.

Batch dùng **12 query cơ học lặp đến 1.200 lần**, tokenizer cache warm, actual six-index search mỗi lượt, budget rộng 300 docs/1000 chunks/language/channel và fused1000/3000. Không phải bộ 1.200 query cuộc thi, không có qrels, không đo cold translation hay độ đa dạng query thật. Không có điểm Precision/Recall/F2 relevance để báo. Phép chấm BTC có implementation và mathematical tests, chưa áp dụng lên nhãn độc lập.

## Đọc mẫu output

| Query | Ví dụ top chunk thật | Nhận xét |
|---|---|---|
| Viêm phổi mắc phải cộng đồng ở trẻ em | doc6281983, order0: Vitamin E administration may decrease the incidence of pneumonia in elderly males | Khớp disease nhưng lệch population trẻ em; cần full-query translation/reranker |
| Amoxicillin điều trị viêm phổi | doc5171604, order0: bài omeprazole/amoxicillin/clarithromycin điều trị H. pylori | Khớp thuốc nhưng lệch bệnh/intent; OR/alias channel đang quá rộng cho final ranking |
| Triệu chứng tăng huyết áp | doc5096477, order0: HSP72 protects against organ damage, hypothesis | Khớp bệnh; không đảm bảo trả trực tiếp triệu chứng |
| Bệnh phổi tắc nghẽn mạn tính | doc5484899, order0: Medical therapy for chronic obstructive pulmonary disease in 2007 | Có nội dung khớp chủ đề; relevance/gold coverage vẫn chưa chấm |

Tập rộng giúp reranker có cơ hội chọn, nhưng chưa đo có bao nhiêu tài liệu/chunk đúng thật hoặc bị bỏ sót vì budget. Nhiều query đạt trần1000/3000; không mặc định trần này đã bao phủ tối đa. Cần dictionary production, query translations bảo toàn intent/population/drug và nhãn độc lập để điều chỉnh. Không sửa ranking bằng tuning lên `for_valid`.

## Sửa lỗi concurrency từ benchmark

180-call/2-thread repro trước fix: 25 lượt sai doc/chunk partition, 74 rank mismatches. Sau khóa Java calls process-wide: 0/0; thêm regression serial/parallel parity. PyJNIus shared receiver descriptor được đối chiếu [source chính thức](https://raw.githubusercontent.com/kivy/pyjnius/master/jnius/jnius_export_class.pxi). Index Lucene giữ nguyên; fix ở boundary backend. Calls Java trong một process hiện serialize; chưa implement process worker pool. Không gọi threads hiện tại là speedup.

## Điều kiện trước full

- **Whitelist đã chốt (cập nhật 15/10/2026):** người dùng chọn bản active **1.220.598 URL** cho full và xuất bài; file/hash được ghi trong README. Index test20k dùng đúng snapshot này nên không cần rebuild vì lựa chọn này. Giữ 1.320 IDs ngoài bản asked cũ. `asked.md` vẫn ghi 1.194.469; chưa có xác minh mới từ BTC về điểm lệch này.
- **Disk gate fail:** staging595,2MB/index150,7MB/SQLite121,5MB; dự phóng full1.220.598docs/4.342.218chunks cần ~81,8GB free có scratch/headroom, hiện~22,7GB. Cần ổ/dung lượng hoặc lifecycle staging khác được kiểm thử.
- **Assets:** 12 local seed concepts chưa đủ coverage; mở rộng cần source/license/ontology review. Local translator adapter có code/contract, chưa provision/inference model thật, neural environment chưa lock.
- **Relevance:** candidates rộng chưa là final selector/reranking; chưa có independent Precision/Recall/F2. Không nộp demo1200 query lặp hoặc demo12query như bài thi.

**Kết luận:** nền BM25 sparse mới đã chạy và kiểm chứng trên toàn bộ snapshot test20k, có input cho reranker và export giữ nguyên source. Chưa đủ điều kiện xác nhận full production hoặc điểm cao nhất.

## Artifact để mở

- `artifacts/retrieval/demo-queries.jsonl`: 12 query minh họa.
- `artifacts/retrieval/demo-candidates.jsonl`: tập ứng viên đầy đủ của chúng.
- `artifacts/retrieval/demo-submission.json` / `.zip`: demo20docs/40chunks, ZIP một JSON ở root; không phải bài nộp1200query.
- `artifacts/retrieval/benchmark-test20k-fixed.json`: benchmark kỹ thuật sau fix.
- `artifacts/retrieval/benchmark-test20k-fixed.samples.jsonl`: output12query đầu.
- `artifacts/retrieval/tests-final.log`: 30 tests.
- `artifacts/retrieval/recall-first-test20k-release/manifest.json`, `integrity.json`, `capacity.json`, `code-release-hashes.json`: identity/resource/runtime/capacity evidence.
- `artifacts/retrieval/test20k-whitelist-difference.json`: 1.320 IDs ngoài asked snapshot.
