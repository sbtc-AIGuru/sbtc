# Đặc tả kỹ thuật: Tích hợp và Benchmark Dịch thuật Truy vấn Y khoa với Qwen2.5-1.5B-Instruct

- **Module**: `sbtc/Scripts/Retrieval/translation.py`, `sbtc/Scripts/Retrieval/scripts/`
- **Trạng thái**: Bản thảo đề xuất (Chờ duyệt)
- **Ngày lập**: 16/10/2026
- **Tác giả**: Antigravity Pair Programmer

---

## 1. Mục đích & Bối cảnh

### 1.1 Vấn đề của hệ thống hiện tại
- Hệ thống dịch truy vấn trước đó sử dụng **MultiMed-ST (M2M-100 fine-tuned 418M)**.
- Dù đã được tối ưu hóa CTranslate2 INT8 giúp giảm RAM còn 1.95 GB và tăng tốc gấp 4 lần, MultiMed-ST vẫn gặp **lỗi ngữ nghĩa y khoa nghiêm trọng** do bản chất là mô hình Seq2Seq tĩnh:
  - Dịch sai từ lóng lâm sàng Việt Nam: *"đi ngoài"* $\to$ *"walking outside"*, *"phân ướt"* $\to$ *"moisturizing"*, *"sản dịch"* $\to$ *"epidemic/proliferation"*, *"thiểu sản"* $\to$ *"deficit artery production"*, *"cảm mạo"* $\to$ *"tiêu chảy (腹泻)"* (bịa đặt triệu chứng).
  - Thất lạc định lượng/chỉ số xét nghiệm: Tỷ lệ làm mất số liệu y khoa (`3,0 mm`, `881,3`, `tuần 28`) lên đến 30% trên các câu truy vấn dài.
  - Phải duy trì **2 mô hình độc lập** (1 mô hình VI $\to$ EN và 1 mô hình VI $\to$ ZH), tốn tài nguyên và nhân đôi thời gian suy luận.

### 1.2 Giải pháp mới: Qwen2.5-1.5B-Instruct
- Sử dụng mô hình sinh đa ngôn ngữ mã nguồn mở **Qwen2.5-1.5B-Instruct** (Alibaba, 18T tokens pretraining).
- **Dual Translation trong 1 prompt**: Nhận vào câu truy vấn tiếng Việt, sinh đồng thời bản dịch chuẩn xác cả tiếng Anh (EN) và tiếng Trung (ZH) định dạng JSON sạch.
- Đạt chuẩn bất biến ViBioMIR: Open-weight Apache 2.0, dung lượng $1.5\text{B} \le 15\text{B}$, phát hành trước 01/08/2026.

---

## 2. Đặc tả Kỹ thuật Chi tiết

### 2.1 Input & Output
- **Input**:
  - `query_vi` (str): Câu hỏi y khoa tiếng Việt tự nhiên (hội thoại bệnh nhân, từ ngữ thông tục hoặc thuật ngữ chuyên sâu).
  - Tùy chọn `temperature=0.0` (greedy decoding) để đảm bảo tính tất định và bảo toàn chính xác số liệu y tế.
- **Output**:
  - `en` (str): Bản dịch tiếng Anh chuyên ngành y khoa chuẩn mực.
  - `zh` (str): Bản dịch tiếng Trung giản thể chuyên ngành y khoa chuẩn mực.
  - `metadata`: Thời gian sinh (latency ms), số lượng token sinh ra, cờ kiểm tra bảo toàn số liệu (`numbers_preserved`).

### 2.2 Cơ chế Prompting & Định dạng Trả về (Strict JSON Output)
Prompt thiết kế tối giản, chuyên biệt cho dịch thuật lâm sàng để tránh sinh râu ria hoặc hallucination:

```text
<|im_start|>system
You are a professional medical translator. Translate the given Vietnamese medical query into English and Simplified Chinese accurately.
Requirements:
1. Translate colloquial telemedicine terms into precise medical concepts (e.g., 'đi ngoài' -> 'diarrhea / frequent bowel movements' / '腹泻', 'sản dịch' -> 'lochia' / '恶露', 'thiểu sản' -> 'hypoplasia' / '发育不良', 'cảm mạo' -> 'common cold' / '感冒').
2. Preserve all exact numerical values, measurements, and units (e.g., '3,0 mm', '881,3', 'tuần 28').
3. Output strictly valid JSON with keys "en" and "zh". Do NOT write any introduction or explanation.
<|im_end|>
<|im_start|>user
Query: {query_vi}
<|im_end|>
<|im_start|>assistant
{{"en": "
```

### 2.3 Tiêu chuẩn Đánh giá: Độ chuẩn xác khi cắt (Segmentation Precision)
Người dùng đặc biệt quan tâm đến **độ chuẩn xác khi cắt**:
1. **Cắt bỏ râu ria (Prompt Hallucination / Boilerplate Stripping)**:
   - Output phải được bóc tách chuẩn xác vào 2 chuỗi văn bản sạch `en` và `zh`. Tuyệt đối không để lẫn các cụm từ giải thích (*"Here is the translation..."*).
2. **Bảo tồn ranh giới thực thể và định lượng (Entity & Number Boundary Guard)**:
   - Mọi số thực, số nguyên, phân số và đơn vị đo (`38,5 độ`, `3,0 mm`, `881,3`, `22 ngày`, `1 tháng 4 ngày`) trong câu nguồn bắt buộc phải xuất hiện nguyên vẹn trong bản dịch, không bị cắt đứt hoặc làm tròn sai lệch.
3. **Độ chuẩn xác phân tách token y khoa khi nạp vào Analyzer (Tokenization Segmentation)**:
   - Bản dịch tiếng Anh và tiếng Trung phải tạo ra các token y khoa đơn lẻ hoặc cụm ghép chuẩn xác khi đi qua Lucene ICU / Standard Analyzer.
   - Tránh phân tách thành các từ vô nghĩa phá hỏng chỉ số BM25 (như `walk` + `outside` thay vì `diarrhea`; `epidemic` thay vì `lochia`).

### 2.4 Tiêu chuẩn Đánh giá: Thời gian & Tài nguyên (Latency & Resources)
1. **Model Load Time**: Thời gian nạp trọng số vào bộ nhớ.
2. **Query Latency (ms)**: Thời gian hoàn tất cả 2 bản dịch (EN + ZH) cho 1 câu truy vấn.
3. **Throughput (queries/sec)**: Số lượng câu dịch được mỗi giây trên CPU AMD Ryzen 5 5500U.
4. **RAM Peak Consumption (MB)**: Bộ nhớ RAM tối đa bị chiếm dụng.
5. **Dung lượng lưu trữ đĩa (Disk Footprint)**: Dung lượng thư mục trọng số (FP16 vs INT8).

---

## 3. Danh mục Ca kiểm thử (Test Cases)

| Nhóm test | ID | Dữ liệu kiểm thử | Tiêu chuẩn đạt (Pass Criteria) |
| :--- | :--- | :--- | :--- |
| **Từ lóng lâm sàng** | TC-01 | `"Trẻ sơ sinh đi ngoài nhiều lần, phân ướt..."` | EN chứa `diarrhea` / `loose stools` (không có `walk outside`). ZH chứa `腹泻` / `大便稀` (không có `出门`, `润肤`). |
| **Thuật ngữ giải phẫu** | TC-02 | `"Thiểu sản động mạch thông sau hai bên là gì?"` | EN chứa `posterior communicating artery hypoplasia`. ZH chứa `后交通动脉发育不良`. |
| **Bảo toàn số & phân đoạn** | TC-03 | `"Em chuyển phôi IVF 21 ngày... đường kính 3,0 mm... beta là 881,3. Chuyển phôi ngày 2"` | EN và ZH bảo toàn đủ 100% các số: `21`, `3,0` (hoặc `3.0`), `881,3` (hoặc `881.3`), `2`. |
| **Tránh bịa triệu chứng** | TC-04 | `"Bầu bị sốt nhẹ 38,5 độ do cảm mạo bình thường..."` | EN dịch `common cold`, ZH dịch `感冒`. Tuyệt đối không dịch thành tiêu chảy (`腹泻`). Số `38,5` và `28` được bảo toàn. |
| **Xử lý chuỗi rỗng / biên** | TC-05 | Chuỗi chỉ có số hoặc ký tự lạ: `"12345???"` | Không crash, trả về cấu trúc JSON hợp lệ. |

---

## 4. Kế hoạch Thực hiện Chi tiết

1. **Bước 1: Tải weights & cấu hình Qwen2.5-1.5B-Instruct**:
   - Tải mô hình vào `artifacts/models/Qwen2.5-1.5B-Instruct/` (sử dụng Hugging Face Hub / safetensors, dung lượng ~3.09 GB).
   - Kiểm tra tương thích suy luận trực tiếp với PyTorch bfloat16 / CPU.
2. **Bước 2: Xây dựng Module suy luận Qwen2.5 (`sbtc/Scripts/Retrieval/translation.py`)**:
   - Hiện thực lớp `QwenQueryTranslator` kế thừa cấu trúc dịch chuẩn.
   - Tích hợp Number Guard và bộ trích xuất JSON chống lỗi cú pháp.
3. **Bước 3: Chạy Benchmark thực nghiệm trên 10 câu mẫu (Seed 42)**:
   - Dùng script `sbtc/Scripts/Retrieval/scripts/benchmark_qwen_vs_multimed.py`.
   - So sánh trực tiếp 3 cột mốc:
     1. MultiMed-ST PyTorch FP32
     2. MultiMed-ST CTranslate2 INT8
     3. Qwen2.5-1.5B-Instruct
   - Đo đạc chính xác: Latency, Throughput, Peak RAM, Number Preservation rate, và Bảng đối chiếu từ khóa y khoa.
4. **Bước 4: Đánh giá chất lượng dịch bằng LLM & Chấm điểm lâm sàng**:
   - Phân tích chi tiết từng câu dịch của Qwen2.5 so với MultiMed-ST.
   - Chấm điểm trên thang 10 theo tiêu chuẩn y khoa quốc tế (MeSH / ICD-10).
5. **Bước 5: Ghi nhận nhật ký**:
   - Báo cáo kết quả ra `REPORT_benchmark_qwen_vs_multimed.md`.
   - Cập nhật đầy đủ vào `docs_AI.md` và `thaydoicongnghe.md`.
