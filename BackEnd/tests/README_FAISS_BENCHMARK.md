# Benchmark độ chính xác FAISS IVF-PQ

Lấy ngẫu nhiên **50 chunk** trong `test_merged.json`, seed 42, dùng embedding
GTE đã tái tạo trên GPU và so kết quả `index.faiss` với `IndexFlatIP` trên toàn
bộ 99.180 vector chưa nén. Không retrain, insert hoặc ghi đè index nguồn.

Chạy trong venv project:

```bash
source .venv/bin/activate
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 python BackEnd/tests/benchmark_faiss.py \
  --queries 50 --output BackEnd/tests/benchmark_runs/accuracy_50_repeat
python -m pytest -q tests/test_faiss_benchmark.py
```

Thư mục `--output` phải chưa tồn tại. Cache tại
`BackEnd/tests/benchmark_cache/gte/corpus.npy` đã được tạo bằng
`Alibaba-NLP/gte-multilingual-base`, 768 chiều, L2-normalized, FP16 autocast
trên RTX 4050 trong `.venv`. Revision, phiên bản thư viện và checksum lưu cùng
cache. Benchmark chỉ đọc cache; FAISS hiện tại là bản CPU.

- **Recall@k**: trung bình tỉ lệ ID top-k exact xuất hiện trong top-k IVF-PQ.
- **Self-hit@1/10**: tìm lại chính chunk làm query ở top-1/top-10.
- **Neighbor Recall@10**: loại chính chunk query khỏi cả hai bên, so 10 hàng xóm.
- Quét nprobe từ 1 tới 4096 để xem mất recall do bỏ cụm hay do PQ.

Output: `report.md`, `report.json`, `results.csv`, `sampled_queries.json`.
Các file cache/kết quả được ignore khỏi Git.

Đây là query nằm trong corpus, không phải tập query độc lập có nhãn relevance.
Exact reference dùng embedding GTE **tái tạo**, vì không có vector insert gốc.
Nội dung trùng hoặc score bằng nhau có thể khiến ID top-k khác nhau.

## Benchmark IVFPQ với query tiếng Việt, nprobe cao và RAM

`benchmark_ivfpq.py` dùng lại 50 câu hỏi trong `hnsw_queries_50.json`, các
helper embedding/latency/RAM đã có và raw HNSWFlat làm exact reference.
Metadata tham chiếu phải khớp byte với metadata của index cần đo. Script
kiểm tra toàn bộ ID trong inverted lists, đo RAM ở subprocess riêng, tạo
embedding trên GPU và chỉ thay `nprobe` trong RAM. Không ghi lại index nguồn.

Chạy GPU ngoài sandbox, trong Conda `DL_Env`:

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate DL_Env
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false \
python BackEnd/tests/benchmark_ivfpq.py \
  --index 'tests/index _1.faiss' --metadata 'tests/metadata _1.json' \
  --nprobes 16 64 128 256 512 1024 2048 4096 \
  --end-to-end-nprobe 512 --threads 4 --repeats 20 \
  --output BackEnd/tests/benchmark_runs/ivfpq_50_repeat
python -m pytest -q tests/test_benchmark_ivfpq.py tests/test_benchmark_hnsw.py
```

Tên hai file tải về có dấu cách trước `_1`. Thư mục output phải mới. Script
xuất JSON/CSV, query vectors và RAM probe; báo cáo Markdown diễn giải kết quả
lần chạy ngày 2026-10-12 nằm trong `benchmark_runs/ivfpq_50_nprobe_20261012/report.md`.
Quét `nprobe=nlist` vẫn xếp hạng bằng PQ, không phải exact vector chưa nén.

Để benchmark chỉ bằng câu hỏi, thêm `--questions-only`. Chế độ này không đọc
reference index/metadata hoặc encode lại source chunk; đo source-document
Hit@1/5/10/20/50, MRR, source-chunk hit, tốc độ và RAM. Source document là tài
liệu dùng để viết câu hỏi, không phải tập nhãn đầy đủ cho mọi đáp án hợp lệ.
Tập 50 câu thứ hai nằm trong `ivfpq_queries_50_set2.json`, seed 43, không trùng
câu hoặc source document với tập seed 42. Chạy cùng command trên với:

```text
--questions-only --queries BackEnd/tests/ivfpq_queries_50_set2.json
```

Setter dùng `ParameterSpace`, đọc lại `extract_index_ivf(index).nprobe` và ghi
code scan count từ `indexIVF_stats` cho mỗi nprobe. Mức nprobe=nlist phải quét
đủ `query_count * ntotal` code, nếu không driver báo lỗi.
