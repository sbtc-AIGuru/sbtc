# Báo cáo nghiệm thu Chunk Cleaning

Ngày: 2026-10-13. Trạng thái: **Hoàn tất phần chunk-cleaning theo đặc tả**.
Cleaner: `verbatim-v4`; thuật toán chunk tiếp tục là `paragraph-v3`.
Đặc tả: [SPEC](SPEC-chunk-cleaning-pipeline.md). Kế hoạch: [tasks/plan.md](tasks/plan.md).

## 1. Output và bằng chứng

Thư mục output cuối, mở được trực tiếp trong workspace:

```text
/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/chunks/
```

Có **20 shards** `part-000000.jsonl` đến `part-000019.jsonl` và
`checkpoint.json`. Mỗi dòng tương ứng một record input; children chứa các chunk.
Không phải mỗi dòng là một chunk riêng.

| Artifact | Đường dẫn |
|---|---|
| Shard đầu | [part-000000.jsonl](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/chunks/part-000000.jsonl) |
| Summary | [summary.json](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/summary.json) |
| Audit | [audit.json](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/audit.json) |
| Toàn vẹn input | [input_integrity.json](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/input_integrity.json) |
| So sánh tất cả doc đổi | [cleaning_comparison.json](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/cleaning_comparison.json) |
| Mẫu đọc trước–sau/boundary/wrappers | [review_cases.json](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/review_cases.json) |
| Script tái lập review | [review_test_output.py](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/review_test_output.py) |
| Code snapshot | [snapshot/](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/snapshot/) |

Baseline trước khi sửa:
`/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-baseline-20261013-d28445jp/`.
Baseline audit đạt 0 errors bằng đúng code tại thời điểm đó.
Các run thử cleaner v1/v2/v3 được giữ nguyên để tra cứu; **run v4 ở trên là bản
nghiệm thu**. Không resume/mix checkpoint cũ vào run này.

## 2. Thay đổi đã triển khai

- Một lõi cung cấp `clean_to_verbatim(text) -> str` và
  `clean_with_report(text) -> tuple[str, dict]`; báo cáo gồm phiên bản, hash,
  length, action counters và warning codes.
- HTML được nhận diện theo tag hỗ trợ; giữ alt text trước khi bỏ ảnh, giữ
  ranh giới block, bảo vệ so sánh toán học và giữ/cảnh báo markup mơ hồ.
- Scanner có giới hạn xử lý ngoặc/nhãn lồng nhau, ảnh trong link và reference
  có definition. Bare URL/base64 không nuốt dấu câu hoặc phần CJK sát đích.
- Bảo vệ nội dung code/escape trước rule markup; giữ phép nhân, underscore nội
  từ, khoảng số có tilde và pipe ngoài table. Table chỉ bóc khi có alignment row.
- Entity giải mã tối đa hai lượt theo tên đầy đủ có dấu chấm phẩy; unknown entity
  được giữ, tránh giải mã nhầm tiền tố tên. Unicode theo allowlist, không NFKC
  hoặc lower-case văn bản nguồn. Control dùng separator để tránh ghép token.
- UI Long Châu dùng rule hẹp đã có. Source chỉ còn marker/URL không sinh chunk.
  Ký hiệu có thể mang nghĩa như `+` không bị đưa vào tập marker xóa.
- Chunk/audit cùng dùng một source và report; có report cả empty-after-cleaning.
  CLI lưu cleaner version trong checkpoint/fingerprint, kiểm trước recovery.
  Summary cộng counters/warnings ở cấp document.

Không thay đổi dữ liệu crawl, corpus, input test, thuật toán packing hoặc
boilerplate detector. Source của offset vẫn là văn bản sau làm sạch.

## 3. Kiểm chứng

**53/53 tests** của `test_chunk_*.py` đạt: 26 tests cleaning, 20 component,
7 streaming. Các test mới dùng record/snippet từ `datacrawl/test.jsonl`;
markup và lỗi schema là biến thể trong bộ nhớ, không tạo dữ liệu y khoa mới.

Các regression được chứng minh thất bại trước sửa gồm: `8*12 -> 812`, mất
HTML alt, URL nuốt CJK, reference/nested image, code/table/Unicode, metadata,
resume sai version và marker-only tạo chunk rỗng nội dung.
Đảo điều kiện version guard làm suite streaming fail; đã phục hồi nguyên byte
code rồi chạy lại suite đạt. Không bỏ/nới assertion để pass.

`git diff --check` đạt. Code snapshot của run cuối khớp code đang dùng.
Repo không có cấu hình lint/type check riêng cho component; không thêm framework.
Các suite crawler/legacy synthetic ngoài phạm vi không được chạy.

| Chỉ số | Baseline | Cleaner v4 |
|---|---:|---:|
| Input records | 20000 | 20000 |
| Document ok | 17523 | 17523 |
| Skipped (crawl_failed) | 2477 | 2477 |
| Pipeline errors | 0 | 0 |
| Parent | 50682 | 50682 |
| Child chunks | 134224 | 134224 |
| Oversized atoms | 3 | 3 |
| Mean units/chunk | 201.6160 | 201.6149 |
| Eligible overlap 30–50 units | 86.4643% | 86.4655% |
| Coverage trên cleaned source, kể cả excluded span | 100% | 100% |
| Audit errors | 0 | 0 |

Input SHA-256 trước/sau và baseline cùng bằng:

```text
5a0036c791ea2057f8761bb49808b5b8b4dd47b8806fed0e22e789d643765583
```

Runtime v4: 88.73 giây với 2 workers;
RSS peak của process cha 34220 KiB.
Thời gian baseline 163.03 giây được đo ở thời điểm khác,
không phải benchmark kiểm soát tải; không dùng để tuyên bố speedup production.
Units là đơn vị của chunker, không phải model tokens.

## 4. Bảo toàn nội dung và đọc output

- **247/17523** document có cleaned source thay đổi; cùng
  247 document có children đổi. Không có document rỗng mới.
- **541** biểu thức `< số`, phép nhân và khoảng số tìm thấy
  trong nguồn đều còn trong cleaned source (sau chuẩn hóa whitespace được cho phép).
  Đây là kiểm tra các pattern cụ thể, không phải chứng minh mọi nội dung y khoa.
- Đọc 10 case/nhóm links, medical symbols, Unicode, QA, fullwidth;
  10 record thật được bọc HTML/table/code (30 phép kiểm tra, 0 fail);
  20 document được đọc đầu/cuối chunk và ngữ cảnh quanh boundary.
- Đọc nhóm giảm độ dài lớn nhất. Ví dụ `200652` giảm 108 ký tự do bỏ cú pháp/
  title target lặp, giữ nhãn hiển thị và đoạn bên cạnh.
- `1040581`: phép nhân `8*12` được giữ; `118639`: `< 300 ml` được giữ;
  `1032046`: `每天3~6餐` được giữ; `2066978`: citation hóa học không bị
  hiểu nhầm thành reference link. `204811`: ảnh trong link chỉ giữ alt.
- Report counters từ review độc lập khớp summary của CLI. Mẫu review v4 khớp
  byte-for-byte với các mẫu v3 đã đọc; guard marker-only mới không đổi các mẫu này.

**Kết luận trong phạm vi:** các case được kiểm tra giữ câu chữ/số liệu theo
hợp đồng và không thấy mất nội dung mới do cleaner. Audit mapping đạt trên full
test. Output vẫn có các ngoại lệ/cảnh báo dưới đây; không kết luận mọi chunk
đều kết thúc ở trọn câu hoặc retrieval/F2 đã tăng.

## 5. Cảnh báo và giới hạn còn lại

| Warning | Document có warning | Số lần xuất hiện |
|---|---:|---:|
| `retained_format_character` | 132 | 577 |
| `unresolved_emphasis` | 1 | 1 |
| `unresolved_entity` | 1 | 1 |
| `incomplete_markdown_link` | 225 | 1493 |
| `replacement_character` | 203 | 22780 |
| `ambiguous_markdown_target` | 1 | 1 |

Các hàng có thể trùng document, không cộng thành số doc duy nhất.
`203` document trong **test.jsonl** vốn có `�` (22.780 ký tự); cleaner giữ và
cảnh báo, không đoán ký tự mất. Một số link đã hỏng từ input như
`[[email protected]](` và citation mất đích được giữ để không nuốt văn bản
kế bên. `317672` có chuỗi giống entity `&DL;` nhưng không phải tên entity
hỗ trợ. `204815` còn emphasis mơ hồ `__Cách...`, được ghi warning.

Ba oversized atoms đã có trong baseline:
`1714705/order 7: 405 units`, `1714705/order 12: 306 units`,
`4142716/order 5: 589 units`. Chunking v3 không tìm được boundary nhỏ hơn
theo rule hiện tại. Đây là phần phân đoạn riêng, không sửa trong task cleaner.

Rà boundary thấy **doc 766452, child 0** kết thúc sau `8、` trong
`8、9个月`. Child 1 bắt đầu từ offset 214, overlap 28 units và chứa nguyên
cụm `8、9个月`; child 0 kết thúc ở offset 247. Điểm cắt này có từ baseline,
không do cleaner, nhưng cần cải thiện nếu muốn mọi biên chunk đều tự nhiên.
Các biên clause/colon khác cũng có thể chia một câu dài; không tuyên bố
“không cắt giữa câu” cho thuật toán v3 đang giữ nguyên.

Tập test không có PubMed; chưa nghiệm thu trên corpus EN mới hoặc chạy
`data_final/`. HTML/table/code không có mẫu trực tiếp theo khảo sát test;
nhóm đó dùng wrapper trên snippet thật. Cleaner là subset bảo thủ của markup
Crawl4AI, không phải parser tuân thủ đầy đủ CommonMark. Bare relative targets
dạng từ đơn được giữ/cảnh báo; entity không có semicolon không được tự giải mã.

Cleaner chỉ xử lý văn bản đầu vào còn hiện diện; không khôi phục phần đã bị
lọc mất ở công đoạn crawl/merge trước đó. Một số script crawler/build có
cleaner sao chép riêng; cập nhật helper dùng chung này không tự sửa các bản
sao hoặc dữ liệu đã xuất bởi chúng. Không coi kết quả test này là bằng chứng
`data_final/` đã được sửa hoặc nghiệm thu lại.

## 6. Lệnh tái lập

Chạy từ workspace root. Output mới phải là thư mục trống:

```bash
sbtc/.venv/bin/python -m unittest discover -s sbtc/tests -p 'test_chunk_*.py' -v
CHUNK_CLEAN_RUN="$(mktemp -d datacrawl/derived/chunk-cleaning-new-XXXXXX)"
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_cli \
  datacrawl/test.jsonl "$CHUNK_CLEAN_RUN" --strategy hybrid --workers 2
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_audit \
  datacrawl/test.jsonl "$CHUNK_CLEAN_RUN"
```

Audit run đã lưu:
```bash
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_audit \
  datacrawl/test.jsonl /home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/derived/chunk-cleaning-verbatim-v4-20261013-svu22oxa/chunks
```

Khi đổi rule ảnh hưởng source, tăng cleaner version và tạo run mới.
