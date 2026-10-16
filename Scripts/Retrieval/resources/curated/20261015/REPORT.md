# Resource curation report — 2026-10-15

Rule version: resource-curation-1.0. Source files are read-only; this output is not installed into BM25.

## Monolingual lists

| Language | Source lines | Unique terms | Lexical candidates | Review | Excluded |
|---|---:|---:|---:|---:|---:|
| vi | 154122 | 154122 | 44913 | 109209 | 0 |
| en | 12955 | 12955 | 12949 | 6 | 0 |
| zh | 21736 | 21736 | 18962 | 2774 | 0 |

- vi review reasons: {"five_token_window_shape_requires_review": 94102, "known_fragment_or_nonmedical_sample": 30, "negation_or_context_candidate": 371, "organization_or_provider_candidate": 11084, "possible_context_word": 44637, "possible_sentence_or_context_phrase": 2115, "possible_sentence_suffix": 224}

- en review reasons: {"generic_or_broad_phrase": 3, "possible_code_glued_to_label": 3}

- zh review reasons: {"known_nonmedical_sample": 28, "negation_or_context_candidate": 325, "organization_or_provider_candidate": 30, "possible_context_phrase": 623, "possible_sentence_or_action_prefix": 519, "possible_sentence_or_context_phrase": 414, "possible_sentence_prefix": 1099}

Reason counts overlap when one term has several review cues; they are not disjoint groups.

lexical_candidate means only that deterministic structural rules found no review/exclusion cue. It is not a claim that the phrase is medically correct or an exact synonym.
Vietnamese five-token entries are routed to review because the source has an unusually high five-token concentration; likely sentence/context words and Chinese action/context markers are also routed to review.
A separate fixed-seed sample of 15 lexical candidates per language exposed residual contextual fragments and noisy strings. Several clear examples were moved into review; this sample does not estimate the full semantic error rate.
Review records retain their source references and reasons. Excluded records are limited to mechanically identifiable formatting/empty/control problems.

## Aligned concepts

- Input records: 856
- JSON/schema validation: passed; no malformed row was skipped.
- Exact normalized VI/EN/ZH triples after merge: 839
- Exact-triple duplicate groups: 17
- Redundant source rows merged: 17
- ICD-bearing canonical records, all unverified: 155
- Label collision groups after exact-triple merge by language: {"en": 6, "vi": 10, "zh": 12}
- Only exact triples are merged. Partial language collisions remain separate and are marked ambiguous for that language.
- No source/license fields were present in the aligned file; the output records this as unknown/missing.

## Sample external IDs

- Records: 8; rejected external IDs: 2; pending external ID review: 6.
- JSON/schema validation: passed; no malformed row was skipped.
- Rejected IDs are not deleted from the source; their records are retained in the review output and cannot be used as anchors.
- Every alias relation remains unverified. ASCII aliases are marked language-unknown when script alone cannot establish language.

## Local seed comparison

- Seed concepts compared: 12
- Exact label triples: 5; partial overlaps: 2; single/no overlap: 5.
- This is a label overlap report, not a semantic-equivalence decision.

## Examples routed to review

### vi
- bệnh cao hơn một chút — five_token_window_shape_requires_review, known_fragment_or_nonmedical_sample, possible_sentence_suffix; source line(s): 2746.
- bệnh gan và một số — five_token_window_shape_requires_review, known_fragment_or_nonmedical_sample, possible_sentence_suffix; source line(s): 9745.
- bệnh loãng xương xem thêm — five_token_window_shape_requires_review, known_fragment_or_nonmedical_sample, possible_sentence_suffix; source line(s): 14973.
- thuốc yêu quý — known_fragment_or_nonmedical_sample; source line(s): 115413.
- bệnh viện e trong tình — five_token_window_shape_requires_review, organization_or_provider_candidate; source line(s): 46178.
- chứng như tay yếu — known_fragment_or_nonmedical_sample, possible_context_word; source line(s): 68406.
- thuốc ông nguyễn văn — known_fragment_or_nonmedical_sample, possible_context_word; source line(s): 115455.
- thuốc trước khi đoàn — known_fragment_or_nonmedical_sample; source line(s): 112102.
- bệnh gout bệnh gout — known_fragment_or_nonmedical_sample; source line(s): 10259.
- chứng và hậu quả — known_fragment_or_nonmedical_sample; source line(s): 72119.

### en
- anthrax meningitisg01 — possible_code_glued_to_label; source line(s): 934.
- meningococcal meningitisg01 — possible_code_glued_to_label; source line(s): 7764.
- tuberculous meningitisg01 — possible_code_glued_to_label; source line(s): 12348.
- fat — generic_or_broad_phrase; source line(s): 4837.
- inflammatory disorder — generic_or_broad_phrase; source line(s): 6463.

### zh
- 不算糖尿病 — negation_or_context_candidate; source line(s): 431.
- 指责孩子 — known_nonmedical_sample; source line(s): 10586.
- 的指责孩子 — known_nonmedical_sample, possible_sentence_prefix; source line(s): 15167.
- 年的慢性咽炎 — possible_sentence_prefix; source line(s): 8337.
- 节和肌肉疼痛 — possible_sentence_prefix; source line(s): 18443.
- 达到止痛 — possible_sentence_or_action_prefix, possible_sentence_or_context_phrase; source line(s): 19827.
- 如肉样瘤病 — possible_sentence_or_action_prefix; source line(s): 6912.
- 克抄枣仁 — known_nonmedical_sample; source line(s): 2688.
- 么是小儿重症 — possible_context_phrase; source line(s): 1023.
- 妈要控制好病 — known_nonmedical_sample; source line(s): 6999.

## Validation and use limits

- Converter checks every source row/ID is represented, JSONL outputs parse, canonical IDs are unique, source hashes are unchanged, and normalized terms have no duplicate output keys.
- Automated rules cannot validate translations, medical correctness, ICD version/mapping, ontology hierarchy, or source license.
- Do not load these candidates as production medical anchors or term dictionaries until review and separate test20k ablation are approved.
