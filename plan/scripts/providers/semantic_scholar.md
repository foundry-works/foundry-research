# Provider: Semantic Scholar

## Modes

### Keyword Search
```bash
python search.py --provider semantic_scholar \
  --query "transformer efficiency" \
  --limit 5 --year-range 2023-2026 \
  --fields-of-study "Computer Science" \
  --min-citations 10 --sort citationCount:desc
```

### Forward Citations (who cited this paper)
```bash
python search.py --provider semantic_scholar --cited-by <paper_id_or_doi> --limit 20
```

### Backward References (what this paper cites)
```bash
python search.py --provider semantic_scholar --references <paper_id_or_doi> --limit 20
```

### Paper Recommendations (similar papers)
```bash
python search.py --provider semantic_scholar --recommendations <paper_id_or_doi> --limit 10
```

### Author Search
```bash
python search.py --provider semantic_scholar --author "Yoshua Bengio" --limit 20 --sort citationCount:desc
```

## API Endpoints

| Endpoint | URL | Purpose |
|----------|-----|---------|
| Paper search | `GET /paper/search?query=...&fields=paperId,title,abstract,authors,citationCount,year,externalIds,url,openAccessPdf,tldr,venue&limit=N` | Keyword search |
| Forward citations | `GET /paper/{id}/citations?fields=...&limit=N` | Who cited this paper |
| Backward references | `GET /paper/{id}/references?fields=...&limit=N` | What this paper cites |
| Recommendations | `GET /recommendations/v1/papers/forpaper/{id}?fields=...&limit=N` | Similar papers |
| Author search | `GET /author/search?query={name}&fields=authorId,name,paperCount,citationCount,hIndex` | Find author |
| Author papers | `GET /author/{id}/papers?fields=...&limit=N` | Author's papers |

**Base URL:** `api.semanticscholar.org/graph/v1`

**Auth:** Optional `x-api-key: $SEMANTIC_SCHOLAR_API_KEY` header. Rate limit: 1 RPS.

**Paper ID formats:** Semantic Scholar ID, DOI (`DOI:10.1234/...`), arXiv ID (`ARXIV:2401.12345`), PMID (`PMID:38000001`).

## Output Fields

Standard PAPER_SCHEMA fields plus:
- `tldr`: auto-generated summary
- `is_open_access`: boolean
- `cited_by_percentile`: citation impact percentile (when available from cross-ref with OpenAlex)

## Deduplication

Results from Semantic Scholar often overlap with OpenAlex. Deduplicate by normalized DOI via `_shared/doi_utils.py`.
