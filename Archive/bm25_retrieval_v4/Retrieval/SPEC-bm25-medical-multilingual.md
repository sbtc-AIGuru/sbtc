# Đặc tả BM25 truy hồi y khoa Việt–Anh–Trung

Ngày: 2026-10-14. Trạng thái: **Đề xuất để duyệt; chưa triển khai**.

## 1. Mục tiêu và phạm vi

Xây dựng một component lexical retrieval dùng Pyserini/Lucene BM25: nhận query y khoa tiếng Việt, tìm tài liệu và chunk tiếng Việt, Anh, Trung; xuất kết quả đúng định dạng BTC. Component phải sử dụng được trên corpus triệu tài liệu, nhiều triệu chunk, JSONL đầu vào khoảng 20–25 GB và batch hàng nghìn query mà không nạp toàn bộ corpus vào RAM.

Mục tiêu chất lượng là cải thiện **F2 macro ở cả document và chunk**, đồng thời công bố Precision/Recall riêng để thấy đánh đổi. Không có lời hứa đạt điểm tối đa: tokenizer, BM25 và mở rộng query không bảo đảm hiểu đúng mọi quan hệ y khoa; điểm thực tế cần nhãn độc lập để đo.

Yêu cầu mới của người dùng là cơ sở thiết kế: **không phân tích hoặc dùng `for_valid/` để thiết kế, tạo dictionary, chọn model, chọn tham số, đặt ngưỡng hay đánh giá phương án trong task này**. Những khảo sát benchmark ở lượt trước không được dùng làm căn cứ cho đặc tả này. Retriever không có dependency tới ground truth; evaluator là công cụ tách biệt, chỉ chạy khi có bộ nhãn độc lập được phép sử dụng.

Đặc tả này bao phủ một component retrieval với các lớp bên trong: input/identity → tokenization/index → query bridge → search/fusion → selection/export. Không thay chunker, crawler, nội dung crawl, các file chunk đã có hoặc luật `AGENTS.md`.

## 2. Bằng chứng hiện có và điều chưa xác minh

### 2.1. Repo và corpus

- Nguồn yêu cầu: công thức BTC người dùng cung cấp trong phiên hiện tại và `sbtc/asked.md`.
- Chưa có module BM25 trong `sbtc/Scripts/`; module mới đặt tại `sbtc/Scripts/Retrieval/`.
- `sbtc/pyproject.toml` hiện chỉ khai báo `crawl4ai`, `pyarrow`, và cấu hình package finder cho `BackEnd*`. Dependency retrieval được quản lý trong môi trường riêng; đặc tả không sửa cấu hình package đang dùng.
- Đọc metadata Parquet tại thời điểm khảo sát: `newcorpus/links_corpus_vi_en_zh.parquet` có **1.220.598 dòng**, schema `id:int64,url:string`, min/max ID từ thống kê row group là **583/7.466.161**. Bản backup 1.194.469 dòng còn tồn tại. `newcorpus/query.parquet` có **1.200 query**, schema `id:int64,query:string`.
- Một số đoạn cũ trong `asked.md`/`AGENTS.md` còn mô tả snapshot 1.194.469 và trần ID 4.420.561. Retriever xác thực bằng **membership trong Parquet được chọn và ghi hash**, không dùng trần ID cũ hoặc `row_index`. Đặc tả không tự thay tài liệu nguồn sự thật; manifest phải làm rõ snapshot đang dùng.
- `data_final/chunks_format_v3_final/checkpoint.json`: run hoàn tất, 1.220.598 record, 1.213.716 `ok`, 4.342.218 chunk, 1.098 chunk trên 300 units, 20 trên 500 và 20 `unresolved`. Đây là số tự báo của run, không phải kết quả kiểm toán độc lập mới.
- Input thử nghiệm được phép: `data_final/test_20k.jsonl` và output dẫn xuất `data_final/chunks_format_v3_r3_reserve_test20k/`. Checkpoint output thử nghiệm ghi 20.000 record, 62.941 chunk và không có `unresolved`.
- Source JSONL có `id,url,text,success,error,row_index`. Output chunk có `doc_id,url,status,children,parents`, hash source, span theo ký tự, profile và cảnh báo. Mỗi child có `chunk_id,doc_id,chunk_order,chunk_text,parent_id,start_char,end_char,retrieval_eligible`.

### 2.2. Môi trường

Interpreter khảo sát là Python 3.14.7; chưa có Pyserini/Jieba/Underthesea trong interpreter đó. Máy có 12 logical CPU, khoảng 14,5 GiB RAM tổng, khoảng 4,5 GiB RAM available và 30,8 GiB đĩa trống tại thời điểm khảo sát. Các số available thay đổi theo tải máy.

Theo [Pyserini README](https://github.com/castorini/pyserini), hướng cài đặt hiện hành dùng Python 3.12 và Java 21. Đề xuất bắt đầu với **Pyserini 2.4.0**, dùng Anserini/JAR đi kèm, không tự trộn các phiên bản Lucene. Khóa phiên bản Jieba, Underthesea NLP và dependency sau bước compatibility; không dùng nhánh `main` làm dependency vận hành.

Trang [cuộc thi chính thức](https://leaderboard.aiguru.com.vn/competitions/15/) không truy cập được qua công cụ web trong lượt khảo sát này. Công thức và định dạng dưới đây dựa trên nội dung người dùng cung cấp và `asked.md`; không tự thêm trọng số điểm tổng giữa hai cấp đánh giá.

## 3. Bất biến dữ liệu

1. `doc_id` nội bộ là integer từ snapshot Parquet; loại `bool`, float, ID tự sinh từ vị trí dòng. Lucene dùng `str(doc_id)` hoặc `chunk_id` làm external ID; số nội bộ Lucene không được dùng làm ID nộp.
2. Bảo toàn `(doc_id,url)` với snapshot được chọn. ID thiếu trong snapshot, URL không khớp, trùng ID có payload khác nhau là lỗi build; không tự sửa mapping.
3. `chunk_text` nộp lấy nguyên chuỗi đã lưu trong child của output chunk, với `doc_id` và `chunk_order` tương ứng. Tokenization, stemming, lowercase, synonym, dịch query và text dùng để index không được ghi đè chuỗi này.
4. Mỗi index snapshot gắn với hash corpus whitelist, hash input shards, cleaner/chunker version, analyzer, lexicon và code retrieval. Không trộn chunk ID/offset giữa hai snapshot.
5. `uncertain_format` không đủ để loại dữ liệu: nó là cảnh báo của router. Không hard filter theo confidence, domain, profile, ICD hoặc ngôn ngữ suy đoán mặc định.
6. Status lỗi, `retrieval_eligible=false`, chuỗi rỗng hoặc không có lexical token được ghi audit và không tạo posting; registry vẫn giữ danh tính/reason. Một tài liệu ngắn có nội dung thật vẫn được index.
7. Mọi kết quả build/prepare/log/index nằm trong thư mục dẫn xuất mới `artifacts/retrieval/<run_id>/`. Không viết vào source JSONL, Parquet, thư mục chunk hiện tại hoặc `for_valid/`.

## 4. Chấm điểm BTC và hệ quả đối với retrieval

### 4.1. Document

Với từng query, `D` và `G` là tập ID:

`P_doc = |D ∩ G| / |D|`; `R_doc = |D ∩ G| / |G|`.

Loại ID trùng trong output trước khi chấm. Không gộp tài liệu có cùng URL/nội dung nhưng khác ID nguồn, vì nhãn BTC đối sánh theo ID.

Khi prediction rỗng và ground truth không rỗng, evaluator đặt Precision/Recall/F2 bằng 0; tương tự ở cấp chunk. Reference chunk có chuỗi rỗng hoặc normalization không còn token là nhãn không hợp lệ cần báo lỗi, không chia cho 0 hoặc coi mọi prediction khớp.

### 4.2. Chunk

Chuẩn hóa **chỉ cho evaluator** theo đúng thứ tự:

```python
def btc_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text.split()
```

`match(c,g)` chỉ xét khi cùng query và cùng `doc_id`, và đúng khi `5 * LCS_tokens(c,g) >= 2 * len(tokens(g))`. Dùng bất đẳng thức integer để kiểm tra đúng ngưỡng 40%.

- Precision chunk: số predicted chunk khớp ít nhất một reference / số predicted chunk.
- Recall chunk: số reference chunk được ít nhất một prediction khớp / số reference chunk.
- Đây là matching **nhiều–nhiều**, không ép ghép 1–1. Một prediction có thể phủ nhiều reference; nhiều prediction cùng phủ một reference không làm reference đó được đếm thêm.
- Khi một prediction đã khớp reference đầu tiên, evaluator vẫn phải xét các reference còn lại để tính đủ Recall.

### 4.3. F2 và macro

Từng query, từng cấp: `F2 = 5PR / (4P + R)`; nếu `P=R=0`, F2 bằng 0. Macro P, macro R, macro F2 là ba trung bình riêng trên cùng danh sách query; **không lấy F2 của macro P và macro R** làm macro F2.

Đối với document và nhãn không rỗng, có thể viết `F2_doc = 5TP / (4|G| + |D|)`. Không dùng dạng rút gọn này cho chunk: tử số Precision và Recall của chunk có thể đếm các đối tượng khác nhau.

F2 ưu tiên Recall hơn Precision, nhưng thêm tài liệu/chunk không liên quan vẫn giảm điểm. Ngân sách tìm ứng viên phải rộng hơn ngân sách nộp; không nộp toàn bộ top-1000 hoặc tất cả chunk của các document tìm được. Cũng không hard filter khiến mất nhãn dương trước khi ranking.

Nội dung đã cung cấp chưa quy định cách chấm query có ground truth rỗng hoặc trọng số gộp document/chunk thành điểm tổng. Evaluator mặc định báo lỗi nhãn rỗng chưa định nghĩa, thay vì tự suy diễn; report luôn xuất hai bộ P/R/F2. Chỉ bật convention/điểm tổng khi có quy định BTC được xác minh.

### 4.4. Rủi ro đặc biệt của tiếng Trung

Tokenizer cho retrieval và tokenizer BTC là hai hệ khác nhau. Ví dụ: reference `甲乙丙丁` là một whitespace token; prediction `甲乙` cũng là một token nhưng LCS bằng 0. Bao phủ substring hoặc ngữ nghĩa không bảo đảm khớp token.

Jieba phục vụ tìm kiếm, **không được chèn khoảng trắng vào `chunk_text` nộp**. Benchmark kỹ thuật cần có các ca CJK này. Nếu source chunker đã cắt giữa một whitespace token dài, BM25 không tự sửa được phần mất khả năng đối sánh đó. Parent có thể giúp ranking nhưng không tự động được đưa ra thay child. Việc đổi đơn vị chunk nộp hoặc mở rộng span vượt cấu hình chunking cần đặc tả riêng được duyệt; không dùng toàn tài liệu làm chunk để lợi dụng ngưỡng 40%.

## 5. Kiến trúc đề xuất

```text
Chunk shards + corpus Parquet
  → CorpusReader + IdentityRegistry + QualityPolicy
  → LanguageRouter + TokenPipelineRegistry
  → Prepared JSONL + source-pointer metadata store
  → Lucene document indexes: vi / en / zh
  → Lucene chunk indexes: vi / en / zh

Query tiếng Việt
  → QueryBridge: original + medical aliases + optional local translation
  → TokenPipelineRegistry + explicit Lucene QueryBuilder
  → document search + chunk search trên các ngôn ngữ
  → canonical-ID dedup + rank fusion
  → document/chunk selectors
  → lấy nguyên văn từ OriginalTextStore
  → JSON BTC + diagnostics
```

Chọn **sáu index** theo `(granularity, language)` để thống kê chiều dài/IDF của document và chunk không bị trộn, và analyzer từng ngôn ngữ có hợp đồng rõ. Một document/chunk đa ngôn ngữ có thể xuất hiện ở nhiều index nhưng vẫn giữ một canonical ID.

Đây là lựa chọn thiết kế, không phải quy định BTC. Đổi sang một index nhiều field ngôn ngữ cũng khả thi, nhưng tăng độ phức tạp của routing, field thống kê và custom generator. Với repo hiện tại, sáu index dễ kiểm tra và vận hành hơn. Khi hợp nhất ranking giữa index, không so raw BM25 score như thể chúng cùng thang đo.

## 6. Tokenization y khoa và chống tokenize hai lần

### 6.1. Hợp đồng chung

`TokenPipeline.analyze(text)` trả các token/field **dẫn xuất cho index**, không sửa input. Cùng pipeline, normalizer, tài nguyên và fingerprint được sử dụng cho document/chunk/query của ngôn ngữ tương ứng.

Index normalization: NFKC, giải mã entity, lowercase, whitespace chuẩn hóa trên bản sao. Giữ dấu tiếng Việt, số thập phân, phủ định, liều lượng, tên hoạt chất, biomarker, chữ viết tắt và ký hiệu có ý nghĩa. Không dùng stoplist phổ thông làm mất `không/chưa`, `no/not/without`, `不/无`. Không bỏ số hoặc dấu cộng/trừ trong field bảo vệ thuật ngữ.

**Lựa chọn thống nhất:** chạy analyzer/tokenizer trước, lưu token cách nhau bởi một dấu cách; cả sáu Lucene index dùng WhitespaceAnalyzer. Vì vậy, ngay cả EN cũng không bị stemming lần thứ hai.

### 6.2. English

- Pipeline chính dùng lớp Lucene **`org.apache.lucene.analysis.en.EnglishAnalyzer`** với stopword set rỗng ban đầu. Đây là cấu hình bảo toàn phủ định; có thể thử medical stoplist được version hóa trên dev độc lập về sau.
- Không đồng nhất `get_lucene_analyzer('en')` của Pyserini với lớp trên: source Pyserini dùng Anserini `DefaultEnglishAnalyzer` cho helper này. Adapter phải kiểm tra actual Java class và hash cấu hình.
- EN worker giữ analyzer/JVM trong suốt batch; không khởi tạo JVM mỗi tài liệu.
- Field `surface` giữ dạng không stemming để giảm mất thuật ngữ. Field `medical_exact` giữ token chuẩn hóa của các biểu thức như `IL-6`, `CD4+`, `SARS-CoV-2`, gene/hoạt chất được nhận diện bằng lexicon hoặc quy tắc có provenance.

[EnglishAnalyzer API](https://lucene.apache.org/core/9_12_2/analysis/common/org/apache/lucene/analysis/en/EnglishAnalyzer.html) mô tả constructor có stopword set; [Pyserini analyzer source](https://github.com/castorini/pyserini/blob/pyserini-2.4.0/pyserini/analysis/_base.py) cho thấy helper English và wrapper `Analyzer.analyze`. API Lucene thực dùng phải tương thích JAR đã khóa, không cài Lucene 9.12 riêng vì link tài liệu này.

### 6.3. Vietnamese

- Underthesea `word_tokenize` chạy offline. Dùng token nhiều âm tiết nối bằng `_`, ví dụ `ung_thư`, `suy_thận`; index và query áp dụng giống nhau.
- Adapter giữ dạng surface âm tiết trong field riêng để cứu trường hợp segmentation khác nhau hoặc thuật ngữ chưa biết. Trọng số field phụ thấp hơn `contents`.
- Danh sách thuật ngữ cần giữ nguyên được tạo từ nguồn y khoa công khai, không từ query/nhãn đánh giá; snapshot dictionary bất biến trong job.
- Chỉ dùng chức năng word segmentation NLP, không sử dụng agent/API bên trong các phiên bản khác của Underthesea.

[Underthesea word-tokenize source](https://github.com/undertheseanlp/underthesea/blob/main/underthesea/pipeline/word_tokenize/__init__.py) xác nhận output `format='text'` dùng dấu `_`; bản triển khai phải khóa một release NLP tương thích Python 3.12 và kiểm tra model/resource hash.

### 6.4. Chinese

- Một `jieba.Tokenizer` riêng mỗi worker, precise mode với medical user dictionary UTF-8; giữ cấu hình HMM cố định trong manifest.
- Dictionary chứa tên bệnh, hoạt chất, giải phẫu, thủ thuật và xét nghiệm; chỉ thêm terms có provenance, tránh ép nhập các cụm quá rộng thành một token.
- Field phụ `surface` có CJK bigram để cứu lỗi segmentation/từ ngoài dictionary; không dùng cách thêm bigram vào field chính làm tăng TF/chiều dài một cách không kiểm soát.
- Traditional/Simplified được hỗ trợ qua aliases trong lexicon ban đầu. Chuyển script bằng OpenCC là adapter tùy chọn cần snapshot/cấu hình tương ứng hai phía trước khi bật.

[Jieba documentation](https://github.com/fxsjy/jieba#主要功能) mô tả tokenizer riêng, precise/search mode và user dictionary. Với v1 chọn precise + field cứu segmentation riêng; `cut_for_search` là phương án ablation, không trộn tự do hai mode trong cùng `contents`.

### 6.5. Lucene backend

Build dùng `--pretokenized`, không truyền thêm `--language zh` cho token đã chạy Jieba. Trong [Anserini IndexCollection 2.3.0](https://github.com/castorini/anserini/blob/anserini-2.3.0/src/main/java/io/anserini/index/IndexCollection.java), lựa chọn analyzer theo language được xét trước nhánh `pretokenized`; kết hợp hai flag sai có thể làm token bị phân tích lại.

Searcher phải cài `JWhiteSpaceAnalyzer()` và dựng query từ token đã chuẩn bị. [Pyserini custom-index guide](https://github.com/castorini/pyserini/blob/pyserini-2.4.0/docs/usage-index.md) có hướng dẫn này. Test hợp đồng analyzer bắt buộc chứng minh postings chứa đúng token, kể cả dấu `_`, CJK, chữ số và token y khoa có dấu câu.

## 7. Query bridge xuyên ngôn ngữ

Ba tokenizer không tự dịch `suy thận` thành `renal failure` hoặc `肾衰竭`. Do đó chia hai capability trong cùng component:

- `lexical-control`: original query và ký hiệu chung; dùng để kiểm tra BM25/analyzer, không được mô tả là đã đáp ứng truy hồi xuyên ngôn ngữ đầy đủ.
- `multilingual`: original query + multilingual medical aliases/concepts + bản dịch query EN/ZH cục bộ khi có tài nguyên hợp lệ. Đây là cấu hình đề xuất cho chạy corpus ba ngôn ngữ.

### 7.1. Lexicon

Một entry có `concept_id,type,labels{vi,en,zh},aliases,source_uri,license,version,ambiguity`. Có thể xây snapshot từ medical labels/aliases trong dữ liệu cấu trúc Wikidata, lọc đúng domain y khoa và rà ambiguity trước khi dùng. Wikidata structured data là [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing); giấy phép không bảo đảm chất lượng thuật ngữ.

Medical dictionary Jieba, lexicon alias query và concept mapping chia sẻ nguồn version hóa nhưng có adapter riêng. Một lexicon đơn ngữ ZH tốt cho segmentation không tự trở thành từ điển dịch ba ngôn ngữ. Không lấy ánh xạ dịch từ ground truth hoặc ID tài liệu liên quan.

Longest-match + word boundary cho Latin, match CJK theo trie; không biên dịch regex chứa toàn bộ ontology. Terms mơ hồ như `MS` giữ dạng literal; không tự ép một nghĩa nếu thiếu ngữ cảnh. `concepts` chỉ xuất cho entity thực sự được nhận diện trong nội dung tương ứng, không truyền mọi disease/topic của document xuống tất cả chunk.

### 7.2. Dịch query

Adapter đề xuất để thử sau khi duyệt: local `google/madlad400-3b-mt`. [Model card](https://huggingface.co/google/madlad400-3b-mt) mô tả model dịch 3B và giấy phép Apache 2.0. Trước khi bật, bắt buộc ghi revision weight/tokenizer, bằng chứng artifact đã phát hành trước 01/08/2026, số tham số và điều kiện sử dụng; năm bài báo không thay cho bằng chứng ngày phát hành checkpoint.

Dịch **query**, không dịch corpus/chunk nộp. Giữ query VI làm nhánh gốc; bản dịch EN/ZH là nhánh bổ sung. Kiểm tra bảo toàn chữ viết tắt, số, liều lượng và dấu hiệu phủ định; alias đã biết được bổ sung như alternative term, không tự sửa nội dung query nguồn.

Chỉ dịch một lần cho mỗi `(query_hash,target_language,model_revision,lexicon_hash,decoding_config)`. Cache bền trên đĩa; decoding deterministic, không sampling. Query quá dài được chia theo câu theo token limit thực của model; không truncate âm thầm.

Model này là model tổng quát, chất lượng dịch y khoa chưa được xác nhận ở task này. Không dùng likelihood của model làm xác suất relevance. Các variant hỏng numeric/protected-term checks được gắn warning, loại khỏi nhánh dịch và ghi fallback rõ ràng; job production báo degradation, không tuyên bố đầy đủ cross-language coverage.

Kiểm tra numeric/protected terms là điều kiện cần, chưa chứng minh bản dịch đúng phủ định hoặc quan hệ bệnh–thuốc. Cần bộ ca y khoa độc lập để review khả năng giữ các ý này; không gắn nhãn `translation_verified` chỉ vì regex checks đạt.

Translate trong process/pha riêng; search không nạp model cùng JVM/index. Model FP32 3B có yêu cầu bộ nhớ đáng kể và assets trên đĩa; máy hiện tại chưa được chứng minh đủ RAM available. Có thể chuẩn bị query cache trên máy CPU/GPU phù hợp rồi dùng cache local cho search. Khi thiếu cache/model ở cấu hình multilingual strict, preflight thất bại; không âm thầm chuyển sang lexical-control.

### 7.3. Giới hạn expansion

Ban đầu tối đa hai variant/ngôn ngữ và 128 unique clauses cho mỗi query vật lý. Giữ terms gốc trước terms mở rộng; synonyms cùng concept được đóng nhóm OR/DisjunctionMax để không cộng điểm vô hạn khi entity có nhiều aliases. Phủ định không tự mở rộng thành chẩn đoán dương. Query chính có nhiều concept/quan hệ thì giữ cả query; không thay bằng danh sách từ khóa y khoa đơn lẻ.

## 8. Data model, field và lưu nguyên văn

### 8.1. Prepared records

Document external ID là `str(doc_id)`; chunk external ID là `chunk_id` nguyên bản của input. Identity registry lưu quan hệ tới doc ID và chunk order, không suy ID bằng parse chuỗi hoặc row number.

Prepared JSONL cho Lucene chỉ chứa fields search và identity; không kèm toàn bộ `parents`, `atom_spans`, warning detail hoặc `chunk_text` nguyên văn.

| Field | Document | Chunk | Analyzer trước khi ghi |
|---|---|---|---|
| `id` | ID tài liệu nguồn | ID chunk nguồn | String identity |
| `contents` | Nội dung body duy nhất theo source offsets | Nội dung child | Pipeline của language |
| `title` | Tiêu đề xác minh được từ source spans | Tiêu đề nguồn, boost thấp | Pipeline của language |
| `section` | Nhãn section hợp lệ | Section context tương ứng | Pipeline của language |
| `surface` | Dạng cứu segmentation/stemming | Tương tự | Surface pipeline riêng |
| `medical_exact` | Terms/biomarkers thấy trong body | Chỉ terms thấy trong chunk | Protected-term pipeline |
| `concepts` | Concepts thấy trong document | Concepts thấy trong chunk | Canonical concept IDs |

Field không có bằng chứng để trống; không dùng URL slug làm tiêu đề giả. Field values là chuỗi token. `--fields title section surface medical_exact concepts` bật đúng fields cần index. [DefaultLuceneDocumentGenerator](https://github.com/castorini/anserini/blob/anserini-2.3.0/src/main/java/io/anserini/index/generator/DefaultLuceneDocumentGenerator.java) chỉ index các field phụ khai báo trong args; metadata JSON thêm tự do không tự tạo searchable field.

Document body được dựng từ **union source intervals của các child đủ điều kiện**, theo thứ tự vị trí, mỗi ký tự overlap chỉ xuất hiện một lần. Không nối naïve mọi chunk: overlap làm tăng TF, length và tạo lợi thế sai cho tài liệu nhiều chunk. Overlap có nội dung không nhất quán là lỗi dữ liệu. Gap không biết nguyên văn được đánh dấu ranh giới trong bản index; không dùng body dựng này làm chunk nộp.

### 8.2. OriginalTextStore mặc định

Chọn `SourcePointerTextStore`: SQLite lưu con trỏ tới JSONL nguồn, giúp không nhân đôi toàn bộ văn bản.

```text
documents: doc_id PK, url, source_sha256, shard_id,
           record_byte_offset, record_byte_length, record_sha256
chunks: chunk_id PK, doc_id FK, chunk_order, parent_id,
        start_char, end_char, chunk_text_sha256, quality_state
source_shards: shard_id PK, relative_path, size, mtime_ns, sha256
```

Byte offset/length dùng cho **dòng JSONL trên đĩa**, khác char offsets của source text. Đọc binary và decode UTF-8; không lấy char offset làm file offset.

`get_many(chunk_ids)` gom theo source record, seek/đọc/decode một lần cho các chunk cùng document; kiểm tra row/doc/chunk identity và hash chuỗi trước khi nộp. Cache record decode theo byte budget, không theo số tài liệu không giới hạn. Source shards phải tồn tại bất biến; stat check khi mở snapshot, hash kiểm trên record/text được hydrate. Bản portable muốn tự chứa văn bản có thể dùng `SqliteTextStore` sau này qua cùng interface, phải tính lại dung lượng.

SQLite một writer trong build, bulk insert theo transaction; worker tokenizer không tự cạnh tranh ghi DB. Sau build, checkpoint WAL và đóng writer trước khi publish. Search dùng read-only connection riêng theo thread. Không dùng `PRAGMA` bỏ durability để tăng tốc.

### 8.3. Ngôn ngữ và chất lượng

Routing dựa trên evidence của `content_language_spans`, script và nguồn; `source_language` theo domain chỉ là prior. Các span `und` không làm mất tài liệu. Latin không chắc VI/EN được tạo rescue view có giới hạn; CJK được đưa vào ZH; multilingual chunk có view tương ứng. Các view giữ canonical ID, và fusion tránh cộng nhiều lần các alias chỉ do uncertainty của cùng một routing group. Report counts phải phân biệt số canonical record và số physical indexed view.

Profile ảnh hưởng field/section context, không quyết định eligibility một mình. Chỉ có tiêu đề hoặc lẫn UI được đánh dấu `content_limited/review_required`; default không loại tất cả tài liệu ngắn. Những `oversized_unresolved` đã biết trong full output tạo release blocker cho input production mặc định, cho phép build thí nghiệm bằng flag rõ ràng để nghiên cứu. Retriever không tự sửa chunk nguồn hoặc âm thầm bỏ tài liệu dương có thể liên quan.

## 9. BM25, query construction và fusion

### 9.1. BM25

Khởi đầu `k1=1.2,b=0.75`, đặt rõ bằng API trên từng searcher, không phụ thuộc default Pyserini. Đây là baseline tham chiếu theo [Lucene BM25Similarity](https://lucene.apache.org/core/9_12_2/core/org/apache/lucene/search/similarities/BM25Similarity.html), **chưa phải tham số tối ưu cho corpus này**. Cấu hình cho phép tách k1/b theo language và granularity sau khi có đánh giá độc lập.

Field score là tổng đóng góp BM25 qua các clause được boost, **không gọi đó là BM25F**. Boost khởi đầu đề xuất: `contents=1.0`; document `title=1.5`, chunk `title=0.2`; `section=0.2,surface=0.15,medical_exact=0.5,concepts=0.5`. Fields phụ chưa có resource thì không tạo clause. Title yếu ở chunk vì cùng tiêu đề có thể được kế thừa bởi rất nhiều chunk không trả lời query.

### 9.2. QueryBuilder

- Dựng Lucene `TermQuery/BooleanQuery/BoostQuery/DisjunctionMaxQuery` từ field-specific tokens. Query dùng cho `contents` đã stemming/segmentation; query `surface`/`medical_exact` giữ dạng riêng. Không đưa một chuỗi token chung vào mọi field như thể analyzer giống nhau.
- Dấu `+ - : ( )` trong lời người dùng là dữ liệu, không phải cú pháp QueryParser; không dùng parser tự do dễ biến query y khoa thành toán tử.
- Query terms cùng nghĩa là alternatives; không ép AND tất cả từ hoặc tất cả bản dịch. Term coverage/relations có thể hỗ trợ reranking, không áp hard gate mặc định khi evidence còn yếu.
- `LuceneSearcher.search(JQuery,k)` là đường API cho query tùy biến; không truyền `fields=...` đồng thời vì wrapper không hỗ trợ tổ hợp này. `batch_search` chuẩn nhận strings; không giả định nhận list custom `JQuery`. Với custom query, scheduler dùng các lần `search` trong thread pool có giới hạn, searcher/analyzer bất biến được mở một lần.

[Pyserini searcher source](https://github.com/castorini/pyserini/blob/pyserini-2.4.0/pyserini/search/lucene/_searcher.py) là căn cứ cho giới hạn API; compatibility tests phải kiểm lại phiên bản cài thực tế trước full build.

### 9.3. Hai đường truy hồi

1. Chunk index tìm các vùng liên quan trực tiếp trên toàn corpus: tránh document retrieval sai làm khóa mất chunk dương.
2. Document index tìm tài liệu theo body/title: tránh một chunk ngắn yếu khiến mất document dương hoặc chỉ dựa vào evidence cục bộ.
3. Tạo thêm document run từ chunk run bằng evidence tốt nhất của mỗi doc, không cộng mọi chunk của doc khiến tài liệu dài được ưu tiên.
4. Kết hợp document runs; chunk runs kết hợp riêng theo canonical chunk ID. Một chunk không cần phải thuộc top-document ban đầu để được làm candidate.

Ban đầu lấy `candidate_chunks=1000/language/variant`, `candidate_docs=200/language/variant`; mọi con số là budget ban đầu cần đo, không phải hạn mức BTC. Có thể tăng riêng khi recall candidate ở đánh giá độc lập chưa đủ và còn tài nguyên.

### 9.4. Rank fusion

Dùng weighted RRF: `score(x)=sum_r w_r/(rrf_k+rank_r(x))`, rank bắt đầu 1; `rrf_k=60`, weights khởi đầu bằng nhau giữa language runs. Mỗi run dedup canonical ID trước khi rank. Correlated variants/rescue aliases đóng cùng group, lấy contribution lớn nhất trong group trước khi cộng các group.

RRF tránh giả định raw BM25 của index Anh, Trung, Việt cùng thang đo. Nó có thể mất thông tin khoảng cách score, nên lưu cả raw score/rank/field evidence cho ablation. Những weights này không phải confidence đã calibration.

Input shard chỉ là đơn vị IO/preparation. Mặc định mỗi language/granularity có một logical Lucene index với thống kê toàn partition. Không search các index chia ngẫu nhiên theo shard rồi cộng raw score: IDF/avgdl khác nhau. Nếu cần physical distributed shards trong tương lai, bổ sung global statistics hoặc merge Lucene segments cùng analyzer, kèm capacity estimate; không mặc định native `batch_search` giải quyết distributed scoring.

## 10. Chọn kết quả để tối ưu F2

Tách `CandidateFusion` khỏi `ResultSelector`. Thử candidate recall và output precision riêng; tăng candidate budget không đồng nghĩa tăng số nộp.

### 10.1. Chính sách khởi đầu không học nhãn

- `FixedBudgetSelector`: tối đa 20 document, 40 chunk; chunk tối đa 4/doc ban đầu, không cố điền đủ khi không có lexical hit. Đây là mốc baseline, không tuyên bố tối ưu.
- Dedup document theo doc ID; chunk trùng nguyên văn sau BTC normalization **trong cùng doc** được giữ một đại diện. Không dedup các doc khác ID.
- Các chunk overlap cao có thể giảm contribution trong selector để dành ngân sách cho vùng khác; penalty mềm theo source interval và lexical evidence, không loại toàn bộ chunk chung parent/section.
- Không tự trả tất cả chunk của một doc. Không ép một chunk/doc: query nhiều ý có thể cần nhiều vùng khác nhau.
- Doc selector nhận cả evidence document và chunk. Hai danh sách output được chọn theo hai mục tiêu đánh giá; mọi chunk phải FK đúng source. BTC được cung cấp không nêu `doc_id` trong relevant_chunks bắt buộc thuộc relevant_docs, nên không thêm ràng buộc cứng đó. Chính sách promote selected-chunk documents nếu dùng phải là option được đánh giá riêng, vì nó có thể làm giảm doc Precision.
- Chunk output mặc định là child nguồn, giữ `chunk_order` nguồn; order ranking có thể khác source order nhưng không thay giá trị metadata.

### 10.2. Chính sách có calibration độc lập về sau

`AdaptiveSelector` có thể dùng score-gap, coverage concept, agreement các runs và confidence được calibration để chọn số lượng theo query. Không dùng raw BM25 hoặc RRF score như xác suất; không lấy threshold ngẫu nhiên dùng chung cho mọi ngôn ngữ và query dài/ngắn.

Chọn hyperparameters trên **development labels độc lập**, freeze, rồi đánh giá một lần trên held-out labels khác. Query/tài liệu liên quan dùng chung phải được group khi split để tránh leakage; chính sách split này là quy trình cho tập nhãn độc lập tương lai, không khảo sát `for_valid`.

Nếu chưa có nhãn được phép dùng: giữ FixedBudgetSelector và report chưa xác nhận chất lượng P/R/F2. Chạy unlabelled official queries chỉ tạo predictions/latency/diagnostics, không tự gọi các chỉ số đó là điểm BTC.

### 10.3. Mở rộng chất lượng sau BM25

Interface `CandidateReranker` cho phép bổ sung dense/hybrid hoặc open-weight reranker hợp lệ khi BM25 không giải quyết được synonym/ngữ cảnh/phủ định. Default `NoOpReranker`. Không tích hợp closed API vào query translation, reranking hoặc dự đoán chính thức. BM25 là tầng ứng viên có thể mở rộng, không được quảng bá là đủ hiểu ngữ nghĩa y khoa chỉ nhờ dictionary.

## 11. Hợp đồng OOP và cấu trúc module

Dùng composition, `Protocol` cho dependency và frozen dataclass cho DTO. Không tạo cây kế thừa sâu hoặc class cho từng hàm thuần.

| Interface/lớp | Trách nhiệm và giới hạn |
|---|---|
| `CorpusReader` | Stream record, kiểm schema ở input boundary |
| `IdentityRegistry` | Membership `(id,url)`, canonical IDs, pointer metadata |
| `QualityPolicy` | Eligibility, warning, production blocker có reason |
| `LanguageRouter` | Language views có evidence/routing-group ID |
| `TokenPipeline` | Chuẩn bị field tokens; fingerprint; không sửa source |
| `QueryBridge` | Original/lexicon/translation variants, không truy cập nhãn |
| `IndexBuilder` | Bounded preparation, backend build, manifests/resume |
| `SearchBackend` | Lucene-specific query/search API, ẩn Java hits |
| `CandidateFusion` | Runs → canonical candidates, dedup/rank provenance |
| `CandidateReranker` | Adapter optional, default NoOp |
| `ResultSelector` | Candidates → lists với budget/policy rõ |
| `OriginalTextStore` | Lấy đúng chuỗi nguồn bằng ID, bulk lookup/hash |
| `SubmissionWriter` | Valid JSON/ZIP, identity/query completeness |
| `BtcEvaluator` | Pure evaluation ngoài serving, chỉ nhận predictions + labels cho phép |
| `BM25Engine` | Điều phối dependencies, không biết qrels hoặc logic Java cụ thể |

Ví dụ interface dự kiến:

```python
@dataclass(frozen=True)
class SearchHit:
    external_id: str
    doc_id: int
    chunk_id: str | None
    rank: int
    score: float
    run_id: str

class OriginalTextStore(Protocol):
    def get_many(self, chunk_ids: Sequence[str]) -> Mapping[str, OriginalChunk]: ...

class SearchBackend(Protocol):
    def search_batch(self, queries: Sequence[AnalyzedQuery], *, k: int) -> Mapping[str, Sequence[SearchHit]]: ...
    def close(self) -> None: ...

class BM25Engine:
    def __init__(self, *, bridge: QueryBridge, backend: SearchBackend,
                 fusion: CandidateFusion, selector: ResultSelector,
                 text_store: OriginalTextStore): ...
    def search(self, query: Query) -> SubmissionItem: ...
    def search_batch(self, queries: Iterable[Query]) -> Iterator[SubmissionItem]: ...
```

DTO `OriginalChunk` có nguyên văn, doc ID, chunk order, source offsets/hash; `AnalyzedQuery` có unique request key tách `(query_id,language,variant,granularity)` để native batch không ghi đè cùng query ID. `SubmissionItem` là định dạng DTO nộp, không chứa scores/debug.

Structure đề xuất:

```text
sbtc/Scripts/Retrieval/
  SPEC-bm25-medical-multilingual.md
  __init__.py, cli.py, config.py, models.py, interfaces.py
  corpus.py, identity.py, quality.py, text_store.py
  analyzers.py, lexicon.py, query_bridge.py
  lucene_backend.py, index_builder.py, query_builder.py
  fusion.py, selectors.py, engine.py, export.py, evaluation.py
  configs/bm25-test.toml, configs/bm25-full.toml
  resources/README.md, requirements-bm25.lock
  tests/test_analyzers.py, test_identity.py, test_evaluation.py,
        test_search_contract.py, test_resume.py
artifacts/retrieval/<run_id>/
  manifest.json, state.sqlite, metadata.sqlite
  prepared/{documents,chunks}/{vi,en,zh}/
  indexes/{documents,chunks}/{vi,en,zh}/
  query_cache/, runs/, audit/, resource_report.json
```

Các source/config/test ngoài file đặc tả trên là **file dự kiến**, chưa tồn tại do task này. Formatter/test tooling reuse những gì module/repo có ở thời điểm triển khai; có thể dùng `unittest` stdlib cho module riêng nếu repo không cung cấp runner thích hợp, không bổ sung framework chỉ để làm baseline.

## 12. Build, resume và vận hành Big Data

### 12.1. Streaming và bounded memory

- Đọc từng shard, từng dòng binary; parse từng document, giữ tối đa record/batch hiện tại. Không tạo list chứa 4 triệu chunk hoặc load JSONL thành DataFrame.
- Batch preparation giới hạn theo **bytes và records**; khởi đầu 64 MiB, 1000 record, dừng ở ngưỡng đạt trước. Input một record lớn hơn giới hạn batch được xử lý riêng; vượt safety limit riêng thì báo lỗi với offset, không truncate.
- Dictionary/tokenizer nạp một lần mỗi worker. Python multiprocessing dùng `spawn`, không fork JVM đã khởi tạo; EN analyzer chạy trong worker riêng sống lâu. Producer/consumer queue bounded, không submit futures không giới hạn.
- Worker budget có thể khác theo language, tránh mỗi worker mang ba tokenizer và một JVM. Khởi đầu conservative trên máy hiện tại: một EN worker, tối đa hai worker VI/ZH, sau preflight mới tăng.
- Không giữ Prepared JSON và bản raw text cùng lúc cho cả corpus. Metadata writer duy nhất; index subprocess build từng partition để hạn chế đỉnh RAM/đĩa.

### 12.2. Index tiết kiệm dung lượng

Mặc định term frequencies + norms; không `--storeRaw`, không `--storeContents`, không docvectors, không positions. Nguyên văn được hydrate qua pointer store. Phrase search/RM3 muốn bật cần cấu hình index mới và đo lại kích thước, không giả định dùng được trên index thiếu positions/docvectors.

Tokenized staging là JSONL shard chỉ có fields cần index; Anserini đọc nhiều file. Sau khi partition được build, kiểm hash/count và publish thành công mới cho phép cleanup **intermediate thuộc chính run**, theo retention cấu hình. Không cleanup input nguồn hoặc artifact của run khác.

### 12.3. Tính nhất quán/resume

- One-writer job lock; `run_id` phải mới hoặc resume đúng fingerprint.
- Preparation: ghi shard `.tmp`, fsync, rename, rồi commit task completion/row metadata vào state transaction. Crash giữa các bước phải có reconciliation từ task state và hashes; task chưa complete được làm lại idempotently.
- Không blind append vào Lucene rồi cộng checkpoint counter: có thể trùng postings hoặc mất mapping. Build từng index vào `<partition>.building`, kiểm tra, close và publish atomic sau cùng. Resume bỏ qua partition đã hoàn tất đúng fingerprint; partition dở được rebuild từ prepared data của run.
- `done=true` chỉ khi đủ sáu partition, metadata closed, số view/canonical ID đối soát, và integrity checks đạt. Manifest write atomic.
- Source shard/lexicon/analyzer đổi hash → không resume snapshot cũ. Tạo run mới; không overwrite index đang phục vụ query.
- Search reader dùng một snapshot manifest duy nhất trong một job; không cập nhật nóng giữa các query của cùng bài nộp.

### 12.4. Preflight tài nguyên

Trước full build, dùng **test_20k** đo kích thước staging/index/metadata cho từng language và granularity, số terms/view, peak RSS, throughput; không dùng nhãn để đo capacity. Chiếu theo canonical counts, view/term amplification và phân bố corpus manifest, không nhân tỷ lệ theo 23 GB metadata JSON một cách máy móc.

Ước lượng disk gồm index mới, staging đang sống, metadata, model cache nếu có, merge scratch và artifact cũ cần giữ. Yêu cầu headroom tối thiểu 30% trên đỉnh ước lượng; phần merge chưa biết phải ghi giả định bảo thủ. Khi đĩa/RAM thiếu: báo `InsufficientResources`, không tự xóa dữ liệu hoặc giảm fields/budget đã chốt.

Khoảng 30,8 GiB trống hiện tại **chưa đủ căn cứ kết luận full job sẽ vừa**, nhất là nếu tải model dịch. Tận dụng pointer store, build partitions tuần tự, cache dịch ở thiết bị khác và storage riêng là lựa chọn vận hành, không thay thuật toán.

## 13. Batch query, hiệu năng và lỗi

- Mở sáu index/searcher một lần, set BM25/analyzer một lần. Không tạo JVM, reopen index hoặc đọc lại corpus cho từng query.
- Chuẩn bị/query-cache trước search; query batch ban đầu 64, tối đa 4 concurrent searches toàn scheduler trên máy 12 CPU. Đây là tổng budget, không phải 4 thread nhân 6 index nhân mọi variant.
- `SearchBackend.search_batch` giữ contract chung; baseline chuỗi một field có thể dùng native `batch_search`, query đa field khác token dùng bounded custom-query scheduler. Keys variant riêng tránh dictionary result overwrite.
- Candidate pool giới hạn theo budgets và batch size; hydrate nguyên văn sau shortlist, gom theo record; caches có byte budget mặc định 128–256 MiB và đo thực tế.
- Query cache key chứa analyzer/query bridge/index fingerprints. Không reuse ranking của index khác hoặc translated query của lexicon/model khác.
- Empty query/không có lexical token: xuất hai list rỗng và reason. Query error tạm thời: retry có giới hạn, lưu error; job chưa thành công không tạo ZIP hoàn tất. Không bỏ query hoặc âm thầm bỏ một language branch.
- Tie handling deterministic theo external canonical ID, không phụ thuộc worker completion order. Output query giữ thứ tự input, không giả định ID liên tục từ 1 tới N.

Mục tiêu hiệu năng ban đầu để đo sau triển khai: trên máy 12 logical CPU, RAM tổng ít nhất 16 GiB và available ít nhất 8 GiB, SSD/NVMe, warmed indexes + translation cache: **>=1 query/s toàn batch**, p95 end-to-end search/hydration **<=5 s**, 1.200 query **<=30 phút**; resident memory retrieval/build phase mục tiêu <=8 GiB, không tính page cache OS và pha dịch tách riêng. Các mốc là mục tiêu nghiệm thu đề xuất, chưa có phép đo chứng minh. Cold start, hashing và translation time báo riêng; không bỏ chúng khỏi resource report tổng.

### 13.1. Error contract và telemetry

`BM25Error` mang `code,message,source_path,byte_offset,query_id/doc_id` nếu liên quan. Codes gồm `InvalidInput`, `MappingMismatch`, `SourceChanged`, `AnalyzerMismatch`, `IndexNotReady`, `InsufficientResources`, `QueryBridgeDegraded`. Lỗi cấu hình/mapping/hash chặn job; warning nội dung phải có reason và counters, không được chuyển thành success âm thầm. Log không dump toàn bộ record lớn.

Report build tách canonical documents/chunks, physical language views, skipped records theo reason, prepared/indexed counts, index/token/lexicon hashes, disk bytes, queue peak, Python/JVM memory và records/s. Trace query lưu query hash, variant status/cache, candidates trước/sau dedup, raw BM25/rank/RRF, selector reason, số output, thời gian translation/search/hydration. `profile` và quality flags hỗ trợ audit, không trở thành nhãn relevance.

## 14. Evaluation độc lập và chống bias

Task đặc tả không mở/đọc/tune/chấm theo `for_valid/`. CLI search/preparation không nhận qrels hoặc benchmark metadata. Evaluator chỉ được gọi riêng với labels được phép dùng, sau khi freezing config và predictions.

Khi chưa có development labels độc lập: chỉ báo technical correctness, corpus/query completeness, analyzer consistency, latency/resources và predictions. Không gán điểm F2 giả, không dùng self-query từ đoạn nguồn làm bằng chứng đã đạt retrieval accuracy thực tế.

Khi có tập nhãn độc lập sau này:

1. Ghi provenance, phạm vi corpus/snapshot, chính sách judgment và query/document group split trước khi tune.
2. Check mọi label doc ID tồn tại trong corpus đánh giá; không bỏ missing positives khỏi mẫu số. Corpus nhỏ thiếu nhãn phải được báo là coverage-limited, không so với full score như cùng điều kiện.
3. Report candidate Recall@K trước selection, macro P/R/F2 sau selection ở hai cấp. Recall@K/MRR/nDCG là diagnostic, không thay công thức BTC.
4. Tách doc/chunk cutoff. Grid nhỏ k1/b và budgets trên dev; không tích Cartesian product cho sáu index cùng tất cả fields/weights. Thay từng nhóm tham số, record experiment config đầy đủ.
5. Ablations: lexical-control → medical dictionary → translation → fields phụ → fusion → selector. Test language/profile/length subgroup trên dev được phép, không tối ưu theo một vài query biết đáp án.
6. Freeze rồi held-out evaluation; báo cả lỗi/nhóm mất Recall. Không chọn chỉ report tốt nhất của nhiều lần trên held-out.

Evaluator group reference/prediction theo `(query_id,doc_id)`, normalize cache trong một query, LCS exact DP một hàng O(min(n,m)) memory. Prefilter an toàn bằng `min(n,m)` và multiset token intersection để loại cặp không thể đạt ngưỡng; không dùng substring/embedding/Jaccard thay LCS. Không làm all-pairs giữa mọi query/tài liệu.

## 15. Export BTC

```json
[
  {
    "id": 1,
    "relevant_docs": ["583"],
    "relevant_chunks": [
      {"doc_id": "583", "chunk_text": "Chuỗi nguyên bản từ chunk nguồn", "chunk_order": 0}
    ]
  }
]
```

Ví dụ schema, không phải một prediction đã chạy. Export kiểm tra all expected query IDs từ input; khi input official là `newcorpus/query.parquet` thì phải đủ 1.200. Giữ các query không có kết quả với list rỗng. IDs nguồn xuất string ở các trường doc, query ID xuất integer.

Write array JSON theo stream qua `.partial`, finalize sau count/schema/identity/hash checks. ZIP chứa đúng một JSON ở root, không chứa scores, trace, manifest hoặc file nguồn. Writer chỉ đóng gói; không tự upload bài nộp.

## 16. Cấu hình và lệnh dự kiến

Những lệnh dưới đây là **hợp đồng CLI sẽ triển khai sau khi đặc tả được duyệt**, không phải các lệnh BM25 đã có trong repo hiện tại. Chạy từ root repo.

```bash
python3.12 -m venv .venv-bm25
.venv-bm25/bin/python -m pip install -r sbtc/Scripts/Retrieval/requirements-bm25.lock

.venv-bm25/bin/python -m sbtc.Scripts.Retrieval.cli preflight \
  --config sbtc/Scripts/Retrieval/configs/bm25-test.toml

.venv-bm25/bin/python -m sbtc.Scripts.Retrieval.cli build \
  --config sbtc/Scripts/Retrieval/configs/bm25-test.toml \
  --run-dir artifacts/retrieval/bm25-test-v1

.venv-bm25/bin/python -m unittest discover \
  -s sbtc/Scripts/Retrieval/tests -p 'test_*.py'

.venv-bm25/bin/python -m sbtc.Scripts.Retrieval.cli prepare-queries \
  --config sbtc/Scripts/Retrieval/configs/bm25-test.toml \
  --queries newcorpus/query.parquet \
  --cache artifacts/retrieval/query-cache-v1

.venv-bm25/bin/python -m sbtc.Scripts.Retrieval.cli search \
  --config sbtc/Scripts/Retrieval/configs/bm25-test.toml \
  --run-dir artifacts/retrieval/bm25-test-v1 \
  --queries newcorpus/query.parquet \
  --output artifacts/retrieval/bm25-test-v1/runs/predictions.json
```

Unlabelled query run trên test corpus không phải điểm official/full. `evaluate --predictions <file> --qrels <approved-independent-labels> --queries <file> --output <report>` là contract tùy chọn tương lai; không cấu hình đường dẫn `for_valid` làm default.

Ví dụ argv backend build một partition, dựa trên API đã đối chiếu; prepared files và index folder trong ví dụ vẫn là artifact sẽ được tạo sau triển khai:

```bash
JAVA_TOOL_OPTIONS="-Xmx3g" .venv-bm25/bin/python -m pyserini.index.lucene \
  --collection JsonCollection \
  --input artifacts/retrieval/bm25-test-v1/prepared/chunks/vi \
  --index artifacts/retrieval/bm25-test-v1/indexes/chunks/vi.building \
  --generator DefaultLuceneDocumentGenerator \
  --threads 2 --pretokenized \
  --fields title section surface medical_exact concepts
```

Builder chạy subprocess bằng argv list, không ghép query/path vào shell expression. JVM heap trong ví dụ phải qua preflight; không tự chạy khi máy thiếu RAM available. Các partition khác dùng đúng pipeline tương ứng và vẫn WhitespaceAnalyzer.

`bm25-test.toml`: chunks từ `chunks_format_v3_r3_reserve_test20k`, source scope từ `test_20k.jsonl`; build tests/benchmark dùng tập này. `bm25-full.toml`: chunks từ `chunks_format_v3_final`, whitelist từ Parquet được chọn; dùng chung logic engine, chỉ khác paths/capacity flags. Full build chưa tự chạy trong task này, và input quality/resource preflight phải đạt trước khi publish.

Các config keys bắt buộc: `corpus_snapshot`, `source_scope`, `chunk_input`, `run_dir`, `analyzer_versions`, `lexicon_manifest`, `query_bridge.mode`, model revision/cache khi dùng translation, `bm25` theo granularity/language, field boosts, candidate budgets, selector, resources, quality policy, export/evaluation conventions.

Không sửa `sbtc/pyproject.toml` hoặc cài dependency vào môi trường crawler trong task đặc tả. Requirement lock retrieval và Java environment sẽ được review ở bước triển khai. Không khóa một phiên bản Underthesea chưa kiểm compatibility chỉ vì có số version mới.

## 17. Ca kiểm thử và nghiệm thu

Tests chạy trên extracts của **test_20k** và các fixture cơ học minh họa luật BTC; không dùng nhãn/query từ `for_valid`, không chạy thử thay đổi trên raw full corpus.

| Nhóm | Ca bắt buộc |
|---|---|
| Identity | ID khuyết thiếu/lớn hơn trần cũ vẫn đúng membership; reject bool/float; mismatch URL; duplicate ID conflicting payload; FK child sai |
| Text fidelity | Unicode VN/CJK; original hash giữ nguyên sau tokenization/translation/index/hydration; offset byte khác char; đổi source record sau build bị phát hiện |
| Analyzer | Index/query tokens trùng pipeline; `_` không tách; real EnglishAnalyzer class; negation còn token; medical symbols/numbers còn exact field; dictionary drift làm resume fail |
| Multilingual | Known medical aliases cùng concept; translation cache hit/miss; numeric mismatch; ambiguity giữ literal; missing model/cache strict fail; mixed/und không bị drop |
| Index | Postings/TF/length đúng fixture; field phụ thật sự được index; doc body de-overlap; unknown fields không phát sinh silent behavior; không cần storeRaw để hydrate |
| Search | Query chứa `+/-/:/()` không biến thành operator; no-hit/empty query; stable ties; variant keys không overwrite; single và batch cùng kết quả |
| Selection | Hai candidate pathways; document dài không ăn điểm từ cộng nhiều chunk; không trả all chunks; dedup đúng scope; per-doc cap và overlap penalty không che các vùng khác nhau |
| BTC scoring | NFKC/entity/lower/whitespace; LCS không cần liên tiếp; sai doc ID là sai; 0.399/0.400; many-to-many và unique reference recall; macro F2 khác F2(macro P,R); Chinese whitespace-token mismatch |
| Export | Query IDs không liên tục/thiếu/trùng; optional order giữ nguồn; JSON stream valid; ZIP một file root; debug không vào submission |
| Resume | Interrupt trước/sau prepared rename/DB commit/index close; không nhân đôi record; incomplete partition rebuild; changed fingerprint/source fail; no overwrite existing snapshot |
| Big Data | Bounded queues/cache; large record không truncate; insufficient disk/RAM fail; resource telemetry gồm Java/Python; 1000+ unlabelled query batch memory không tăng theo N corpus |

Nghiệm thu kỹ thuật: tất cả ca hợp đồng thuộc phạm vi đạt; zero mapping/text mismatch; manifest counts reconcile; no unexplained dropped records; analyzer/query bridge assets/fingerprints tái lập; batch hiệu năng đạt mục tiêu trên máy ghi rõ cấu hình; export đủ expected queries.

Nghiệm thu production input: quality blocker được xử lý/xác nhận bằng artifact riêng; không tự loại âm thầm 20 unresolved hiện có. `uncertain_format` không phải blocker mặc định.

Nghiệm thu chất lượng retrieval: chỉ kết luận có cải thiện điểm sau phép đo nhãn độc lập được phép dùng; báo P/R/F2 hai cấp và trade-offs. Không đặt mốc F2 0.9/1.0 khi chưa có bằng chứng, không coi technical tests xanh là đạt điểm thi cao.

## 18. Thứ tự triển khai đề xuất sau khi duyệt

1. Compatibility môi trường riêng Python 3.12/Java 21/Pyserini; kiểm analyzer thật, fields và custom query API bằng fixture test_20k nhỏ. Chốt lock/asset provenance.
2. DTO/Protocols + streaming reader + identity/pointer store + immutable manifest. Chứng minh original text round-trip và idempotent preparation.
3. Token pipelines EN/VI/ZH, medical dictionary/lexicon importer version hóa, language routing. Chứng minh index/query symmetry.
4. Sáu index test20k; full document de-overlap; postings/schema/count audit; đo capacity.
5. Lexical-control engine + document/chunk candidate paths + RRF + FixedBudgetSelector + streaming export, single/batch parity.
6. Query bridge multilingual: lexicon aliases/concepts và optional verified local translation adapter/cache; đo tài nguyên riêng, kiểm terms/negation/numbers. Không đọc nhãn để sửa dictionaries.
7. Evaluator độc lập theo công thức người dùng; mechanical tests, diagnostics/trace, bounded batch resource run trên corpus test20k. Chưa chạy chấm điểm nếu chưa có nhãn độc lập được phép.
8. Review readiness source chunk hiện tại và preflight full storage/RAM. Full index mới chỉ publish khi input/resource gates đạt; search official queries, kiểm đủ 1.200 predictions và đóng gói.
9. Tune/adaptive cutoff/reranking chỉ sau khi có quy trình đánh giá độc lập. Khi chưa có, giữ defaults công bố rõ và không tuyên bố tối ưu.

## 19. Quyết định cần duyệt

Đề xuất duyệt sáu index + tokenization offline thống nhất WhitespaceAnalyzer, pointer store giữ nguyên text, query bridge có khả năng dịch local/medical lexicon, hai candidate pathways và output selection riêng theo hai cấp F2.

Các quyết định resource/version còn phải xác minh lúc triển khai: release NLP Underthesea phù hợp, medical lexicon snapshot đủ chất lượng/provenance, revision model dịch hợp lệ và máy đủ capacity. Chúng không được thay bằng số liệu từ `for_valid` hoặc auto fallback không thông báo. Hướng mở rộng giữ qua interface; thêm translator/reranker không phải viết lại BM25 core.
