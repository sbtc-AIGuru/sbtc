# Kết quả format-aware chunking

Task khởi động13/10/2026, kiểm chứng14/10/2026. Folder giữ cả candidate/debug runs.

**Output cuối: [chunks-verified](chunks-verified/)** — 20 shards, 20.000 records, 19.900 ok/100 skipped,
62,465 chunks. [Audit](audit-verified.json):0errors. [Summary](summary-verified.json).

[Báo cáo đầy đủ](../../REPORT-format-aware-chunking-v1.md) · [32 case trước–sau](evaluation/CASEBOOK.md) ·
[Comparison](evaluation/comparison.json) · [24 oversized atoms](evaluation/oversized_review.json).

68 new/current tests đạt. Full discovery có3legacyfixture errors; xem báo cáo. Input và baseline không đổi.
`code-verified/` + `code-verified-hashes.json` là code của output cuối.
Các run-01/run-02/chunks/chunks-v1/chunks-release và snapshot khác là candidate để debug, không phải output nghiệm thu.

Mỗi JSONL row chứa1document, `children` là array chunk; chọn `children[].chunk_text` để đọc nội dung.
Offsets tính trên source sau cleaner. Excluded ledger giữ exact source text, title/question source spans ở metadata.

Reproduce comparison từ root:

```bash
PYTHONPATH=. python3 sbtc/Scripts/Preprocess/research/format-implementation-20261013/evaluate_outputs.py \
 --output sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified \
 --baseline sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks \
 --report-dir sbtc/Scripts/Preprocess/research/format-implementation-20261013/evaluation
```
