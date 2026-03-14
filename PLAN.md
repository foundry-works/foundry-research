# Deep Research Pipeline Improvements — Plan

## Context

Observations from the 2026-03-14 "uncanny valley" research session. 32 sources deeply read, 100 findings logged, ~5,200-word report produced. The pipeline worked end-to-end but several structural issues wasted tokens, time, and introduced data quality risks.

---

## 1. Reader Agent Path Handling (Bug Fix)

### Problem
Three gap-mode reader agents wrote notes to `deep-research-uncanny-valley/deep-research-uncanny-valley/notes/` (doubled path) instead of `deep-research-uncanny-valley/notes/`. This caused findings-loggers to miss the notes entirely, requiring manual discovery and `cp` to fix. The root cause is the reader agent prompt saying "use relative paths from the project root" — but agents receive an absolute session directory path and construct relative paths from their working directory, which may differ from the project root.

### Fix
**File: `agents/research-reader.md`** — Remove the "always use relative paths" instruction. Replace with explicit path construction guidance:

```
## File paths

Construct output paths by joining the session directory from your directive with the relative note path. Example: if session directory is `/home/user/project/deep-research-topic`, write notes to `/home/user/project/deep-research-topic/notes/src-003.md` (absolute) or `deep-research-topic/notes/src-003.md` (relative from project root — use this only if your working directory is the project root).

**Never double the session directory name.** If the session directory path ends with `deep-research-topic`, the note path is `{session_dir}/notes/src-NNN.md`, not `deep-research-topic/deep-research-topic/notes/src-NNN.md`.
```

**Why:** The current instruction is ambiguous when the agent's working directory isn't the project root. Explicit examples prevent the doubled-path failure mode.

### Validation
After fix, spawn a test reader with a session directory path and verify the note lands in the correct location.

---

## 2. Earlier Content Mismatch Detection (Quality Gate)

### Problem
21 sources (15% of downloads) were eventually flagged as mismatched. The existing `check_content_mismatch()` in `quality.py` runs at download time but misses cases where:
- A paper shares domain vocabulary but covers a different topic (e.g., "uncanny valley" in geology vs. psychology)
- The downloaded PDF is a completely different paper (correct domain but wrong specific paper)
- Paywall landing pages with abstracts pass the content-length and sentence checks

The current three-layer check (title keywords, abstract overlap, brief keywords) catches ~70% of mismatches. The remaining 30% leak through to the pre-read step or worse, to reader agents.

### Fix
**File: `skills/deep-research/scripts/_shared/quality.py`** — Strengthen `check_content_mismatch()`:

1. **Check first-page author presence more aggressively.** Currently checks first 20,000 chars for author surnames. Change to: check first 3,000 chars (roughly the first page) for at least one author surname. Most legitimate PDFs have author names on the first page. If zero authors in first 3,000 chars AND title_hits < 3, flag as mismatched.

2. **Add a "paywall abstract stub" detector.** After `assess_quality()` returns `"ok"`, check if the content is suspiciously short for a full paper (< 2,000 chars of real text after stripping HTML comments and boilerplate) AND contains paywall markers anywhere (not just first 50 lines). Many Springer/Wiley pages pass the current checks because they include the abstract as real text.

**File: `skills/deep-research/scripts/download.py`** — After `check_content_mismatch()`, add a log line to stderr when a source is flagged, including the reason. This makes it visible in the acquisition agent's context without parsing JSON.

### Why not just rely on pre-read?
Pre-read validation costs one `Read` call per source — cheap but serial. Catching mismatches at download time is free (already in the pipeline) and prevents mismatched sources from appearing in triage rankings, download counts, and the acquisition manifest. The pre-read step remains as a second layer for subtle mismatches.

---

## 3. Gap-Mode "Light" Path (New Feature)

### Problem
The full gap-mode cycle (spawn acquisition agent → 10+ searches → downloads → spawn readers → re-run findings-loggers → re-audit) added ~50 minutes and ~300K tokens to get Q7 from 6 to 11 findings. For emerging topics with sparse academic literature, a lighter approach would be more cost-effective.

### Fix
**File: `skills/deep-research/SKILL.md`** — Add a "light gap-mode" option in step 14:

```
**Light gap-mode (for thin coverage on emerging/non-academic topics):**
When a question's gap is about topic recency (few academic papers exist yet) rather than search quality (papers exist but weren't found), use light gap-mode instead of the full acquisition agent:

1. Run 2-3 targeted tavily web searches directly (no acquisition agent)
2. Download any promising results via `download <src-id> --url <url>`
3. Spawn 1-2 reader agents for the best new sources
4. Log findings directly
5. Log the skip decision and rationale in journal.md

**When to use light vs. full gap-mode:**
- Light: The gap is about topic recency (AI deepfakes, voice cloning — sparse academic literature). Web sources and preprints are the best available evidence.
- Full: The gap is about search coverage (papers exist in well-connected citation networks but weren't found). Academic providers and citation chasing will find them.
```

### Why
The acquisition agent is designed for academic literature with citation networks. For emerging topics, its strength (citation chasing, provider diversity, recovery cascade) doesn't help — the papers don't exist yet. Direct tavily searches from the orchestrator find the same web sources in 2-3 tool calls instead of spawning an Opus agent for 50+ minutes.

---

## 4. Source Quality Report in Synthesis Handoff (Data Flow)

### Problem
The synthesis-writer had to reconstruct source quality information from the handoff JSON and its own reads of metadata files. The orchestrator's quality report (written to journal.md) was the most accurate tally but wasn't directly available to the writer.

### Fix
**File: `skills/deep-research/scripts/state.py`** — In the `summary --write-handoff` command, include a `source_quality_report` section in the output JSON:

```json
"source_quality_report": {
  "on_topic_with_evidence": {"count": 21, "ids": ["src-012", ...]},
  "abstract_only_relevant": {"count": 4, "ids": ["src-016", ...]},
  "degraded_unread": {"count": 1, "ids": ["src-098"]},
  "mismatched": {"count": 16, "ids": ["src-044", ...]},
  "reader_validated": {"count": 5, "ids": ["src-004", ...]}
}
```

This is already available from `audit` — just needs to be included in the handoff.

**File: `skills/deep-research/SKILL.md`** — In step 15a, tell the orchestrator to mention the quality report is in the handoff file so the writer uses it for the Methodology section.

**File: `agents/synthesis-writer.md`** — Add instruction to use `source_quality_report` from the handoff JSON for the Methodology section's source counts, rather than inferring from source metadata.

### Why
The Methodology section's accuracy depends on knowing exactly how many sources were deeply read vs. abstract-only vs. mismatched. Currently this requires the writer to re-derive it from metadata files, which is error-prone and token-expensive.

---

## 5. Abstract-Only Source Utilization (New Feature)

### Problem
16 abstract-only sources had potentially useful information (especially for thin questions like Q6 individual differences and Q3 voice synthesis), but were completely excluded from findings extraction. Structured abstracts contain methods, sample sizes, and key results — enough for 1-2 findings per source.

### Fix
**File: `skills/deep-research/SKILL.md`** — After the main reader batch (step 7) and before findings-loggers (step 10), add a step:

```
### Step 9b: Abstract-based findings for thin questions (optional)

If any question has < 5 findings after step 10's findings-loggers complete, and there are abstract-only sources relevant to that question:

1. Read the metadata JSON for each relevant abstract-only source (`sources/metadata/src-NNN.json`)
2. If the abstract contains a clear empirical result (sample size, effect, conclusion), log a finding directly via `state log-finding` with the caveat "Based on abstract only; full methodology not verified"
3. Cap at 2-3 abstract-based findings per question — these supplement, not replace, deep-read evidence

Do NOT spawn reader agents for abstract-only sources — the metadata JSON already contains the abstract, and there's no content file to read.
```

**File: `agents/findings-logger.md`** — Add instruction that findings-loggers may also read `sources/metadata/src-*.json` (not just `notes/src-*.md`) when the supervisor explicitly directs them to extract from abstracts for thin questions. Include the metadata path pattern in the "How to work" section.

### Why
Abstract-based findings are lower-confidence but better than nothing for thin questions. They're already in the methodology section as "abstract-only sources" — extracting findings from them makes that designation more useful. The cost is near-zero (metadata JSON is already on disk, no agent spawn needed).

---

## 6. Prevent Background Task Leakage from Subagents (Guard Rail)

### Problem
The source-acquisition agent spawned background download tasks (`run_in_background: true` on Bash calls) that completed after the report was already written. These task notifications appeared in the orchestrator's context as noise. The acquisition agent doesn't have the `TaskOutput` tool, so it can't retrieve background results — making them pure waste.

### Fix
**File: `agents/source-acquisition.md`** — Rule 4 already says "Never sleep-poll or background commands" and explains why. But the agent still did it. Strengthen the rule:

```
4. **Never background commands — they are irrecoverable.** Don't set `run_in_background: true` on any Bash call. You don't have the TaskOutput tool, so you cannot retrieve background results — they're lost. If a command is slow (e.g., `recover-failed`), set `timeout: 600000` instead. Background tasks also leak notifications into the orchestrator's context as noise after you've returned.
```

Add the word "irrecoverable" — the current phrasing explains the mechanism but doesn't convey the severity. The agent may be reasoning "I'll just kick this off for later" without understanding that "later" doesn't exist for it.

### Why
This is a prompt clarity issue, not an architecture issue. The agent has the information it needs (rule 4) but the framing doesn't prevent the behavior under time pressure.

---

## Non-Changes (Considered but Rejected)

### Parallel pre-read validation
Considered spawning a subagent for batch pre-read validation instead of doing it inline. Rejected: the orchestrator's inline `Read` calls are cheap (30 lines × 43 sources = ~1,300 lines total), complete in seconds, and keep quality decisions in the orchestrator's context where they inform reader allocation. An agent would add latency and move the quality decision to a place where it's harder to act on.

### Automated gap-mode skip decision
Considered adding a flag in `state audit` that automatically recommends skip/run for gap-mode based on findings counts and coverage scores. Rejected: the skip decision is a research judgment that depends on context the audit can't capture (is Q7's thin coverage because the topic is emerging, or because we searched poorly?). The current approach — explicit criteria in SKILL.md with a journal.md rationale requirement — keeps the human-in-the-loop.

### Reader agents for metadata-only sources
Considered spawning lightweight reader agents that just read metadata JSON and write thin notes. Rejected: this adds agent overhead (spawn, context, return) for something the findings-logger can do directly from the metadata file. The abstract-based findings approach (item 5 above) is cheaper.
