# Implementation plan: Hybrid Chunking v3

Đặc tả đã duyệt: `../../SPEC-hybrid-chunking-v3-improvement.md`. Đây là phần mở
rộng của component paragraph chunking đã hoàn tất. Mọi kiểm thử/benchmark chỉ
đọc `datacrawl/test.jsonl`; output mới ghi dưới `/tmp`.

## Kiến trúc và dependency

```text
sentence/clause atoms
        │
        ├── overlap-aware packing + short-tail rebalance
        │                     │
boilerplate span detector ────┤
                              ▼
                  document/parent/child output v3
                              │
                    CLI metrics + independent audit
                              │
                    full-run review and comparison
```

- `source_text` vẫn là nguồn offset duy nhất; mọi atom/chunk/excluded span là
  exact slice liên tục.
- Tách boundary và detector thành helper rõ trách nhiệm; orchestration ở
  `chunking.py`, không thêm dependency ngoài standard library.
- Chạy `paragraph-v3` như output mới; giữ `/tmp/aiguru-chunks-v2-20261008` làm
  baseline và không resume checkpoint v2.
- Boilerplate là span có provenance và eligibility; không sửa/xóa source.

## Thứ tự thực hiện

### Phase 1: Boundary foundation

1. Viết regression tests cho sentence/clause boundary đa ngôn ngữ và các doc
   oversized thật; chứng minh test thất bại trên v2.
2. Thêm atom splitter exact-slice, tránh decimal/domain/abbreviation, chỉ giữ
   oversized khi một atom tự nó không có boundary phù hợp.

Checkpoint: exact slice/coverage đạt trên mẫu thật, `doc_id 1429888` không còn
`oversized_paragraph`.

### Phase 2: Packing quality

3. Viết test overlap dài hơn 40 và residual ngắn; thêm packer chừa overlap,
   lookahead/rebalance, reason cho mọi ngoại lệ.
4. Giữ parent containment và deterministic IDs; thêm metadata v3 trên child và
   document.

Checkpoint: test overlap, short-tail, parent/child và worker/resume đều đạt.

### Phase 3: Boilerplate provenance

5. Viết regression tests cho các `doc_id` 103925, 2443608, 2991145, 942223.
6. Thêm detector high-confidence theo span; prefix hợp lệ vẫn index, excluded
   span giữ exact slice/rule/reason/confidence.

Checkpoint: included + excluded phủ 100% nguồn; không mất câu hỏi hợp lệ trong
chunk hỗn hợp.

### Phase 4: Operations and review

7. Mở rộng summary/audit/benchmark cho overlap denominator, short reasons,
   oversized atoms và excluded spans.
8. Chạy toàn bộ 20.000 record vào `/tmp/aiguru-chunks-v3-20261008`, audit độc
   lập, so sánh v2/v3 và kiểm tra source hash.
9. Rà soát câu chữ tại boundary trên mẫu phân tầng: đầu/cuối chunk, punctuation
   Trung/Việt/Anh, oversized cũ, overlap và boilerplate. Ghi ví dụ lỗi, sửa và
   chạy lại nếu còn cắt vô lý.
10. Cập nhật `docs_AI.md` với thay đổi thiết kế, lỗi đã sửa, metric và giới hạn.

## Rủi ro và cách kiểm soát

| Rủi ro | Mức | Kiểm soát |
|---|---|---|
| Tách sai dấu chấm trong số/domain/viết tắt | Cao | Fixtures thật + exact boundary review |
| Overlap làm vượt 300 | Cao | Reserve budget, rebalance, exception bắt buộc |
| Parent nhỏ tạo chunk ngắn | Trung bình | Coalesce/reason, không gộp qua strong boundary mù |
| Boilerplate false positive | Cao | High-confidence nhiều tín hiệu, giữ span và review phân tầng |
| Output tăng mạnh do sentence atoms | Trung bình | Benchmark count/bytes/RSS với v2 |
| Metric đẹp nhưng retrieval kém | Cao | Không kết luận F2; giữ v2 baseline |

## Điều kiện hoàn thành

- Toàn bộ tiêu chí mục 7 của spec đạt hoặc phần chưa đạt được nêu bằng số liệu
  và nguyên nhân cụ thể.
- Audit 20.000/20.000 record không lỗi, source SHA-256 không đổi.
- Báo cáo review trả lời trực tiếp: câu đầu/cuối có tự nhiên không, có cắt giữa
  token/số/domain/câu không, và ngoại lệ nào còn lại.
