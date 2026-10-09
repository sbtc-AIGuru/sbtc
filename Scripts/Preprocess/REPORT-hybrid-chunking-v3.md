# Báo cáo kiểm chứng Hybrid Chunking v3

Ngày đánh giá: 2026-10-08  
Input duy nhất: `datacrawl/test.jsonl`  
SHA-256 input: `5a0036c791ea2057f8761bb49808b5b8b4dd47b8806fed0e22e789d643765583`  
Output được đánh giá: `/tmp/aiguru-chunks-v3-final3-20261008`

## 1. Kết luận

Hybrid v3 đạt các quality gate cấu trúc trong đặc tả và phù hợp để dùng làm
ứng viên indexing tiếp theo. Các điểm cắt không nằm giữa token; source,
`doc_id`, offset và coverage được audit đầy đủ. Vấn đề paragraph quá dài của
v2 gần như được loại bỏ, overlap trong cùng parent ổn định hơn và số chunk quá
ngắn giảm rõ rệt.

Chưa có ground truth relevance hoặc kết quả submission để kết luận F2 tăng.
V2 nên tiếp tục được giữ làm baseline cho vòng đánh giá retrieval.

## 2. Kết quả toàn bộ `test.jsonl`

| Chỉ số | v2 | v3 | Thay đổi |
|---|---:|---:|---:|
| Record input | 20.000 | 20.000 | bằng nhau |
| Record chunk thành công | 17.523 | 17.523 | bằng nhau |
| Record crawl lỗi được skip | 2.477 | 2.477 | bằng nhau |
| Parent | 50.858 | 50.657 | -0,40% |
| Child chunk | 137.242 | 134.144 | -2,26% |
| Chunk `<100` units | 22.223 | 14.898 | -32,96% |
| Chunk `>300` units | 2.659 | 3 | -99,89% |
| Unit lớn nhất | 9.289 | 589 | -93,66% |
| Document-level overlap dương | 41,85% | 71,52% | +29,67 điểm % |
| Eligible within-parent overlap dương | 58,00% | 99,91% | +41,91 điểm % |
| Eligible overlap nằm trong 30–50 units | chưa có | 86,46% | metric mới |
| Coverage ký tự không trắng | 100% | 100% | giữ nguyên |
| Audit error | 0 | 0 | giữ nguyên |

Phân bố 134.144 chunk v3: 6.907 ở dải 0–49, 7.991 ở 50–99,
8.893 ở 100–149, 43.889 ở 150–219, 66.461 ở 220–300 và 3 trên 300.
Chunk `<100` còn chiếm 11,11%; tất cả có `short_chunk_reason`.

## 3. Đánh giá câu chữ và điểm cắt

### Không cắt giữa token hoặc làm biến dạng câu chữ

- Đối chiếu cả 134.144 child với `source_text` cho 0 trường hợp bắt đầu hoặc
  kết thúc giữa token.
- Mỗi `chunk_text` là exact slice liên tục theo `start_char:end_char`; không
  dịch, tóm tắt, viết lại hoặc nối hai đoạn rời nhau.
- Audit kiểm tra `doc_id`, parent containment, exact slice và hợp của phần
  indexed + excluded; kết quả 20.000/20.000 record, 0 lỗi.
- 134.113/134.144 chunk, tương đương 99,98%, giữ nguyên ranh giới cấu trúc.

### Các lỗi cắt cụ thể đã được sửa

- `doc_id 1429888`: v2 có các chunk 9.289 và 1.583 units. V3 tạo 52 chunk,
  phần lớn 220–265 units, dùng ranh giới câu/mệnh đề và overlap 32–50 units.
- `doc_id 884718`: dấu chấm toàn chiều rộng `．` được nhận là boundary. Một
  mutation cố ý bỏ ký tự này làm test hồi quy thất bại, xác nhận test có khả
  năng phát hiện regression.
- `doc_id 101063`: heading ngắn `Mía` được chuyển sang đầu chunk có nội dung
  theo sau, không còn bị bỏ cô lập ở cuối chunk trước.
- Decimal, domain và viết tắt được giữ nguyên trong atom; test bao phủ các mẫu
  `2.5`, `example.com` và `BS.`.

### Ba ngoại lệ trên 300 units

- `doc_id 1714705`: hai atom 405 và 306 units.
- `doc_id 4142716`: một atom văn ngôn Trung Quốc 589 units.

Ba atom không có boundary câu/mệnh đề tự nhiên đủ tin cậy trong source. Chúng
được giữ nguyên với `oversized_atom`. Cắt theo số ký tự ở đây sẽ chia câu tùy
tiện và làm giảm tính nguyên bản ngữ nghĩa, nên giữ ngoại lệ là lựa chọn hợp lý.

### Overlap còn ngoài khoảng mục tiêu

83.413/83.487 transition đủ điều kiện có overlap dương. Có 74 transition bằng
0; tất cả có exception và các mẫu kiểm tra là ranh giới câu/đoạn hoàn chỉnh bị
giới hạn bởi `max_capacity`, không phải cắt giữa token. Trong số transition có
overlap, 72.183 nằm trong mục tiêu 30–50 units. Phần còn lại chủ yếu là atom
ngắn, giới hạn capacity hoặc atom không thể chia tự nhiên.

## 4. Chunk ngắn còn lại

14.898 chunk `<100` đều có lý do:

| Lý do | Số lượng | Diễn giải |
|---|---:|---|
| `atomic_section` | 12.873 | section/caption/list ngắn có boundary mạnh |
| `short_document` | 1.978 | toàn bộ tài liệu vốn ngắn |
| `qa_atomic` | 45 | cặp hỏi đáp ngắn cần giữ nguyên |
| `oversized_neighbor` | 2 | nằm cạnh atom quá lớn, không thể rebalance an toàn |

Không nên ép các chunk này đủ 100 units bằng cách trộn tài liệu, Q&A hoặc
section không liên quan. Số lượng vẫn đáng theo dõi trong retrieval benchmark;
metric cấu trúc một mình chưa chứng minh từng chunk ngắn là hữu ích.

## 5. Boilerplate

V3 đánh dấu 422 high-confidence span, tổng 313.983 ký tự không trắng, tương
đương 0,734% source. Nội dung không bị xóa khỏi `source_text`; chỉ bị đặt
`retrieval_eligible=false` và giữ exact offset, rule, reason.

| Rule | Số span |
|---|---:|
| `alphabetical_navigation_tail` | 250 |
| `unsupported_audio_line` | 94 |
| `related_arrow_tail` | 56 |
| `related_content_tail` | 19 |
| `department_navigation_block` | 2 |
| `booking_contact_tail` | 1 |

Rà soát phân tầng 200 span gồm toàn bộ 94 audio, 56 related-arrow, 19
related-content, 1 booking, 2 department và 28 alphabetical-navigation đầu
tiên không ghi nhận false positive. Đây là rà soát rule và câu chữ trên tập
test, chưa thay thế đánh giá relevance độc lập trên corpus đầy đủ.

## 6. Vận hành và giới hạn

- Output v3 khoảng 170 MB, tăng từ khoảng 145 MB của v2 do metadata, overlap
  và provenance chi tiết hơn.
- Full run dùng 2 worker mất 81,77 giây, khoảng 244,58 record/giây; số này chỉ
  mô tả môi trường chạy hiện tại.
- 2.477 record crawl lỗi không có text vẫn được skip và ghi reason; chunker
  không thể khôi phục nội dung chưa crawl được.
- Run mới lưu toàn bộ `ChunkConfig` trong checkpoint; audit tự đọc đúng cấu
  hình thay vì dùng ngưỡng 300 cố định. Checkpoint cũ không có trường này được
  audit bằng cấu hình mặc định để tương thích với output v2/v3 đã sinh.
- Chưa đo số model token vì embedding model chưa được chọn.
- Chưa có đánh giá retrieval/F2, nên quyết định thay v2 trong pipeline chính
  cần một benchmark retrieval riêng cùng encoder, index và top-K.

## 7. Lệnh tái lập

```bash
sbtc/.venv/bin/python -m unittest discover -s sbtc/tests -p 'test_chunk_*.py' -v
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_cli \
  datacrawl/test.jsonl /tmp/aiguru-chunks-v3-final3-20261008 \
  --strategy hybrid --workers 2
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_audit \
  datacrawl/test.jsonl /tmp/aiguru-chunks-v3-final3-20261008
```

CLI từ chối ghi đè thư mục output đã có. Dùng thư mục mới để chạy lại, hoặc
thêm `--resume` khi tiếp tục đúng input và cấu hình của một run bị gián đoạn.
