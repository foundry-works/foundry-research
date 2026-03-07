# Provider: Hacker News

Uses the free Algolia-powered HN Search API — no auth, generous limits.

## Modes

### Search Stories
```bash
python search.py --provider hn \
  --query "transformer efficiency" --type story \
  --limit 10 --sort relevance --days 365
```

### Search Comments
```bash
python search.py --provider hn \
  --query "pytorch vs jax benchmarks" --type comment --limit 20
```

### Full Story + Comments
```bash
python search.py --provider hn --story-id 12345678 --comment-limit 30
```

### Tag Filters
```bash
python search.py --provider hn \
  --query "CRISPR" --tags show_hn --limit 10
```

## API Endpoints

| Endpoint | URL | Purpose |
|----------|-----|---------|
| Search | `hn.algolia.com/api/v1/search?query={q}&tags={type}` | Search by relevance |
| Search by date | `hn.algolia.com/api/v1/search_by_date?query={q}&tags={type}` | Search by recency |
| Item | `hn.algolia.com/api/v1/items/{id}` | Full story + comment tree |

**Auth:** None. Rate limit: ~1 RPS (polite).

### Search Parameters

- `tags`: `story`, `comment`, `show_hn`, `ask_hn`, `front_page` (combinable)
- `numericFilters`: `points>100`, `num_comments>50`, `created_at_i>{unix_timestamp}`
- `hitsPerPage`: results per page (max 1000)

## Implementation Notes

- **HTML stripping:** HN comments contain HTML (`<p>`, `<a>`, `<pre>`, `<code>`). Strip tags, preserve link URLs, convert `<p>` to newlines. Uses `_shared/html_extract.py`.
- **Link extraction:** Story `url` field + links within comments (arXiv papers, GitHub repos, blog posts).

## Output Fields

### Search
`id`, `title`, `author`, `url`, `points`, `num_comments`, `created_at`, `story_text`, `hn_url`

### Story Details
`story` object + `comments` array (nested with depth + children) + `extracted_links` array

## When to Use

- Expert commentary on papers (many ML/CS researchers comment on HN)
- Higher signal than Reddit for technical topics
- Paper discovery, tool/library announcements
- Contrarian/critical takes on paper claims
