# Đặc tả curate và tích hợp lexicon VI/EN/ZH

**Trạng thái:** Đã bổ sung hẹp schema v1 theo yêu cầu trực tiếp; đề xuất schema v2 và mở rộng candidate khác vẫn chờ duyệt.  
**Ngày:** 15/10/2026  
**Nguồn đầu vào:** `artifacts/retrieval/medical-lexicon-staging/20261015-run-08/`  
**Phạm vi:** Chuyển candidate staging thành resource có thể thử với analyzer BM25; không sửa nội dung tài liệu/chunk/query.

## 1. Mục tiêu và quyết định cần duyệt

Tạo bản lexicon được curate theo từng ngôn ngữ, có provenance ở cấp thuật ngữ, giảm thuật ngữ ngoài miền/fragment, và cho phép analyzer sử dụng từ để tách mà không giả định từ đó là một concept y khoa đã grounding.

**Đề xuất:** tách hai loại dữ liệu trong resource:

1. `segmentation_terms`: các cụm từ đã được duyệt để hướng dẫn Underthesea (VI) hoặc Jieba (ZH). Chúng không sinh concept anchor.
2. `concepts`: nhãn/alias có quan hệ concept được chứng minh bằng cùng mã định danh nguồn, chẳng hạn cùng `CodeSystem + code` hoặc cùng MeSH descriptor UI. Nguồn không có mapping concept không được tự gán anchor.

Hiện tại runtime chỉ đọc `resources/concepts.json`; mỗi concept cần `concept_id`, `source`, `license`, `labels`/`aliases`. Analyzer dùng aliases để tìm concept, dùng terms tiếng Trung làm Jieba user dictionary, và gửi các phrase match sang `Underthesea fixed_words`. Candidate JSONL chưa có schema này và gộp provenance ở cấp source refs. Vì vậy dùng toàn bộ candidate như concepts sẽ tạo mapping giả; dùng làm từ điển trực tiếp cũng không biểu diễn trạng thái/ngữ cảnh đủ an toàn.

Đây là thay đổi schema và cách analyzer nhận segmentation terms; runtime hiện hành phải giữ tương thích schema v1 và không chuyển mặc định sang v2 cho đến khi kiểm tra đạt.

## 2. Ranh giới dữ liệu

- Read-only đầu vào: run08, VN Core package trong `Downloads/package`, source snapshots/pins đã ghi trong manifest.
- Ghi đầu ra vào thư mục versioned mới, ví dụ `artifacts/retrieval/medical-lexicon-curated/<run_id>/`; không sửa run08 hoặc xóa các run trước.
- Không ghi đè `sbtc/Resources`, `sbtc/Scripts/Retrieval/resources/concepts.json`, index, cache, dữ liệu crawl/chunk hay submission trong bước curate.
- Chỉ chuyển resource sang đường dẫn thử nghiệm bằng flag `--lexicon` hiện có. Đổi resource mặc định là bước riêng, phải qua ablation và nghiệm thu.
- Không đọc `for_valid/`, không dùng query/qrels để tạo term hoặc alias. Chỉ đánh giá trên analyzer fixture độc lập và `data_final/test.jsonl` nếu tìm thấy/được chỉ định.
- Không dịch/tóm tắt/tạo lại thuật ngữ bằng LLM. Không dùng dịch máy hoặc chuỗi trùng bề mặt để tạo concept mapping.

## 3. Quy tắc curate theo nguồn

Mỗi term được quyết định theo cả nguồn, trường, vai trò và quyền. `quality_status=candidate` trong run08 không đủ để tự chuyển thành `approved`.

### 3.1 Tiếng Việt

- **VN Core FHIR:** chỉ lấy resource `active`, concept không `notSelectable`, đúng `display` hoặc `designation` có language VI. Giữ `system`, `version`, `code`, resource, category và copyright. Tên hoạt chất/triệu chứng ngắn có thể vào segmentation review; bài thuốc phối hợp, liều, mã phân loại và mô tả nhiều vế giữ ở review hoặc tách thành thành phần chỉ khi source có cấu trúc cho phép. Không cắt surface để tự tạo alias.
- **En-ViMedNER:** chỉ train spans đã kiểm offset. Áp dụng bộ lọc cho trial ID, mã định danh, dấu quote/bracket, fragment có ngữ cảnh, cụm quá dài và từ quá ngắn/nhập nhằng. Semantic type code chỉ dùng sau khi có mapping được duyệt; không tự coi mọi type là bệnh/thuật ngữ phân đoạn. Không tạo concept anchor từ type code.
- **VietBioNER:** mọi mention giữ review cho tới khi xác nhận cách dựng span từ CoNLL và kiểm tra lỗi token/annotation. Không tự sửa surface; bản sửa tay phải lưu cả raw và decision provenance.
- **VietENT-Text:** chỉ trường catalogue `term/group`, giữ group ENT. Không dùng câu tổng hợp. Có thể ưu tiên segmentation sau khi rà cả 235 mục; trạng thái review phát sinh do source khác không được tự hiểu là lỗi của catalogue, cần đánh giá theo từng provenance ref.

### 3.2 Tiếng Anh

- **MeSH 2026:** giữ quan hệ `preferred_descriptor_name`/`mesh_entry_term`, descriptor UI, lexical tag và tree numbers. Entry term chỉ thành alias của descriptor khi có mapping nguyên bản rõ và được rà; dấu phẩy, nhánh không lâm sàng/rộng, phrase quá dài và chemical string phức tạp giữ review. Ghi đúng NLM attribution/currentness notice.
- **FHIR English designations:** giữ cùng `CodeSystem + code` với nhãn VI nếu designation song ngữ được khai báo trong cùng concept. Nhãn YHCT tiếng Anh giữ category riêng, không trộn mặc định với thuật ngữ y sinh hiện đại.
- Không tạo từ điển tách từ EN riêng nếu analyzer Krovetz không dùng resource đó. EN terms chỉ dùng cho concept aliases có mapping hợp lệ hoặc exact-field riêng sau khi có thiết kế và kiểm tra phù hợp.

### 3.3 Tiếng Trung

- **THUOCL medical:** chỉ lấy `term`; DF chỉ để audit, không làm Jieba frequency. Rà ngoài miền, thuật ngữ phổ thông/đa nghĩa, tên biệt dược, cụm thuốc và dạng giản/phồn thể. Ví dụ `一元论`, `一年生植物`, `光电效应` hiện đều bị gắn candidate nên cần review phạm vi trước khi load.
- PKU dictionary chưa tải được ở run08; không giả định THUOCL đã thay thế độ bao phủ đó. Nếu tải được ở lần sau, tạo run mới, không ghi đè run08.
- THUOCL terms chỉ làm segmentation terms nếu được duyệt; không tạo anchor đa ngôn ngữ vì không có mapping concept ở nguồn.

## 4. Trạng thái và output

Mỗi term/provenance ref mang một trạng thái độc lập:

- `candidate`: qua lọc máy, chưa rà người.
- `review`: có dấu hiệu nhập nhằng, ngoài miền, phức hợp, lỗi span hoặc quyền cần xác minh.
- `approved_segmentation`: được duyệt để tách từ, không tạo grounding.
- `approved_concept_label` / `approved_concept_alias`: mapping concept có căn cứ và đã duyệt.
- `rejected`: không phù hợp cho mục đích cụ thể; giữ lý do và source ref trong audit, không đưa runtime.
- `blocked_rights`: quyền/notice chưa đạt điều kiện dùng trong runtime hoặc không được phân phối.

Đầu ra versioned:

```text
artifacts/retrieval/medical-lexicon-curated/<run_id>/
  segmentation_terms_vi.jsonl
  segmentation_terms_zh.jsonl
  concepts.json
  review.jsonl
  rejected.jsonl
  blocked_rights.jsonl
  source_manifest.json
  SOURCE_CATALOG.md
  REPORT.md
```

`concepts.json` tăng `schema_version` và thêm `segmentation_terms` trong khi giữ nguyên `concepts` v1; mỗi term có raw surface, normalized key, source refs, quality decision và rights status. Concept IDs được tạo ổn định từ namespace + source identifier (`CodeSystem + code`, MeSH descriptor UI). VietBioNER/En-ViMedNER/VietENT/THUOCL không được gán ID concept giả.

## 5. Tương thích analyzer và hành vi

- `Lexicon` đọc schema v1 hiện tại không đổi và đọc schema v2 mới; schema lỗi, thiếu provenance hoặc rights status chưa đạt phải fail closed.
- `MedicalAnalyzer` chỉ thêm `approved_segmentation` vào Jieba; THUOCL DF không truyền vào tần số.
- Với VI, phrase matcher riêng lấy các `approved_segmentation` thực sự xuất hiện trong câu, tôn trọng ranh giới từ, sắp xếp longest-first rồi truyền sang `Underthesea fixed_words`. Segmentation-only term không được trả về như anchor.
- `concepts` tiếp tục cung cấp anchors/aliases chỉ khi cùng concept ID được chứng minh. Tên bị map nhiều concept không grounding; vẫn có thể làm segmentation term nếu được duyệt riêng.
- Nếu v2 không có segmentation terms hợp lệ, analyzer giữ nguyên kết quả schema v1.
- Pack curated được thử qua `--lexicon <versioned path>`; không đổi default cho tới khi pass nghiệm thu.

## 6. Kế hoạch xác minh

1. **Curation audit:** số lượng theo nguồn/ngôn ngữ/status; code/ID collisions; false-positive sample; độ dài; punctuation/ID/quote; span provenance; audit mọi 235 VietENT catalogue terms và sample phân tầng các nguồn lớn.
2. **Unit tests:** schema v1 backward compatibility; v2 load; duplicate/missing IDs; rights-blocked rejected; segmentation-only không tạo anchor; concept mapping chỉ theo source ID; Unicode/case/space; VI boundary/longest match; ZH simplified/traditional; empty/large vocabulary.
3. **Analyzer fixture:** chạy fixture medical analyzer đa ngôn ngữ hiện có, báo từng case tăng/giảm match, false lock, preservation và token boundary; không sửa gold để làm pass.
4. **Resource/performance:** đo load time, peak memory, term count, serialized size và thời gian analyze cho v1/v2.
5. **Retrieval ablation:** chỉ khi có tập test được chỉ định, so baseline v1 với curated v2 trên cùng corpus/query/index snapshot; báo per-language candidate coverage, Precision/Recall/F2 nếu nhãn hợp lệ có mặt, và không suy điểm từ fixture máy móc.
6. **Publish/rollback:** giữ v1 nguyên vẹn; v2 bật qua đường dẫn/config riêng. Chỉ đổi default khi rights, semantic audit và benchmark được chấp nhận.

## 7. Tiêu chí nghiệm thu

- Không term nào có rights status unresolved được gắn approved/loadable.
- Mọi term runtime có source ref, field, version/hash, attribution và quyết định chất lượng.
- Không có anchors sinh từ chuỗi trùng hoặc semantic type code đơn lẻ.
- Các ca dương/âm trong fixture giữ đúng hành vi; false locks và regression đều được báo theo ngôn ngữ.
- Schema v1 vẫn load và analyzer v1 không đổi khi chưa bật v2.
- Output hashes, input hashes, per-source counts và reject/review reasons tái lập được.
- Không tuyên bố cải thiện truy hồi nếu chưa có retrieval benchmark đủ điều kiện.

## 8. Rủi ro và đánh đổi

| Phương án | Ưu điểm | Đánh đổi |
|---|---|---|
| Chỉ tạo concept aliases theo schema v1, không sửa analyzer | Ít rủi ro code; giữ tương thích | Không tận dụng trực tiếp En-ViMedNER/VietENT/THUOCL segmentation terms; dễ gán nhầm khái niệm nếu cố nhét mọi term vào concept |
| Schema v2 tách segmentation terms khỏi concepts (**đề xuất**) | Dùng được nguồn phrase không có concept mapping; giảm anchor giả; provenance tách rõ | Sửa `Lexicon`/`MedicalAnalyzer`, thêm test và cần curation/review riêng cho từng vai trò |

## 9. Phê duyệt cần thiết

Đề nghị duyệt phương án schema v2 tách `segmentation_terms` và `concepts`, giữ v1 tương thích và thử v2 qua `--lexicon` trước khi đổi default. Đây là thay đổi schema và hành vi analyzer; chưa triển khai cho tới khi đặc tả này được duyệt.

## Addendum — Phase 1 hẹp theo yêu cầu người dùng (2026-10-15)

Người dùng yêu cầu đọc/lọc dữ liệu và bổ sung trực tiếp `concepts.json`. Đã thực hiện một phần tương thích schema v1: thêm 80 concept VI/EN có cùng code từ `vn-communicable-disease-cs` (hash ghi trong `concepts.json`), loại A15. Đây không phải duyệt toàn bộ staging run08 và không triển khai schema v2 `segmentation_terms`; phần đề xuất schema v2 và các nguồn candidate còn lại vẫn ở trạng thái chờ.

Run08 ghi package FHIR CC-BY-4.0 nhưng yêu cầu rà quyền theo resource; metadata của seed giữ `production_ready=false` và các concept mới mang `rights_status` pending. Do runtime hiện không thực thi gate rights, chỉ dùng subset này trong nghiên cứu cục bộ cho đến khi hoàn tất rights review. Không có nhãn Trung được suy diễn từ THUOCL; cần nguồn code-aligned riêng. Không chạy retrieval ablation trong phase này.
