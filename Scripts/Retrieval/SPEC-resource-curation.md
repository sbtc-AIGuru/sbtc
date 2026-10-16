# Đặc tả xử lý resource y khoa đa ngữ

**Trạng thái:** Đã được duyệt; converter và dữ liệu dẫn xuất đã tạo  
**Ngày:** 2026-10-15

## 1. Mục tiêu

Chuẩn hóa và phân loại toàn bộ resource y khoa đa ngữ hiện có để có thể kiểm tra, truy vết và dùng có kiểm soát cho Retrieval. Kết quả phải giữ được dòng/ID nguồn, ghi lý do phân loại, không biến cụm từ chưa kiểm chứng thành synonym hoặc medical anchor đã xác nhận.

## 2. Phạm vi đầu vào

Đọc các file sau, không sửa/ghi đè/xóa chúng:

1. `sbtc/Resources/base_vi.txt`
2. `sbtc/Resources/base_en.txt`
3. `sbtc/Resources/base_zh.txt`
4. `sbtc/Resources/concepts_aligned_vi_en_zh.jsonl`
5. `sbtc/Resources/medical_lexicon_vi_en_zh.sample.jsonl`
6. `sbtc/Scripts/Retrieval/resources/concepts.json` — dùng làm seed đối chiếu; giữ nguyên file.

Không đọc `for_valid/`, không lấy query/qrels làm nguồn tạo alias, không chạy lại builder cũ, không đọc/import code trong archive, không sửa corpus/chunk/index hiện có và không tự tích hợp resource vào BM25.

## 3. Cách xử lý dự kiến

### 3.1. Ba danh sách từ đơn ngữ

- Giữ nguyên `display_term`; tạo `normalized_term` bằng Unicode NFKC, lowercase và gộp khoảng trắng. Không tự bỏ dấu tiếng Việt, dịch, sửa chính tả hoặc nối từ.
- Dedupe theo `(language, normalized_term)` nhưng giữ đủ `source_file`, `source_line`, giá trị gốc và số lần xuất hiện.
- Phân loại từng dòng thành:
  - `lexical_candidate`: cấu trúc đủ dùng làm ứng viên segmentation/recall thử nghiệm; không đồng nghĩa đã xác nhận là thuật ngữ y khoa.
  - `review`: có dấu hiệu mẩu câu, phủ định/ngữ cảnh, cụm quá chung, tổ chức, mã dính, hoặc chưa đủ căn cứ tự động quyết định.
  - `exclude`: rỗng, lỗi định dạng/markup, hoặc nhiễu cấu trúc xác định được bằng quy tắc máy.
- Mỗi bản ghi có `reasons[]` và `rule_version`. Không tự loại `review` khỏi resource; không khẳng định tỷ lệ chính xác y khoa nếu chưa có người thẩm định.
- Các cụm VI đúng 5 token vào review vì source có mật độ bất thường ở độ dài này. Từ chỉ ngữ cảnh/hội thoại và dấu hiệu hành động trong ZH cũng được đưa vào review; đây là lựa chọn bảo thủ, không phải kết luận rằng cụm sai.

### 3.2. Bộ đối chiếu VI–EN–ZH

- Parse và kiểm tra schema từng dòng; giữ `source_line`, `original_concept_id`, category, nhãn và ICD code nguyên gốc.
- Chỉ tự gộp các record có **cả ba nhãn VI/EN/ZH trùng sau chuẩn hóa**. Chọn ID canonical ổn định theo dòng xuất hiện đầu tiên; xuất mapping từ mọi ID nguồn sang ID canonical.
- Các collision chỉ trùng một hoặc hai ngôn ngữ không được gộp. Gắn cờ term đó `ambiguous` cho ngôn ngữ tương ứng và không cho phép tạo anchor từ term đó.
- ICD code được giữ ở trạng thái `unverified`; không dùng để tạo anchor cho đến khi đối chiếu nguồn/version chính thức.
- Nhãn từ file này là `concept_candidate`, chưa phải thuật ngữ đã được chuyên gia xác nhận. Không tự thêm alias hay ánh xạ MeSH/UMLS.

### 3.3. Lexicon sample có Wikidata QID

- Giữ từng record và alias cùng nguồn dòng; phân ngôn ngữ alias chỉ khi xác định được chắc chắn, còn lại đánh `language: unknown`.
- Hai mapping đã có bằng chứng sai (`Q12136`, `Q181754`) nhận trạng thái `rejected_external_id` với lý do và URL bằng chứng.
- Sáu QID chưa xác minh nhận trạng thái `review_external_id`; không dùng QID nào trong số này làm anchor khi chưa xác minh.
- Quan hệ alias dạng điều trị/chức năng không tự coi là đồng nghĩa chính xác.

### 3.4. Seed local 12 concept

- Giữ nguyên seed. Đưa vào báo cáo đối chiếu với aligned records để phát hiện ID/nhãn/collision trùng hoặc xung đột.
- Không tự hợp nhất hai concept chỉ vì nhãn gần nhau; mọi đề xuất hợp nhất có trạng thái `review`.
- Giữ nguồn/license gốc của seed; với resource thiếu provenance/license, ghi `unknown`, không suy đoán.

### 3.5. Rà mẫu và giới hạn ứng viên

- Đọc mẫu cố định 15 lexical candidates/ngôn ngữ, seed 20261015. Mẫu phát hiện thêm cụm ngữ cảnh và chuỗi nhiễu; cập nhật quy tắc trước khi chốt artifact.
- `lexical_candidate` vẫn chưa được thẩm định ngữ nghĩa thủ công. Không gọi đây là danh sách sạch hoặc được duyệt production.

## 4. Đầu ra dẫn xuất

Tạo thư mục mới `sbtc/Scripts/Retrieval/resources/curated/20261015/`, không ghi vào thư mục resource gốc:

- `terms_vi.jsonl`, `terms_en.jsonl`, `terms_zh.jsonl`: bản ghi đã chuẩn hóa, dedupe và phân loại.
- `concepts_candidates.jsonl`: aligned concepts sau exact-triple merge, kèm ambiguity, ICD verification status và provenance.
- `concept_id_map.jsonl`: mapping ID nguồn → canonical ID và quy tắc gộp.
- `external_ids_review.jsonl`: toàn bộ sample records/QIDs, trạng thái xác minh và bằng chứng có sẵn.
- `seed_comparison.jsonl`: kết quả đối chiếu aligned concepts với seed 12 concept.
- `manifest.json`: SHA-256 đầu vào, số record, phiên bản quy tắc, thời điểm xử lý, và tình trạng provenance/license.
- `REPORT.md`: số liệu trước/sau, số lexical_candidate/review/exclude theo ngôn ngữ, duplicate/collision, lỗi schema, ví dụ đại diện, giới hạn xác minh và hướng dùng.

Các tên `lexical_candidate`/`concept_candidate` chỉ mô tả ứng viên dẫn xuất. Đầu ra chưa được nạp vào analyzer, matcher, index hay bài nộp cho đến khi có bước đánh giá riêng.

## 5. Kiểm tra sau xử lý

- Đối chiếu tổng số dòng đầu vào với số record được phân loại; mọi dòng phải được giữ hoặc có lý do loại rõ.
- Kiểm tra JSONL parse được, ID canonical duy nhất, mapping đầy đủ, không mất provenance dòng nguồn.
- Kiểm tra exact-triple merge và collision không bị gộp nhầm.
- So sánh SHA-256 đầu vào trước/sau để chứng minh nguồn không đổi.
- Không chạy unit test suite hoặc benchmark Retrieval trong bước curation này; báo cáo validation dữ liệu riêng.

## 6. Giới hạn và rủi ro

Quy tắc cấu trúc không thể xác nhận bản dịch, tính y khoa, phạm vi khái niệm hay quyền sử dụng. Vì vậy trạng thái ứng viên không phải phê duyệt ngữ nghĩa/pháp lý. File chưa có license phải tiếp tục bị chặn khỏi production contract yêu cầu source/license. Tích hợp và reindex cần một quyết định/đánh giá tiếp theo.

## 7. Kế hoạch thực hiện

1. Viết converter/auditor xác định, đầu ra chỉ vào thư mục dẫn xuất mới.
2. Chạy converter trên sáu input đã liệt kê; không chạy builder cũ.
3. Kiểm tra đầy đủ counts, hashes, collisions, mapping, output parseability.
4. Đọc mẫu các nhóm candidate/review/exclude và sửa lỗi của converter nếu phát hiện.
5. Cập nhật `docs_AI.md` và `tasks/todo.md` bằng thay đổi, lỗi và kết quả đã xác minh.
6. Trình bày report; chưa tích hợp BM25/index trong phạm vi này.

## 8. Kết quả triển khai

- Converter: `sbtc/Scripts/Retrieval/curate_resources.py`.
- Dữ liệu dẫn xuất: `sbtc/Scripts/Retrieval/resources/curated/20261015/`.
- Converter đã đối chiếu record/ID, parse lại JSONL, kiểm tra canonical ID duy nhất và xác nhận SHA-256 nguồn trước/sau không đổi.
- Counts, hashes, collision và giới hạn sử dụng nằm trong REPORT.md và manifest.json của artifact.
