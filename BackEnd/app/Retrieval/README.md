# BM25 y khoa Việt–Anh–Trung mới

Component mới hoàn toàn, ưu tiên tập ứng viên document/chunk cho reranker. Không import BM25 archive; không dùng `for_valid` làm nguồn từ điển/tuning/evaluation. [Đặc tả](SPEC-bm25-recall-first.md), [kế hoạch](tasks/plan.md), [tiến độ](tasks/todo.md).

## Runtime và cách chạy

Module hiện nằm tại `BackEnd/app/Retrieval`. Chạy các ví dụ dưới đây từ root repository `sbtc`, dùng môi trường Python hiện có của dự án. [Ghi chú chuyển thư mục](MIGRATION.md) mô tả đường dẫn mới và các kiểm tra an toàn.

Các đường dẫn corpus, query và artifact trong config vẫn được tính từ thư mục chạy lệnh (cwd), như trước. Nếu dữ liệu nằm trong workspace cha, hãy dùng đường dẫn tuyệt đối qua CLI hoặc chạy từ workspace đó với `PYTHONPATH` trỏ tới root repository và đường dẫn Python/config tuyệt đối.

```bash
PY=.venv/bin/python
$PY -m BackEnd.app.Retrieval.cli preflight
$PY -m BackEnd.app.Retrieval.cli analyze --language vi --text 'Điều trị suy thận mạn với metformin 500 mg'
$PY -m BackEnd.app.Retrieval.cli prepare --config BackEnd/app/Retrieval/configs/test.toml
$PY -m BackEnd.app.Retrieval.cli build --config BackEnd/app/Retrieval/configs/test.toml
$PY -m BackEnd.app.Retrieval.cli index --config BackEnd/app/Retrieval/configs/rolling-test.toml
$PY -m BackEnd.app.Retrieval.cli search --config BackEnd/app/Retrieval/configs/test.toml \
  --queries newcorpus/query.parquet --output artifacts/retrieval/candidates-new.jsonl
```

Config `test.toml` dùng bulk builder làm đối chứng; `rolling-test.toml` trỏ tới snapshot no-folded rolling test20k đã `READY` tại `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/`. Run này chỉ bao phủ test20k, không phải full corpus. Báo cáo A/C và giới hạn relevance nằm trong [REPORT-no-folded-rolling-test20k-20261015.md](REPORT-no-folded-rolling-test20k-20261015.md). Rolling dùng writer tăng dần, một batch staging tối đa 300 MB; payload từng batch đã được dọn sau commit. Run đang dở chỉ resume cùng fingerprint và build policy. Đổi analyzer/lexicon/input phải chọn run-dir mới; không dùng lại run-dir có fingerprint cũ. Scope là bản dẫn xuất ID/URL của snapshot test20k; raw `data_final/test_20k.jsonl` không còn tại vị trí cũ. Input là `data_final/chunks_format_v3_r3_reserve_test20k`.

Yêu cầu đường sparse: Python tương thích với `requirements-lock.txt`, full JDK 21 có `jdk.incubator.vector`, `JAVA_HOME` hợp lệ. Lock phản ánh Linux/Python 3.12 của máy đã kiểm thử trước đây; `.venv` hiện tại dùng Python 3.14 và chưa có đủ dependencies BM25. Khi được yêu cầu cài dependencies, dùng môi trường dự án và lock tại `BackEnd/app/Retrieval/requirements-lock.txt`; không chạy resolver full Pyserini vốn kéo neural stack. JDK được phát hiện tự động trong `BackEnd/app/Retrieval/.runtime/jdk/` nếu shell chưa đặt JAVA_HOME. Model translation không thuộc lock sparse.

## Thiết kế tìm kiếm

| Thành phần | Trách nhiệm |
|---|---|
| MedicalAnalyzer | VI Underthesea, ZH Jieba/OpenCC, EN Krovetz; compound/broad/exact/anchors (profile `medical-no-folded-v1`) |
| Lexicon | Aho-Corasick có boundary, concept namespace/provenance và aliases ba ngôn ngữ |
| CorpusPreparer | Whitelist ID/URL, union overlap, bulk stage JSONL, metadata transaction và resume |
| RollingIndexer | Cursor theo record/view, một stage batch có hard cap, commit receipts sáu partition, resume/cleanup theo ownership |
| LuceneBackend | Sáu index, pretokenized whitespace; OR TermQuery, field boosts, immutable BM25 params |
| QueryProjector | Original VI, multilingual aliases/anchors, exact literals, optional translation cache |
| CandidateEngine | Search độc lập document/chunk, RRF có channel evidence, document union best chunk |
| TextStore | SQLite pointer/hash, lấy nguyên văn source child cho reranker/export |
| export_submission | JSON/ZIP BTC, đủ expected query IDs, budget riêng, source identity/text/order |

Không so raw BM25 giữa languages, không ép toàn bộ candidate qua ngưỡng 0.3, không xóa từ chỉ intent/phủ định. Mặc định lấy 300 documents/1000 chunks **mỗi language/channel**, fused tối đa 1000/3000. Các số này là cấu hình khởi đầu, chưa tối ưu trên nhãn độc lập. k1=0.8,b=0.4; có thể ablation bằng CLI `--k1 1.2 --b 0.75`, không rebuild. RRF không phải xác suất relevance.

BM25 field chính giữ TF. Các field cứu Recall giữ alternatives duy nhất mỗi record, có length norms riêng; không giả lập synonym graph. Query tối đa 128 clauses mỗi channel, chia budget theo fields và có warning khi vượt. Chuỗi query không đưa qua QueryParser nên dấu `+`, `:` và mã y khoa không thành cú pháp truy vấn.

## Hợp đồng với reranker

```python
from pathlib import Path
from BackEnd.app.Retrieval.store import TextStore

with TextStore(Path('artifacts/retrieval/recall-first-test20k-release/metadata.sqlite')) as store:
    # candidates là danh sách chunks của một query trong candidate JSONL.
    texts = store.get_many(c['chunk_id'] for c in candidates)
    # texts[id] -> {doc_id: str, chunk_order: int, chunk_text: source verbatim}
```

Reranker đọc `query`, evidence, metadata và source text; trả thứ hạng mới giữ nguyên IDs. Candidate file mặc định không lặp lại toàn bộ chunk_text, giúp batch hàng nghìn query giữ RAM/output hợp lý. Engine streaming theo query; six indexes mở một lần/job. PyJNIus shared-method receiver được khóa trong một process để giữ đúng partition; `threads` không làm các Java search calls chạy song song. Mở rộng song song thực cần process/JVM workers và RAM budget riêng. SQLite/raw line cache có budget; không load cả corpus vào RAM.

## Dịch query đầy đủ

Thiếu translation cache thì chỉ có lexical aliases/anchors/literals cho EN/ZH và warning; từ điển starter **12 concepts**, chưa đủ coverage corpus. Xem [resource contracts](resources/README.md). Cache phải có exact source query/hash, revision model cố định, license, số params, ngày phát hành và open-weight declaration.

Optional `translate` dùng local HuggingFace NLLB assets qua AutoModelForSeq2SeqLM, checksum mọi file, không trust_remote_code/network. Dịch VI → EN/ZH theo batch và ghi cache atomically. Chưa provision/test inference model thật trong task này. Cần môi trường translation riêng có Torch/Transformers/SentencePiece; chưa có version lock cho đường optional này.

```bash
$PY -m BackEnd.app.Retrieval.cli translate --model-manifest /path/to/verified-model.json \
  --queries newcorpus/query.parquet --output artifacts/retrieval/query-translations.jsonl --batch-size 8
$PY -m BackEnd.app.Retrieval.cli search --config BackEnd/app/Retrieval/configs/test.toml \
  --cache artifacts/retrieval/query-translations.jsonl --queries newcorpus/query.parquet \
  --output artifacts/retrieval/candidates-with-translation.jsonl
```

NLLB là lựa chọn nghiên cứu, chưa chứng minh chất lượng thuật ngữ y khoa; model card nêu CC-BY-NC và giới hạn domain/input. Không coi output dịch là chunk nguồn. [Model card](https://huggingface.co/facebook/nllb-200-distilled-600M), [HF API](https://huggingface.co/docs/transformers/model_doc/nllb).

## Export và đo lường

```bash
$PY -m BackEnd.app.Retrieval.cli export --config BackEnd/app/Retrieval/configs/test.toml \
  --queries newcorpus/query.parquet --candidates artifacts/retrieval/candidates-new.jsonl \
  --output artifacts/retrieval/submission.json --zip artifacts/retrieval/submission.zip \
  --docs 20 --chunks 40
$PY -m unittest discover -s BackEnd/app/Retrieval/tests -v
$PY -m BackEnd.app.Retrieval.tests.analyze_fixture --json-report artifacts/retrieval/analyzer-testset-20261015/report.json
$PY -m BackEnd.app.Retrieval.tests.analyze_fixture --strict
$PY -m BackEnd.app.Retrieval.cli capacity --config BackEnd/app/Retrieval/configs/test.toml \
  --expected-documents 1220598 --expected-chunks 4342218
```

`tests/fixtures/medical_analyzer_cases.jsonl` là bộ regression tổng hợp, cân bằng 30 ca mỗi ngôn ngữ. Runner chạy ở cả index/query mode và báo riêng theo ngôn ngữ, risk group, kiểu đầu vào và contract/challenge. Chế độ mặc định là chẩn đoán: mismatch được in ra đầy đủ nhưng không đổi exit code. Dùng `--strict` để làm gate cho contract cases; các challenge cases luôn được báo nhưng không tính là đạt. Bộ này kiểm tra analyzer, không phải benchmark relevance/F2 trên corpus.

Export cần query set chính xác; với bài nộp phải đủ 1200 IDs. Top20/40 chỉ minh họa export, cần selector/reranker và đánh giá độc lập trước nộp. Candidate generator rộng không đảm bảo F2 cuối.

`evaluation.evaluate(predictions, references)` có document P/R/F2, chunk LCS whitespace >=40%, many-to-many và macro từng query. Không tự tải qrels. Bộ test kiểm toán học bằng fixtures cơ học, không chứng minh relevance của kết quả tìm kiếm. Reference rỗng dùng zero denominators; xác minh quy ước BTC nếu gold thực có trường hợp này.

## Trước chạy full

1. Whitelist đã chốt theo phản hồi người dùng ngày 15/10/2026: `newcorpus/links_corpus_vi_en_zh.parquet`, **1.220.598 URL**, SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`. Dùng cho BM25 full và xuất bài. Đây là quyết định chọn dữ liệu của người dùng; thông tin snapshot 1.194.469 trong `asked.md` chưa được BTC xác minh lại. Giữ cả 1.320 IDs test20k ngoài snapshot cũ vì chúng thuộc whitelist đã chọn. Index test20k hiện có dùng đúng hash này, không cần rebuild vì quyết định này.
2. Mở rộng tài nguyên y khoa có nguồn/license; không nạp tài nguyên archive hoặc nhãn benchmark vào lexicon mới.
3. Provision model/cache dịch hợp lệ và kiểm tra thuật ngữ/negation/numerics; numeric guard hiện chỉ phát hiện thiếu số, không chứng minh dịch đúng.
4. `capacity` lấy stage/index/SQLite bytes thật và dự phóng có merge scratch +30%; không bảo đảm RAM hay phân bố token full giống test20k.
5. Chạy full vào thư mục mới sau các gate; đối chiếu coverage/counts, đánh giá Recall/F2 trên nhãn độc lập được phép dùng.

## Dung lượng test20k và rolling gate

Bulk test20k trước đây đo staging ~595,2 MB, sáu index ~150,7 MB, SQLite ~121,5 MB; capacity dự phóng full theo lifecycle bulk là ~81,8 GB. Rolling mới giới hạn stage tạm, nhưng chưa có số đo full-size no-folded index/SQLite/merge để thay capacity estimate. Kiểm thử rolling gồm dữ liệu tổng hợp nhỏ và smoke test bulk↔rolling trên 4 source records lấy từ test20k; **chưa chạy full 20k rolling hoặc benchmark A/B/C**, do cần kiểm tra lại disk gate trước khi ghi index lớn. Không suy ra rolling đã đủ chỗ cho corpus full từ giới hạn stage 300 MB.

## Curation resource đa ngữ

Resource nguồn nằm ở `sbtc/Resources/`; không nạp nguyên trạng vào analyzer. Converter đã tạo snapshot dẫn xuất tại `resources/curated/20261015/`, có line references, lý do phân loại, mapping concept ID, trạng thái ICD/QID, provenance/license và SHA-256 trong manifest. Xem [đặc tả](SPEC-resource-curation.md) và [report](resources/curated/20261015/REPORT.md).

`lexical_candidate` và `concept_candidate` vẫn chưa được xác nhận ngữ nghĩa; output này không tự động đổi cấu hình BM25 hoặc index. Chạy lại nên ghi sang thư mục phiên bản mới vì converter chủ ý từ chối ghi đè artifact đã có:

```bash
$PY -m BackEnd.app.Retrieval.curate_resources \
  --output-dir BackEnd/app/Retrieval/resources/curated/20261016
```

Chỉ tích hợp sau khi xử lý provenance/license, rà các nhóm review và chạy ablation riêng trên test20k.
