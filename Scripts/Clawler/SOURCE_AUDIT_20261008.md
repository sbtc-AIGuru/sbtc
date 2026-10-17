# Source failure audit — 2026-10-08

Scope: only the current baseline and `.backfill/large_ranges_20261007`. No older corpus or job history was used. The campaign ledger snapshot has 33 of 52 hostnames with 6,874 unresolved records; its last journal update was 2026-10-07 22:42 +07:00. Probe results below are separate diagnostics, not ingested campaign results.

The final per-row probe union contains 47 distinct rows across 25 additional sources: 1 invalid_url, 8 unsupported_content, 4 access_denied, 29 success, 1 robots_denied, 4 server_error.

These are a bounded regression sample, not a whole-source success guarantee. Some rows were rechecked after fixing errors discovered in the first pass. Tests and HTML fixtures are used separately to verify unchanged behavior.

| Source | Unresolved in ledger | Live sample outcomes | Resolution / remaining cause |
|---|---:|---|---|
| `baolangson.vn` | 854 | 1 robots_denied | Robots disallow verified; retain permanent robots_denied. |
| `baoangiang.com.vn` | 778 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `baothanhhoa.vn` | 770 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `bachmai.gov.vn` | 766 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `baotayninh.vn` | 766 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `health.people.com.cn` | 710 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `baogialai.com.vn` | 695 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `baoquangninh.vn` | 636 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `tamanhhospital.vn` | 330 | Prior live sample: 1 success | Previously repaired configured title/body extraction; one live HTTP sample verified. Broader templates still require a campaign rerun. |
| `qihuangzhishu.com` | 213 | 3 success | Explicit chapter title/body; short Chinese headings remain valid. |
| `baophutho.vn` | 162 | 3 success | Decoded browser layout; retain HTTP first and browser fallback for encoded JavaScript content. |
| `dantri.com.vn` | 63 | 3 success | Magazine templates and source image-alt headings; article text retained. |
| `baochinhphu.vn` | 32 | 3 success | Redirected policy subsite layout. |
| `article.iiyi.com` | 19 | 3 server_error | HTTP 521 verified; server outage remains external; source backoff. |
| `nhathuoclongchau.com.vn` | 10 | 2 success | Scope validation to the article container; nested product cards excluded from body candidates. |
| `suckhoeviet.org.vn` | 9 | 2 success, 1 unsupported_content | Magazine tables/text supported; image-only article needs OCR. |
| `baodanang.vn` | 8 | 1 access_denied | HTTP 403 verified; source cooldown/backoff. |
| `baohaiphong.vn` | 8 | 1 access_denied | HTTP 403 verified; source cooldown/backoff. |
| `baonghean.vn` | 8 | 1 access_denied | HTTP 403 verified; source cooldown/backoff. |
| `benhvienvietduc.org` | 7 | 1 server_error | HTTP timeout/502 verified; service unavailable during probes. Its extraction layout could not be confirmed live. |
| `pmc-ecm-healthblog.beta.pharmacity.io` | 7 | 1 access_denied | HTTP 403 verified; source cooldown/backoff. |
| `baocantho.com.vn` | 4 | 2 unsupported_content, 1 success | Magazine text supported; image-only infographic needs OCR. |
| `benhviennhitrunguong.gov.vn` | 3 | 3 unsupported_content | Video-only records need transcription; link-only record requires separate extraction. |
| `youmed.vn` | 3 | 3 success | XML controls removed; medical comparisons preserved. |
| `ask.familydoctor.com.cn` | 2 | 2 success | Verified canonical question hostname; original identity/quota retained; browser fallback verified. |
| `gan.39.net` | 2 | 2 success | Legacy .artCon template. |
| `wei.39.net` | 2 | 2 success | Legacy .artbox .article template. |
| `yanglao.familydoctor.com.cn` | 2 | 1 success | Original protocol/server redirect and #viewContent layout. |
| `baoquangtri.vn` | 1 | 1 unsupported_content | Sample is an image-only infographic; OCR needed. |
| `baovinhlong.com.vn` | 1 | 1 unsupported_content | Sample is an image-only infographic; OCR needed. |
| `heart.39.net` | 1 | 1 success | Medical comparison text no longer swallowed by the cleaner. |
| `suckhoecongdongonline.vn` | 1 | 1 invalid_url | Source record is a homepage; invalid article URL, zero fetches. |
| `woman.39.net` | 1 | 1 success | Legacy .article_title/.article_cur template. |

## Implementation

- `site_configs.py` and `quality.py`: explicit alternate magazine, older Chinese, question, redirect and rendered layouts; media/reference classification.
- `http_strategy.py`: preserve source image-alt headings and remove invalid XML controls before parsing.
- `verbatim.py`: remove actual HTML tags while preserving medical less-than/greater-than comparisons.
- `fetch.py` and `fetch_policy.py`: canonical routing with original source quotas, metadata, server-error handling and growing denial/outage cooldown.
- `backfill.py`: retry-only scheduling and request attribution; existing batch durability remains in place.

## Resume

```bash
source .venv/bin/activate
python Scripts/Clawler/backfill.py run --campaign .backfill/large_ranges_20261007 --retry-only --max-rounds 4
```

This retries recorded recoverable failures. It returns at cooldown by default; `--wait-for-retries` keeps waiting. Remove `--retry-only` for the complete existing manifest. Permanent failures and unprocessed pending rows remain explicit in the report. The 10 large gaps in this campaign do not include every small gap.

## Verification

- 133 unittest regressions passed in the project `.venv`, including real loopback HTTP/Chromium, article validation, canonical source attribution, retry-only scheduling, cooldowns, cancellation and batch recovery.
- Python compileall and scoped git diff checks passed. Upstream Crawl4AI still emits sqlite ResourceWarning messages under Python 3.14.

## Limits

- Robots/403/521/502/transport outages were not bypassed. Server availability cannot be repaired in this repository.
- OCR, video transcription and external-reference extraction are not implemented. Those rows remain failures with specific reasons rather than empty successful text.
- Earlier successful output is not retroactively repaired by the text-cleaner fix; that requires original content or a separately scoped recrawl.
- Baseline JSONL, Parquet, campaign journal and ledger were not modified by these probes.
