# Đặc tả: Sửa literal y khoa sát chữ Hán và acronym giả tiếng Anh

**Trạng thái:** Đã được duyệt và triển khai xong trên snapshot `test20k`; xem [báo cáo kết quả](REPORT-analyzer-literal-acronym-fixes-20261015.md). Chưa đo Precision/Recall/F2 vì không có qrels độc lập.

## 1. Mục tiêu

Sửa hai điểm yếu đã quan sát ở `MedicalAnalyzer`:

1. Nhận diện nhất quán mã y khoa, biomarker và liều lượng khi chúng dính trực tiếp với chữ Hán, đồng thời không cắt sai số thập phân.
2. Giảm token acronym giả sinh ra từ tiêu đề/mục cấu trúc tiếng Anh viết hoa toàn bộ, nhưng vẫn giữ literal y khoa và acronym có ích.
3. Dựng index dẫn xuất mới từ tập chunk test20k và so sánh retrieval trước/sau trên cùng dữ liệu, cùng truy vấn và cùng cấu hình.

Thành công ở giai đoạn này nghĩa là hai lỗi analyzer được sửa, snapshot test20k được dựng lại đúng fingerprint và tác động retrieval được báo cáo có giới hạn rõ. Không tuyên bố điểm Precision/Recall/F2 nếu không có nhãn liên quan độc lập được phép sử dụng.

## 2. Bằng chứng hiện trạng

- `analyzers.py` dùng `\b` trong regex liều lượng/ký hiệu. Ranh giới từ của Python coi chữ Hán là ký tự chữ, nên literal Latin hoặc số ngay sau chữ Hán có thể không được lấy vào trường `exact`.
- Báo cáo analyzer trước đây ghi nhận các trường hợp `J18.9`, `500 mg`, `IL-6`, `SpO2`, `5.17 mmol/L` và `10 μg/kg` không được trích đầy đủ khi nằm sát chữ Hán; có mẫu sinh nhầm `17mmol/l` thay cho `5.17mmol/l`.
- `exact_tokens()` hiện thêm `case_upper_<token>` cho mọi chuỗi in hoa 2–8 ký tự. Mẫu chunk thực tế đã sinh marker như `case_upper_methods`, `case_upper_setting`, `case_upper_primary` và `case_upper_outcome`; các marker này được lập chỉ mục ở trường `exact` có trọng số BM25 2.0.
- Báo cáo cũ là kết quả trước lần cập nhật lexicon gần nhất. Fingerprint của index test20k đang lưu không khớp fingerprint code/lexicon hiện tại, vì vậy index đó không dùng làm baseline so sánh đáng tin cậy.
- `data_final/test.jsonl` không có trong workspace. Tập corpus BM25 test có sẵn là `data_final/chunks_format_v3_r3_reserve_test20k/`, kèm query chính thức ở `newcorpus/query.parquet`. Không dùng `for_valid/`.

## 3. Phạm vi

### Trong phạm vi

- Điều chỉnh trích xuất literal ở `sbtc/Scripts/Retrieval/analyzers.py`.
- Điều chỉnh phát literal của query channel nếu cần để token truy vấn và token index dùng cùng quy tắc; giới hạn trong `query.py`.
- Thêm hoặc cập nhật kiểm tra analyzer ở `tests/test_core.py`, `tests/test_analyzer_fixture.py` và fixture cân bằng hiện có.
- Tạo config và artifact dẫn xuất mới cho hai lần dựng test index: baseline và candidate.
- Chạy retrieval trên 1.200 query trong `newcorpus/query.parquet`, so sánh candidate và lấy mẫu rà soát kết quả.
- Ghi thay đổi thuật toán, đánh đổi và kết quả vào `docs_AI.md` và `thaydoicongnghe.md` sau khi triển khai.

### Ngoài phạm vi

- Không sửa, xóa hoặc ghi đè chunk/corpus gốc, `concepts.json`, resource nguồn hay index test20k đã có.
- Không nạp thêm từ điển, không thêm dependency, không đổi Underthesea/Jieba/Krovetz/OpenCC.
- Không đổi BM25 weights, `k1`, `b`, RRF, budget candidate, query translation, reranking, chunking hay định dạng nộp bài.
- Không dựng full corpus 1.220.598 URL trong task này.
- Không dùng `for_valid/` làm từ điển, tuning set, query set hay qrels.

## 4. Hợp đồng hành vi

### 4.1. Literal y khoa có chữ Hán liền kề

Trích xuất literal sau khi giải mã HTML entity và chuẩn hóa Unicode NFKC. Ranh giới trái/phải phải phân biệt chữ Latin/số với chữ Hán theo Unicode, không phụ thuộc `\b` ASCII/Python giữa hai nhóm ký tự.

Các trường hợp bắt buộc có cùng kết quả ở analyzer `index_mode=True` và `index_mode=False`:

| Đầu vào | Literal tối thiểu trong `exact` |
|---|---|
| `诊断编码J18.9；` | `j18.9` |
| `给予阿莫西林500 mg。` | `500mg` |
| `糖尿病患者服用metformin` | literal `metformin`; anchor vẫn do lexicon quyết định |
| `检查IL-6及SpO2` | `il-6`, `il6`, `spo2` |
| `血糖5.17 mmol/L` | `5.17mmol/l` |
| `剂量10 μg/kg` | `10mcg/kg` |
| `２型糖尿病，剂量５００ｍｇ` | literal sau NFKC tương ứng `2型` và `500mg` nếu pattern hiện có nhận diện loại literal đó |

Yêu cầu chi tiết:

- Không mất chữ số đầu của số thập phân; không tạo `17mmol/l` từ `5.17 mmol/L`.
- Không bắt buộc khoảng trắng giữa literal và Han; dấu câu CJK hai bên không làm rớt literal.
- Đơn vị phải nằm trong danh sách đơn vị hiện hỗ trợ; không biến mọi chuỗi số thành liều thuốc.
- Cho phép dấu phẩy phân cách danh sách ngay trước liều; không được bắt đầu giữa số thập phân có dấu chấm hoặc dấu phẩy.
- Chuẩn hóa `μg`/`µg` về dạng `mcg` trong literal liều, giữ nguyên giá trị số. Không chuyển đổi đơn vị hay tính toán liều.
- Mã có cấu trúc như ICD, biomarker có số và ký hiệu gạch nối được giữ thành token nguyên khối; có thể bổ sung biến thể bỏ dấu nối nếu hợp đồng hiện có yêu cầu.
- Analyzer chỉ tạo field tìm kiếm; không chỉnh `chunk_text`, text nguồn hoặc văn bản xuất bài.
- Trường `anchors` không được suy ra từ regex literal. Anchor vẫn chỉ do lexicon hiện hành trả về.

### 4.2. Giảm acronym giả tiếng Anh

Mục tiêu hẹp là bỏ case-marker do viết hoa ở tiêu đề/cấu trúc bài báo; không xóa các từ đó khỏi `contents`/`broad` và không thay đổi văn bản nguồn.

- Các từ viết hoa toàn bộ thuộc nhóm tiêu đề/cấu trúc phổ biến như `ABSTRACT`, `BACKGROUND`, `OBJECTIVE`, `METHODS`, `MATERIALS`, `RESULTS`, `CONCLUSIONS`, `DESIGN`, `SETTING`, `PARTICIPANTS`, `INTERVENTION`, `OUTCOME`, `PRIMARY`, `SECONDARY`, `CASE`, `FIGURE`, `TABLE` không được tạo `case_upper_*` trong `exact`.
- Token chữ thường tương ứng vẫn có thể tồn tại trong `contents`/`broad`; quy tắc chỉ loại bỏ cách diễn giải “viết hoa nên là acronym y khoa”.
- Tiếp tục giữ các literal có số/ký hiệu như `HbA1c`, `IL-6`, `BRCA1`, `HLA-B*15:02` và liều lượng.
- Tiếp tục giữ các acronym y khoa đã được hợp đồng hiện tại kiểm tra, gồm `ALL`, `MI`, `CAP`, `COPD` và các alias y khoa có căn cứ trong lexicon. Không tạo anchor chỉ từ chữ viết hoa; kiểm tra âm tính hiện có cho `MI` phải còn đạt.
- Các acronym ngoài danh sách tiêu đề không được tự động gán concept mới. Phần này không thêm ontology hay đoán nghĩa viết tắt.
- Quy tắc loại heading phải dùng chính sách tách biệt, dễ kiểm tra; không thêm stopword vào analyzer tiếng Anh nói chung và không đổi stemming.
- Nếu query projector tạo kênh literal quốc tế cho cả ba ngôn ngữ, marker acronym tiếng Anh bị loại vẫn không được phát tán thành exact boost cho các nhánh VI/ZH. Literal mã/liều dùng chung vẫn được chiếu như hiện tại.

### 4.3. Tính nhất quán index/query

- `contents`, `exact` và `anchors` phải nhất quán giữa hai mode với cùng text và language.
- Các literal quốc tế dùng ở query phải khớp được literal đã lưu ở index sau cùng quy tắc chuẩn hóa.
- Thay đổi này không được làm thay đổi thứ tự/ký tự của `chunk_text` lấy từ `TextStore`.

## 5. Thiết kế kiểm thử

### 5.1. Kiểm tra đơn vị và fixture analyzer

Thêm ca positive và negative độc lập với output hiện tại:

- Positive: mã/liều/biomarker sát chữ Hán, có hoặc không có dấu câu; full-width; μg/µg; số thập phân; acronym y khoa được bảo vệ.
- Negative: không có literal thập phân bị cắt; không có `case_upper_methods/results/setting/outcome/case` trong `exact`; không có anchor bị sinh thêm từ acronym hoặc literal.
- Parity: chạy cùng expectation cho index và query mode.
- Regression: giữ các test đang có cho `J18.9`, `10 μg`, `10 µg`, `ALL`, `MI` và nguyên tắc không ground acronym mơ hồ.
- Cập nhật case heading hiện có theo hợp đồng mới; không tạo expectation bằng cách chụp output analyzer sau sửa.

Lệnh tập trung:

```bash
PY=sbtc/Scripts/Retrieval/.runtime/venv/bin/python
$PY -m unittest sbtc.Scripts.Retrieval.tests.test_core sbtc.Scripts.Retrieval.tests.test_analyzer_fixture -v
$PY -m sbtc.Scripts.Retrieval.tests.analyze_fixture --json-report artifacts/retrieval/analyzer-fix-eval-20261015/fixture-report.json
$PY -m sbtc.Scripts.Retrieval.tests.analyze_fixture --strict
```

### 5.2. So sánh retrieval có kiểm soát

Index cũ không khớp fingerprint hiện tại. Để tách ảnh hưởng của hai sửa đổi khỏi thay đổi lexicon, tạo hai snapshot dẫn xuất mới, cùng một input và cấu hình:

1. **Baseline:** code analyzer hiện tại + `concepts.json` hiện tại, dựng trước khi sửa.
2. **Candidate:** code sau sửa + cùng `concepts.json`, dựng sau khi sửa.

Dùng run directory riêng, ví dụ:

- `artifacts/retrieval/analyzer-fix-eval-20261015/baseline/`
- `artifacts/retrieval/analyzer-fix-eval-20261015/candidate/`

Không tái sử dụng index stale và không ghi vào `recall-first-test20k-release/`. Hai lượt phải dùng đúng cùng:

- `data_final/chunks_format_v3_r3_reserve_test20k/` và cùng hash shard;
- `artifacts/retrieval/test20k-scope.jsonl`;
- `newcorpus/links_corpus_vi_en_zh.parquet`;
- `newcorpus/query.parquet`;
- BM25 parameters, per-language budgets, max docs/chunks, translation cache (nếu có; mặc định không dùng cache dịch để giữ cùng điều kiện).

Trên từng snapshot:

- chạy `preflight`, `prepare`, `build`, xác minh manifest fingerprint và đủ sáu index;
- chạy đủ 1.200 query chính thức từ `newcorpus/query.parquet`;
- ghi số ứng viên theo ngôn ngữ/kênh, query rỗng, cảnh báo, tỷ lệ chạm budget, thời gian p50/p95 và lượng ứng viên thay đổi so với baseline;
- audit thủ công một mẫu phân tầng các query/kết quả bị thay đổi, tập trung vào query/chunk có literal y khoa và acronym.

### 5.3. Giới hạn diễn giải retrieval

Repo không có qrels độc lập được phép dùng cho task này; `for_valid/` bị loại khỏi quy trình. Vì vậy:

- Không báo Precision, Recall, F2 hoặc tuyên bố “Recall tăng” từ số lượng candidate, overlap thứ hạng hay audit nhỏ.
- Báo riêng **độ phủ kỹ thuật/candidate generation**: số query có kết quả, số docs/chunks ứng viên, phân bố ngôn ngữ, budget-hit, latency và thay đổi top kết quả.
- Ghi ví dụ cải thiện/hồi quy từ audit thủ công, nêu rõ cỡ mẫu và không coi đây là điểm relevance tổng quát.
- Chỉ tính metric relevance nếu người dùng cung cấp hoặc chỉ định bộ nhãn độc lập hợp lệ, không phải `for_valid/`.

## 6. Kế hoạch thực hiện sau khi duyệt

1. Ghi hash input/config/lexicon; dựng baseline hiện hành vào run directory mới và chạy 1.200 query để chụp kết quả so sánh.
2. Bổ sung test fail-first cho literal CJK boundary, decimal integrity, heading false positives, acronym preservation và parity.
3. Sửa extractor literal Unicode-aware, sau đó sửa chính sách case-marker tiếng Anh; không đổi BM25 scoring hay nguồn lexicon.
4. Chạy unit + fair fixture; xử lý mismatch theo nguyên nhân, không nới expectation để đạt xanh.
5. Dựng candidate snapshot mới; xác minh counts, ID/URL scope, text hydration/hash và source immutability.
6. Chạy cùng 1.200 query/cấu hình lên candidate; so sánh thống kê và audit mẫu output với baseline.
7. Ghi report kết quả; cập nhật `docs_AI.md`, `thaydoicongnghe.md` và checklist Retrieval. Không chạy full corpus.

## 7. Tiêu chí nghiệm thu

- Tất cả ca contract mới về CJK-adjacent literals, decimal, heading false positives và acronym preservation đạt ở cả query/index mode.
- Không có literal đầu vào mục tiêu nào bị cắt/hỏng; không sinh marker `case_upper_*` cho heading đã liệt kê.
- Không đổi chunk text, IDs, doc mapping, source hash hoặc format submission.
- Baseline và candidate đều được dựng từ cùng snapshot nguồn và có manifest/hash đầy đủ; candidate fingerprint phản ánh code sau sửa và lexicon hiện hành.
- 1.200 query được xử lý ở cả hai lượt; kết quả so sánh có số liệu và audit thủ công, nêu rõ không có qrels nên không báo F2/Recall relevance.
- Lệnh test hiện có trong Retrieval đạt; mọi lỗi môi trường hoặc dữ liệu được ghi rõ, không bỏ qua.
- Chỉ dùng test20k; không đọc `for_valid/`; không ghi đè corpus/chunk/index cũ.

## 8. Rủi ro và đánh đổi

| Quyết định | Lợi ích | Đánh đổi / rủi ro | Giảm thiểu |
|---|---|---|---|
| Unicode-aware boundary thay `\b` cho literal | Không bỏ mã/liều sát chữ Hán; giữ được decimal đầy đủ | Regex quá rộng có thể lấy chuỗi Latin/ngày tháng không phải y khoa | Chỉ nhận các grammar mã và đơn vị hiện hỗ trợ; test negative |
| Loại heading khỏi case-marker | Giảm exact boost cho metadata bài báo không phải acronym bệnh | Một từ trùng acronym hợp lệ nhưng nằm trong danh sách heading sẽ mất marker riêng | Giữ lexical lowercase; giới hạn danh sách vào section words phổ biến; không đổi anchors |
| Dựng fresh baseline và candidate | Tách tác động code khỏi lexicon mới; kết quả tái lập được | Tốn thời gian/dung lượng staging và hai bộ index test20k | Run directory mới, chỉ test20k, preflight dung lượng trước |
| Retrieval không có qrels độc lập | Tránh dùng nhãn lệch hoặc tuyên bố quá mức | Không chứng minh được cải thiện Recall/F2 cuối | Báo coverage kỹ thuật + audit mẫu; bổ sung đánh giá relevance khi có bộ nhãn hợp lệ |

## 9. Ranh giới thay đổi

- **Luôn làm:** giữ source verbatim; fingerprint từng run; dùng artifact dẫn xuất riêng; ghi lại mọi thay đổi thuật toán và lỗi thực tế.
- **Cần duyệt riêng nếu phát sinh:** thêm dependency, nạp/sửa lexicon, đổi BM25 weights/budget, thay format field/schema hoặc mở rộng từ test20k sang full.
- **Không làm:** sửa/xóa dữ liệu crawl/chunk gốc; dùng `for_valid/`; dùng số candidate như bằng chứng trực tiếp của Recall/F2.

## 10. Câu hỏi mở

- Không có câu hỏi kỹ thuật chặn việc triển khai trong phạm vi trên. Cần người dùng duyệt đặc tả trước khi capture baseline, sửa code hoặc dựng index.
- Nếu yêu cầu bắt buộc có điểm Precision/Recall/F2 retrieval, cần chỉ định một bộ relevance labels độc lập được phép dùng; nếu chưa có, report sẽ giới hạn ở các số liệu tại mục 5.3.
