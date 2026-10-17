# Đặc tả: Bộ đánh giá tách từ và truy hồi bằng nhãn LLM trên chunk chính thức

**Trạng thái:** Bản nháp chờ duyệt. Lượt này chỉ ghi đặc tả; chưa đọc nội dung mẫu, chưa chọn chunk, chưa tạo query/nhãn và chưa chạy retrieval.

## 1. Mục tiêu

Tạo một bộ đánh giá nội bộ khoảng 100 chunk tiếng Việt, Anh và Trung. LLM đọc từng chunk và tự lập cách phân đoạn từ y khoa làm nhãn tham chiếu; bộ analyzer hiện hành được chạy sau đó để so sánh. Từ cùng các chunk, LLM viết query tiếng Việt và ánh xạ đáp án về nội dung nguồn nguyên bản. Cuối cùng chạy CandidateEngine hiện tại và đo xem tài liệu/chunk đích có được đưa vào danh sách ứng viên ở thứ hạng nào.

Bộ này dùng để tìm lỗi tách từ và kiểm tra candidate recall. Đây là **LLM-annotated diagnostic set**, không phải nhãn chính thức của BTC và không được trình bày như điểm F2 cuộc thi.

## 2. Giả định về dữ liệu và phạm vi

- Bộ chunk nguồn chính thức: `data_final/chunks_format_v3_final/`.
- Index BM25 hiện có để chạy retrieval: `artifacts/retrieval/no-folded-rolling-test20k-after-regex-fix/`, profile `medical-no-folded-v1`, được dựng từ `data_final/chunks_format_v3_r3_reserve_test20k/`. Index này chỉ bao phủ test20k.
- Để mỗi đáp án đích thực sự có trong index hiện tại, mẫu 100 chunk sẽ lấy từ bộ chunk chính thức **sau khi giới hạn vào các `doc_id` và `chunk_id` có trong snapshot test20k hiện hành**. Nếu không tìm đủ mẫu cân bằng trong phần giao này, phải báo số lượng thực tế và xin quyết định trước khi mở rộng phạm vi hoặc dựng index khác.
- Query do BTC phát hành là tiếng Việt theo `sbtc/asked.md`; query thử nghiệm cũng được viết bằng tiếng Việt, kể cả khi chunk đích là tiếng Anh hoặc Trung.
- Không dùng `for_valid/`, nhãn/đáp án BTC, hay output analyzer để tạo hoặc sửa nhãn tham chiếu.
- Không thay đổi chunk nguồn, corpus, index hiện tại, resource, analyzer, CandidateEngine hoặc định dạng nộp bài. Chỉ tạo artifact dẫn xuất riêng.

## 3. Quy tắc lấy mẫu

### 3.1 Quy mô và cân bằng

- Mục tiêu 100 chunk từ 100 tài liệu khác nhau, tối đa một chunk mỗi `doc_id` để giảm tương quan giữa mẫu.
- Phân bổ ngôn ngữ: 34 tiếng Việt, 33 tiếng Anh, 33 tiếng Trung. Nếu corpus/index không đủ một nhóm, không bù âm thầm bằng ngôn ngữ khác; ghi rõ count và chờ duyệt phương án.
- Trong từng ngôn ngữ, chia mẫu theo nhóm độ dài ngắn/vừa/dài và format trang có trong dữ liệu. Ưu tiên giữ các format thực sự phổ biến; vẫn lấy một số trường hợp ít phổ biến như hỏi–đáp, danh sách/hướng dẫn, bài viết tường thuật, nội dung dạng catalogue hoặc abstract nếu có.
- Dùng lấy mẫu ngẫu nhiên có seed cố định trong từng strata. Seed, tập ID đủ điều kiện, số lượng từng strata và cách chọn phải được ghi để tái tạo. Cách lấy mẫu chỉ chọn bản ghi; **không tạo segmentation bằng regex, từ điển hay thuật toán**.
- Nếu chunk có nhiều ngôn ngữ, giữ nhãn `content_languages` gốc; chọn một `evaluation_language` theo metadata nguồn và ghi rõ chunk đó là mixed. Không ép mẩu mixed thành ví dụ đơn ngữ.

### 3.2 Cổng duyệt trước khi đọc/ghi artifact

Trước khi LLM đọc nội dung hoặc tạo bản dẫn xuất, phải xuất danh sách preview để người dùng xem, gồm:

- đường dẫn shard và số dòng/byte offset;
- `doc_id`, `chunk_id`, `chunk_order`, ngôn ngữ, format, độ dài;
- SHA-256 của nội dung và một trích đoạn đủ để nhận diện mẫu;
- thư mục artifact dự kiến và các file sẽ được tạo.

Chỉ sau khi người dùng duyệt danh sách mẫu cụ thể mới tiến hành annotation. Source files luôn read-only. Nếu duyệt mẫu rồi nhưng phát hiện bản ghi lỗi/không phù hợp, ghi lý do và xin duyệt bản thay thế cùng strata; không âm thầm đổi mẫu.

## 4. Quy trình LLM lập nhãn tách từ

### 4.1 Hợp đồng annotation

LLM đọc nguyên văn toàn bộ chunk đã chọn và tự xác định ranh giới từ/cụm y khoa theo ngữ cảnh. LLM không được xem token hoặc kết quả của `MedicalAnalyzer`, không gọi Underthesea/Jieba/Krovetz, không tra từ điển để sinh segmentation và không dùng mã để phân đoạn tự động. Mã chỉ được dùng sau annotation để kiểm tra schema, offsets, so sánh và tính metric.

Annotation chỉ là nhãn đánh giá. Không được ghi segmentation vào `chunk_text`, index, resource hoặc submission. Không dịch, tóm tắt, sửa chính tả hay bổ sung nội dung không có trong chunk.

Vì tiếng Việt/Trung có thể có nhiều ranh giới chấp nhận được, nhãn không áp đặt một tokenization duy nhất cho mọi trường hợp. LLM phải ghi biến thể hợp lệ cho span mơ hồ; cụm từ y khoa, mã, gene, thuốc và liều được đánh dấu riêng để chấm bảo toàn thuật ngữ.

### 4.2 Hai lượt kiểm tra mù

1. **Annotator LLM:** chỉ nhận văn bản nguồn, ngôn ngữ và yêu cầu JSON; tạo segmentation, span thực thể, ghi chú mơ hồ và độ tin cậy. Không thấy analyzer output hoặc truy vấn/kết quả search.
2. **Auditor LLM:** nhận lại text và annotation đã xáo thứ tự, không thấy tên phiên bản analyzer hoặc kết quả retrieval. Kiểm tra token có thật trong nguồn, ranh giới gây mất nghĩa, mã/liều bị tách sai và span bị bỏ sót. Mọi bất đồng được lưu lại; nếu chưa giải quyết được thì đánh dấu `uncertain`, không tự chọn đáp án tiện cho analyzer.

Hai lượt bằng cùng một model vẫn không được gọi là đánh giá độc lập. Report phải ghi provider/model/revision nếu biết, ngày, prompt version và giới hạn của nhãn LLM. Nếu không thể xác định chính xác model revision, ghi `unavailable` thay vì đoán.

### 4.3 Định dạng nhãn tách từ

Mỗi dòng `annotations.jsonl` liên kết về sample manifest và có tối thiểu:

```json
{
  "case_id": "S001",
  "doc_id": 123,
  "chunk_id": "...",
  "language": "vi",
  "segments": [
    {"surface": "suy thận mạn", "start_char": 120, "end_char": 132, "role": "medical_term"}
  ],
  "entities": [
    {"surface": "500 mg", "start_char": 210, "end_char": 216, "type": "dose", "must_preserve": true}
  ],
  "acceptable_segmentations": [],
  "ambiguous_spans": [],
  "confidence": "high",
  "auditor_status": "accepted"
}
```

Offsets là chỉ số ký tự Python trên đúng `chunk_text` nguồn; `surface` phải khớp chính xác với `text[start_char:end_char]`. `role`/`type` tối thiểu bao gồm: từ chức năng, thuật ngữ bệnh/triệu chứng, thuốc/hoạt chất, thủ thuật, gene/biomarker, mã phân loại, số-liều-đơn vị, phủ định và ký hiệu khác. Các từ chưa chắc là thuật ngữ phải để `uncertain`, không ép vào medical entity.

Validation code chỉ báo lỗi offset/span/schema và yêu cầu LLM sửa annotation; code không tự tách hoặc nhập token. Bất kỳ sửa thủ công nào cũng ghi người sửa, lý do, thời gian và hash trước/sau.

## 5. Tạo query và đáp án tham chiếu

### 5.1 Query

- Tạo một query tiếng Việt tự nhiên cho mỗi sample chunk được duyệt, tối đa 100 query.
- Query phải hỏi một thông tin thực sự được nêu trong chunk và có thể được trả lời từ chunk; không suy thêm chẩn đoán, phác đồ hoặc quan hệ nhân quả ngoài nguồn.
- Với chunk tiếng Anh/Trung, LLM diễn đạt câu hỏi tiếng Việt dựa trên nội dung. Đây là bài kiểm tra cross-lingual của code retrieval; query không phải bản dịch toàn văn.
- Dùng nhiều kiểu hỏi phù hợp dữ liệu: bệnh/triệu chứng, điều trị, thuốc/liều, định nghĩa, nguy cơ/biến chứng hoặc thông tin nghiên cứu. Không ép một kiểu cho tất cả format.
- Query writer không được thấy analyzer output, candidate list hoặc kết quả hiện tại. Một lượt auditor khác kiểm tra tính trả lời được, không nhập nhằng, không chứa tiền đề sai và không sao chép nguyên đoạn dài làm query.
- Query thiếu căn cứ, quá mơ hồ hoặc có nhiều cách hiểu không phân biệt được với chunk đích sẽ bị loại và thay bằng một sample khác trong cùng strata theo cổng duyệt §3.2; mọi loại/bổ sung đều có lý do.

### 5.2 Đáp án và qrels

LLM không được viết lại câu trả lời để đưa vào `chunk_text`. Đáp án máy đọc được được tạo từ record nguồn đã chọn:

- `relevant_docs`: chứa `doc_id` gốc của chunk đích;
- `relevant_chunks`: chứa đúng `doc_id`, `chunk_order` và `chunk_text` byte-for-byte như nguồn;
- `query_id`: số nguyên riêng trong test nội bộ, không ghép vào 1.200 query BTC;
- `case_id`: liên kết với annotation và source manifest.

Ban đầu mỗi query có một positive “seed” là tài liệu/chunk nguồn đã sinh ra câu hỏi. Đây là **known-positive qrels**, không chứng minh mọi tài liệu/chunk liên quan trong kho đã được gán nhãn. Candidate khác chỉ được thêm là positive sau khi LLM auditor đọc bằng chứng nguồn và xác nhận trực tiếp; nội dung không đủ bằng chứng được gắn `uncertain`, không tính là negative.

## 6. Chạy analyzer và retrieval hiện hành

1. Đóng băng `samples.jsonl`, `annotations.jsonl`, `queries.jsonl`, `qrels.json` và hash của chúng trước khi chạy analyzer/search.
2. Chạy profile `medical-no-folded-v1` với cùng `Lexicon` fingerprint như index đã `READY`. Ghi đủ `contents`, `broad`, `exact`, `anchors`; profile hiện không có field `folded`.
3. Chạy `MedicalAnalyzer` trên 100 chunk ở `index_mode=True`. Không sửa code/resource/lexicon sau khi xem mismatch; mọi thử nghiệm sửa sau này phải dùng phiên bản benchmark hoặc holdout mới.
4. Chạy query qua `QueryProjector` và `CandidateEngine` trên index `test20k` hiện hành, không rebuild full. Ghi query warnings, candidates, rank, channel, `doc_id`, `chunk_id`, `chunk_order`; hydrate nội dung bằng `TextStore` và kiểm tra hash.
5. Kết quả chỉ đánh giá behavior của snapshot test20k và query do LLM tạo. Không suy rộng thành hiệu năng trên full corpus hoặc 1.200 query BTC.

## 7. Metric và cách diễn giải

### 7.1 Chất lượng tách từ

Báo riêng cho VI/EN/ZH, format và nhóm thực thể:

- **Boundary precision/recall/F1** trên lexical spans của `contents`, tính với các segmentation được auditor chấp nhận. Casing/Unicode chuẩn hóa để so sánh; phép chuẩn hóa không được thay đổi nhãn hoặc source text.
- **Medical-term preservation**: tỷ lệ entity span được giữ nguyên hoặc có dạng chuẩn hóa được chấp thuận; báo riêng bệnh/thuốc, acronym, mã, gene/biomarker, liều/đơn vị.
- **Over-splitting**: số entity cần nguyên khối nhưng bị tách; **under-splitting**: các từ độc lập bị gộp làm mất khả năng khớp.
- **Broad coverage**: tỷ lệ subterm/token tham chiếu quan trọng xuất hiện trong `broad`, cùng tỷ lệ token ngoài gold/approved variants. Không coi mọi token broad thêm là lỗi vì trường này chủ ý mở rộng recall.
- **Anchor audit**: chỉ chấm đúng/sai cho concept có mapping/provenance được auditor xác nhận; không xem vắng anchor là lỗi segmentation.

`contents` và `broad` có nhiệm vụ khác nhau; không gộp thành một token score. Công bố số mẫu và khoảng tin cậy/độ biến động phù hợp với mẫu nhỏ; không xếp hạng ngôn ngữ chỉ bằng tổng điểm.

### 7.2 Retrieval

- **Chỉ số chắc chắn trên known positives:** seed document/chunk Hit@K, Recall@K trên seed targets, MRR và median rank ở các cutoff cố định. Cutoff đề nghị: docs `10/20/50`, chunks `20/40/100`, đồng thời ghi max candidate budget đang dùng.
- **Đánh giá relevance trong pool:** LLM auditor blind chấm toàn bộ document/chunk nằm trong cutoff đã chọn, xem query + title/bằng chứng nội dung nguồn, không xem rank/engine/channel. Ghi nhãn `relevant`, `not_relevant`, `uncertain` và evidence span. Chỉ tính P@K trên các candidate đã phán quyết; báo riêng tỷ lệ uncertain.
- Nếu tạo được pool qrels đủ judged, có thể tính P/R/F2 macro bằng evaluator BTC hiện có trên **pool đã xét**. Gắn nhãn rõ `pooled diagnostic F2`, không gọi là BTC F2; tài liệu/chunk liên quan ngoài pool chưa được phán quyết nên recall toàn corpus chưa biết.
- Không dùng Precision/F2 trên một positive seed duy nhất làm điểm chất lượng chính. Không xem candidate chưa được judge là negative.
- Luôn tách metric retrieval theo ngôn ngữ nguồn của chunk đích, format, query style và có/không có mã/thuốc/liều; report cả kết quả có warning và không warning.

### 7.3 Giới hạn ngoại suy

100 query tự tạo từ 100 chunk tạo thành benchmark chẩn đoán có chủ đích, không phải test độc lập đại diện toàn bộ corpus. LLM có thể tạo câu hỏi dễ, lặp lại cách diễn đạt trong nguồn hoặc mắc sai sót y khoa; ngôn ngữ/chuyên khoa/format hiếm có thể thiếu. Mọi bảng điểm phải ghi rõ các giới hạn này.

## 8. Artifact dự kiến

Tất cả artifact mới nằm trong một thư mục run riêng, không ghi đè snapshot đã có:

```text
artifacts/retrieval/llm-manual-eval-20261015/
  preview.jsonl                 # chỉ sau khi được phép lập mẫu
  samples.jsonl                 # source snapshots + hashes, nguyên văn
  annotations.jsonl             # LLM segmentation + audit
  queries.jsonl                 # <=100 Vietnamese queries
  qrels.json                     # exact seed positives + audited pool labels
  analyzer-output.jsonl          # output từng field của analyzer hiện hành
  candidates.jsonl              # current CandidateEngine output
  judgments.jsonl               # blind pooled judgments
  manifest.json                  # source/index/query/lexicon/LLM hashes
  REPORT.md                      # metrics, ví dụ lỗi, giới hạn
```

`preview.jsonl` được tạo trước artifact còn lại. Không sửa/xóa `data_final/chunks_format_v3_final/`, test20k source shards, candidate snapshot hoặc index hiện tại. `chunk_text` trong qrels phải được copy nguyên văn từ source, không lấy từ LLM.

## 9. Kế hoạch thực hiện sau khi đặc tả được duyệt

1. **Inventory read-only:** xác nhận shard schema, index snapshot `READY`, source/index intersection, phân bố ngôn ngữ/format/độ dài; tạo deterministic preview cho khoảng 100 sample.
2. **Duyệt sample:** trình người dùng danh sách chính xác `doc_id`/`chunk_id`/shard/offset/hash/trích đoạn và thư mục artifact dự kiến; chỉ tiến hành annotation sau khi được xác nhận.
3. **Tạo sample snapshot:** sao chép đúng 100 chunk sang run artifact, giữ ID, thứ tự, nội dung, source pointer và hash; kiểm tra đối chiếu nguồn.
4. **LLM segmentation:** annotator tạo token spans/entities/alternatives; auditor rà mù; sửa schema/offset bằng vòng LLM có audit trail. Đóng băng và hash labels.
5. **LLM query/qrels:** tạo 1 query tiếng Việt/chunk; auditor kiểm tra độ rõ và căn cứ; sinh seed qrels từ nguồn chính xác; đóng băng/hash.
6. **Analyzer evaluation:** chạy profile hiện tại sau khi gold đã khóa; tính metrics từng field/ngôn ngữ/format và xuất các mismatch có ví dụ.
7. **Retrieval evaluation:** chạy 100 query trên index hiện có; map candidates về source texts, judge pool mù, tính target retrieval metrics và pooled metrics nếu đủ phán quyết.
8. **Report/review:** ghi dữ liệu, hash, lệnh, môi trường, giới hạn và quyết định tiếp theo. Không sửa analyzer hoặc chọn sample mới sau khi xem điểm trong cùng run.

## 10. Điều kiện hoàn tất

- Có khoảng 100 sample hợp lệ, nguồn không đổi, strata/các thiếu hụt được báo; mọi target có mặt trong index snapshot đang test.
- LLM segmentation bao phủ ba ngôn ngữ, chỉ có token spans khớp source, lưu accepted alternatives/uncertainty và có audit trail.
- Có query tiếng Việt tương ứng từng target được chấp nhận; đáp án chunk/document giữ đúng mapping và nguyên văn.
- Analyzer/search chạy đúng fingerprint snapshot, mọi candidate hydrate được về nguồn; query thất bại hoặc thiếu target không bị bỏ khỏi report.
- Report tách analyzer scores khỏi retrieval scores, known-positive metrics khỏi pooled relevance metrics; không tuyên bố đây là điểm chính thức hay chứng minh chất lượng full corpus.
- Source chunk, index, corpus, lexicon và submission files không bị sửa.

## 11. Rủi ro và đánh đổi

| Rủi ro | Ảnh hưởng | Xử lý |
|---|---|---|
| LLM làm gold cũng mắc lỗi/thiên vị cách cắt riêng | Analyzer tốt có thể bị chấm sai; query có thể dễ hoặc nhập nhằng | Lượt auditor mù, alternatives, uncertainty, source-span validation; gọi nhãn là LLM pseudo-gold |
| 100 mẫu nhỏ và cân bằng nhân tạo | Không ước lượng chính xác phân bố toàn kho | Báo per-language/per-format; ghi population count và trọng số mẫu; không ngoại suy full |
| Full official chunk có tài liệu ngoài test20k index | Đích không thể xuất hiện trong kết quả search hiện tại | Chỉ lấy giao với index; nếu thiếu strata thì dừng hỏi trước khi mở rộng/build |
| Qrels có seed positive nhưng thiếu positives khác | Precision/F2 có thể bị đánh thấp giả hoặc recall cao giả | Chấm target Hit@K/MRR riêng; judge top pool; không tính unseen là negative |
| Query được tạo từ chính chunk đích | Có thể quá khớp từ ngữ của nguồn | Query writer bị mù analyzer/results; tạo câu hỏi paraphrase, audit query specificity và ghi style |
| Candidate budget lớn | Judge pool có thể tốn thời gian/tokens | Khóa cutoff trước khi search; đánh giá mọi kết quả trong cutoff, không đổi cutoff theo kết quả |

## 12. Phê duyệt cần có trước khi chạy

Đặc tả này đề nghị **100 chunk tổng cộng, 34/33/33 theo ngôn ngữ, lấy từ phần giao giữa chunk chính thức và index test20k hiện tại**. Trước khi LLM đọc nội dung, cần duyệt preview chứa đúng các IDs, offsets/hashes/trích đoạn. Sau khi duyệt đặc tả, bước kế tiếp chỉ lập preview read-only; không bắt đầu annotation cho tới khi người dùng duyệt các bản ghi cụ thể theo quy tắc dữ liệu của repo.

