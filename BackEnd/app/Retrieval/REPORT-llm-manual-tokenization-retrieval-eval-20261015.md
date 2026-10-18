# Báo cáo chẩn đoán LLM manual term spans và retrieval — 2026-10-15

## Kết quả tóm tắt

Đã chạy 100 query tiếng Việt trên index `test20k` hiện hành, sau khi chốt trước 100 mẫu, câu hỏi, qrels known-positive và các span thuật ngữ y khoa thủ công. Analyzer và index không bị sửa hoặc rebuild.

Run này **chưa hoàn tất yêu cầu benchmark full manual tokenization**: annotation bao phủ 962 lượt thuật ngữ y khoa/lâm sàng/mã/liều được chọn thủ công, không phân đoạn hết từng từ phổ thông trong 100 chunk. Không có auditor độc lập và không judge candidate pool. Các điểm bên dưới là chẩn đoán snapshot, không phải điểm BTC hay điểm đại diện toàn corpus.

## Phạm vi và nguồn

- Chunk gốc: `data_final/chunks_format_v3_final/`.
- Mẫu benchmark: 100 chunk từ 100 `doc_id` riêng, cân bằng route language 34 VI / 33 EN / 33 ZH; tất cả được chọn trong giao với index test20k đã `READY`.
- Retrieval index: `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/`, profile `medical-no-folded-v1`, fingerprint `29eba76615874877501c41b2d4aca106a6229f9713e7028aeb85d35cfcc6df7`.
- Câu hỏi: 100 query do LLM tạo bằng tiếng Việt, ID nội bộ `910001–910100`. Mỗi query có một known-positive seed là chính chunk sinh ra câu hỏi; `doc_id`, `chunk_id`, `chunk_order`, nội dung và hash giữ nguyên.
- Không đọc `for_valid/`, không dùng qrels BTC hoặc candidate output để lập/sửa nhãn. Hash của sample/annotation/query/qrels được ghi tại `presearch-freeze.json` trước khi chạy analyzer.
- Model/provider revision không có trong runtime metadata; ghi nhận là annotation do Codex trong phiên hiện tại tạo, revision chính xác `unavailable`. Không có người rà độc lập.

## Kiểm tra toàn vẹn và chạy

- 100/100 record khớp `source_record_sha256`, `source_chunk_sha256`, `doc_id`, `chunk_id`, `chunk_order` và nguyên văn với shard chính thức tại byte offset đã lưu.
- 100/100 chunk khớp nội dung hydrate từ `metadata.sqlite` của index; fingerprint analyzer cục bộ trùng index manifest.
- Analyzer chạy `index_mode=True` trên 100 mẫu, xuất `contents`, `broad`, `exact`, `anchors`; không có field `folded`.
- CandidateEngine chạy trên index `test20k`, không dịch query và không có translation cache. Thời gian tổng 16,644 giây, trung bình 0,166 giây/query (~6,01 query/giây). Mỗi query đều có warning `full_query_translation_missing: EN/ZH coverage limited to available aliases/anchors/literals`.
- Trung bình mỗi query trả 995 document candidates và 1.762 chunk candidates; cấu hình caps là 1.000 docs / 3.000 chunks.
- Candidate output hydrate metadata ngay trong CandidateEngine; sample targets cũng được kiểm tra độc lập với TextStore.

## Đánh giá các span thuật ngữ qua analyzer

Các số này đánh giá **bảo toàn chuỗi thuật ngữ đã gắn nhãn**, không phải độ chính xác ranh giới từ toàn văn. Chuẩn hóa khi so sánh: NFKC, chữ thường, bỏ khoảng trắng/dấu phân cách để đo chuỗi ký tự; tiếng Trung chuyển phồn thể sang giản thể như analyzer. `atomic` nghĩa là toàn bộ span xuất hiện như một token trong `contents` hoặc `exact`; `continuous` nghĩa là chuỗi ký tự còn nguyên khi nối output `contents`; `broad component recall` kiểm tra âm tiết VI, lexical components EN, và Han bigrams/Latin-number components ZH. Vì phép đo bề mặt bỏ dấu phân cách, nó có thể ghi nhận chuỗi là “liên tục” dù dấu `/` hoặc cấu trúc liều đã mất; không dùng `continuous` làm bằng chứng bảo toàn định dạng liều.

| Route language | Lượt span | Một token nguyên khối | Chuỗi còn liên tục trong `contents` | Thành phần có mặt trong `broad` |
|---|---:|---:|---:|---:|
| VI | 289 | 69,6% | 100,0% | 100,0% |
| EN | 351 | 46,4% | 80,6% | 83,2% |
| ZH | 322 | 58,7% | 99,7% | 98,3% |
| **Tổng** | **962** | **57,5%** | **92,8%** | **94,2%** |

### Nhận xét

- Nhiều thuốc, hoạt chất, acronym, số đo và tên bệnh còn được giữ ở dạng đơn nguyên hoặc `exact`; ví dụ S001 tách `8mg` thành `8` + `mg` trong `contents`, nhưng giữ `8mg` và `48mg` trong `exact`. Tuy nhiên, giữ từng liều riêng không đảm bảo giữ đúng cấu trúc tỷ lệ/liều ghép.
- Ngôn ngữ Việt và Trung giữ được gần như toàn bộ chuỗi ký tự của các span đã gắn nhãn; `broad` giữ đủ các thành phần ở mẫu VI và gần đủ ở mẫu ZH. Điều này hữu ích cho candidate generation, nhưng **không chứng minh** ranh giới `contents` là ngôn ngữ học tối ưu.
- EN có mức bảo toàn bề mặt thấp hơn. Krovetz stemming làm thay đổi một số dạng như số nhiều/biến tố; do đó `continuous` có thể phạt stemming hợp lệ và không được diễn giải trực tiếp thành mất thuật ngữ. Mặt khác, `broad component recall` EN 83,2% cho thấy cần xem thêm các mẫu bị thiếu trước khi khẳng định độ phủ đủ.
- Tỷ lệ atomic thấp một phần vì nhiều bệnh danh/thuật ngữ là cụm nhiều từ; việc chúng thành nhiều token không mặc nhiên là lỗi. Bộ nhãn không có toàn bộ segmentation hoặc accepted alternatives để chấm boundary precision/recall/F1.

### Ví dụ lỗi thực tế quan sát được

- S001: dose `8mg` được tách thành hai token trong `contents`; bản nguyên khối có trong `exact`, là hành vi có thể chấp nhận khi query có exact literal.
- S007: `exact` giữ `40mg/ml`, nhưng `500 mg/2 ml` bị tách thành `500mg` + `2ml`; cấu trúc liều ghép không còn nguyên. Analyzer còn sinh token phụ `mg/2`, `mg2`. Phép đo `continuous` bỏ dấu phân cách nên không phát hiện được lỗi cấu trúc này; đây là nhiễu/loss literal cần audit riêng trước khi dùng `exact` làm kênh xếp hạng mạnh.
- S093: văn bản tiếng Nhật bị gắn route ZH. Jieba cho nhiều mảnh một ký tự như `ア`, `ト`, `ピ`, `ー`; đây là lỗi mismatch ngôn ngữ/format của mẫu, không phải bằng chứng đánh giá tokenizer tiếng Trung.
- S069: nguồn có khoảng trắng bất thường bên trong `糖尿 病`; analyzer sinh các mảnh `糖尿`, `病人`, `病`. Đây là distortion của text đầu vào và làm giảm tính nhất quán của cụm bệnh.

## Retrieval known-positive

Đây là tỷ lệ seed target xuất hiện trong top K và MRR trên 100 query. Mỗi query chỉ có một seed positive nên `Hit@K` bằng seed-target Recall@K; không thể suy ra Precision, đầy đủ Recall trên corpus hoặc BTC F2.

| Route language | Queries | Doc Hit@10 | Doc Hit@50 | Doc MRR | Chunk Hit@20 | Chunk Hit@100 | Chunk MRR |
|---|---:|---:|---:|---:|---:|---:|---:|
| VI | 34 | 85,3% | 97,1% | 0,737 | 88,2% | 94,1% | 0,652 |
| EN | 33 | 24,2% | 33,3% | 0,183 | 18,2% | 24,2% | 0,056 |
| ZH | 33 | 3,0% | 3,0% | 0,031 | 3,0% | 3,0% | 0,004 |
| **Tổng** | **100** | **38,0%** | **45,0%** | **0,321** | **37,0%** | **41,0%** | **0,241** |

### Truy vết một query tiếng Trung bị trượt: S068

- Query tiếng Việt: “Phụ nữ bị tử cung phát triển kém được khuyên chú ý gì về ăn uống và sinh hoạt trong giai đoạn phát triển, và Đông y quy căn nguyên vào đâu?” Đích là doc `3038320`, chunk `3038320:c:11:2979:3289:format-v3`, route/source language ZH.
- `QueryProjector` không tìm được concept anchor (`anchors=()`); run không có translation cache nên phát warning `full_query_translation_missing`. Kết quả projection chỉ có `vi/original-compound` và `vi/original-broad`; không tạo channel EN/ZH cho câu hỏi này.
- CandidateEngine vì vậy chỉ tìm trong partition VI: 1.000 document và 1.654 chunk candidate đều có evidence language `vi`. Doc/chunk đích tiếng Trung không xuất hiện trong candidate set. Top kết quả là các trang tiếng Việt về u xơ tử cung, rối loạn kinh nguyệt và tử cung đôi — cùng chủ đề rộng nhưng không phải bài đích.
- Đối chứng chẩn đoán, không thuộc pipeline benchmark: dùng bản Trung do người viết thủ công `子宫发育不良的女性在发育期应注意哪些饮食和生活习惯？中医认为其病因是什么？`, phân tích bằng cùng `MedicalAnalyzer` và tìm trực tiếp trên cùng partition ZH. Doc đích đứng hạng 1/100 và chunk đích hạng 1/300.
- Ca này chỉ ra nguyên nhân trực tiếp là **thiếu query projection/dịch sang ngôn ngữ tài liệu**: index ZH và analyzer hiện có match được khi nhận query ZH. Đây là phép thử một mẫu, bản dịch được viết dựa trên nội dung đích, nên không phải bằng chứng tổng quát rằng dịch query sẽ đưa mọi query ZH lên hạng cao.

### Ảnh hưởng của format và ngôn ngữ

| Profile | n | Doc Hit@10 | Doc Hit@50 | Chunk Hit@20 | Chunk Hit@100 |
|---|---:|---:|---:|---:|---:|
| `disease_drug_catalogue` | 18 | 50,0% | 55,6% | 50,0% | 50,0% |
| `generic` | 2 | 50,0% | 100,0% | 100,0% | 100,0% |
| `narrative_article` | 35 | 62,9% | 68,6% | 51,4% | 57,1% |
| `qa` | 8 | 12,5% | 12,5% | 12,5% | 12,5% |
| `research_abstract` | 30 | 16,7% | 23,3% | 20,0% | 26,7% |
| `structured_list` | 1 | 0,0% | 100,0% | 100,0% | 100,0% |
| `tcm_book` | 6 | 0,0% | 0,0% | 0,0% | 0,0% |

Các profile bị lệch theo ngôn ngữ trong mẫu này: phần lớn `research_abstract`, `qa` và `tcm_book` có route EN/ZH nhưng query vẫn là tiếng Việt, trong khi chưa có translation cache. Cỡ mẫu `generic`/`structured_list` nhỏ. Không kết luận format đó tự thân kém.

### Ca minh họa

- S001, query tiếng Việt → VI: document/chunk đích đều hạng 1.
- S048, query tiếng Việt về abstract tiếng Anh: document hạng 131, chunk hạng 173; nằm ngoài các cutoff report, dù còn trong candidate pool.
- S069, query tiếng Việt về trang bệnh tiểu đường tiếng Trung: document hạng 66, chunk đích không có trong top 3.000.
- S070, query có tên thuốc `Indapamide` nhưng không có bản dịch/alias tương ứng: document hạng 886, chunk hạng 1.978.
- S042 (EN) và S086 (ZH): seed target không có trong 1.000 doc / 3.000 chunk candidates.
- S038: văn bản quan sát được là tiếng Việt nhưng route là EN; target document hạng 1 còn target chunk không xuất hiện. S035 cũng là văn bản VI trộn EN với route EN, document hạng 1 nhưng chunk đích vắng. Đây là dấu hiệu cần kiểm tra view/routing theo chunk.
- S093: chunk tiếng Nhật route ZH, query tiếng Việt; target vắng. Không gộp ca này thành lỗi tìm tiếng Trung.

## Giới hạn và kết luận

1. Đây là pseudo-gold từ một LLM trong cùng phiên, không có auditor độc lập hoặc chuyên gia y khoa phê duyệt. LLM revision cụ thể không được runtime cung cấp.
2. Annotation chỉ gắn spans y khoa/lâm sàng/mã/liều được chọn thủ công; chưa cắt toàn bộ 100 chunk thành token. Vì vậy chưa có boundary precision/recall/F1 và chưa hoàn tất trọn vẹn protocol “manual tokenization” đã mô tả trong spec.
3. Query được tạo từ chính chunk đích; dù được viết thành câu hỏi, tập này có nguy cơ dễ hơn query độc lập. Qrels chỉ có 1 positive seed/query, candidate chưa được judge không phải negative.
4. Không tạo pooled judgments; không báo Precision, Recall đầy đủ hay F2. Không gọi bất kỳ kết quả nào là điểm BTC.
5. Kết quả cho thấy analyzer có giữ bề mặt VI/ZH tốt trên các span được chọn, nhưng EN cần audit thêm; retrieval same-language VI hoạt động tốt trên seed, còn cross-language rất yếu vì cả 100 query đều thiếu full translation. Các trường hợp route/content mismatch cũng làm chunk retrieval hụt dù document được tìm thấy.

**Kết luận dùng thực tế:** benchmark này đủ để phát hiện ưu tiên kỹ thuật (translation coverage, route/content language mismatch, và literal-noise ở dose fields), nhưng **chưa đủ làm căn cứ định lượng cuối cùng để chọn tokenizer hoặc tuyên bố chất lượng retrieval trên full corpus**. Trước khi thay analyzer nên bổ sung một đợt độc lập có segmentation đầy đủ, reviewer độc lập và judged pool cho một cutoff cố định.

## Artifacts

Tất cả nằm tại `artifacts/retrieval/llm-manual-eval-20261015/`: `preview.jsonl`, `samples.jsonl`, `manual-label-inputs.jsonl`, `annotations.jsonl`, `queries.jsonl`, `qrels.json`, `presearch-freeze.json`, `analyzer-output.jsonl`, `candidates.jsonl`, `candidates.jsonl.report.json`, `term-audit.jsonl`, `term-metrics.json`, `retrieval-target-ranks.jsonl`, `retrieval-metrics.json`, `representative-ranks.jsonl`, `manifest.json`.

Không ghi `judgments.jsonl` vì chưa thực hiện pooled blind judging.
