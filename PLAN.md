# Plan: Tavily CLI Search Provider

**Source:** `deep-research-uncanny-valley/REFLECTION.md` finding: "Journal mentions Tavily but no Tavily searches appear in state.db — web searches aren't being logged, making them invisible to quality assessment."

**Supersedes:** Previous PLAN.md (round 3 items are complete or tracked in PLAN-CHECKLIST.md history)

---

## Problem

Web searches via Tavily MCP or native WebSearch bypass the CLI `search` pipeline and don't get logged to state.db. This causes:
- Web searches invisible to `audit`, `summary`, and provider diversity metrics
- Agent needs a "SEPARATE batch from academic" workaround in SKILL.md (fragile, often ignored)
- Provider diversity underreported — if 30% of research came from web sources, the audit doesn't know

## Solution

Add `tavily` as a CLI search provider. It hits the Tavily REST API directly, flows through the same `search.py` dispatch → auto-log search → auto-add sources pipeline as academic providers. No special handling, no MCP dependency.

---

## API Reference

**Tavily Search** — `POST https://api.tavily.com/search`
- Auth: `Authorization: Bearer {TAVILY_API_KEY}`
- Body (JSON): `query` (required), `search_depth` (basic|advanced), `max_results` (1-20, default 10), `topic` (general|news), `include_domains` (list), `exclude_domains` (list), `include_raw_content` (bool)
- Response: `{ "query": str, "results": [...], "response_time": float }`
- Result item: `{ "title": str, "url": str, "content": str, "score": float, "raw_content"?: str, "published_date"?: str }`

**Tavily Extract** — `POST https://api.tavily.com/extract`
- Body (JSON): `urls` (required, list of strings), `extract_depth` (basic|advanced)
- Response: `{ "results": [...], "failed_results": [...] }`
- Result item: `{ "url": str, "raw_content": str }`

---

## Implementation

### 1. New file: `skills/deep-research/scripts/providers/tavily.py`

Follow the reddit.py/hn.py pattern:

**`add_arguments(parser)`:**
- `--search-depth` — `basic` (default) or `advanced` (deeper scraping, slower)
- `--topic` — `general` (default) or `news` (enables `published_date`)
- `--include-domains` — nargs="+", restrict to specific domains
- `--exclude-domains` — nargs="+", exclude specific domains
- `--urls` — nargs="+", switch to extract mode
- `--extract-depth` — `basic` (default) or `advanced`, only used with `--urls`
- `--include-raw-content` — include full page content in search results (off by default)

**`search(args)` dispatch:**
```
if args.urls → _extract(client, args)
elif args.query → _search(client, args)
else → error_response("missing_query")
```

**`_search(client, args)` → search mode:**
- POST to `https://api.tavily.com/search`
- Headers: `Authorization: Bearer {api_key}`, `Content-Type: application/json`
- Map `args.limit` → `max_results` (cap at 20, Tavily's max)
- Map results to source dicts:
  ```python
  {
      "title": r["title"],
      "url": r["url"],
      "abstract": r["content"],  # Tavily's AI-extracted snippet
      "type": "web",
      "year": _parse_year(r.get("published_date")),  # news topic only
  }
  ```
- Return via `success_response(results, total_results=len(results), provider="tavily", query=args.query)`

**`_extract(client, args)` → extract mode:**
- POST to `https://api.tavily.com/extract`
- Return extracted content with titles derived from URLs
- Map to source dicts with `type: "web"`
- Include failed URLs in response envelope

**Auth:** Read `TAVILY_API_KEY` from `os.environ`. Return `error_response(["TAVILY_API_KEY environment variable not set"], error_code="auth_missing")` if absent.

**Rate limiting:** `{"api.tavily.com": 1.0}` — conservative default. Tavily allows 100 req/min on production keys, but we're typically I/O-bound on context processing, not API calls.

**Error handling:** Tavily returns standard HTTP errors. Map 401 → `auth_failed`, 429 → `rate_limited`, 4xx/5xx → `api_error`. The `http_client.py` retry logic handles 429/500/502/503 automatically.

### 2. Registry: `skills/deep-research/scripts/providers/__init__.py`

Add one line: `"tavily": "providers.tavily"` to `_REGISTRY`.

### 3. SKILL.md updates

**Provider table** (line ~36): Add row:
```
| `tavily` | Web search, news, non-academic sources | `--search-depth`, `--topic`, `--include-domains`, `--exclude-domains`, `--urls` (extract mode) |
```

**Quick-Start step 3-4** (lines ~17-18): Merge into a single step. Remove the "SEPARATE batch from academic" workaround. Tavily now goes through CLI and is safe to parallelize with academic providers:
```
3. Search providers (parallel OK — use `--provider tavily` for web, academic providers for papers)
```
Remove old step 4 entirely.

**Native Tools table** (line ~133): Remove the `Tavily search / WebSearch` row. Add a note: "WebSearch is available as a fallback if Tavily API key is not configured."

**"Parallel search resilience" paragraph** (line ~155): Simplify — the warning about mixing CLI and web tool calls is no longer needed since Tavily is now CLI-based. Keep the general principle about exit codes.

**Provider Selection Guidance** (line ~210): Update `When unsure` and `General technical` bullets to reference `--provider tavily` instead of "Tavily/WebSearch".

---

## Design Decisions

**Why direct REST instead of tavily Python SDK?** The API is 2 endpoints. `http_client.py` already provides rate limiting, retries, and connection pooling. No new dependency.

**Why include extract mode?** Tavily's AI-powered extraction is often higher quality than basic HTML scraping for complex pages. Having it as `--urls` keeps it in the same provider without a separate tool. The `download` tool's `--url --type web` is still available for non-Tavily extraction.

**Why cap max_results at 20 instead of mapping to --limit directly?** Tavily's API hard-limits at 20. Passing a higher value returns an error. We silently cap and log a warning so the agent doesn't need to remember the limit.

**Why not pass include_raw_content by default?** Raw content per result can be 10-50KB. With 20 results, that's up to 1MB of text loaded into the agent's context via the JSON response. The default `content` field (Tavily's AI-extracted snippet) is sufficient for triage. Full content should be fetched via `download` or `--include-raw-content` on targeted searches.

---

## What doesn't change

- `search.py` — generic dispatch, auto-tracking already handle new providers
- `state.py` — no schema changes; `type: "web"` already supported
- `_shared/` — http_client, output work as-is
- `download.py` — unchanged; web source download via `--url --type web` still works for full content
