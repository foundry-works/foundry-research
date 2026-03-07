# `enrich.py` — Crossref DOI Metadata Enrichment

**Purpose:** Look up DOIs via Crossref to fill missing bibliographic metadata. Unchanged from original plan.

## CLI Interface

```bash
python enrich.py \
  --doi "10.1038/s41586-020-2649-2" \
  --doi "10.1145/3580305.3599571" \
  --mailto "user@example.com"  # optional, for polite pool (10 RPS vs 1 RPS)
```

## Output

```json
{
  "results": [
    {
      "doi": "10.1038/s41586-020-2649-2",
      "title": "...",
      "authors": ["Author A", "Author B"],
      "year": 2020,
      "venue": "Nature",
      "volume": "584",
      "issue": "7821",
      "pages": "357-362",
      "publisher": "Springer Science and Business Media LLC",
      "abstract": "...",
      "cited_by_count": 15234,
      "type": "journal-article",
      "is_retracted": false,
      "url": "https://doi.org/10.1038/s41586-020-2649-2"
    }
  ],
  "errors": []
}
```

## API

**Endpoint:** `GET api.crossref.org/works/{doi}`

**Auth:** None. User-Agent: `deep-research-skill/1.0 (mailto:{email})` for polite pool.

**Rate limit:** 10 RPS with polite pool, ~1 RPS without.

## Implementation Details

- Parse `date-parts` format: `[[year, month?, day?]]` → year
- Strip JATS XML tags from abstracts: `re.sub(r'<[^>]+>', '', abstract)`
- Titles returned as arrays — take first element
- Check multiple date fields: `published-print`, `published-online`, `issued`
- **Retraction detection:**
  - `update-to` array with `type: "retraction"`
  - `update-policy` field
  - Record `type` is `"retraction"` (retraction notice itself)
- Only fill missing fields (don't overwrite existing data)

## Dependencies

`_shared/` (config, output, http_client, rate_limiter, doi_utils, html_extract).
