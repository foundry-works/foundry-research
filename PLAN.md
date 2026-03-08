# Plan: Deep Research Skill Improvements (Round 2)

**Source:** `deep-research-uncanny-valley/REFLECTION.md` (session score: 6.8/10)
**Supersedes:** Previous PLAN.md (round 1 SKILL.md changes — most already applied)
**Goal:** Fix infrastructure bugs and strengthen SKILL.md guidance to raise baseline session quality.

---

## Part 1: Bug Fixes (Infrastructure & Process Efficiency)

Code changes in `skills/deep-research/scripts/`. These directly caused the Infrastructure score of 5/10 and Process Efficiency score of 6/10.

### 1.1 Fix silent `_sync_to_state` failures in download.py

**Problem:** After downloading a source, `_sync_to_state()` calls `state.py update-source` via subprocess to record `content_file` in the DB. But it never checks the response — not the exit code, not the JSON body. Since all commands exit 0 (errors conveyed in the JSON envelope per `_shared/output.py`), failures are completely invisible. This caused 55 of 58 downloaded files to have no `content_file` in state.db, making `audit` and `download-pending` unreliable.

**Root cause:** `subprocess.run(cmd, capture_output=True, timeout=5)` at `download.py:111` — output is captured but discarded. Confirmed by investigation: even when `state.py update-source` returns `{"status": "error", "errors": ["Source src-210 not found"]}`, exit code is 0 and nothing is logged.

**Fix:**
- Parse the JSON response from stdout after the subprocess call
- Check for `"status": "error"` in the response
- Log warnings on failure with source_id and error details
- This is diagnostic logging only — the download itself succeeded, only the DB sync failed

**Files:** `scripts/download.py` — `_sync_to_state` function (~lines 74-116)

### 1.2 Fix `download-pending` to check disk, not just DB

**Problem:** `cmd_download_pending` queries `WHERE content_file IS NULL AND pdf_file IS NULL` to find sources needing download. But since bug 1.1 means `content_file` is often NULL even when files exist on disk, this re-downloads sources that already have content — wasting time, API calls, and rate limit budget.

**Fix:**
- After the DB query, filter out sources where `sources/{id}.md` or `sources/{id}.pdf` exists on disk
- Use the same logic `audit` already uses at lines 1009-1014
- Log how many were filtered ("N sources already on disk, skipping")
- This makes `download-pending` correct even when the DB is out of sync (defense in depth)

**Files:** `scripts/state.py` — `cmd_download_pending` function (~lines 860-891)

### 1.3 Record ingested count in searches table

**Problem:** `search.py` logs `total_results` from the provider response to the `result_count` column — but this is the API's total matching count (e.g., Semantic Scholar returns 9,088 for a broad query). Only 20 results were actually ingested (because `--limit 20`). This makes efficiency metrics in `audit` misleading: "152 sources from 12,966 results" looks like 1.2% efficiency when real ingestion was much higher.

**Fix:**
- Add `ingested_count INTEGER` column to `searches` table schema (with `ALTER TABLE` migration for existing DBs)
- In `search.py _log_search_to_state`, pass `len(result.get("results", []))` as `--ingested-count`
- In `state.py cmd_log_search`, accept and store the new column
- Keep `result_count` as API total — it's useful signal for spotting unfocused queries

**Why both columns:** The API total tells you how broad your query was (helps diagnose unfocused searches). The ingested count tells you what you actually got (needed for efficiency metrics). Dropping either loses signal.

**Files:** `scripts/state.py` (schema + `cmd_log_search` + `cmd_searches` output), `scripts/search.py` (`_log_search_to_state`)

### 1.4 Scale `download-pending --auto-download` timeout with batch size

**Problem:** `_auto_download_pending` has a hardcoded 600-second (10 min) timeout. With 149 sources, each DOI cascade can take 5-15 seconds across 6 providers, so 149 × ~10s ≈ 25 minutes needed. The timeout kills the download subprocess mid-run.

**Fix:**
- Calculate timeout dynamically: `max(600, len(batch) * 30)` seconds
- Add `--timeout` flag to `download-pending` parser for manual override
- Log the calculated timeout so the operator can plan accordingly

**Files:** `scripts/state.py` — `_auto_download_pending` (~line 935) and parser (~line 1359)

---

## Part 2: SKILL.md Guidance Improvements (Search Strategy & Process)

Changes to `skills/deep-research/SKILL.md`. These address Search Strategy (6/10) and Process Efficiency (6/10) by giving the agent better decision-making principles. Each change explains not just the what and how, but **why** — so the agent internalizes the principle rather than just following a rule.

### 2.1 Add citation chasing guidance

**Problem:** The session ran 7 first-round keyword searches in parallel but never used `--cited-by`, `--references`, or `--recommendations`. After identifying Kätsyri (2015) and MacDorman (2016) as seminal papers, citation traversal would have found the active research network with higher precision than more keyword searches.

**What to add:** New paragraph after "Iterative search across multiple providers" explaining citation chasing as a second-round strategy. Must include:
- **Why it works:** Citation networks have higher precision than keyword search because relevance is pre-filtered by the citing/cited authors — a paper that cites Kätsyri 2015 is almost certainly about the uncanny valley, whereas a keyword match for "uncanny valley cross-cultural" pulls in food science papers.
- **When to trigger:** After identifying 2-3 key/seminal papers in initial results.
- **How to scope:** `--cited-by PAPER_ID --limit 10`, `--references PAPER_ID --limit 10`.

### 2.2 Expand query refinement guidance

**Problem:** All 7 searches were first-round queries with no refinement. One returned 9,088 results. The existing SKILL.md says "Broad initial queries narrow based on what emerges" but doesn't explain the feedback loop.

**What to add:** Expand the "Search query crafting" subsection with:
- **Why refinement matters:** Treating search as a one-shot misses the feedback loop. Initial results reveal the field's actual terminology (e.g., discovering that "realism inconsistency" is the accepted term, not "appearance mismatch"), which makes follow-up queries far more precise.
- **Concrete technique:** Use terminology discovered in round 1 papers to craft round 2 queries. Combine broad concept terms with specific methodological terms from key papers.

### 2.3 Strengthen journal.md guidance

**Problem:** The session's journal was 200 words — too brief to capture reasoning. No mid-session strategy adjustments, no contradiction analysis, no decision points logged.

**What to add:** Expand "journal.md captures reasoning" into a substantive paragraph with:
- **Why it matters:** journal.md is the agent's persistent memory. During long sessions, context compression erases reasoning traces. Without journal entries, the agent loses track of what it tried, what worked, and why it pivoted — leading to repeated searches and missed contradictions.
- **What to log:** Strategy decisions ("pivoting to targeted searches for Q3"), emerging patterns ("three papers converge on perceptual mismatch"), contradictions ("Kätsyri challenges MacDorman's framing"), coverage assessments ("Q6 has 1 source, need follow-up").
- **Minimum bar:** 500+ words across a full session.

---

## Sequencing

```
Phase 1 (bug fixes — can be parallelized):
  1.1  Fix _sync_to_state error handling
  1.2  Fix download-pending disk check
  1.3  Add ingested_count column
  1.4  Scale download timeout

Phase 2 (SKILL.md — do together):
  2.1  Citation chasing guidance
  2.2  Query refinement guidance
  2.3  Journal.md guidance
```

Phases 1 and 2 are independent and could be done in parallel.
