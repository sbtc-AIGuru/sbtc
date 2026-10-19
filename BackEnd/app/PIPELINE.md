# Medical retrieval pipeline

Run from the repository root with the existing `.venv`:

```bash
.venv/bin/python -m BackEnd.app.pipeline query_translated.parquet \
  --output artifacts/pipeline/output.json --zip artifacts/pipeline/output.zip \
  --batch-size 16 --workers 4
```

Qwen reranking is disabled by default to retain retrieval coverage. No Qwen
weights are loaded and no chunks are dropped by an output cap unless requested.
To enable it again, add `--rerank --max-chunks 50 --reranker-device cuda:0`.
Omit `--reranker-device` to use the encoder's `--device` (default `cpu`).
Use `--start 1 --end 16` for a small run. Bounds are inclusive, 1-based input
row positions; omitted bounds run the entire file. IDs and output order remain
unchanged. See also the [upload API](api/README.md).

## Models and services

- Qdrant requires the existing hybrid GTE + BM25 collection. Set `QDRANT_URL`,
  `QDRANT_COLLECTION` and existing vector/BM25 configuration, or pass `--manifest`
  from a hybrid snapshot. The collection is checked before embedding.
- The pinned GTE encoder reuses `Scripts/Qdrant/build_gte_qdrant.encode_records`:
  normalized CLS, 8192-token windows, weighted window fusion without truncation.
  VI queries are encoded together once per input batch.
- When enabled, Qwen3-Reranker-0.6B runs locally with Transformers/PyTorch already available
  in the project environment. It needs no OpenAI client, endpoint, or API key.
- PostgreSQL is used only for missing `doc_id`/`chunk_text` fields via the existing
  `PostgreManager.get_submission_chunks(ids)`, in parameterized batches of up to
  1000 IDs. Complete Qdrant payloads need no SQL lookup. Set `DATABASE_URL` if needed.

Both model loaders use cached files only; the default mode needs only GTE.
Set `PIPELINE_MODEL_CACHE` or
`--model-cache`; the downloaded project cache is automatically detected.
Download pinned public files explicitly before starting jobs:

```bash
.venv/bin/hf download Alibaba-NLP/gte-multilingual-base \
  config.json model.safetensors tokenizer.json tokenizer_config.json special_tokens_map.json \
  --revision 9bbca17d9273fd0d03d5725c7a4b0f6b45142062 --cache-dir artifacts/model-cache
.venv/bin/hf download Alibaba-NLP/new-impl configuration.py modeling.py \
  --revision 40ced75c3017eb27626c9d4ea981bde21a2662f4 --cache-dir artifacts/model-cache
.venv/bin/hf download Qwen/Qwen3-Reranker-0.6B \
  config.json model.safetensors tokenizer.json tokenizer_config.json merges.txt vocab.json \
  --revision e61197ed45024b0ed8a2d74b80b4d909f1255473 --cache-dir artifacts/model-cache
```

Qwen weights are about 1.2 GB. Cache files are ignored by Git. Setup failures
surface as `ENCODER_MODEL_UNAVAILABLE` / `RERANKER_MODEL_UNAVAILABLE`, rather
than marking every row as invalid input. No models are downloaded on upload.

## Retrieval and reranking

The translated input schema is `id` (integer), `query`, `english`, `chinese`.
The existing 1200-row dataset was inspected. Column overrides are available via
`--id-column`, `--original-query-column`, `--eng-query-column`,
`--chinese-query-column`, or the Python `columns` mapping. Missing translations,
invalid IDs, duplicates, and blank queries fail explicitly; no translation runs.

`--search-mode 4-branch` (default) uses `QdrantManager.query_original_dense`:
**GTE dense VI + native BM25 VI/EN/ZH**, fused by Qdrant RRF.
`--search-mode 6-branch` uses the existing `query_multilingual_dense`:
**GTE dense VI/EN/ZH + native BM25 VI/EN/ZH**. The six-branch mode batch-encodes
the three existing translations once per unique text, then reuses those vectors.
The UI selects either method per job. The pipeline defaults to 100 points per branch and
200 fused points; configure `--branch-limit` / `--top-k` to change coverage.
The API exposes these as `PIPELINE_BRANCH_LIMIT` / `PIPELINE_TOP_K`.

Source document/chunk IDs are preserved. Conflicting PostgreSQL/Qdrant metadata
fails the affected query. Chunk deduplication uses the existing BTC text
normalization; output always retains the original source text.

By default, fused candidates keep their Qdrant RRF order after source hydration
and deduplication. With `rerank=True` (Python), `--rerank` (CLI), or
`PIPELINE_RERANK=1` (API), `Retrieval/qwen_reranker.py` scores each original VI query–chunk pair using the
[official Qwen yes/no prompt and logits](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B).
There is no text generation. Python stably sorts scores descending, keeping
retrieval order on ties. Only chunks are reordered; document order is preserved.
The model can neither invent IDs nor rewrite chunks because it returns scores.

One model is initialized per pipeline run and reused for every query. Retrieval
uses bounded parallel workers with persistent sessions; model forwards run
sequentially in bounded pair batches to avoid concurrent GPU allocations.
Controls (also exposed as `PIPELINE_RERANKER_*` API environment variables):

| CLI option | Default | Meaning |
| --- | --- | --- |
| `--reranker-device` | Same as `--device` | CPU or e.g. `cuda:0` |
| `--reranker-batch-size` | 4 | Maximum pairs per model forward |
| `--reranker-max-length` | 8192 | Maximum tokens per window, up to 32768 |
| `--reranker-token-budget` | 8192 | Padded tokens per forward; must be at least max length |

Each window retains the complete query. Long chunks are split into document
windows and assigned their maximum window score; source text is never truncated
in the submission. A query that leaves no document context fails explicitly;
increase both context length and token budget if resources permit. CPU uses
float32, CUDA float16, SDPA attention, no KV cache, and final-position logits only.
These settings bound inference work; there is no claim of measured Recall/F2 gains.

The default output retains **all chunks from the 200 fused candidates** after
source deduplication. Fewer candidates remain fewer; no padding or invented
chunks are added. `--max-chunks 50` explicitly limits the output to 50, after
optional Qwen reranking; Python's `max_chunks=None` is the default.
`--max-docs` remains independent and unlimited by default. The competition
specifies no numeric candidate cap. Calibrate budgets against
validation labels; no Recall/F2 improvement is assumed.

## Submission, checkpoints and recovery

The field names were checked directly against the official [Submission Instructions
and Evaluation](https://leaderboard.aiguru.com.vn/competitions/15/) on 2026-10-18,
and agrees with [asked.md](../../asked.md):

```json
[{"id": 1, "relevant_docs": [123], "relevant_chunks": [{"doc_id": 123, "chunk_text": "Exact source text"}]}]
```

IDs are source integer document IDs serialized as **JSON integers**, including
IDs read as numeric strings from Qdrant payloads. The competition
requires chunk text, not internal chunk IDs. `chunk_order` is optional; the
submitted array position is used when it is omitted, so Qwen ranking is retained
without adding a source-position field. ZIP contains exactly one JSON file at its
root. A competition submission must cover all **1200 queries**; an explicit
start/end test range remains a partial local export. Empty retrieval is a valid
result with two empty lists; no medical answer or explanation is generated.

- `output.checkpoint.jsonl` records the input/configuration fingerprint and each
  successful row with original chunk IDs. Each successful query is flushed and
  fsynced before progress is published, including within an unfinished batch.
- `output.errors.json` records failed row positions, IDs, stages and exception
  types. Independent queries continue. A failed query prevents final JSON/ZIP;
  enabled Qwen failures never silently fall back to unranked results.
- Repeat the command with `--resume` to retry only unfinished/failed rows.
  Interrupted final journal appends are discarded. Changed input, retrieval
  configuration, search mode, submission format, chunk budget, reranking mode and
  enabled Qwen revision/instruction/context/device reject the checkpoint.
  The API saves search/rerank choices and candidate/output budgets per job; resume
  uses that saved configuration, even if the server's defaults change.
  Choose a new job/output when changing a job's mode. **Checkpoints from the
  previous string-ID format require a new job/output.**
  Use a new job/output for the widened 100-per-branch / 200-fused defaults;
  checkpoints created with the former 50/100 limits require those original limits to resume.
  **Checkpoints from the previous LLM reranker require a new job/output path.**
- Pause remains at the next input batch boundary. Already checkpointed rows
  survive a restart. Model/retrieval progress and per-query durations are logged.
  API state advances after each durable query; no special frontend changes needed.

Python callers use `run_pipeline(...)`; tests can inject `dense_encoder(texts)`,
`qdrant_factory(encoder)`, `postgres_manager`, and `reranker.score(query,texts)`.
Injected components are caller-owned and require a stable `resume_tag` on resume.
The former `llm_client`, `llm_workers`, `llm_timeout` arguments and CLI flags have
been removed. The separate legacy LLM module is not imported by this pipeline.

## Focused checks

```bash
.venv/bin/python -m pytest -q tests/test_qwen_reranker.py tests/test_pipeline.py tests/test_api.py
```

Fixtures use real Parquet/SQLAlchemy SQLite and mocked Qdrant/reranker boundaries.
Qwen unit tests also run a real tiny randomly initialized Qwen3 model, without
network access or pretrained weights. They do not establish live database or
retrieval quality. Full-weight smoke tests must be run separately on synthetic
inputs before processing a large dataset.
