# Implementation Checklist

## Batch 1: Prompt Changes

- [ ] **1. Remove fixed finding quota** — `agents/findings-logger.md`
  - [ ] Line 9: Remove "2-3" from description
  - [ ] Line 23 (step 4): Replace fixed range with organic guidance
  - [ ] Verify no other lines reference the "2-3" quota

- [ ] **2. Mandatory pre-read validation step** — `skills/deep-research/SKILL.md`
  - [ ] Insert new step 6 between triage (current 5) and reader spawning (current 6)
  - [ ] Renumber subsequent steps (6→7, 7→8, ... 12→13)
  - [ ] Update existing pre-read note at line 248 to reference the new step number
  - [ ] Update all internal step references (e.g., "step 8" in findings-logger delegation, "step 12" in synthesis)

- [x] **3. Post-reader source quality report** — `skills/deep-research/SKILL.md`
  - [x] Insert new step after mark-read step, before findings-loggers
  - [x] Include journal.md template with structured tally format
  - [x] Renumber subsequent steps

- [x] **4. Mismatch context for gap-mode** — `skills/deep-research/SKILL.md`
  - [x] Add "Mismatched source IDs" to step 13's agent directive bullet list
  - [x] Add `known_mismatches_excluded` field to gap-mode manifest spec
  - [x] Reference the quality report from item 3 as the source for mismatch IDs

- [x] **5. Paywall strategy** — `skills/deep-research/SKILL.md`
  - [x] Add "Paywall-heavy fields" subsection under "What Good Research Looks Like"
  - [x] Include: citing-paper search, preprint hunting, honest framing, ask user

- [ ] **6. Instrument-first search strategy** — `agents/source-acquisition.md`
  - [ ] Add "Domain-specific search strategies" section after "Query crafting rules"
  - [ ] Include instrument-first, construct-second, population-third ordering
  - [ ] Include author-name search guidance
  - [ ] Add "How to detect this pattern" trigger

- [ ] **7. Pre-insertion relevance gate** — `agents/source-acquisition.md`
  - [ ] Add "Pre-insertion relevance gate" section to Search Strategy
  - [ ] Include: extract 5-8 domain terms from brief, keyword-check titles
  - [ ] Caveat: this is guidance-level since `search` auto-ingests

- [ ] **Post-batch-1: Run `./copy-to-skills.sh`** to deploy to `.claude/` for testing

## Batch 2: Script Changes

- [ ] **8. Strengthen content mismatch detection** — `skills/deep-research/scripts/_shared/quality.py`
  - [ ] Add `abstract` parameter to `check_content_mismatch`
  - [ ] Extract top-10 non-stopword terms from abstract
  - [ ] Add abstract keyword overlap check (threshold: <20% AND title_hits < 2)
  - [ ] Update callers in `download.py` to pass `meta.get("abstract", "")`
  - [ ] Write tests for the new check with realistic mismatch examples

- [ ] **9. Debug triage citation counts** — `skills/deep-research/scripts/state.py`
  - [ ] Trace data flow: search result JSON → `add-sources` → state.db `citation_count` column
  - [ ] Check field name normalization across providers (`citation_count` vs `citationCount` vs `cited_by_count`)
  - [ ] Verify `cmd_triage` reads from correct column
  - [ ] Fix the propagation gap
  - [ ] Test with sample data from multiple providers

- [ ] **10. Fix content_file population** — `skills/deep-research/scripts/state.py` + `download.py`
  - [ ] Check `_sync_to_state` in download.py for `content_file` update
  - [ ] Check `cmd_sources` in state.py for `content_file` in output
  - [ ] If missing, add content_file update to download success path
  - [ ] If not displayed, add to sources output format
  - [ ] Test: download a source, verify `state sources` shows content_file
