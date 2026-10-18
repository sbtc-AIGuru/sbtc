# Medical retrieval pipeline

Run from the repository root with the existing `.venv`:

```bash
.venv/bin/python -m BackEnd.app.pipeline query_translated.parquet \
  --output artifacts/pipeline/output.json --zip artifacts/pipeline/output.zip \
  --batch-size 16 --workers 4 --reranker-device cuda:0
```

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
- Qwen3-Reranker-0.6B runs locally with Transformers/PyTorch already available
  in the project environment. It needs no OpenAI client, endpoint, or API key.
- PostgreSQL is used only for missing `doc_id`/`chunk_text` fields via the existing
  `PostgreManager.get_submission_chunks(ids)`, in parameterized batches of up to
  1000 IDs. Complete Qdrant payloads need no SQL lookup. Set `DATABASE_URL` if needed.

Both model loaders use cached files only. Set `PIPELINE_MODEL_CACHE` or
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

`QdrantManager.query_original_dense` is the four-branch implementation:
**GTE dense VI + native BM25 VI/EN/ZH**, fused by Qdrant RRF. The six-branch
`query_multilingual_dense` is not used. Defaults remain 50 points per branch and
100 fused points; configure `--branch-limit` / `--top-k` to change coverage.

Source document/chunk IDs are preserved. Conflicting PostgreSQL/Qdrant metadata
fails the affected query. Chunk deduplication uses the existing BTC text
normalization; output always retains the original source text.

`Retrieval/qwen_reranker.py` scores each original VI query–chunk pair using the
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

The default output is at most **50 chunks per query**, selected after Qwen reranks
all 100 fused candidates. Fewer candidates remain fewer; no padding or invented
chunks are added. `--max-chunks` changes this output budget; Python callers can
pass `max_chunks=None` to retain all chunks. `--max-docs` remains independent and
unlimited by default. The competition specifies no numeric candidate cap; 50 is
the requested project default, not a competition rule. Calibrate budgets against
validation labels; no Recall/F2 improvement is assumed.

## Submission, checkpoints and recovery

The schema was checked directly against the official [Submission Instructions
and Evaluation](https://leaderboard.aiguru.com.vn/competitions/15/) on 2026-10-18,
and agrees with [asked.md](../../asked.md):

```json
[{"id": 1, "relevant_docs": ["123"], "relevant_chunks": [{"doc_id": "123", "chunk_text": "Exact source text"}]}]
```

IDs are source integer document IDs serialized as strings. The competition
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
  the pipeline never silently falls back to an unranked success.
- Repeat the command with `--resume` to retry only unfinished/failed rows.
  Interrupted final journal appends are discarded. Changed input, retrieval
  configuration, chunk budget, Qwen revision/instruction/context/device reject the checkpoint.
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
