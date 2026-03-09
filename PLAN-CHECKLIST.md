# Plan Checklist: Deep Research Skill Improvements (Round 3)

## Phase A: High-Impact Bug Fixes

### 3.1 Fix `tldr` field in Semantic Scholar citation/reference endpoints
**File:** `skills/deep-research/scripts/providers/semantic_scholar.py`
- [x] Add `CITATION_FIELDS` constant (line ~14, same as `PAPER_FIELDS` minus `tldr`)
- [x] Update `_forward_citations` (line 97) to use `CITATION_FIELDS`
- [x] Update `_backward_references` (line 126) to use `CITATION_FIELDS`
- [x] Update `_get_recommendations` (line 155) to use `CITATION_FIELDS`
- [ ] **Verify:** `--cited-by <paper_id>` → HTTP 200 with results
- [ ] **Verify:** `--references <paper_id>` → HTTP 200 with results
- [ ] **Verify:** `--recommendations <paper_id>` → HTTP 200 with results

### 3.2 Reject empty queries in PubMed provider
**File:** `skills/deep-research/scripts/providers/pubmed.py`
- [x] Add empty/whitespace query guard in keyword search path
- [x] Return `error_response(["Query is required..."], error_code="missing_query")`
- [ ] **Verify:** `--query ""` → error response, not results
- [ ] **Verify:** `--query "   "` → error response (whitespace-only)
- [ ] **Verify:** normal `--query "uncanny valley"` still works

---

## Phase B: SKILL.md Gap Tracking

### 3.3 Strengthen gap tracking enforcement
**File:** `skills/deep-research/SKILL.md`
- [x] Revise step 10 — add consequence/rationale for gap logging
- [x] Add "gap-driven refinement" paragraph in "What Good Research Looks Like"
- [x] Keep changes concise — explain the *why*, don't bloat

---

## Phase C: Remaining Round 2 Bug Fixes (already implemented)

### 1.1 Fix silent `_sync_to_state` failures
**File:** `skills/deep-research/scripts/download.py`
- [x] Parse subprocess stdout as JSON after `subprocess.run()`
- [x] Check for `"status": "error"` in parsed response
- [x] Log warning with source_id and error details on failure
- [x] Handle `JSONDecodeError` gracefully (log and continue)

### 1.2 Fix `download-pending` to check disk
**File:** `skills/deep-research/scripts/state.py`
- [x] After DB query, check if `sources/{id}.md` or `sources/{id}.pdf` exists on disk
- [x] Exclude sources with existing on-disk content from pending list
- [x] Log count of filtered sources

### 1.4 Scale download timeout with batch size
**File:** `skills/deep-research/scripts/state.py`
- [x] Replace `timeout=600` with `max(600, len(batch) * 30)`
- [x] Add `--timeout` flag to `download-pending` parser
- [x] Log calculated timeout

---

## Applied (from prior rounds)

- [x] 1.3 Record ingested count in searches table (search.py)
- [x] 2.1 Citation chasing guidance (SKILL.md)
- [x] 2.2 Query refinement guidance (SKILL.md)
- [x] 2.3 Journal.md guidance (SKILL.md)

---

## Post-Implementation

- [ ] Run `./copy-to-skills.sh` to deploy changes to `.claude/`
- [ ] Smoke-test: `state init` → `search --provider semantic_scholar --cited-by <id>` → `download-pending`
- [ ] Verify no regressions in normal keyword search
- [ ] Re-read SKILL.md for internal consistency
