# Báo cáo sửa literal y khoa và acronym giả — 2026-10-15

## Kết luận

Đã sửa trích xuất mã/liều lượng sát chữ Hán, hỗ trợ từ thuốc tiếng Anh được lexicon xác nhận khi dính chữ Hán, và bỏ `case_upper_*` khỏi các heading tiếng Anh phổ biến. Candidate cuối được dựng mới từ `test20k` và tìm kiếm đủ 1.200 query.

Các kiểm tra analyzer đạt toàn bộ 69/69 contract cases. Retrieval cho thêm một lượng candidate nhỏ, tập trung ở kênh tiếng Trung, nhưng rà tay cho thấy exact matching bằng một literal ngắn như `CT` hoặc `500mg` có thể đẩy tài liệu chỉ trùng từ khóa lên cao. Không có qrels độc lập nên **không thể kết luận Precision, Recall hoặc F2 tăng**. Kết quả phù hợp để chuyển candidate rộng sang reranker và cần đánh giá relevance sau khi có bộ nhãn độc lập.

## Thay đổi

- Thay ranh giới `\b` bằng boundary Unicode nhận biết chữ Latin/số/Hán cho dose và symbol. Giữ nguyên số thập phân như `5.17mmol/L`, không sinh `17mmol/l`; nhận diện `J18.9`, `500mg`, `IL-6`, `SpO2`, `10μg/kg` khi dính chữ Hán.
- Giải mã entity HTML và NFKC trước khi đọc literal; ánh xạ `μg`/`µg` thành `mcg`, không đổi giá trị số hay đơn vị.
- Cho phép liều bắt đầu sau dấu phẩy phân cách danh sách, đồng thời chặn trường hợp bắt đầu giữa phần thập phân.
- Khi văn bản tiếng Trung có từ Latin sát chữ Hán, chỉ thêm từ đó vào exact và anchor nếu lexicon tiếng Anh nhận diện được. Ví dụ `糖尿病患者服用metformin` tạo exact `metformin` và anchor hiện có `local:diabetes`, `local:metformin`; từ không có trong lexicon không được promotion.
- Không tạo case marker cho `ABSTRACT`, `BACKGROUND`, `METHODS`, `RESULTS`, `SETTING`, `OUTCOME`, `CASE` và các heading trong danh sách ở `analyzers.py`. Các từ này vẫn có thể được xử lý như lexical text; không sinh concept anchor.
- Giữ acronym y khoa hiện có như `ALL`, `MI`, `CAP`, `COPD`. Việc khớp literal acronym không tự tạo concept anchor.

## Kiểm tra

### Analyzer và unit tests

- `python -m unittest discover -s sbtc/Scripts/Retrieval/tests -v`: **40 tests passed**.
- `python -m sbtc.Scripts.Retrieval.tests.analyze_fixture --strict`: **69/69 contract cases đạt** trên cả index/query mode.
- Fixture có 1 mismatch trong 21 challenge cases: `en-07`, câu `Stroke.It can follow atrial fibrillation.` không tách `Stroke.It` như kỳ vọng. Đây là challenge cũ về dấu câu, không phải contract của thay đổi hiện tại; không được tính là pass hay che giấu.
- Regression riêng kiểm tra literal sát Han, full-width, decimal, dose sau dấu phân cách, heading và từ tiếng Anh không có trong lexicon.

### Snapshot và điều kiện so sánh

| Yếu tố | Baseline | Candidate cuối |
|---|---|---|
| Input | `data_final/chunks_format_v3_r3_reserve_test20k/` | Giống baseline |
| Scope SHA-256 | `77305fe3531180b24b4d50db3633a3a3626c84d268b0d6a4e43eb05b596ca550` | Giống baseline |
| Corpus SHA-256 | `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7` | Giống baseline |
| Query | `newcorpus/query.parquet`, 1.200 queries | Giống baseline |
| Query SHA-256 | `ce13508b893bbd6b9169679d540630bc37eb5950cad08b4d5e0e5d7063670c08` | Giống baseline |

| Index partition | Documents |
|---|---:|
| Documents VI / EN / ZH | 10.689 / 4.520 / 4.770 |
| Chunks VI / EN / ZH | 34.377 / 6.385 / 22.179 |
| Tổng | 19.898 documents / 62.941 chunks |

Hai run dùng cùng 20 shard nguồn, scope, corpus, 92-concept lexicon và cấu hình `k1=0.8`, `b=0.4`, budget 300 docs/1.000 chunks mỗi ngôn ngữ, cap 1.000 docs/3.000 chunks. Candidate cuối có fingerprint analyzer mới; không dùng index stale.

### Kết quả candidate generation

| Chỉ số trên 1.200 query | Baseline | Candidate cuối | Thay đổi |
|---|---:|---:|---:|
| Query không có document / chunk | 0 / 0 | 0 / 0 | Không đổi |
| Tổng documents candidates | 1.170.665 | 1.170.804 | +139 |
| Tổng chunk candidates | 1.987.777 | 1.991.094 | +3.317 |
| Median documents/query | 1.000 | 1.000 | Không đổi |
| Median chunks/query | 1.551 | 1.553 | +2 |
| Query chạm cap documents | 896 | 897 | +1 |
| Query chạm cap chunks | 49 | 49 | Không đổi |
| Top-20 doc overlap trung bình | — | 97,70% với baseline | — |
| Top-20 chunk overlap trung bình | — | 97,32% với baseline | — |
| Query có candidate set thay đổi | — | 191/1.200 (15,9%) | — |
| Search time cộng dồn | 179,69 s | 186,29 s | +3,7% |
| p50 / p95 latency mỗi query | 127,8 / 284,5 ms | 132,8 / 289,0 ms | +5,0 / +4,5 ms |

Candidate mới thêm 2.049 document-query pairs và bỏ 1.910; thêm 3.632 chunk-query pairs và bỏ 315. Các số này đo thay đổi tập ứng viên, **không phải** số tài liệu/đoạn liên quan đúng.

| Evidence theo ngôn ngữ | Baseline documents / chunks | Candidate documents / chunks | Chênh lệch |
|---|---:|---:|---:|
| VI | 584.087 / 1.912.678 | 584.648 / 1.913.416 | +561 / +738 |
| EN | 21.436 / 34.683 | 21.466 / 34.740 | +30 / +57 |
| ZH | 12.956 / 40.416 | 14.081 / 42.938 | +1.125 / +2.522 |

Warning không đổi: 1.200/1.200 query thiếu bản dịch câu đầy đủ EN/ZH; 319 query vượt ngân sách term. Vì vậy query xuyên ngôn ngữ hiện vẫn dựa vào aliases, anchors và literals có sẵn.

## Rà tay các kết quả đổi

Rà ba query trong `candidate-final` và hydrate chunk text từ TextStore, không dùng nhãn relevance:

- Query 77 nhắc chảy máu khi khạc và có chụp CT phổi. Candidate mới hạng 1 là bài ung thư tâm vị có nhắc CT; các kết quả tiếp theo có CT não trong nội dung về vô kinh hoặc bệnh cột sống. Literal được giữ và tìm thấy, nhưng các ví dụ đầu chưa trả đúng vấn đề chính.
- Query 681 hỏi việc cho con bú sau truyền kháng sinh, gồm liều `500mg/100ml`. Candidate mới hạng 1 là chunk hướng dẫn điều trị viêm âm đạo do nấm có `500mg`; có trùng liều nhưng ngữ cảnh không liên quan câu hỏi bú mẹ.
- Query 770 hỏi thuốc cho người tiểu đường. Candidate mới có chunk về điều trị nấm âm đạo, trong đó nhắc tiểu đường và nhiều liều thuốc. Đây là lexical overlap nhưng liên quan yếu.

Các mẫu trên xác nhận trade-off: nhận diện literal sát Han tăng khả năng lấy tài liệu chứa token bị bỏ sót trước đây; acronym/dose ngắn có IDF và exact-match mạnh nên có thể gây nhiễu xuyên ngôn ngữ. Giữ nguyên hành vi candidate rộng theo scope đã duyệt; chưa đưa kết quả này thành output nộp bài. Bước kế tiếp nên dùng reranker và relevance set độc lập để đo chất lượng thật, hoặc bổ sung kiểm soát query-side cho acronym/liều mơ hồ sau khi được duyệt.

## Artifact

- Baseline index: `artifacts/retrieval/analyzer-fix-eval-20261015/baseline/`
- Baseline search: `artifacts/retrieval/analyzer-fix-eval-20261015/baseline-candidates.jsonl`
- Candidate cuối index: `artifacts/retrieval/analyzer-fix-eval-20261015/candidate-final/`
- Candidate cuối search: `artifacts/retrieval/analyzer-fix-eval-20261015/candidate-final-candidates.jsonl`
- So sánh chi tiết: `artifacts/retrieval/analyzer-fix-eval-20261015/comparison-final.json`
- Fixture cuối: `artifacts/retrieval/analyzer-fix-eval-20261015/fixture-report-final.json`
- CLI run reports: `baseline-candidates.jsonl.report.json`, `candidate-final-candidates.jsonl.report.json`

Candidate ban đầu tại `.../candidate/` được giữ làm artifact trung gian; candidate dùng cho kết luận và bước sau là `candidate-final/` với fingerprint `37fb4eedd81f18b0d218ca66c3931820f040b095b93bb683fc651526c444dd7b`.

Không đọc `for_valid/`, không thay đổi dữ liệu chunk gốc, không chạy full corpus, không dùng qrels hoặc tuyên bố F2/Recall relevance.
