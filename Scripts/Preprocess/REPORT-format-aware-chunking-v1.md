# Báo cáo triển khai format-aware chunking v1

Khởi động: 13/10/2026. Kiểm chứng cuối: 14/10/2026.
Đặc tả được duyệt: [SPEC-format-aware-chunking.md](SPEC-format-aware-chunking.md).
Kế hoạch/checklist: [plan](tasks/format-aware/plan.md), [todo](tasks/format-aware/todo.md).

## 1. Kết quả và phạm vi nghiệm thu

- Strategy **`format`**, `profile_version=format-v1`, cleaner `verbatim-v4`.
- Toàn bộ **20.000** dòng `data_final/test_20k.jsonl`: **19.900 ok**, **100 skipped** do crawl đã thất bại, **0 runtime errors**.
- **62,465 children**, **27,778 parents**, 20 shards.
- Audit tất cả output: **0 errors** về ID/URL/hash/source slice/order/parent/coverage/rule metadata/protected boundaries.
- **68/68 tests hiện tại đạt**, từ dữ liệu test thật và các mutation metadata/schema/layout có chủ ý.
- Full discovery **chưa xanh**: 3 lớp legacy lỗi `setUpClass` vì `datacrawl/test.jsonl` không tồn tại. Không skip hoặc bỏ assertion. Chi tiết ở mục 7.
- Không chạy chunk trên corpus chính 1,22 triệu dòng. Không đo F2 vì chưa có gold retrieval/queries trong phép so sánh này.

Nguồn duy nhất để thử nghiệm:
[/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl)

SHA-256 không đổi: `9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
37.334.226 ký tự không trắng: 37.148.244 indexed + 185.982 excluded = 100% coverage.
Coverage không chứng minh toàn bộ source crawl đúng hoặc mọi exclusion có chất lượng ngữ nghĩa hoàn hảo.

## 2. Cấu trúc đã triển khai

| Thành phần | Công việc |
|---|---|
| [format_profiles.py](format_profiles.py) | Router bằng evidence, language spans, sentence/structural atoms, protected expressions, exclusions có ledger |
| [format_chunking.py](format_chunking.py) | Pack whole atoms, parent regions, source context, metadata theo giao span, explicit short/oversize/overlap reasons |
| [chunking.py](chunking.py) | Dispatch strategy `format`; bốn strategy cũ vẫn dùng lõi cũ |
| [chunk_cli.py](chunk_cli.py) | Streaming/shards/resume; profile + source/config/code fingerprints; thống kê profiles/languages/warnings |
| [chunk_audit.py](chunk_audit.py) | Tái dựng evidence từ nguồn, reject metadata giả, kiểm source context và fingerprint trước audit |

Mặc định CLI vẫn là `hybrid`. Để dùng phiên bản mới phải chọn **`--strategy format`**.
Không thêm model/dependency, không dịch/tóm tắt/viết lại chunk. Title/question/context ở metadata;
`chunk_text` luôn một source slice liên tục sau cleaner. Không ghép nội dung của URL khác vào doc_id.
ID lấy nguyên `record.id`, bao gồm ID PubMed lớn hơn giới hạn lịch sử 4,42 triệu; không lấy `row_index`.

Các profile:

- Narrative: giữ sentence/inline fragments/heading và câu dẫn liên quan; không dùng 120 chars làm ranh giới title.
- Abstract: nhận nhãn inline và đầu dòng, cả nhóm FINDINGS/INTERPRETATION/FUNDING và nhãn dài có thật trong test; short abstract giữ nguyên.
- QA: context người hỏi bằng span; marker rõ chia answer region; bio marker đôi chuyển sang ledger. Lời người hỏi “你好，医生” không thành answer.
- Catalogue: field headings có cả prefix tên thuốc, label–body, table rows và manufacturer/approval/package records.
- Book/TCM: formula ingredients/doses nguyên record; quoted snippets giữ; chỉ pagination có arrow/keyboard layout bị exclude.
- Structured list: conference O/P entries nguyên record. Không biến title/author thành full abstract không có trong nguồn.
- Generic/unknown: giữ source, confidence thấp và warning.

Metadata `section_spans`/`section_paths` mô tả nhãn tìm được từ source, chưa phải cây HTML/XML đầy đủ.
`source_language` là **domain prior** khi input chưa có bucket/metadata ngôn ngữ chính thức;
`content_language_spans` là heuristic text evidence, tách biệt với prior. `und` không nên làm điều kiện loại tài liệu.

## 3. So sánh với baseline cùng tập test

Ngân sách vẫn 150/220/300/40 **custom units**, parent 1200. CJK character và Latin/numeric expression
được đếm theo hàm sẵn có; đây không phải model tokens và không phải phép tokenize whitespace của BTC.

| Chỉ số | Hybrid v3 baseline | Format v1 |
|---|---:|---:|
| Chunks | 71,203 | 62,465 |
| Parents | 30,929 | 27,778 |
| Mean units | 202.93 | 225.10 |
| <50 units | 3.114 | 2.036 |
| <100 units | 6.707 | 4.460 |
| >300 units | 2 | 24 |
| Scanner số rộng: expression bị cắt | 38 trên 29 docs | 0 |
| Delimiter-end flags | 9.254 | 424 |
| Positive overlap trong cùng parent | 99.78% | 87.30% |
| Overlap 30–50 trong cùng parent | 83.50% | 59.05% |
| Shard bytes | 116.66 MiB | 309.77 MiB |

Scanner số độc lập dùng `digit + ([.,:] + digit)+`, rộng hơn detector trong báo cáo baseline trước
(17 biên/14 docs). **38 là số flags theo định nghĩa mới, không phải 38 lỗi liều lượng đã review thủ công**.
Các case 37,5/(1:1)/$10,100/11,6 đã được xác nhận trực tiếp. Delimiter flags gồm cả semicolon kết item hợp lệ;
không gán toàn bộ flags là “cắt ngu”. Tỷ lệ structural heading không so như semantic accuracy:
metric cũ dùng heuristic heading, bản mới cho phép pack mục nhỏ và có atom_boundary_rate riêng.

Theo profile (profile của bản mới dùng để nhóm cả hai output):

| Profile | Docs | Chunks cũ → mới | <100 units cũ → mới | >300 mới |
|---|---:|---:|---:|---:|
| research_abstract | 4,482 | 6,826 → 6,547 | 1,383 → 1,376 | 3 |
| structured_list | 1 | 10 → 8 | 1 → 0 | 0 |
| narrative_article | 13,014 | 52,998 → 44,509 | 4,611 → 1,669 | 9 |
| disease_drug_catalogue | 307 | 3,094 → 2,335 | 231 → 8 | 0 |
| tcm_book | 240 | 1,066 → 791 | 181 → 30 | 4 |
| generic | 55 | 55 → 55 | 55 → 55 | 0 |
| qa | 1,801 | 7,154 → 8,220 | 245 → 1,322 | 8 |

Runtime bản mới 175.44s, workers=2, parent peak RSS 36.51 MiB.
Baseline cũ 88.58s, workers=1; phép đo không kiểm soát cùng worker/load nên không dùng
để kết luận speedup. RSS không cộng RAM worker. Output mới **2.66×** bytes
vì atom/evidence/context metadata chi tiết. Tập stress/stratified này không đại diện phân bố full corpus.

## 4. Đọc output thật: điểm cải thiện

[CASEBOOK 32 tài liệu có source/output links](research/format-implementation-20261013/evaluation/CASEBOOK.md)
và [review_cases.json](research/format-implementation-20261013/evaluation/review_cases.json) chứa toàn output để kiểm tiếp.

| Case | Kết quả đã kiểm |
|---|---|
| 211401 | `37,5 độ C` nguyên biểu thức và câu |
| 6333519 | `(1:1)` nguyên câu randomisation; tail có FINDINGS/INTERPRETATION/FUNDING đúng source |
| 5714388 / 6480634 | `$10,100` / `11,6` không bị chẻ comma; French/Spanish không kế thừa en cho đoạn dài |
| 7147848 / 283585 / 263670 | ES/CI và ngoặc qua inline anchors/newline nguyên atom |
| 269380 / 223012 / 244904 / 1067218 | Câu dẫn colon và 病情分析/指导意见 không treo trước body |
| 1138672 | Người hỏi chào bác sĩ vẫn nằm trong question context |
| 2335124 | Bio doctor không trộn vào nội dung triệu chứng; answer giữ nguyên |
| 279805 | TOC/menu/title-date template không tạo child chỉ có nhãn; title vẫn có source metadata |
| 2531165 | Hai rows bệnh–triệu chứng–khoa giữ cùng atom, render paragraph lặp có mapping |
| 4050109 | Catalogue drug, field headings có tên thuốc, mỗi manufacturer record riêng |
| 3078554 / 2996442 | Wiki ICD/dense navigation/footer có evidence và exact spans |
| 4265827 / 4271202 | Lật trang tách khỏi nội dung; formula và quoted snippets vẫn còn |
| 7156587 | EN/ZH cùng doc_id, không overlap qua language region |
| 6248072 | O/P conference entries không bị chẻ tác giả; có content_limited |
| 5180531 / 5294437 / 7286850 | Không cắt sau `et al.` / `i.v.` / `vs.` ở giữa câu |
| 6954391 / 218831 / 1128713 | Short abstract 1 chunk; narrative câu đầy đủ; short QA 1 chunk |

Đánh giá câu chữ: component **không sửa câu chữ nguồn**. Các số liệu, phủ định, công thức, thứ tự và ngôn ngữ
trong ca review vẫn nguyên văn. Có cải thiện rõ về ranh giới ở các ca trên; không tuyên bố mọi chunk toàn corpus đã tối ưu.

## 5. Điểm còn yếu và trade-offs

1. **QA nhiều chunk ngắn hơn:** 245 → 1.322 chunks <100 units; tổng 7.154 → 8.220. Marker/responder/language regions
   và exclusions tạo ranh giới cứng. Ví dụ 2335124 có question title đứng riêng trước bio bị exclude.
   Không được nối câu hỏi với reply bằng xóa khoảng source hoặc chèn câu hỏi vào `chunk_text`.
   `question_context` và source question_span giúp index/rerank dùng context; cần gold để chọn eligibility/boost
   cho question-only candidates. Chưa có bằng chứng QA retrieval score tăng.
2. **24 atoms >300 units**, max 2.760, đều có reason; [danh sách](research/format-implementation-20261013/evaluation/oversized_review.json).
   Đây là ngoại lệ thật của nguồn thiếu punctuation/structural record/whole sentence. Không cắt clause cho đủ size.
   Cần kiểm model-token budget sau khi chọn encoder; không mặc định truncate âm thầm.
3. **Overlap giảm:** capacity không đủ whole sentence thì có zero overlap hoặc overlap ngoài 30–50 kèm reason.
   Chưa đánh giá tác động Recall/F2; target overlap không được xem là acceptance tuyệt đối khi trái bảo toàn câu.
4. **Noise chưa hết:** 2531165 còn child 79 units gồm broken `详细>>...` links/UI sau bản render lặp.
   Cleaner có incomplete-link warning, không suy đoán body của link. Chưa thể gọi pipeline “sạch 100%”.
5. **Heuristic format/language:** 13.069 uncertain-format warnings gồm fallback narrative/generic, không đồng nghĩa
   13.069 docs bị chunk sai. Nhãn/heading/hierarchy chỉ là source evidence, chưa calibrated; không dùng làm hard prefilter bệnh/ngôn ngữ.
6. **Ngoặc source vỡ:** 1.716 warning events. ASCII/fullwidth parentheses được hiểu tương thích.
   Pair xuyên paragraph chỉ tin khi <=1200 chars và <=6 line breaks; dài hơn giữ nguyên chữ và flag review,
   không ghép dấu mở bị vỡ qua abstract khác. Đây là heuristic bảo vệ local expression, không phải quy tắc BTC.
7. **Table/layout thiếu:** đã giữ rows có dấu hiệu rõ; không phục dựng cột/HTML tree đã mất. Forum không có mẫu
   thành công trong test nên không nghiệm thu thread/post profile. Không re-crawl URL con trong task này.
8. **Storage tăng:** metadata là audit evidence; exporter cho index compact nên là bước riêng. Không lấy tỷ lệ sample
   này để khẳng định chi phí/storage toàn 1,22 triệu corpus.

## 6. Địa chỉ output cuối và chạy lại

Output cuối được kiểm chứng, không dùng các candidate folders làm final:

- [/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/): `part-000000.jsonl` đến `part-000019.jsonl` + checkpoint.
- [summary-verified.json](research/format-implementation-20261013/summary-verified.json)
- [audit-verified.json](research/format-implementation-20261013/audit-verified.json)
- [comparison.json](research/format-implementation-20261013/evaluation/comparison.json)
- [snapshot code + hashes](research/format-implementation-20261013/code-verified-hashes.json)
- [numeric comparison](research/format-implementation-20261013/evaluation/numeric_boundary_comparison.json)

Chạy từ root AIGuru, **folder output mới**:

```bash
python3 -m sbtc.Scripts.Preprocess.chunk_cli \
  data_final/test_20k.jsonl \
  sbtc/Scripts/Preprocess/runs/format-test-20k \
  --strategy format --workers 2 --progress-every 2000

python3 -m sbtc.Scripts.Preprocess.chunk_audit \
  data_final/test_20k.jsonl \
  sbtc/Scripts/Preprocess/runs/format-test-20k
```

Resume cùng code/input/config thêm `--resume`. Fingerprint thay đổi hoặc folder không rỗng sẽ bị từ chối.
Toàn source, corpus crawl và baseline cũ không bị sửa. Candidate directories giữ để truy lỗi phát triển.

## 7. Lệnh và kết quả kiểm thử

Môi trường đã chạy: **Python 3.14.7** (streaming buffersize theo implementation hiện có).

```bash
python3 -m unittest sbtc.tests.test_chunk_formats sbtc.tests.test_chunk_format_streaming
# 68 tests / OK — tests_verified.log

python3 -m unittest discover -s sbtc/tests -p 'test_chunk_*.py'
# 68 tests executed; 3 setUpClass errors — tests_all_verified.log
```

3 lớp cũ: `ChunkCleaningTests`, `ChunkComponentTests`, `ChunkStreamingTests` tham chiếu
`/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/datacrawl/test.jsonl`. File không tồn tại và các ID cũ không có trong test20k.
Không lấy corpus chính làm fixture thay thế, không bỏ test. Đây là **giới hạn regression legacy chưa xác minh lại**.
Baseline outputs20k vẫn audit bằng auditor hiện tại: 0 errors ([bằng chứng](research/format-implementation-20261013/baseline-audit-current.json)).

New tests: real numeric/sentence/colon/abbreviation/QA/bio/title/TOC/table/formula/lang/sections,
source SHA/slices/IDs/coverage, invalid schema/empty/malformed JSON, workers1/2, overlap0,
custom60-unit oversized, resume/pending/checksum/version/code/source/config hash guards và tampering.
Mutation test đảo guard CJK bị bilingual regression bắt; code đã khôi phục byte-identical trước snapshot.
`git -C sbtc diff --check` đạt trên files sửa trong task; không commit/stage các thay đổi đã có của người dùng.

## 8. Kết luận kiểm chứng

Bản format-v1 đáp ứng các ca source/biên/metadata đã đặc tả và thử trên test20k, có evidence trước–sau.
Cần tiếp tục đánh giá retrieval bằng gold, xử lý noise còn lại theo source evidence và kiểm encoder budget
cho 24 oversized atoms. Không khẳng định full regression legacy hoặc F2 improvement đã hoàn tất.
