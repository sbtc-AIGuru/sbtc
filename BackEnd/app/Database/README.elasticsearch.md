# BM25 đa ngôn ngữ với Elasticsearch

## Dữ liệu đã khảo sát

File nguồn: `datav3/ViBioMIR_chunks_with_recovery.jsonl` (khoảng 5,5 GiB).
Các bản ghi mẫu có `doc_id` dạng số, `chunk_id` dạng chuỗi,
`content`, `token_count`, `content_origin`, `language`.
Nhãn thực tế là `language: "vi" | "en" | "zh"`; script thêm metadata `lang`
cho Elasticsearch, giữ các trường nguồn trong `_source`, và đổi ID sang chuỗi keyword.
Các metadata khác không được lập chỉ mục (`dynamic: false`).

Theo báo cáo có sẵn `Scripts/LanguageLabeling/output/ViBioMIR_chunk_languages.summary.json`,
corpus có 4.936.835 chunks: VI 3.811.358, EN 540.913, ZH 584.564.
Đây là số liệu của báo cáo nguồn, không phải một lượt kiểm đếm mới.

Đã tìm thấy phồn thể ở dòng 855.092, `doc_id=1006706`,
`chunk_id=1006706:673e397d0d72:cc522ed7b5e6:00000`, chứa `報告`, `醫生`.
Ngoài ra có nhiễu nhãn: dòng 138.775 chứa bài tiếng Việt và mang nhãn `vi`,
nhưng một mẫu `vi` trước đó vẫn là tiếng Anh; một mẫu `zh` chủ yếu là tiếng Việt
có chèn `花鈿`. Script dùng nhãn nguồn, không tự phát hiện hay sửa nhãn.

## Chọn analyzer và phiên bản

Project đã khai báo `elasticsearch>=9.5.1`; `.venv` hiện có client 9.5.1.
Chưa thấy cấu hình server Elasticsearch trong project. Cấu hình Docker mới pin
server **9.5.1**, cài `analysis-smartcn` bằng plugin manager ngay trong image đó.
Script kiểm tra server thuộc nhánh 9.x, từ 9.5 trở lên; nên dùng cặp client/server
9.5.1 trong hướng dẫn này. Khi nâng server phải build lại image để plugin khớp bản.

Một index chung có ba trường được chấm điểm BM25:

| Trường | Xử lý trước Elasticsearch | Analyzer Elasticsearch |
| --- | --- | --- |
| `content_vi` | PyVi 0.1.1 tách từ ghép thành `bệnh_nhân`, v.v.; chuẩn hóa NFC | `medical_vi`: whitespace + lowercase, giữ dấu và từ phủ định |
| `content_en` | NFC | `medical_en`: standard + lowercase; không stop filter, không stemming |
| `content_zh` | NFC + OpenCC 0.1.7 `t2s` chuẩn hóa phồn thể → giản thể | `smartcn`, chuyên tách từ giản thể |

Mỗi chunk chỉ điền **một** trường theo `language`. `content` gốc được lưu nhưng
không index. Không tạo bản dịch. OpenCC chỉ đổi dạng chữ cùng ngôn ngữ,
và áp dụng giống nhau cho query/document. Bản gốc vẫn dùng để trả ngữ cảnh RAG.
BM25 giữ các từ phủ định để so khớp từ vựng; điều này không bảo đảm hiểu nghĩa phủ định.

Đã xem [plugin tiếng Việt CocCoc](https://github.com/duydo/elasticsearch-analysis-vietnamese)
và [pom.xml của plugin](https://github.com/duydo/elasticsearch-analysis-vietnamese/blob/master/pom.xml):
upstream khai báo 9.3.0 và cần thư viện native CocCoc. Không có cơ sở xác nhận
binary đó chạy với server 9.5.1. Vì vậy dùng [PyVi](https://github.com/trungtv/pyvi)
để có tách từ ghép tiếng Việt mà không ép cài plugin Java khác phiên bản.
Đây là tách từ ở Python, **không phải** tokenizer tiếng Việt native của Elasticsearch.
Client khác gọi trực tiếp `_search` cũng phải gọi `prepare_text()` cho query VI/ZH.
PyVi là mô hình tách từ tổng quát; chất lượng thuật ngữ y khoa cần đánh giá riêng.
Trong môi trường Python 3.14 hiện tại, PyVi 0.1.1 tách từ được nhưng phát
`SyntaxWarning` về escape regex và `DeprecationWarning` về `codecs.open()` từ
mã thư viện. Không sửa hoặc che các cảnh báo upstream trong code project.

[Tài liệu SmartCN chính thức](https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-smartcn)
yêu cầu plugin khớp phiên bản server, cài trên mọi node và khởi động lại các node.
[English analyzer mặc định](https://www.elastic.co/docs/reference/text-analysis/analysis-lang-analyzer#english-analyzer)
có stop/stem filters; analyzer tùy chỉnh ở đây bỏ cả hai để giữ thuật ngữ và
`no`, `not`, `nor`, `without`.

## Cài dependency và chạy thử

Chạy các lệnh từ thư mục gốc project, dùng `.venv` có sẵn:

```bash
uv pip install --python .venv/bin/python -r BackEnd/app/Database/requirements-elasticsearch.txt
docker compose -f BackEnd/app/Database/compose.elasticsearch.yml up -d --build
```

Docker này dành cho phát triển local, chỉ mở `127.0.0.1:9200`, security tắt,
heap 1 GiB và volume lưu dữ liệu. Server triển khai thật cần TLS và xác thực.
Không dùng lệnh xóa volume khi còn dữ liệu cần giữ.

| Biến môi trường | Mặc định / ý nghĩa |
| --- | --- |
| `ELASTICSEARCH_URL` | `http://127.0.0.1:9200` |
| `ELASTICSEARCH_INDEX` | `vibiomir_bm25` |
| `ELASTICSEARCH_BATCH_SIZE` | `1000` |
| `ELASTICSEARCH_WORKERS` | `1`; tăng bằng `--workers 8` để tiền xử lý song song trên Python 3.14+ |
| `ELASTICSEARCH_API_KEY` | Tùy chọn; ưu tiên hơn basic auth |
| `ELASTICSEARCH_USERNAME`, `ELASTICSEARCH_PASSWORD` | Basic auth khi không dùng API key |
| `ELASTICSEARCH_CA_CERTS` | Đường dẫn CA cho HTTPS; xác minh TLS vẫn bật |
| `ELASTICSEARCH_TIMEOUT` | `60` giây |

Xuất các biến từ môi trường chạy; script không tự đọc file `.env`.
Không đưa giá trị bí mật vào code, lịch sử shell hay output chia sẻ.

Sau khi server sẵn sàng, kiểm tra analyzer và một mẫu nhỏ:

```bash
.venv/bin/python -B BackEnd/app/Database/elastic_search.py --index vibiomir_sample create-index
.venv/bin/python -B BackEnd/app/Database/elastic_search.py --index vibiomir_sample analyze
.venv/bin/python -B BackEnd/app/Database/elastic_search.py --index vibiomir_sample index --limit 30
.venv/bin/python -B BackEnd/app/Database/elastic_search.py --index vibiomir_sample search 'prolactin' --lang en --top-k 5
```

Các dòng đầu của corpus là tiếng Anh, nên `--limit 30` chưa thử được cả ba ngôn ngữ.
Test tích hợp dưới đây dùng bốn chunks VI/EN/ZH (cả giản thể lẫn phồn thể),
gọi `_analyze`, index hai lần, kiểm tra số lượng không tăng và search từng ngôn ngữ:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_elastic_search.py
ELASTICSEARCH_TEST_URL=http://127.0.0.1:9200 \
  .venv/bin/python -B -m pytest -s -q -p no:cacheprovider \
  tests/test_elastic_search.py::test_live_analyzers_indexing_retrieval_and_rerun
```

Chỉ đặt `ELASTICSEARCH_TEST_URL` tới cluster dành cho thử nghiệm.
Test tạo index riêng `vibiomir-test-<uuid>`, để lại bốn documents cho kiểm tra,
không xóa index. Tài khoản cần quyền tạo index, ghi, đọc mapping, analyze, refresh,
count và search. `analyze` in tokens thật của server, kiểm tra từ ghép VI,
và xác nhận từ phủ định/thuật ngữ EN còn nguyên; không giả lập kết quả analyzer.

Mặc định lệnh `index` chỉ nạp tối đa 1.000 bản ghi. Khi chủ động muốn nạp toàn bộ:

```bash
.venv/bin/python -B BackEnd/app/Database/elastic_search.py index --all --batch-size 1000
```

Để tăng tốc tách từ khi nạp corpus trên Python 3.14+, dùng thêm `--workers 8`.
Các worker chỉ tiền xử lý text; tiến trình chính vẫn đọc JSONL và gửi
`streaming_bulk` batch 1.000. Hàng đợi giới hạn `2 × workers` nhóm, mỗi nhóm
32 records, giữ thứ tự và ID như bản một worker. Không nạp toàn bộ corpus vào RAM.
Mặc định vẫn một worker; cân nhắc RAM cho mỗi bản mô hình PyVi khi tăng số worker.

Đã so sánh trên 4.000 chunks VI thực tế: 1 worker 755,1 docs/s, 4 workers
1.451,5 docs/s, 8 workers 2.624,3 docs/s; hash toàn bộ action giống nhau.
Đây là benchmark tiền xử lý mẫu, không phải tốc độ cam kết cho toàn corpus.
Sau thay đổi, 12 tests đã pass, gồm tiền xử lý song song và indexing/retrieval
thật. Lượt nạp toàn corpus được người dùng yêu cầu sau bàn giao đã được khởi
động bằng systemd unit `sbtc-elasticsearch-import-20261025.service` với 8 workers.
Log nằm ở `artifacts/elasticsearch-import-20261025/import.log`; kết quả kiểm tra
sau khi hoàn tất được ghi vào `result.json` cùng thư mục.

Không chạy lệnh cuối trong lần bàn giao này. Chạy lại ghi đè cùng `_id`, không tạo
bản sao. Index đã có chỉ được kiểm tra, không xóa/tạo lại hay tự sửa mapping.
Nếu mapping/pipeline khác, chọn tên index mới và chủ động quyết định việc chuyển dữ liệu.

## Đọc code theo luồng

| Hàm | Vai trò |
| --- | --- |
| `connect_elasticsearch()` | Đọc biến môi trường, kết nối, kiểm tra version server |
| `index_definition()` | Trả settings/mapping của một index dùng BM25 |
| `create_index()` | Tạo khi chưa có, kiểm tra mapping khi đã có |
| `prepare_text()` | Chuẩn hóa/tách từ nhất quán cho document và query |
| `read_jsonl()` | Generator đọc từng dòng; dừng tại `limit`; báo vị trí bản ghi lỗi |
| `iter_actions()` | Sinh action, ánh xạ `language` → `lang` và trường text; SHA-256 của cặp ID làm `_id` |
| `bulk_index()` | Dùng `streaming_bulk`, batch mặc định 1.000, giới hạn request 16 MiB, trả `(success, failed)` |
| `search_bm25()` | Nhận `query`, `lang`, `top_k`, dùng match và lọc `lang`, trả hits gồm score và nội dung gốc |
| `check_analyzers()` | Tiền xử lý ví dụ y khoa rồi gọi `_analyze` trên ba trường |
| `main()` | CLI cho tạo index, kiểm tra analyzer, import có giới hạn và search |

`bulk_index()` retry tối đa ba lần cho 429/502/503/504, backoff từ 2 tới tối đa
30 giây. Bộ đếm dựa trên kết quả cuối sau retry, không đếm lại các lần thử.
Lỗi document không tạm thời được đếm và hiển thị tối đa năm `_id`/status/type;
không in toàn bộ nội dung. CLI trả exit code 1 nếu có documents thất bại.
Lỗi đọc JSONL hoặc lỗi kết nối hết retry dừng lượt chạy; documents đã thành công
vẫn còn trong index. Có thể sửa lỗi rồi chạy lại nhờ `_id` cố định.
Tiến độ gồm thành công, thất bại và tốc độ thành công trung bình; CLI refresh
một lần sau import để thử retrieval ngay.

Ví dụ gọi từ Python với kết nối được tái sử dụng:

```python
from BackEnd.app.Database.elastic_search import connect_elasticsearch, search_bm25

with connect_elasticsearch() as client:
    hits = search_bm25("suy thận", "vi", top_k=5, client=client)
```

## Kết quả kiểm tra lúc bàn giao

Ngày 25/10/2026, sau khi người dùng phê duyệt cài dependency/chạy Docker ngoài
sandbox, đã cài PyVi/OpenCC vào `.venv` có sẵn và build/start image ở trên.
Đã xác nhận server **9.5.1**, plugin **analysis-smartcn 9.5.1** và chạy toàn bộ
file test với `ELASTICSEARCH_TEST_URL`: **11 passed**, không skip.
Có 14 cảnh báo upstream PyVi trên Python 3.14 như đã ghi ở phần analyzer.

Test cô lập dùng helper `streaming_bulk` thật với phản hồi bulk giả lập để xác
nhận chia batch, retry 429, đếm lỗi 400, ID ổn định, giữ nội dung và không sửa
index đã có. Test tích hợp trên server thật index bốn chunks ở ba ngôn ngữ,
index lại vẫn có **4 documents**, và retrieval cả ba ngôn ngữ đều thành công.
Query ZH phồn thể tìm được cả hai bản giản thể/phồn thể đã index.

Kết quả `_analyze` thật, sau `prepare_text()`:

```json
{
  "vi": ["bệnh_nhân", "không", "bị", "suy", "thận", "và", "đái_tháo_đường", "."],
  "en": ["no", "diabetes", "not", "hepatitis", "nor", "cancer", "without", "insulin", "deficiency"],
  "zh": ["患者", "没有", "糖尿病", "医生", "建议", "检查", "肾", "功能"]
}
```

Đã kiểm tra generator trên ba bản ghi đầu của corpus và tiền xử lý bốn mẫu thực
tế VI/EN/giản thể/phồn thể lấy từ corpus; bốn documents trong test tích hợp là
các câu mẫu ngắn trong test. Đã kiểm tra CLI `--help`, từ chối `--limit 0` và
`--all --limit`, `docker compose config --quiet`, `git diff --check`.
Không chạy toàn bộ test suite vì phạm vi thay đổi chỉ là luồng Elasticsearch;
chưa nạp corpus hay đánh giá chất lượng retrieval trên tập câu hỏi y khoa.

Trong lần bàn giao code ban đầu, container đã được dừng để giải phóng RAM, giữ volume
`database_elasticsearch-data` và index mẫu
`vibiomir-test-e32a9d0b2c72494986df4574db9c0324` với bốn documents.
Khởi động lại bằng lệnh `docker compose ... up -d --build` ở trên để kiểm tra tiếp.
Sau đó người dùng đã yêu cầu nạp toàn corpus: container được khởi động lại và
tác vụ systemd ở phần tăng tốc đang dùng index `vibiomir_bm25`.
