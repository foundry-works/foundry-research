# Deep Research Skill — Implementation Checklist

Companion to [PLAN.md](./PLAN.md). Check items off as completed.

---

## Phase 1: Core Ergonomics

### #1 — Session Directory Auto-Discovery
- [x] Add `.deep-research-session` marker file write to `state.py` `init` subcommand
- [x] Update `get_session_dir()` in `scripts/_shared/config.py`:
  - [x] Add precedence level 3: walk up from cwd looking for `.deep-research-session`
  - [x] Read absolute session path from marker file contents
  - [x] Add `.deep-research-session` to `.gitignore`
- [x] Update SKILL.md: document auto-discovery behavior
- [x] Update SKILL.md: add zsh-compatible syntax note — no longer needed since auto-discovery eliminates the need
- [x] Test: `./state init --query "test" --session-dir ./test-session` creates marker; subsequent `./state summary` works without `--session-dir`

### #2 — Structured Output (Logs vs. JSON)
- [x] Audit `scripts/_shared/output.py` — identify all log/print functions
- [x] Route `[info]`, `[warn]`, `[error]`, `[debug]` output to **stderr** (already correct)
- [x] Ensure **stdout** contains only the JSON result envelope
- [x] Add `--quiet` flag to suppress stderr log output
- [x] Audit and fix all direct `print()` calls in:
  - [x] `scripts/search.py` (no stray prints found)
  - [x] `scripts/download.py` (no stray prints found)
  - [x] `scripts/state.py` (fixed `_connect()` to use `error_response()`)
  - [x] `scripts/enrich.py` (no stray prints found)
- [x] Test: `./state summary 2>/dev/null` produces valid JSON on stdout
- [x] Test: `./state summary | python3 -c "import sys,json; json.load(sys.stdin)"` works

---

## Phase 2: Data Quality

### #3 — PDF Quality Detection and Fallback
- [x] Create quality assessment utility in `scripts/_shared/quality.py`:
  - [x] Alphabetic character ratio check
  - [x] Sentence detection regex (`[A-Z].*[.!?]`)
  - [x] Minimum content length threshold (>500 chars of real text)
  - [x] Return quality grade: `ok`, `degraded`, `empty`
- [x] Integrate into `scripts/download.py` after markdown conversion:
  - [x] Run quality check on converted `.md` file
  - [x] Set `"quality": "degraded"` in result when heuristics fail
  - [x] Include `"quality_details"` in JSON output (char_ratio, sentence_count)
  - [x] Print `[WARN]` to stderr for degraded conversions
- [x] Add abstract fallback on cascade failure:
  - [x] When all 6 PDF sources fail, attempt `https://doi.org/{doi}` as web download
  - [x] Mark result as `"quality": "abstract_only"`
- [x] Update source metadata in state.db with quality field
- [ ] Test: download a known-degraded PDF (e.g., some Elsevier accepted manuscripts) → quality marked as degraded

### #7 + #9 — Search Auto-Logs, Auto-Adds Sources, and Silent Failure Fix
- [x] ~~Extract `log_search()` and `add_sources()` from `state.py` into importable functions~~ (Used subprocess calls instead, consistent with existing patterns)
- [x] In `scripts/search.py`, after successful search:
  - [x] Auto-call `log_search()` with provider, query, result_count
  - [x] Auto-call `add_sources()` with search results (using existing dedup logic)
  - [x] ~~Include assigned source IDs in the JSON output~~ (source IDs logged to stderr; stdout already printed by provider)
- [x] Handle gracefully when no session directory is available (skip auto-log/add, no error)
- [x] Verify `state.json` is regenerated after auto-log/add (calls `_regenerate_snapshot`)
- [x] **Bug fix**: Phase 1's `_log_search_to_state` was never called because `success_response()` returns a JSON string, not a dict. Fixed by parsing the result string back into a dict.
- [ ] Test: `./search --provider semantic_scholar --query "test"` → `./state summary` shows search count > 0 and sources added
- [ ] Test: running same search twice doesn't create duplicate sources
- [ ] Test: `state.json` reflects searches and sources after search completes
- [x] Root cause note: searches were NEVER logged in any prior session (manual `log-search` was never called). Findings went missing in a prior session likely due to zsh session-dir syntax errors causing silent `log-finding` failures. Both fixed by auto-discovery (#1) + auto-logging (#7/#9).

---

## Phase 3: Citation Integrity

### #11 — Download-First Citation Policy
- [x] Add `./download --batch --from-json FILE` mode:
  - [x] Accept JSON array of `{"doi": "...", "url": "..."}` objects
  - [x] Download in parallel with rate limiting (max 3 concurrent)
  - [x] Return per-item results (success/fail/degraded)
- [x] Add `./state download-pending` convenience command:
  - [x] Query state.db for all sources without on-disk content files
  - [x] Output DOI/URL list in batch-download format
  - [x] Option: `--auto-download` to immediately download all pending
- [x] Update SKILL.md citation policy:
  - [x] Only sources with on-disk `.md` content (quality != degraded) may appear in main References
  - [x] Abstract-only sources go in "Further Reading" section
  - [x] Report methodology must distinguish deep reads vs. abstract-only
- [x] Update report template in SKILL.md:
  - [x] Split references: `## References (Sources Read)` and `## Further Reading`
- [x] Update SKILL.md workflow:
  - [x] After search rounds, download ALL relevant sources (not just top 5-8)
  - [x] Triage downloaded sources by quality
  - [x] Spawn reader subagents for all good-quality sources
  - [x] Only cite sources with notes in `notes/`

### #8 — Pre-Report Audit Command
- [x] Add `audit` subcommand to `scripts/state.py`:
  - [x] Count sources tracked vs. downloaded vs. with notes
  - [x] List sources with degraded quality
  - [x] Count findings per research question
  - [x] Flag questions with <2 findings
  - [x] Count sources with no on-disk content
  - [x] Compute methodology stats: deep reads, abstract-only, web sources
  - [x] Print structured summary to stdout (JSON) and human-readable to stderr
- [x] Add `--strict` flag: exit with non-zero if any source is cited without on-disk content
- [x] Update SKILL.md: replace manual pre-report audit checklist with `./state audit` command
- [x] Test: run `./state audit` against the uncanny valley session → flags 14 sources without on-disk content

---

## Phase 4: Correctness

### #5 — Web Source ID Mapping
- [x] In `scripts/download.py` web download path:
  - [x] Look up existing source by URL match in state.db
  - [x] If no match found, create a new source entry automatically
  - [x] If match found, verify URL matches before assigning content
  - [x] Print assigned source ID prominently in output
- [x] Test: download a web URL not in state.db → new source created with correct type "web"
- [x] Test: download a web URL already in state.db → maps to correct existing source

---

## Phase 5: Polish

### #4 — SKILL.md Instruction Updates
- [x] Add Quick-Start Workflow section (10-step condensed workflow)
- [x] Bold the parallel search warning (academic vs. web in separate batches)
- [x] Add degraded PDF handling guidance
- [x] Remove any instructions that are now handled by tools:
  - [x] "Log searches" → auto-logged (#7)
  - [x] "Add sources after search" → auto-added (#9)
  - [x] "Pre-report audit checklist" → replaced by `./state audit` (#8)
- [x] Update Output Format section with split references template (already done in Phase 3)
- [x] Document session auto-discovery and `--from-stdin` support
- [x] Document `--source-id` download mode
- [x] Update SKILL.md: document auto-discovery behavior
- [x] Update SKILL.md: add zsh-compatible syntax note (`VAR=val command`, not `export VAR=val && command`) — no longer needed since auto-discovery eliminates the need

### #6 — `--from-stdin` Support
- [x] In `scripts/state.py`, for subcommands that accept `--from-json`:
  - [x] Add `--from-stdin` as mutually exclusive alternative
  - [x] When used, read JSON from `sys.stdin`
  - [x] Subcommands: `set-brief`, `add-source`, `add-sources`, `check-dup-batch`, `update-source`, `log-metrics`
- [x] Test: `echo '{"scope":"test"}' | ./state set-brief --from-stdin`

### #10 — Download by Source ID
- [x] Add `--source-id` flag to `scripts/download.py` (already existed as common flag, now works as standalone input mode)
- [x] Look up DOI and/or URL from state.db
- [x] Run existing download logic with resolved DOI/URL
- [x] Ensure downloaded content maps to the correct source ID
- [x] Test: `./download --source-id src-003 --to-md` → resolves DOI from state.db and runs cascade

---

## Validation

After all phases complete:
- [ ] Re-run the "uncanny valley" research topic end-to-end with the improved tools
- [ ] Verify: zero `--session-dir` errors
- [ ] Verify: all searches auto-logged and sources auto-added
- [ ] Verify: `./state audit` produces accurate pre-report assessment
- [ ] Verify: report only cites deeply-read sources in main References
- [ ] Verify: no cascade failures from mixed parallel calls
- [ ] Compare report quality and evidence chain to original session
