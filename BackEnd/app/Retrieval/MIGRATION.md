# Chuyển BM25 vào BackEnd — 17/10/2026

Toàn bộ component `Scripts/Retrieval/` được chuyển sang `BackEnd/app/Retrieval/`, cạnh `Database/`. Giữ tên `Retrieval` vì component còn bao gồm analyzer, candidate fusion, translation và taxonomy.

## Đường dẫn và lệnh chạy

| Trước | Sau |
|---|---|
| `Scripts/Retrieval/` | `BackEnd/app/Retrieval/` |
| `sbtc.Scripts.Retrieval.*` | `BackEnd.app.Retrieval.*` |
| `Scripts/Retrieval/configs/` | `BackEnd/app/Retrieval/configs/` |
| `Scripts/Retrieval/resources/` | `BackEnd/app/Retrieval/resources/` |

Chạy từ root repository, sử dụng môi trường Python dự án:

```bash
.venv/bin/python -m BackEnd.app.Retrieval.cli --help
.venv/bin/python -m BackEnd.app.Retrieval.taxonomy.cli --help
.venv/bin/python -m unittest discover -s BackEnd/app/Retrieval/tests -v
```

Code và subprocess nội bộ đã dùng import mới. Script/notebook bên ngoài repository phải cập nhật import, đường dẫn config và đường dẫn runtime cũ theo bảng trên. Không có lớp chuyển tiếp ở đường dẫn cũ.

Các đường dẫn dữ liệu trong config tiếp tục được tính từ cwd. Với workspace có dữ liệu ở thư mục cha repository, ví dụ chạy từ workspace đó:

```bash
REPO=/absolute/path/to/sbtc
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}" "$REPO/.venv/bin/python" \
  -m BackEnd.app.Retrieval.cli search \
  --config "$REPO/BackEnd/app/Retrieval/configs/test.toml" \
  --queries newcorpus/query.parquet --output artifacts/retrieval/candidates-new.jsonl
```

## Phạm vi bảo toàn

- Giữ nguyên nội dung từ điển, fixture, config, dependency lock, manifest và dữ liệu curation; các trường provenance trong manifest tiếp tục ghi vị trí ở thời điểm tạo.
- Giữ nguyên mã analyzer, lexicon, models và cách tính analysis fingerprint. Việc đổi thư mục không tự làm đổi fingerprint; cần cùng phiên bản dependency và cùng từ điển khi mở index cũ.
- Không thay BM25 scoring, API hàm/lớp, schema, định dạng output hoặc cách resolve đường dẫn dữ liệu. Không build lại index hoặc chạy model.
- Đưa config và tài nguyên runtime vào package data của setuptools để wheel chứa từ điển/config sau khi chuyển.
- Các báo cáo, SPEC và task lịch sử được giữ nguyên; lệnh và đường dẫn cũ trong chúng phản ánh thời điểm thực hiện. Dùng README hiện tại cho lệnh chạy mới.

Các script curation xác định workspace từ vị trí repository và đọc từ điển cạnh mã nguồn. Chúng vẫn là công cụ offline có thể ghi artifact khi được gọi; việc import BackEnd/Retrieval thông thường không tự chạy curation.

Taxonomy có fingerprint riêng chứa checksum toàn bộ code taxonomy. Việc sửa đường dẫn subprocess trong `taxonomy/cli.py` làm đổi fingerprint này; build taxonomy đã có có thể từ chối resume và yêu cầu run-dir mới. Không sửa manifest cũ hoặc bỏ qua kiểm tra đó. Điều này độc lập với analysis fingerprint dùng để search index BM25.

## Kiểm tra trên môi trường hiện tại

- Đối chiếu trước/sau: đủ 136 file gốc; từ điển, fixture, config, lock và code quyết định BM25 analysis fingerprint giữ nguyên byte.
- Kiểm tra cú pháp toàn bộ Python của component đạt; không còn import thực thi dùng `sbtc.Scripts.Retrieval`.
- Build wheel trong thư mục tạm đạt; 13 file config/resource/requirements được đối chiếu byte, CLI BM25 và taxonomy gọi được từ cwd ngoài repository với mã nguồn trong wheel.
- Suite Retrieval trước và sau đều chạy 68 tests, cùng 3 failures và 28 errors, không có test lỗi mới. Môi trường `.venv` thiếu dependencies BM25/OpenCC và JDK; chưa xác nhận indexing/search/analyzer với runtime đầy đủ.
- Bộ test taxonomy không cần dependencies còn thiếu: 27 tests đạt. Regression Database chạy bằng SQLite: 32 tests đạt, 2 skipped do thiếu dataset/server PostgreSQL; không kiểm thử PostgreSQL thật.
- Không cài package, đổi môi trường, chạy GPU/model, tạo index hay sửa corpus/artifact đang có.

## Loại bỏ dependency còn sót vào Archive

`Scripts/build_expanded_base_resources.py` trước đây còn import năm nhóm concepts từ `Archive/bm25_retrieval_v4/Retrieval/lexicon_data.py`. Dữ liệu đang dùng đã được tách sang `BackEnd/app/Retrieval/lexicon_data.py`, giữ nguyên byte và đầy đủ 224 concepts; script dùng import mới và hỗ trợ nạp trực tiếp từ cwd ngoài repository. Đường dẫn input/output của builder vẫn giữ nguyên.

Đây là dữ liệu phục vụ builder offline, không tự nạp vào `Lexicon`/analyzer hiện tại. Không chạy builder để khai phá corpus hoặc ghi lại tài nguyên.

Kiểm tra bổ sung:

- `tests/test_resource_builder_imports.py`: 2 tests đạt, kiểm tra nạp script và import module trong bản sao dự án không có thư mục Archive, từ cwd ngoài repository; không gọi `main()` hoặc ghi artifact.
- Wheel chứa `lexicon_data.py` nguyên byte; builder nạp đủ 224 concepts từ wheel khi không có Archive. Hai CLI BM25/taxonomy vẫn gọi được từ wheel.
- Rà soát Python, shell, notebook và config đang dùng không còn đường dẫn `Archive/`, `bm25_retrieval_v4`, import `Retrieval.*` hoặc đường dẫn/import `Scripts/Retrieval` cũ. Những lần nhắc trong báo cáo lịch sử và provenance không phải dependency thực thi.
- 38 file dữ liệu/runtime được bảo vệ tiếp tục giữ nguyên checksum, gồm code quyết định analysis fingerprint BM25.

Mã đang dùng trong repository hiện độc lập với Archive. Bản lịch sử trong Archive vẫn được giữ nguyên; chưa xoá thư mục đó trong lần sửa dependency này.
