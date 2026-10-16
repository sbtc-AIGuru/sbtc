# Resource contract

`concepts.json` contains 12 team-authored seed concepts and 80 code-grounded Vietnamese-English communicable-disease concepts from VN Core FHIR 0.10.0. The FHIR entries use the same source CodeSystem/code for both language labels; their IDs preserve that namespace. The file remains `production_ready: false`: package-level CC-BY-4.0 attribution is recorded, but independent resource-level rights review is pending. It is not a complete UMLS/MeSH/CMeSH/ICD/drug lexicon. Team-authored local IDs do not assert equivalence to an official identifier. No Chinese mappings were inferred from THUOCL.

To extend, supply `--lexicon path.json` with the same schema and per-entry source/license. Aho-Corasick matchers and the Jieba dictionary derive from this snapshot; hashes bind preparation and queries. Do not derive aliases from queries/qrels/for_valid. Do not package copyrighted dictionaries without the appropriate permission. Acronyms listed under `ambiguous_aliases` are not grounded automatically.

The `concepts.json` hash participates in the corpus preparation fingerprint. After changing this file, rebuild the prepared corpus and indexes before querying; the CLI rejects a prepared snapshot whose fingerprint does not match the selected lexicon.

Query translation cache (`--cache path.jsonl`) contains lines with `query_sha256` (UTF-8 SHA256 of exact input query), `translations` (`en`/`zh`) and `provenance` (source/model/revision). It must be prepared independently of qrels. No closed API is invoked by the component. Missing translations are disclosed per query; aliases/anchors provide partial cross-language retrieval only. Full production requires a verified eligible open-weight translator/cache, resource provenance and independent terminology review; this code does not invent translated queries to hide missing resources.

English alias tables cover selected whole-word inflections/spelling variants; they are not the full NLM LVG lexicon. The implementation does not claim complete NegEx/ConText, medical morpheme decomposition or drug prefix dictionaries. These are extension resources requiring their own semantic validation, not unconditional replacements of source text.

## Translation cache schema (validated)

```json
{"source_query":"đái tháo đường 500 mg","query_sha256":"<sha256 of exact source_query UTF-8>","translations":{"en":"diabetes 500 mg","zh":"糖尿病 500 mg"},"provenance":{"model_id":"<public HuggingFace model>","revision":"<40 lowercase hex commit>","license":"<actual license>","parameters":600000000,"release_date":"<verified YYYY-MM-DD before 2026-08-01>","open_weights":true}}
```

Placeholder values are not accepted runnable cache entries. Manifest declarations must be checked against the actual model source; validation cannot itself prove the author's publication claim. Numeric guard drops a translation missing any source number, retaining original/aliases channels and warnings. It does not prove doses, polarity or medical terms were translated correctly.

Optional local NLLB model manifest for `translate`:

```json
{"local_directory":"/absolute/path/to/model-snapshot","provenance":{"model_id":"<verified HF ID>","revision":"<40 lowercase hex commit>","license":"<actual license>","parameters":600000000,"release_date":"<verified release date>","open_weights":true},"files":{"config.json":"<SHA256>","model.safetensors":"<SHA256>","tokenizer.json":"<SHA256>"}}
```

Include **every** actual model/tokenizer file in `files`; the three names above are illustrative. Assets must be provisioned separately from reviewed public HF revisions. No automatic download, external inference service, qrels access, pickle weight loading or remote-code execution is used. Loaded parameter count is checked as well as declared eligibility. NLLB long inputs >512 tokenizer tokens fail rather than truncate silently. The local-model adapter has contract tests, but real model inference has not been exercised/provisioned in this task.

## Curated source snapshot

The source resource audit and derived, auditable snapshot are documented in [SPEC-resource-curation.md](../SPEC-resource-curation.md) and [curation report](curated/20261015/REPORT.md). Run the converter with a fresh versioned output directory:

```bash
python3 sbtc/Scripts/Retrieval/curate_resources.py \
  --output-dir sbtc/Scripts/Retrieval/resources/curated/20261016
```

The run08 `curated/` term/concept candidates remain unverified and are not loaded by the current BM25 lexicon. The 80 code-aligned VN Core FHIR disease entries noted above were separately added to `concepts.json`; they are loaded by the local analyzer, but independent resource-level rights review remains open. No retrieval benchmark has established a score improvement.
