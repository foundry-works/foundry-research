# Provider: PubMed / NCBI E-utilities

Modeled after [pubmed-cli](https://github.com/drpedapati/pubmed-cli) (Go — reimplemented in Python).

## Modes

### Search
```bash
python search.py --provider pubmed \
  --query "CRISPR gene therapy clinical trials" \
  --limit 20 --sort relevance \
  --year 2022-2026 --type review --fetch
```

### Fetch by PMIDs
```bash
python search.py --provider pubmed --fetch-pmids 38000001 38000002 38000003
```

### Forward Citations
```bash
python search.py --provider pubmed --cited-by 38000001 --limit 20
```

### Backward References
```bash
python search.py --provider pubmed --references 38000001 --limit 20
```

### Related Articles (with relevance scores)
```bash
python search.py --provider pubmed --related 38000001 --limit 10
```

### MeSH Term Lookup
```bash
python search.py --provider pubmed --mesh "fragile x syndrome"
```

## API Endpoints

| Endpoint | URL | Purpose | Response |
|----------|-----|---------|----------|
| **ESearch** | `esearch.fcgi?db=pubmed&term={query}&retmode=json&retmax={limit}&sort={sort}` | Search → PMIDs | JSON: PMID list + count + query translation |
| **EFetch** | `efetch.fcgi?db=pubmed&id={pmids}&rettype=xml&retmode=xml` | PMIDs → full article details | PubmedArticleSet XML |
| **ELink** | `elink.fcgi?dbfrom=pubmed&db=pubmed&id={pmid}&linkname={type}&retmode=json` | Citation graph | JSON: linked PMIDs + scores |
| **ESummary** | `esummary.fcgi?db=mesh&id={mesh_id}&retmode=json` | MeSH term details | JSON: term metadata |

**Base URL:** `eutils.ncbi.nlm.nih.gov/entrez/eutils`

**Auth:** Optional `NCBI_API_KEY`. Rate limit: 3 RPS without key, 10 RPS with.

### ELink Types

- `pubmed_pubmed_citedin` → forward citations (cited-by)
- `pubmed_pubmed_refs` → backward references
- `neighbor_score` (via `cmd` param) → related articles with relevance scores

## Implementation Notes

- **XML parsing (EFetch):** `xml.etree.ElementTree` on `PubmedArticleSet`
  - Handle structured abstracts: `<AbstractText Label="BACKGROUND">...</AbstractText>`
  - Extract DOI and PMCID from `<ArticleIdList>`
  - Strip embedded XML/HTML tags from titles and abstracts
  - Handle author variants: individual (LastName/ForeName) vs collective (CollectiveName)
  - Date extraction: prefer `<Year>`, fall back to `<MedlineDate>` with regex
- **Year range:** Append `AND {start}:{end}[dp]` to query
- **Publication type:** Append `AND "{type}"[pt]` — maps shorthand: `review` → `"review"[pt]`, `trial` → `"clinical trial"[pt]`
- **Rate limiting:** Retry on HTTP 429 with exponential backoff (700ms base, 4s cap, 2 retries). Respect `Retry-After` header.

## Output Fields

Standard PAPER_SCHEMA fields plus:
- `pmid`: PubMed ID
- `pmcid`: PMC ID (for free full-text PDF access)
- `journal`, `journal_abbrev`, `volume`, `issue`, `pages`
- `abstract_sections`: structured abstract parts (BACKGROUND, METHODS, RESULTS, CONCLUSIONS)
- `publication_types`: ["Journal Article", "Review", "Clinical Trial", etc.]
- `mesh_terms`: [{"descriptor": "...", "major_topic": true, "qualifiers": [...]}]
- `pmc_url`: direct PMC URL when PMCID available
- `query_translation`: PubMed's MeSH-expanded query

## When to Use

- Biomedical, clinical, life science research
- MeSH-controlled vocabulary search
- Structured abstracts (BACKGROUND/METHODS/RESULTS/CONCLUSIONS)
- Citation graph with relevance scores
- PMCIDs for free full-text PDF downloads via `download.py`
