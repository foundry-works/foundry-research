# Plan Checklist: Tavily CLI Search Provider

## Phase 1: Provider Implementation

### 1.1 Create `providers/tavily.py`
**File:** `skills/deep-research/scripts/providers/tavily.py`
- [ ] `add_arguments(parser)` — register all flags (`--search-depth`, `--topic`, `--include-domains`, `--exclude-domains`, `--urls`, `--extract-depth`, `--include-raw-content`)
- [ ] `search(args)` dispatcher — route to `_search` or `_extract` based on `args.urls`
- [ ] `_search(client, args)` — POST to `/search`, map results to source dicts with `title`/`url`/`abstract`/`type`
- [ ] `_extract(client, args)` — POST to `/extract`, map results, report failures
- [ ] Auth guard — check `TAVILY_API_KEY` env var, return `error_response` if missing
- [ ] Cap `max_results` at 20 with warning log
- [ ] Empty query guard — reject empty/whitespace `args.query` in search mode

### 1.2 Register provider
**File:** `skills/deep-research/scripts/providers/__init__.py`
- [ ] Add `"tavily": "providers.tavily"` to `_REGISTRY`

### 1.3 Verify
- [ ] `search --provider tavily --query "uncanny valley" --limit 5` → JSON with results, `status: ok`
- [ ] `search --provider tavily --query "uncanny valley" --topic news --limit 5` → results with `published_date`
- [ ] `search --provider tavily --urls https://en.wikipedia.org/wiki/Uncanny_valley` → extracted content
- [ ] `search --provider tavily --query ""` → error response, not results
- [ ] Without `TAVILY_API_KEY` set → clear auth error message
- [ ] With active session: verify search logged in `state.db` searches table
- [ ] With active session: verify sources auto-added to `state.db` sources table with `type: web`

---

## Phase 2: SKILL.md Updates

### 2.1 Provider table
**File:** `skills/deep-research/SKILL.md`
- [x] Add `tavily` row to provider table with description and key flags

### 2.2 Quick-Start workflow
- [x] Merge steps 3-4 — remove "SEPARATE batch from academic" workaround
- [x] Web search is now just another `--provider tavily` call, safe to parallelize

### 2.3 Native Tools table
- [x] Remove `Tavily search / WebSearch` row
- [x] Add note that WebSearch remains available as fallback

### 2.4 Parallel search resilience
- [x] Simplify paragraph — CLI-based Tavily eliminates the mixed-batch problem
- [x] Keep general principle about exit 0 for CLI tools

### 2.5 Provider Selection Guidance
- [x] Update `General technical` to reference `--provider tavily`
- [x] Update `When unsure` to reference `--provider tavily`
- [x] Update `Comparative questions` if it mentions Tavily/WebSearch (N/A — doesn't mention it)

---

## Phase 3: Deploy & Smoke Test

- [ ] Run `./copy-to-skills.sh` to deploy to `.claude/`
- [ ] End-to-end: `state init` → `search --provider tavily --query "..."` → verify in `state summary`
- [ ] Parallel test: run tavily + semantic_scholar searches in same batch → both succeed
- [ ] Verify no regressions: existing providers still work (`search --provider semantic_scholar --query "test"`)

---

## History (prior rounds, all complete)

- [x] 1.3 Record ingested count in searches table (search.py)
- [x] 2.1 Citation chasing guidance (SKILL.md)
- [x] 2.2 Query refinement guidance (SKILL.md)
- [x] 2.3 Journal.md guidance (SKILL.md)
- [x] 3.1 Fix `tldr` field in Semantic Scholar citation endpoints
- [x] 3.2 Reject empty queries in PubMed provider
- [x] 3.3 Strengthen gap tracking enforcement in SKILL.md
- [x] 1.1 Fix silent `_sync_to_state` failures in download.py
- [x] 1.2 Fix `download-pending` to check disk
- [x] 1.4 Scale download timeout with batch size
