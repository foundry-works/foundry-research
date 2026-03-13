# Implementation Checklist

## 1. Download Content Mismatch Detection

- [x] **1a.** Add `brief_keywords: list[str] | None = None` parameter to `check_content_mismatch()` in `quality.py`
- [x] **1b.** Add brief-keyword gate: if `brief_keywords` provided and zero match in `text[:2000]` AND `title_hits < 3`, set `mismatched = True`
- [x] **1c.** Lower abstract-overlap threshold from `title_hits < 3` to `title_hits < 2` (line 239)
- [x] **1d.** In `download.py`, read brief keywords from state.db (query brief JSON, extract scope/questions, run `_extract_keywords`)
- [x] **1e.** Pass extracted brief keywords to `check_content_mismatch()` calls (3 call sites: lines ~195, ~551, ~845)
- [ ] **1f.** Add test: mock a brief with domain keywords, download content with zero domain overlap → expect mismatched
- [ ] **1g.** Add test: on-topic content with brief keyword hits → expect not mismatched

## 2. Quality Flag Granularity

- [x] **2a.** Add `reader_validated` to quality choices in `state.py` `set-quality` argparse (line ~2500)
- [x] **2b.** In `mark-read` handler: if source quality is `degraded` AND note file exists in `notes/`, auto-upgrade quality to `reader_validated`
- [x] **2c.** Update `audit` output: split `degraded_quality` into `degraded_unread` and `reader_validated` arrays
- [x] **2d.** Update audit warnings: "do not claim deep reading" only for `degraded_unread`, not `reader_validated`
- [x] **2e.** Update `audit --brief` to report `reader_validated` count separately
- [x] **2f.** Update SKILL.md audit interpretation guidance (lines ~222-223) to reflect new categories
- [ ] **2g.** Add test: `mark-read` on a degraded source with existing note → quality becomes `reader_validated`
- [ ] **2h.** Add test: `mark-read` on an `ok` source → quality stays `ok` (no spurious downgrade)

## 3. Recovery Search Budget and Domain-Aware Early Exit

- [x] **3a.** Add `--max-attempts N` flag to `recover-failed` in `state.py` (default 15)
- [x] **3b.** Implement attempt counter: increment per recovery attempt (each channel per source = 1 attempt), stop when counter reaches max
- [x] **3c.** Add per-channel success tracking dict: `{channel: {"attempts": N, "successes": M}}`
- [x] **3d.** Implement channel early-exit: if a channel has 0 successes after 5 attempts, skip it for remaining sources; log the skip in the JSON response
- [x] **3e.** Add `skipped_channels` to `recover-failed` response schema
- [x] **3f.** Update `source-acquisition.md` recovery section (lines 149-158): add budget framing, document `--max-attempts`, add channel-skip behavior
- [x] **3g.** Update `source-acquisition.md` CLI reference (line ~300-301) with new flag
- [ ] **3h.** Add test: 20 sources eligible, max-attempts=5 → only 5 attempts run
- [ ] **3i.** Add test: channel with 0/5 success rate → channel skipped for source #6

## 4. Findings Deduplication

- [ ] **4a.** Add `deduplicate-findings` subcommand to `state.py`
- [ ] **4b.** Implement: query all findings, group by overlapping source citations
- [ ] **4c.** Implement: for candidate pairs, compute token overlap ratio on `--text`
- [ ] **4d.** Implement: merge findings with >70% overlap — keep the one with more source citations, add `also_relevant_to` field with the merged question(s)
- [ ] **4e.** Return JSON: `{"merged": N, "remaining": M, "original": K}`
- [ ] **4f.** Update `findings-logger.md`: add cross-reference guidance (lines ~47-49 area)
- [ ] **4g.** Update SKILL.md: add dedup step between steps 10 and 11
- [ ] **4h.** Add test: two findings with 80% text overlap citing same sources → merged
- [ ] **4i.** Add test: two findings with 40% overlap → not merged
- [ ] **4j.** Add test: two findings with different source citations → not merged even if text is similar

## 5. Citation Chasing Enforcement

- [ ] **5a.** In `state.py` `manifest` handler: compute `citation_chasing_ratio = traversals_run / max(1, total_searches - recovery_searches)`
- [ ] **5b.** Add `citation_chasing_ratio` to manifest output
- [ ] **5c.** If brief has 5+ questions AND ratio < 0.25, add warning to manifest `warnings` array
- [ ] **5d.** Update `source-acquisition.md`: add hard checkpoint between rounds 2 and 3 — "Before proceeding to round 3+, verify: `traversals_run >= floor(primary_searches * 0.25)`. If not, run more traversals."
- [ ] **5e.** Update manifest response schema in `source-acquisition.md` (line ~384) to include `citation_chasing_ratio`

## 6. Prompt Organization

- [ ] **6a.** Create `skills/deep-research/LESSONS.md` with entry format (ID, session, what happened, lesson, applied-in)
- [ ] **6b.** Extract ~15 incident-specific narrative blocks from SKILL.md into LESSONS.md entries
- [ ] **6c.** Replace extracted blocks with one-line references: "See LESSONS.md#entry-id"
- [ ] **6d.** Extract ~5 incident-specific blocks from `source-acquisition.md` into LESSONS.md
- [ ] **6e.** Verify: does Claude Code skill loader include LESSONS.md automatically, or only SKILL.md? If only SKILL.md, add a Read instruction at the top of SKILL.md pointing to LESSONS.md for debugging context.
- [ ] **6f.** Review: ensure all inline "why" blocks that explain *principles* (not incidents) remain in place
