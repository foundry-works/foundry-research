# Provider: OpenAlex

## Modes

### Keyword Search
```bash
python search.py --provider openalex \
  --query "transformer efficiency" \
  --limit 10 --year-range 2023-2026 \
  --open-access-only --sort cited_by_count:desc
```

## API Endpoints

| Endpoint | URL | Purpose |
|----------|-----|---------|
| Works search | `GET /works?search=...&per_page=N&filter=publication_year:YYYY-YYYY` | Keyword search |
| Work by DOI | `GET /works/doi:{doi}` | Single work lookup |

**Base URL:** `api.openalex.org`

**Auth:** Required `x-api-key: $OPENALEX_API_KEY` header (free key). Rate limit: 50 RPS.

## Implementation Notes

- **Abstract reconstruction:** OpenAlex returns `abstract_inverted_index` (word → position list). Reconstruct plain text in Python — don't waste Claude's tokens on this.
- **Author extraction:** `authorships[].author.display_name`
- **Open access:** Check `is_oa` and extract `open_access.oa_url`
- **Citation percentile:** Extract `cited_by_percentile_year.min` for citation impact context
- **Year range filter:** `filter=publication_year:2023-2026`

## Output Fields

Standard PAPER_SCHEMA fields plus:
- `is_open_access`: boolean
- `oa_url`: open access URL (for download.py)
- `cited_by_percentile`: percentile rank of citation count for year+field
- `topics`: OpenAlex topic classifications
