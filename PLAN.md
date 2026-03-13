# Deep Research Pipeline Improvements — v1

Source: `deep-research-uncanny-valley/REFLECTION.md` and `SUGGESTIONS.md` session analysis (2026-03-12).

---

## 1. Post-download content verification in `download.py`

**Problem:** 48% of downloads contained wrong content. Mismatch detection exists inline during download (`assess_quality` + `check_content_mismatch` at lines 494/507 for web, 801 for PDF), but the recovery path (`_handle_retry_sync`) only reads quality from metadata JSON — it never re-validates content against expected title/authors.

**What already works:**
- `check_content_mismatch(content, title, authors, abstract)` runs during initial web/PDF download
- `assess_quality(content)` detects paywalls/stubs during initial download
- Quality string stored in metadata JSON and synced to state.db

**What's missing:**
- Recovery sync (`_handle_retry_sync`, line 122) trusts whatever quality is in metadata JSON or defaults to `"ok"` — never re-checks content
- No paywall-specific string detection (current `assess_quality` checks for short content, not paywall keywords)

**Changes:**
1. **`download.py` — `_handle_retry_sync()` (line 122):** After recovering a source's content_file path, if quality is `"ok"` or missing, re-run `check_content_mismatch()` against metadata title/authors. This catches sources that were downloaded before mismatch detection was added.
2. **`download.py` — `assess_quality()` or new helper:** Add paywall string detection — scan first 50 lines for "Buy article", "Subscribe", "Log in via an institution", "Access this article", "USD", "purchase". Flag as `quality: "degraded"` with reason `"paywall_page"`.
3. **`download.py` — `_sync_to_state()` (line 82):** If quality was set to "mismatched" during download, include `quality_details` (mismatch reason, title_hits, author_hits) in the metadata JSON so it survives retry-sync.

**Files:** `skills/deep-research/scripts/download.py`

---

## 2. Recovery phase relevance gate

**Problem:** ~20% of search budget spent recovering off-topic high-citation papers (PRISMA guidelines, COVID burden studies). These entered state.db from broad keyword searches sharing terms like "systematic review" or "artificial intelligence".

**What already exists:**
- `source-acquisition.md` line 126 mentions filtering by `relevance_score < 0.3` or zero keyword hits
- But the actual `recover-failed` state command doesn't enforce this — it returns all failed sources

**Changes:**
1. **`state.py` — `recover-failed` command:** Add `--min-relevance` flag (default 0.0) that filters out sources with `relevance_score` below threshold before returning them. Also add `--title-keywords` flag that requires at least one keyword match in the source title.
2. **`source-acquisition.md` — recovery phase:** Instruct agent to always pass `--min-relevance 0.3` and `--title-keywords` derived from the brief's scope when calling `recover-failed`. Make this a hard rule, not optional.

**Files:** `skills/deep-research/scripts/state.py`, `agents/source-acquisition.md`

---

## 3. Elevate citation chasing to primary strategy

**Problem:** Only 1 citation-chase search in a session with seed papers at 440+ citations. A paper with 440 cites returning 0 results suggests a possible bug in the Semantic Scholar `--cited-by` code path.

**Changes:**
1. **Investigate `search.py` cited-by path:** Verify that `--cited-by` correctly calls the Semantic Scholar `/paper/{id}/citations` endpoint. Check if paper ID format (DOI vs S2 ID) is handled correctly. The `_detect_search_mode()` function (line 191) looks correct for flag detection, but the actual API call needs verification in the provider implementation.
2. **`source-acquisition.md` — search strategy:** Add explicit instruction: after round 1 keyword searches, identify 3-5 highest-cited on-topic sources. In round 2, run `--cited-by` on each via Semantic Scholar. Run `--references` on the same sources. For literature review topics, citation chasing should account for 30-50% of search effort.
3. **`SKILL.md` — search examples:** Add citation-chasing examples showing the expected workflow.

**Files:** `skills/deep-research/scripts/search.py` (verify), `agents/source-acquisition.md`, `skills/deep-research/SKILL.md`

---

## 4. Fix author name fabrication in synthesis-writer

**Problem:** Writer hallucinated 3 of 4 co-author names on a reference. The verifier caught it but only checks 5-10 claims — systematic risk of undetected fabrication.

**Changes:**
1. **`synthesis-writer.md` — references section (line 76):** Add explicit instruction: "For each cited source, read the corresponding `sources/metadata/src-NNN.json` file and extract authors, title, year, venue, and DOI from the JSON fields. NEVER generate author names, titles, or publication details from memory or training data."
2. **`synthesis-writer.md` — references section:** Add fallback instruction: "If a metadata file is missing or has incomplete author data, write `[metadata incomplete]` in place of the missing fields rather than guessing."
3. **`synthesis-writer.md` — references section:** Add template: `Read sources/metadata/src-NNN.json → use authors, title, year, venue fields exactly as written.`

**Files:** `agents/synthesis-writer.md`

---

## 5. Fix `set-quality` CLI type mismatch

**Problem:** `--quality` argument is `type=float` (line 2139) but workflow uses string labels ("ok", "mismatched", "degraded", "abstract_only"). The `quality` column is `REAL` in schema (line 74) but stores strings via `update-source --from-json` workaround.

**Changes:**
1. **`state.py` — `set-quality` subcommand (line 2137):** Change `type=float` to `type=str` with `choices=["ok", "abstract_only", "degraded", "mismatched"]`.
2. **`state.py` — schema (line 74):** Change `quality REAL` to `quality TEXT`. SQLite is type-flexible so existing databases continue to work, but new databases get the correct type.
3. **`SKILL.md`:** Verify documented syntax matches: `state set-quality --id src-NNN --quality mismatched`.

**Files:** `skills/deep-research/scripts/state.py`, `skills/deep-research/SKILL.md`

---

## 6. Ingestion-time relevance filtering

**Problem:** 471 sources tracked, ~92% irrelevant by title. Bloats state, wastes triage effort, and feeds irrelevant sources into recovery.

**What already exists:**
- `source-acquisition.md` lines 82-89 describe a pre-insertion relevance gate with domain term filtering
- `relevance_score` column exists in schema (line 75) but appears unused at ingestion
- `add-sources` in state.py does no relevance checking

**Changes:**
1. **`search.py` — `_add_sources_to_state()` (line 239):** Before calling `add-sources`, compute a lightweight title-keyword overlap score against a `--brief-keywords` argument. Pass computed `relevance_score` in each source object.
2. **`state.py` — `_insert_source()` (line 489):** Store `relevance_score` if provided in the source object (it's already in the schema).
3. **`source-acquisition.md`:** Instruct agent to pass `--brief-keywords` to search calls, derived from the brief's scope and question keywords. Sources with zero overlap get `relevance_score: 0.0` and are still ingested (no data loss) but deprioritized for triage and download.

**Files:** `skills/deep-research/scripts/search.py`, `skills/deep-research/scripts/state.py`, `agents/source-acquisition.md`
