# ĐẶC TẢ KỸ THUẬT: XÂY DỰNG ICD-10 TAXONOMY VÀ BỘ TỪ ĐIỂN ĐA NGỮ (VI / EN / ZH)

> Dự thảo thu hẹp và làm rõ riêng bước chuẩn bị taxonomy/lexicon: [SPEC-icd10-foundation.md](SPEC-icd10-foundation.md). Bản mới đang chờ duyệt; ghi rõ các điều chỉnh so với 2.1 tại mục 14. Tài liệu 2.1 này được giữ để đối chiếu yêu cầu và lịch sử, không được coi các con số/nhận định cũ là kết quả thực nghiệm đã đạt.

- **Trạng thái:** Technical Review — Changes Required (Sẵn sàng triển khai Pilot có kiểm soát)
- **Phiên bản:** 2.1.0 (Bổ sung toàn diện Cơ chế Kiểm toán Độc lập, Phân loại Lỗi & Đóng băng Dữ liệu Bất biến Phase 1d)
- **Ngày cập nhật:** 16/10/2026
- **Mục tiêu:** Thiết lập tầng tri thức nền tảng (Knowledge Grounding Layer) phục vụ gán nhãn Silver Dataset, mô hình phân loại FastText, chỉ mục BM25 Đa tầng và Reranking ngữ nghĩa.
- **Quy chuẩn tuân thủ:** Bất biến ViBioMIR, Quy chuẩn đối chiếu 5 bước của BTC, Ràng buộc bảo toàn mã định danh, Khóa composite versioned, Plain Verbatim Text và Quy trình Release Gate nghiêm ngặt.

---

## 1. Mục Đích & Bối Cảnh Hệ Thống

### 1.1. Tại sao Taxonomy và Lexicon là bước tiên quyết số 1?
Trong bài toán ViBioMIR, truy vấn y khoa tiếng Việt ($Q_{\text{vi}}$) cần được đối chiếu chéo với kho ngữ liệu 3,47 triệu tài liệu đa ngữ (Tiếng Việt, Tiếng Anh, Tiếng Trung) với mục tiêu tối ưu hóa trực tiếp hàm mục tiêu **Macro $F_2$** (ưu tiên Recall gấp 2 lần Precision).

Nếu hệ thống thực thể hoặc taxonomy bị sai lệch:
1. **Silver Dataset học sai:** Các nhãn gán tự động sẽ bị ô nhiễm (noise propagation).
2. **FastText / BM25 mất Recall:** Tách từ sai ranh giới thực thể, không bắt được các cách gọi đời thường, từ viết tắt hoặc bị nhầm lẫn giữa triệu chứng lâm sàng với chẩn đoán xác định.
3. **Reranker bị quá tải:** Khi phễu tầng 1 (BM25) kéo về các tài liệu nhiễu do nhập nhằng từ vựng, điểm $F_2$ toàn cục sẽ sập nghiêm trọng.

Do đó, **Phase 1** tập trung xây dựng hai bảng dữ liệu độc lập, chuẩn hóa cao:
- **Bảng 1 (Taxonomy):** Cây phân cấp chuẩn quốc tế ICD-10 gắn nhãn song ngữ 3 chiều (VI / EN / ZH) ở mọi cấp độ (Chương $\to$ Khối $\to$ Mã 3 ký tự $\to$ Mã 4/5 ký tự) sử dụng khóa định danh phức hợp có phiên bản.
- **Bảng 2 (Multilingual Lexicon):** Bộ từ vựng y tế lâm sàng và đời thường có quan hệ ngữ nghĩa mềm dẻo (`links`), phân biệt rạch ròi giữa tên bệnh, cách gọi thông tục, từ viết tắt, dấu hiệu/xét nghiệm và các cụm chỉ định ngữ cảnh (phủ định, nghi ngờ, tiền sử).

---

## 2. Nguồn Dữ Liệu & Đối Soát Từng Bản Phát Hành

Hệ thống tích hợp và đồng bộ 4 nhóm nguồn dữ liệu chính thống với quy trình đối soát chặt chẽ:

| Nguồn | Vai trò trong Pipeline | Định dạng & Giao thức thu thập | Trách nhiệm dữ liệu & Lưu ý đối soát |
|---|---|---|---|
| **WHO ICD-10 2019** | Khung cấu trúc quốc tế gốc (Chương, Khối, Mã 3 ký tự, Mã 4 ký tự, Inclusions/Exclusions, Nhãn EN) | File nén chính thức: `claml/icd102019en.xml.zip` (Chuẩn XML ClaML ISO 13120) và `meta/icd102019enMeta.zip` (Plain text tabular) từ `https://icdcdn.who.int/icd10/`. | **ClaML là nguồn chân lý cấu trúc** (quan hệ `SuperClass`/`SubClass`, inclusions, exclusions). Bản Tabular metadata chỉ dùng đối soát mã nhanh, không thay thế ClaML do thiếu inclusion/exclusion. |
| **BYT TT 06/2026/TT-BYT** | Danh mục chuẩn Việt Nam hiện hành (Nhãn VI, mã mở rộng, cờ sử dụng và đặc thù Việt Nam) | Văn bản pháp quy ban hành 02/04/2026 (hiệu lực 01/07/2026) kèm phụ lục 16.052 mã (`06-byt-kem.pdf` tại Cổng TTĐT Chính phủ, QĐ 1849/QĐ-BYT hướng dẫn kỹ thuật mã hóa, kết hợp VN Core FHIR ICD-10 / CCMS catalog). | **Phân biệt rõ:** VN Core FHIR v0.10.0 (Draft) chứa 16.052 concept (15.844 active, 208 inactive), dùng làm nguồn máy đọc được để tăng tốc, nhưng phải đối soát với văn bản pháp lý ký chính thức. Bắt buộc bảo toàn **6 cờ sử dụng mã** (cột 24–29). |
| **NHSA ICD-10 & National Clinical 2.0 (Trung Quốc)** | Nguồn thuật ngữ tiếng Trung chuẩn hóa theo mã bệnh | Danh mục mã hóa bệnh tật Quốc gia Trung Quốc (国家医疗保障局 医保版 ICD-10, 国家临床版 2.0 / 3.0, kết hợp kho chuẩn hóa mở `chaseliu/ICD-10-CN` và từ điển CMeSH / THUOCL-Medical). | Cục NHSA công khai lưu ý bản thanh toán bảo hiểm và bản lâm sàng có khác biệt. **Tuyệt đối không tự động cắt chuỗi 6 ký tự về 4 ký tự để gán exact_match**. Bắt buộc lưu mã nguồn riêng và gán loại quan hệ (`exact_match`, `narrower_than`,...). |
| **Từ Điển Y Khoa Thẩm Định & Lâm Sàng** | Đồng nghĩa, khẩu ngữ dân gian, viết tắt lâm sàng và bằng chứng hỗ trợ | NLM MeSH 2026 (tuyển chọn các nhóm chuyên biệt), VN Core FHIR CodeSystems (Dược chất, YHCT), VietBioNER, En-ViMedNER, và Bộ từ vựng khẩu ngữ thực nghiệm (`Medical Slang Normalizer`). | Phân loại rõ mục đích: Nhóm C (Bệnh tật), Nhóm D (Thuốc/hóa chất), Nhóm E (Kỹ thuật/xét nghiệm/thủ thuật -> làm bằng chứng hỗ trợ). Loại trừ các nhóm phi lâm sàng (Z, V, I, J, M, K). |

---

## 3. Kiến Trúc & Cấu Trúc Dữ Liệu Chi Tiết

### 3.1. Bảng 1: `taxonomy.jsonl` (Cây Phân Loại Chuẩn Hóa Có Phiên Bản)

Thay vì chỉ dùng `code` làm khóa chính đơn lẻ (dễ gây xung đột khi cùng một mã có ý nghĩa hoặc trạng thái khác nhau giữa các hệ thống/phiên bản), mỗi nút phân loại được định danh duy nhất bởi bộ ba:
$$\text{NodeKey} = (\text{system}, \text{version}, \text{code})$$

#### Schema JSON Chi Tiết:
```json
{
  "system": "WHO_ICD10",
  "version": "2019",
  "code": "E11",
  "level": "category",
  "chapter": "Ch_IV",
  "block": "E10-E14",
  "parent_code": "E10-E14",
  "status": "active",
  "valid_from": "2019-01-01",
  "valid_to": null,
  "labels": {
    "en": "Type 2 diabetes mellitus",
    "vi": "Đái tháo đường típ 2",
    "zh": "2型糖尿病"
  },
  "label_status": {
    "en": "official",
    "vi": "official",
    "zh": "crosswalk_mapped"
  },
  "inclusions": {
    "en": ["Diabetes (mellitus): non-obese", "Diabetes (mellitus): obese"],
    "vi": ["Đái tháo đường: không béo phì", "Đái tháo đường: béo phì"],
    "zh": null
  },
  "exclusions": {
    "en": ["diabetes mellitus in pregnancy, childbirth and the puerperium (O24.-)"],
    "vi": ["đái tháo đường trong thai kỳ, khi sinh và thời kỳ sau sinh (O24.-)"],
    "zh": null
  },
  "dagger_asterisk": null,
  "paired_codes": [],
  "usage_flags": {
    "not_primary_diagnosis": false,
    "primary_diagnosis_discouraged": false,
    "requires_more_specific_code": false,
    "mortality_only": false,
    "female_only_or_predominant": false,
    "male_only_or_predominant": false
  },
  "verification_status": "source_verified",
  "verification_method": "claml_parsing",
  "source_ref": "who_claml_2019:E11",
  "review_note": null
}
```

#### Quy chuẩn các trường trong `taxonomy.jsonl`:
1. `system` (string, trong NodeKey): Hệ thống phân loại gốc (`"WHO_ICD10"`, `"BYT_ICD10"`, `"NHSA_ICD10"`).
2. `version` (string, trong NodeKey): Phiên bản chuẩn (`"2019"`, `"2026"`, `"2.0"`).
3. `code` (string, trong NodeKey): Mã bệnh chuẩn hóa (`"E11"`, `"E11.9"`, `"Ch_04"`).
4. `level` (enum): `"chapter"` | `"block"` | `"category"` | `"subcategory"`.
5. `status` (enum): `"active"` (hiện hành) | `"inactive"` (đã hủy/ngưng dùng) | `"deprecated"`.
6. `valid_from` & `valid_to`: Ngày hiệu lực pháp lý (ví dụ: BYT TT 06/2026 có `valid_from: "2026-07-01"`).
7. `labels` & `label_status`: Cho phép nhãn thiếu có kiểm soát (`null`), đi kèm trạng thái xuất xứ (`"official"`, `"crosswalk_mapped"`, `"missing"`). Cấm dùng dịch máy tự động để bù đắp.
8. `usage_flags`: Bảo toàn nguyên vẹn **6 cờ quy định** trong TT 06/2026/TT-BYT (cột 24–29).
9. `dagger_asterisk` & `paired_codes`: Lưu mã kép nguyên nhân (`†`) và biểu hiện (`*`), xác nhận theo dữ liệu thực từ ClaML và BYT.
10. `verification_status` (enum): `"raw"` $\to$ `"normalized"` $\to$ `"source_verified"` $\to$ `"crosswalk_verified"` $\to$ `"reviewed"`, `"rejected"`, `"conflict"`.

---

### 3.2. Bảng 2: `lexicon.verified.jsonl` (Bộ Từ Điển Đa Ngữ & Quan Hệ Ngữ Nghĩa Mềm Dẻo)

Thay vì bắt buộc `chapter` và `block`, bảng lexicon sử dụng mảng `links: list[dict]` mềm dẻo.

#### Schema JSON Chi Tiết:
```json
{
  "term_raw": "HbA1c cao",
  "term_normalized": "hba1c cao",
  "term_original_script": null,
  "language": "vi",
  "kind": "diagnostic_test",
  "specificity": "context_evidence",
  "case_sensitive": false,
  "co_occurrence_triggers": [],
  "context_window": 0,
  "links": [
    {
      "target_system": "WHO_ICD10",
      "target_version": "2019",
      "target_type": "block",
      "target_code": "E10-E14",
      "relation": "supporting_evidence"
    }
  ],
  "verification_status": "reviewed",
  "verification_method": "clinical_guideline",
  "source_ref": "ada_guidelines_2026",
  "review_note": "Chỉ số xét nghiệm đường huyết hỗ trợ khối đái tháo đường, không kết luận bệnh cụ thể"
}
```

#### Quy chuẩn các trường trong `lexicon.verified.jsonl`:
1. `term_raw`: Thuật ngữ nguyên bản, giữ nguyên hoa/thường và bảng mã gốc.
2. `term_normalized`: Chuỗi sau khi chuẩn hóa qua **NFKC**, chữ thường, khử khoảng trắng thừa (và OpenCC `t2s` đối với tiếng Trung).
3. `term_original_script`: Ghi nhận bảng mã gốc (ví dụ: `"traditional_hant"`).
4. `kind`: `"official_disease"`, `"colloquial"`, `"abbreviation"`, `"symptom_sign"`, `"diagnostic_test"`, `"treatment_procedure"`, `"contextual_modifier"`.
5. `links`: Danh sách liên kết với hệ thống ICD-10 (`target_system`, `target_version`, `target_type`, `target_code`, `relation`). Đối với `contextual_modifier` (phủ định, nghi ngờ, tiền sử), `links` là mảng rỗng `[]`.
6. `case_sensitive`, `co_occurrence_triggers`, `context_window`: Cấu hình nhận diện từ viết tắt có điều kiện.

---

## 4. Phân Nhóm Thuật Ngữ & Đính Chính Phân Loại Lâm Sàng

1. **Đính chính ranh giới Bệnh vs Triệu chứng:**
   - *Đau dạ dày / Đau bao tử:* Là triệu chứng (`symptom_sign`), gán quan hệ `relation: "supporting_evidence"` trỏ về khối `K20-K31`, tuyệt đối **không** coi là `exact_match` của viêm loét dạ dày tá tràng (`K25-K29`).
   - *HbA1c cao:* Là xét nghiệm (`diagnostic_test`), liên kết `relation: "supporting_evidence"` vào `E10-E14`.
2. **Bãi bỏ quy tắc cứng 2 âm tiết:** Các unigram tiếng Anh (*pneumonia*, *hypertension*, *gout*, *scabies*) có tính đặc hiệu lâm sàng gần 100%. Áp dụng 4 tiêu chí định lượng (Đặc hiệu lâm sàng, Nguy cơ nhập nhằng, Khớp nguyên chuỗi, Đo đạc thực nghiệm).
3. **Đồng nhất quy tắc chuẩn hóa:** Thống nhất 100% giữa Lexicon và văn bản lúc matching: NFKC $\to$ hạ chữ thường $\to$ gộp khoảng trắng $\to$ OpenCC `t2s` (với tiếng Trung) $\to$ Half-width số và ký tự Latinh.

---

## 5. Bảng Đối Chiếu Cạnh (Crosswalk Edges) & Xử Lý Mã Trung Quốc

Không tự động cắt tiền tố mã 6 ký tự Trung Quốc để gán `exact_match` cho mã 4 ký tự WHO. Bảng `crosswalk_edges.jsonl` ghi nhận chi tiết từng cạnh ánh xạ với 6 loại quan hệ: `exact_match`, `narrower_than`, `broader_than`, `related_match`, `unmapped`, `conflict`.

#### Schema của `crosswalk_edges.jsonl`:
```json
{
  "source": {
    "system": "NHSA_ICD10",
    "version": "clinical_v2",
    "code": "E11.201"
  },
  "target": {
    "system": "WHO_ICD10",
    "version": "2019",
    "code": "E11.2"
  },
  "relation": "narrower_than",
  "verification_status": "source_verified",
  "verification_method": "nhsa_official_mapping_table",
  "review_note": "Mã lâm sàng 6 số Trung Quốc chi tiết hơn mã 4 số WHO"
}
```

---

## 6. Bộ Artifact Bàn Giao Đầy Đủ Của Phase 1

Toàn bộ kết quả được quy hoạch độc lập tại `artifacts/taxonomy/`:

```
artifacts/taxonomy/
├── taxonomy.jsonl                      # Cây phân loại chuẩn hóa có phiên bản (Bảng 1)
├── lexicon.verified.jsonl              # Bộ từ vựng đa ngữ & bằng chứng ngữ cảnh (Bảng 2)
├── version_crosswalk.json              # Tổng hợp ma trận đối chiếu phiên bản
├── crosswalk_edges.jsonl               # Chi tiết từng cạnh đối chiếu WHO-BYT-NHSA kèm loại quan hệ
├── unresolved_mappings.jsonl           # Danh sách mã thiếu nhãn, unmapped, xung đột cần rà soát
├── duplicate_and_ambiguity_report.json # Báo cáo chi tiết các mã trùng và thuật ngữ nhập nhằng
├── source_manifest.json                # Bảng kê nguồn, URL, version, timestamp, license, SHA-256
│
├── audit/                              # Báo cáo kiểm toán tự động và thực nghiệm
│   ├── pytest_results.xml              # Kết quả thực thi test suite dạng XML
│   ├── validation_results.json         # Chi tiết kiểm thử cấu trúc T01 - T11
│   ├── semantic_audit.json             # Kết quả kiểm toán ngữ nghĩa trên tập Gold Test
│   ├── performance_benchmark.json      # Benchmark latency, memory, throughput
│   └── REPORT_taxonomy_and_lexicon_phase1.md # Báo cáo nghiệm thu bằng chứng toàn diện
│
└── releases/                           # Bản phát hành bất biến (Immutable Releases)
    └── taxonomy-v1.0.0/
        ├── freeze_manifest.json        # Bản kê đóng băng (Release ID, Git commit, Checksum SHA-256)
        ├── taxonomy.jsonl
        ├── lexicon.verified.jsonl
        ├── version_crosswalk.json
        ├── crosswalk_edges.jsonl
        ├── unresolved_mappings.jsonl
        ├── duplicate_and_ambiguity_report.json
        └── source_manifest.json
```

---

## 7. Tiêu Chí Nghiệm Thu Bắt Buộc (T01 – T11) & Phân Loại Lỗi

### 7.1. Bảng 11 Tiêu Chí Nghiệm Thu (Acceptance Criteria)

| ID | Hạng mục kiểm thử | Điều kiện nghiệm thu (PASS / FAIL Criteria) | Mức độ lỗi |
|:---:|---|---|:---:|
| **T01** | **Schema & Uniqueness** | 100% bản ghi hợp lệ theo JSON Schema đã version hóa; 0 trùng lặp khóa phức hợp `(system, version, code)`. | **P0** |
| **T02** | **Hierarchical Integrity** | Không orphan code, không chu trình (acyclic đồ thị); mọi nút cha (`parent_code`) phải tồn tại hợp lệ trong cùng hệ thống/phiên bản. | **P0** |
| **T03** | **Source Reconciliation** | 100% mã thiếu hoặc chênh lệch so với nguồn đều được giải trình (đối soát 16.052 concepts của VN Core FHIR gồm 15.844 active và 208 inactive). | **P0** |
| **T04** | **Crosswalk Validation** | Tuyệt đối không dùng ánh xạ `exact_match` chưa được xác minh làm dữ liệu chuẩn phát hành; cạnh 6 ký tự NHSA phải là `narrower_than`. | **P0** |
| **T05** | **ICD Coding Rules & Flags** | Kiểm tra các quan hệ Dagger/Asterisk thực tế từ ClaML và BYT; bảo toàn 100% 6 nhóm cờ `usage_flags` cho mã BYT. | **P1** |
| **T06** | **Multilingual Coverage** | Đo tỷ lệ nhãn VI, EN, ZH theo từng cấp mã; 100% mã thiếu nhãn phải được ghi nhận vào `unresolved_mappings.jsonl`, cấm dùng dịch máy tự động bù đắp. | **P1** |
| **T07** | **Lexicon Semantic Integrity** | Loại quan hệ phù hợp, mọi `target_code` trong `links` có thực; tuyệt đối không ép triệu chứng lâm sàng thành chẩn đoán xác định. | **P0** |
| **T08** | **Ambiguity & Context Testing** | Kiểm thử độc lập trên bộ dữ liệu kiểm định ngữ nghĩa riêng (`semantic_gold_test.jsonl`) bao phủ từ viết tắt có điều kiện, phủ định, nghi ngờ, tiền sử và phồn/giản thể. | **P1** |
| **T09** | **Normalization & Verbatim** | Luật chuẩn hóa đạt tính lũy đẳng: `normalize(normalize(x)) == normalize(x)`; bảo toàn nguyên vẹn `term_raw` và 100% Plain Verbatim Text. | **P0** |
| **T10** | **Performance & Stability** | Benchmark trên cả query ngắn và parent dài: Latency p95 $< 10\text{ ms}$ / query, throughput $\ge 500$ queries/sec, RAM peak $< 500\text{ MB}$, 0 rò rỉ bộ nhớ dưới 10.000 vòng lặp. | **P1** |
| **T11** | **Reproducibility & Provenance** | 100% tệp đầu vào có SHA-256, URL, version trong `source_manifest.json`; quá trình build tái lập deterministic 100%. | **P0** |

### 7.2. Phân loại Mức Độ Nghiêm Trọng Của Lỗi (Error Severity Levels)
- **P0 (Blocker — Chặn phát hành tuyệt đối):** Lỗi schema, trùng khóa định danh, orphan code, quan hệ cha-con vòng tròn, ánh xạ `exact_match` sai lệch, gán nhầm triệu chứng thành bệnh xác định, chênh lệch mã nguồn không giải trình được. $\to$ **Kết luận tự động: REJECTED, cấm đóng băng dữ liệu.**
- **P1 (Major — Cảnh báo nghiêm trọng):** Tỷ lệ bao phủ đa ngữ ở cấp Subcategory chưa đạt ngưỡng mục tiêu, quan hệ Dagger/Asterisk chưa hoàn tất đối ứng hai chiều, từ viết tắt mơ hồ chưa có đủ từ khóa kích hoạt lâm sàng. $\to$ **Kết luận: APPROVED_WITH_WARNINGS (cho phép freeze có phạm vi sử dụng hạn chế sau khi người dùng phê duyệt văn bản).**
- **P2 (Minor — Ghi nhận cải thiện):** Thiếu nhãn ở các mã hiếm/mở rộng cục bộ, các biến thể khoảng trắng đã được bóc tách an toàn. $\to$ **Ghi nhận log kiểm toán, không chặn phát hành.**

---

## 8. Lộ Trình Triển Khai Thực Hiện Chi Tiết

### Giai đoạn 1a: Thu thập Nguồn & Pipeline Staging Độc lập
1. Tạo `artifacts/taxonomy/source_manifest.json` ghi nhận SHA-256, URL, version của toàn bộ các file nguồn:
   - `who_claml_2019`: `claml/icd102019en.xml.zip` và `meta/icd102019enMeta.zip`.
   - `byt_tt06_2026`: `06-byt-kem.pdf` và VN Core FHIR `CodeSystem-vn-*.json`.
   - `nhsa_clinical_v2`: Kho mã hóa chuẩn hóa `chaseliu/ICD-10-CN` và CMeSH.
   - `mesh_2026`: NLM MeSH 2026 (nhóm C, D, E).
2. Xây dựng các parser staging độc lập xuất ra `artifacts/taxonomy/staging/`:
   - `ingest_who_claml.py` $\to$ `staging/who_taxonomy_raw.jsonl`.
   - `ingest_byt_icd10.py` $\to$ `staging/byt_taxonomy_raw.jsonl` (bảo toàn 6 cờ `usage_flags` và phân định 15.844 active vs 208 inactive).
   - `ingest_nhsa_zh.py` $\to$ `staging/zh_taxonomy_raw.jsonl` (chuẩn hóa OpenCC `t2s` và Half-width).

### Giai đoạn 1b: Đối Chiếu Cạnh & Xử Lý Xung Đột (Crosswalk Engine)
3. Xây dựng `crosswalk_builder.py`: Khớp nối mã 3 chiều theo `NodeKey = (system, version, code)`.
   - Phân loại quan hệ ngữ nghĩa chuẩn (`exact_match`, `narrower_than`, `broader_than`,...).
   - Xuất xưởng:
     - `artifacts/taxonomy/taxonomy.jsonl`
     - `artifacts/taxonomy/crosswalk_edges.jsonl`
     - `artifacts/taxonomy/unresolved_mappings.jsonl`
     - `artifacts/taxonomy/duplicate_and_ambiguity_report.json`
     - `artifacts/taxonomy/version_crosswalk.json`

### Giai đoạn 1c: Curation Lexicon Đa Ngữ & Bằng Chứng Ngữ Cảnh
4. Xây dựng `lexicon_curator.py`:
   - Trích xuất từ vựng từ MeSH (C, D, E), VN Core FHIR và Slang Normalizer.
   - Thiết lập cấu trúc `links: list[dict]` mềm dẻo.
   - Cấu hình `case_sensitive`, `co_occurrence_triggers` và `context_window` cho từ viết tắt.
   - Xuất xưởng: `artifacts/taxonomy/lexicon.verified.jsonl`.

---

### Giai đoạn 1d — Comprehensive Audit & Data Freeze

#### Bước 5 — Automated Validation & Semantic Audit
1. **Thiết lập Bộ dữ liệu Kiểm định Ngữ nghĩa Riêng (`semantic_gold_test.jsonl`):**
   - Xây dựng tối thiểu **200 ca kiểm định ngữ nghĩa lâm sàng độc lập** (không sinh từ rule tự động), bao phủ cả 3 ngôn ngữ VI, EN, ZH:
     - 50 ca Tên bệnh chính thức (Precision mapping $\ge 99\%$).
     - 50 ca Khẩu ngữ đời thường & Viết tắt nhạy cảm (`ALL`, `WAS`, `COLD`, `MS`, `ĐTĐ`, `THA`).
     - 40 ca Triệu chứng/Xét nghiệm (Kiểm tra `code == null` và `relation == "supporting_evidence"`).
     - 30 ca Cụm từ biến đổi ngữ cảnh (Phủ định, nghi ngờ, tiền sử).
     - 30 ca Chữ Hán phồn thể / giản thể và số Half-width.
2. **Thực thi Kiểm thử Tự động:**
   ```bash
   python -m pytest \
       sbtc/tests/test_taxonomy_and_lexicon.py \
       -v \
       --tb=short \
       --junitxml=artifacts/taxonomy/audit/pytest_results.xml
   ```
3. **Thực thi Benchmark Hiệu năng & Rò rỉ Bộ nhớ:**
   - Chạy script đo lường `benchmark_taxonomy_runtime.py`: Đo latency p50/p95 trên 1.200 queries của `query.parquet` và các parent chunks dài; ghi lại peak RAM và theo dõi memory growth qua 10.000 lượt matching Aho-Corasick.
   - Xuất xưởng các tệp log kiểm toán:
     - `artifacts/taxonomy/audit/pytest_results.xml`
     - `artifacts/taxonomy/audit/validation_results.json`
     - `artifacts/taxonomy/audit/semantic_audit.json`
     - `artifacts/taxonomy/audit/performance_benchmark.json`

#### Bước 6 — Evidence-Based Audit Report
Hệ thống tự động tổng hợp toàn bộ số liệu thực tế từ các tệp log và xuất ra báo cáo chính thức:
`artifacts/taxonomy/audit/REPORT_taxonomy_and_lexicon_phase1.md`

**Báo cáo bắt buộc có 11 mục chi tiết:**
1. **Executive Summary:** Tổng quan kết quả kiểm thử và khuyến nghị phát hành.
2. **Source Provenance:** Danh sách nguồn WHO, BYT, NHSA, phiên bản, ngày thu thập và SHA-256.
3. **Data Inventory:** Thống kê thực tế số lượng mã theo cấp (Chapter, Block, Category, Subcategory), số lượng mục từ theo ngôn ngữ và nhóm thực thể (`kind`).
4. **Validation Results (T01 – T11):** Bảng tổng hợp trạng thái PASS/WARN/FAIL cho từng tiêu chí, chi tiết số lượng vi phạm (nếu có).
5. **Crosswalk Quality:** Tỷ lệ % các loại quan hệ `exact_match`, `narrower_than`, `broader_than`, `unmapped`, `conflict`.
6. **Multilingual Coverage:** Tỷ lệ % nhãn VI, EN, ZH theo từng cấp mã; thống kê danh sách mã thiếu.
7. **Semantic Audit Results:** Điểm Precision, Recall, $F_1$ đo được trên `semantic_gold_test.jsonl` kèm phân tích các ca thất bại.
8. **Performance Benchmark:** Thống kê độ trễ p50, p95, throughput (queries/s), peak RAM (MB), thời gian nạp Automaton.
9. **Unresolved Issues & Risk Matrix:** Danh sách toàn bộ các vấn đề còn tồn đọng phân loại theo mức độ P0, P1, P2.
10. **Release Decision:** Đưa ra kết luận chính thức: `APPROVED` / `APPROVED_WITH_WARNINGS` / `REJECTED`.
11. **Freeze Manifest Preview:** Xem trước mã băm SHA-256 của từng tệp dữ liệu dự kiến đóng băng.

> [!CAUTION]
> **Quy tắc Liêm chính Dữ liệu:**
> Toàn bộ số liệu trong báo cáo phải được tính toán trực tiếp từ artifact và log thực tế. Tuyệt đối cấm điền số liệu ước lượng, số liệu giả định hoặc làm tròn tùy tiện.

#### Bước 7 — Release Gate & Immutable Data Freeze
1. **Đánh giá Điều kiện Release Gate:**
   - **`APPROVED`:** Toàn bộ kiểm thử T01–T11 đạt PASS; 0 lỗi P0; KPI Semantic Precision $\ge 98\%$; tỷ lệ giải trình nguồn đạt 100%. $\to$ Đủ điều kiện đóng băng dữ liệu chuẩn sản xuất.
   - **`APPROVED_WITH_WARNINGS`:** 0 lỗi P0; chỉ còn một số cảnh báo P1 (ví dụ: một số mã hiếm chưa có nhãn ZH nhưng đã nằm trong `unresolved_mappings.jsonl`); người dùng đã xác nhận bằng văn bản. $\to$ Cho phép đóng băng với phạm vi sử dụng hạn chế.
   - **`REJECTED`:** Tồn tại bất kỳ lỗi P0 nào hoặc kiểm thử tự động thất bại. $\to$ **Dừng quy trình, cấm đóng băng, tạo task sửa lỗi.**
2. **Quy trình Đóng Băng Dữ Liệu Bất Biến (Immutable Freeze):**
   - Tạo thư mục release độc lập: `artifacts/taxonomy/releases/taxonomy-v1.0.0/`.
   - Sao chép toàn bộ các tệp dữ liệu từ `artifacts/taxonomy/` vào thư mục release.
   - Sinh tệp định danh bất biến `freeze_manifest.json`:
     ```json
     {
       "release_id": "taxonomy-v1.0.0",
       "release_timestamp": "2026-10-16T23:00:00Z",
       "release_status": "APPROVED",
       "git_commit": "COMMITTED_HASH",
       "environment": {
         "python_version": "3.12.3",
         "platform": "Linux-x86_64"
       },
       "source_manifest_sha256": "...",
       "files": {
         "taxonomy.jsonl": {
           "sha256": "...",
           "records_count": 14520,
           "size_bytes": 12458900
         },
         "lexicon.verified.jsonl": {
           "sha256": "...",
           "records_count": 42150,
           "size_bytes": 8945200
         },
         "version_crosswalk.json": { "sha256": "..." },
         "crosswalk_edges.jsonl": { "sha256": "..." },
         "unresolved_mappings.jsonl": { "sha256": "..." },
         "duplicate_and_ambiguity_report.json": { "sha256": "..." },
         "source_manifest.json": { "sha256": "..." }
       }
     }
     ```
3. **Hậu Kiểm Độc Lập Sau Đóng Băng (Post-Freeze Verification):**
   - Đọc lại toàn bộ các file trong `artifacts/taxonomy/releases/taxonomy-v1.0.0/`.
   - Băm SHA-256 độc lập và so khớp với `freeze_manifest.json`. Nếu có bất kỳ byte nào sai lệch, release bị hủy bỏ ngay lập tức.
4. **Nguyên Tắc Bất Biến:**
   - Thư mục release là **chỉ đọc (Read-Only)**. Tuyệt đối không chỉnh sửa trực tiếp dữ liệu đã đóng băng.
   - Mọi thay đổi hoặc cập nhật thuật ngữ trong tương lai bắt buộc phải được thực hiện qua chu trình phát hành phiên bản mới (`taxonomy-v1.0.1`, `taxonomy-v1.1.0`).
