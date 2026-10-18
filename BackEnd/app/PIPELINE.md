# Medical retrieval pipeline

Run from the repository root in the existing `.venv`. The module is
`BackEnd/app/pipeline.py`; there was no pipeline implementation in this checkout.

```bash
.venv/bin/python -m BackEnd.app.pipeline /path/to/query_translated.parquet \
  --output artifacts/pipeline/submission.json \
  --zip artifacts/pipeline/submission.zip \
  --batch-size 16 --workers 4 --llm-workers 2
```

Use `--limit 3` and a different output path for a small service smoke test.
Omit `--limit` for the full dataset. `--help` lists all options.

The [local upload API and UI](api/README.md) accept a Parquet file and return
`output.zip`, with persistent jobs, pause/resume, and live batch progress.
`--start`/`--end` (or Python `start`/`end`) select inclusive, 1-based row positions.
Omitted bounds run from the first/to the last row. They preserve original query
IDs; the selected range is part of the checkpoint fingerprint. Python callers can
also pass `progress_callback` and `stop_event` for durable batch progress/pause.

## Services and models

- Configure the existing `QDRANT_URL`, `QDRANT_COLLECTION`, optional
  `QDRANT_API_KEY`, and vector-name environment settings. The default collection
  is `sbtc_gte_multilingual`. It must contain a populated **hybrid** index with
  GTE dense vectors and native `bm25` sparse vectors. A dense-only snapshot cannot
  run the four-branch query. The pipeline does not create or alter indexes.
- Prefer `--manifest /path/to/snapshot_manifest.json` from the restored hybrid
  snapshot. The existing `from_manifest` reads collection, vector names and BM25
  options; the pipeline checks its embedding signature against the pinned model.
- The default encoder loads **cached files only**, with the GTE weights/code
  revisions used by the notebook. It reuses `encode_records` and normalization
  from `Scripts/Qdrant/build_gte_qdrant.py`: normalized CLS vectors, 8192-token
  windows, and content-length-weighted fusion. No input is truncated. The model
  is initialized once; Vietnamese queries are encoded together once per batch.
  CPU is the default; use `--device cuda:0` when desired. PyTorch, Transformers,
  NumPy and psutil are already present in the project environment; no packages
  or model files are installed/downloaded by this pipeline. Missing cached
  weights/code are reported as encoding failures.
- The loader detects a downloaded `artifacts/model-cache` automatically, or uses
  `PIPELINE_MODEL_CACHE` / `--model-cache` when provided. Otherwise the existing
  Hugging Face cache remains the fallback. Both pinned repositories are needed:

  ```bash
  .venv/bin/hf download Alibaba-NLP/gte-multilingual-base \
    config.json model.safetensors tokenizer.json tokenizer_config.json special_tokens_map.json \
    --revision 9bbca17d9273fd0d03d5725c7a4b0f6b45142062 --cache-dir artifacts/model-cache
  .venv/bin/hf download Alibaba-NLP/new-impl configuration.py modeling.py \
    --revision 40ced75c3017eb27626c9d4ea981bde21a2662f4 --cache-dir artifacts/model-cache
  ```

  Downloads are an explicit setup step, not performed on upload. The cache is
  ignored by Git. The loader handles Transformers 5's removal of the legacy
  tokenizer window method while keeping the original BOS/content/EOS sequence,
  restores the pinned model's legacy encoder padding-mask expansion, and pins
  tokenizer configuration code too, without an interactive trust prompt.
  Model-load setup errors stop once and surface an actionable message rather
  than repeating an `OSError` for every query in every batch.
- Set `MODEL_NAME`, `LLM_BASE_URL`, and `LLM_API_KEY` for the existing
  `LLM/llm_as_reranker.py`. Its OpenAI-compatible client is reused across bounded
  concurrent calls. Configure a competition-eligible open model according to
  [asked.md](../../asked.md). No model choice or remote provider is introduced.
- Configure the existing `DATABASE_URL` only when Qdrant lacks `doc_id` or
  `chunk_text`. `PostgreManager.get_submission_chunks(ids)` selects just
  `chunk_id`, `doc_id`, and `chunk_text` in parameterized batches of at most
  1,000 IDs. It returns a keyed mapping with `None` for missing records.
  Complete Qdrant payloads need no SQL lookup. No schema/import operations run.

The existing managers/reranker load environment settings through their existing
dotenv support. Credentials are never written into checkpoints or error reports.

## Input and retrieval

The inspected `query_translated.parquet` has 1,200 rows and columns `id` (int64),
`query`, `english`, `chinese`. A complete streaming audit found 1,200 unique IDs
and no missing/empty query translations. The pipeline reads Parquet record
batches and detects these columns from the schema. Explicit overrides are
available as `--id-column`, `--original-query-column`, `--eng-query-column`, and
`--chinese-query-column`; Python callers can pass the equivalent `columns` dict.
Ambiguous columns/types, duplicate IDs, null IDs, and blank translations fail
explicitly. The untranslated `query.parquet` alone lacks the required EN/ZH
inputs; the pipeline does not translate or substitute Vietnamese text for them.

`QdrantManager.query_original_dense` is the selected implementation: **one dense
Vietnamese query plus BM25 Vietnamese/English/Chinese**, fused by the existing
Qdrant RRF. `query_multilingual_dense` has six branches and is not called.
One fused query retrieves chunk points; distinct payload document IDs in fused
rank order form document candidates. There is no redundant document search or
second fusion implementation. Qdrant point UUIDs are never used as source IDs.

Defaults preserve the existing 50 candidates per branch and 100 fused points.
`--branch-limit` and `--top-k` can increase candidate coverage. The competition
specification gives no fixed per-query document/chunk cap. All candidates are
retained by default; `--max-docs` and `--max-chunks` are optional independent
output budgets, not relevance thresholds. These defaults have not been tuned
against relevance labels; no Recall/F2 improvement is claimed.

The pipeline checks PostgreSQL/Qdrant agreement whenever it hydrates an ID.
Missing records or conflicting identity/text fail the affected query. Document
IDs remain source integer IDs serialized as strings, following the existing
exporter. Chunks are deduplicated by document and the existing BTC text
normalization, keeping the first source occurrence and its unmodified text.
Blank chunk texts are excluded, but their retrieved document IDs remain.

`llm_as_reranker.rerank(query, documents, client=...)` runs after hydration, before
optional output truncation. Its existing strict schema and candidate-multiset
validation reject hallucinated IDs, altered text, missing candidates, and changed
document order. Only chunks are reordered. Empty candidate lists make no LLM
request. Exact source chunk IDs are mapped back from validated `(doc_id, text)`
pairs and retained in the checkpoint for audit; they are not extra submission
fields.

## Submission and recovery

The contract is established by [asked.md](../../asked.md) and the existing
`Retrieval/export.py`, rather than the uppercase conceptual output names:

```json
[
  {
    "id": 1,
    "relevant_docs": ["123"],
    "relevant_chunks": [{"doc_id": "123", "chunk_text": "Exact source text"}]
  }
]
```

`id` is an integer. Both retrieval lists are always present. Ranking is array
order; optional `chunk_order` is omitted. The competition evaluates chunk text,
not our internal chunk IDs. Output contains no medical answer or explanation.
The optional ZIP contains exactly the JSON file at its root. The full submission
must contain all 1,200 competition queries; `--limit` is for local checks only.

Retrieval uses a persistent manager/HTTP session per worker. LLM requests use a
separate pool (default two workers). SQL hydration is once per query batch over
the deduplicated set of missing IDs. Batch barriers and explicit row indices keep
the original query order regardless of worker completion order. Input/candidate
work is bounded by batch size; returned predictions/checkpoint entries are kept
in memory, proportional to the final output size.

With JSON output, two sidecars are used:

- `submission.checkpoint.jsonl`: configuration/input fingerprint and successful
  rows, including their original source chunk IDs. Successful batches are flushed
  and synced. Only a truncated final journal append is discarded on resume.
- `submission.errors.json`: failed row positions, query IDs, stages and exception
  types. Raw service exception text is excluded because it may contain secrets.

Any failed query makes `run_pipeline` raise `PipelineError` (CLI exit 1) **after**
processing independent rows. No final JSON/ZIP is written on a failed run.
Empty retrieval results are valid successful predictions with two empty lists.
The pipeline does not silently fall back to unreranked results on an LLM error.

Repeat the same command with `--resume` to reuse successful rows and retry failures.
Input/configuration changes reject the checkpoint. Set `--resume-tag` to an index
generation identifier when the same collection endpoint can change without a
new manifest; change it for new retrieval data/model configuration. Existing
final JSON/ZIP files are not overwritten: choose a new output for a completed run.
Interrupted rows may be recomputed, but committed rows are not reretrieved.

## Python interface and checks

```python
from BackEnd.app.pipeline import run_pipeline

predictions = run_pipeline(
    "query_translated.parquet", "artifacts/pipeline/submission.json",
    zip_path="artifacts/pipeline/submission.zip", workers=4, llm_workers=2,
)
```

Tests can inject a `dense_encoder(texts)`, `qdrant_factory(encoder)` returning one
owned manager per worker, and caller-owned `postgres_manager` / `llm_client`.
Injected components require a stable `resume_tag` on resume. The module does not
close caller-owned database/LLM clients.

```bash
.venv/bin/python -m pytest -q \
  tests/test_pipeline.py tests/test_postgre_database.py \
  tests/test_llm_reranker.py tests/test_qdrant_db.py tests/test_gte_qdrant.py
```

Pipeline tests use real Parquet files and SQLAlchemy/SQLite with mocked Qdrant REST
and LLM completion transport. Live PostgreSQL, Qdrant retrieval, real GTE weights,
and live LLM inference are not established by those tests. Existing live database
tests require an explicit isolated test database; snapshot tests require an
explicit Qdrant test binary.
