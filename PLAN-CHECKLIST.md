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
- [ ] Update SKILL.md: document auto-discovery behavior
- [ ] Update SKILL.md: add zsh-compatible syntax note (`VAR=val command`, not `export VAR=val && command`)
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
- [ ] Create quality assessment utility in `scripts/_shared/quality.py`:
  - [ ] Alphabetic character ratio check
  - [ ] Sentence detection regex (`[A-Z].*[.!?]`)
  - [ ] Minimum content length threshold (>500 chars of real text)
  - [ ] Return quality grade: `ok`, `degraded`, `empty`
- [ ] Integrate into `scripts/download.py` after markdown conversion:
  - [ ] Run quality check on converted `.md` file
  - [ ] Set `"quality": "degraded"` in result when heuristics fail
  - [ ] Include `"quality_details"` in JSON output (char_ratio, sentence_count)
  - [ ] Print `[WARN]` to stderr for degraded conversions
- [ ] Add abstract fallback on cascade failure:
  - [ ] When all 6 PDF sources fail, attempt `https://doi.org/{doi}` as web download
  - [ ] Mark result as `"quality": "abstract_only"`
- [ ] Update source metadata in state.db with quality field
- [ ] Test: download a known-degraded PDF (e.g., some Elsevier accepted manuscripts) → quality marked as degraded

### #7 + #9 — Search Auto-Logs, Auto-Adds Sources, and Silent Failure Fix
- [ ] Extract `log_search()` and `add_sources()` from `state.py` into importable functions
- [ ] In `scripts/search.py`, after successful search:
  - [ ] Auto-call `log_search()` with provider, query, result_count
  - [ ] Auto-call `add_sources()` with search results (using existing dedup logic)
  - [ ] Include assigned source IDs in the JSON output
- [ ] Handle gracefully when no session directory is available (skip auto-log/add, no error)
- [ ] Verify `state.json` is regenerated after auto-log/add (calls `_regenerate_snapshot`)
- [ ] Test: `./search --provider semantic_scholar --query "test"` → `./state summary` shows search count > 0 and sources added
- [ ] Test: running same search twice doesn't create duplicate sources
- [ ] Test: `state.json` reflects searches and sources after search completes
- [ ] Root cause note: searches were NEVER logged in any prior session (manual `log-search` was never called). Findings went missing in a prior session likely due to zsh session-dir syntax errors causing silent `log-finding` failures. Both fixed by auto-discovery (#1) + auto-logging (#7/#9).

---

## Phase 3: Citation Integrity

### #11 — Download-First Citation Policy
- [ ] Add `./download --batch --from-json FILE` mode:
  - [ ] Accept JSON array of `{"doi": "...", "url": "..."}` objects
  - [ ] Download in parallel with rate limiting (max 3 concurrent)
  - [ ] Return per-item results (success/fail/degraded)
- [ ] Add `./state download-pending` convenience command:
  - [ ] Query state.db for all sources without on-disk content files
  - [ ] Output DOI/URL list in batch-download format
  - [ ] Option: `--auto-download` to immediately download all pending
- [ ] Update SKILL.md citation policy:
  - [ ] Only sources with on-disk `.md` content (quality != degraded) may appear in main References
  - [ ] Abstract-only sources go in "Further Reading" section
  - [ ] Report methodology must distinguish deep reads vs. abstract-only
- [ ] Update report template in SKILL.md:
  - [ ] Split references: `## References (Sources Read)` and `## Further Reading`
- [ ] Update SKILL.md workflow:
  - [ ] After search rounds, download ALL relevant sources (not just top 5-8)
  - [ ] Triage downloaded sources by quality
  - [ ] Spawn reader subagents for all good-quality sources
  - [ ] Only cite sources with notes in `notes/`

### #8 — Pre-Report Audit Command
- [ ] Add `audit` subcommand to `scripts/state.py`:
  - [ ] Count sources tracked vs. downloaded vs. with notes
  - [ ] List sources with degraded quality
  - [ ] Count findings per research question
  - [ ] Flag questions with <2 findings
  - [ ] Count sources with no on-disk content
  - [ ] Compute methodology stats: deep reads, abstract-only, web sources
  - [ ] Print structured summary to stdout (JSON) and human-readable to stderr
- [ ] Add `--strict` flag: exit with non-zero if any source is cited without on-disk content
- [ ] Update SKILL.md: replace manual pre-report audit checklist with `./state audit` command
- [ ] Test: run `./state audit` against the uncanny valley session → should flag 16 sources without on-disk content

---

## Phase 4: Correctness

### #5 — Web Source ID Mapping
- [ ] In `scripts/download.py` web download path:
  - [ ] Look up existing source by URL match in state.db
  - [ ] If no match found, create a new source entry automatically
  - [ ] If match found, verify URL matches before assigning content
  - [ ] Print assigned source ID prominently in output
- [ ] Test: download a web URL not in state.db → new source created with correct type "web"
- [ ] Test: download a web URL already in state.db → maps to correct existing source

---

## Phase 5: Polish

### #4 — SKILL.md Instruction Updates
- [ ] Add Quick-Start Workflow section (10-step condensed workflow)
- [ ] Bold the parallel search warning (academic vs. web in separate batches)
- [ ] Add degraded PDF handling guidance
- [ ] Remove any instructions that are now handled by tools:
  - [ ] "Log searches" → auto-logged (#7)
  - [ ] "Add sources after search" → auto-added (#9)
  - [ ] "Pre-report audit checklist" → replaced by `./state audit` (#8)
- [ ] Update Output Format section with split references template

### #6 — `--from-stdin` Support
- [ ] In `scripts/state.py`, for subcommands that accept `--from-json`:
  - [ ] Add `--from-stdin` as mutually exclusive alternative
  - [ ] When used, read JSON from `sys.stdin`
  - [ ] Subcommands: `set-brief`, `add-source`, `add-sources`, `check-dup-batch`
- [ ] Test: `echo '{"scope":"test"}' | ./state set-brief --from-stdin`

### #10 — Download by Source ID
- [ ] Add `--source-id` flag to `scripts/download.py`
- [ ] Look up DOI and/or URL from state.db
- [ ] Run existing download logic with resolved DOI/URL
- [ ] Ensure downloaded content maps to the correct source ID
- [ ] Test: `./download --source-id src-003 --to-md` → downloads and maps correctly

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
