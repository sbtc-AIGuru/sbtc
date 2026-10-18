# SBTC AIGuru

Mã nguồn BackEnd nằm trong `BackEnd/app`:

- `Database/`: lưu trữ PostgreSQL và FAISS.
- `Retrieval/`: BM25 Việt–Anh–Trung, analyzer, taxonomy, cấu hình, từ điển và kiểm thử.

BM25 đã chuyển từ `Scripts/Retrieval` sang `BackEnd/app/Retrieval`. Xem [hướng dẫn chạy](BackEnd/app/Retrieval/README.md) và [ghi chú chuyển thư mục](BackEnd/app/Retrieval/MIGRATION.md).

```bash
.venv/bin/python -m BackEnd.app.Retrieval.cli --help
```
