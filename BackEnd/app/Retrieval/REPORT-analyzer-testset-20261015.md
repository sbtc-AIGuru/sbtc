# Báo cáo bộ test công bằng cho MedicalAnalyzer — 15/10/2026

## Thiết kế

Tạo bộ fixture độc lập với output analyzer: 90 ca tổng hợp, 30 ca/ngôn ngữ. Mỗi ngôn ngữ có 4 ca trong từng nhóm rủi ro và 5 ca trong từng kiểu đầu vào. Sáu khái niệm được đối chiếu qua VI/EN/ZH; bốn khái niệm seed kiểm tra anchor chung, còn asthma/epilepsy chỉ yêu cầu giữ thuật ngữ, không ép seed lexicon phải gán anchor.

Fixture cho phép nhiều dạng phân đoạn hợp lệ, kiểm tra token thiết yếu, literal y khoa và anchor bị cấm. Không khóa toàn bộ thứ tự token. Chế độ challenge được báo riêng và không tính là pass. Không dùng `for_valid/`, query thi hoặc chunk thật; không thay đổi analyzer, lexicon hay dữ liệu gốc.

## Kiểm tra

- Schema/cân bằng fixture: đạt; 90 ID duy nhất, 30 mỗi ngôn ngữ, đủ sáu nhóm rủi ro/sáu kiểu đầu vào theo thiết kế.
- Retrieval suite: `python -m unittest discover -s sbtc/Scripts/Retrieval/tests -v` — **34 tests passed**.
- Analyzer diagnostic: 90 ca × 2 modes = 180 lần chạy; 6 ca có mismatch, gồm 4 contract và 2 challenge.
- Strict gate: xác minh trả exit code 1 do có bốn mismatch contract. Chế độ thường in toàn bộ mismatch nhưng giữ exit code 0 để phục vụ chẩn đoán.

## Kết quả theo ngôn ngữ

| Ngôn ngữ | Contract đạt | Contract mismatch | Challenge mismatch / tổng |
|---|---:|---:|---:|
| Việt | 23/23 | 0 | 0/7 |
| Anh | 23/23 | 0 | 1/7 |
| Trung | 19/23 | 4 | 1/7 |

## Mismatch cần xử lý ở task cải thiện analyzer riêng

1. **Tiếng Anh — dấu câu sát câu:** `Stroke.It can follow atrial fibrillation.` thành token `stroke.it`; `stroke` không có trong trường lexical chính/broad dù anchor nhận diện `local:stroke`. Đây là challenge, không nằm trong bốn contract lỗi.
2. **Tiếng Trung — literal Latin/số đứng cạnh chữ Hán:** `J18.9`, `500 mg`, `IL-6`, `SpO2`, `5.17 mmol/L`, `10 μg/kg` không được trích đầy đủ vào `exact` khi không có ranh giới ASCII rõ. Một mẫu còn trích `17mmol/l`, làm mất phần nguyên `5.`.
3. **Tiếng Trung — anchor trong chuỗi trộn script:** trong `糖尿病患者服用metformin`, anchor diabetes có nhưng `local:metformin` thiếu. Ranh giới chữ Latin liền với chữ Hán cần được xem xét riêng.

Các lỗi literal ở mẫu Trung tập trung vào ranh giới từ theo Unicode: `\b` và kiểm tra chữ liền kề kiểu ASCII không đủ cho chuỗi có Han characters. Đây là giả thuyết nguyên nhân dựa trên regex/boundary hiện tại và output quan sát; cần xác nhận khi sửa analyzer. Mismatch `Stroke.It` là lỗi tách ranh giới câu khác, không nên gộp vào cùng một bản sửa.

Trong quá trình rà gold, hai expectation tiếng Anh ban đầu đòi dạng stem cụ thể (`measur`, `dizzi`) dù từ bề mặt là cách kiểm tra công bằng hơn; đã sửa thành `measured`, `dizzy`. Với tiếng Trung `受体阻滞剂`, expectation cho phép cả cụm nguyên vẹn hoặc hai token có nghĩa `受体` + `阻滞剂`. Những điều chỉnh này tránh khóa test vào một stemmer hay cách segment cụ thể; chúng không loại bỏ mismatch của analyzer.

## Cách chạy

```bash
PY=sbtc/Scripts/Retrieval/.runtime/venv/bin/python
$PY -m unittest discover -s sbtc/Scripts/Retrieval/tests -v
$PY -m sbtc.Scripts.Retrieval.tests.analyze_fixture --json-report artifacts/retrieval/analyzer-testset-20261015/report.json
$PY -m sbtc.Scripts.Retrieval.tests.analyze_fixture --strict
```

Chi tiết toàn bộ mismatch và token quan sát được lưu tại `artifacts/retrieval/analyzer-testset-20261015/report.json`.

## Giới hạn

Đây là bộ kiểm tra hồi quy ngôn ngữ tổng hợp, không đại diện toàn bộ biến thể của website y khoa, không đo recall/precision/F2 retrieval và không chứng minh chất lượng trên corpus 20k hoặc full. Khi bổ sung ca mới, giữ cân bằng ba ngôn ngữ, ghi rõ rationale, và chỉ thay đổi kỳ vọng sau rà soát độc lập.
