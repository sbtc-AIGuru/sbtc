# So sánh BM25 folded bulk và no-folded rolling trên test20k

Ngày: 15/10/2026. Đây là so sánh candidate-generation trên toàn bộ 1.200 query, không phải đánh giá relevance.

## Kết luận

- Bản `medical-no-folded-v1` dựng rolling đã hoàn tất `READY` trên test20k; 6 partition, số document/chunk và mapping nguồn khớp run cũ. Ba batch staging đều được commit rồi dọn; batch lớn nhất là **249.999.677 bytes**, dưới target 250.000.000 bytes.
- Search mới trả nhiều candidate hơn: **+14.354 document-query pairs (+1,23%)** và **+60.648 chunk-query pairs (+3,05%)**. Candidate set thay đổi ở cả 1.200 query; top-20 overlap trung bình còn **75,40% docs / 73,16% chunks**. Top-1 đổi ở 381 query document và 422 query chunk.
- Đây là thay đổi đáng kể đối với tập ứng viên chuyển cho reranker, nhưng không có qrels độc lập nên **không thể kết luận precision, recall, F2 hay chất lượng ngữ nghĩa tăng**. Không dùng `for_valid/`.
- A/C hiện tại gộp nhiều thay đổi: bỏ `folded`, cấp lại term budget cho `broad`, chuyển bulk sang rolling writer, và fix cách truyền từ điển literal vào Underthesea. Vì chưa dựng no-folded bulk B trên toàn 20k, số liệu không cô lập riêng tác động của `folded` hoặc rolling.

## Phạm vi và tính tương đương

| Thuộc tính | A — cũ | C — mới |
|---|---|---|
| Index | `artifacts/retrieval/analyzer-fix-eval-20261015/candidate-final/` | `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/` |
| Build | Bulk | Rolling, profile `medical-no-folded-v1`, schema v2 |
| Field `folded` trong Lucene `FieldInfos` | Có ở cả 6 partition | Không có ở cả 6 partition |
| Source chunks | 20 shard giống nhau | 20 shard giống nhau |
| Scope SHA-256 | `77305fe3531180b24b4d50db3633a3a3626c84d268b0d6a4e43eb05b596ca550` | Giống A |
| Corpus SHA-256 | `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7` | Giống A |
| Query SHA-256 | `ce13508b893bbd6b9169679d540630bc37eb5950cad08b4d5e0e5d7063670c08` | Giống A |
| Lexicon | Cùng snapshot 92 concept | Cùng snapshot 92 concept |
| BM25 / budget kết quả | `k1=0.8`, `b=0.4`, tối đa 1.000 docs / 3.000 chunks | Giống A |

Kiểm tra trực tiếp `FieldInfos` xác nhận field folded tồn tại ở mọi partition cũ và vắng ở mọi partition mới. Cả hai output có đúng 1.200 ID query và query text theo cùng thứ tự.

| Counts | A | C |
|---|---:|---:|
| Source records | 20.000 | 20.000 |
| Tài liệu `ok` | 19.898 | 19.898 |
| Chunk | 62.941 | 62.941 |
| Document views VI / EN / ZH | 10.689 / 4.520 / 4.770 | 10.689 / 4.520 / 4.770 |
| Chunk views VI / EN / ZH | 34.377 / 6.385 / 22.179 | 34.377 / 6.385 / 22.179 |

## Kết quả candidate

| Chỉ số trên 1.200 query | A — folded bulk | C — no-folded rolling | Thay đổi |
|---|---:|---:|---:|
| Document candidates tổng | 1.170.804 | 1.185.158 | +14.354 |
| Chunk candidates tổng | 1.991.094 | 2.051.742 | +60.648 |
| Docs/query p50, p95 | 1.000, 1.000 | 1.000, 1.000 | Không đổi |
| Chunks/query p50, p95 | 1.553, 2.802,5 | 1.602, 2.847,1 | +49 p50 / +44,6 p95 |
| Query chạm cap docs=1.000 | 897 | 1.032 | +135 |
| Query chạm cap chunks=3.000 | 49 | 48 | -1 |
| Query rỗng ở docs/chunks | 0 / 0 | 0 / 0 | Không đổi |
| Query có candidate set khác | — | 1.200 / 1.200 | — |
| Top-20 ID overlap trung bình — docs | — | 75,40% với A | — |
| Top-20 ID overlap trung bình — chunks | — | 73,16% với A | — |
| Top-1 đổi — docs / chunks | — | 381 / 422 | — |
| Query term-budget warning | 319 | 205 | -114 |
| Thiếu bản dịch EN/ZH cho query đầy đủ | 1.200 | 1.200 | Không đổi |

Tổng candidate pairs thêm/bớt: docs **+217.623 / -203.269**, chunks **+445.440 / -384.792**. Đây là các cặp query–ID đổi trong top kết quả, không phải số tài liệu đúng/sai. Search ghi **186,29 giây** ở A và **169,08 giây** ở C; hai lần chạy không phải benchmark latency được kiểm soát nên không dùng chênh lệch này để kết luận tăng tốc.

Query mới được phân tích: **1.200/1.200 đều có dấu tiếng Việt**; tập này không đo trực tiếp query gõ tiếng Việt không dấu. Việc bỏ `folded` làm mất đường rescue không dấu. Đồng thời, khi không còn field folded, `broad` nhận phần term budget rộng hơn; cảnh báo budget giảm từ 319 xuống 205 và kết quả VI tăng. Vì vậy candidate rộng hơn không thể được quy là hiệu quả thuần của việc bỏ folded.

## Rolling staging và dung lượng quan sát được

| Đo lường | A — bulk cũ | C — rolling mới |
|---|---:|---:|
| `prepared/` còn lại sau build | 595.548.579 bytes | Không giữ full prepared corpus |
| Peak logical staging | 595.548.579 bytes trong snapshot cũ | 249.999.677 bytes |
| Staging sau khi hoàn tất | Prepared data còn trên đĩa | 133 bytes ownership marker |
| Lucene indexes | 151.447.998 bytes | 162.963.848 bytes |
| `metadata.sqlite` | 121.479.168 bytes | 127.397.888 bytes |
| Thời gian xử lý ghi trong batch metrics | Không có số cùng cách đo | Tổng `PREPARED` 2.361,728 giây; chưa gồm thời gian commit/publish riêng |
| Peak RSS ghi trong batch metrics | — | 891.340 KiB |
| Free space nhỏ nhất trong các batch metric | — | 13.208.588.288 bytes |

Index mới lớn hơn index cũ khoảng **7,60%**, metadata lớn hơn khoảng **4,87%**. Đây là phép so A bulk với C rolling, nên không chứng minh bỏ folded làm index lớn hơn; khác biệt có thể đến từ layout segment/merge của writer và ledger rolling. Kết quả chắc chắn ở đây là rolling giữ peak staging dưới 250 MB và xóa payload từng batch sau commit. Cần run B no-folded bulk để đo riêng storage/analyzer effect.

Ba batch đã seal/commit/cleanup: 249.997.741, 249.999.677 và 66.174.095 bytes. Batch 3 có 19.609 events; sáu receipt khớp partition counts. `manifest.json` kết thúc `READY`, cursor `COMPLETE`; không thay đổi source chunks, corpus, A index hay A candidates.

## Rà tay có giới hạn

Query 190 hỏi về siêu âm và nốt tăng âm 7 mm ở hạ phân thùy V. Top chunk A là bài Vinmec tổng quan siêu âm gan; top chunk C là bài Vinmec về nốt đau ở đầu ngực, có vẻ ít liên quan hơn. Query 278 hỏi nguy cơ tái phát bệnh lậu; top 4 chunk IDs giữ nguyên giữa A và C. Hai ví dụ chỉ xác nhận có ca bị xáo thứ hạng và có ca giữ ổn định; chúng không đại diện toàn bộ 1.200 query và không thay thế nhãn relevance.

## Lỗi thực tế và xử lý

Lần dựng đầu trên source article `doc_id=243917` dừng vì một mục lexicon tiếng Việt có dấu `)` cuối (`thực vật)`) được Underthesea nội suy vào regex `fixed_words`, gây `unbalanced parenthesis`. Đã thêm `_underthesea_fixed_words()` escape mọi ký tự regex nhưng giữ khoảng trắng theo API Underthesea, kèm regression `test_vietnamese_fixed_word_with_unmatched_parenthesis_is_literal`. Retrieval suite sau sửa: **56 tests pass**. Strict analyzer fixture: **69/69 contract pass**, 0 contract mismatch; challenge `en-07 Stroke.It` còn mismatch chẩn đoán cũ và không tính là pass.

Một lần khởi động phụ trong lúc writer còn giữ lock bị từ chối `Another writer owns this snapshot`; không tạo writer song song. Writer sở hữu run tiếp tục commit batch 3 và hoàn tất READY. Lần thử đầu và lần chạy lại dùng run-dir riêng; không xóa artifact nào.

## Artifact và hashes

- Candidate A: `artifacts/retrieval/analyzer-fix-eval-20261015/candidate-final-candidates.jsonl` — SHA-256 `a8a24d77f186b771881d6cec66a7aa12c1670c2890c1d188d97c5ee61a97ad52`.
- Candidate C: `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/candidates.jsonl` — SHA-256 `e678bcc9870fa8ead05e550c42f8497b2301959711c0f27dccc56431c45f7059`.
- Metric chi tiết từng query/top-10 cho 20 query có churn lớn: [`comparison.json`](../../../artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/comparison.json).
- Snapshot manifest và receipts: `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/manifest.json`, `rolling_metrics.jsonl`.

## Quyết định đề xuất

Có thể dùng C làm nguồn candidate cho bước reranking thử nghiệm trên test20k vì build, mapping và hydration đã đạt kiểm tra kỹ thuật, đồng thời candidate set rộng hơn. Chưa nên gọi C là tốt hơn A hoặc dùng số liệu này để chọn cấu hình nộp cuối. Nếu cần xác định tác động riêng, bước tiếp theo là dựng B no-folded bulk trên cùng snapshot rồi đối chiếu A↔B và B↔C; dù vậy, Recall/F2 vẫn cần nhãn độc lập được phép sử dụng.
