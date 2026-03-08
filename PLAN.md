# Deep Research Skill — Improvement Plan

Based on a retrospective of the "uncanny valley" deep research session (2026-03-08), this plan captures all identified friction points and improvements, organized by priority and implementation area.

---

## Problem Summary

The deep research skill works end-to-end but has significant friction in three areas:
1. **Shell/environment ergonomics** — session-dir handling causes repeated failures in zsh
2. **Tooling gaps** — degraded PDFs, cascade failures, and log/JSON mixing create silent data quality issues
3. **Skill instructions** — missing workflow guidance, insufficient warnings, and no pre-report audit step lead to inflated claims and wasted tool calls

---

## 1. Session Directory Auto-Discovery (High Priority)

**Problem:** Every command requires `--session-dir` or a correctly-set env var. In zsh, `export VAR=val && command` doesn't work (zsh syntax issue), causing repeated failures. This was the #1 source of wasted tool calls.

**Root cause:** `get_session_dir()` in `scripts/_shared/config.py` only checks `args.session_dir` and `$DEEP_RESEARCH_SESSION_DIR`. No filesystem-based discovery.

### Solution: Add `.deep-research-session` marker file

**A. On `init`:** Write a `.deep-research-session` file in the current working directory containing the absolute path to the session directory.

**B. In `get_session_dir()`:** Add a third precedence level:
1. `args.session_dir` (CLI flag)
2. `$DEEP_RESEARCH_SESSION_DIR` (env var)
3. **NEW:** Walk up from `cwd` looking for `.deep-research-session` file

**C. In SKILL.md:** Document that after `init`, all subsequent commands auto-discover the session. Add the zsh-compatible syntax `VAR=val command` (not `export VAR=val && command`).

**Files to modify:**
- `scripts/_shared/config.py` — add marker file discovery to `get_session_dir()`
- `scripts/state.py` — write marker file in `init` subcommand
- `SKILL.md` — document auto-discovery, add zsh syntax note

---

## 2. Structured Output (Logs vs. JSON) (High Priority)

**Problem:** CLI tools mix `[info]`/`[warn]`/`[error]` log lines with JSON output on stdout. When piping to `python3 -c "json.load(sys.stdin)"`, the log lines cause parse failures, which can cascade-cancel parallel tool calls.

### Solution: Separate log and data streams

**A.** Move all `[info]`/`[warn]`/`[error]` log output to **stderr**.

**B.** Ensure stdout contains **only** the JSON result envelope.

**C.** Add `--quiet` flag to suppress log output entirely (for pipeline use).

**Files to modify:**
- `scripts/_shared/output.py` — route log functions to stderr
- `scripts/search.py`, `scripts/download.py`, `scripts/state.py`, `scripts/enrich.py` — audit all `print()` calls; ensure logs go to stderr

---

## 3. PDF Quality Detection and Fallback (High Priority)

**Problem:** Degraded PDF conversions (e.g., Ürgen 2018 — just line numbers and a pymupdf warning) are reported as `"quality": "ok"` in metadata. The agent trusts this and claims to have "deeply read" a paper that was actually unreadable. When the full cascade fails, there's no automatic fallback.

### Solution A: Improve quality detection

- After markdown conversion, check content quality heuristics:
  - Ratio of alphabetic characters to total characters
  - Presence of actual sentences (regex for `[A-Z].*[.!?]`)
  - Minimum content length threshold (e.g., >500 chars of actual text)
- Set `"quality": "degraded"` when heuristics fail

### Solution B: Abstract fallback on cascade failure

- When all 6 PDF sources fail, automatically attempt to download the DOI landing page as web content (`--url https://doi.org/{doi} --type web`)
- Log this as a partial source with `"quality": "abstract_only"`

### Solution C: Report quality in CLI output

- When quality is degraded, print a prominent warning: `[WARN] PDF conversion quality is degraded — content may be unusable`
- In the JSON result, include `"quality_details": {"char_ratio": 0.12, "sentence_count": 0}`

**Files to modify:**
- `scripts/download.py` — add quality heuristics after conversion, add abstract fallback
- `scripts/_shared/` — add quality assessment utility

---

## 4. SKILL.md Instruction Improvements (Medium Priority)

### 4a. Add Quick-Start Workflow

Add a condensed workflow at the top of the skill instructions, right after the "Key principle" line:

```
## Quick-Start Workflow
1. `./state init --query "..."` — creates session
2. Draft research brief → `./state set-brief --from-json`
3. Search academic providers (parallel OK within academic)
4. Search web providers (Tavily/WebSearch — SEPARATE batch from academic)
5. `./state add-sources --from-json` — batch add
6. `./download --doi` top 5-8 papers
7. Spawn reader subagents for downloaded papers
8. `./state log-finding` per research question
9. `./state summary` — check coverage, identify gaps
10. Write report — but FIRST run the pre-report audit (see below)
```

### 4b. Bold the Parallel Search Warning

Change the existing parallel search note to a prominent callout:

```
> **CRITICAL: Never mix academic CLI searches (./search) with web tool calls
> (Tavily/WebSearch) in the same parallel batch.** If one fails, the runtime
> cancels all siblings. Always separate them into distinct response blocks.
```

### 4c. Add Pre-Report Audit Step

Add a new section before "Output Format":

```
## Pre-Report Audit

Before writing report.md, verify your evidence chain:

1. **Check notes/**: `ls notes/` — which sources have subagent summaries?
2. **Check sources/**: `ls sources/*.md` + review metadata quality fields
3. **Count actual deep reads**: Only count sources where you (or a subagent)
   read the full text and wrote notes. Abstracts ≠ deep reads.
4. **Cross-reference claims**: Every factual claim in the report must trace
   to a source with on-disk content. If you only have the abstract, say so.
5. **Methodology section must be honest**: Report actual deep reads, not
   total sources tracked.
```

### 4d. Document zsh Syntax

Add to the session-dir documentation:

```
**zsh users (including Claude Code):** Use `VAR=val command` syntax, NOT
`export VAR=val && command`. Example:
    DEEP_RESEARCH_SESSION_DIR="./my-session" ./search --provider semantic_scholar --query "..."
```

### 4e. Document Degraded PDF Handling

Add to the "Sources on disk before synthesis" section:

```
**Degraded PDFs:** Check `"quality"` in metadata files. For `"degraded"`
sources, do NOT claim deep reading. Options:
- Use abstract from search metadata instead
- Try `./download --url https://doi.org/{doi} --type web` for the landing page
- Seek an alternate open-access version
```

**Files to modify:**
- `SKILL.md` — all changes in this section

---

## 5. Web Source ID Mapping (Medium Priority)

**Problem:** When `./download --url` downloads web content, it assigns the content to an existing source ID by unclear logic (first available? matching URL?). This can overwrite or mismap content.

### Solution

- When downloading web content, if no existing source matches the URL, **create a new source** in state.db automatically
- When an existing source matches, confirm the match by URL before assigning
- Print the assigned source ID prominently in the output

**Files to modify:**
- `scripts/download.py` — improve source ID resolution for web downloads

---

## 6. `--from-stdin` Support (Low Priority)

**Problem:** Every `add-sources` / `set-brief` call requires writing a temp file, then passing `--from-json /tmp/file.json`. This is correct for robustness but adds friction.

### Solution

Add `--from-stdin` flag as an alternative to `--from-json`:

```bash
echo '{"scope": "..."}' | ./state set-brief --from-stdin
```

Implementation: In the argument parser, add a mutually exclusive group for `--from-json` / `--from-stdin`. When `--from-stdin` is used, read JSON from `sys.stdin`.

**Files to modify:**
- `scripts/state.py` — add `--from-stdin` to relevant subcommands

---

## 7. Log Searches Automatically + Fix Silent State Failures (Medium Priority)

**Problem:** `./state log-search` is a manual step that's easy to forget. The search count in `./state summary` showed 0 despite multiple searches being run.

### Solution

Have `./search` automatically call `./state log-search` when a session directory is available. The search script already knows the provider, query, and result count.

### Observed data loss pattern

In multiple sessions, state.json has been found missing searches (every session — never manually logged) and occasionally missing findings (previous session). Root cause analysis:

- **Searches:** Never auto-logged. `./search` doesn't call `log-search`. Agent never calls it manually. This is 100% reproducible — **no session has ever had searches logged.**
- **Findings:** `log-finding` writes to SQLite and calls `_regenerate_snapshot()` which writes `state.json`. The code path is correct. Most likely failure mode: the `log-finding` CLI call itself failed silently due to session-dir issues (zsh `export && command` syntax error), and the agent didn't notice because it was one of many chained commands.

The fix is two-fold:
1. Auto-log searches (#7/#9) eliminates the manual step
2. Session-dir auto-discovery (#1) eliminates the most common cause of silent state write failures

**Files to modify:**
- `scripts/search.py` — auto-log search and auto-add sources after successful execution

---

## 8. Pre-Report Audit Command (Medium Priority — replaces instruction-only approach)

**Problem:** The SKILL.md tells the agent to audit evidence before writing the report, but instructions get ignored under context pressure. This should be a tool, not a reminder.

### Solution: `./state audit` command

A new subcommand that automatically checks readiness and prints an honest assessment:

```
$ ./state audit
=== Pre-Report Audit ===
Sources tracked:     20
Sources downloaded:  4  (src-002, src-004, src-007, src-018)
Sources with notes:  2  (src-002, src-004)
Degraded quality:    1  (src-007 — quality: degraded)
Findings logged:     8  (covering Q1, Q2, Q3, Q6)
Gaps logged:         0
Questions with <2 findings: Q4, Q5, Q7

WARNINGS:
- src-007 has degraded PDF quality — do not claim deep reading
- Q4, Q5, Q7 have insufficient coverage (<2 findings each)
- 16 sources have no on-disk content (abstract-only)

Methodology stats (use these in report):
  Deep reads: 2
  Abstract-only: 16
  Web sources: 2
```

This replaces the "Pre-Report Audit" instruction section — the tool enforces honest reporting automatically.

**Files to modify:**
- `scripts/state.py` — add `audit` subcommand
- `SKILL.md` — reference `./state audit` instead of manual checklist

---

## 9. Search Auto-Adds Sources (Medium Priority — reduces manual steps)

**Problem:** After every search, the agent must manually extract results, write them to a temp JSON file, and call `./state add-sources --from-json`. This is error-prone and tedious. Sometimes the agent forgets and sources aren't tracked.

### Solution: Auto-add in search

When `--session-dir` is available (or auto-discovered), `./search` should automatically:
1. Add all results to state.db via the existing dedup logic
2. Log the search via `log-search`
3. Return the JSON results as before, but with source IDs assigned

This eliminates two manual steps (add-sources + log-search) per search call.

**Files to modify:**
- `scripts/search.py` — import and call state.py's add_sources and log_search functions directly
- `scripts/state.py` — extract add_sources/log_search into importable functions (if not already)

---

## 10. Download Auto-Discovery from State (Low Priority — reduces manual lookups)

**Problem:** To download a paper, the agent must look up the DOI from search results and pass it manually. The state DB already has all DOIs.

### Solution: `./download --source-id src-003`

Allow downloading by source ID. The tool looks up the DOI (or URL) from state.db and runs the cascade automatically. This also ensures the downloaded content is correctly mapped to the right source.

**Files to modify:**
- `scripts/download.py` — add `--source-id` flag, look up DOI/URL from state.db

---

## 11. Download-First Citation Policy (High Priority — fundamental quality fix)

**Problem:** In the uncanny valley session, 20 sources were cited but only 2 were deeply read. The remaining 18 were cited based on search abstracts and metadata alone. This creates an evidence chain that *looks* authoritative but is actually thin — the agent is citing papers it hasn't read, which risks misrepresenting findings, missing nuance, and propagating abstract-level oversimplifications.

The skill instructions say "Every factual claim must be verified against the corresponding on-disk .md file before inclusion" but this was ignored in practice because:
1. Downloading is slow and some papers are paywalled
2. There's no enforcement — nothing stops the agent from citing unread sources
3. The report template doesn't distinguish "deeply read" from "abstract-only" citations

### Solution: Only cite what you've read

**A. Policy change in SKILL.md:**
- Sources cited in the report **must** have on-disk content (`.md` file with real content, not degraded)
- Sources known only from abstracts can be mentioned in a separate "Additional References" or "Further Reading" section, explicitly marked as not deeply read
- The `./state audit` command (#8) should flag any cited source lacking on-disk content

**B. Workflow change — download aggressively, filter ruthlessly:**
1. After initial search rounds, attempt to download **all** sources that look relevant (not just "top 5-8")
2. Use `./download --doi` in parallel batches of 3-5
3. After downloads complete, triage: which have good content? which degraded? which paywalled?
4. Spawn reader subagents for all sources with good content (parallel, 2-3 per agent)
5. Only cite sources that have been read (by agent or subagent with notes in `notes/`)

**C. Tool support — `./download --batch`:**
Add a batch download mode that takes a list of DOIs (from state.db or a file) and downloads them in parallel with rate limiting:
```
./state download-pending          # downloads all sources without on-disk content
./download --batch --from-json    # batch download from DOI list
```

**D. Report template enforcement:**
Split references into two sections:
```markdown
## References (Sources Read)
[1] Author, "Title," ... [academic]  ← has notes/src-001.md

## Further Reading (Not Deeply Read)
- Author, "Title," ... — cited for abstract/metadata only
```

**Files to modify:**
- `SKILL.md` — new citation policy, updated workflow
- `scripts/download.py` — add `--batch` mode
- `scripts/state.py` — add `download-pending` convenience command, update `audit` to check citation coverage
- Report template in SKILL.md — split references section

---

## Design Philosophy: Build Guardrails Into Tools, Not Instructions

Several improvements follow the principle that **tools should enforce correctness by default** rather than relying on the agent to follow instructions:

| What was instructed | What should be built |
|---|---|
| "Log searches after each search" | Search auto-logs (#7) |
| "Add sources after each search" | Search auto-adds (#9) |
| "Check PDF quality before claiming deep reads" | Quality detection in download (#3) |
| "Audit evidence before writing report" | `./state audit` command (#8) |
| "Separate academic and web parallel calls" | Logs to stderr prevents cascade (#2) |
| "Use correct zsh syntax for session-dir" | Auto-discovery eliminates need (#1) |
| "Verify claims against on-disk files" | Download-first policy + audit enforcement (#11) |
| "Only cite what you've read" | Split references in report template + batch download (#11) |

The remaining instruction-only items (quick-start workflow, parallel search warning) are genuinely about research strategy and can't be fully automated — those stay as instructions.

---

## Implementation Order

| Phase | Items | Impact | Effort |
|-------|-------|--------|--------|
| **Phase 1: Core ergonomics** | #1 session auto-discovery, #2 structured output | Eliminates ~60% of wasted tool calls | Small-Medium |
| **Phase 2: Data quality** | #3 PDF quality detection, #7+#9 search auto-log/add | Prevents silent data issues, removes 2 manual steps per search | Medium |
| **Phase 3: Citation integrity** | #11 download-first policy + batch download, #8 audit command | Only cite what you've read; honest methodology | Medium-Large |
| **Phase 4: Correctness** | #5 web source mapping | Prevents source ID misassignment | Small |
| **Phase 5: Polish** | #4 SKILL.md updates, #6 --from-stdin, #10 download by source-id | Ergonomic improvements | Small |
