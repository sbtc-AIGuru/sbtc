# Spec: Hybrid paragraph chunking

Status: approved by the user on 2026-10-08 and implemented from the current checkout. Scope: chunk construction and its own input/output, tests, and benchmarks only.

## Objective and evidence

Build a deterministic, streaming chunker for the crawled medical documents. It must preserve the official `id` as `doc_id`, retain exact text slices, and construct Document → Parent → Child relationships. Embedding, retrieval, reranking, and crawler behavior are outside this scope.

The sole dataset for development checks, tests, and benchmarks is `datacrawl/test.jsonl` (read only). A read-only scan on 2026-10-08 found 20,000 records, including 17,523 successful records and 2,477 empty failures. All records have `row_index`, `id`, `url`, `text`, and `success`; failures have `error`, and 573 records have `page_count`. Median nonempty text length is 1,075 characters; median nonempty line count is 16; 8,614 records contain a blank line; 299 contain a Markdown heading. These are sample findings, not full-corpus estimates.

The `Scripts/Preprocess` Python sources described in `docs_AI.md` and shown in the IDE are absent from the current filesystem and Git tree. This spec assumes a separate chunking component under `Scripts/Preprocess`, reusing the current `Scripts/Clawler/verbatim.py` cleaner without changing crawler code. If the missing sources are restored, integration points will be reviewed before implementation.

## Input and text provenance

- Stream UTF-8 JSONL one record at a time. Require `id` to be an integer, `text` to be a string, and `success` to be a boolean; preserve the input `id` and `url`. `row_index` is provenance only and never substitutes for `id`.
- For a successful, nonempty record, apply the existing `clean_to_verbatim` to `record["text"]`. Name this result `source_text`. Keep a hash of both raw and cleaned text for audit. Do not overwrite input.
- All parent and child offsets refer to `source_text`; every child must satisfy `chunk_text == source_text[start_char:end_char]`. This follows the repo's Markdown rule. Raw crawler offsets are not claimed to be interchangeable with cleaned offsets.
- Failed, malformed, or empty records produce a counted skip/error status with line number and reason. Malformed JSON is reported without changing the source data.

## Chunk behavior

1. Detect document type with deterministic Q&A, length, line-break, and fallback rules; detect headings when extracting structure. Record `doc_type`, `classification_reason`, and `classification_confidence` (`high`/`medium`/`low`) as metadata. Confidence is only a rule-strength label, not a calibrated probability or a claim of semantic understanding.
2. Extract contiguous line/paragraph spans, preserving exact character positions. Blank lines are strong boundaries; single newlines are candidate paragraph boundaries because the test data often lacks blank lines. Headings, Q&A labels, doctor replies, and section markers are structural boundaries.
3. Make short Q&A or short documents one coherent parent with one child when possible. For longer documents, group adjacent paragraphs within a section. Keep question and answer, negation and condition context together when the detected structure supports it. Never split a sentence or a paragraph, including as fallback.
4. Count configurable sizing units without altering text: CJK characters individually and contiguous Latin/numeric medical expressions as units. Start with min/target/max of 150/220/300 units and a preferred overlap near 40 units, matching the existing repo design. Boundaries and source fidelity take priority; overlap uses only complete paragraph spans. A lone paragraph over max remains intact and receives an `oversized_paragraph` reason.
5. Parents are coherent sections or document regions. Children are contiguous spans contained in exactly one parent. A child never crosses a document or parent boundary. Use deterministic IDs derived from `doc_id`, hierarchy level, order, offsets, and configuration version. Preserve `chunk_order` as a nonnegative integer.
6. Do not silently discard source content. This implementation keeps every non-whitespace source span in at least one child; it does not filter navigation or boilerplate. No synthetic title or heading is inserted into `chunk_text`.

## Output and operations

- Write a new derived JSONL artifact, separate from source data, with one compact record per input document. A successful record contains `doc_id`, URL, text hashes, text length, version, parent metadata (ID, offsets, type), child metadata (ID, parent ID, offsets, order, units, exact `chunk_text`, exception reason), and source coverage counts. A failed record contains a status and reason, without chunks.
- Process input in bounded memory. Write output in configurable shards, with each shard committed atomically and a checkpoint recording the last complete input line, output shard, config fingerprint, and input fingerprint. Resume only when these match. Reject input/output path equality and existing output unless explicitly resuming.
- Log counts and validation errors by reason. Support configurable shard size and worker count; preserve output order and deterministic IDs regardless of worker count.
- Benchmark four modes on `datacrawl/test.jsonl`: basic paragraph grouping; structure-aware paragraph grouping; adaptive structure-aware grouping; full parent-child hierarchy. Keep text source, unit counter, and machine conditions comparable. Report throughput, peak RAM, chunk counts and sizes, oversized rate, structural-boundary rate, source-span coverage, and parent-child integrity. Do not infer retrieval accuracy from these metrics.

## Project structure and commands

- `Scripts/Preprocess/`: document structure, sizing, chunking, hierarchy, streaming CLI, and benchmark entry points.
- `tests/`: tests of this chunking feature using records selected from `datacrawl/test.jsonl` only. Test output goes to a temporary directory; input is never modified.
- `docs_AI.md`: record design decisions, difficulties, fixes, and measured results.

Commands from the workspace root:

```bash
python -m sbtc.Scripts.Preprocess.chunk_cli datacrawl/test.jsonl /tmp/aiguru-chunks-test --min-units 150 --target-units 220 --max-units 300 --overlap-units 40
python -m unittest discover -s sbtc/tests -p 'test_chunk_*.py' -v
python -m sbtc.Scripts.Preprocess.chunk_benchmark datacrawl/test.jsonl /tmp/aiguru-chunk-benchmark
python -m sbtc.Scripts.Preprocess.chunk_audit datacrawl/test.jsonl /tmp/aiguru-chunks-test
```

The unit suite selects real records from `test.jsonl`; malformed and boundary cases may be constructed by changing those records in memory or in temporary files. It never reads another crawl dataset. A resumed CLI run uses the same command with `--resume` and the same output directory.

## Verification cases and acceptance

- Short and long Q&A, article headings, medical negation/conditions, failed and malformed records, no structural delimiter, long single paragraph, Chinese medical values and Latin expressions.
- For every successful output record: valid original `doc_id`; child/parent offsets in bounds; child inside parent; exact `source_text` slice; stable IDs and output across repeated runs; no duplicate child records; complete accounting of source spans or explicit exclusion reason.
- For every run: bounded memory, resumable output, no edits to `datacrawl/test.jsonl`, and a benchmark report containing all four modes and the required metrics.

## Approved design decisions

1. Use cleaned plain-verbatim `source_text` as the offset reference, while retaining raw text hashes. This reconciles the attachment's exact-substring requirement with the repo rule to clean Markdown before chunking.
2. Build a standalone chunking component because the existing `Scripts/Preprocess/*.py` sources are absent. If those files are restored, adapt to their existing interfaces before changing code.
3. Allow a whole paragraph to exceed the nominal 300-unit maximum, as the attachment explicitly requires no paragraph or sentence splitting. Report each exception.
