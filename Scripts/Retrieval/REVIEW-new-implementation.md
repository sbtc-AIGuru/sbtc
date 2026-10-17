# Rà soát BM25 mới — 15/10/2026

Phạm vi chỉ module mới; không đọc/diff BM25 archive. Skill `code-review-and-quality` dùng để kiểm correctness, readability, architecture, boundary và performance. Không merge/push.

## Các điểm đã sửa và có kiểm tra

- Runtime Java thu gọn thiếu vector module: dùng full JDK21; actual JVM heap đo được 2 GiB. Sparse path dùng API `SimpleSearcher` và fatjar `IndexCollection`, tránh wrapper kéo remote catalogue/neural dependencies.
- Width/Traditional normalization và dictionary ZH dùng cùng OpenCC; source chunk không bị thay đổi. Test `高血壓` khớp neo như `高血压`.
- VI shingles không bắc qua ranh giới câu đơn giản. Clinical abbreviation/decimal phức tạp có thể khiến boundary conservative; field syllable/compound/exact vẫn giữ cơ hội.
- Whole-atom source intervals có overlap được kiểm text bằng char offsets; document body union loại duplication do stride. Tests có nested overlap và conflict.
- ID bool/float/string không được biến thành source integer tùy tiện. Corpus ID/URL là whitelist join; actual source/hash/order roundtrip có test ba ngôn ngữ.
- Resume chuẩn bị có source/analyzer/resource hashes và transaction từng shard; build publish có marker spec hash/count để phục hồi crash trước mark manifest. Completed index không append/overwrite.
- Search TermQuery tránh query-string syntax; field budget 128 clauses chia đều và warning nếu vượt. Không cộng raw score ba language partitions.
- Cache dịch phải đúng source SHA, immutable model revision, eligibility declarations; số bị mất làm loại translation và warning. Đây là guard cấu trúc, không proof dịch y khoa.
- Export chỉ hydrate source nguyên văn; expected query IDs phải khớp; ZIP một JSON ở root. Evaluator test LCS subsequence/40%, doc scope, many-to-many và macro F2.

## Hạn chế ảnh hưởng triển khai full

| Mức | Vấn đề | Xử lý hiện tại |
|---|---|---|
| Đã chốt | Người dùng chọn whitelist active 1.220.598 ngày 15/10/2026; vẫn khác asked.md 1.194.469 | Dùng cho BM25 full/export; giữ 1.320 IDs test20k ngoài bản cũ. Không coi là BTC xác nhận đổi luật |
| Gate | Lexicon chỉ 12 local seed concepts, không phải MeSH/UMLS/ICD | Cần nguồn/license/semantic review trước nạp resource production |
| Gate | Chưa inference translator thật; cache có thể thiếu EN/ZH | Warning rõ; adapter local có code/contract tests, không gọi đã chứng minh medical translation |
| Gate | Chưa có nhãn relevance độc lập được phép dùng | Chỉ báo integrity/throughput/candidate counts; không bịa Recall/F2 |
| Gate | Full capacity/RAM phụ thuộc số tokens/languages | Đo sample bytes rồi dự phóng; không mặc định 20GB raw nghĩa index đủ disk |
| Còn giới hạn | Classical plurals/UK-US/Greek alias tables chỉ một phần; không đầy đủ LVG/NegEx/drug prefixes | Có exact/broad rescue; không bật các rewrite rộng thiếu validation |
| Còn giới hạn | Một số seed labels là khái niệm coarse/fine; acronym alias matching không disambiguation theo ngữ cảnh | Evidence mềm, không hard filter; ontology/ambiguity review thuộc T11 |
| Còn giới hạn | Prepare hiện xử lý shard tuần tự, Underthesea được gọi cho child và document union | RAM bounded; cần profiling/worker-stage implementation riêng nếu throughput full chưa đủ |
| Còn giới hạn | Search metadata point-lookups theo selected chunks, tối đa 3000/query | Không quét corpus; cần đo SSD/full index trước tối ưu batch SQL/hydration |
| Còn giới hạn | Batch benchmark lặp 12 query | Chứng minh pipeline batch, không đại diện độ đa dạng 1200 query thực hoặc hiệu năng cold translation |

Không thay threshold/bỏ assertion để đạt tests. Chưa chứng nhận production/relevance. Checklist kỹ thuật được chứng minh bằng logs/tests và artifacts riêng; nguồn crawl/chunks không ghi đè.

## Phát hiện thêm từ benchmark lớn hơn

PyJNIus concurrent method binding gây wrong-index hits; 180-call repro trước fix có 25 lượt sai granularity/74 rank mismatches, sau global JVM-call lock có 0/0. Source chính thức descriptor `__get__` cập nhật shared receiver: [PyJNIus source](https://raw.githubusercontent.com/kivy/pyjnius/master/jnius/jnius_export_class.pxi). Đã thêm regression actual parallel/serial parity, không che bằng sửa ID. Tradeoff serialized Java calls trong một process; đã sửa mô tả concurrency.

30 tests đạt (13,785s). Integrity 62.941 chunks source SHA/FK/order/text hash đạt. Six index counts khớp. Full disk gate chưa đạt (~81,8GB required free/~22,7GB available); chưa suy production ready từ kết quả này.
