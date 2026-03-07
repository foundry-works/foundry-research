# Test Plan

Automated tests to run before provider expansion. These cover the reliability-critical paths that manual end-to-end testing won't catch consistently.

## 1. Deduplication (`state.py` + `doi_utils.py`)

| Test case | Input | Expected |
|-----------|-------|----------|
| Exact DOI match | `add-source` with `10.1234/foo`, then again with `10.1234/foo` | Second call returns existing `src-001`, no new entry |
| DOI normalization | `10.1234/FOO` vs `10.1234/foo` | Treated as duplicate |
| DOI prefix stripping | `https://doi.org/10.1234/foo` vs `10.1234/foo` | Treated as duplicate |
| Exact URL match | Same URL with and without trailing slash | Treated as duplicate |
| URL fragment stripping | `example.com/page#section` vs `example.com/page` | Treated as duplicate |
| URL query param stripping | `example.com/page?ref=twitter` vs `example.com/page` | Treated as duplicate |
| arXiv abs vs pdf URL | `arxiv.org/abs/2401.12345` vs `arxiv.org/pdf/2401.12345.pdf` | Treated as duplicate |
| bioRxiv version suffix | `biorxiv.org/content/10.1101/2024.01.01.123456v2` vs `...v1` | Treated as duplicate |
| PMC path variants | `ncbi.nlm.nih.gov/pmc/articles/PMC123/` vs `.../PMC123/pdf/` | Treated as duplicate |
| doi.org resolver URL vs raw DOI | `https://doi.org/10.1234/foo` (as URL) vs `10.1234/foo` (as DOI) | Treated as duplicate |
| Fuzzy title match (above threshold) | "Attention Is All You Need" vs "attention is all you need" | Duplicate (case insensitive) |
| Fuzzy title match (punctuation) | "Attention Is All You Need." vs "Attention Is All You Need" | Duplicate |
| Fuzzy title near threshold | Titles with ~85% token overlap | Duplicate |
| Fuzzy title below threshold | Titles with <85% token overlap | Not duplicate |
| Fuzzy title gray zone — same authors | ~90% title overlap, same authors, same year | Duplicate |
| Fuzzy title gray zone — different authors | ~90% title overlap, different authors | Not duplicate |
| Fuzzy title gray zone — different year | ~90% title overlap, same authors, year differs by >1 | Not duplicate |
| Fuzzy title high confidence | >95% title overlap, different authors | Duplicate (title match alone sufficient) |
| Fuzzy title too short | "Introduction" vs "Introduction" (< 15 chars) | Skipped — not treated as duplicate by fuzzy match |
| Fuzzy title short generic | "Editorial" vs "Editorial" | Skipped — too short for fuzzy matching |
| No DOI, no URL, different titles | Two genuinely different sources | Not duplicate |
| `check-dup` by DOI | Existing source has DOI, `check-dup --doi` | Returns matched source ID |
| `check-dup` miss | DOI not in state | Returns null |

## 2. Rate Limiting (`rate_limiter.py`)

| Test case | Expected |
|-----------|----------|
| Token bucket fills correctly | After N tokens consumed, next request blocks until refill |
| Per-domain isolation | Rate limit on `scholar.google.com` doesn't affect `api.semanticscholar.org` |
| Burst allowance | Fresh bucket allows burst up to capacity |
| Refill timing | Tokens replenish at configured rate |
| Cross-invocation state | Two sequential `python search.py` calls respect shared rate state |

## 3. Metadata Normalization (`metadata.py`)

| Test case | Input | Expected |
|-----------|-------|----------|
| Author name formats | `"Vaswani, A."`, `"Ashish Vaswani"`, `"A Vaswani"` | Normalized consistently |
| Year extraction | `"2023"`, `"2023-01-15"`, `"January 2023"` | All → `2023` |
| DOI in various fields | DOI in `url`, `doi`, `link` fields | Extracted and normalized |
| Missing fields | Source with no authors, no year | Graceful defaults, no crash |
| JSON metadata round-trip | Write metadata JSON → read back | Identical structured output |
| Unicode in titles/authors | Non-ASCII characters | Preserved correctly |

## 4. State Schema & Resumption (`state.py`)

| Test case | Expected |
|-----------|----------|
| Init creates valid state.db | SQLite DB exists, has required tables, schema is correct |
| `set-brief` persists | Brief survives process exit + `summary` reload |
| `log-finding` persists | Finding appears in `summary` output |
| `log-gap` + `resolve-gap` | Gap transitions from open → resolved |
| `summary` output is compact | Output is under 3KB for a 20-source session |
| Concurrent writes | Two rapid `add-source` calls don't corrupt state.db (SQLite WAL handles concurrency) |
| Source ID auto-increment | After `src-003`, next source is `src-004` |
| Empty state summary | `summary` on fresh session doesn't crash |

## 5. HTTP & Error Handling (`http_client.py`)

| Test case | Expected |
|-----------|----------|
| Retry on 429 | Retries with backoff, respects `Retry-After` header |
| Retry on 500/502/503 | Retries up to max attempts |
| No retry on 404 | Returns error immediately |
| Timeout handling | Returns clean error JSON, not stack trace |
| User-Agent header | Present on all requests |

## 6. Provider Output Format (`search.py`)

| Test case | Expected |
|-----------|----------|
| JSON envelope structure | Every provider returns `{"status": "ok", "results": [...], "errors": [], "total_results": N}` or `{"status": "error", "results": [], "errors": [...], "total_results": 0}` |
| Required result fields | Each result has at minimum: `title`, `url` |
| Empty results | Returns `{"status": "ok", "results": [], "errors": [], "total_results": 0}`, not error |
| Invalid API key | Returns structured error, not stack trace |

## 7. Financial Data (`yfinance` + `edgar` providers) — Phase 2

### yfinance Provider

| Test case | Input | Expected |
|-----------|-------|----------|
| Valid ticker profile | `--provider yfinance --ticker AAPL --type profile` | JSON with `market_cap`, `trailing_pe`, `sector` fields present |
| Invalid ticker | `--provider yfinance --ticker ZZZZZ --type profile` | `{"status": "error"}` with descriptive message, no crash |
| Multi-ticker batch | `--provider yfinance --ticker AAPL,MSFT,GOOG --type profile` | 3 results, 2-second delay between each |
| History data points | `--provider yfinance --ticker AAPL --type history --period 1mo --interval 1d` | ~21 data points, each with open/high/low/close/volume |
| Financials structure | `--provider yfinance --ticker MSFT --type financials --statement income` | 4 periods, `Total Revenue` and `Net Income` keys present |
| Quarterly vs annual | `--frequency quarterly` vs `--frequency annual` | Quarterly returns 4+ periods per year, annual returns 1 |
| Options chain | `--provider yfinance --ticker AAPL --type options` | Both calls and puts DataFrames non-empty |
| None field handling | Profile with fields returning `None` from Yahoo | `None` fields omitted from output, not serialized as `null` |
| Rate limit backoff | Simulate 429 response | Retries with exponential backoff, max 3 attempts |

### EDGAR Provider

| Test case | Input | Expected |
|-----------|-------|----------|
| CIK resolution | `--ticker AAPL` | Resolves to CIK `0000320193` |
| CIK zero-padding | CIK `320193` | Padded to `0000320193` in URLs |
| Unknown ticker | `--ticker ZZZZZ` | Clean error, no crash |
| EFTS full-text search | `--query "artificial intelligence" --form-type 10-K` | Results with `entity_name`, `form_type`, `accession_number` |
| Company filings | `--ticker AAPL --form-type 10-K --limit 3` | 3 filing results, all form type 10-K |
| Accession number lookup | `--accession 0000320193-24-000123` | Single filing result |
| Accession format conversion | Display format ↔ URL path format | Correct conversion both directions |
| XBRL company facts | `--ticker MSFT --type facts --concept Revenues` | Time series of revenue values with fiscal periods |
| Missing concept | `--concept NonExistentConcept` | Error with available concept suggestions |
| User-Agent header | All requests | `User-Agent` header present and non-empty |
| Filing download | `--download` flag | HTML filing converted to Markdown in `sources/`, metadata JSON in `sources/metadata/` |

### Metrics State Tracking

| Test case | Input | Expected |
|-----------|-------|----------|
| Log single metric | `log-metric --ticker AAPL --metric "Trailing P/E" --value "32.5"` | Stored in metrics table |
| Log duplicate metric | Same ticker + metric + period + source twice | Second call updates existing row, no duplicate |
| Different sources same metric | Same metric from yfinance and edgar | Both stored (different source column) |
| Get metrics by ticker | `get-metrics --ticker AAPL` after logging 3 metrics | All 3 returned |
| Get metric across tickers | `get-metric --metric "Trailing P/E"` with 3 tickers logged | All 3 tickers returned |
| Summary includes metrics | `summary` after logging metrics | Metrics section appended to output |
| Metric with period | `--period "FY2025"` vs `--period "TTM"` | Both stored separately |

## Running Tests

Tests should be runnable with:
```bash
python -m pytest tests/ -v
```

Use mocked HTTP responses (e.g., `responses` or `pytest-httpserver`) for provider tests to avoid hitting live APIs in CI. Live API tests can be run separately with a `--live` flag for integration testing.

## Integration Tests (Manual, from `implementation-order.md`)

After automated tests pass, run 4 end-to-end queries:
1. General/technical: "What is WebAssembly and why does it matter?"
2. Comparative: "Compare PostgreSQL vs MySQL for high-write workloads"
3. Academic/CS: "Current state of quantum error correction approaches in 2025-2026"
4. Biomedical: "CRISPR delivery mechanisms for in vivo gene therapy"

Verify:
- Source files on disk (`.md` readable, PDFs openable)
- `state.db` tracks searches and sources, no duplicates (verify via `state.py summary` and `state.py export`)
- Report citations backed by on-disk sources
