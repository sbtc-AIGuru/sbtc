# Đặc tả: Bộ test công bằng cho MedicalAnalyzer đa ngôn ngữ

## Mục tiêu

Tạo bộ ca kiểm thử tái sử dụng cho phần phân tích/tách từ y khoa tiếng Việt, Anh và Trung. Bộ test phải phản ánh hợp đồng ngôn ngữ mong muốn một cách độc lập với output hiện tại của `MedicalAnalyzer`; dùng để phát hiện cả bỏ sót thuật ngữ lẫn khớp nhầm, không dùng làm benchmark điểm truy hồi.

## Giả định và ranh giới

- Phạm vi là analyzer và các trường đầu ra `contents`, `broad`, `folded`, `exact`, `anchors`; không đánh giá BM25 ranking, dịch query, reranking hoặc F2 cuộc thi.
- Chỉ dùng câu ví dụ tổng hợp do nhóm tự soạn. Không lấy `for_valid/`, query thi, qrels hoặc chunk thật để làm gold; không sửa corpus, index hay resource nguồn.
- Kỳ vọng được xác định từ yêu cầu ngôn ngữ và ý nghĩa y khoa, không chụp output analyzer hiện tại để làm đáp án.
- Tách từ hợp lệ có thể có nhiều dạng. Bộ test kiểm tra các token/điều kiện thiết yếu và các khớp sai bị cấm, không khóa toàn bộ danh sách token hay thứ tự nội bộ.
- Bộ test không thể bao quát mọi thuật ngữ y khoa; mục tiêu là bao phủ có hệ thống các nhóm lỗi thường gặp và để lộ thiếu hụt theo từng lát cắt.

## Quy mô và cân bằng

- Tổng cộng 90 ca: 30 tiếng Việt, 30 tiếng Anh, 30 tiếng Trung.
- Trong mỗi ngôn ngữ, 24 ca thuộc sáu nhóm rủi ro (mỗi nhóm 4 ca): Unicode/dấu câu; từ ghép/hình thái; mã y khoa, biomarker và liều; phủ định/acronym; trộn ngôn ngữ/biến thể; độ dài và chất lượng văn bản đầu vào.
- Sáu khái niệm đối chiếu ba ngôn ngữ tạo thêm 18 ca (6 khái niệm × 3 ngôn ngữ), để kiểm tra tính nhất quán giữa ngôn ngữ. Ít nhất hai khái niệm ngoài seed hiện tại chỉ kiểm tra khả năng giữ thuật ngữ và không gán anchor sai; không đòi lexicon hiện tại phải biết chúng.
- Trong 30 ca của mỗi ngôn ngữ, phân bố ít nhất sáu kiểu đầu vào: văn xuôi, hỏi–đáp, tiêu đề kèm nội dung, danh sách, văn bản dạng trường/bảng phẳng, và mẩu ngắn hoặc văn bản trộn ngôn ngữ. Không kiểu nào vượt quá 25% số ca của một ngôn ngữ.
- Báo cáo kết quả tách theo ngôn ngữ, nhóm rủi ro và kiểu đầu vào; không dùng một điểm gộp duy nhất để che lệch phân bố.

## Nhóm hành vi cần bao phủ

1. **Unicode và ranh giới:** dấu tiếng Việt dạng dựng sẵn/tổ hợp; full-width/half-width tiếng Trung; dấu câu sát từ; dấu câu CJK; viết tắt câu; entity HTML nếu analyzer nhận đầu vào có entity.
2. **Tách từ và cấu tạo từ:** thuật ngữ nhiều âm tiết tiếng Việt; compound tiếng Anh, số nhiều y khoa cổ điển và biến thể chính tả; từ ghép Trung giản thể/phồn thể và cụm y khoa dài.
3. **Literal y khoa:** ICD-10, gene/biomarker, ký hiệu Hy Lạp, mã có gạch nối/dấu chấm, số thập phân, đơn vị/liều và dạng có khoảng trắng hoặc không.
4. **Phủ định và acronym:** giữ riêng dấu hiệu phủ định và nội dung bị phủ định; phân biệt acronym viết hoa với từ thường khi hợp đồng cho phép; không biến tiêu đề phổ thông thành tín hiệu bệnh.
5. **Biến thể và trộn ngôn ngữ:** tên generic/alias có căn cứ, tên thuốc Anh trong câu Việt/Trung, chữ Hán phồn thể; không gán khái niệm quá rộng chỉ vì một thành phần từ trùng nhau.
6. **Kiểu văn bản và biên:** câu văn xuôi, câu hỏi bệnh nhân, tiêu đề, danh sách, đoạn ngắn, đoạn dài hơn, ký hiệu điều hướng hoặc phần nhiễu. Phần nhiễu chỉ kiểm tra không gây anchor sai; đặc tả không yêu cầu analyzer làm sạch hay viết lại văn bản nguồn.

## Hợp đồng dữ liệu và kiểm tra

Fixture dự kiến ở `tests/fixtures/medical_analyzer_cases.jsonl`, mỗi dòng có:

- `case_id`, `language`, `risk_group`, `input_style`, `text`, `status`, `source`, `rationale`;
- `required_any`: các dạng token/chuỗi token tương đương được chấp nhận, gắn với một hoặc nhiều trường analyzer;
- `required_exact`: mã, liều hoặc literal phải còn tra được trong `exact`;
- `required_none`: khớp từ hoặc anchor không được xuất hiện trong các ca phủ định;
- `anchors_include`, `anchors_exclude`, và `paired_concept` cho grounding/đối chiếu có kỳ vọng rõ;
- trạng thái kỳ vọng là `contract` hoặc `challenge`.

Runner ở `tests/analyze_fixture.py` sẽ đọc fixture, chạy analyzer thật ở cả index/query mode và xuất báo cáo theo ngôn ngữ/nhóm/kiểu, liệt kê từng mismatch cùng input và expectation. `contents`, `exact`, `anchors` phải nhất quán giữa hai mode; `broad` có thể khác. Chế độ chẩn đoán không âm thầm bỏ qua mismatch; chế độ strict trả exit code khác 0 khi bất kỳ ca `contract` nào sai. Các ca `challenge` được báo riêng. Ca chỉ được đổi từ challenge sang contract sau khi người phụ trách xác nhận kỳ vọng, không phải vì output hiện tại tiện đạt.

## Quy trình triển khai sau khi duyệt

1. Soạn fixture độc lập trước, cân bằng số lượng và kiểu đầu vào; rà chéo kỳ vọng theo ngôn ngữ mà không chạy analyzer để tạo đáp án.
2. Thêm runner/report và kiểm tra schema, ID duy nhất, cân bằng ba ngôn ngữ, phân bố risk/style, và các tham chiếu token hợp lệ.
3. Chạy fixture với analyzer hiện tại ở chế độ chẩn đoán; ghi rõ mismatch theo từng lát cắt, không sửa code analyzer trong phạm vi này.
4. Chạy suite retrieval hiện có để bảo đảm fixture/runner mới không phá test cũ. Ghi quyết định thiết kế, khó khăn và mismatch quan trọng vào `docs_AI.md`.

## Lệnh kiểm tra dự kiến

Runtime theo `sbtc/Scripts/Retrieval/README.md`:

```bash
PY=sbtc/Scripts/Retrieval/.runtime/venv/bin/python
$PY -m unittest discover -s sbtc/Scripts/Retrieval/tests -v
$PY -m sbtc.Scripts.Retrieval.tests.analyze_fixture --json-report artifacts/retrieval/analyzer-testset-20261015/report.json
$PY -m sbtc.Scripts.Retrieval.tests.analyze_fixture --strict
```

Tên module runner ở các lệnh trên có thể điều chỉnh theo quy ước import khi triển khai, nhưng không đổi runtime hoặc thêm dependency.

## Tiêu chí chấp nhận

- Có đúng 90 ca tổng, 30 ca cho mỗi ngôn ngữ, và có các nhóm/style như phần cân bằng.
- Mỗi ca có rationale, nguồn synthetic, ngôn ngữ, kiểu đầu vào và kỳ vọng có thể kiểm tra.
- Có positive assertions và negative assertions; có trường hợp query/index parity hoặc dạng tương đương ở ba ngôn ngữ.
- Kỳ vọng không phải snapshot toàn bộ output và không được sinh từ analyzer hiện tại.
- Báo cáo làm lộ mismatch hiện tại theo lát cắt; không được gộp hoặc đổi nhãn để che lỗi.
- Không thay đổi analyzer, lexicon sản xuất, dữ liệu nguồn, BM25 ranking, dependencies hay `for_valid/`.

## Rủi ro và cách xử lý

| Rủi ro | Tác động | Cách giảm |
|---|---|---|
| Gold tokenization áp đặt một cách tách duy nhất | Phạt analyzer hợp lệ khác biệt | Dùng các dạng tương đương cho phép, chỉ khóa token thiết yếu |
| Dựa quá nhiều vào seed lexicon hiện tại | Test thiên về khả năng sẵn có của code | Bổ sung thuật ngữ ngoài seed; chỉ yêu cầu bảo toàn lexical khi không có grounding được duyệt |
| Cân bằng số ca nhưng lệch độ khó | Điểm tổng gây hiểu nhầm | Chia báo cáo theo ngôn ngữ, risk group và input style; công bố số mẫu từng nhóm |
| Ví dụ tổng hợp thiếu tự nhiên | Không đại diện lỗi crawl thật | Đa dạng cấu trúc câu/độ dài/trộn ngôn ngữ; ghi rõ đây là regression set ngôn ngữ, không phải corpus benchmark |
| Ca đòi analyzer hiểu ngữ nghĩa phủ định hoặc loại TOC | Vượt trách nhiệm tokenizer | Chỉ kiểm tra giữ tín hiệu/token và không gán anchor sai; không yêu cầu phân loại nội dung hoặc làm sạch nguồn |

## Trạng thái duyệt

Người dùng đã duyệt phạm vi 90 ca tổng hợp, cân bằng 30 ca/ngôn ngữ, fixture + runner chẩn đoán/strict và không sửa analyzer trong lượt triển khai này.
