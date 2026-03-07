# Provider: bioRxiv / medRxiv

## Modes

### Search by Keyword
```bash
python search.py --provider biorxiv \
  --query "CRISPR delivery mechanisms" \
  --server biorxiv \      # biorxiv | medrxiv | both (default: both)
  --limit 20 --days 30
```

### Single Paper by DOI
```bash
python search.py --provider biorxiv --doi "10.1101/2024.01.15.575733"
```

### Browse by Category
```bash
python search.py --provider biorxiv --category neuroscience --days 7 --limit 50
```

## API Endpoints

| Endpoint | URL | Purpose |
|----------|-----|---------|
| Content detail | `api.biorxiv.org/details/{server}/{interval}/{cursor}` | Papers by date range |
| Published links | `api.biorxiv.org/pubs/{server}/{interval}/{cursor}` | Map preprints → published DOIs |
| Paper detail | `api.biorxiv.org/details/{server}/{doi}` | Single paper by DOI |

- `{server}`: `biorxiv` or `medrxiv`
- `{interval}`: date range in `YYYY-MM-DD/YYYY-MM-DD` format
- `{cursor}`: pagination offset (100 results per page)

**Auth:** None. Rate limit: ~1 RPS (polite).

## Implementation Notes

- **No keyword search endpoint** — the bioRxiv API is date-range based only
- **Keyword search delegates to OpenAlex:** When `--query` is provided, route through OpenAlex with `primary_location.source.publisher:Cold Spring Harbor Laboratory` filter (covers both bioRxiv and medRxiv). This gives proper keyword search, citation counts, and OA URLs without client-side filtering hacks
- **Direct API for recency/browse only:** Use the native bioRxiv API for `--category` browsing and `--doi` lookups where date-range access is natural
- **Published version tracking:** `/pubs/` endpoint maps preprint DOIs to their published journal DOIs ("this preprint was later published in Nature as 10.1038/...")

## Output Fields

Standard PAPER_SCHEMA fields plus:
- `server`: "biorxiv" or "medrxiv"
- `category`: e.g. "molecular biology", "neuroscience"
- `version`: preprint version number
- `published_doi`: DOI of peer-reviewed version (if published)
- `published_journal`: journal name (if published)

## When to Use

- Cutting-edge bio/med preprints (weeks-months before PubMed indexing)
- PubMed only indexes published papers, not preprints
- Complements PubMed the same way arXiv complements Semantic Scholar
