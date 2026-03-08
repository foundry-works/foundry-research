# Plan Checklist: Deep Research Skill Improvements (Round 2)

## Phase 1: Bug Fixes

### 1.1 Fix silent `_sync_to_state` failures
**File:** `scripts/download.py` — `_sync_to_state` (~line 111)
- [ ] After `subprocess.run()`, decode stdout and parse as JSON
- [ ] Check for `"status": "error"` in parsed response
- [ ] Log warning with source_id and error details on failure
- [ ] Handle `JSONDecodeError` gracefully (log and continue)
- [ ] **Verify:** download a source → confirm `content_file` appears in state.db
- [ ] **Verify:** pass a bad source_id to `_sync_to_state` → confirm warning is logged (not silent)

### 1.2 Fix `download-pending` to check disk
**File:** `scripts/state.py` — `cmd_download_pending` (~line 865-871)
- [ ] After DB query, for each pending source check if `sources/{id}.md` or `sources/{id}.pdf` exists on disk
- [ ] Exclude sources with existing on-disk content from the pending list
- [ ] Log count of filtered sources ("N sources already on disk, skipping")
- [ ] **Verify:** create source with NULL content_file in DB but existing .md on disk → excluded from pending

### 1.3 Record ingested count in searches table
**File:** `scripts/state.py` — schema, `cmd_log_search`, `cmd_searches`
- [ ] Add `ingested_count INTEGER` column to `searches` in `_SCHEMA`
- [ ] Add `ALTER TABLE searches ADD COLUMN ingested_count INTEGER` migration in schema setup (wrapped in try/except for existing DBs)
- [ ] Add `--ingested-count` argument to `log-search` parser
- [ ] Store `ingested_count` in `cmd_log_search` INSERT statement
- [ ] Include `ingested_count` in `cmd_searches` SELECT output

**File:** `scripts/search.py` — `_log_search_to_state`
- [ ] Compute `len(result.get("results", []))` as the ingested count
- [ ] Pass `--ingested-count` to the `state.py log-search` subprocess call

**Audit integration (optional, do if straightforward):**
- [ ] If audit calculates efficiency, use `ingested_count` instead of `result_count`

- [ ] **Verify:** run a search with `--limit 20` → confirm DB has `result_count` = API total AND `ingested_count` = 20

### 1.4 Scale download timeout with batch size
**File:** `scripts/state.py` — `_auto_download_pending` (~line 935) and parser (~line 1359)
- [ ] Replace `timeout=600` with `max(600, len(batch) * 30)`
- [ ] Add `--timeout` flag to `download-pending` parser
- [ ] If user passes `--timeout`, use that value; otherwise use dynamic calculation
- [ ] Log the timeout: `f"Downloading {len(batch)} sources (timeout: {timeout}s)"`
- [ ] **Verify:** batch of 5 → 600s; batch of 50 → 1500s; `--timeout 120` → 120s

---

## Phase 2: SKILL.md Guidance

**File:** `skills/deep-research/SKILL.md`

### 2.1 Add citation chasing guidance
- [x] Add new paragraph after "Iterative search across multiple providers"
- [x] Explain **why** citation networks beat keyword search (pre-filtered relevance)
- [x] Explain **when** to trigger (after finding 2-3 key papers)
- [x] Explain **how** (`--cited-by`, `--references`, `--recommendations` with `--limit 10`)
- [x] Include concrete example to make it tangible

### 2.2 Expand query refinement guidance
- [x] Expand existing "Search query crafting" subsection
- [x] Explain **why** refinement matters (search is a dialogue; round 1 reveals the field's terminology)
- [x] Add technique: use terms from round 1 papers in round 2 queries
- [x] Add technique: combine broad concepts with specific methodological terms

### 2.3 Strengthen journal.md guidance
- [x] Expand "journal.md captures reasoning" paragraph
- [x] Explain **why** it matters (persistent memory survives context compression; without it the agent repeats work)
- [x] List specific things to log: strategy pivots, emerging patterns, contradictions, coverage gaps
- [x] Set minimum bar: 500+ words for a full session
- [x] Add 2-3 example journal entries to make the expectation concrete

---

## Post-Flight

- [ ] Re-read SKILL.md for internal consistency (no contradictions between sections)
- [ ] Run `state init` + `search` + `download` to smoke-test bug fixes
- [ ] Confirm `audit` output reflects accurate download counts
- [ ] Commit with descriptive message referencing the reflection
