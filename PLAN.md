# Refactoring Plan: `skills/deep-research/scripts/`

## 1. Deduplicate Term Extraction in state.py

**Problem:** `cmd_audit()` and `cmd_triage()` both implement stop-word filtering and keyword extraction from research questions with nearly identical code (~50 lines each). A bug fix in one won't reach the other.

**Fix:** Extract a `_extract_question_terms(questions: list) -> list[str]` helper within state.py. Both commands call it instead of inlining the logic.

**Files:** `skills/deep-research/scripts/state.py`

---

## 2. Consistent Subprocess Error Logging

**Problem:** Three files log subprocess failures differently — download.py includes exit code, search.py omits it, state.py uses a third format. When debugging, you have to remember which script logs what.

**Fix:** Add a `log_subprocess_failure(name: str, proc)` helper to `_shared/output.py`. Replace the three inline patterns with calls to it.

**Files:**
- `skills/deep-research/scripts/_shared/output.py` (add helper)
- `skills/deep-research/scripts/download.py` (use helper)
- `skills/deep-research/scripts/search.py` (use helper)
- `skills/deep-research/scripts/state.py` (use helper)

---

## 3. Remove Global Mutable State in enrich.py

**Problem:** `_OC_BATCH_TIMEOUT` is set via `global` from arg parsing. Works for CLI, but is a landmine if enrichment functions are ever called from another module — they'd get stale or unset state.

**Fix:** Pass `timeout` as a parameter to `_enrich_with_opencitations()` and any other functions that read the global. Remove the global variable.

**Files:** `skills/deep-research/scripts/enrich.py`

---

## 4. Canonical Error Codes

**Problem:** Error codes are ad-hoc string literals across providers. Most use `"rate_limited"`, `"auth_failed"`, `"not_found"`, but dblp uses `f"http_{status}"` and edgar mixes `"error"` keys into data dicts. The agent can't handle errors uniformly.

**Fix:** Define canonical error code constants in `_shared/output.py` (simple string constants, not an enum class — keep it lightweight). Update dblp.py and edgar.py to use them. Add a brief comment block listing the valid codes so the contract is explicit.

**Files:**
- `skills/deep-research/scripts/_shared/output.py` (add constants)
- `skills/deep-research/scripts/providers/dblp.py` (use constants)
- `skills/deep-research/scripts/providers/edgar.py` (use constants)

---

## 5. Fix biorxiv Raw Requests Bypass

**Problem:** `biorxiv.py` uses `requests.get()` directly for category listing, bypassing the rate limiter and retry logic every other provider uses.

**Fix:** Route through the existing `client.get()` call.

**Files:** `skills/deep-research/scripts/providers/biorxiv.py`

---

## 6. Verify EDGAR Rate Limit

**Problem:** EDGAR sets 10.0 req/s for both `efts.sec.gov` and `data.sec.gov`. SEC aggressively throttles despite their stated 10 req/s policy. Other providers use 1–5 req/s. May be causing silent 403s.

**Fix:** Test with current settings. If 403s are observed, lower to 5.0 or add adaptive backoff. At minimum, add a comment documenting the SEC policy and any observed behavior.

**Files:** `skills/deep-research/scripts/providers/edgar.py`
