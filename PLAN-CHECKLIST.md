# Implementation Checklist

Tracks completion of each change item from PLAN.md.

---

## 1. Post-download content verification

- [x] **1a.** `download.py` — `_handle_retry_sync()`: Re-run `check_content_mismatch()` on sources with `quality == "ok"` or NULL during retry-sync
- [x] **1b.** `download.py` — Add paywall string detection (scan first 50 lines for paywall keywords, flag as `quality: "degraded"`)
- [x] **1c.** `download.py` — `_sync_to_state()`: Persist `quality_details` in metadata JSON so it survives retry-sync

## 2. Recovery phase relevance gate

- [x] **2a.** `state.py` — `recover-failed`: Add `--min-relevance` and `--title-keywords` flags to filter candidates
- [x] **2b.** `source-acquisition.md` — Recovery phase: Require `--min-relevance 0.3` and brief-derived `--title-keywords` on all `recover-failed` calls

## 3. Elevate citation chasing

- [x] **3a.** `search.py` — Investigate and verify `--cited-by` code path against Semantic Scholar API (check paper ID format handling)
- [x] **3b.** `source-acquisition.md` — Add round-2 citation chasing instructions: `--cited-by` and `--references` on top 3-5 cited sources
- [x] **3c.** `SKILL.md` — Add citation-chasing workflow examples

## 4. Fix author name fabrication

- [x] **4a.** `synthesis-writer.md` — Add instruction: pull all bibliographic data from `sources/metadata/*.json`, never from memory
- [x] **4b.** `synthesis-writer.md` — Add fallback: use `[metadata incomplete]` for missing fields instead of guessing
- [x] **4c.** `synthesis-writer.md` — Add reference-building template

## 5. Fix `set-quality` CLI type mismatch

- [x] **5a.** `state.py` — Change `set-quality --quality` from `type=float` to `type=str, choices=[...]`
- [x] **5b.** `state.py` — Change schema `quality REAL` → `quality TEXT`
- [x] **5c.** `SKILL.md` — Verified: already documents `--quality mismatched` (string-based), consistent with fix

## 6. Ingestion-time relevance filtering

- [x] **6a.** `search.py` — `_add_sources_to_state()`: Compute title-keyword overlap score, pass `relevance_score` in source objects
- [x] **6b.** `state.py` — `_insert_source()`: Store `relevance_score` if provided
- [x] **6c.** `source-acquisition.md` — Instruct agent to pass `--brief-keywords` to searches derived from brief scope
