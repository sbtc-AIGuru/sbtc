# BGE-M3 Training Data

Pipeline tạo dữ liệu retrieval từ `data/merged.json`, giữ nguyên file gốc.
Đầu ra dùng được với FlagEmbedding: một JSON object mỗi dòng, gồm `query`,
`pos`, `neg`, `pos_scores`, `neg_scores`. Các passage là nguyên văn chunk đã chọn.

## Các bước

1. Quét JSON theo luồng và tính SHA-256 của toàn bộ nguồn.
2. Lấy mẫu theo ngôn ngữ/nguồn, lọc heading ngắn, quảng bá và preview thiếu nội dung.
3. Gom document theo hash, canonical URL, đoạn trùng và tiêu đề chuẩn hóa giống nhau.
   Chia nhóm vào train/validation/test; nhóm liên quan 100 câu hỏi benchmark hiện có
   được dành cho test. Đây là grouping thận trọng, chưa phải tìm mọi near-duplicate
   bằng ngữ nghĩa trên toàn bộ 3,47 triệu document.
4. Qwen sinh câu hỏi tiếng Việt/Trung và evidence nguyên văn. Một lượt kiểm tra
   riêng xác nhận câu hỏi/đáp án được passage hỗ trợ. Giữ tối đa tám positive có
   cùng evidence, gồm anchor và các đoạn overlap.
5. Tokenizer BGE đo độ dài thật. Đoạn quá giới hạn bị loại khỏi mining/export;
   không cắt ngầm. BGE-M3 tạo dense embeddings CLS chuẩn hóa, lưu `float32`.
6. Kết hợp dense retrieval và SQLite FTS5 BM25 trên subword BGE. Reranker chấm
   positives/candidate negatives; lọc theo độ tin cậy và score margin.
7. Qwen kiểm tra negatives một lần nữa. Chỉ nhãn `unanswerable` được dùng; nhãn
   `answerable`/`uncertain` bị loại. Không dùng nhóm duplicate/overlap làm negative;
   negatives của train chỉ lấy từ passage thuộc train.
8. Xuất triplets, provenance, silver qrels, baseline trên corpus thử nghiệm,
   CSV để người kiểm tra và ZIP. Nếu các bước chưa hoàn tất hoặc số lượng thấp
   hơn ngưỡng, báo lỗi và vẫn giữ toàn bộ checkpoints/output đã tạo.

## Chạy tại máy

Mọi lệnh Python tại máy dùng Conda `DL_Env`:

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate DL_Env
python -m Scripts.BGE_M3_Data.pipeline prepare \
  --input data/merged.json --work data/bge_m3_20261014_v1
```

Chạy toàn bộ khi CUDA hoạt động:

```bash
python -m Scripts.BGE_M3_Data.pipeline all \
  --input data/merged.json --work data/bge_m3_gpu_run
```

`config.json` cố định revision của Qwen, BGE-M3 và reranker. Mặc định chọn khoảng
6.000 passages để sinh tối đa 12.000 queries, với 60% passages tiếng Việt và
40% tiếng Trung. Trong passages tiếng Trung, 75% tasks yêu cầu câu hỏi tiếng Việt.
Đây là cấu hình ban đầu; số lượng thực tế phụ thuộc các kiểm tra chất lượng.

Không có lệnh tự cài thư viện. Các bước GPU cần PyTorch, Transformers, NumPy,
Accelerate, Hugging Face Hub và SQLite có FTS5. Thiếu dependency hoặc CUDA sẽ
dừng với lỗi cụ thể. Chuẩn bị corpus chỉ dùng thư viện chuẩn Python.

## Kaggle

Notebook dùng Python/thư viện có sẵn trong runtime Kaggle, vì Kaggle là máy riêng
không có môi trường Conda `DL_Env` của máy Ubuntu. Không thay đổi môi trường tại máy.
Bundle chỉ chứa code/config và hai bộ câu hỏi benchmark, không chứa credentials,
model weights hoặc bản sao `merged.json`. Dataset nguồn được gắn trực tiếp vào
notebook private, Internet bật, GPU T4 x2.

```bash
python -m Scripts.BGE_M3_Data.kaggle \
  --source data/merged.json \
  --source-sha256 FULL_SOURCE_SHA256 \
  --dataset nhminh107/sbtc-data1 \
  --kernel nhminh107/sbtc-bge-m3-data-20261014-v1 \
  --output data/bge_m3_kaggle_20261014_v1
kaggle kernels push -p data/bge_m3_kaggle_20261014_v1 \
  --accelerator NvidiaTeslaT4 --timeout 39600
kaggle kernels status nhminh107/sbtc-bge-m3-data-20261014-v1
kaggle kernels output nhminh107/sbtc-bge-m3-data-20261014-v1 \
  -p data/bge_m3_kaggle_outputs_20261014_v1
```

Nếu không truyền `--source-sha256`, pipeline vẫn tính/lưu hash đầy đủ nhưng chưa
đối chiếu với bản tại máy. Notebook tự tìm đúng `merged.json` bằng tên và kích thước.
Hai GPU xử lý các shard generation/mining/judging độc lập. Một warmup 12 passages
phải tạo đủ queries có bằng chứng. Một probe riêng trên tối đa khoảng 5.000 chunks
chạy thực tế embedding, mining, reranking, negative judging và export trước khi
chạy generation dài hơn. Triplets của probe không được trộn vào dataset chính.

## Checkpoints Và Đầu Ra

`generation-ledger-*.jsonl`, `queries-*.jsonl`, `mining-ledger-*.jsonl`,
`mined-*.jsonl`, `negative-judgments-*.jsonl` được flush sau mỗi batch/query.
Chạy lại với cùng work/config sẽ bỏ qua những công việc đã ghi journal.
Đổi cấu hình cần dùng thư mục run mới; pipeline từ chối ghi vào thư mục lạ.
Embedding/BM25 cache được dùng lại khi chữ ký corpus và model khớp. Nếu encoding
bị gián đoạn trước khi cache hoàn tất, giữ cache cũ và dùng một run directory mới.

Các file giao cho training nằm trong `dataset/` và `bge_m3_dataset.zip`:

| File | Nội dung |
| --- | --- |
| `train.jsonl` | Triplets train và teacher logits |
| `validation.jsonl`, `test.jsonl` | Triplets giữ lại, không dùng để train |
| `provenance.jsonl` | IDs, groups, evidence spans, quyết định kiểm tra, model revisions |
| `evaluation/corpus.jsonl` | Corpus thử nghiệm có stable chunk IDs |
| `evaluation/queries.jsonl`, `evaluation/qrels.tsv` | Queries và nhãn relevance tự động |
| `human_review.csv` | Mẫu 500 queries để người kiểm tra |
| `report.json`, `manifest.json`, `checksums.json` | Số lượng thực tế, lineage và tính toàn vẹn |

Qrels là **synthetic silver**, chưa được người gán nhãn và chưa bao phủ mọi đáp án
đúng. Baseline chỉ áp dụng cho corpus thử nghiệm được xuất, không đại diện cho
toàn bộ 19 triệu chunks. Lượt kiểm tra bằng cùng Qwen không phải một teacher độc lập.
Token budgets, heuristic ngôn ngữ và quality filters có thể bỏ sót dữ liệu hữu ích;
mọi số đếm loại bỏ đều được lưu trong báo cáo. Pipeline này sinh data, chưa train
embedding model hoặc thay thế index GTE đang dùng trong ứng dụng.

## Kiểm Tra

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate DL_Env
pytest -q tests/test_bge_m3_data.py
python -m compileall -q Scripts/BGE_M3_Data
```
