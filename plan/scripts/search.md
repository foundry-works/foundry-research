# `search.py` — Unified Search CLI

**Purpose:** Single entry point for all search providers. Replaces 9 separate search scripts with one CLI that routes to provider-specific modules.

## CLI Interface

```bash
python search.py --provider <name> [--query "..."] [--limit N] [--session-dir DIR] [provider-specific flags]
```

### Common Flags (all providers)

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | *required* | Provider name (see table below) |
| `--query` | *conditionally required* | Search query (required unless an identifier flag is used — see below) |
| `--limit` | 10 | Max results |
| `--offset` | 0 | Skip the first N results (for pagination) |
| `--session-dir` | None | Session directory for state integration |

**When `--query` is not required:** Several providers support identifier-based lookups that don't need a query string. When any of these flags are used, `--query` is optional:
- Semantic Scholar: `--cited-by`, `--references`, `--recommendations`, `--author`
- Reddit: `--post-url`, `--post-id`, `--browse`
- Hacker News: `--story-id`
- bioRxiv: `--doi`
- PubMed: `--fetch-pmids`

If neither `--query` nor an identifier flag is provided, `search.py` exits with an error explaining what's needed.

### Provider Names & Key Flags

| Provider | Name | Key provider-specific flags |
|----------|------|-----------------------------|
| Semantic Scholar | `semantic_scholar` | `--cited-by`, `--references`, `--recommendations`, `--author`, `--year-range`, `--fields-of-study`, `--min-citations`, `--sort` |
| OpenAlex | `openalex` | `--year-range`, `--open-access-only`, `--sort` |
| arXiv | `arxiv` | `--categories`, `--category-expr`, `--sort`, `--days`, `--download`, `--to-md` |
| PubMed | `pubmed` | `--cited-by`, `--references`, `--related`, `--mesh`, `--fetch-pmids`, `--year`, `--type`, `--sort`, `--fetch` |
| bioRxiv | `biorxiv` | `--server`, `--days`, `--category`, `--doi` |
| Google Scholar | `scholar` | `--format`, `--parse` |
| GitHub | `github` | `--type`, `--sort`, `--language`, `--min-stars`, `--repo`, `--include-readme` |
| Reddit | `reddit` | `--subreddits`, `--sort`, `--time`, `--browse`, `--post-url`, `--post-id`, `--comment-limit` |
| Hacker News | `hn` | `--type`, `--sort`, `--days`, `--tags`, `--story-id`, `--comment-limit` |

See [provider specs](./providers/) for full API details per provider.

## Output

All providers emit the same JSON envelope to stdout:

```json
{
  "status": "ok",
  "results": [...],
  "errors": [],
  "total_results": N,
  "provider": "semantic_scholar",
  "query": "..."
}
```

On failure: `{"status": "error", "results": [], "errors": ["..."], "total_results": 0, ...}`. Partial failures (some results + some errors) use `"status": "ok"` with a non-empty `errors` array.

### Pagination

When `total_results` exceeds `limit`, Claude can request the next page:

```bash
# First page
python search.py --provider semantic_scholar --query "transformer efficiency" --limit 20
# → {"status": "ok", "results": [...], "total_results": 150, "offset": 0, "limit": 20, "has_more": true}

# Second page
python search.py --provider semantic_scholar --query "transformer efficiency" --limit 20 --offset 20
# → {"status": "ok", "results": [...], "total_results": 150, "offset": 20, "limit": 20, "has_more": true}
```

The output envelope includes `offset`, `limit`, and `has_more` fields. Providers that don't natively support pagination (e.g., Google Scholar) return `has_more: false` regardless.

**Provider pagination support:**

| Provider | Native pagination | Notes |
|----------|------------------|-------|
| `semantic_scholar` | Yes | `offset` param in API |
| `openalex` | Yes | Cursor-based, mapped to offset internally |
| `arxiv` | Yes | `start` param in API |
| `pubmed` | Yes | `retstart` param in ESearch |
| `biorxiv` | Limited | Date-range paging only; `--offset` does client-side skip |
| `scholar` | No | `has_more: false` always; blocked after few requests anyway |
| `github` | Yes | `page` param in API |
| `reddit` | Yes | `after` cursor, mapped to offset internally |
| `hn` | Yes | `page` param in Algolia API |

Result objects contain normalized metadata (title, authors, year, url, doi, etc.) plus provider-specific fields. See `_shared/metadata.py` PAPER_SCHEMA for the normalized fields.

## Provider Registry (`providers/__init__.py`)

```python
PROVIDERS = {
    "semantic_scholar": providers.semantic_scholar,
    "openalex": providers.openalex,
    "arxiv": providers.arxiv,
    "pubmed": providers.pubmed,
    "biorxiv": providers.biorxiv,
    "scholar": providers.scholar,
    "github": providers.github,
    "reddit": providers.reddit,
    "hn": providers.hn,
}
```

Each provider module exports a `search(args) -> dict` function that returns the JSON envelope.

## Implementation

1. Parse common args + detect provider
2. Pass remaining args to provider module's argument parser
3. Provider module handles API calls, pagination, response parsing
4. Provider returns normalized results via `_shared/output.py` envelope
5. If `--session-dir` provided, log search to state via `state.py log-search`

## Error Handling

- Unknown provider → exit 1 with error message listing available providers
- Provider API failure → return partial results + errors array
- Rate limit hit → exponential backoff via `_shared/rate_limiter.py`
- Network failure → return empty results + error

## Dependencies

`_shared/` (config, output, http_client, rate_limiter, doi_utils, metadata, html_extract) + provider modules.
