**Đánh giá phương án gán chủ đề ICD-10 cho parent trên dữ liệu hiện tại — 16/10/2026**

**Kết luận:** Phù hợp để phát triển thành lớp metadata hỗ trợ truy hồi. Nên thử nghiệm Aho-Corasick trước, sau đó mới chứng minh giá trị bổ sung của FastText và Qwen teacher. Chưa đủ bằng chứng để gán toàn corpus hoặc dùng nhãn ICD-10 làm điều kiện loại tài liệu. ICD-10 cũng không bao phủ đầy đủ các loại nội dung y sinh đang có trong corpus.

Đây là đánh giá tài liệu thiết kế và khảo sát dữ liệu, không phải kết quả benchmark của một ICD tagger đã huấn luyện. Chưa triển khai tagger, chưa sửa chunk/BM25, chưa chạy model, scorer hoặc test suite.

**1. Bằng chứng đã khảo sát và giới hạn kết luận**

Đã đọc toàn bộ phương án đính kèm “Nghiên cứu và thiết kế hệ thống gán nhãn ICD-10 đa ngôn ngữ cho Parent Chunks”, đối chiếu code chunker, corpus preparer, text store, query projector và candidate engine. Repo đã có [đặc tả taxonomy](SPEC-icd10-taxonomy-and-multilingual-lexicon.md) và [review đặc tả](REVIEW-icd10-taxonomy-and-multilingual-lexicon.md). Hai tài liệu này chưa phải bằng chứng mô hình đã hoạt động tốt. Chưa tìm thấy `artifacts/taxonomy/`, model ICD FastText hay mã MVP `icd_tagger.py`/`train_fasttext.py` trong phạm vi kiểm tra. Tệp ZIP và kết quả “4 tests pass” được nhắc trong nội dung đính kèm không được cung cấp để xác minh.

Số toàn corpus dưới đây lấy từ checkpoint `done: true`; dung lượng và số shard được kiểm kê trực tiếp. Khảo sát độc lập đọc tất cả record trong mỗi shard thứ 20 theo tên đã sắp xếp, cộng shard cuối: **62 shard, 61.598 record**, khoảng **5,05%** tổng record. Đây là mẫu hệ thống theo shard, không phải mẫu ngẫu nhiên; không dùng các tỷ lệ trong mẫu như ước lượng chính xác toàn corpus. Đã đọc ngữ nghĩa các ví dụ được trích trong báo cáo; script chỉ kiểm kê trường dữ liệu, offset, độ dài và chọn mẫu, không gán nhãn ICD hay relevance.

Artifact kiểm tra: [data-profile.json](../../../artifacts/research/icd10-parent-fit-20261016/data-profile.json), [source-examples.jsonl](../../../artifacts/research/icd10-parent-fit-20261016/source-examples.jsonl), [edge-case-examples.jsonl](../../../artifacts/research/icd10-parent-fit-20261016/edge-case-examples.jsonl), [inspection-manifest.json](../../../artifacts/research/icd10-parent-fit-20261016/inspection-manifest.json).

| Chỉ số | Toàn corpus: checkpoint/kiểm kê | Mẫu đọc lại |
|---|---:|---:|
| Shard | 1.221 | 62 |
| Record | 1.220.598 | 61.598 |
| Record `ok` | 1.213.716 | 61.552 |
| Parent | 1.632.801 | 81.749 |
| Child | 4.342.218 | 217.876 |
| Parent `topic: null` | Chưa đếm lại toàn bộ | 81.749 / 81.749 |
| Record `ok` lưu riêng toàn văn source/cleaned text | Chưa đếm lại toàn bộ | 0 / 61.552 ở các trường đã kiểm tra |
| Parent lưu riêng `text`/`parent_text`/`source_text` | Chưa đếm lại toàn bộ | 0 / 81.749 |

Dung lượng shard hiện tại: **23.749.707.225 bytes**, tương đương khoảng 23,75 GB thập phân hoặc 22,12 GiB. Snapshot full đang được cấu hình sử dụng danh sách **1.220.598 URL** trong `configs/full.toml`, phù hợp lựa chọn trước đó của người dùng.

Các profile toàn corpus trong checkpoint: narrative_article **832.198**, research_abstract **240.039**, qa **130.929**, tcm_book **6.039**, disease_drug_catalogue **3.340**, generic **1.170**, structured_list **1**. Đây là nhãn của router hiện tại, không phải nhãn format đã được xác thực thủ công. Ví dụ trong mẫu, một trang giáo dục về tự kỷ đang mang `research_abstract`.

Parent không đồng nhất về độ dài. Median trong mẫu theo profile: narrative **707 units**, abstract **202**, QA **143**, TCM **458**, generic **15**. Parent QA có **2.458/10.833** trường hợp dưới 50 units. `units` là đơn vị của chunker, không đồng nghĩa số token Qwen hoặc số từ giữa ba ngôn ngữ. Không nên chọn một ngưỡng, độ dài tối thiểu hay cấu hình teacher duy nhất từ giả định mọi parent đều là đoạn bệnh học 1.200 từ.

**2. Những phần nên giữ trong phương án**

| Thành phần | Đánh giá theo repo hiện tại | Điều kiện áp dụng |
|---|---|---|
| Taxonomy có version, lexicon tách riêng | Cần thiết | Mã/quan hệ nguồn khác nhau phải có provenance và crosswalk; từ đồng nghĩa không mặc nhiên là mã chẩn đoán |
| Aho-Corasick trên văn bản tự nhiên | Phù hợp | Repo đã dùng `pyahocorasick`; cần ranh giới Latin, nhập nhằng, khớp lồng nhau và ngữ cảnh |
| FastText OVA ở cấp chapter | Baseline hợp lý về chi phí | Nhãn huấn luyện phải xử lý được thiếu positive; đo riêng VI/EN/ZH và từng format |
| Block từ bằng chứng rõ | Hợp lý hơn dự đoán hàng nghìn mã ngay | Cho phép nhiều block hoặc abstain; không ép triệu chứng/thuốc vào một block bệnh |
| Qwen teacher dùng có chọn lọc | Có thể bổ sung ca khó | Model cụ thể hợp lệ theo `asked.md`; quote nguyên văn; đầu ra vẫn là silver |
| Không union toàn bộ nhãn parent đầu | Đúng hướng | Ngữ cảnh tiêu đề/câu hỏi phải lưu riêng với nhãn nội dung cục bộ |
| Nhánh retrieval có metadata song song nhánh nền | Phù hợp mục tiêu Recall | Phải bảo vệ ngân sách ứng viên nền khi fusion/cắt top-K |
| Streaming, checkpoint, `.jsonl.zst` | Phù hợp quy mô | Sidecar metadata theo shard; không sao chép lại toàn bộ văn bản chunk vào output mới |

WHO có bản tải ICD-10 2019 ClaML/tabular và API công bố ICD-10 2019 chỉ có tiếng Anh; không thể giả định API này cung cấp nhãn VI/ZH. [WHO downloads](https://icdcdn.who.int/icd10/index.html), [WHO API languages](https://icd.who.int/icdapi/docs2/SupportedClassifications/).

Đã xác minh tại Cổng Chính phủ: **Thông tư 06/2026/TT-BYT ban hành 02/04/2026, có hiệu lực 01/07/2026**. Dùng danh mục Việt Nam có version là hợp lý. Điều này không có nghĩa phải bỏ tên bệnh lịch sử có trong bài cũ; có thể giữ làm alias có xuất xứ. [Thông tư và phụ lục chính thức](https://chinhphu.vn/?docid=217536&orggroupid=4&pageid=27160).

Nguồn Trung Quốc cần phân biệt **NHC clinical edition** với **NHSA insurance edition**. Nguồn NHC phân biệt disease classification clinical 2.0 với procedure classification 3.0; không được hiểu “3.0” của thủ thuật thành phiên bản ICD-10 bệnh học. Đã tìm được trang cơ quan y tế Phúc Kiến có XLS clinical 2.0, nhưng chưa tải và thẩm định toàn bảng/crosswalk trong task này. [NHC giải thích](https://www.nhc.gov.cn/yzygj/c100067/202204/c335364a5309434cb31a27b1c45dea77.shtml), [nguồn XLS cơ quan y tế](https://wjw.fj.gov.cn/jggk/csxx/yzc/gzdt_33135/202106/t20210603_5607241.htm).

**3. ICD-10 phù hợp đến đâu với các nội dung thực tế?**

**Bệnh và bài giải thích bệnh:** phù hợp nhất ở chapter/block. Ví dụ `doc_id=1458145`, [record nguồn](../../../data_final/chunks_format_v3_final/part-001080.jsonl:124), nói về yếu tố dạng thấp và viêm khớp dạng thấp. Có thể ghi nhận chủ đề bệnh, xét nghiệm và các bệnh được nhắc để phân biệt, nhưng không biến mọi bệnh được kể trong ví dụ thành chủ đề chính.

**Phủ định không đồng nghĩa tài liệu không liên quan.** Cùng record trên có câu `RF阳性，不一定就是类风湿关节炎；RF阴性，也不一定就不是类风湿关节炎。` Nội dung phủ định giá trị khẳng định chẩn đoán, đồng thời trực tiếp giải thích bệnh và xét nghiệm đó. Xóa nhãn chủ đề chỉ vì có phủ định sẽ làm mất một tài liệu hữu ích. Cần phân biệt `topic_relation` (chính/phụ/phân biệt) với `assertion` của mention, thay vì dùng bộ phủ định bệnh nhân để quyết định relevance tài liệu.

**Hỏi đáp:** cần ngữ cảnh câu hỏi nhưng phải giữ nhãn câu trả lời riêng. `doc_id=1101585`, [record nguồn](../../../data_final/chunks_format_v3_final/part-001020.jsonl:1), có bốn parent. Parent trả lời thứ nhất nằm ở `[153,233)`, trong khi `question_span` là `[0,126)` ở ngoài parent. Các câu trả lời không thống nhất về cách mô tả tình trạng được hỏi. Gán nhãn chủ đề không xác nhận lời khuyên điều trị trong đó đúng. Phương án nên đọc `[câu hỏi/tiêu đề] + [câu trả lời cục bộ]` để hiểu tham chiếu, nhưng đánh dấu rõ nguồn bằng chứng cục bộ và contextual prior.

**Thủ thuật/nghiên cứu:** không nên ép về một bệnh. `doc_id=5681393`, [record nguồn](../../../data_final/chunks_format_v3_final/part-000800.jsonl:613), là abstract “Procedural sedation analgesia.”, bàn an thần/giảm đau trong cấp cứu, nha khoa, chẩn đoán hình ảnh và nội soi. `PSA` ở đây là **procedural sedation analgesia**, không phải prostate-specific antigen. Chỉ có từ điển viết tắt và ICD bệnh học sẽ dễ gán nhầm; parent có thể là `non_disease_topic` và vẫn rất hữu ích cho retrieval. Không dùng Chapter XXI như một thùng chứa mọi bài thủ thuật.

**Thuốc/cây thuốc và sức khỏe sinh sản:** `doc_id=564986`, [record nguồn](../../../data_final/chunks_format_v3_final/part-000560.jsonl:79), nói về cây thuốc, kinh nguyệt, tinh trùng và hiếm muộn. Một mã bệnh đơn lẻ không mô tả hết chủ đề. Tên thuốc, xét nghiệm, bộ phận cơ thể và can thiệp nên có facet riêng khi có bằng chứng; không cần xây đầy đủ ontology thứ hai trong MVP.

**Đông y:** `doc_id=4379433`, [record nguồn](../../../data_final/chunks_format_v3_final/part-001220.jsonl:247), bàn `颤证`, có nhắc Parkinson, múa giật, gan/thận theo hệ giải thích Đông y và nhiều bài thuốc. Không có ánh xạ 1-1 an toàn từ chứng Đông y sang một bệnh ICD-10. Đặc biệt, tự gán chương bệnh gan từ từ khóa `肝`/`肝肾阴虚` có thể sai ý nghĩa. Chỉ gán chủ đề Tây y khi có evidence rõ; giữ trạng thái `tcm_context`/`unmapped` cho phần còn lại.

**Thiếu nội dung:** `doc_id=484835`, [record nguồn](../../../data_final/chunks_format_v3_final/part-000480.jsonl:37), chỉ có tiêu đề “6 thực phẩm tốt cho sức khỏe khi thức đêm xem bóng đá”, parent 13 units. Teacher không được bổ sung bệnh giả định để lấp nội dung thiếu. Cần `insufficient_text`, không gán block chỉ từ suy đoán.

**Ngoài y khoa:** `doc_id=465430`, [record nguồn](../../../data_final/chunks_format_v3_final/part-000460.jsonl:632), là tin ViruSs xóa kênh YouTube. Domain sức khỏe và profile narrative không bảo đảm bài có nội dung y khoa. Cần `out_of_scope`; không dùng alias quá ngắn hay khớp một phần tên riêng để suy ra bệnh.

**Proceedings:** record duy nhất `structured_list`, `doc_id=6248072`, [record nguồn](../../../data_final/chunks_format_v3_final/part-000858.jsonl:130), là chương trình hội nghị HIV, có nhiều entry và tên tác giả. Gán chương chủ đề có thể hữu ích, nhưng không biến một danh sách tiêu đề thành các abstract có đầy đủ bằng chứng. Mẫu hệ thống không chứa record này; đã bổ sung kiểm tra riêng theo ID từ audit cũ. Một record không đủ để kết luận chung cho proceedings.

ICD-10 là lớp phân loại bệnh và các vấn đề sức khỏe liên quan, không thay thế toàn bộ chủ đề y sinh. MeSH được NLM dùng để index tài liệu PubMed và có các nhóm thuốc/hóa chất, giải phẫu, kỹ thuật, sinh vật…; đây là căn cứ để chừa chỗ cho facet ngoài bệnh trong hướng phát triển, không phải yêu cầu phải triển khai ngay toàn bộ MeSH. [NLM MeSH](https://www.ncbi.nlm.nih.gov/mesh?cmd=search), [các nhóm MeSH](https://www.ncbi.nlm.nih.gov/mesh/1000048).

**4. Parent text: cần sửa cách tiếp cận so với thiết kế đính kèm**

[format_chunking.py](../Preprocess/format_chunking.py) đang tạo parent với `start_char`, `end_char`, `section_paths`, `content_languages`, `question_span`, `title_span`, `block_role`, `answer_span`, `topic: null`. Văn bản lưu ở child. Offset trỏ vào **source sau `clean_with_report`**, không phải raw HTML hay chuỗi đã NFKC/OpenCC thêm một lần.

Trong mẫu có **48.831/81.749 parent (59,733%)** chứa children overlap. Nối tất cả child bằng khoảng trắng làm lặp nội dung và tăng TF. Repo đã có [corpus.union_body](corpus.py), kiểm tra đoạn overlap khớp nhau và bỏ phần lặp; vì vậy không nên viết lại phép nối đơn giản.

Tuy nhiên, không được gọi mọi output của `union_body` là source slice chính xác: hàm này chèn `\n\n` khi có khoảng trống giữa children. **73.624 parent (90,061%)** trong mẫu được children phủ liên tục toàn span; **8.125 parent (9,939%)** có gap, tổng **9.743 ký tự**. Chưa có source đầy đủ để khẳng định các ký tự gap đều là khoảng trắng. Kết quả này chỉ đánh giá interval coverage, không tự chứng minh mọi byte nguồn đã được kiểm tra.

Nên dùng ba trạng thái rõ ràng:

1. `exact_source_span`: đọc đúng cleaned source và xác nhận `source_sha256` khớp rồi cắt offset.
2. `exact_child_union`: children phủ toàn parent, mọi overlap thống nhất, không tự chèn ký tự.
3. `reconstructed_view`: còn gap, chỉ tạo view phục vụ classifier, ghi số gap/loại phục hồi; không gọi view là văn bản nguyên bản để nộp.

Trong `data_final/` tại lần kiểm tra này không còn đường dẫn `final_data.jsonl` mà các tài liệu cũ nhắc tới; chưa xác minh được bản raw tương ứng còn ở vị trí khác. Vì vậy “cắt trực tiếp từ cleaned_document” là phương án ưu tiên có điều kiện, chưa phải khả năng sẵn có cho toàn corpus.

Không cần chạy lại cả chunking để thử metadata. Trước hết tạo sidecar theo `parent_id` + `source_sha256` + taxonomy/tagger/preprocessing version. Chỉ cân nhắc đưa tagger vào lúc chunking sau khi nhãn và chi phí đã đạt yêu cầu. Cách này tận dụng output hiện hành và tránh thay toàn bộ fingerprint/index khi đang nghiên cứu.

Một lỗi thiết kế dễ gặp: NFKC, casefold và OpenCC có thể thay độ dài hoặc chuỗi ký tự. Offset của match trên chuỗi normalized không mặc nhiên bằng offset cleaned source. Evidence phải có `offset_space` rõ ràng, nguồn/hash và phép ánh xạ offset; hoặc trích trực tiếp từ child nguồn được đối chiếu. Cờ viết tắt phân biệt hoa/thường phải được kiểm tra trước bước hạ chữ.

**5. Các khoảng trống quan trọng trong phần huấn luyện**

**Thiếu nhãn không phải nhãn âm.** Aho tìm được Ch_IV không chứng minh parent không thuộc Ch_IX. Trong implementation OVA của FastText, mỗi lớp không có trong `targets` được cập nhật như negative. Nếu đưa nhãn thiếu của Aho vào thẳng một dòng huấn luyện, hệ thống có thể học triệt tiêu chính các chủ đề ít từ khóa, ngược mục tiêu Recall. Đây là rủi ro lớn hơn việc chọn `lr=0.25` hay `epoch=25`. [Mã nguồn OneVsAllLoss](https://raw.githubusercontent.com/facebookresearch/fastText/main/src/loss.cc).

MVP nên dùng những record mà tập chapter được rà đủ tương đối, loại/abstain các nhãn chưa biết khỏi quá trình tạo ví dụ âm. Nếu cần học với mask theo từng lớp hoặc soft labels đầy đủ, phải chọn cách huấn luyện hỗ trợ chúng; API FastText OVA thông thường không cung cấp hợp đồng này. Không thể chỉ viết “dùng Snorkel” rồi coi FastText đã tự học với loss xử lý nhãn thiếu.

**Các từ khóa không độc lập.** `đái tháo đường`, `tiểu đường` và dạng lặp của cùng một câu không phải ba nguồn xác nhận độc lập. Cần xử lý match lồng nhau, số mention phân biệt và tương quan giữa labeling functions. Bài Snorkel mô tả nguồn nhãn có độ chính xác/tương quan khác nhau, không chứng minh heuristic “hai từ khóa” đã đủ sạch. [Nghiên cứu gốc](https://arxiv.org/abs/1711.10160).

**Teacher bị giới hạn ứng viên cũng có thể bỏ sót.** Nếu chỉ cho Qwen chọn chapter Aho đã tìm, teacher không sửa được chapter Aho bỏ lỡ. Vì chỉ có khoảng 22 chapter, nên cho phép chọn toàn bộ chapter đã xác nhận trong taxonomy hoặc trả `outside_candidates`/abstain. Block có thể giới hạn ứng viên để giảm lỗi, nhưng không được coi “không chọn ứng viên” là chứng minh không có block khác.

**Gold 600–1.000 parent đủ khởi đầu, chưa đủ khẳng định Recall 96–98% cho mọi nhóm.** Riêng 22 chapter × 3 ngôn ngữ đã có 66 ô, chưa tính format và độ dài. Phải báo số positive mỗi ô, phân bố lỗi và khoảng tin cậy; ô không đủ mẫu phải ghi thiếu bằng chứng. Không điều chỉnh 66 ngưỡng từ một validation quá nhỏ rồi dùng lại chính tập đó để báo thành tích.

Chia train/calibration/test theo nhóm `doc_id`, canonical URL và near-duplicate trước. Parent cùng tài liệu, nội dung tái đăng hoặc các bản dịch trùng không được nằm ở cả train và test. Gold đánh giá relevance đang được xây trong `validation/` cũng không được trộn vào dữ liệu train ICD rồi dùng nó để chứng minh retrieval cải thiện.

FastText OVA, lấy toàn bộ nhãn với `k=-1`, tuning threshold và so sánh trước/sau quantization đều có căn cứ trong tài liệu chính thức. Các giá trị `0.15`, `dim`, `bucket`, tốc độ và model 25 MB vẫn chỉ là giả thuyết để đo. Score đầu ra chưa được hiệu chỉnh không nên được diễn giải là xác suất đúng y khoa. [FastText tutorial](https://fasttext.cc/docs/en/supervised-tutorial.html).

FastText không tự trở thành mô hình hiểu xuyên ngôn ngữ chỉ vì trộn ba ngôn ngữ vào file train. Cần positive/negative đủ ở mỗi ngôn ngữ, chuẩn hóa/tách từ riêng và báo cáo riêng. Mẫu có **4.988 record `source_language=und`**; ví dụ `1458145` ở trên rõ ràng là tiếng Trung. Không được bỏ các record đó hoặc xử lý mặc định thành tiếng Việt. Không ghép toàn bộ token các field `contents/broad/exact/anchors` của BM25 thành input FastText vì sẽ nhân đặc trưng và tần suất có chủ ý cho retrieval.

Từ điển hiện tại có **28.218 dòng VI**, **114.232 EN**, **27.332 ZH**; đây là segmentation lexicon, không phải danh sách thuật ngữ đã được gán ICD. `concepts.json` có **92 concepts**, nhãn VI/EN cho cả 92 nhưng nhãn ZH chỉ cho **12**; metadata còn ghi `production_ready: false`. Có thể tái sử dụng dữ liệu như nguồn ứng viên/provenance, chưa thể coi là bảng nối mã ba ngôn ngữ hoàn chỉnh.

**6. Tích hợp retrieval: thiết kế tốt nhưng chưa khớp API đang có**

Code hiện tại tìm ở hai cấp **documents/chunks**, mỗi cấp ba partition VI/EN/ZH. [models.py](models.py) chỉ khai báo field `contents`, `broad`, `exact`, `anchors`, `title`. [store.py](store.py) chưa có bảng parent/topic hoặc mapping parent trong bảng chunks. [backend.py](backend.py) chưa nhận điều kiện metadata; [engine.py](engine.py) fusion và cắt theo ngân sách. Ghi thêm `topic` vào JSON không tự làm metadata filtering hoạt động.

Nên triển khai theo hai mức, sau khi đặc tả tích hợp được duyệt:

1. Pilot: join sidecar để ghi feature/trace cho candidate sẵn có, đo độ chính xác nhãn và sự phù hợp query-parent. Mức này không tự tìm lại được tài liệu đã vắng trong candidate set.
2. Khi chứng minh có ích: thêm field keyword/filter hoặc một nhánh index chủ đề có version; truy vấn gồm lexical evidence cộng điều kiện topic. Hợp nhất với nhánh nền trước reranker. Query classifier cần evaluation riêng trên truy vấn tiếng Việt ngắn, không dùng nguyên ngưỡng của classifier parent dài.

Giữ nhánh không lọc **chưa đủ** để bảo đảm Recall không giảm. Khi thêm nhánh ICD, top-K sau fusion vẫn có thể đẩy mất positive của nhánh nền. `fuse()` hiện còn chia trọng số theo số run mỗi ngôn ngữ; thêm run sẽ làm thay đổi trọng số của các run cũ. Cần giữ ngân sách ứng viên nền được xác định rõ, ghi candidate bị thay thế và so sánh cả trường hợp cùng tổng ngân sách lẫn ngân sách tăng thêm.

ICD không thay thế dịch query/alias đa ngữ. Nhãn chapter chung có thể giúp routing nhưng quá rộng để tìm chính xác triệu chứng, gen, thuốc, thủ thuật và các facet điều trị. Cũng không mặc định giảm latency: chạy nhánh unfiltered đầy đủ cộng nhánh filtered thường tăng công việc trước rerank. Chỉ số có ý nghĩa là Recall/coverage tại cùng chi phí rerank hoặc chất lượng tăng tương xứng với chi phí.

Nhãn parent nên là prior cho child; nhãn có evidence ngay trong child có thể có trọng số mạnh hơn. Không mặc nhiên biến một bệnh được nhắc ở đầu parent 1.200 units thành bằng chứng mạnh ở mọi child. Tiêu đề/câu hỏi giúp hiểu context nhưng không tự chứng minh một chapter là nội dung chính của child.

**7. Tài nguyên và khả năng chạy Kaggle**

Tài liệu Kaggle hiện công bố CPU 4 cores, RAM 30 GB, vùng output được lưu 20 GB và phiên CPU/GPU tối đa 12 giờ; cấu hình/quota thực tế vẫn phải ghi từ session. [Kaggle documentation](https://www.kaggle.com/docs/notebooks).

Corpus chunk 23,75 GB đã vượt ngân sách output được lưu 20 GB nếu sao chép nguyên folder sang `/kaggle/working`. Nên mount input và chỉ ghi sidecar nén theo shard, checkpoint và model; không ghi lại text của 4,34 triệu child. Evidence có thể tham chiếu source span thay vì lặp cả đoạn trong mọi record. Quyền công bố các nguồn ghép phải được ghi trong manifest trước khi phát hành artifact.

Để thấy độ nhạy về chi phí, với 1.632.801 parent: throughput đầu-cuối 100 parent/s tương đương khoảng **4,54 giờ**; 500/s khoảng **54,4 phút**; 1.000/s khoảng **27,2 phút**. Đây là phép tính kịch bản, không phải throughput đã đo. LLM teacher, tách từ và nén/I/O phải được đo riêng; không suy từ tốc độ riêng FastText sang toàn pipeline.

Qwen2.5-7B-Instruct là ví dụ checkpoint công khai 7,61B, dòng Qwen2.5 được công bố tháng 9/2024; nằm trong giới hạn số tham số/ngày phát hành ghi ở `asked.md`. Điều đó không chứng minh model gán nhãn tốt trên dữ liệu này. Cần pin revision, precision/quantization, prompt và đo VRAM/throughput trước khi chốt ngân sách teacher. [Model card](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct), [thông báo phát hành](https://qwenlm.github.io/blog/qwen2.5/).

Repo FastText chính thức đã archive từ 19/03/2024; nên khóa wheel/runtime và kiểm tra cài đặt trên đúng môi trường Kaggle trước khi nhận làm dependency. Đây là rủi ro duy trì, không phải bằng chứng thuật toán không dùng được. [Repository chính thức](https://github.com/facebookresearch/fastText).

**8. Hướng triển khai nên chọn**

| Bước | Phạm vi khuyến nghị | Điều cần chứng minh trước khi mở rộng |
|---|---|---|
| 1 | Taxonomy chapter/block có version; lexicon bệnh đã đối chiếu theo từng nguồn | Mapping đúng, giữ ambiguity, không coi thuốc/xét nghiệm là tên bệnh; không chờ hoàn thiện mọi mã chi tiết mới được pilot |
| 2 | Adapter parent và sidecar; nguồn exact/union/reconstructed tách rõ | ID/source hash/offset đúng; không nhân overlap; không đổi `chunk_text` |
| 3 | Pilot khoảng 5.000 parent phân tầng VI/EN/ZH/und, profile, độ dài, parent đầu/cuối và QA answer | Aho precision/coverage; tỷ lệ unknown, ngoài bệnh, thiếu nội dung; lỗi title/negation/acronym/TCM |
| 4 | Gold độc lập và silver đủ thông tin; teacher chỉ cho khoảng trống có giá trị | Không leakage, không coi abstain là negative, giữ test chưa dùng tuning |
| 5 | So sánh Aho-only, FastText-only, Aho+FastText; thêm teacher khi có delta | Phần lợi ích ngoài dictionary baseline, theo từng ngôn ngữ và format; sau đó mới xét quantization |
| 6 | Thử metadata với candidate engine và query classifier | Doc Recall@K, chunk reference coverage theo LCS BTC, positive bị mất, cùng ngân sách và chi phí rerank |
| 7 | Chạy 100.000 parent rồi mới full | Resume/manifest/source consistency, throughput đầu-cuối và dung lượng output thực tế |

Điều kiện tối thiểu để chuyển giai đoạn: invariants ID/text/hash không có lỗi trong kiểm tra; không có giả định “khớp keyword = gold”; báo cáo per-language/per-format và support từng chapter; có so sánh retrieval dùng nhãn độc lập. Đề xuất ngưỡng nghiệm thu chất lượng cần được chốt từ pilot và mục tiêu recall của dự án, không lấy 96–98% trong phương án làm kết quả có sẵn.

Ưu tiên hiện tại là **parent adapter + taxonomy/lexicon tối thiểu + Aho pilot**, tạo metadata hỗ trợ và giữ unknown. FastText là bước tiếp theo có điều kiện; có thể bỏ hoặc trì hoãn nếu Aho đã đủ hữu ích hoặc FastText chủ yếu nhân lại lỗi silver. Reranker/embedding về sau có thể dùng chapter/block, mức tin cậy và loại bằng chứng làm feature mà không cần ép tất cả dữ liệu vào ICD-10.

Trang cuộc thi chính thức đã được thử truy cập lại nhưng công cụ không truy cập được. Quy định cuộc thi trong đánh giá này dựa vào [asked.md](../../asked.md): dữ liệu ngoài có nguồn, giới hạn model công khai ≤15B/phát hành trước 01/08/2026, bảo toàn `doc_id`/văn bản nguồn, và chấm ở document/chunk bằng macro-F2. Việc cho GPT tạo gold validation cục bộ trong task trước không được mở rộng thành quyền dùng closed-model teacher cho metadata của pipeline chính thức. Chưa đưa ra kết luận pháp lý hoặc xác nhận của BTC ngoài nội dung đã đọc.
