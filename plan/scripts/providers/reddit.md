# Provider: Reddit

Uses Reddit's public JSON API — no auth, no OAuth, no API keys needed.

## Modes

### Global Search
```bash
python search.py --provider reddit \
  --query "transformer efficiency inference" \
  --limit 10 --sort relevance --time year
```

### Subreddit-Specific Search
```bash
python search.py --provider reddit \
  --query "quantum error correction" \
  --subreddits MachineLearning physics QuantumComputing \
  --sort top --time year --limit 5
```

### Browse a Subreddit
```bash
python search.py --provider reddit --browse MachineLearning --sort hot --limit 10
```

### Full Post + Comments
```bash
python search.py --provider reddit \
  --post-url "https://www.reddit.com/r/MachineLearning/comments/1rihows/..." \
  --comment-limit 20
```

```bash
python search.py --provider reddit \
  --post-id 1rihows --subreddit MachineLearning --comment-limit 20
```

## API Endpoints

1. **Search:** `GET https://www.reddit.com/search.json?q={query}&sort={sort}&t={time}&limit={limit}`
   - Subreddit-specific: `GET https://www.reddit.com/r/{sub}/search.json?q={query}&restrict_sr=on&...`
2. **Browse:** `GET https://www.reddit.com/r/{sub}/{sort}.json?limit={limit}`
3. **Post details:** `GET https://www.reddit.com/{permalink}.json?limit={comment_limit}`
4. **Comment tree:** Recursively flatten `replies` into nested structure with depth tracking

**Auth:** None. Rate limit: ~10 req/min (use 0.15 RPS = 1 req per ~7 seconds).

## Key Features

- **Full text extraction:** Reddit's JSON API returns complete `selftext` (32K+ chars verified) — no truncation
- **Comment tree with nesting:** Preserves reply structure with depth
- **Link extraction:** Pulls URLs from post text and comments (arXiv papers, GitHub repos, blog posts)

## Output Fields

### Search Results
`id`, `title`, `author`, `subreddit`, `score`, `upvote_ratio`, `num_comments`, `url`, `permalink`, `selftext`, `link_flair_text`, `content_length`

### Post Details
`post` object + `comments` array (nested with depth) + `extracted_links` array

## When to Use

- Real-world experience, practical comparisons
- Community consensus via upvotes
- Supplementary citations (comments link to papers, repos, blog posts)
- Contrarian views and failure cases
- Subreddit-specific: r/MachineLearning, r/science, r/AskScience, etc.
