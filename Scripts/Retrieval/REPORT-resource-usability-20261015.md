# Đánh giá tài nguyên hiện có cho BM25 — 15/10/2026

## Phạm vi và cách kiểm

Kiểm tra dữ liệu trong `sbtc/Resources/` và contract của module Retrieval mới. Quét toàn bộ dòng để đếm, kiểm trùng, schema và collisions; đọc 45 mẫu cố định/ngôn ngữ của base, 45 mẫu aligned và các nhóm collision; đọc cả 8 dòng sample. Seed chọn mẫu 20261015. Đây là audit dữ liệu, không phải unit tests hay benchmark relevance; không đọc `for_valid`, không chạy builder hoặc code archive. Không sửa dữ liệu nguồn, không tự tích hợp vào index.

Raw audit: `artifacts/retrieval/resource-audit-20261015/audit.json` có hash, sample số dòng và collisions đầy đủ. Số mẫu không đủ chứng nhận toàn bộ dịch đúng hoặc suy tỷ lệ lỗi ngữ nghĩa của cả tập.

## Kết luận

**Có tài nguyên hữu ích để mở rộng BM25, nhưng chưa nên nạp nguyên trạng.** Ưu tiên bộ aligned 856 dòng cho lexicon đối chiếu; base tiếng Anh hỗ trợ vocabulary sau lọc; base Việt/Trung cần làm sạch mạnh. Không dùng số dòng/unique làm thước đo chuẩn thuật ngữ.

| File | Số dòng | Exact/NFKC-lower-whitespace unique | Khả năng dùng |
|---|---:|---:|---|
| base_vi.txt | 154.122 | 154.122 | Kho ứng viên cụm từ, cần lọc; không đưa toàn bộ vào fixed_words hoặc synonym |
| base_en.txt | 12.955 | 12.955 | Nhiều tên bệnh/thuật ngữ hữu ích; cần sửa mã dính và cụm quá rộng |
| base_zh.txt | 21.736 | 21.736 | Kho ứng viên bổ sung Jieba; cần bỏ mẩu câu/phủ định bị nhận làm tên bệnh |
| concepts_aligned_vi_en_zh.jsonl | 856 | 856 IDs, 839 triples VI/EN/ZH khác nhau sau lowercase | Nguồn ưu tiên cho anchors/aliases sau merge/review/schema conversion |
| medical_lexicon_vi_en_zh.sample.jsonl | 8 | Audit thủ công toàn bộ | Không dùng nguyên trạng: external IDs sai, aliases lẫn ngôn ngữ và ý nghĩa rộng |

839 triples khác nhau không có nghĩa 839 khái niệm y khoa độc lập/chính xác.

## Chứng cứ nhiễu thật

### Tiếng Việt

- Dòng2746: `bệnh cao hơn một chút`.
- Dòng9745: `bệnh gan và một số`.
- Dòng14973: `bệnh loãng xương xem thêm`.
- Dòng115413: `thuốc yêu quý`.
- Có 11.070 dòng chứa `bệnh viện`: không phải tất cả là rác, nhưng tên cơ sở cần phân loại organization riêng; nhiều cụm còn dính phần câu.
- 94.102 dòng có đúng5 từ (~61,1%). Kết hợp script regex tối đa cụm và các ví dụ bị treo cho thấy ảnh hưởng cửa sổ trích xuất, không chứng minh đây là danh mục thuật ngữ chuẩn.

Nếu khóa các mẩu này thành token, có thể thay đổi segmentation theo mẩu câu, cản khớp query ngắn và làm tăng nhiễu. Đừng truyền154k entries vào Underthesea mỗi câu: phiên bản hiện có dựng regex từ fixed_words; nên dùng matcher lấy các ứng viên thật sự xuất hiện và chọn longest nonoverlapping matches trước overlay.

### Tiếng Trung

- Dòng431: `不算糖尿病` — chứa sắc thái phủ định/không được tính là tiểu đường, không phải tên bệnh đồng nghĩa với 糖尿病.
- Dòng10586: `指责孩子` — mắng/chỉ trích trẻ, không phải thuật ngữ y khoa.
- Dòng8337: `年的慢性咽炎` — mẩu câu có phần thời gian.
- Dòng18443: `节和肌肉疼痛` — bắt đầu giữa cụm.

Thêm nguyên bộ vào Jieba có nguy cơ gắn chặt phủ định/mẩu câu thành một token. Không xóa phủ định khỏi nội dung nguồn; giữ nó trong query/index và loại cụm không phù hợp khỏi từ điển dẫn xuất.

### Tiếng Anh

Trong mẫu có nhiều tên rõ như `adrenal gland`, `deep vein thrombosis nos`, `chronic conjunctivitis`, nhưng vẫn có lỗi:

- Dòng934: `anthrax meningitisg01`.
- Dòng7764: `meningococcal meningitisg01`.
- Dòng12348: `tuberculous meningitisg01`.

Có dấu hiệu mã G01 dính vào nhãn. Những cụm chung như `fat`, `inflammatory disorder`, `neurological burden of disease` không nên được coi như tên bệnh cụ thể hoặc alias tương đương vô điều kiện. Chưa đối chiếu từng term với ontology nguồn.

## Bộ aligned856

- Cả856 dòng parse JSON được, đủ chuỗi VI/EN/ZH, ID khác nhau.
- Có155 dòng có icd10_code; chưa kiểm đúng từng mapping code/label với phiên bản ICD chính thức.
- Không dòng nào chứa trường source/license. Không đồng nghĩa nguồn bị cấm; provenance/điều kiện tái sử dụng chưa được ghi trong artifact.
-17 nhóm lặp nguyên triple dưới ID khác nhau (17 dòng dư); nhãn lặp giữa nhiều IDs: VI27 nhóm/54 dòng, EN23/46, ZH29/58. Những số này giao nhau, không cộng lại thành tổng số dòng lỗi.
- Ví dụ `đau đầu`: dòng1 MC0001 và dòng532 MX0154 có cùng cả ba nhãn. Nếu chỉ thêm namespace rồi nạp nguyên bộ, matcher hiện tại thấy một term trỏ hai IDs và bỏ grounding term đó vì ambiguity.
- Có các collision cần xem hierarchy thay vì merge mù: `chronic obstructive pulmonary disease` ở dòng89 và472, trong khi dòng472 VI/ZH có chữ “khác”/“其他”. Nhãn EN giống không đủ kết luận khái niệm hoàn toàn bằng nhau.

Đề xuất: tạo bản dẫn xuất, giữ mapping original_id→canonical_id, merge các triple trùng; aliases/same-concept chỉ gộp khi kiểm nghĩa. Preserve ICD/version/evidence riêng. Dùng namespace local cho MC/MX, không tự quảng bá thành MeSH/UMLS.

## File sample8: external IDs không đáng tin

Dòng1 gán Q12136 cho renal failure, nhưng [Wikidata Q12136](https://www.wikidata.org/wiki/Q12136) là disease. Dòng5 gán Q181754 cho paracetamol, nhưng [Wikidata Q181754](https://www.wikidata.org/wiki/Q181754) là heart failure. Hai mapping được đối chiếu trực tiếp; chưa xác minh sáu QIDs còn lại.

Aliases như `hạ sốt` trỏ paracetamol hoặc `thuốc kháng đông` trỏ aspirin là nhóm chức năng/điều trị được đưa chung vào alias, không có evidence exact-equivalence trong file; cần chuyên môn xác nhận quan hệ và không mở rộng thành synonym cứng. `aliases` còn là list pha ngôn ngữ, cần phân ngôn ngữ rõ. Giá trị ambiguity=false không chứng minh term không mơ hồ.

## Nguồn tạo và nguyên nhân khả dĩ

Script `sbtc/Scripts/build_expanded_base_resources.py` cho thấy: đọc base labels từ CSV medical_queries_60k_aligned trong Downloads, XML ICD, một resource module archive và regex mining từ test20k cùng150 shards đầu full. Chỉ đọc script này để truy vết; không import/đọc module archive hoặc chạy lại builder.

- CSV/ICD input không có provenance/license/checksum được gắn theo từng output entry. Chưa xác minh quan hệ của CSV với bộ validation bị loại khỏi phạm vi; không kết luận chắc chắn độc lập nhãn.
- Corpus regex không phải NER có xác nhận loại thực thể. Ngưỡng xuất hiện>=2 tính trên chunks có thể đếm lại cùng nội dung do overlap hoặc test20k trùng full; không phải hai tài liệu độc lập.
- Giới hạn từ/regex có thể giữ mẩu câu; bộ lọc bị bypass với fallback raw ở một số nguồn.
- Có except Exception: pass, nên script không đủ evidence mọi shard đều được xử lý thành công.

Khẳng định lịch sử “độc nhất” đúng ở mức exact/normalized lines ba base. Khẳng định “gọt sạch100% rác/ngữ pháp” không phù hợp với ví dụ audit; không tái dùng làm chứng nhận chất lượng.

## Tích hợp được vào đâu?

1. **Đối chiếu ba ngôn ngữ:** ưu tiên aligned856 đã hợp nhất/rà soát → labels, aliases, anchors.
2. **Tokenizer:** dùng base sạch riêng theo ngôn ngữ; VI medical overlay và ZH user dictionary. EN làm protected terms/aliases được kiểm chứng; không mặc định mọi term phải nối thành token.
3. **Broad recall:** các ứng viên chưa đủ tin cậy chỉ nên thử ở kênh phụ có trọng số thấp; không biến thành neo concept chắc chắn.
4. **Không phải bản dịch toàn query:**856 triplets và ba danh sách đơn ngữ không thay model/cache dịch phần ngữ cảnh tuổi, phủ định, thời gian, intent.

Ba base độc lập không có row alignment; tuyệt đối không ghép dòng thứ i của ba file để tạo khái niệm. Adapter hiện nhận JSON object metadata/concepts, labels/aliases map language→list, IDs có namespace và source/license; cả hai JSONL hiện có cần converter trước khi dùng. Nạp dictionary index/anchor mới phải chọn snapshot mới và reindex để query/index dùng cùng fingerprint.

## Bước tiếp theo đề xuất

Viết spec converter/curation → xuất riêng approved/review/rejected với lý do, provenance và mapping IDs → đo số tài liệu khớp lexicon trên đúng test20k → ablation index/query bằng bản dẫn xuất mới. Đánh giá segmentation và candidate coverage độc lập; không suy F2 tăng từ số từ tăng, không dùng for_valid. Chưa thực hiện tích hợp hay thay index trong lần audit này.
