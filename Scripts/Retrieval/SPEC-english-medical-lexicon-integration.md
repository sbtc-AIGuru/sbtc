# Đặc tả tích hợp Từ điển Phân đoạn Y khoa Tiếng Anh (English Medical Lexicon Integration)

**Trạng thái:** Bản thảo đề xuất — Đang trình người dùng duyệt  
**Ngày:** 16/10/2026  
**Phạm vi:** Kích hoạt nạp và xử lý 114.232 thuật ngữ y khoa tiếng Anh (`segmentation_en.txt`) vào module `Lexicon` và `MedicalAnalyzer`. **Tuyệt đối không chạy lại dữ liệu (No re-indexing)**, không can thiệp vào các chỉ mục Lucene cũ trên đĩa.

---

## 1. Mục tiêu và Lý do Kỹ thuật

### 1.1. Mục tiêu
- Kích hoạt nạp bộ 114.232 thuật ngữ y khoa tiếng Anh chuẩn quốc tế (trích xuất từ MeSH và PubMed tại [`sbtc/Scripts/Retrieval/resources/segmentation_en.txt`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/resources/segmentation_en.txt)) vào runtime `Lexicon`.
- Xây dựng cơ chế phát hiện và bảo vệ các cụm danh pháp y khoa đa từ (Multi-word Medical Compounds, chiếm 71,0% tổng số từ vựng) trong [`MedicalAnalyzer`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/analyzers.py).
- Ngăn chặn việc Anserini Krovetz Stemmer xé nhỏ hoặc làm biến dạng các thực thể y khoa phức tạp, đồng thời vẫn bảo lưu tính linh hoạt hình thái học ở trường `broad`.

### 1.2. Vấn đề của bộ tách từ Tiếng Anh hiện tại
Hiện tại, nhánh `language == "en"` trong `analyzers.py` chỉ chạy tách từ cơ học theo khoảng trắng rồi đưa qua Krovetz Stemmer:
- Khi gặp cụm bệnh lý phức tạp như *"acute myeloid leukemia"* (ung thư bạch cầu dòng tủy cấp tính) hay *"triple negative breast cancer"* (ung thư vú bộ ba âm tính), bộ tách từ xé vụn thành các token đơn lẻ: `['acute', 'myeloid', 'leukemia']`.
- Trong BM25, việc thiếu token cụm (compound token) khiến một tài liệu chỉ nói về "viêm da cấp tính" (`acute`) và "ung thư phổi" (`leukemia`) có thể bị chấm điểm cao giả tạo do ăn điểm các unigram rời rạc.
- Cần có cơ chế nhận diện cụm từ nguyên khối (Phrase Bonding) bằng dấu gạch dưới (`acute_myeloid_leukemia`) trong trường `contents` để bảo toàn trọng số IDF chính xác.

---

## 2. Ranh giới, Điều kiện & Bất biến

1. **Ranh giới dữ liệu**:
   - Tệp nguồn `segmentation_en.txt` là Read-only.
   - Không chạy lại prepare, không index lại snapshot test20k hay full corpus. Không ghi đè các chỉ mục Lucene hiện có trong `.runtime/` hay `artifacts/`.
2. **Quy tắc BTC & Hệ thống**:
   - Phân biệt rõ ràng giữa **Từ điển phân đoạn (`segmentation_terms`)** và **Khái niệm định danh (`concepts`)**: Việc nạp `segmentation_en.txt` chỉ phục vụ gom cụm từ cho bộ tách từ, **tuyệt đối không tự ý sinh concept anchor giả** (`local:...`) vào trường `anchors`.
   - Giữ nguyên 100% hành vi phân tích của Tiếng Việt (Underthesea) và Tiếng Trung (Jieba).
   - Bảo toàn các token intent và phủ định (`no`, `not`, `without`, `rule out`) cùng các mã gen/biomarkers (`exact_tokens`).

---

## 3. Kiến trúc & Đặc tả Hành vi Thuật toán

### 3.1. Thuật toán Aho-Corasick Automaton cho Tiếng Anh ([`lexicon.py`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/lexicon.py))
- Trong `Lexicon.__init__`:
  * Mở rộng `self.segmentation_dict = {"vi": set(), "zh": set(), "en": set()}`.
  * Duyệt vòng lặp `for lang in ("vi", "zh", "en"):` nạp tệp `segmentation_en.txt`.
  * Khởi tạo `self.en_seg_automaton = ahocorasick.Automaton()`.
  * Nạp tất cả các cụm từ tiếng Anh có độ dài $> 1$ ký tự và xây dựng đồ thị hữu hạn Aho-Corasick (`make_automaton()`).

### 3.2. Cơ chế Phát hiện Khớp Cụm từ (`segmentation_spans_en`)
- Khi quét câu tiếng Anh qua `self.en_seg_automaton.iter(text)`:
  1. **Rào chắn ranh giới từ (Word Boundary Guard)**:
     - Ký tự ngay trước điểm bắt đầu không được là ký tự chữ/số hoặc dấu gạch dưới (`not text[start - 1].isalnum() and text[start - 1] != '_')`).
     - Ký tự ngay sau điểm kết thúc không được là ký tự chữ/số hoặc dấu gạch dưới (`not text[stop].isalnum() and text[stop] != '_')`).
     - Ngăn ngừa triệt để lỗi khớp chuỗi con (ví dụ: không để "cat" khớp vào "communication", "ear" khớp vào "heart").
  2. **Thuật toán Khớp tham lam dài nhất (Greedy Longest-Match First)**:
     - Sắp xếp các cụm từ tìm được theo độ dài giảm dần: `hits.sort(key=lambda x: (-(x[1] - x[0]), x[0]))`.
     - Dùng mảng bitmask `occupied = [False] * len(text)` để chặn các cụm từ ngắn bị bao bọc trong cụm từ dài hơn (ví dụ: *"triple negative breast cancer"* được chọn, bỏ qua *"breast cancer"*).
  3. **Trả về danh sách Span không chồng lấn**: `list[tuple[start_char, stop_char, term]]`.

### 3.3. Phân phối Đa trường trong [`MedicalAnalyzer`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/analyzers.py)
Với mỗi câu tiếng Anh (sau khi hạ chữ thường NFKC):
1. Tìm các span cụm từ ghép y khoa (`len(term.split()) >= 2`).
2. Thay thế các cụm từ ghép này bằng token nối dấu gạch dưới: `"acute myeloid leukemia"` $\to$ `"acute_myeloid_leukemia"`.
3. Tách từ trên câu đã ghép:
   - Các token có chứa dấu gạch dưới `_` được bảo vệ nguyên khối, **không đưa qua Krovetz stemmer**, nạp thẳng vào `compound` (trường `contents`, trọng số 2.5).
   - Các từ đơn lẻ thông thường còn lại vẫn đi qua bảng chuẩn hóa `SPELLING`, `INFLECTION` và Anserini Krovetz Stemmer `self.english.analyze(...)`.
4. Trường `broad` (trọng số 1.0):
   - Nhận toàn bộ các từ unigram ban đầu (`words`), các dạng chuẩn hóa (`canonical`), và các từ thành phần tách ra từ cụm ghép (ví dụ: `broad` chứa cả `acute`, `myeloid`, `leukemia`).
   - Đảm bảo truy vấn từ đơn vẫn khớp postings của tài liệu.

---

## 4. Các trường hợp biên (Edge Cases) & Xử lý

| Trường hợp biên | Rủi ro nếu không xử lý | Cách giải quyết trong đặc tả |
|---|---|---|
| **Từ ngắn nằm trong từ khác** (e.g. *art* trong *artery*, *ear* trong *heart*) | Làm biến dạng từ thông thường thành token y khoa sai | Bắt buộc kiểm tra `\b` (ký tự trước và sau không phải `isalnum()`). |
| **Cụm từ lồng nhau** (e.g. *breast cancer* nằm trong *triple negative breast cancer*) | Nhân đôi token hoặc xé lẻ cụm lớn | Greedy Longest-Match đánh dấu bit `occupied`, chỉ giữ cụm lớn nhất. |
| **Dấu gạch nối trong tên thuốc/gen** (e.g. *brca-1*, *11-cis-retinal*) | Bị ngắt thành 2 từ rời rạc | Nhận diện đúng span có dấu gạch nối hoặc bảo vệ qua `exact_tokens`. |
| **Dấu chấm câu sát từ** (e.g. *"...diagnosed with leukemia."*) | Dấu chấm làm trượt ranh giới từ | Chuẩn hóa tách ranh giới câu trước khi quét cụm từ. |
| **Từ phủ định y khoa** (e.g. *no*, *without*) | Bị nhầm thành stopword | Tiếp tục duy trì `stopwords=False` trong Krovetz analyzer. |

---

## 5. Kế hoạch Kiểm thử & Tiêu chuẩn Nghiệm thu

1. **Unit Test Phân tích Cụm từ Tiếng Anh mới (`test_core.py`)**:
   - Kiểm tra câu: *"Patient with acute myeloid leukemia and triple negative breast cancer."*
   - Kiểm tra `fields["contents"]`: Phải chứa `acute_myeloid_leukemia` và `triple_negative_breast_cancer`.
   - Kiểm tra `fields["broad"]`: Phải chứa đầy đủ các từ con `acute`, `myeloid`, `leukemia`, `triple`, `negative`, `breast`, `cancer`.
   - Kiểm tra `fields["anchors"]`: Tuyệt đối không sinh concept anchor giả cho các cụm từ này nếu không có trong `concepts.json`.
2. **Regression Test Toàn diện**:
   - Chạy toàn bộ test suite: `sbtc/Scripts/Retrieval/.runtime/venv/bin/python -m unittest discover -s sbtc/Scripts/Retrieval/tests -v`.
   - **Chỉ tiêu**: **56/56 tests PASS 100%**.
3. **Strict Fixture Test**:
   - Chạy `tests/analyze_fixture.py --strict`.
   - **Chỉ tiêu**: **69/69 contract cases PASS** (0 contract mismatches).
4. **Không can thiệp Dữ liệu**:
   - Kiểm tra trạng thái thư mục `prepared/` và `indexes/`, đảm bảo không có file nào bị ghi đè hoặc sinh mới.
