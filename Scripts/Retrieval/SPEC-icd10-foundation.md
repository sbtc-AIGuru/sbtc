# Đặc tả nền tảng ICD-10 và lexicon VI/EN/ZH

- Phiên bản: **1.0.0-draft**.
- Ngày: **16/10/2026**.
- Trạng thái: **được người dùng duyệt triển khai ngày 16/10/2026; implementation được theo dõi trong [kế hoạch](tasks/icd10-foundation/plan.md)**.
- Phạm vi: chuẩn bị taxonomy và lexicon phục vụ **nhận diện chủ đề**, ưu tiên chapter/block; category là căn cứ liên kết. Không phải phần mềm mã hóa bệnh án.
- Căn cứ dữ liệu: [báo cáo khảo sát corpus](REPORT-icd10-parent-fit-20261016.md).
- Tài liệu liên quan: [đặc tả 2.1 trước đây](SPEC-icd10-taxonomy-and-multilingual-lexicon.md), [review trước đây](REVIEW-icd10-taxonomy-and-multilingual-lexicon.md), [quy định cuộc thi](../../asked.md).

## 1. Mục đích, giả định và giới hạn

Xây một bộ tri thức có nguồn và phiên bản, cho phép consumer về sau trả lời: thuật ngữ này thuộc loại gì, có những đối tượng ICD-10 nào được nguồn hỗ trợ, quan hệ chính xác đến mức nào, và khi nào phải giữ nhiều ứng viên hoặc abstain.

Đơn vị bàn giao là dữ liệu máy đọc được và bộ kiểm tra chất lượng. Việc ghi `verified` phải chứng minh được bằng artifact; không dùng điểm tự chấm của LLM hoặc số lượng dòng lớn để xác nhận chất lượng.

Các giả định thiết kế được đưa ra để duyệt:

1. **WHO ICD-10 2019, có snapshot cập nhật được pin**, là hệ quy chiếu chủ đề chung. Nhãn Việt/Trung đến từ nguồn riêng và được liên kết có kiểm chứng.
2. Core cần đầy đủ chapter, các block/group có trong cây nguồn và category ba ký tự. Chưa bắt buộc dịch hoặc đối chiếu mọi subcategory quốc gia để bắt đầu pilot.
3. Thiếu bản dịch, alias hoặc crosswalk được biểu diễn tường minh. Không tự sinh dữ liệu để lấp chỗ trống.
4. Bộ mới được xây độc lập; không thay `resources/concepts.json`, `segmentation_*.txt` hoặc hợp đồng `Lexicon` hiện hành trong giai đoạn này.
5. Đây là một capability nền tảng: taxonomy, nguồn và các lexical links là các phần phụ thuộc của cùng một bộ dữ liệu phát hành. Train, parent tagging và retrieval là capability phía sau.

Ngoài phạm vi: huấn luyện FastText/Qwen; phục hồi parent; gán nhãn corpus; index/retrieval/reranking; sửa gold validation; tự động chẩn đoán hoặc chọn mã thanh toán. Không đọc `for_valid`, gold retrieval hay 1.200 query chính thức để xây từ điển hoặc chỉnh quy tắc.

## 2. Hợp đồng đầu vào/đầu ra

### 2.1. Đầu vào

| Nhóm | Dữ liệu cần nhận | Vai trò và giới hạn |
|---|---|---|
| WHO | ClaML 2019 + bản tabular cùng snapshot khi có | Cây chuẩn, preferred labels, rubric, references; tabular dùng đối soát và giải thích khác biệt |
| Việt Nam | TT 06/2026/TT-BYT và phụ lục; nguồn máy đọc được có thể đối soát với văn bản này | Native codes/labels VI và các thuộc tính nguồn; không coi một package cộng đồng là văn bản pháp lý |
| Trung Quốc | NHC disease clinical edition có version; NHSA insurance edition nếu bổ sung | Hai hệ nguồn khác nhau; không gộp phiên bản, mã hoặc labels |
| Lexicon bổ sung | Các tài nguyên hiện có và nguồn thuật ngữ có provenance | Đầu vào ứng viên; không tự động nhận làm ICD mapping |
| Quyết định review | Tệp review có entry ID, source refs, reviewer và lý do | Duyệt/loại từng sense, link, guard hoặc crosswalk; không chỉnh trực tiếp release |

Nguồn chính thức đã kiểm tra:

- [WHO download](https://icdcdn.who.int/icd10/index.html): có bản 2019 kèm COVID-19 updates. Một tên “2019” không đủ định danh bytes cụ thể.
- [WHO ClaML](https://icdcdn.who.int/icd10/clamlinfo.html): hierarchy, rubrics và references là dữ liệu riêng.
- [WHO metadata format](https://icdcdn.who.int/icd10/metainfo.html): tabular thiếu inclusion/exclusion và không đủ làm coding software; block identifier trong metadata có thể là mã bắt đầu, không mặc nhiên là chuỗi range.
- [WHO API languages](https://icd.who.int/icdapi/docs2/SupportedClassifications/): ICD-10 2019 công bố `en`, không cung cấp sẵn VI/ZH trong bảng này.
- [Cổng Chính phủ: TT 06/2026](https://chinhphu.vn/?docid=217536&orggroupid=4&pageid=27160): ban hành 02/04/2026, hiệu lực 01/07/2026; có phụ lục đính kèm.
- [NHC giải thích chuẩn](https://www.nhc.gov.cn/yzygj/c100067/202204/c335364a5309434cb31a27b1c45dea77.shtml): phân biệt disease clinical 2.0 và procedure 3.0.
- [Cơ quan y tế Phúc Kiến: clinical 2.0 XLS](https://wjw.fj.gov.cn/jggk/csxx/yzc/gzdt_33135/202106/t20210603_5607241.htm): đã xác minh trang có liên kết XLS; chưa xác minh bytes file trong task viết đặc tả.

Không khóa số lượng mã theo một con số trong báo cáo/package khác trước khi pin file. Chẳng hạn 16.052 concept hoặc số mã active/inactive trong tài liệu trước là mốc cần đối soát theo đúng phiên bản, không phải hằng số để parser cố tạo cho đủ.

Đường dẫn `/home/tran-nhat-truong/Downloads/package` được dùng trong công việc cũ hiện không tồn tại tại lần khảo sát này. Importer phải hỗ trợ nguồn local được khai báo hoặc tải nguồn đã chỉ định; không giả định package cũ còn sẵn, không yêu cầu quyền truy cập tới source đã mất để định nghĩa schema.

### 2.2. Đầu ra

Hai bảng nghiệp vụ chính:

- `taxonomy.jsonl`: cây canonical WHO, labels đa ngữ có provenance và thuộc tính phân cấp.
- `lexicon.verified.jsonl`: từng lexical sense đã được chấp nhận, có loại thuật ngữ, typed links và policy sử dụng.

Các bảng hỗ trợ bắt buộc:

- `source_manifest.json`, `source_nodes.jsonl`, `source_rubrics.jsonl`.
- `crosswalk_edges.jsonl`, `topic_projections.jsonl`.
- `review_queue.jsonl`, `review_decisions.jsonl`, `rejected.jsonl`.
- `ambiguity_groups.jsonl`, `coverage.json`, `reconciliation.json`, `ambiguity_report.json`.
- `release_manifest.json` và báo cáo audit khi đến bước phát hành.

`verified` không có nghĩa mọi entry tự tạo nhãn bệnh. Thuật ngữ xét nghiệm/thuốc đã kiểm chứng vẫn có thể chỉ được dùng làm context hoặc không có ICD link.

## 3. Ranh giới module và dữ liệu hiện hành

Code tương lai nằm trong `sbtc/Scripts/Retrieval/taxonomy/`; không sửa `lexicon.py`, `analyzers.py`, `corpus.py`, `rolling.py`, `engine.py`, `backend.py` để đưa dữ liệu mới vào production ở bước này.

Các `segmentation_*.txt` đang phục vụ tokenizer không mang đầy đủ quan hệ ICD. `concepts.json` hiện có schema khác, yêu cầu namespaced concepts/labels/source/license và bỏ qua ambiguous aliases ở matcher hiện hành. Không đổi tên file mới thành `concepts.json` để nạp vào loader cũ.

Bộ foundation cung cấp loader riêng. Việc nối sang tokenizer hoặc retrieval cần đặc tả tích hợp phía sau; chưa đổi index schema hoặc fingerprint hiện tại.

## 4. Mô hình taxonomy: bảo toàn cây thực tế

### 4.1. Cây và cấp độ

Mô hình hỗ trợ:

```text
chapter → block/group → [block/group con ...] → category → [subcategory ...]
```

Không ép độ sâu cố định. Các nhóm ung thư có phân cấp lồng nhau; chỉ tạo node từ class/group thực có trong source, không biến mọi heading trong bản in thành một node mới. Cây canonical lấy từ quan hệ ClaML, không dựng bằng thứ tự mã hoặc prefix. Nguồn tham khảo về các nhóm lồng nhau: [WHO Volume 1](https://iris.who.int/bitstream/handle/10665/246208/9789241549165-V1-eng.pdf?sequence=1), [BfArM ICD-10-WHO 2019](https://klassifikationen.bfarm.de/icd-10-who/kode-suche/htmlamtl2019/index.htm).

Core export bao gồm mọi chapter/block/group/category được nhận diện đúng từ snapshot WHO. Subcategory chỉ bắt buộc giữ ở `source_nodes` khi cần làm căn cứ lexical/crosswalk; mức độ xử lý modifier phải ghi trong manifest. Chưa hỗ trợ expansion của modifier không được âm thầm coi là không có dữ liệu.

`topic_level` có giá trị `chapter`, `block`, `category`, `subcategory`, `other_group`. Source kind được giữ riêng; chỉ map sang topic level khi có quy tắc được kiểm tra. `other_group` giữ grouping cần thiết cho hierarchy nhưng không tự thành nhãn train.

### 4.2. Khóa định danh

Khóa node là **`(system, edition_id, level, code)`**. Có `level` để tránh đụng category với block identifier dạng mã bắt đầu trong nguồn tabular.

- `system`: `WHO_ICD10`, `BYT_ICD10`, `NHC_ICD10_CLINICAL`, `NHSA_ICD10_INSURANCE`. Nguồn thuật ngữ khác có namespace riêng.
- `edition_id`: phiên bản nguồn bất biến, gắn với content hash của source bundle. Tên release của bộ foundation không thay thế edition của nguồn.
- `code`: mã canonical ở cấp tương ứng; giữ thêm `source_code_raw`.
- `node_id`: mã định danh chuỗi được sinh xác định từ bốn thành phần; không dùng row index hoặc tên bệnh.

Công thức định danh chốt cho implementation:

- `canonical_json(x)`: UTF-8, `ensure_ascii=False`, object keys được sort, separators `(',', ':')`, cấm NaN/Infinity; không chuẩn hóa thêm raw label trong phép băm.
- `bundle_hash = SHA256(canonical_json(sorted([{role, content_sha256}, ...])))`; danh sách member của edition được sắp theo `(role, content_sha256)`, không chứa URL/thời gian tải/path máy.
- `edition_id = declared_version + '@sha256:' + bundle_hash`. Thiếu declared version thì giữ `unknown` và đưa vào staging, chưa đủ điều kiện tạo edition official được chấp nhận.
- `node_id = 'icdnode:' + SHA256(canonical_json([system, edition_id, level, code]))` dùng toàn bộ 64 hex. Các trường human-readable vẫn được lưu cùng ID.

Không chọn tùy ý một parent nếu nguồn cung cấp các quan hệ cha mâu thuẫn/nhiều cha chưa giải thích được. Giữ source edges, đưa issue vào review; canonical tree chưa được publish cho node đó. Reference/dagger pairing không được biến thành hierarchy parent để xử lý tình huống này.

Quy ước chapter của WHO core: `01`…`22`, với Roman numeral/raw chapter ID giữ trong `source_code_raw`. Bảng chuyển chapter phải đối soát từ nguồn, không trộn `IV`, `Ch_IV`, `Ch_04` trong cùng trường. Số chapter thực tế và phạm vi U codes lấy từ snapshot; khác kỳ vọng phải báo lỗi để kiểm tra thay vì tự thêm/xóa chương.

Category dùng mã ba ký tự từ source; subcategory giữ dấu chấm theo nguồn. Không tự đoán dấu chấm cho mã quốc gia. Với block, giữ ID/range có nguồn; không suy end-range từ dòng kế tiếp. Dagger/asterisk lưu ở thuộc tính riêng và raw code, không bị xóa mất thông tin.

### 4.3. Schema `taxonomy.jsonl`

| Trường | Kiểu/ràng buộc |
|---|---|
| `schema_version` | integer, phiên bản hợp đồng dữ liệu |
| `node_id` | string duy nhất |
| `system`, `edition_id`, `level`, `code` | thành phần NodeKey; canonical core thuộc WHO |
| `source_code_raw`, `source_kind` | giữ nguyên giá trị từ nguồn |
| `parent_id` | null chỉ với chapter root; còn lại là FK trong cùng edition |
| `chapter_id` | FK tới chapter; chapter trỏ chính nó |
| `block_path` | list ID các block ancestor từ ngoài vào trong; không chỉ một `block` |
| `nearest_block_id` | block ancestor gần nhất; null khi không áp dụng |
| `labels` | object `en`, `vi`, `zh`; mỗi phần là null hoặc LabelAssertion |
| `code_status` | `active`, `inactive`, `deprecated`, `unknown`; chỉ lấy trạng thái có căn cứ |
| `valid_from`, `valid_to` | ISO date hoặc null; không gán mặc định 01/01 theo năm edition |
| `coding_attributes` | terminal status, usage flags, dagger/asterisk, modifier/reference IDs; nullable khi thiếu nguồn |
| `source_refs` | ít nhất một evidence ref tới source snapshot |
| `verification` | cấu trúc nêu trạng thái, phương pháp và evidence |

`LabelAssertion` gồm: `text`, `language`, `origin` (`official_source`, `equivalent_crosswalk`, `reviewed_display_label`), `native_node_id` nếu có, `source_refs`, `crosswalk_edge_ids`, `review_decision_id` nếu cần review. Label VI/ZH lấy từ mã native chi tiết hơn **không** được gắn thành preferred label cho một WHO block rộng hơn.

Ví dụ schema dưới đây chỉ minh họa, không phải record đã trích xuất/duyệt. Các placeholder không được xuất hiện trong artifact phát hành:

```json
{
  "schema_version": 1,
  "node_id": "<WHO-edition-category-E11-id>",
  "system": "WHO_ICD10",
  "edition_id": "<immutable-source-edition>",
  "level": "category",
  "code": "E11",
  "source_code_raw": "E11",
  "source_kind": "category",
  "parent_id": "<WHO-edition-block-E10-E14-id>",
  "chapter_id": "<WHO-edition-chapter-04-id>",
  "block_path": ["<WHO-edition-block-E10-E14-id>"],
  "nearest_block_id": "<WHO-edition-block-E10-E14-id>",
  "labels": {
    "en": {
      "text": "Type 2 diabetes mellitus",
      "language": "en",
      "origin": "official_source",
      "native_node_id": "<WHO-source-node-id>",
      "source_refs": ["<source-ref>"],
      "crosswalk_edge_ids": [],
      "review_decision_id": null
    },
    "vi": null,
    "zh": null
  },
  "code_status": "unknown",
  "valid_from": null,
  "valid_to": null,
  "coding_attributes": {},
  "source_refs": ["<source-ref>"],
  "verification": {"status": "draft", "method": null, "evidence_refs": []}
}
```

`coding_attributes` không tham gia hard filter retrieval. Chẳng hạn “không làm chẩn đoán chính” trong hệ coding không có nghĩa nội dung liên quan phải bị loại khỏi corpus. Thuộc tính không đọc được phải là null/unknown, không mặc định false.

### 4.4. Các bảng căn cứ và quyết định

| Artifact | Các trường tối thiểu |
|---|---|
| `source_nodes.jsonl` | `source_node_id`, NodeKey nguồn, raw/source kind, native parent IDs, raw/preferred labels, attributes, locator/source refs, parse status; mã chưa map vẫn được giữ |
| `source_rubrics.jsonl` | `rubric_id`, `source_node_id`, `rubric_kind`, `language`, `text_raw`, extracted text, references, source refs; exclusion và instruction có loại riêng |
| `review_queue.jsonl` | `issue_id`, object type/ID, reason code, candidates, evidence refs, required action, open/resolved/rejected status |
| `review_decisions.jsonl` | `decision_id`, object ID, accept/reject/defer, relation/usage đã chốt, reviewer/method/version, evidence refs, rationale, superseded decision ID nếu có |
| `rejected.jsonl` | object ID/raw ref, reason, decision ID; không xóa dấu vết nguồn |

`source_node_id` dùng cùng công thức NodeKey ID nhưng thuộc system/edition native. Rubric/issue/decision IDs có namespace và content key xác định, không theo số dòng. Quyết định review mới không ghi đè quyết định cũ; selection quyết định đang hiệu lực phải dựa vào supersession chain hợp lệ, không dựa vào file order.

Raw unresolved references được giữ làm raw data có trạng thái; accepted FK/link không được trỏ tới node thiếu. Không yêu cầu mọi raw mention trong coding instruction đều trở thành một taxonomy node mới.

## 5. Provenance và nhập nguồn

### 5.1. Source manifest

Mỗi snapshot ghi `source_id`, tổ chức, system, version khai báo, edition ID, landing URL, download URL thực, redirect URL, thời gian lấy UTC, SHA-256/bytes archive, SHA-256/bytes từng member, media type/encoding, local path, parser/config version và trạng thái quyền sử dụng có căn cứ.

Source local phải có file hash, provenance có được và giới hạn xác minh. URL nguồn không tự chứng minh file local tương ứng; phải đối soát version/content. URL tải chưa xác minh được giữ trạng thái `download_unverified`, không bịa tên file hoặc hash.

`source_ref` định danh được **snapshot + locator**: XML class/rubric/ref; PDF page/table/row và raw cell; XLS sheet/row/cell; JSON pointer/item code. Đủ để mở lại nguồn kiểm tra label hoặc mapping cụ thể.

### 5.2. Quy tắc nhập theo nguồn

**WHO:** đọc Class/SuperClass/SubClass, tách preferred/inclusion/exclusion/definition/coding instruction/reference. Nếu SuperClass và SubClass mâu thuẫn, dừng build canonical. Preferred title lấy đúng rubric; inclusion chỉ tạo ứng viên khi là thuật ngữ phù hợp; exclusion không được dùng làm synonym của node đang chứa nó. Các reference trong exclusion giữ nguyên như quan hệ coding, không chuyển thành parent hoặc alias.

**Tabular:** phát hiện encoding/schema thực và đối soát với ClaML cùng snapshot. Không dùng block start ID thay cho full range; không tự coi mọi chênh lệch là parser lỗi nếu khác định nghĩa về modifier/terminal codes. Phải giải thích từng nhóm chênh lệch bằng log.

**Việt Nam:** giữ mã native, tên VI/EN nếu có, trạng thái, cờ sử dụng và raw headers. Sơ đồ cột/flag được xác nhận theo file thực, không cố định “cột 24–29” hoặc sáu giá trị false trước khi đọc phụ lục. PDF row bị nối, tách, OCR không chắc chắn phải vào review queue. Nguồn FHIR máy đọc được chỉ được nhận sau khi pin package và đối soát với danh mục pháp lý, không nâng `draft` của package thành nhãn official của WHO.

**Trung Quốc:** tách NHC clinical và NHSA insurance ở system/edition. Giữ tên phồn thể/giản thể gốc và mã native, không chuyển OpenCC trên label nguồn. Mã thủ thuật ICD-9-CM-3 không nhập nhầm cây bệnh ICD-10. File mirror/GitHub chỉ là nguồn hỗ trợ với provenance, không được nâng thành official nếu chưa đối soát.

**Nguồn lexical:** MeSH, tài liệu bệnh, dictionary hiện có và corpus chỉ sinh candidates. NER type disease không chứng minh ICD code. Từ điển tách từ không tự có semantic links. Không loại cả nhóm thuật ngữ chỉ theo số âm tiết hoặc độ dài; một từ như `gout` có thể hợp lệ, một viết tắt hai chữ có thể rất nhập nhằng.

Parser phải có reconciliation: tổng record nguồn = accepted + quarantined + rejected + deferred, kèm lý do. Không drop silent. Archive/XML/XLS được đọc có giới hạn tài nguyên, tránh path traversal và tải external entity; không thực thi macro/code từ nguồn.

## 6. Crosswalk và chiếu sang chủ đề

### 6.1. Crosswalk là quan hệ giữa khái niệm, không phải phép cắt chuỗi

`crosswalk_edges.jsonl` chứa `edge_id`, `source_node_id`, `target_node_id`, `relation`, `verification`, `source_refs`, `review_decision_id` và `mapping_method`.

`relation` có hướng từ source sang target: `equivalent`, `narrower_than`, `broader_than`, `related_to`. `unmapped` và `conflict` là trạng thái quyết định trong review queue, không phải cạnh xác nhận có thể đi qua.

Quy tắc bắt buộc:

1. Cùng chuỗi mã giữa hai edition/system chỉ tạo **candidate edge**. Kiểm tra meaning, scope, hierarchy và inclusion/exclusion khi có.
2. Mã dài hơn không tự thành `narrower_than`. Prefix matching, code similarity, tên giống hoặc bản dịch chỉ là phương pháp đề xuất candidate.
3. `equivalent` cần mapping chính thức phù hợp đúng edition, hoặc review source-grounded về cùng khái niệm/phạm vi. Không gộp mã bằng tên.
4. Source cụ thể hơn target thì có thể `narrower_than` khi được chứng minh; không chuyển nhãn cụ thể đó thành preferred label của target rộng.
5. `broader_than` không cho phép chọn một nhánh con cụ thể. Nếu nguồn rộng tương ứng nhiều mã, giữ nhiều ứng viên hoặc project tới ancestor chung được xác minh.
6. `related_to` chỉ cho context; không dùng làm nhãn bệnh xác định.
7. Không suy bắc cầu qua arbitrary related/broader edges. Chỉ cho phép chain được duyệt và ghi đầy đủ đường đi.
8. Không xác định chapter bằng chữ cái đầu: D và H có các phạm vi thuộc chương khác nhau.

### 6.2. Topic projections

`topic_projections.jsonl` tách projection phục vụ chủ đề khỏi crosswalk tương đương khái niệm. Mỗi record gồm `projection_id`, source/target IDs, path gồm các edge/ancestor IDs, `scope: chapter|block|category`, `status`, `source_refs` và căn cứ review.

Projection được chấp nhận khi source được xác minh tương đương hoặc hẹp hơn một canonical node và target là chính node đó hoặc ancestor trong cây WHO. Không project một concept rộng xuống một category chỉ vì category đó thường gặp. Nếu chưa chứng minh được block nhưng đã chứng minh chapter, chỉ phát hành chapter projection.

Một leaf native chưa có crosswalk có thể vẫn có chapter projection nếu native hierarchy và mapping ancestor đều đã xác minh. Phải lưu đúng đường đi, không gắn nhãn `equivalent` cho leaf.

## 7. Lexicon theo lexical sense và cách sử dụng

### 7.1. Không dùng normalized term làm khóa duy nhất

Cùng surface form có thể có nhiều sense, kể cả trong cùng ngôn ngữ. `PSA`, `MS`, `ALL`, `THA` là nhóm cần xử lý như vậy. Mỗi sense có `entry_id` riêng và giữ nhiều source refs; không lấy candidate đầu tiên theo thứ tự file.

Khóa identity của entry sinh xác định từ language, raw surface/sense identifier có nguồn. Giá trị normalized là chỉ mục lookup, không phải bằng chứng hai entry đồng nghĩa. Duplicate cùng sense được gộp provenance; collision giữa các sense giữ ambiguity group. Nếu chưa phân biệt được same-sense với homonym, giữ candidates ở review queue.

`sense_id` là ID concept nguồn có nghĩa đã xác minh, hoặc ID curation được cấp một lần qua review khi không có concept sẵn. `entry_id = 'lex:' + SHA256(canonical_json([language, term_raw, sense_id, lexical_relation]))`. `source_refs` không nằm trong identity để thêm nguồn không làm đổi entry ID. Chỉ gộp khi tuple này giống nhau; các raw variants khác tuple giữ entry riêng. `ambiguity_group_id` sinh từ `[normalization_profile, language, term_normalized]`; group lưu đủ sense IDs, kể cả sense còn pending và chưa có trong runtime export.

`ambiguity_groups.jsonl` là dữ liệu runtime, không chỉ báo cáo: chứa group ID, normalized surface, language/profile, mọi sense ID/status, decision refs và trạng thái conflict. Loader phải đọc registry này cùng lexicon. Một sense accepted còn sense cạnh tranh chưa được giải quyết thì không được coi là unambiguous chỉ vì sense pending không xuất hiện trong file verified. `ambiguity_report.json` chỉ là bản thống kê tổng hợp, không thay thế registry.

Language lấy từ nguồn hoặc review có căn cứ; không đoán ngôn ngữ của tên thuốc Latin chỉ từ bảng chữ cái. Một surface được dùng ở nhiều ngôn ngữ có các language entries được xác nhận riêng; `und` giữ ở staging, chưa tự thành entry VI/EN/ZH accepted.

### 7.2. Schema `lexicon.verified.jsonl`

| Trường | Hợp đồng |
|---|---|
| `schema_version`, `entry_id` | version và ID ổn định, không theo số dòng |
| `language` | `vi`, `en`, `zh`; script variant là trường riêng |
| `term_raw` | surface đã trích, giữ dấu/hoa thường; raw cell nằm trong evidence |
| `term_normalized`, `term_case_preserved` | hai view theo normalization profile đã pin |
| `normalization_profile` | ID/version và config hash |
| `kind` | bảng loại thuật ngữ bên dưới |
| `lexical_relation` | `official_label`, `inclusion_term`, `synonym`, `colloquial_alias`, `abbreviation`, `orthographic_variant`, `context_term` |
| `native_concept_ids` | list NodeKey ID nguồn, có thể rỗng với context chưa có concept |
| `links` | typed semantic links, nhiều target hoặc rỗng; mỗi link có evidence và review riêng |
| `ambiguity_group_id` | null hoặc group ID liên kết mọi sense cạnh tranh |
| `matching_policy` | case/boundary/script/guard, định nghĩa tại 8 |
| `usage` | `topic_candidate`, `context_only`, `abstain`; policy gắn cả entry và link, lấy mức chặt hơn |
| `verification` | acceptance/source/semantic states tách riêng |
| `source_refs`, `review_decision_ids` | provenance không rỗng, review IDs khi cần |

Mỗi link chứa `target_node_id`, `relation` (`exact_concept`, `narrower_concept`, `topic_association`, `supporting_evidence`), `projection_ids`, `usage`, `source_refs`, `review_decision_id`. `topic_association` là liên hệ để xem xét chủ đề, không tuyên bố tương đương mã chẩn đoán.

| `kind` | Quy tắc mặc định |
|---|---|
| `disease_or_condition` | Có thể `topic_candidate` khi sense/link được xác minh |
| `symptom_sign` | Có thể nhận diện chính khái niệm triệu chứng trong ICD nếu có mapping; liên hệ với bệnh chỉ là supporting/context |
| `diagnostic_test` | Context; không suy ra bệnh từ tên xét nghiệm hoặc chỉ số đơn lẻ |
| `drug_substance` | Context; nhiều chỉ định không bị ép về một bệnh |
| `procedure` | Context; không nhầm system mã thủ thuật với mã bệnh |
| `anatomy` | Context; tên cơ quan không tự tạo chương bệnh |
| `biomarker` | Context, bảo toàn literal/case khi cần; không suy ung thư chỉ từ tên gen |
| `context_modifier` | Phủ định/nghi ngờ/tiền sử/so sánh; `links=[]` nếu chỉ là modifier |
| `tcm_pattern` | Có thể giữ context; chỉ liên kết ICD khi có evidence cho quan hệ cụ thể |
| `unknown` | Không được vào runtime verified; chờ review |

Thuật ngữ không bệnh học có thể được kiểm chứng là thuật ngữ đúng mà không cần có ICD link. Không bị reject chỉ vì `links=[]`, nếu kind/usage/provenance hợp lệ.

### 7.3. Bằng chứng và trạng thái

`verification` có ba chiều độc lập:

- `extraction_status`: `source_verified` hoặc trạng thái staging chưa xác minh.
- `semantic_status`: `direct_official_label`, `source_supported`, `independently_reviewed`, `unverified`, `conflict`.
- `acceptance`: `accepted`, `quarantined`, `rejected`.

Chỉ accepted entries và accepted links được export vào `lexicon.verified.jsonl`; semantic unverified/conflict không được che bằng tên file verified. Official label trực tiếp trỏ đúng native node có thể accepted bằng quy tắc nguồn xác định, không bắt buộc LLM rà lại mọi dòng. Alias thông tục, viết tắt, translation/crosswalk suy luận phải có review thích hợp.

LLM có thể đề xuất từ/sense/mapping và lý do, nhưng đề xuất đó không tự trở thành official hoặc verified. Nếu dùng model để tạo dữ liệu cho pipeline chính thức phải đáp ứng `asked.md`; quyền dùng GPT tạo gold validation cục bộ trong task khác không mở rộng sang dataset production này.

Một nhãn hiển thị dịch thủ công hoặc đề xuất dịch chỉ được dùng khi có review độc lập, nguồn khái niệm và quyết định chấp nhận được ghi lại; luôn mang `reviewed_display_label`, không mang `official_source`. Không chạy dịch máy để tự điền các ô null rồi tính chúng là coverage đã xác minh.

`review_queue.jsonl` giữ entry/link candidate, reason code, evidence hiện có và phần còn thiếu. Không xóa các trường hợp khó để báo một tỷ lệ precision đẹp hơn; báo rõ phần bị loại khỏi phạm vi đánh giá/runtime.

## 8. Chuẩn hóa, nhập nhằng và hợp đồng lookup

### 8.1. Hai normalization view

Profile nền đề xuất: NFKC → OpenCC `t2s` với ZH → chuẩn hóa whitespace → strip. Từ đó tạo:

- `term_case_preserved`: giữ case sau các bước trên.
- `term_normalized`: thêm `lower()`, tương thích nguyên tắc normalize đang dùng; không tự thay bằng casefold.

Không bỏ dấu tiếng Việt, không cắt theo ký tự Hán, không xóa toàn bộ dấu câu, không tự rút mã chi tiết, không đổi liều lượng/đơn vị sang bệnh danh. Dạng viết tắt/chính tả khác chỉ được thêm như entry có provenance hoặc variant có transformation được khai báo.

HTML entity/markup được xử lý tại adapter nguồn đúng một lần với log raw/extracted; không đặt `html.unescape` lặp trong normalize chung vì chuỗi double-escaped có thể làm sai tính lũy đẳng. Pinned profile phải đạt `normalize(normalize(x)) == normalize(x)` trên fixtures và mọi term được nhận.

Pin OpenCC package, config và data hash trong manifest. OpenCC chỉ tạo matching view; label/raw text vẫn giữ nguyên. Collision do giản/phồn, compatibility characters hoặc lowercasing được ghi lại, không tự gộp sense.

### 8.2. Matching policy là dữ liệu có kiểm chứng

- `case_policy`: `insensitive` hoặc `sensitive`. Sensitive phải xét `term_case_preserved` trước khi lowercase; lowercase rồi kiểm uppercase là không hợp lệ.
- `boundary_policy`: `latin_token`, `cjk_phrase`, `code_literal`, `exact_surface` với hợp đồng cụ thể cho audit matcher.
- `latin_token`: chặn khớp bên trong chuỗi Latin/chữ số/underscore; chữ Hán kề mã Latin không mặc nhiên làm match mất hiệu lực. Không dùng duy nhất `str.isalnum()` để đặt boundary cho tất cả script.
- `cjk_phrase`: khớp surface trên chuỗi Hán tự nhiên; xử lý term lồng nhau theo span/sense, không tự tính mỗi mảnh là một nguồn bằng chứng độc lập.
- `code_literal`: theo grammar/edition nguồn, giữ marker/context; prefix code dài không tự tạo exact code ngắn.
- `context_rule_id`: null với entry không cần guard; entry nhập nhằng muốn được resolve phải có rule đã rà hoặc vẫn abstain.

Guard quy định context scope, trigger/exclusion term IDs, polarity, và đơn vị window rõ ràng. Không ghi “±5 token” mà không có tokenizer/version, đặc biệt với ZH. Một rule chưa được kiểm định có thể nằm ở staging, không được phát hành như rule đã chứng minh disambiguation.

Lookup phải trả một trong `resolved_candidate`, `ambiguous_candidates`, `context_only`, `no_match`. `no_match` không có nghĩa “không có bệnh”. Nếu nhiều sense/guard cùng phù hợp, giữ nhiều ứng viên; không ưu tiên sense do ID hay thứ tự import.

Phủ định, nghi ngờ, tiền sử gia đình và so sánh được ghi thành assertion/context, không xóa mention chủ đề. Một tài liệu giải thích “RF dương tính không đủ chẩn đoán viêm khớp” vẫn có chủ đề viêm khớp. Module này không quyết định relevance của tài liệu.

Audit matcher nếu xuất span phải ghi `offset_space`, text hash và normalization profile. Offset normalized không được gắn nhãn cleaned-source offset. Ánh xạ về source parent thuộc hợp đồng tích hợp về sau.

## 9. Ví dụ bắt buộc phải xử lý đúng

Các ví dụ dưới đây là yêu cầu về loại quan hệ/hành vi; không phải danh sách mapping đã được duyệt:

| Tình huống | Kết quả bắt buộc |
|---|---|
| “tiểu đường” không có subtype | Không tự gán riêng E11; chỉ giữ quan hệ chủ đề rộng/candidates có nguồn |
| “đau dạ dày” | Phân loại triệu chứng; không tự coi là synonym chính xác của viêm/loét dạ dày |
| HbA1c / HbA1c cao | Xét nghiệm/biomarker và context; không tự chứng minh chẩn đoán E11 |
| metformin / aspirin | Thuốc; không suy một bệnh duy nhất từ tên thuốc |
| PSA trong procedural sedation analgesia | Không resolve sang xét nghiệm tuyến tiền liệt chỉ vì cùng viết tắt |
| ALL trong câu thông thường/heading viết hoa | Không resolve leukemia khi thiếu guard nghĩa phù hợp |
| MS/mS và đơn vị đo | Không phá case/unit để suy bệnh |
| 糖尿病 / dạng phồn thể có nguồn | Matching view nhất quán; raw labels được bảo toàn |
| 肝肾阴虚 | Giữ loại chứng Đông y; không đồng nhất với suy gan/suy thận |
| Mã quốc gia dài có prefix trùng mã WHO | Candidate mapping; chưa có evidence thì abstain |
| Exclusion của một mã nhắc tới bệnh khác | Không thêm bệnh bị loại trừ làm synonym của mã chứa exclusion |
| Mã D/H khác phạm vi | Chapter lấy theo cây nguồn, không theo ký tự đầu |
| Alias cùng surface thuộc hai concept | Giữ đủ senses/ambiguity; không silently overwrite |
| Không có nhãn ZH của một category | null + coverage gap; không dịch máy rồi ghi official |
| Nguồn có trạng thái/cờ không rõ | unknown/null và issue có locator; không điền false cho đủ schema |

## 10. Cấu trúc code và artifact dự kiến

```text
sbtc/Scripts/Retrieval/taxonomy/       # sẽ tạo sau khi duyệt
  models.py                          # DTO, NodeKey, enums
  sources.py                         # manifest, adapter interface
  who.py / byt.py / chinese.py        # source-specific parsers
  normalize.py                       # pinned profile, two case views
  crosswalk.py                       # candidate edges, accepted projections
  lexicon.py                         # lexical sense curation, loader
  validation.py                      # structural/source/semantic release gates
  cli.py                             # orchestration, no retrieval dependency
sbtc/Scripts/Retrieval/configs/taxonomy.sources.json
sbtc/Scripts/Retrieval/tests/test_taxonomy_*.py
sbtc/Scripts/Retrieval/tests/fixtures/taxonomy/
  semantic_gold_test.jsonl
  source_fixture_*                    # nhỏ, có nguồn hoặc synthetic đánh dấu rõ

artifacts/taxonomy/
  sources/<source-id>/<sha256>/       # immutable source bytes
  runs/<run-id>/
    source_manifest.json
    source_nodes.jsonl / source_rubrics.jsonl
    taxonomy.jsonl / crosswalk_edges.jsonl / topic_projections.jsonl
    lexicon.verified.jsonl
    review_queue.jsonl / review_decisions.jsonl / rejected.jsonl
    ambiguity_groups.jsonl / coverage.json / reconciliation.json / ambiguity_report.json
    audit/
  releases/<release-id>/              # chỉ sau khi đạt release gate
    release_manifest.json
    ... accepted data + coverage/provenance/audit ...
```

Các đường dẫn trên là đề xuất, chưa có code/CLI được tạo bởi task viết đặc tả. Nếu một path đã có dữ liệu, không ghi đè; chọn run mới. Nguồn/bộ dẫn xuất cũ giữ nguyên.

Dùng Python theo runtime repo, `unittest` đang có, thư viện chuẩn cho JSON/hash/streaming; tái sử dụng OpenCC/pyahocorasick đã khai báo để audit matching. Nếu đọc XLS cần thư viện chưa có trong runtime, phải xác nhận dependency khi lập kế hoạch; không đổi file extension để giả làm XLSX/CSV. Chưa yêu cầu framework schema hay database mới; schema version và validation contract phải được định nghĩa tường minh trong implementation.

Boundary API tối thiểu:

- `SourceAdapter.parse(snapshot) -> Iterator[SourceRecord]`.
- `TaxonomyReader.node(node_id)` và `ancestors(node_id)`.
- `CrosswalkResolver.candidates(source_node_id)` trả đủ trạng thái, không chọn thay consumer.
- `LexiconReader.lookup(surface, language, context=None)` trả các sense/links/policies, không có nhãn bệnh bị bịa khi no-match.
- `ReleaseValidator.validate(bundle) -> ValidationReport`.

Code style theo dataclass và type hints hiện có; ví dụ hợp đồng, chưa phải code triển khai:

```python
@dataclass(frozen=True)
class NodeKey:
    system: str
    edition_id: str
    level: str
    code: str
```

## 11. CLI và hành vi lỗi dự kiến

Các lệnh chỉ là hợp đồng cho implementation tương lai, **chưa chạy được và chưa được thực thi**:

```bash
python -m sbtc.Scripts.Retrieval.taxonomy.cli fetch \
  --sources sbtc/Scripts/Retrieval/configs/taxonomy.sources.json \
  --run-dir artifacts/taxonomy/runs/phase1-pilot-001

python -m sbtc.Scripts.Retrieval.taxonomy.cli build \
  --run-dir artifacts/taxonomy/runs/phase1-pilot-001

python -m sbtc.Scripts.Retrieval.taxonomy.cli validate \
  --run-dir artifacts/taxonomy/runs/phase1-pilot-001

python -m sbtc.Scripts.Retrieval.taxonomy.cli audit \
  --run-dir artifacts/taxonomy/runs/phase1-pilot-001 \
  --gold sbtc/Scripts/Retrieval/tests/fixtures/taxonomy/semantic_gold_test.jsonl

python -m sbtc.Scripts.Retrieval.taxonomy.cli freeze \
  --run-dir artifacts/taxonomy/runs/phase1-pilot-001 \
  --release-id icd10-foundation-v1.0.0

python -m unittest discover -s sbtc/Scripts/Retrieval/tests -p 'test_taxonomy_*.py'
```

`build` không tự tải nguồn mới. Thiếu file hoặc hash lệch thì dừng, không fallback sang edition khác. Fetch có timeout/retry hữu hạn và resume chỉ khi bytes/hash tương thích. Thư mục đã tồn tại nhưng manifest không khớp thì từ chối ghi. Write tạm rồi atomic publish; failure không tạo artifact có cờ ready.

Exit code dự kiến: `0` hoàn tất theo đúng lệnh/profile; `2` input/config sai; `3` source/hash/parser failure; `4` validation/semantic gate fail; `5` release conflict/incompatible resume. `validate` có warnings phải in rõ và trả report status riêng, không đổi một error thành warning để freeze.

## 12. Kiểm tra và nghiệm thu

### 12.1. Kiểm tra cấu trúc và nguồn

| ID | Điều kiện bắt buộc |
|---|---|
| F01 | Schema/enum/type hợp lệ 100%; không placeholder, NaN/Infinity, duplicate NodeKey/entry/edge ID |
| F02 | Không orphan/cycle; ancestor/chapter/block_path khớp cây và edition; không ép độ sâu cố định |
| F03 | Mọi source record được reconciliation; mọi chênh lệch phải có reason/locator; không tạo thêm mã cho đủ expected count |
| F04 | Accepted crosswalk có evidence; không suy relation từ độ dài/prefix; không project broader/related xuống bệnh cụ thể |
| F05 | Rubric exclusion không đi vào synonym; flags/dagger/asterisk/modifiers giữ được raw và missing status |
| F06 | Mọi nhãn/entry/link accepted có source refs hợp lệ; source_verified không thay semantic verification |
| F07 | 100% preferred EN chapter/block/category đối soát đúng source WHO; thiếu label khác ghi coverage và unresolved |
| F08 | Normalization idempotent; raw không đổi; case-sensitive guards còn hiệu lực; collision không overwrite |
| F09 | Lookup giữ đủ senses khi ambiguous; no-match khác negative; context modifier không tự xóa topic mention |
| F10 | Runtime verified chỉ chứa accepted entries/links; unknown/conflict không lọt qua bằng fallback |
| F11 | Cùng nguồn/config/review decisions sinh cùng bytes của data files; manifest tách timestamp/metrics khỏi content fingerprint |
| F12 | Không sửa corpus/query/gold, resources hiện hành hoặc chạy retrieval trong module foundation |

WHO chapter/block/category coverage đo theo snapshot đã pin. Label coverage VI/ZH và lexical coverage phải báo riêng theo level/language, không cộng alias để làm tăng tỷ lệ node được bao phủ. Không dùng tỷ lệ coverage nguồn thay cho recall trên ngôn ngữ tự nhiên.

`coverage.json` phải có denominator là số node canonical ở từng level, numerator là số node có label assertion accepted ở ngôn ngữ đó, danh sách missing node IDs và nguồn/edition đang xét. Với lexicon, báo số raw candidates, số accepted senses, số surface khác nhau, số accepted links theo relation/usage, ambiguity và abstain riêng. Không trộn số senses với số thuật ngữ hoặc tính context-only link là disease coverage.

### 12.2. Audit ngữ nghĩa độc lập

Giữ yêu cầu tối thiểu **200 ca** từ đặc tả trước, trong đó mỗi VI/EN/ZH có ít nhất 50 ca và có các ca nhập nhằng/mixed-script. Bao phủ: tên bệnh; khẩu ngữ/viết tắt; triệu chứng/xét nghiệm/thuốc/thủ thuật; phủ định/tiền sử/so sánh; phồn–giản; source codes/crosswalk; các ví dụ corpus thật đã chỉ ra trong báo cáo khảo sát.

Expected answers phải được đọc/xác lập độc lập từ nguồn và rubric trước khi xem kết quả implementation; không sinh expected bằng matcher đang kiểm tra. Giữ developer fixtures riêng với semantic holdout. Nếu có thêm ví dụ corpus, chỉ dùng tập test đã được người dùng cho phép; không dùng `for_valid`, gold retrieval hoặc official queries để tune.

Chỉ số bắt buộc: đúng/sai loại thuật ngữ, đúng/sai target/relation, resolved precision, ambiguity preservation, abstain rate, supported-sense recall và breakdown theo language/kind. Khi corpus ngoài scope không có ICD phù hợp, abstain đúng không bị coi là lỗi recall. Mỗi tỷ lệ có tử số/mẫu số, support và khoảng tin cậy khi phù hợp.

Giữ các mục tiêu chất lượng của đặc tả trước làm **gate cần kiểm chứng**: mapping tên bệnh chính thức precision ≥99%; resolved/topic mapping precision ≥98% trên holdout đã duyệt. Không gọi các mục tiêu này là kết quả đạt được; 200 ca không đủ chứng minh chất lượng 98% ở từng chapter/ngôn ngữ hiếm. Mọi mapping catastrophic (đổi hệ mã, nhầm bệnh với chỉ dấu, silent homonym resolution) phải được sửa dù aggregate còn vượt ngưỡng.

### 12.3. Hiệu năng và khả năng tái lập

Giữ các mục tiêu tham chiếu trước đây cho **lexicon audit matcher**: query p95 <10 ms, throughput ≥500 query/s, peak RAM <500 MB và không tăng bộ nhớ không giới hạn qua 10.000 lượt. Đây là targets, không phải lời hứa đã benchmark. Ghi CPU/core/thread/runtime, kích thước dictionary, số sense/term, normalization config, cold/warm state và độ dài fixture.

Đo query ngắn và parent dài thành hai nhóm riêng; không áp p95 query cho mọi parent 1.200 units hoặc suy tốc độ riêng Aho thành tốc độ gán nhãn toàn corpus. RSS fluctuation không tự là memory leak; báo chuỗi đo và giới hạn cache/số object giữ lại. Chưa dùng 1.200 truy vấn chính thức làm benchmark ở phase này.

### 12.4. Release profiles và lỗi

- `rejected`: có lỗi cấu trúc, nguồn/hash, accepted mapping sai hoặc runtime leak; không freeze.
- `audit_only`: dữ liệu dùng nghiên cứu, chưa đáp ứng runtime gate; không tự nạp vào hệ thống.
- `pilot_partial`: F01–F12 đạt, audit đạt gate trong phạm vi đã khai báo, còn gap ngôn ngữ/mapping được liệt kê. Không tuyên bố bao phủ đủ ba ngôn ngữ hay mọi block.
- `core_ready`: ngoài các gate trên, toàn bộ chapter/block trong core có preferred labels VI/EN/ZH đã kiểm chứng; category EN đầy đủ, category VI/ZH được phép thiếu với ledger; runtime lexicon chỉ lấy phần accepted. Đây là đủ chuẩn dữ liệu cho giai đoạn thử tagger, chưa phải chứng nhận retrieval/F2.

Không giảm tiêu chí để chuyển trạng thái. Release thiếu phần bắt buộc chỉ được gọi `pilot_partial`/`audit_only`; không dùng `APPROVED_WITH_WARNINGS` để che accepted semantic conflicts. Nếu muốn thay đổi gate đã chốt phải sửa đặc tả và được người dùng đồng ý trước.

## 13. Freeze và hợp đồng cho consumer phía sau

Release có `schema_version`, `release_id`, nguồn/edition IDs, code/config/review hashes, normalization profile, scope/coverage, trạng thái audit và SHA-256/count/bytes từng data file. `git_commit` có thể null nếu chưa có commit thích hợp; code hashes vẫn bắt buộc, không ghi giá trị giả.

Data JSONL UTF-8, newline LF, sort xác định, không timestamp hiện tại trong mỗi row. Manifest nguồn được pin; run timestamps và hiệu năng nằm ở phần audit ngoài content hash. Sau freeze đọc lại/hash/count toàn bộ output; không sửa release tại chỗ. Update tạo release mới. Quyền phân phối theo từng nguồn được ghi nhận; nguồn chưa rõ quyền không tự được gắn một license chung hoặc phát hành công khai.

Consumer phải kiểm tra release/hash/normalization compatibility, giữ ambiguity và unknown, không tự biến `context_only` thành nhãn positive. Không suy nhãn âm từ một entry/link vắng mặt. Đầu ra không sửa `doc_id`, `parent_id`, offset hay `chunk_text` của corpus.

## 14. Các điều chỉnh tường minh so với đặc tả 2.1 trước

| Điểm cũ | Quyết định ở bản này | Lý do |
|---|---|---|
| Bối cảnh 3,47 triệu tài liệu | Dùng snapshot hiện hành 1.220.598 record; 1.632.801 parent theo checkpoint | Tránh thiết kế từ số corpus cũ |
| Cây cứng chapter/block/category | Hỗ trợ block/group lồng nhau, giữ parent thật | Bảo toàn hierarchy nguồn |
| NodeKey ba trường | Thêm level | Tránh xung đột mã block identifier/category và hợp đồng code rõ ràng |
| `Ch_IV`/`Ch_04` lẫn nhau | Chapter canonical hai chữ số, raw ID giữ riêng | Một namespace nhất quán |
| NHSA/NHC clinical/procedure trộn tên | Tách hệ nguồn/edition và loại mã | Khác mục đích và bảng mã |
| T04 yêu cầu mã Trung Quốc dài phải narrower | Chỉ xác định relation bằng evidence | Độ dài không chứng minh ngữ nghĩa |
| Label đa ngữ một trạng thái chung | Assertion/provenance riêng từng ngôn ngữ | Nhãn native không tự là bản dịch tương đương của WHO |
| Flags mặc định false và ngày từ năm version | null/unknown nếu nguồn không xác nhận | Tránh dữ kiện được bịa bởi default |
| Triệu chứng/xét nghiệm mặc định một disease block | Typed link, context hoặc chính concept triệu chứng có nguồn | Tránh suy bệnh từ dấu hiệu |
| Normalize lowercase nhưng có case-sensitive flag | Hai view và kiểm case trước lower | Guard phải hoạt động thực tế |
| Performance query/parent trộn, benchmark official query | Tách nhóm, dùng fixture độc lập và báo cấu hình | Không suy diễn tốc độ hoặc tune theo bộ thi |
| Artifact verified chỉ dựa extraction | Tách extraction/semantic/acceptance | Parse đúng chưa chứng minh mapping đúng |

## 15. Điểm còn phải xác minh khi triển khai

Bytes/version/encoding nguồn tải; cấu trúc cột và counts phụ lục BYT; code hierarchy và mappings của từng edition Trung Quốc; phạm vi các modifier WHO; quyền dùng/phân phối từng source; độ phủ nhãn VI/ZH; ngưỡng và tài nguyên thực tế của audit matcher. Tất cả phải được ghi trong manifest/audit, không thay bằng khẳng định định tính từ review cũ.

Task hiện tại dừng ở đặc tả. Sau khi người dùng duyệt phạm vi/schema/gates này mới lập kế hoạch kỹ thuật và triển khai; không tạo dữ liệu, chạy test hoặc tích hợp runtime trong lượt viết đặc tả.
