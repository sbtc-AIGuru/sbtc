# BM25 mới: ứng viên y khoa đa ngữ cho reranking

Ngày 15/10/2026. Đặc tả cho triển khai mới theo yêu cầu trực tiếp của người dùng; không đọc, copy hoặc import module BM25 cũ. Không dùng `for_valid` để thiết kế, tuning hay đánh giá.

## 1. Mục tiêu

Tạo tập ứng viên rộng, có truy vết, ở cả document và chunk cho query tiếng Việt trên corpus Việt/Anh/Trung. BM25 là tầng tìm ứng viên trước reranker; kết quả ứng viên không đồng nghĩa với danh sách tối ưu để nộp BTC. Bảo toàn ID nguồn và `chunk_text` nguyên bản; mở rộng OOP bằng composition/interfaces.

Input: JSONL chunk hiện tại (`status`, `doc_id`, `url`, `parents`, `children`, source metadata), whitelist Parquet `id,url`, query Parquet hoặc JSON/JSONL `id,query`. Tests/benchmark corpus chỉ sử dụng `data_final/test_20k.jsonl` và các chunk dẫn xuất của nó. Full corpus khoảng 1,22 triệu tài liệu/4,34 triệu chunk được hỗ trợ qua streaming, không chạy thử trên raw full trong task này.

## 2. Chọn lọc thông tin mới

| Đề xuất dán vào | Quyết định triển khai |
|---|---|
| Compound + phân rã mịn | Tách fields, không tăng TF/length của field chính bằng tất cả variants |
| Giữ mã y khoa, liều lượng, acronym trước lowercase | Có; giữ literal và thêm aliases an toàn, không đổi chuỗi nguồn |
| VI shingles + không dấu | Fields cứu Recall riêng, weight thấp; không bỏ dấu field chính |
| ZH asymmetric analyzers | Index broad có subwords/bigram; query precise giữ cụm dài. Jieba `cut_for_search` thực tế là mode mịn, không phải mode thô |
| EN kstem/inflection/Greek variants | Krovetz trên field compound, field exact bảo vệ biomarker; inflections/spelling từ bảng mapping, không regex thay mọi chuỗi con |
| Neo khái niệm chung | Dictionary có namespace/provenance, không tự suy CUI/MeSH/ICD từ regex hoặc bịa ID |
| Synonym graph lúc index | Flat pretokenized fields không biểu diễn Lucene token graph. Synonyms dùng query alternatives/concept field, không giả vờ flatten graph tương đương |
| Xóa “điều trị/phác đồ” | Giữ intent, không coi là stopword. Câu hỏi điều trị, chẩn đoán, phòng ngừa khác nhau |
| OR + per-language quota | Lấy ứng viên OR theo channel/language; quota là minimum candidate opportunity, không quota bắt buộc trong bài nộp |
| DisMax bảo đảm công bằng đa ngữ | Không đúng: raw score các partition/fields chưa calibration. Dùng RRF rank giữa channels; DisMax chỉ cho alternatives trong cùng index |
| Minmax và threshold 0.25–0.35 | Không bật ngưỡng relevance cố định chưa đo; không cắt sớm tập ứng viên |
| F1 tối đa, không đánh đổi P/R, OOV 100% | Không có bảo đảm đó; mục tiêu BTC là F2 macro. Giữ report P/R riêng |
| TF=1 đạt 100% saturation khi k1 thấp | Không đúng: với chiều dài trung bình, factor TF=1 là 1 bất kể k1; asymptote là k1+1 |
| Projection <80 ms gồm dịch LLM | Không cam kết; dictionary/cache và model translation latency báo riêng |
| Tất cả CMeSH/dược điển/UMLS đều mở | Không giả định giấy phép; resource importer yêu cầu license, version, nguồn và hash |

## 3. Bất biến và luật BTC

Doc ID lấy đúng integer trong whitelist đang chọn, không dùng row index hoặc trần ID lịch sử. Current Parquet có ID Anh vượt 4.420.561. Mọi chunk FK trỏ đúng document; chunk order nguồn giữ nguyên.

Chỉ biến đổi bản index/query: NFKC xử lý width, bảo vệ biểu thức từ bản có case trước lowercase, thêm alias Greek/spelling/units; `chunk_text` nộp hydrate từ child nguồn và kiểm hash. NFKC không tự đổi Traditional/Simplified, OpenCC xử lý trên bản index. Không bật mapping Roman numeral toàn văn; cần asset/quy tắc ngữ cảnh được kiểm chứng riêng.

BTC normalize NFKC → html.unescape → lower → collapse whitespace → strip → split whitespace. Same query/doc_id, chunk đúng khi `5*LCS_tokens(c,g)>=2*len(g)`. Precision đếm prediction khớp ít nhất một reference; Recall đếm reference được phủ ít nhất một lần, matching nhiều–nhiều. Macro F2 là trung bình F2 từng query. Không dùng Jieba/Underthesea thay tokenizer BTC. CJK không có whitespace có thể mất LCS dù prediction chứa substring đúng; BM25 không tự sửa lỗi phân đoạn nguồn đó.

Không tự giả định trọng số điểm tổng giữa document/chunk. Không nộp toàn bộ tập ứng viên rộng vì sẽ làm giảm Precision/F2. Không chấm điểm nếu không có nhãn độc lập được phép dùng.

## 4. Kiến trúc

```text
source shards → validate identity → pointer registry → analyzers index mode
             → staged multi-field JSONL → 6 Lucene indexes (doc/chunk × vi/en/zh)
query → case/protected entities → concept/alias matching → optional translation cache
      → analyzers query mode → independent language/channel searches
      → union + rank fusion → bounded candidates JSONL → later reranker
      → separate explicit submission selector → original text hydration → BTC JSON
```

Schema analyzer hiện hành `medical-no-folded-v1` có năm fields: `contents` (compound), `broad` (VI syllables+2/3 shingles; ZH subwords+character bigram; EN inflection/spelling/surface), `exact` (biomarker/acronym/dose identifiers), `anchors` (verified/local namespaced concepts), `title` (source evidence). Hợp đồng no-folded và rolling build được ghi chi tiết ở [SPEC-no-folded-rolling-staging.md](SPEC-no-folded-rolling-staging.md); tài liệu này supersedes thiết kế `folded` bên dưới cho runtime mới.

Build/query đều pretokenized WhitespaceAnalyzer. Asymmetry có chủ đích: `index_mode` tạo broad variants nhiều hơn; `query_mode` chọn các compound/terms có nghĩa và số alternatives hữu hạn. Đây là hợp đồng hai mode, không yêu cầu output index/query giống hệt; phải chứng minh query terms có postings tương ứng khi source cùng khái niệm.

EN: kstem dùng Anserini Krovetz, stopword set rỗng để bảo toàn negation. `ALL`, `WAS`, `MS`, `OR` có thể mơ hồ; giữ token case-aware literal, chỉ grounding khi dictionary có điều kiện/evidence. Không mặc định ALL là leukemia hoặc COLD là COPD chỉ vì viết hoa. Greek aliases bảo toàn microgram, không đổi μg thành mg. Classical plurals là bảng alias audit được. Decompound/prefix chỉ thêm vào broad với whitelist, không bung mọi từ thành hình vị vô hạn.

VI: Underthesea local + dictionary overlay; compound giữ cụm y khoa; broad có âm tiết/shingles còn dấu. `folded` đã bị loại khỏi runtime theo profile no-folded; vì vậy query không dấu không còn kênh rescue đảm bảo. Thuật ngữ/viết tắt mở rộng ở kênh alias, không thay query nguồn hoặc xóa intent.

ZH: Jieba tokenizer riêng + medical dictionary, precise cho compound/query, `cut_for_search` + bigrams cho broad index. OpenCC conversion trước segmentation trên copy, giữ source. Không query bằng tất cả chữ đơn; tên vị thuốc một chữ chỉ dùng khi dictionary xác nhận.

Shared anchors: importer chấp nhận entry `concept_id`, `labels{vi,en,zh}`, `aliases`, `source`, `license`, `type`, optional `case_sensitive`. Starter entries là **local concept IDs**, không được quảng bá là UMLS/MeSH đầy đủ. Cần nguồn cấp phép để đạt vocabulary coverage production. Regex trích international symbol đưa vào namespace literal, không thành disease CUI. Entity linking ambiguous là alternative mềm, không hard filter.

Negation/hypothetical/history: giữ terms và evidence metadata, không thay hoàn toàn body bằng `neg_...`; “rule out” là nghi ngờ/cần loại trừ, không phải khẳng định âm tính. Semantic assertion tagging đầy đủ là adapter riêng cần resources/tests, không hard filter candidate theo rule thô.

## 5. Query và ứng viên

Query channels: original Vietnamese, medical aliases mỗi ngôn ngữ, exact international symbols, anchors, optional full-query EN/ZH translation. Adapter cache JSONL độc lập qrels; entry query/source hash, translations, model/revision/provenance. Khi không có bản dịch, thông báo coverage limited ngoài lexicon, không tuyên bố đã dịch hoàn chỉnh. Không gọi closed APIs; model adapter tương lai phải ≤15B, trước 01/08/2026.

Candidate defaults (để đo, không gọi tối ưu): mỗi language/channel 300 document và 1000 chunk; tối đa fused 1000 document/3000 chunk. Không ngưỡng relevance cố định, không hard per-doc cap; có thể bật cap mềm cho tài liệu chiếm quá nhiều ngân sách sau khi có đánh giá độc lập. RRF rank=1-based,k=60; normalize tổng contribution weights theo language để language nhiều channels không tự có lợi thế. Lưu raw BM25/rank/channel score trước fusion.

Doc candidates là union full-doc search và chunk-collapse (best evidence/doc, không cộng mọi chunk). Chunk candidates là union global chunk search và bounded lookup các chunk trong doc candidates nếu mở option sau này; mặc định không đóng cổng chunk bằng top-doc. Canonical-ID dedup, không loại toàn bộ overlapping child vì có thể phủ reference khác nhau. Quota chỉ bảo vệ cơ hội trước reranker, không ép kết quả cuối phải có mọi ngôn ngữ.

Output candidate một JSONL/query: `id`, `query`, `documents[{doc_id,rank,fusion_score,evidence}]`, `chunks[{chunk_id,doc_id,chunk_order,rank,fusion_score,evidence}]`, warnings và timings. Không nhồi nguyên văn của hàng nghìn chunks vào candidate file mặc định: reranker dùng `TextStore.get_many` khi cần. Đây là internal API mới, khác submission BTC.

BM25 khởi đầu k1=0.8,b=0.4 theo giả thuyết từ tài liệu dán, nhưng giữ configuration và baseline k1=1.2,b=0.75 để ablation. Các khoảng theo EMR/article chỉ là search grid, không suy corpus hỏi đáp/cẩm nang là EMR. Hiện cấu hình k1/b chung cho doc/chunk trong một backend bất biến; có thể tách backend config khi có ablation độc lập, không reindex để thay search parameters. Không dùng b thấp như bảo đảm Recall tăng.

## 6. Storage và Big Data

Pointer store SQLite trên đĩa: source shard path/hash, document byte offset/length/record hash, canonical chunk metadata/text hash. Offset file là byte, offset source text là char. Hydration seek đúng JSONL record, validate root/child ID/order/hash, LRU bounded byte budget. Không copy 20+ GB metadata vào Lucene storeRaw.

Doc body dựng union child source intervals theo thứ tự để overlap không nhân TF. Verify overlap text khớp; gap source không biết chỉ được separator trong index, không xuất làm verbatim. Status failed/empty/noneligible audit; `uncertain_format` không drop.

Prepare stream theo shard, metadata transaction mỗi shard, staged output atomic. Manifest gồm file SHA256, lexicon/analyzer/resource versions, code fingerprint, whitelist hash, counters và phase status. Resume chỉ task đã committed đúng hashes; unfinished owned temporary artifact được rebuild, không blind append index. Chống hai writer bằng lock. Mỗi language index chứa global stats partition, không naive cộng raw scores của independent small indexes.

Lucene xây từng partition vào `.building`, close/validate/publish rồi mark done; không overwrite snapshot đang có. Tiết kiệm disk: không raw/docvectors/positions khi query bag-of-words; staging field-only; preflight dựa measured test20k bytes/terms + merge scratch + 30% headroom, không đoán từ kích thước JSON metadata.

Batch search reopen indexes một lần/job, query cache bounded, streaming output, hydrate sau fusion, JVM/Python RAM giới hạn. Java calls qua PyJNIus được khóa process-wide do shared receiver descriptor; các threads trong một process không tăng concurrency search thật. Scale thêm cần process/JVM workers có memory budget, chưa triển khai trong bản này. Cấu hình CPU/thread/batch là tổng budget, tránh nhân 6 index × tất cả workers. Hàng nghìn queries không tạo list corpus hoặc giant output JSON trong memory.

## 7. OOP

`Lexicon`/`MedicalAnalyzer`/`QueryProjector`/`CorpusPreparer`/`LuceneBackend`/`CandidateEngine`/`TextStore` tách responsibilities. Dataclass `Analysis`/`Hit` giữ fields rõ. Custom backend/analyzer/projector có thể thay bằng dependency injection; engine không đọc labels. Entry points `python -m sbtc.Scripts.Retrieval.cli` và configs TOML. Archive cũ không nằm trong import graph.

Errors config/mapping/source changed/hash/index chưa done làm job fail, không biến thành list rỗng thành công. Empty query hợp lệ → zero candidates. Unexpected query failure giữ error log và không finalize submission đầy đủ giả. Resource extension thiếu asset/license phải báo rõ, không tạo bản dịch hoặc mã giả.

## 8. Kiểm chứng

Meaningful tests: protected biomarker trước lowercase; μg khác mg; arbitrary acronym không disease-map; compound/subphrase matches postings; index/query modes; CJK bigram không across punctuation; VI folding rescue; anchors đa ngữ namespace đúng; doc overlap de-dup TF; non-contiguous gap không output; status skip; pointer fidelity; resume/source mutation; batch/single parity; candidate quota/dedup; exact BTC macro/LCS boundary nếu evaluator triển khai.

Corpus test chỉ test20k/derived shards. Mechanical fixtures lấy source record và ví dụ trong yêu cầu để test luật tokenizer, không đọc `for_valid`. Run candidate queries minh họa không phải báo cáo Recall/F2 thật; coverage cần independent qrels tương lai, không invent metrics. CJK LCS bảo toàn là prerequisite upstream cần report riêng.

Mục tiêu performance cần đo: process memory bounded, no O(N corpus) per query, ≥1000 queries batch chạy cùng API; tokens/index stats/file counts reconcile. Translation cold/cached latency báo riêng; <80ms chưa được chứng minh.

## 9. Tài liệu chính thức và điểm cần xác minh

- [Jieba](https://github.com/fxsjy/jieba): precise/search mode, user dictionary.
- [Pyserini custom index](https://github.com/castorini/pyserini/blob/pyserini-2.4.0/docs/usage-index.md): field JSONL, pretokenized + Whitespace query analyzer.
- [Synonym graph](https://www.elastic.co/docs/reference/text-analysis/analysis-synonym-graph-tokenfilter): token graphs khác flat token strings.
- [DisMax](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-dis-max-query): max + tie-break contribution, không calibration partition score.
- [THUOCL](https://github.com/thunlp/THUOCL): tài nguyên nguồn cần review giấy phép trước đóng gói; không giả định mọi nguồn y khoa là public-domain.
- BTC: `sbtc/asked.md` + công thức người dùng. Trang leaderboard không truy cập được trong lần đối chiếu này.

Full production còn cần dictionaries đủ coverage, translation cache/model hợp lệ, capacity estimate full và independent relevance evaluation; core index/candidate search không che những điều chưa xác minh đó.

## 10. Trạng thái triển khai và snapshot thực tế

Code mới và sparse runtime đã chạy actual Lucene; tests 25/25 gồm ba ngôn ngữ/identity/export và evaluator cơ học. Config test dùng snapshot chunk test20k còn lại; raw `data_final/test_20k.jsonl` không tồn tại ở vị trí cũ nên scope ID/URL được dẫn xuất ra artifacts. Không dùng `for_valid`. Các metrics candidate/throughput không phải điểm relevance.

Ngày 15/10/2026, người dùng xác nhận chọn active corpus **1.220.598 URL** làm whitelist cho BM25 full và xuất bài: `newcorpus/links_corpus_vi_en_zh.parquet`, SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`. Index test20k hiện có dùng cùng hash, không cần rebuild vì lựa chọn này. `asked.md`/backup vẫn ghi snapshot 1.194.469/hash9e34...; quyết định người dùng không phải xác nhận BTC đã thay luật. Official leaderboard chưa truy cập được. Giữ 1.320 IDs test20k thuộc whitelist mới nhưng ngoài snapshot cũ.

Adapter local NLLB có offline checksum manifest và eligibility declarations; chưa provision/inference model thật. Chỉ cache API được kiểm thử bằng contract fixtures. Numeric guard là kiểm tra tối thiểu, không chứng minh đúng y khoa/polarity. [HF model card](https://huggingface.co/facebook/nllb-200-distilled-600M) nêu CC-BY-NC, domain tổng quát và giới hạn research; không gọi NLLB là translator y khoa chuẩn. Resource production/dense/reranking/semantic evaluation là các gate riêng.

Bản release test20k đã build đủ six indexes, 20.000 records/19.898 OK/62.941 chunks. Integrity hydrate/hash kiểm toàn bộ 62.941 chunks đạt. Capacity staging/index/SQLite dự phóng full với scratch/headroom cần ~81,8GB free so với ~22,7GB hiện có: disk gate fail; chưa chạy full.
