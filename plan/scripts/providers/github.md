# Provider: GitHub

## Modes

### Search Repos
```bash
python search.py --provider github \
  --query "transformer pruning" --type repos \
  --limit 10 --sort stars --language python --min-stars 50
```

### Search Code
```bash
python search.py --provider github \
  --query "class TransformerPruner" --type code --language python --limit 10
```

### Search Discussions
```bash
python search.py --provider github \
  --query "quantization inference speed" --type discussions --limit 10
```

### Get Repo Details
```bash
python search.py --provider github --repo "huggingface/transformers" --include-readme
```

## API Endpoints

| Endpoint | URL | Auth | Purpose |
|----------|-----|------|---------|
| Repo search | `api.github.com/search/repositories?q={query}` | Optional | Find repos |
| Code search | `api.github.com/search/code?q={query}` | **Required** | Find code |
| Discussions | `api.github.com/search/discussions?q={query}` | Optional | Community Q&A |
| Repo details | `api.github.com/repos/{owner}/{repo}` | Optional | Metadata |
| README | `api.github.com/repos/{owner}/{repo}/readme` | Optional | README (Base64) |

**Auth:** Optional `GITHUB_TOKEN` or `GH_TOKEN`. Without: 10 search req/min, 60 general req/hr. With: 30 search req/min, 5000 general req/hr. Code search **requires** auth.

## Search Qualifiers

Passed in query string: `language:python`, `stars:>100`, `topic:machine-learning`, `pushed:>2025-01-01`, `in:readme,description`, `org:huggingface`.

## Output Fields

### Repos
Standard fields plus: `full_name`, `description`, `stars`, `forks`, `language`, `topics`, `updated_at`, `license`, `open_issues`, `readme_excerpt`

### Code
`repository`, `path`, `url`, `content_excerpt`

### Discussions
`title`, `body`, `url`, `answer`, `comments_count`

## When to Use

- Implementations, benchmarks, tools, datasets
- "What tools exist for X" questions
- Stars/forks as community validation signal
- Paper-repo links (via Papers With Code)
