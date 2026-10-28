# Medical retrieval pipeline

Run from the repository root with the existing `.venv`:

```bash
.venv/bin/python -m BackEnd.app.pipeline artifacts/query-embeddings/query_rewritten_final_embeddings.parquet \
  --output artifacts/pipeline/output.json --zip artifacts/pipeline/output.zip \
  --batch-size 16 --workers 4
```

Qwen reranking is disabled by default to retain retrieval coverage. No Qwen
weights are loaded and no chunks are dropped by an output cap unless requested.
To enable it again, add `--rerank --max-chunks 50 --reranker-device cuda:0`.
Omit `--reranker-device` to use `--device` (default `cpu`).
Use `--start 1 --end 16` for a small run. Bounds are inclusive, 1-based input
row positions; omitted bounds run the entire file. IDs and output order remain
unchanged. See also the [upload API](api/README.md).

## Models and services

- Qdrant performs dense search only; no sparse/BM25 index is required. Set
  `QDRANT_URL`, `QDRANT_COLLECTION`, optionally `QDRANT_DENSE_VECTOR_NAME`, or
  pass `--manifest` from a compatible dense snapshot. Qwen input defaults to
  `vibiomir_qwen3_06b_1024_fp16_dense`; GTE input retains its existing default.
- Elasticsearch performs all BM25 search. Set `ELASTICSEARCH_URL` and
  `ELASTICSEARCH_INDEX` (default `vibiomir_bm25`). One index contains
  `content_vi`, `content_en`, `content_zh`, each searched with its matching
  `lang` filter. VI uses PyVi, ZH uses OpenCC + SmartCN, EN retains medical
  terms/negations. The pipeline validates existing mappings without changing them.
  English search analyzes the original query with the existing `medical_en` analyzer,
  then gives the personal terms `i/me/my/mine/myself/we/our/ours/ourselves` a 0.05
  BM25 boost. All analyzed tokens remain eligible under OR; no stemming, synonym
  expansion, concept gate, or stopword deletion is added. Other terms retain normal
  scoring, including numbers and negations. VI/ZH search and adaptive RRF are unchanged.
  This needs read access to `_analyze` and `_search`, without reindexing or changing
  the query Parquets. Restart the API and create a new job to use the updated search;
  checkpoints from the old profile must not be resumed into the new profile.
- Dense vectors are read from the Parquet produced by
  [Query_GTE_Embeddings_Colab.ipynb](Database/Notebook/Query_GTE_Embeddings_Colab.ipynb).
  The pipeline never automatically loads GTE or computes query embeddings.
  GTE files retain their pinned model/code revisions and pooling settings.
  Qwen3 1024 FP16 notebook files are also supported; see the paired-input example below.
- When enabled, Qwen3-Reranker-0.6B runs locally with Transformers/PyTorch already available
  in the project environment. It needs no OpenAI client, endpoint, or API key.
- PostgreSQL is used only for missing `doc_id`/`chunk_text` fields of top-k chunks via the existing
  `PostgreManager.get_submission_chunks(ids)`, in parameterized batches of up to
  1000 IDs. Complete search payloads need no SQL lookup; original `content` from either store
  is mapped to `chunk_text` without rewriting it. Set `DATABASE_URL` if needed.

The default mode requires no local embedding or reranker weights. When reranking
is enabled, the Qwen loader uses cached files only.
Set `PIPELINE_MODEL_CACHE` or
`--model-cache`; the downloaded project cache is automatically detected.
Download pinned public files explicitly before starting jobs:

```bash
.venv/bin/hf download Qwen/Qwen3-Reranker-0.6B \
  config.json model.safetensors tokenizer.json tokenizer_config.json merges.txt vocab.json \
  --revision e61197ed45024b0ed8a2d74b80b4d909f1255473 --cache-dir artifacts/model-cache
```

Qwen weights are about 1.2 GB. Cache files are ignored by Git. Setup failures
surface as `RERANKER_MODEL_UNAVAILABLE`, rather
than marking every row as invalid input. No models are downloaded on upload.

## Retrieval and reranking

The input retains `id` (integer), `query`, `english`, `chinese`, and adds
`vector_original`, `vector_english`, `vector_chinese` (fixed-size lists of 768
float32 values) and `query_sha256`. The notebook's `query_embedding` schema
metadata identifies model/code revisions, language/vector mapping and pooling.
Missing/incompatible metadata is rejected before contacting services; each row's
text hash, finite values and L2 norms are validated before retrieval. Text remains
available for BM25 and optional Qwen reranking. Text-only CLI/API uploads must be
embedded with the notebook first; there is no automatic encoder fallback.
Column overrides for text/ID are available via
`--id-column`, `--original-query-column`, `--eng-query-column`,
`--chinese-query-column`, or the Python `columns` mapping. Missing translations,
invalid IDs, duplicates, and blank queries fail explicitly; no translation runs.

`--search-mode 4-branch` (default) searches **Qdrant dense VI + Elasticsearch BM25 VI/EN/ZH**.
`--search-mode 6-branch` searches **Qdrant dense VI/EN/ZH + Elasticsearch BM25 VI/EN/ZH**.
`--search-mode 3-branch` searches **Qdrant dense VI/EN/ZH only**. It uses the three
cached query vectors, gives each branch RRF weight `1/3`, ignores `dense_weight`,
and does not connect to Elasticsearch. Filters, source hydration, reranking,
candidate/output limits, JSON/ZIP and checkpoint behavior remain the same.
The pipeline fuses these ranked lists by original `chunk_id`, since Qdrant UUIDs
and Elasticsearch SHA-256 IDs differ. It retains original source text and fails
on conflicting document IDs/text between stores. The shared Elasticsearch client
is thread-safe; Qdrant sessions remain per worker.
The default is 100 candidates per branch, then 200 fused chunks. `relevant_docs`
contains only unique document IDs from these top-k chunks, in RRF order.
Equal fusion scores keep the first branch appearance; Qdrant previously left ties unspecified.
Use `--branch-limit` / `--top-k` to change coverage.
The API exposes these as `PIPELINE_BRANCH_LIMIT` / `PIPELINE_TOP_K`.

Dense Qdrant requests use `hnsw_ef=512` by default in every search mode.
Use `--hnsw-ef 1024`, the API/UI `hnsw_ef` field, or `PIPELINE_HNSW_EF`
to change the HNSW search breadth independently of candidate/output counts.
This is a query parameter; it does not modify `ef_construct` or rebuild the index.
Python callers can pass `hnsw_ef=None` to retain the snapshot's search default.
The ef value is part of the checkpoint signature; changing it requires a new output.
API jobs created before this option retain their original snapshot default on resume.

### Adaptive dense/lexical weights

An optional `dense_weight` column controls each input query independently.
Missing columns, null/NaN values and blank strings default to `0.5`. Numeric
values (including numeric strings) must be finite and between 0 and 1; invalid
values fail that row as input errors. No embedding is recomputed when weights change.

The weight belongs to the whole dense group; `1 - dense_weight` belongs to the
whole lexical group. It is divided equally among that group's language branches:

| Mode | Each dense branch | Each BM25 branch |
| --- | --- | --- |
| 4-branch | `dense_weight` | `(1 - dense_weight) / 3` |
| 6-branch | `dense_weight / 3` | `(1 - dense_weight) / 3` |
| 3-branch | `1 / 3` | Not used; Elasticsearch is not contacted |

Fusion now runs in Python because the branches come from two services. It retains
Qdrant's exact rank-weighting formula and float32 accumulation:
`sum(1 / ((position + 1) / branch_weight + 2 - 1))`, with zero-based positions.
This is Qdrant's weighted RRF, not `weight / (k + rank)`; see the
[official implementation](https://github.com/qdrant/qdrant/blob/v1.19.2/lib/segment/src/common/reciprocal_rank_fusion.rs).
Dense branches come first, followed by BM25 VI/EN/ZH.
At weight 0 only BM25 branches run; at weight 1 only dense branches run, so the
zero-weight group's candidates cannot fill unused result positions.

Preserve the notebook's schema metadata when adding the optional column, e.g.:

```python
import pyarrow as pa
import pyarrow.parquet as pq

table = pq.read_table('query_rewritten_final_embeddings.parquet')
weights = [None] * table.num_rows  # Set each row's chosen weight; None uses 0.5.
table = table.append_column('dense_weight', pa.array(weights, type=pa.float32()))
pq.write_table(table, 'query_adaptive.parquet', compression='zstd')
```

Create a new job/output after changing weights or switching from the previous
unweighted RRF pipeline. Checkpoint signatures include the input file and fusion
version, so resume cannot mix results produced with different weights.

Source document/chunk IDs are preserved. Conflicting PostgreSQL/Qdrant metadata
fails the affected query. Chunk deduplication uses the existing BTC text
normalization; output always retains the original source text.

By default, fused candidates keep their RRF order after source hydration
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

`relevant_docs` retains **unique document IDs from the top-k fused results**, in
RRF order. IDs stay integers and appear once. Qdrant returns at most `top_k`
points in one query; candidates outside top-k are not requested for document IDs.
`max_docs` / `--max-docs` optionally caps the document list and is unlimited by default.

`relevant_chunks` retains **chunks from the top 200 fused points** after source
deduplication. Candidates below top-k do not refill chunks removed by deduplication.
`--max-chunks 50` further limits chunks after optional Qwen reranking;
Python's `max_chunks=None` is the default. Chunk limits, empty chunk text and
reranking do not truncate the document list. The competition specifies no numeric
candidate cap. Calibrate budgets against validation labels; no Recall/F2 improvement
is assumed. Create a new job/output when switching from the all-branch-document
policy; its checkpoints cannot be mixed with top-k-only results.

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
The explicit Python `dense_encoder` injection remains compatible with legacy
text-only callers; embedded inputs always take precedence and never call it.
`encoder_batch_size` / `--encoder-batch-size` are retained for compatibility and
do not affect precomputed vectors. Existing text-input checkpoints require a new
job/output when switching to the embedded Parquet.
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

## Qwen3 paired input (1024 FP16)

The Qwen notebook replaces `query`, `english`, `chinese` with vectors. Provide
its original text Parquet as well, so Elasticsearch and optional reranking can
use the original queries. The merger verifies the notebook's `source_sha256`,
row counts, every row's ID, model profile, dimension and dtype. It streams in
batches of 64, preserving FP16 values and `dense_weight` from the vector file.
The resulting input contains both text and `vector_*` columns plus per-row
text hashes; the original files stay unchanged. FP16 squared L2 norms allow
0.002 rounding tolerance; GTE retains its existing 0.00002 tolerance.

```bash
.venv/bin/python -B -m BackEnd.app.pipeline \
  query/query_rewritten_weighted_qwen3_1024_fp16.parquet \
  --query-text /home/nhminh/Downloads/query_rewritten_weighted.parquet \
  --output artifacts/pipeline/output.json --zip artifacts/pipeline/output.zip \
  --search-mode 4-branch --start 1 --end 3
```

The CLI retains `output.input.parquet` next to the output. Resume also verifies
both original file hashes. Python callers can use `combine_query_files()` and
pass the returned path to `run_pipeline()`. A ready combined file from this
handoff is `artifacts/pipeline-elasticsearch/query_qwen3_with_text.parquet`.

The upload API accepts a second multipart field `query_file`; the UI has an
optional original-query file picker. Existing GTE and combined Qwen inputs still
use a single upload. Upload size limits apply to the sum of both files.

Use new jobs/checkpoints after this migration. The fingerprint includes the
Elasticsearch URL/index and the new fusion backend, rejecting old hybrid-Qdrant
checkpoints. `PIPELINE_RESUME_TAG` should identify an in-place corpus/index update.
Shared keyword `query_filter` conditions on `doc_id`, `chunk_id`, `lang` support
`match.value/any/except` and boolean groups. Unsupported Qdrant-only filters fail
explicitly rather than silently broadening BM25 results. The HTTP form has no filter setting.

## Verification — 26 October 2026

The existing `.venv` ran the focused pipeline, precomputed-input, API, hybrid,
Qdrant and Elasticsearch tests: **218 passed, 2 skipped**. The skipped checks
need the local raw corpus and a dedicated writable Elasticsearch test cluster;
no production index was written. Existing PyVi/Starlette warnings remain upstream.
`git diff --check`, the CLI help and JavaScript syntax check also passed.

All 1,200 supplied query rows were merged and checked for text hashes, FP16 norms
and preserved adaptive weights. The real upload/job/download API then processed
the first three rows at the default 100 candidates/branch and top 200:

| Mode | Qdrant dense requests | ES BM25 requests | Successful queries | Output chunks/query |
| --- | ---: | ---: | ---: | ---: |
| 4-branch | 3 | 9 | 3 | 200 |
| 6-branch | 9 | 9 | 3 | 200 |

The check asserted every Qdrant query was a 1024-dimensional dense-only request,
and every Elasticsearch query used the correct language field/filter and returned
that language. Both ZIP downloads contained valid integer-ID `output.json`.
Artifacts: `artifacts/pipeline-elasticsearch/live-api-report.json` and
`live-api-jobs/<job-id>/output.zip`; repeat with `check_live_api.py` in that folder.
The live tests used existing 4,936,835-chunk indexes and disabled reranking.
Reranker behavior and pause/resume are covered by isolated tests with mocked
model scores; full 1,200-query retrieval and live GPU reranking were not run.
