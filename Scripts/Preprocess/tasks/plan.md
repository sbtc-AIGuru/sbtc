# Kế hoạch triển khai Chunk Cleaning

Kế hoạch feature tiếp theo: [format-aware chunking](format-aware/plan.md),
[tiến độ](format-aware/todo.md). Nội dung bên dưới giữ lịch sử cleaning đã hoàn thành.

Trạng thái: **Đã triển khai và nghiệm thu ngày 2026-10-13**.
Kết quả: [REPORT-chunk-cleaning-pipeline.md](../REPORT-chunk-cleaning-pipeline.md).
Cleaner cuối: `verbatim-v4`; 53 tests đạt, full-run 20.000 record audit 0 errors.
Các bước và lệnh dưới đây là kế hoạch gốc; kết quả và giới hạn xem báo cáo.
Nguồn yêu cầu: [SPEC-chunk-cleaning-pipeline.md](../SPEC-chunk-cleaning-pipeline.md).
Checklist thực hiện: [todo.md](todo.md).
Lịch sử đã hoàn tất: [kế hoạch Hybrid v3](hybrid-v3/plan.md) và
[checklist Hybrid v3](hybrid-v3/todo.md).

## 1. Phạm vi và nguyên tắc

Triển khai cleaner bảo toàn văn bản y khoa tại bước tạo `source_text`, bổ sung
báo cáo làm sạch theo phiên bản, tích hợp chunk/audit và bảo vệ resume.
Giữ API `clean_to_verbatim(text) -> str`; bổ sung API nội bộ
`clean_with_report(text) -> tuple[str, dict]` để cùng dùng một lõi xử lý.
Python standard library tiếp tục là stack của component.

Mọi nguồn cho kiểm thử, khảo sát và benchmark là `datacrawl/test.jsonl`, chỉ đọc.
Fixture chọn record/substring thật từ tập này. Ca markup/validation lỗi dùng
bản sao trong bộ nhớ và thêm wrapper trình bày quanh nội dung thật; không
tự tạo tài liệu y khoa hoặc lấy dữ liệu từ corpus khác. Nếu thiếu một nhóm nội
dung, ghi rõ khoảng trống thay vì coi test tương tự là bằng chứng đã phủ nhóm đó.

Output thử nghiệm được tạo trong thư mục mới dưới `datacrawl/derived/`, có tên
baseline hoặc chunk-cleaning cùng run ID. Test streaming dùng thư mục tạm mới.
Không ghi đè dữ liệu, output hoặc checkpoint có sẵn. Giữ nguyên các thay đổi
đang có trong `verbatim.py` và `test_unit_verbatim.py` khi sửa phần liên quan.

## 2. Bằng chứng từ trạng thái hiện tại

Khảo sát chỉ đọc ngày 2026-10-13 cho thấy tập test có **20.000 record**,
**17.523 success** và **2.477 failed**. Đây là metadata đầu vào, chưa phải
kết quả chạy chunking bằng cleaner mới.

| Record/nhóm | Bằng chứng | Ý nghĩa cho kế hoạch |
|---|---|---|
| `118639` | Nội dung có `< 300 ml` | Regression bảo toàn dấu so sánh và liều lượng |
| `1040581` | Nội dung có `8*12` trong kích thước điện cực | Cleaner hiện xóa mọi `*` còn lại; cần bảo vệ phép nhân |
| `1032046` | Nội dung có `每天3~6餐` | Bảo toàn khoảng số; không ghép thành `36` |
| `2066978` | Tên hóa học kèm `[...][2,5]` | Giống reference link nhưng là trích dẫn; không bóc nếu thiếu definition hợp lệ |
| `115283` | Có soft hyphen U+00AD trong văn bản | Chốt quy tắc Unicode bằng mẫu thật |
| `104719`, `113731`, `125593` | Có cú pháp link/ảnh Markdown | Fixture chuyển sang nhãn hiển thị |
| `766444`, `766445`, `766446` | Có `：` hoặc `．` | Bảo vệ dấu câu mà chunker đang dùng |
| 100 record | Có ít nhất một ký tự trong nhóm invisible đã dò | Candidate để phân loại; không mặc định xóa toàn bộ |
| 0 record khớp table pipe, HTML tag, fenced code | Không có ví dụ trực tiếp theo các pattern đã dò | Các ca đó phải dùng wrapper trên snippet thật; ghi rõ là ca tạo biến thể |
| 0 document từ domain PubMed | Tập test không chứa nguồn EN PubMed mới | Không tuyên bố đã nghiệm thu trên corpus EN mới |

Các count regex là **candidate**, không phải nhãn chất lượng. Ví dụ match
`> 4` có thể là link điều hướng; dấu `_` có thể thuộc URL ảnh. Chỉ nâng thành
regression sau khi đọc ngữ cảnh.

Các phát hiện kỹ thuật cần giải quyết:

- `text.replace("|", " ")` và bước xóa tất cả dấu sao/backtick còn lại
  áp dụng quá rộng.
- `clean_to_verbatim` hiện chưa có version/report; source hash không giải thích
  nguyên nhân văn bản thay đổi.
- `chunk_cli._config_fingerprint()` chỉ gồm config/strategy/shard size, nên
  thay cleaner hiện không ngăn resume checkpoint cũ.
- `test_verbatim_cleaner.py` tự định nghĩa một cleaner cũ; test đó không chứng
  minh hành vi của cleaner production. Dùng test import module thật cho task này.
- Audit offset/coverage tái sử dụng cleaner chỉ chứng minh mapping sau làm sạch;
  nó không tự phát hiện cleaner đã làm mất một số liệu y khoa.

## 3. Hợp đồng kỹ thuật sẽ triển khai

### 3.1. API và báo cáo

Một lõi làm sạch dùng chung cho API chuỗi và API có report. Phiên bản đầu có
report đặt là `verbatim-v1`; tăng phiên bản khi đổi semantics/rule ảnh hưởng
`source_text`. Tách phiên bản cleaner khỏi `ChunkConfig.version` của thuật toán
paragraph. Mỗi run dùng một cleaner version duy nhất.

`cleaning` ở cấp document gồm:

- `version`, `input_sha256`, `output_sha256`, `input_chars`, `output_chars`.
- `actions`: map tên rule sang số lần biến đổi thực sự; giá trị nguyên không âm.
  Không cộng counters từ nhiều stage rồi diễn giải chúng thành số ký tự đã xóa.
- `warnings`: danh sách mã cảnh báo ổn định và count; không chứa timestamp,
  địa chỉ bộ nhớ hoặc dữ liệu làm output khác nhau giữa workers.

Văn bản nguồn chỉ được làm sạch một lần trong `chunk_document`; report có mặt
cả khi đã chạy cleaner nhưng kết quả rỗng. Failed/empty input được skip trước
cleaner thì không giả lập report đã chạy. Hash báo cáo khớp raw/source hash
hiện có. Counters chỉ phục vụ giải thích, không phải bằng chứng bảo toàn ngữ nghĩa.

### 3.2. Thứ tự và ranh giới rule

1. Phân biệt các vùng inline/fenced code và literal escape trước các rule có
   khả năng diễn giải nội dung đó thành markup. Không dùng sentinel có thể
   trùng ký tự NUL vốn nằm trong input.
2. Giữ chính sách giải mã entity tối đa hai lượt hiện tại, version hóa chính
   sách; chỉ tính action khi có thay đổi. Entity không nhận diện được giữ nguyên.
   Không tuyên bố cleaner idempotent với mọi mức entity lồng nhau.
3. Nhận diện HTML chắc chắn; giữ alt text ảnh trước khi bỏ thẻ. `br` và thẻ
   block tạo ranh giới dòng phù hợp; inline tag không tách từ vô lý. Script,
   style và comment đầy đủ được loại; cấu trúc hỏng/mơ hồ giữ nội dung và cảnh báo,
   không xóa từ một marker tới hết bài.
4. Link/ảnh Markdown có nhãn, đích và ngoặc cân bằng được bóc có giới hạn rõ.
   Reference link chỉ xử lý khi có definition tương ứng; giữ citation hóa học,
   ngoặc liều lượng và link lỗi. Bare URL không được nuốt dấu câu/nội dung sát URL.
5. Chỉ bóc emphasis/header/quote/table/fence khi đúng cấu trúc. Giữ
   multiplication `8*12`, ký hiệu `|` ngoài table, `_` nội từ và `~` đơn.
   Nội dung code được giữ, chỉ bỏ delimiter trình bày.
6. Chuẩn hóa Unicode theo allowlist. BOM đầu văn bản có thể bỏ; BOM giữa bài,
   ZWJ/ZWNJ, bidi và U+FFFD được giữ/cảnh báo nếu chưa có căn cứ riêng. Control
   nằm giữa hai token không được xóa gây ghép từ. Soft hyphen có rule theo ngữ
   cảnh thật. Không lower-case, bỏ dấu hoặc NFKC toàn văn bản.
7. Giữ các rule UI hẹp đã có; không mở rộng xóa boilerplate theo keyword.
   `detect_boilerplate` tiếp tục trả excluded span trên cleaned source.
8. Chuẩn hóa whitespace cuối cùng, giữ thứ tự câu và ranh giới đoạn.

Tất cả thay đổi có nguy cơ xóa nhầm phải có assertion nội dung kỳ vọng độc lập,
không lấy output của cleaner khác làm expected result.

### 3.3. Phiên bản, checkpoint và audit

Bổ sung `cleaner_version` vào checkpoint và vào config fingerprint của CLI.
Kiểm tra version trước recovery pending shard hoặc bất kỳ ghi checkpoint nào.
Checkpoint thiếu/sai version bị từ chối resume bằng lỗi cụ thể; người chạy dùng
output mới. Không tự chuyển đổi hoặc ghi lại checkpoint lịch sử.

Audit kiểm version trước tái tạo source và kiểm tra toàn bộ report, cả document
empty-after-cleaning. Output lịch sử không có version phải được báo là thiếu
thông tin để tái lập, không diễn giải thành ID sai. Thuật toán packing, parent
boundary, overlap và eligibility giữ hợp đồng v3; nếu source thay đổi thì offset,
hash và chunk ID có thể thay đổi theo source mới. Không trộn các run trong cùng
thư mục/index snapshot.

## 4. Thứ tự triển khai và dependency

```text
T1 fixtures + baseline
        |
T2 API/report
        |
T3 HTML/entity -> T4 links/references -> T5 formatting/code/table
        |                                      |
        +---------------- T6 Unicode/UI -------+
                              |
                     T7 chunk + audit
                              |
                     T8 CLI/resume
                              |
                 T9 full run + content review
                              |
                     T10 report/docs
```

Làm tuần tự vì các slice cùng sửa cleaner và dùng chung hợp đồng source/version.
Sau mỗi task cập nhật checklist. Không cần xin duyệt lại chi tiết nằm trong
đặc tả đã chốt. Nếu phát hiện phải đổi dependency, thuật toán chunk hoặc dữ liệu
gốc thì dừng riêng phần mở rộng đó và báo phạm vi vượt yêu cầu.

| Task | Việc làm | Phụ thuộc | File chính | Điểm đạt |
|---|---|---|---|---|
| T1 | Fixture thật và baseline trước thay đổi | Kế hoạch | Test mới, output baseline | Có ID/snippet, hash input, baseline audit |
| T2 | Một lõi cleaner, API report và counters | T1 | `verbatim.py`, test mới | API tương thích, report deterministic |
| T3 | HTML/entity và ranh giới dòng | T2 | `verbatim.py`, test mới | Không nuốt so sánh; giữ nhãn và cấu trúc |
| T4 | Link/ảnh/reference và URL | T3 | `verbatim.py`, test mới | Nhãn đúng; citation không bị bóc nhầm |
| T5 | Code, emphasis, table và literal symbols | T4 | `verbatim.py`, test mới | `8*12` và ký hiệu ngoài markup còn nguyên |
| T6 | Unicode, whitespace, UI và warnings | T5 | `verbatim.py`, test mới | Allowlist rõ, không ghép token do xóa control |
| T7 | Metadata document và audit | T6 | `chunking.py`, `chunk_audit.py`, test mới | ID/hash/slice/report/coverage đúng |
| T8 | Fingerprint, checkpoint và resume | T7 | `chunk_cli.py`, `test_chunk_streaming.py` | Không trộn cleaner; resume cùng version tương đương |
| T9 | Full run, so sánh baseline và đọc output | T8 | Output mới, report | Audit sạch, review phần đổi có bằng chứng |
| T10 | Review cuối và nhật ký | T9 | Report, spec, tasks, `docs_AI.md` | Hoàn tất tiêu chí hoặc ghi đúng phần chưa đạt |

Checkpoint A sau T2–T3: API/report hoạt động và HTML không làm mất medical tokens.
Checkpoint B sau T4–T6: các nhóm cleaning có regression và nội dung mơ hồ được giữ.
Checkpoint C sau T7–T8: worker/resume/audit đạt và từ chối version sai trước mutation.
Checkpoint D sau T9–T10: output full test, review nội dung và tài liệu đều đầy đủ.

## 5. Ma trận ca kiểm thử

| Nhóm | Ca thông thường | Ca biên/lỗi | Assertion chính |
|---|---|---|---|
| Validation | Record success thật | Copy record sai kiểu, failed, empty | Skip/error đúng, không ép ID/string |
| Report | Cùng text qua hai API | Counters 0, output rỗng, gọi lặp cùng input | Text khớp; report/hash deterministic |
| Entity/HTML | Encode snippet thật, tag p/br/em/img | So sánh, literal angle brackets, broken tag/script | Nội dung giữ đúng; không xóa lan |
| Link/URL | Link/ảnh thật, destination có ngoặc | Ngoặc lồng, malformed link, URL sát dấu câu | Giữ nhãn và câu kề; không còn target hợp lệ |
| Reference | Wrapper có definition hợp lệ | `2066978` có citation, thiếu definition | Chỉ unwrap khi definition khớp |
| Emphasis/code | Wrapper quanh snippet thật | `8*12`, escape, nested emphasis, unmatched fence | Không biến số/ký hiệu; code giữ content |
| Table | Wrapper có alignment row | Pipe ngoài table, pipe escaped | Giữ thứ tự cell; không xóa literal pipe |
| Unicode | Space Unicode, BOM đầu, soft hyphen thật | BOM giữa, ZWJ/ZWNJ, U+FFFD, control giữa token | Rule có chủ đích; không đoán ký tự lỗi |
| UI/boilerplate | Mẫu UI có rule đã xác nhận | Snippet gần giống, valid prefix trước excluded tail | False positive không xóa y khoa |
| Chunk integrity | Short QA, long/article, fullwidth punctuation | Empty-after-cleaning, oversized natural atom | Exact source slice, ID/order/coverage đúng |
| Audit | Output mới hợp lệ | Sửa metadata/hash/version trong bản copy | Báo lỗi field cụ thể, không false-pass |
| Resume | Cùng version, ngắt ở pending shard | Version đổi, thiếu version, input/config đổi | Từ chối trước mutation; kết quả cùng version khớp |
| Workers | 1 worker và 2 workers trên cùng sample | Resume có warnings/actions | JSON records và summary counts tương đương |

## 6. Lệnh kiểm tra và output

Chạy từ workspace root bằng interpreter hiện có. Repo dùng `unittest`; không có
cấu hình lint/type-check cho component này trong `sbtc/pyproject.toml`, vì vậy
không tự thêm framework. Các lệnh dưới đây là kế hoạch, chưa chạy ở lượt lập kế hoạch.

Focused suite mới (file sẽ được tạo ở T1–T2):
```bash
sbtc/.venv/bin/python -m unittest discover -s sbtc/tests -p 'test_chunk_cleaning.py' -v
```

Sau tích hợp, chạy suites chunking dùng `test.jsonl`:
```bash
sbtc/.venv/bin/python -m unittest discover -s sbtc/tests -p 'test_chunk_*.py' -v
```

Full run dùng thư mục mới, có thể mở trực tiếp trong workspace:
```bash
CHUNK_CLEAN_RUN="$(mktemp -d datacrawl/derived/chunk-cleaning-test-20261013-XXXXXX)"
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_cli \
  datacrawl/test.jsonl "$CHUNK_CLEAN_RUN" --strategy hybrid --workers 2
sbtc/.venv/bin/python -m sbtc.Scripts.Preprocess.chunk_audit \
  datacrawl/test.jsonl "$CHUNK_CLEAN_RUN"
```

Baseline ở T1 dùng chính CLI/audit hiện tại trước khi sửa code và một thư mục
`chunk-cleaning-baseline-20261013-XXXXXX` mới. Lưu kết quả baseline audit ngay
thời điểm đó; không dùng cleaner mới để tuyên bố audit được output lịch sử.

Report dự kiến: `sbtc/Scripts/Preprocess/REPORT-chunk-cleaning-pipeline.md`.
Report ghi đường dẫn tuyệt đối của run, hash input trước/sau, phiên bản cleaner,
số record/skip/error, actions/warnings, chunk distribution/overlap/coverage,
thời gian/RSS và kết quả review. Không đặt ngưỡng tốc độ suy đoán trước baseline.

## 7. Review chất lượng nội dung

- Kiểm mọi fixture bảo toàn và mọi cảnh báo bất thường được suites phát hiện.
- So sánh baseline/new theo `doc_id`: nhóm hash đổi, text rỗng mới, giảm độ dài
  lớn, thay đổi boundary, counters nhiều và warnings còn lại. Đọc toàn bộ ca
  mới bị rỗng; không bỏ chúng chỉ vì ít.
- Chọn mẫu đọc ít nhất 10 ca mỗi nhóm có dữ liệu: link/URL, số/so sánh/ký hiệu,
  Unicode, bảng/code dạng wrapper, boundary sau HTML, QA và fullwidth punctuation.
  Nhóm có ít hơn 10 thì đọc toàn bộ và ghi mẫu số. Các nhóm có thể trùng doc.
- Đối chiếu raw → source baseline → source mới → đầu/cuối chunk. Ghi snippet
  trước/sau và lý do đổi; riêng ranh giới câu phải phân biệt lỗi cleaner tạo
  newline với hành vi chunker có sẵn.
- Audit mapping đạt không thay thế review bảo toàn văn bản. Chưa có ground truth
  retrieval thì không tuyên bố F2 tăng.

## 8. Rủi ro và xử lý

| Rủi ro | Ảnh hưởng | Cách kiểm soát |
|---|---|---|
| Cleaner shared làm đổi hành vi caller khác | Cao | Giữ API, kiểm call sites, isolate thay đổi có expected độc lập |
| Ký hiệu y khoa bị coi là markup | Cao | Ưu tiên regression `8*12`, comparisons và chemical citations |
| URL regex nuốt phần câu | Cao | Ranh giới URL có giới hạn; ca sát punctuation và CJK |
| Thêm newline làm đổi packing | Trung bình | Source hash/boundary comparison; không nới max/coverage để pass |
| Resume trộn rule | Cao | Version/fingerprint check trước recovery; output mới |
| Metadata phình output | Trung bình | Counter và warning code; không nhân raw text trong mỗi chunk |
| Test thiếu EN/PubMed hoặc markup thật | Trung bình | Wrapper trên data thật; công bố rõ giới hạn và nhóm chưa phủ |
| Text đã hỏng ở công đoạn trước | Cao | Cleaner không phục hồi bằng suy đoán; không claim sửa mất dữ liệu trước đó |

Nếu 2–3 vòng sửa vẫn fail: xét lại expected, giả định grammar, ngữ cảnh nguồn
và thứ tự stage. Chỉ sửa assertion khi chứng minh expected trái đặc tả; không
nới gate bảo toàn, bỏ ca lỗi hoặc biến warning thành pass để hoàn tất.

## 9. Điều kiện hoàn thành

1. Các task/checkpoint có kết quả cụ thể và không còn lỗi bảo toàn nội dung được
   xác nhận trong phạm vi test.
2. Full run có cùng số record với input; audit 0 errors; ID/order/slice/coverage
   và cleaner report đúng trên mọi record thuộc hợp đồng.
3. Resume và workers cùng version tái lập output; version sai bị từ chối trước
   khi ghi file. SHA-256 của `datacrawl/test.jsonl` trước/sau bằng nhau.
4. Report có trường hợp trước/sau và hạn chế coverage; `docs_AI.md` ghi đủ
   thiết kế, lỗi/fix, lệnh và kết quả. Không ghi hoàn thành khi test chưa chạy.
