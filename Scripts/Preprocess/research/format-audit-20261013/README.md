# Artifact khảo sát format chunking ngày 2026-10-13

Đọc [báo cáo](../../REPORT-format-chunking-audit-20261013.md),
[đặc tả đề xuất](../../SPEC-format-aware-chunking.md) và [ví dụ thật](CASEBOOK.md).

Input benchmark: `data_final/test_20k.jsonl`, SHA-256
`9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43`.
Input inventory: `data_final/final_data.jsonl` và manifest hiện hành trong
`newcorpus/`; chỉ đọc thống kê, không chunk full corpus.

`baseline_chunks/` có 20 shards, mỗi dòng là một document output; children
là các chunk. `baseline_summary.json` do CLI ghi, `baseline_audit.json` do
auditor hiện hành ghi. Bản này dùng hybrid v3/cleaner verbatim v4.

Các JSON profile/metrics, `test_rows.csv`, `review_cases.json` và
`curated_cases.json` phục vụ kiểm tra số liệu và đường dẫn bằng chứng.
Language proxy/cờ numeric/bracket/nav không phải nhãn ground truth.

Helper phân tích lưu riêng, không thuộc API production:

- `audit_profile.py`: toàn corpus hoặc test, ID/URL/length/domain và script proxy.
- `audit_url_families.py`: URL-family quantiles và PubMed script/section signals.
- `review_baseline.py`: đọc test và output đã lưu, thống kê và lấy cờ rủi ro.
  ROOT trong script đang trỏ đúng thư mục artifact này.

Chạy profiling vào thư mục dẫn xuất mới từ workspace AIGuru, ví dụ:

```bash
sbtc/.venv/bin/python -u \
  sbtc/Scripts/Preprocess/research/format-audit-20261013/audit_profile.py \
  data_final/test_20k.jsonl /tmp/aiguru-format-profile-rerun --sample
sbtc/.venv/bin/python -u \
  sbtc/Scripts/Preprocess/research/format-audit-20261013/audit_url_families.py \
  data_final/final_data.jsonl /tmp/aiguru-format-profile-rerun
```

`code_input_hashes.json`, `input_code_integrity.json` và `code_snapshot/` xác
định code/input dùng cho lần đo. Source files giữ nguyên; report/spec là DRAFT,
chưa có profile mới được tích hợp hoặc kết quả retrieval/F2 được đánh giá.
