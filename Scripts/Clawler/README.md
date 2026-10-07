# Current-corpus backfill

Use the project virtual environment:

```bash
source .venv/bin/activate
```

`backfill.py` uses only the supplied current successful JSONL and its Parquet
source. It does not discover previous crawl files or reuse earlier Kaggle jobs.
The baseline must have unique increasing `row_index` values and matching
Parquet `id` and `url` fields. Preparation verifies all baseline records and
hashes both inputs. No article text is loaded in bulk.

Prepare a new campaign for gaps of at least 1,001 rows:

```bash
python Scripts/Clawler/backfill.py prepare \
  --campaign .backfill/large_ranges_20261007
```

The default baseline is
`data/crawled_local_kaggle_success_unique_20261005.jsonl`; the default source is
`data/links_corpus.parquet`. The maximum index is inferred from that baseline.
`--max-index` can narrow this scope, but cannot extend it. `--min-gap 1` selects
every gap. A campaign directory must be new; resume uses `run`, not `prepare`.

Run a bounded pilot, with samples spread through each hostname's target rows:

```bash
python Scripts/Clawler/backfill.py run \
  --campaign .backfill/large_ranges_20261007 \
  --pilot-per-host 50 --limit 100
```

`--limit` bounds document dispatches in this invocation, including resumed
attempts. `--pilot-per-host` selects up to that many documents per hostname;
the total pilot can therefore exceed that number. Remove the pilot and limit
options to process the rest of the manifest. Repeat `run` to resume the same
campaign. A pass returns when remaining work is cooling down; use
`--wait-for-retries` to wait for scheduled retries. Each URL gets at most
`--max-rounds 3` campaign rounds by default. Sources that repeatedly deny access
should be inspected before enabling a long-running retry pass.

Inspect coverage and request diagnostics:

```bash
python Scripts/Clawler/backfill.py report \
  --campaign .backfill/large_ranges_20261007
```

`remaining` includes every target without validated success, including
permanent failures. A completed pass does not mean complete success coverage.
Reports include per-host counts, request modes/error types, and latency
percentiles for the last 500 requests per host. `results.jsonl` records final
document outcomes; `attempts.jsonl` records individual HTTP/browser requests.
The SQLite ledger recovers from a journal append followed by a crash before
the state commit. A partial final journal line is backed up before repair.
An unrestricted run exits with code 3 while targets remain; deliberately
bounded pilot/group runs return normally with their remaining counts.

HTTP/browser/retry/pagination share one admission controller. Denials trigger
cooldown for the relevant host/group; other groups continue. `Retry-After`
supports both seconds and HTTP dates. Browser fallback handles incomplete or
JavaScript-rendered articles, while confirmed denial/missing-page responses
are deferred or classified without immediately switching strategies. Both
strategies must pass the article validator. Robots exclusions are respected.
In `auto` mode, Long Chau starts with the ordinary browser: the bounded fresh
pilot returned valid browser content while a direct HTTP sample was denied.
Other sources start with HTTP. Explicit `--fetch-mode http` or `browser`
overrides routing; policies may also specify `fetch_mode`. Existing cooldowns
still apply when changing strategies.
The current `ask.39.net` question template keeps its question description,
excludes recommendation/consultation widgets, and records `has_answer=false`
when no answer is actually present. If answer sections exist, they must be
included for validation to pass.

The default global limits are 8 HTTP slots, 2 browser slots and 16 document
tasks. Host limits are more restrictive. The `39.net` family shares a quota,
with one document in flight per hostname. Chromium is reused and recycled
after 300 browser outcomes or low memory; the HTTP session stays open across
browser recycling. Request pacing controls page fetches, not every browser
asset or redirect hop.

Policy overrides can be supplied to `prepare --policy-file path.json`:

```json
{
  "39.net": {
    "group": "39.net",
    "concurrency": 2,
    "interval_seconds": 3.0,
    "cooldown_seconds": 900.0,
    "max_attempts": 3
  },
  "nhathuoclongchau.com.vn": {
    "concurrency": 1,
    "interval_seconds": 2.5,
    "cooldown_seconds": 900.0,
    "max_attempts": 3
  }
}
```

Policies are captured in the manifest. Group overrides apply to all members;
conflicting overrides for one group are rejected. Initial rates are starting
points to measure, not proven throughput. Successful windows can restore
rates after a slowdown, up to the configured baseline rate.

Use `run --group 39.net` or another reported `group_key` to assign distinct
origins to workers. A campaign has a writer lock; local workers also lock each
origin in `.backfill/host_locks`. These are local filesystem locks, not a
distributed quota service. Local and remote workers must receive disjoint
origin groups; do not launch overlapping local/Kaggle campaigns. The legacy
`krun_sources.py` runner limits each source to one active remote shard.
`--host ask.39.net` narrows a pilot to one exact reported hostname while still
owning and honoring the shared `39.net` quota. Host queues rotate fairly within
a group, so earlier ranges do not starve later question templates.

Import explicitly selected new worker deltas with exact target identity:

```bash
python Scripts/Clawler/backfill.py ingest \
  --campaign .backfill/large_ranges_20261007 \
  --input /path/to/new_delta_a.jsonl /path/to/new_delta_b.jsonl
```

Records must retain original `row_index`, `id`, and `url`, successful usable
text or an explicit failure, and any campaign ID must match. Partial worker
outputs can be ingested when all included lines are complete and valid.
All good successes are retained across files; a later failure cannot replace
one. Content hashes prevent importing an identical file twice.

Publish a new corpus containing the untouched baseline records plus successful
backfill records in index order:

```bash
python Scripts/Clawler/backfill.py merge \
  --campaign .backfill/large_ranges_20261007 \
  --output data/crawled_backfilled_large_ranges_20261007.jsonl
```

Merge refuses an existing output and verifies the baseline checksum before
publishing. A report accompanies its console result; unsuccessful targets
remain visible in campaign state. Fixing only the large ranges does not cover
the smaller gaps. URL text may be unrecoverable when an article is removed or
the source denies access.

Run the focused regression suite without installing another test framework:

```bash
PYTHONPATH=Scripts/Clawler:tests python -m unittest \
  test_backfill test_fetch_policy test_fetch_http_offline test_http_strategy \
  test_crawl_lifecycle test_local_range test_krun_sources test_krun_range \
  test_unit_quality test_unit_quality_universal test_unit_site_configs \
  test_generalized_crawler test_integration_pipeline \
  test_unit_verbatim test_verbatim_cleaner
```

`test_http_strategy` uses a localhost server and the installed Chromium; it
needs permission to create local sockets. The other listed tests use fixtures
and mocked transports. Existing live-site test modules are excluded from this
command. The backfill command never installs dependencies or browsers.

## Implementation map

| Files | Change |
| --- | --- |
| `backfill.py` | Current-baseline manifest, SQLite campaign state, fair host scheduling, pilot, ingestion and sparse merge |
| `fetch_policy.py` | Shared quotas, Retry-After, cooldown, error classification and source routing policy |
| `http_strategy.py` | Preserve HTTP error headers and support a stable per-run user agent |
| `fetch.py` | Strategy routing, request diagnostics and shared HTTP/browser validation |
| `quality.py`, `site_configs.py` | Article layouts, question-only metadata, extraction selectors and robots configuration |
| `utils.py`, `compact.py` | Resume by row identity and retain usable successes after cleaning |
| `crawl.py`, `local_range.py`, `krun_sources.py` | Apply host policies, process finished tasks promptly, reuse browser, bound remote source concurrency |
| Project `pyproject.toml`, `uv.lock` | Pin the verified Crawl4AI 0.9.4 backend without changing installed packages |
| Project `.gitignore` | Exclude new campaign state and runtime artifacts |
| `tests/test_backfill.py`, `tests/test_fetch_policy.py`, `tests/test_http_strategy.py` | Campaign, quota and real loopback/browser regressions |
| `tests/test_fetch_http_offline.py`, `tests/test_unit_quality.py` | Routing, denial handling and question template regressions |
