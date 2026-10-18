# BÁO CÁO THẨM ĐỊNH KỸ THUẬT ĐỘC LẬP
## ĐẶC TẢ ICD-10 TAXONOMY VÀ MULTILINGUAL LEXICON (VI / EN / ZH)

- **Vai trò thẩm định:** Chuyên gia Độc lập về Kiến trúc Dữ liệu Y tế & NLP (Independent Healthcare Data & NLP Architect Reviewer)
- **Tài liệu thẩm định:** [`SPEC-icd10-taxonomy-and-multilingual-lexicon.md`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/SPEC-icd10-taxonomy-and-multilingual-lexicon.md)
- **Ngày thẩm định:** 16/10/2026
- **Kết luận thẩm định:** **PHÊ DUYỆT CÓ ĐIỀU KIỆN (APPROVED WITH MINOR AMENDMENTS)** — Đạt chuẩn kiến trúc cấp doanh nghiệp / y tế chuyên sâu, khắc phục triệt để các hạn chế của pipeline tiền nhiệm. Cần hoàn thiện 5 điểm kỹ thuật biên trước khi triển khai code sản xuất.

---

## 1. Bảng Điểm Đánh Giá Kiến Trúc (Architecture Scorecard)

| Tiêu Chí Đánh Giá | Điểm (Thang 10) | Nhận Định Chuyên Gia |
|---|:---:|---|
| **1. Tính Chuẩn Xác Y Sinh & Phân Loại Học (Clinical & Ontological Accuracy)** | **9.5** | Phân tách rành mạch cây phân cấp (Taxonomy) và biến thể ngữ nghĩa (Lexicon); hiểu sâu sắc cấu trúc ClaML, phân hệ Dagger/Asterisk của ICD-10 và danh mục 16.052 mã của BYT TT 06/2026. |
| **2. Kiến Trúc NLP & Giải Quyết Nhập Nhằng (NLP & Disambiguation Architecture)** | **9.0** | Bãi bỏ quy tắc cứng 2 âm tiết là quyết định mang tính đột phá; xử lý từ viết tắt có điều kiện ngữ cảnh ($\pm 5$ tokens) rất chuẩn xác. Schema cần bổ sung cờ thuộc tính rõ ràng. |
| **3. Tuân Thủ Ràng Buộc Cuộc Thi (ViBioMIR Invariants Compliance)** | **10.0** | Tuân thủ tuyệt đối quy tắc BTC 5 bước, bất biến khóa chính `id`/`doc_id`, hàm mục tiêu Macro $F_2$, và bảo toàn Plain Verbatim Text để chống sụt giảm $LCS_{\text{tokens}}$. |
| **4. Tính Toàn Vẹn & Khả Thi Kỹ Thuật (Data Integrity & Feasibility)** | **8.5** | Thuật toán đối chiếu mã (Crosswalk) rõ ràng. Cần làm rõ phương án bóc tách PDF TT 06/2026 và quan hệ 1-N của mã 6 ký tự NHSA Trung Quốc với mã 4 ký tự WHO. |
| **5. Độ Chặt Chẽ Của Kế Hoạch Kiểm Thử (Testability & Verification)** | **9.5** | Tiêu chuẩn nghiệm thu định lượng, có kiểm tra foreign key, bao phủ đa ngữ $\ge 99.5\%$, kiểm tra Aho-Corasick $< 5\text{ ms}$/query và không rò rỉ bộ nhớ. |
| **TỔNG KẾT TOÀN DIỆN** | **9.3 / 10** | **ĐẠT CHUẨN XUẤT SẮC (HIGH QUALITY SPECIFICATION)** |

---

## 2. Thẩm Định Chi Tiết Theo 5 Yêu Cầu Cốt Lõi

### 2.1. Yêu cầu 1: Thu thập và đồng bộ 4 nguồn dữ liệu
- **WHO ICD-10 2019:** Đặc tả chọn đúng chuẩn ClaML ISO 13120 (`icd102019en.xml.zip`) kết hợp dữ liệu bảng tabular (`icd102019enMeta.zip`). ClaML là chuẩn phân cấp giàu ngữ nghĩa nhất của WHO, bảo tồn trọn vẹn quan hệ cha-con (`SuperClass`/`SubClass`), nhãn ưu tiên (`preferred`), nhãn bao gồm (`inclusion`) và loại trừ (`exclusion`).
- **BYT TT 06/2026/TT-BYT:** Nhận diện chính xác văn bản pháp quy mới nhất (ban hành 02/04/2026, hiệu lực 01/07/2026) với 16.052 mã bệnh. Nắm bắt bản chất hệ thống mã hình sao/chữ thập (Dagger/Asterisk `†`/`*`) và các mã bệnh nhiệt đới/truyền nhiễm đặc thù của Việt Nam (Sốt xuất huyết Dengue, Viêm gan, Lao kháng thuốc,...).
- **NHSA ICD-10 & National Clinical 2.0 (Trung Quốc):** Có cảnh báo cốt tử: **Cấm dùng Google Translate hay LLM dịch mù từ tiếng Anh sang tiếng Trung**. Lựa chọn đối chiếu theo mã số bệnh với danh mục chuẩn của Cục Quản lý An sinh Y tế Quốc gia Trung Quốc (NHSA) và Bản lâm sàng 2.0/3.0.
- **Từ điển Y khoa Thẩm định:** Tích hợp đa nguồn: NLM MeSH 2026, VN Core FHIR CodeSystems, VietBioNER, En-ViMedNER và Slang Normalizer.

### 2.2. Yêu cầu 2: Cấu trúc 2 bảng độc lập (Taxonomy vs Multilingual Lexicon)
- **Tư duy tách bảng:** Đây là điểm sáng kiến trúc lớn nhất của bản đặc tả.
  - Trước đây, việc trộn lẫn mã bệnh với từ khóa tìm kiếm khiến các thuật ngữ chung chung (ví dụ: *"sốt"*, *"đau đầu"*, *"tiểu đường"*) bị ép gán vào một mã cụ thể (như `E11.9`), dẫn đến sai lệch chẩn đoán và sụp đổ độ đặc hiệu.
  - Bản đặc tả đã tách rạch ròi:
    - **`taxonomy.jsonl` (Bảng 1):** Cây phân loại chân lý (Ground Truth Ontology). Mỗi nút là một thực thể phân loại chuẩn có mã `code`, cấp độ `level` (chapter, block, category, subcategory), nhãn đa ngữ chính quy (`labels: {en, vi, zh}`) và quan hệ cha-con nghiêm ngặt.
    - **`lexicon.verified.jsonl` (Bảng 2):** Bề mặt ngôn ngữ (Linguistic Surface & Contextual Evidence). Chứa từ vựng đời thường, từ viết tắt, triệu chứng, xét nghiệm, cụm phủ định/nghi ngờ. Thuật ngữ cấp rộng chỉ được trỏ tới `block` hoặc `chapter`, giữ `code: null`.

### 2.3. Yêu cầu 3: Phân loại ngữ cảnh & Bãi bỏ quy tắc cứng 2 âm tiết
- **Phân loại 5 nhóm rõ ràng:**
  1. *Tên bệnh chính thức (Official Disease Names):* Map 1-1 với tiêu đề ICD-10.
  2. *Cách gọi đời thường (Colloquial Terms):* Ánh xạ qua `target_canonical` và gắn ở cấp độ Khối (`block`).
  3. *Viết tắt y khoa có kiểm soát (Medical Abbreviations):* Chia đôi nhóm: Nhóm đơn nghĩa an toàn (`ĐTĐ`, `THA`, `COPD`) vs Nhóm nhạy cảm trùng từ thông dụng (`ALL`, `WAS`, `COLD`, `MS`) yêu cầu bắt buộc `case_sensitive` và đồng xuất hiện ngữ cảnh lâm sàng $\pm 5$ tokens.
  4. *Bằng chứng ngữ cảnh (Signs, Symptoms, Lab Tests):* Bất biến quan trọng: Triệu chứng/xét nghiệm **không phải** bệnh chẩn đoán xác định. Dùng làm Contextual Boost, không gán cứng mã bệnh.
  5. *Cụm từ biến đổi ngữ cảnh (Contextual Modifiers):* Phủ định (Negation), Nghi ngờ (Suspected/Rule out), Tiền sử (History), Chẩn đoán phân biệt (Differential Diagnosis).
- **Bãi bỏ quy tắc cứng 2 âm tiết:** Hoàn toàn đúng đắn về mặt khoa học ngôn ngữ học tính toán. Các unigram y khoa tiếng Anh (*pneumonia*, *hypertension*, *gout*, *scabies*, *measles*) mang độ đặc hiệu lâm sàng gần 100%, trong khi nhiều bigram tiếng Việt (*tình trạng*, *vấn đề*, *suy nghĩ*) là từ rác không mang tính bệnh học. Thay thế bằng 4 tiêu chí định lượng (Đặc hiệu lâm sàng, Nguy cơ nhập nhằng, Khớp nguyên chuỗi Aho-Corasick, Thực nghiệm Validation Suite).

### 2.4. Yêu cầu 4: Đầu ra bàn giao Phase 1
- Danh mục 4 tệp đầu ra tại `artifacts/taxonomy/` là đầy đủ và trực tiếp giải quyết bài toán:
  1. `taxonomy.jsonl`: ~14.000 – 16.000 bản ghi, bao phủ 22 chương, ~260 khối, ~2.000 mã 3 ký tự và toàn bộ mã 4/5 ký tự.
  2. `lexicon.verified.jsonl`: 35.000 – 50.000 mục từ chất lượng cao.
  3. `version_crosswalk.json`: Ma trận đối chiếu phiên bản và tỷ lệ bao phủ.
  4. `duplicate_and_ambiguity_report.json`: Báo cáo xung đột mã và quy tắc disambiguation.

### 2.5. Yêu cầu 5: Kế hoạch kiểm thử & Nghiệm thu
- 7 ca kiểm thử then chốt: Cú pháp JSONL, Tính trọn vẹn khóa ngoại (không orphan code), Độ bao phủ đa ngữ $\ge 99.5\%$, Bảo toàn Plain Verbatim (khử Markdown theo quy chuẩn ViBioMIR), Phân định triệu chứng vs bệnh, Bảo vệ viết tắt nhạy cảm, Hiệu năng Aho-Corasick $< 5\text{ ms}$ / query.

---

## 3. Các Lỗ Hổng Kỹ Thuật, Ca Biên (Edge Cases) & Đề Xuất Bổ Sung

Dù bản đặc tả đạt chất lượng rất cao, dưới góc độ chuyên gia độc lập, tôi chỉ ra **5 điểm kỹ thuật biên cần được làm rõ và bổ sung vào tài liệu trước khi bấm nút triển khai code**:

### ⚠️ Điểm 1: Schema JSON của `lexicon.verified.jsonl` thiếu trường cấu hình Disambiguation
- **Vấn đề:** Trong Mục 4.3, tài liệu nêu nguyên tắc bảo vệ từ viết tắt nhạy cảm (`ALL`, `WAS`, `COLD`, `MS`) bằng cơ chế `case_sensitive: true` và cửa sổ đồng xuất hiện ngữ cảnh lâm sàng $\pm 5$ tokens. Tuy nhiên, trong Schema mẫu tại Mục 3.2, bảng `lexicon.verified.jsonl` **hoàn toàn không có** các trường:
  - `case_sensitive`: boolean
  - `co_occurrence_triggers`: danh sách từ khóa lâm sàng bắt buộc đi kèm (hoặc `context_window: 5`).
- **Hệ quả:** Module tải từ điển vào Aho-Corasick Automaton sẽ không biết mục từ nào cần phân biệt hoa/thường, dẫn đến việc hạ chữ thường (`lower()`) toàn bộ từ điển và gây ra false positive nghiêm trọng trên các từ như *all*, *was*, *cold*.
- **Đề xuất bổ sung:** Cập nhật Schema của `lexicon.verified.jsonl` thêm các trường sau:
  ```json
  {
    "term": "ALL",
    "normalized_term": "all",
    "language": "en",
    "chapter": "Ch_II",
    "block": "C81-C96",
    "code": "C91.0",
    "kind": "abbreviation",
    "target_canonical": "acute lymphoblastic leukemia",
    "specificity": "exact_code",
    "case_sensitive": true,
    "co_occurrence_triggers": ["leukemia", "blast", "bone marrow", "chemotherapy", "pediatric", "b-cell", "t-cell"],
    "context_window": 5,
    "verified": true,
    "source": "clinical_acronym_curated"
  }
  ```

---

### ⚠️ Điểm 2: Xử lý quan hệ 1-N giữa mã 6 ký tự NHSA Trung Quốc và mã 4 ký tự WHO/BYT
- **Vấn đề:** Hệ thống mã hóa lâm sàng Trung Quốc (NHSA National Clinical 2.0) sử dụng mã 6 ký tự để phân tách các thể bệnh cực kỳ chi tiết (ví dụ: `E11.900`, `E11.901`, `E11.902`). Khi cắt về mã 4 ký tự (`E11.9`), sẽ có nhiều bản ghi tiếng Trung cùng trỏ về một mã 4 ký tự duy nhất (quan hệ 1-to-Many).
- **Hệ quả:** Trong `taxonomy.jsonl`, trường `labels.zh` chỉ nhận một giá trị chuỗi đơn lẻ (`string`). Nếu không quy định rõ thuật toán chọn nhãn tiếng Trung đại diện (ví dụ: nhãn của mã kết thúc bằng `00` hay nhãn ngắn nhất mang tính khái quát), quá trình ghép nối (crosswalk) sẽ bị ghi đè ngẫu nhiên hoặc xung đột dữ liệu.
- **Đề xuất bổ sung:**
  1. Trong `taxonomy.jsonl`: `labels.zh` chỉ nhận tên chính quy chuẩn hóa ở cấp Category/Subcategory (ưu tiên mã đuôi `00` của NHSA hoặc nhãn tương đương trong ICD-10-CN chính thức).
  2. Toàn bộ các biến thể lâm sàng 6 ký tự chi tiết của Trung Quốc được tự động chuyển hóa thành các bản ghi trong `lexicon.verified.jsonl` với `kind: "official_disease"`, `language: "zh"`, trỏ về mã 4 ký tự tương ứng. Như vậy vừa giữ `taxonomy.jsonl` tinh gọn chuẩn 1-1, vừa bảo toàn 100% độ phủ từ vựng tiếng Trung cho retrieval!

---

### ⚠️ Điểm 3: Cơ chế liên kết cặp Dagger/Asterisk (`†`/`*`) trong Taxonomy
- **Vấn đề:** Trong ICD-10, hệ thống Dagger/Asterisk dùng để mã hóa kép:
  - Mã Dagger (`†`): Mã nguyên nhân bệnh sinh chính (ví dụ: `E11.2†` - Bệnh thận do đái tháo đường).
  - Mã Asterisk (`*`): Mã biểu hiện lâm sàng kèm theo (ví dụ: `N08.3*` - Bệnh cầu thận trong bệnh đái tháo đường).
  - Bản đặc tả hiện chỉ lưu trường đơn lẻ `dagger_asterisk: "dagger" | "asterisk" | null`.
- **Hệ quả:** Nếu người dùng tìm kiếm theo biểu hiện lâm sàng (*"bệnh cầu thận ở bệnh nhân đái tháo đường"*), hệ thống tìm được `N08.3*` nhưng không liên kết ngược lại được với `E11.2†`, gây đứt gãy đồ thị tri thức.
- **Đề xuất bổ sung:** Thêm trường `paired_codes: ["N08.3*"]` vào bản ghi của `E11.2†` (và ngược lại `paired_codes: ["E11.2†"]` trong `N08.3*`) trong `taxonomy.jsonl`.

---

### ⚠️ Điểm 4: Chiến lược Ingestion Danh mục BYT TT 06/2026 (Tránh rủi ro bóc tách PDF đơn thuần)
- **Vấn đề:** Văn bản `06-byt-kem.pdf` chứa 16.052 mã bệnh là một tài liệu PDF hành chính khổng lồ (hàng trăm trang dạng bảng biểu). Việc trích xuất tự động qua các thư viện parse PDF (như `pdfplumber`, `pypdf`) thường gặp rủi ro: vỡ cột, xô lệch dòng, lỗi mã hóa font tiếng Việt (TCVN3 vs Unicode), hoặc mất ký tự dagger/asterisk.
- **Đề xuất bổ sung:** Quy định rõ thứ tự ưu tiên nguồn thu thập dữ liệu BYT (Ingestion Hierarchy):
  1. **Ưu tiên 1 (Golden Source):** File dữ liệu có cấu trúc từ Cổng Giám định BHYT / Trung tâm Thông tin Y tế Quốc gia (CCMS) hoặc CodeSystem JSON chính thức từ VN Core FHIR (Đã chuẩn hóa Unicode UTF-8 dựng sẵn).
  2. **Ưu tiên 2:** File Excel/CSV phụ lục kỹ thuật kèm theo Quyết định 1849/QĐ-BYT hoặc Thông tư 06/2026/TT-BYT do Cục Quản lý Khám chữa bệnh ban hành.
  3. **Ưu tiên 3 (Fallback cuối cùng):** Trích xuất từ PDF qua pipeline OCR/Table Extraction có kiểm tra tổng số dòng checksum (phải đủ 16.052 mã, sai lệch $\le 0.1\%$).

---

### ⚠️ Điểm 5: Chuẩn hóa chữ Hán (OpenCC) và Unicode NFKC toàn diện
- **Vấn đề:** Dữ liệu tiếng Trung trong ngữ liệu y khoa (và các tài liệu crawl từ Internet) thường lẫn lộn giữa Chữ Hán Giản thể (Simplified - zh-hans) và Chữ Hán Phồn thể (Traditional - zh-hant, dùng tại Đài Loan, Hồng Kông). Ngoài ra, tiếng Việt thường gặp xung đột giữa Unicode Tổ hợp (NFD) và Dựng sẵn (NFC).
- **Đề xuất bổ sung:**
  - Tiếng Trung: Bắt buộc chuẩn hóa 100% về Chữ Hán Giản thể (`zh-hans`) thông qua thư viện `opencc` (bộ chuyển đổi `t2s.json`), kết hợp đưa toàn bộ ký tự số/chữ cái về Half-width.
  - Tiếng Việt: Bắt buộc chuẩn hóa qua `unicodedata.normalize('NFKC', text)` theo đúng chuẩn 5 bước của BTC ViBioMIR.

---

## 4. Kết Luận & Khuyến Nghị Quyết Định

### Đánh giá chung:
Bản đặc tả kỹ thuật [`SPEC-icd10-taxonomy-and-multilingual-lexicon.md`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/SPEC-icd10-taxonomy-and-multilingual-lexicon.md) là một công trình thiết kế **rất công phu, chuẩn mực và sắc sảo**. Nó giải quyết tận gốc các nút thắt kỹ thuật từng làm suy giảm hiệu năng của BM25 và FastText trong các giai đoạn trước:
- Tách bạch cấu trúc phân loại học và biểu diễn ngữ nghĩa bề mặt.
- Loại bỏ các rào cản máy móc (quy tắc 2 âm tiết).
- Kiểm soát chặt chẽ nguy cơ hallucination/nhiễu từ việc dịch máy tiếng Trung.
- Bảo đảm tối đa tính nguyên bản Plain Verbatim Text để phục vụ chấm điểm $LCS_{\text{tokens}}$ theo Macro $F_2$.

### Khuyến nghị phê duyệt:
**CHẤP THUẬN THÔNG QUA VÀ CHO PHÉP TRIỂN KHAI CODE (APPROVED FOR IMPLEMENTATION)**, với điều kiện đội ngũ phát triển bổ sung 5 điểm biên nêu tại Mục 3 vào bản đặc tả (hoặc đưa trực tiếp vào cấu hình triển khai của Phase 1).
