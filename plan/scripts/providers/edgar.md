# Provider: SEC EDGAR

## Modes

### Full-Text Search (EFTS)
```bash
python search.py --provider edgar \
  --query "artificial intelligence risk factors" \
  --form-type 10-K --limit 10 \
  --year 2024-2026
```

### Company Filings
```bash
python search.py --provider edgar \
  --ticker AAPL --form-type 10-K,10-Q \
  --limit 5
```

### Specific Filing by Accession Number
```bash
python search.py --provider edgar \
  --accession 0000320193-24-000123
```

### Company Facts (XBRL Structured Data)
```bash
python search.py --provider edgar \
  --ticker MSFT --type facts \
  --concept RevenueFromContractWithCustomerExcludingAssessedTax
```

### Company Concept Time Series
```bash
python search.py --provider edgar \
  --ticker NVDA --type concept \
  --taxonomy us-gaap --concept Revenues
```

## API Endpoints

All SEC EDGAR APIs are **free, public, and require no authentication** — only a valid `User-Agent` header identifying the requester.

| Endpoint | URL | Purpose | Response |
|----------|-----|---------|----------|
| **EFTS Full-Text** | `efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt={start}&enddt={end}&forms={type}` | Full-text search across all filings | JSON: hits with filing metadata |
| **Company Search** | `efts.sec.gov/LATEST/search-index?q=&dateRange=custom&entityName={name}&forms={type}` | Find company filings | JSON: filing list |
| **Submissions** | `data.sec.gov/submissions/CIK{cik}.json` | All filings for a CIK | JSON: filing history, company metadata |
| **Company Facts** | `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | All XBRL facts for a company | JSON: structured financial data by concept |
| **Company Concept** | `data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json` | Time series for one concept | JSON: values across filings |
| **Filing Document** | `www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}` | Raw filing document | HTML, XML, or text |

**Auth:** None. SEC requires a `User-Agent` header: `"CompanyName AdminContact@company.com"`. Use the value from config (e.g., `"deep-research-skill admin@example.com"`).

**Rate limit:** 10 requests per second. SEC is generous but will block IPs that exceed this without proper User-Agent.

## CLI Flags

| Flag | Required | Values | Default | Purpose |
|------|----------|--------|---------|---------|
| `--query` | Conditional | Search text | — | Full-text search query (required for EFTS mode) |
| `--ticker` | Conditional | Ticker symbol | — | Company lookup (required for company modes) |
| `--form-type` | No | `10-K`, `10-Q`, `8-K`, `DEF 14A`, `S-1`, etc. | — | Filter by form type (comma-separated) |
| `--limit` | No | 1–100 | 10 | Max results |
| `--year` | No | `YYYY` or `YYYY-YYYY` | — | Date range filter |
| `--accession` | No | Accession number | — | Fetch specific filing |
| `--type` | No | `filings`, `facts`, `concept` | `filings` | Data type |
| `--taxonomy` | No | `us-gaap`, `ifrs-full`, `dei` | `us-gaap` | XBRL taxonomy (concept mode) |
| `--concept` | No | XBRL concept name | — | Specific financial concept (concept mode) |
| `--download` | No | flag | false | Download filing document to session sources/ |

## Implementation Notes

### CIK Resolution

Ticker → CIK mapping is required for all `data.sec.gov` endpoints. Two approaches:

1. **Company tickers JSON:** `GET https://www.sec.gov/files/company_tickers.json` — returns all ticker→CIK mappings. Cache locally for session duration.
2. **EDGAR search fallback:** Search EFTS by entity name if ticker lookup fails.

CIK must be **zero-padded to 10 digits** for `data.sec.gov` URLs (e.g., `CIK0000320193` for Apple).

### Full-Text Search (EFTS)

The EFTS API searches the actual text content of filings — not just metadata. This enables queries like "supply chain disruption" across all 10-K risk factors.

Response structure:
```json
{
  "hits": {
    "hits": [
      {
        "_source": {
          "file_num": "001-36743",
          "display_date_filed": "2025-10-31",
          "entity_name": "APPLE INC",
          "file_type": "10-K",
          "file_description": "Annual report",
          "period_of_report": "2025-09-27",
          "accession_no": "0000320193-25-000123"
        }
      }
    ],
    "total": {"value": 150}
  }
}
```

### Company Facts (XBRL)

The Company Facts endpoint returns structured financial data — the same numbers that appear in financial statements, but machine-readable. This is more reliable than `yfinance` for precise figures.

```json
{
  "cik": 320193,
  "entityName": "Apple Inc.",
  "facts": {
    "us-gaap": {
      "RevenueFromContractWithCustomerExcludingAssessedTax": {
        "label": "Revenue from Contract with Customer, Excluding Assessed Tax",
        "units": {
          "USD": [
            {"end": "2024-09-28", "val": 391035000000, "form": "10-K", "fy": 2024, "fp": "FY", "filed": "2024-11-01"},
            {"end": "2024-06-29", "val": 85778000000, "form": "10-Q", "fy": 2024, "fp": "Q3", "filed": "2024-08-02"}
          ]
        }
      }
    }
  }
}
```

### Filing Document Retrieval

Once an accession number is known, retrieve the filing index:
1. `GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession-formatted}/index.json`
2. Parse the index to find the primary document filename (usually the `.htm` file matching the form type)
3. Download the primary document

For `--download` mode:
- HTML filings: extract with BeautifulSoup, convert to Markdown via `_shared/html_extract.py`
- XBRL inline HTML: strip XBRL tags (`ix:*` namespace) before extraction
- Write content to `sources/` and metadata to `sources/metadata/` (same as `download.py` output)

### Accession Number Formatting

SEC uses two formats:
- Display: `0000320193-24-000123`
- URL path: `000032019324000123` (no dashes)

Convert between them as needed per endpoint.

## Output Fields

### Filing Result
```json
{
  "ticker": "AAPL",
  "cik": "0000320193",
  "entity_name": "Apple Inc.",
  "form_type": "10-K",
  "filing_date": "2025-10-31",
  "period_of_report": "2025-09-27",
  "accession_number": "0000320193-25-000123",
  "filing_url": "https://www.sec.gov/Archives/edgar/data/320193/...",
  "description": "Annual report",
  "primary_document": "aapl-20250927.htm"
}
```

### Facts Result
```json
{
  "ticker": "MSFT",
  "cik": "0000789019",
  "entity_name": "Microsoft Corporation",
  "concept": "Revenues",
  "taxonomy": "us-gaap",
  "label": "Revenues",
  "unit": "USD",
  "values": [
    {"period_end": "2025-06-30", "value": 262000000000, "form": "10-K", "fiscal_year": 2025, "fiscal_period": "FY", "filed": "2025-07-29"},
    {"period_end": "2024-06-30", "value": 245000000000, "form": "10-K", "fiscal_year": 2024, "fiscal_period": "FY", "filed": "2024-07-30"}
  ]
}
```

## Rate Limiting

Register domain `efts.sec.gov` and `data.sec.gov` with:
- Capacity: 10 tokens
- Refill rate: 10 tokens/sec
- Burst: 10

SEC is generous at 10 RPS but will IP-ban without proper User-Agent. The `User-Agent` header is mandatory — anonymous requests get 403.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Unknown ticker | CIK lookup returns no results → `{"status": "error", "errors": ["Ticker 'XYZ' not found in SEC EDGAR"]}` |
| 403 Forbidden | Missing or invalid User-Agent header → log warning, do not retry |
| Filing not found | Accession number invalid → clean error |
| XBRL concept not found | Concept name doesn't exist in taxonomy → list available concepts in error message |
| Rate limit (429) | Exponential backoff, 3 retries |

## Deduplication

Filings are keyed by accession number (globally unique). When adding filing sources to `state.py`, use the accession number as a secondary dedup key alongside URL.

## Dependencies

`requests`, `beautifulsoup4` (already in requirements). No additional dependencies needed — SEC APIs return JSON and HTML.

## When to Use

- Precise financial figures (audit-grade accuracy from XBRL)
- Management commentary: risk factors, MD&A sections from 10-K/10-Q
- Insider transactions and institutional ownership (DEF 14A, Form 4)
- IPO prospectuses (S-1) and merger filings (DEFM14A)
- Full-text search across all public filings (unique capability — no other provider offers this)
- Historical financial data going back decades (EDGAR has filings from 1993+)
- Cross-referencing `yfinance` figures with authoritative SEC data

## When NOT to Use

- Quick screening of current price or market cap (use `yfinance` instead)
- Real-time or intraday data (SEC filings are periodic, not live)
- International companies not listed on US exchanges
- Options or derivatives data (use `yfinance`)
