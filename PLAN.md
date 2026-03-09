# Plan: Deep Research Skill Improvements (Round 3)

**Source:** `deep-research-uncanny-valley/REFLECTION.md` (session score: 6.8/10)
**Supersedes:** Previous PLAN.md (round 2 — Phase 2 SKILL.md changes applied, Phase 1 bug fixes still open)
**Goal:** Fix remaining infrastructure bugs and tighten SKILL.md where the agent still deviated despite existing guidance.

---

## Status of Prior Plan Items

### Applied (Round 2, Phase 2)
- 2.1 Citation chasing guidance — added to SKILL.md
- 2.2 Query refinement guidance — expanded in SKILL.md
- 2.3 Journal.md guidance — strengthened in SKILL.md

### Still Open (Round 2, Phase 1)
- 1.1 Fix `_sync_to_state` in download.py — **still broken** (confirmed: 1 source with NULL quality in reflection)
- 1.2 Fix `download-pending` disk check — still open
- 1.3 Record ingested count — **FIXED** in search.py (confirmed in MEMORY.md)
- 1.4 Scale download timeout — still open

---

## New Items from Round 3 Reflection

### 3.1 Fix `tldr` field bug in Semantic Scholar citation/reference endpoints

**Files:** `skills/deep-research/scripts/providers/semantic_scholar.py`

**Problem:** `PAPER_FIELDS` (line 13) includes `tldr`, which is supported by the main `/paper/search` endpoint but causes HTTP 400 on `/paper/{id}/citations`, `/paper/{id}/references`, and the recommendations endpoint. This broke citation chasing entirely — the highest-precision search strategy available. The agent couldn't chase references from Kätsyri (437 cites) or Saygin (435 cites), forcing it into more keyword searches that returned 57% off-topic noise.

**Why this is the highest-impact fix:** Citation chasing has near-zero noise because relevance is pre-filtered by citing/cited authors. A paper that cites Kätsyri (2015) is almost certainly about the uncanny valley; a keyword match for "uncanny valley cross-cultural" pulls in food science. Fixing this single bug addresses both the "citation chasing failed" finding and much of the "off-topic noise" finding from the reflection.

**Fix:** Create a `CITATION_FIELDS` constant without `tldr`:
```python
CITATION_FIELDS = "paperId,title,abstract,authors,citationCount,year,externalIds,url,openAccessPdf,venue,journal"
```
Use it in:
- `_forward_citations` (line 97) — `params = {"fields": CITATION_FIELDS, ...}`
- `_backward_references` (line 126) — same
- `_get_recommendations` (line 155) — same

**Validation:** Run `--cited-by`, `--references`, and `--recommendations` against a known paper ID and confirm HTTP 200 with results.

### 3.2 Reject empty queries in PubMed provider

**File:** `skills/deep-research/scripts/providers/pubmed.py`

**Problem:** A search with an empty query string was accepted and returned 20 essentially random recent papers. This is a silent failure — the agent believes it searched PubMed but got noise instead.

**Fix:** In the keyword search path, check for empty/whitespace-only `args.query` before calling the API. Return:
```python
error_response(["Query is required for PubMed keyword search"], error_code="missing_query")
```

**Why this matters:** Prevents wasted download bandwidth and off-topic contamination. The reflection flagged one PubMed search with an empty query that returned 20 irrelevant results.

**Validation:** `--query ""` and `--query "   "` should both return error responses.

### 3.3 Strengthen gap tracking enforcement in SKILL.md

**File:** `skills/deep-research/SKILL.md`

**Problem:** Step 10 says to log gaps, line 196 says "You **must** call `log-gap`", but the agent logged zero gaps. The guidance exists but the agent skipped it because gap logging felt like bookkeeping rather than a research strategy. The *why* is missing — the agent doesn't understand that gaps drive targeted follow-up searches.

**Fix:** Two changes:
1. **Step 10 in Quick-Start Workflow:** Add a consequence — "gaps logged here drive targeted follow-up searches in the next round; an empty gaps table means the audit can't identify weak coverage areas."
2. **New paragraph in "What Good Research Looks Like":** Explain the gap-driven refinement loop: log gap → targeted search for that specific gap → resolve gap. Frame it as a research strategy, not bookkeeping. Include a concrete example: "After reader agents flag that Q2 has only 1 supporting source, log-gap → search specifically for that subtopic → resolve-gap when coverage improves."

**Why this matters:** Gap tracking is the mechanism for systematic coverage improvement. Without it, weak areas stay weak because the agent has no structured way to identify and address them.

---

## Remaining Open Items from Round 2

### 1.1 Fix silent `_sync_to_state` failures in download.py

(Unchanged from round 2 plan — still needs implementation)

**File:** `scripts/download.py` — `_sync_to_state` function
**Fix:** Parse JSON response from subprocess stdout, check for `"status": "error"`, log warnings on failure.

### 1.2 Fix `download-pending` to check disk, not just DB

(Unchanged from round 2 plan — still needs implementation)

**File:** `scripts/state.py` — `cmd_download_pending`
**Fix:** After DB query, filter out sources where `sources/{id}.md` or `sources/{id}.pdf` exists on disk.

### 1.4 Scale `download-pending --auto-download` timeout with batch size

(Unchanged from round 2 plan — still needs implementation)

**File:** `scripts/state.py` — `_auto_download_pending`
**Fix:** `max(600, len(batch) * 30)` seconds, with `--timeout` flag for manual override.

---

## Sequencing

```
Phase A (high-impact bug fixes — do first):
  3.1  Fix tldr field in Semantic Scholar citation endpoints
  3.2  Reject empty PubMed queries

Phase B (SKILL.md — quick):
  3.3  Strengthen gap tracking enforcement

Phase C (remaining round 2 bugs — independent of A/B):
  1.1  Fix _sync_to_state error handling
  1.2  Fix download-pending disk check
  1.4  Scale download timeout
```

Phases A, B, and C are independent and can be parallelized.
