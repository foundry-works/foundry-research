# Deep Research Improvement Checklist

## 1. LLM-Powered Abstract Relevance Scoring
- [ ] Add `relevance_score` (REAL) and `relevance_rationale` (TEXT) columns to sources table schema in `state.py`
- [ ] Create `scripts/triage-relevance` executable script
  - [ ] CLI argument parsing (--top N, --batch-size, --session-dir)
  - [ ] Pull brief + abstracts from state.db
  - [ ] Batch abstracts (15-20 per call)
  - [ ] Format prompt for Haiku (brief + numbered abstracts → JSON scores)
  - [ ] Call `claude -p ... --model haiku --output-format json`
  - [ ] Parse response, write scores to state.db
  - [ ] JSON envelope output (exit 0, status ok/error)
  - [ ] Graceful fallback if `claude` CLI unavailable
- [ ] Modify `cmd_triage` in `state.py` to prefer `relevance_score` over keyword matching
- [ ] Update `agents/source-acquisition.md` to call `triage-relevance` between ingest and download
- [ ] Test: run on the temperament session's state.db and verify off-topic papers score low

## 2. Content Validation at Download Time
- [ ] Add mismatch detection in `download.py` after PDF→markdown conversion
  - [ ] Extract significant title words (4+ chars) from metadata
  - [ ] Check first 1000 chars of converted content for title word presence
  - [ ] If < 2 title words found → set `quality = "mismatched"` in state.db
  - [ ] Log mismatch to journal.md
- [ ] Test: verify known mismatches from temperament session (src-051, src-128, src-129, src-758) would be caught

## 3. Triage Keyword Floor Reduction
- [ ] Change `state.py` line 1533: `0.5 + relevance` → `0.1 + relevance`
- [ ] Test: verify "SPIRIT 2013" (6932 cites, 0 relevance) no longer outranks relevant papers

## 4. `recover-failed` Topical Filtering
- [ ] Add relevance check in `cmd_recover_failed` before attempting recovery
- [ ] Skip sources with `relevance_score < 0.3` (or zero keyword hits if no LLM score)
- [ ] Test: verify off-topic high-citation papers are skipped during recovery

## 5. `state sync-files` Command
- [ ] Implement `cmd_sync_files` in `state.py`
  - [ ] Walk `sources/` directory for `.md` and `.pdf` files
  - [ ] Update `content_file` for sources with files on disk but no DB record
  - [ ] Clear `content_file` for records pointing to missing files
  - [ ] Report counts in JSON envelope
- [ ] Register in argparse subcommands
- [ ] Test: create a source with a file but no content_file record, verify sync fixes it

## 6. Source-Acquisition Agent Prompt Updates
- [ ] Add `triage-relevance` step to pipeline in `agents/source-acquisition.md`
- [ ] Add search budget guidance (15-25 searches initial round)
- [ ] Add warning about metadata-content mismatches
- [ ] Add topical filtering requirement for `recover-failed`

## 7. Gap Resolution Verification
- [ ] Update `skills/deep-research/SKILL.md` step 11 (gap-mode)
  - [ ] Orchestrator must not call `resolve-gap` based solely on acquisition manifest
  - [ ] Spawn readers for new gap-mode sources first
  - [ ] Only resolve gaps where a reader confirms relevant content
- [ ] Update `agents/source-acquisition.md` to report "potentially resolved" not "fully resolved"

## 8. Orchestrator Pre-Read Check
- [ ] Add guidance in `skills/deep-research/SKILL.md` delegation section
- [ ] Instruct orchestrator to read first 20-30 lines before spawning reader agents
- [ ] Skip sources that are clearly off-topic, garbled, or stubs

## 9. Open-Access PDF Recovery via Web Search
- [ ] Add web search fallback guidance to `agents/source-acquisition.md` (Option A — immediate)
  - [ ] When high-priority source fails download cascade, try:
    - [ ] `"{first author last name}" "{key title words}" PDF`
    - [ ] `"{paper title}" PDF`
  - [ ] Use first author from source metadata
  - [ ] Only attempt for top 5-10 highest-priority failed sources (not all failures)
- [ ] Evaluate: track recovery rate over 2-3 sessions to decide if Option B (code) or C (recover-failed) is worth building

## 10. Enforce Orchestrator Journal Entries
- [ ] Strengthen journal guidance in `skills/deep-research/SKILL.md`
  - [ ] Mandatory entry after brief is set (questions + search strategy)
  - [ ] Mandatory entry after source-acquisition returns (manifest summary, coverage, gaps)
  - [ ] Mandatory entry after readers complete (coverage analysis, patterns, contradictions)
  - [ ] Mandatory entry after gap-mode returns (resolved vs. open, synthesis strategy)
  - [ ] Mandatory entry before synthesis handoff (narrative key findings summary)
