# Provider: Google Scholar

Modeled after [gscholar](https://github.com/venthur/gscholar).

**Includes BibTeX parser** (consolidated from `_shared/bibtex_parser.py`).

## Modes

### Search
```bash
python search.py --provider scholar \
  --query "transformer efficiency pruning" \
  --limit 10 --format bibtex --parse
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` | `bibtex` | Citation format: bibtex, ris, endnote |
| `--parse` | off | Parse BibTeX into structured JSON |

## How It Works

1. **URL:** `GET https://scholar.google.com/scholar?q={url_encoded_query}`
2. **Cookie-based format selection:** Sets `GSP=CF=4` for BibTeX (4=BibTeX, 3=EndNote, 2=RIS)
3. **Cookie capture:** Captures `Set-Cookie` from response and includes in subsequent requests
4. **Citation link extraction:** Parses HTML (BeautifulSoup with regex fallback) to find `scholar.bib?...` links
5. **Citation fetch:** GETs each citation link to retrieve raw citation text
6. **BibTeX parsing (if `--parse`):** Extracts structured fields

## BibTeX Parser (built into this module)

```python
def parse_bibtex(raw: str) -> dict:
    """Parse a BibTeX entry into structured fields.
    - Split entry by newlines
    - Extract entry type and key from @type{key,
    - For each field line matching field = {value} or field = "value":
      - Strip braces/quotes, handle multi-line values
      - Split author field on ' and ' to get author list
    Returns: {title, authors, year, venue, citation_key, entry_type}
    """
```

## Rate Limiting

- Base delay: 2 seconds between requests
- On 429/503: exponential backoff (2s → 4s → 8s → 16s → 30s cap)
- Random jitter: ±0.5s on each delay
- Max retries: 3 per request
- After 3 consecutive failures: abort with partial results + warning

**Auth:** None (scraping). IP-based rate limiting is aggressive — this is for **supplementary search**, not bulk scraping.

## Output Fields

- `raw_citation`: raw BibTeX/RIS/EndNote text
- `parsed` (if `--parse`): {title, authors, year, venue, citation_key, entry_type}

## Limitations & Reliability

- **Best-effort provider** — Scholar aggressively blocks scrapers and serves CAPTCHAs. Even at 0.2 RPS, automated access can be blocked after a few requests from the same IP. This provider should never be the sole source for any research question.
- No official API — scraping can break if HTML changes
- No access to cited-by counts, related articles, or author profiles
- Results may overlap with Semantic Scholar/OpenAlex — dedup by DOI
- **If Scholar fails:** Fall back to Semantic Scholar (best general-purpose academic search) or OpenAlex (broadest coverage). Both have proper APIs and are more reliable. Scholar's unique value is BibTeX export and relevance ranking for vague queries — but Semantic Scholar handles most of these cases adequately.

## When to Use

- Discovery search when you don't know exact terms (Scholar's relevance ranking is excellent)
- Need BibTeX/RIS citations for bibliography
- **Not for bulk operations** — use Semantic Scholar or OpenAlex when you need to retrieve many results reliably
