# SBTC AIGuru

Mã nguồn BackEnd nằm trong `BackEnd/app`:

- `Database/`: lưu trữ PostgreSQL và FAISS.
- `Retrieval/`: BM25 Việt–Anh–Trung, analyzer, taxonomy, cấu hình, từ điển và kiểm thử.

BM25 đã chuyển từ `Scripts/Retrieval` sang `BackEnd/app/Retrieval`. Xem [hướng dẫn chạy](BackEnd/app/Retrieval/README.md) và [ghi chú chuyển thư mục](BackEnd/app/Retrieval/MIGRATION.md).

```bash
.venv/bin/python -m BackEnd.app.Retrieval.cli --help
```

Pipeline Qdrant bốn nhánh → PostgreSQL source text → LLM reranker → JSON/ZIP
nộp bài: [hướng dẫn và cấu hình](BackEnd/app/PIPELINE.md).

```bash
.venv/bin/python -m BackEnd.app.pipeline --help
```

Giao diện upload Parquet, chọn start–end, theo dõi checkpoint và tải `output.zip`:
[hướng dẫn API](BackEnd/app/api/README.md).

```bash
.venv/bin/python -m uvicorn BackEnd.app.api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Mở [http://127.0.0.1:8000](http://127.0.0.1:8000). Frontend nằm trong `FrontEnd`,
được FastAPI phục vụ trực tiếp, không cần npm/build.
