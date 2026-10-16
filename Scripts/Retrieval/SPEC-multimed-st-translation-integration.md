# Đặc tả Kỹ thuật: Tích hợp Mô hình Dịch Y khoa Đa ngữ MultiMed-ST (EMNLP 2025)

**Trạng thái:** Bản thảo đề xuất — Chờ người dùng xác nhận  
**Ngày:** 16/10/2026  
**Phạm vi:** Thiết kế module nạp và thực thi mô hình dịch chuyên sâu y khoa MultiMed-ST (`leduckhai/MultiMed-ST`, EMNLP 2025) để sinh bộ nhớ đệm dịch câu hỏi ngoại tuyến (`query-translations.jsonl`) cho 1.200 truy vấn BTC, tích hợp trực tiếp vào pipeline [`QueryProjector`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/query.py).  
**Cam kết bất biến:** Tuyệt đối không can thiệp, không sửa đổi hay chạy lại dữ liệu crawl thô, chunk thô hay các chỉ mục Lucene hiện có trên đĩa. Tuân thủ 100% quy chế BTC về giới hạn mô hình (<15B tham số, phát hành trước 01/08/2026, mã nguồn và trọng số mở).

---

## 1. Mục tiêu và Lý do Kỹ thuật

### 1.1. Mục tiêu bài toán
1. Mở rộng khả năng truy xuất đa ngữ (Cross-lingual Information Retrieval) của hệ thống BM25 bằng cách dịch 1.200 câu hỏi tiếng Việt trong `newcorpus/query.parquet` sang **Tiếng Anh (EN)** và **Tiếng Trung (ZH)**.
2. Kích hoạt hiệu quả của 2 kho từ điển phân đoạn y khoa vừa được hoàn thiện:
   - Từ điển Tiếng Anh [`segmentation_en.txt`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/resources/segmentation_en.txt) (114.232 thuật ngữ MeSH/PubMed với cơ chế Compound Bonding).
   - Từ điển Tiếng Trung [`segmentation_zh.txt`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/resources/segmentation_zh.txt) (27.332 thuật ngữ với Jieba Medical HMM).
3. Đảm bảo toàn bộ quá trình dịch được thực hiện **ngoại tuyến 1 lần duy nhất (Offline Pre-translation & Caching)**. Khi hệ thống chạy tìm kiếm thời gian thực (Online Retrieval), `QueryProjector` chỉ việc tra cứu cache trong $O(1)$ từ file JSONL, giữ vững tốc độ xử lý $1.6\text{ ms/query}$ và không tốn VRAM/GPU trong pha xếp hạng.

### 1.2. Lý do chọn MultiMed-ST (EMNLP 2025) thay vì NLLB tổng quát
- `LocalNllbTranslator` hiện tại trong [`translation.py`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/translation.py) được thiết kế cho mô hình NLLB tổng quát (`facebook/nllb-200-distilled-600M`). NLLB tổng quát thường dịch sai hoặc làm suy yếu các thuật ngữ chuyên sâu lâm sàng tiếng Việt (ví dụ: các từ ghép bệnh học, tên hoạt chất, phác đồ điều trị thường bị dịch sang từ thông dụng không đúng chuẩn MeSH/ICD).
- **MultiMed-ST (EMNLP 2025)** do tác giả Khai Le-Duc et al. phát triển dựa trên nền tảng `facebook/m2m100_418M`, được tinh chỉnh chuyên biệt trên tập dữ liệu lâm sàng y khoa đa ngữ (Medical Clinical Corpus) bao gồm cả tiếng Việt, tiếng Anh và tiếng Trung.
- Mô hình chỉ có **418M tham số**, kích thước trọng số mỗi hướng ~1,8 GB (FP16/FP32), phù hợp hoàn hảo với phần cứng máy tính hiện tại (GTX 1650 4GB VRAM / CPU AMD Ryzen 5500U, ổ cứng còn 12 GB trống).

---

## 2. Tiêu chuẩn Pháp lý & Ràng buộc Bất biến của BTC (Provenance Manifest)

Tất cả các mô hình học sâu tham gia pipeline phải tuân thủ điều 1 trong quy tắc làm việc (`AGENTS.md`) và quy chế ViBioMIR:

| Tiêu chí | Quy định BTC | Khai báo MultiMed-ST | Đánh giá |
|---|---|---|---|
| **Giới hạn tham số** | $\le 15\text{ tỷ}$ (15B) parameters | **418 triệu** (418M) parameters | **ĐẠT** ($\ll 15\text{B}$) |
| **Kiến trúc mô hình** | Open-weights PLM/LLM công khai trên HuggingFace | `M2M100ForConditionalGeneration` (`facebook/m2m100_418M` finetuned) | **ĐẠT** |
| **Giới hạn thời gian** | Phát hành trước 01/08/2026 | Công bố tại EMNLP 2025 (upload 23/02/2025) | **ĐẠT** |
| **API độc quyền** | Tuyệt đối cấm closed LLM APIs (GPT-4, Gemini, Claude) | Chạy local offline 100% qua HuggingFace Transformers | **ĐẠT** |
| **Tính bất biến bản quyền** | 40-character commit hash cố định | Commit: `fb15edd1dfc68810a7d0c75e6cfc73c3e5ed01c1` | **ĐẠT** |
| **Giấy phép** | Cho phép sử dụng nghiên cứu | MIT License | **ĐẠT** |
| **Tính nguyên bản Chunk** | Cấm tóm tắt/dịch lại văn bản chunk tham chiếu | **Chỉ dịch câu hỏi (Query Translation)**, giữ nguyên văn bản chunk | **ĐẠT** |

**Cấu trúc Khai báo Chứng thực (`provenance`):**
```python
PROVENANCE_MULTIMED_ST = {
    "model_id": "leduckhai/MultiMed-ST",
    "revision": "fb15edd1dfc68810a7d0c75e6cfc73c3e5ed01c1",
    "license": "mit",
    "parameters": 418_000_000,
    "release_date": "2025-02-23",
    "open_weights": True
}
```

---

## 3. Kiến trúc Triển khai & Chi tiết Kỹ thuật

### 3.1. Phân bổ Checkpoint & Tiết kiệm Ổ đĩa
Kho lưu trữ `leduckhai/MultiMed-ST` trên HuggingFace chứa nhiều nhánh tác vụ. Chúng ta chỉ tải về **2 nhánh chuyên biệt** phục vụ dịch từ câu hỏi tiếng Việt:
1. `m2m100_418M-finetuned-vi-to-en/checkpoint/`: Phục vụ dịch Tiếng Việt $\to$ Tiếng Anh.
2. `m2m100_418M-finetuned-vi-to-zh/checkpoint/`: Phục vụ dịch Tiếng Việt $\to$ Tiếng Trung.

**Quy tắc lọc file an toàn (Không tải file rác):**
- **File cần tải (Inference Bundle):**
  * `model.safetensors` (~1.80 GiB)
  * `config.json`
  * `generation_config.json`
  * `tokenizer_config.json`
  * `sentencepiece.bpe.model`
  * `vocab.json`
  * `special_tokens_map.json`
  * `added_tokens.json`
- **File cấm tải (Training Checkpoints - Bỏ qua để tiết kiệm dung lượng):**
  * `optimizer.pt` (~1.7 GiB) $\to$ **Tiết kiệm 3.4 GiB** cho 2 hướng.
  * `scheduler.pt`, `trainer_state.json`, `training_args.bin`, `rng_state.pth`.
- **Tổng dung lượng đĩa sử dụng:** $\approx 3.6\text{ GiB}$ (Ổ đĩa máy tính còn 12 GiB $\to$ Dư $> 8\text{ GiB}$, an toàn tuyệt đối).

### 3.2. Cấu trúc Module Code trong [`translation.py`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/translation.py)

Bổ sung lớp chuyên dụng cho M2M-100 / MultiMed-ST mà không phá vỡ `LocalNllbTranslator` cũ:

```
sbtc/Scripts/Retrieval/
├── translation.py           # Bổ sung LocalM2MTranslator & MultiMedCompositeTranslator
├── scripts/
│   └── run_translation.py   # CLI tải trọng số tối giản và chạy batch translation
└── tests/
    └── test_translation.py # Unit tests kiểm tra contract, manifest và tokenizer token ID
```

#### A. Lớp `LocalM2MTranslator` (Single Direction)
- Quản lý 1 checkpoint cục bộ (ví dụ `vi-to-en` hoặc `vi-to-zh`).
- Kiểm tra toàn vẹn SHA256 tất cả các file cấu hình và `model.safetensors` đối chiếu với manifest JSON.
- Khởi tạo:
  ```python
  from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
  self.tokenizer = M2M100Tokenizer.from_pretrained(self.directory, src_lang="vi", local_files_only=True)
  self.model = M2M100ForConditionalGeneration.from_pretrained(
      self.directory, local_files_only=True, use_safetensors=True, torch_dtype=torch.float32 # hoặc bfloat16/float16
  ).to(device).eval()
  ```
- Hàm sinh:
  ```python
  forced_bos_token_id = self.tokenizer.get_lang_id(self.target_lang)
  tokens = self.model.generate(**inputs, forced_bos_token_id=forced_bos_token_id, max_new_tokens=512, num_beams=2, do_sample=False)
  ```

#### B. Lớp `MultiMedCompositeTranslator` (Dual Direction)
- Tích hợp 2 translator: `vi_en_translator` và `vi_zh_translator`.
- Cung cấp giao diện chuẩn `translate(texts: list[str]) -> list[dict[str, str]]`:
  ```python
  def translate(self, texts: list[str]) -> list[dict[str, str]]:
      en_results = self.vi_en_translator.translate(texts)
      zh_results = self.vi_zh_translator.translate(texts)
      return [{"en": en, "zh": zh} for en, zh in zip(en_results, zh_results)]
  ```
- Thuộc tính `provenance`: Trả về `PROVENANCE_MULTIMED_ST` đã được kiểm chứng qua `validate_provenance()`.
- Tương thích 100% với hàm `write_translation_cache(queries, translator, output_path)` hiện có.

### 3.3. Hỗ trợ Phần cứng Linh hoạt (Dual Engine GPU/CPU)
- **Tự động nhận diện thiết bị (Device Auto-detection):**
  * Nếu `torch.cuda.is_available()` là `True` (khi đã cài NVIDIA driver cho GTX 1650): Sử dụng `device='cuda'`, `torch_dtype=torch.float16`. Mỗi model chiếm ~900 MB VRAM, chạy cực nhanh (~3-5 giây cho 1.200 queries).
  * Nếu `torch.cuda.is_available()` là `False` (hiện tại trên nouveau driver): Tự động fallback về `device='cpu'`, sử dụng 12 luồng CPU AMD Ryzen 5 5500U với `torch_dtype=torch.bfloat16` hoặc `torch.float32`. Chạy hoàn thành trong khoảng ~2 - 4 phút cho 1.200 queries.
- **Chiến lược Quản lý Bộ nhớ Tuần tự (Sequential Batching):**
  * Nếu chạy trên CPU hoặc bộ nhớ eo hẹp: Có thể cấu hình chạy dịch toàn bộ câu hỏi sang tiếng Anh trước $\to$ lưu mảng đệm $\to$ giải phóng model EN $\to$ nạp model ZH để dịch sang tiếng Trung. Đỉnh RAM tiêu thụ chỉ tối đa ~1,8 GB.

---

## 4. Các Rào chắn An toàn (Guardrails) & Xử lý Trường hợp Biên

1. **Rào chắn Bảo tồn Số liệu (`translation_number_guard` trong `query.py`)**:
   - Trong y khoa, các con số biểu thị liều lượng hoặc phân nhóm bệnh lý (ví dụ: *typ 2*, *500 mg*, *0.5%*, *giai đoạn 3*).
   - Nếu bản dịch của MultiMed-ST làm rơi mất các con số gốc có trong câu tiếng Việt: `QueryProjector` sẽ phát hiện và loại bỏ bản dịch bị khuyết số đó, tự động chuyển về fallback qua aliases/anchors từ điển để tránh sinh query rác.
2. **Rào chắn Ngăn ngừa Chuỗi Rỗng (`empty_guard`)**:
   - Nếu bản dịch trả về chuỗi rỗng hoặc chỉ có khoảng trắng, hàm `write_translation_cache` sẽ raise `ValueError` lập tức để ngăn file cache bị lỗi.
3. **Giới hạn Độ dài Đầu vào (Adapter Budget 512 tokens)**:
   - Tất cả câu hỏi trong `query.parquet` đều là các câu truy vấn lâm sàng ngắn (< 100 từ).
   - Kiểm tra `inputs['input_ids'].shape[1] <= 512`, không silent truncate để đảm bảo toàn vẹn ý nghĩa ngữ nghĩa.
4. **Bảo tồn Danh pháp Chữ viết tắt / Mã Gen Quốc tế**:
   - Các từ viết tắt như *MRI, CT-scanner, ECG, HER2, EGFR, COVID-19* được tokenizer của M2M100 bảo toàn nhờ cơ chế subword Byte-Pair Encoding.

---

## 5. Kế hoạch Kiểm thử & Tiêu chuẩn Nghiệm thu (Verification & Acceptance Criteria)

### 5.1. Unit Test Mức Module (Không yêu cầu tải weights 3.6 GB)
- Thêm `tests/test_translation_multimed.py` sử dụng Mock Translator để kiểm tra:
  * Kiểm tra tính hợp lệ của schema `PROVENANCE_MULTIMED_ST` qua `validate_provenance()`.
  * Kiểm tra hợp đồng gọi của `MultiMedCompositeTranslator` kết hợp với `write_translation_cache`.
  * Kiểm tra việc bắt lỗi sai lệch SHA256 khi manifest không khớp file trên đĩa.
  * Toàn bộ 56 unit test hiện có trong `tests/` phải **PASS 100%**.

### 5.2. Integration Test Mức Runtime (Chạy với trọng số thật)
1. Tải trọng số tối giản của `vi-to-en` và `vi-to-zh` vào thư mục `artifacts/models/MultiMed-ST/`.
2. Tạo manifest `manifest_vi_en.json` và `manifest_vi_zh.json` kèm mã băm SHA256 tự động tính toán.
3. Dịch thử nghiệm 3 câu test lâm sàng đại diện:
   - *Test 1 (Đái tháo đường & liều dùng):* `"bệnh nhân đái tháo đường typ 2 dùng metformin 500 mg"`
     $\to$ EN phải có `"diabetes"` và `"500 mg"`.
     $\to$ ZH phải có `"糖尿病"` và `"500 mg"`.
   - *Test 2 (Bệnh lý tim mạch):* `"nhồi máu cơ tim cấp có st chênh lên"`
     $\to$ EN phải khớp thuật ngữ y khoa chuyên sâu (`"ST-elevation myocardial infarction"` hoặc `"acute myocardial infarction"`).
   - *Test 3 (Ung thư học):* `"ung thư phổi tế bào không nhỏ giai đoạn 3"`
     $\to$ EN phải dịch đúng `"non-small cell lung cancer stage 3"`.
4. Sinh toàn diện file cache `artifacts/retrieval/query-translations.jsonl` cho 1.200 queries từ `newcorpus/query.parquet`.
5. Kiểm tra file cache nghiệm thu:
   - Đủ chính xác 1.200 dòng JSON.
   - Dung lượng file $\approx 350 - 500\text{ KB}$ ($\ll 16\text{ MiB}$ ngân sách tối đa).
   - Mỗi dòng khớp SHA256 của `source_query`.
   - `QueryProjector` nạp cache mượt mà và kích hoạt thành công các kênh tìm kiếm `translation-compound` và `translation-broad` cho cả EN và ZH.

---

## 6. Trình tự Triển khai (Step-by-step Execution Plan)

1. **Bước 1:** Trình người dùng duyệt đặc tả kỹ thuật này.
2. **Bước 2:** Viết script tải trọng số tối giản từ HF `leduckhai/MultiMed-ST` (chỉ tải `safetensors` và tokenizer, bỏ qua `optimizer.pt`), lưu vào `artifacts/models/MultiMed-ST/` và tạo manifest SHA256.
3. **Bước 3:** Cập nhật [`translation.py`](file:///home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/translation.py) bổ sung lớp hỗ trợ MultiMed-ST / M2M100.
4. **Bước 4:** Bổ sung unit tests cho translation module và chạy xác minh toàn bộ test suite.
5. **Bước 5:** Thực thi script dịch offline 1.200 queries sang `artifacts/retrieval/query-translations.jsonl`.
6. **Bước 6:** Chạy thử nghiệm BM25 Query Projection trên queries mẫu để xác nhận các kênh EN/ZH hoạt động trơn tru.
7. **Bước 7:** Ghi nhận toàn bộ thay đổi kỹ thuật vào `docs_AI.md` và `thaydoicongnghe.md`.
