# Deep Research Pipeline Improvement Plan

Based on the uncanny valley session (2026-03-13), this plan addresses six areas where the pipeline underperformed despite having mitigations in place. Each section explains what exists, why it didn't work, and the proposed fix.

---

## 1. Download Content Mismatch Detection

### Problem
~40% of downloaded content was the wrong paper. Three validation layers exist but the mismatch rate remains unacceptably high.

### What exists
- **Layer A** (`quality.py:check_content_mismatch`): Title keyword matching + author surname matching + abstract keyword overlap (20% threshold). Runs at download time.
- **Layer B** (`source-acquisition.md` §Post-download content validation): Agent reads first 10 lines of top 20-30 sources. Manual spot-check.
- **Layer C** (SKILL.md step 6): Orchestrator reads first 30 lines of each candidate before spawning readers.

### Why it didn't work
Layer A's keyword approach fails when: (a) titles share common domain words ("uncanny valley" appears in geology, law, and game design papers), (b) metadata has sparse/missing abstracts (common for CORE and OpenAlex), or (c) author names are common. The `title_hits < 3` threshold on the abstract gate (line 238-240 of quality.py) is too permissive — 2 hits from generic words passes papers that are completely off-topic.

Layer B only checks the top 20-30 sources, letting lower-ranked mismatches through. Layer C catches them but by then download bandwidth and triage effort are wasted.

### Proposed fix

**A. Add brief-keyword content check in `quality.py`.** After the existing title/author/abstract checks, add a new gate: check whether the first 2000 chars of content contain *any* of the brief's domain-specific keywords. This is passed down from the `--brief-keywords` flag that's already threaded through the search pipeline.

Implementation: `check_content_mismatch()` gains an optional `brief_keywords: list[str]` parameter. If provided, check how many appear in `text[:2000]`. If zero brief keywords match AND title_hits < 3, flag as mismatched.

**Why this helps:** The brief keywords are the highest-signal domain terms (e.g., "uncanny", "perception", "humanoid", "eeriness"). A paper about alpine tree line formation contains none of them. This catches the class of mismatches that keyword matching misses — off-topic papers that slip through because they share generic words with the target title.

**B. Thread `brief_keywords` through `download.py`.** The brief is already in state.db after `set-brief`. At download time, `download.py` can read the brief's scope/questions, extract keywords, and pass them to `check_content_mismatch()`. No new CLI flags needed — the brief is in the database.

**C. Lower the abstract-overlap threshold.** Change `title_hits < 3` to `title_hits < 2` in the abstract gate (quality.py line 239). Two generic keyword hits from a wrong paper is the most common false-negative pattern.

### Files to change
- `skills/deep-research/scripts/_shared/quality.py` — add `brief_keywords` parameter to `check_content_mismatch()`, add brief-keyword gate, lower abstract threshold
- `skills/deep-research/scripts/download.py` — read brief keywords from state.db, pass to mismatch check

### Risk
False positives (flagging correct papers as mismatched) if brief keywords are too generic. Mitigated by requiring zero brief keyword hits, not just low overlap — a paper that's truly on-topic will contain at least one domain term in its first 2000 chars.

---

## 2. Quality Flag Granularity

### Problem
The `degraded` quality flag is set for both "PDF conversion was imperfect but content is fully readable" and "actual paywall stub / garbled content." The audit warns "do not claim deep reading" for sources that were successfully deep-read (src-054, src-060, src-065, etc. in this session), creating noise that undermines trust in the audit.

### What exists
- Four flags: `ok`, `abstract_only`, `degraded`, `mismatched` (state.py line 2500)
- `quality.py:assess_quality()` sets degraded for: low alpha ratio, few sentences, low linebreak density, high non-alphanumeric ratio, paywall markers
- The audit treats all `degraded` sources identically

### Why it didn't work
PDF raw-text fallback (the `<!-- WARNING: PDF conversion fell back to raw text extraction -->` header) often produces content that passes all quality thresholds — the text is readable, has good alpha ratio, plenty of sentences — but was flagged `degraded` during initial download before quality checks ran, or a minor heuristic (linebreak density) triggered on the raw extraction format.

The reader agent successfully extracts content, writes a detailed note, and returns `status: "ok"` — but the state.db quality flag was never updated. The audit reads state.db, not reader manifests.

### Proposed fix

**A. Add `reader_validated` quality flag.** When the orchestrator calls `mark-read --id src-NNN` after a reader returns with `status: "ok"`, automatically upgrade the source's quality from `degraded` to `reader_validated` in state.db.

Implementation: In `state.py`'s `mark-read` handler, check if the source currently has `quality = "degraded"` AND a note file exists in `notes/`. If both true, set quality to `reader_validated`.

**B. Update audit to distinguish reader-validated from truly degraded.** The audit warning "do not claim deep reading" should only fire for sources that are `degraded` AND NOT `reader_validated`. Reader-validated sources can be claimed as deep reads.

**C. Split degraded reasons in audit output.** Instead of a flat `degraded_quality` array, return:
```json
{
  "degraded_unread": ["src-074", "src-098"],
  "reader_validated": ["src-054", "src-060", "src-065"]
}
```

### Files to change
- `skills/deep-research/scripts/state.py` — add `reader_validated` to quality choices, update `mark-read` to auto-upgrade, update `audit` output structure
- `skills/deep-research/SKILL.md` — update audit interpretation guidance
- `agents/source-acquisition.md` — no changes (doesn't interact with reader_validated)

### Risk
Low. The `mark-read` + note-file-exists combination is a strong signal that content was usable. The only edge case is a reader that returns `"ok"` for thin content — but reader.md's status determination rules (lines 64-81) explicitly address this.

---

## 3. Recovery Search Budget and Domain-Aware Early Exit

### Problem
61 of 83 searches were recovery attempts (mostly CORE queries) with negligible yield for psychology literature. Recovery searches aren't governed by the same budget discipline as primary searches.

### What exists
- `source-acquisition.md` line 55: "Aim for 15-25 total searches in initial mode"
- `recover-failed` command loops until all eligible sources are attempted
- `--min-relevance` and `--title-keywords` filters exist but only filter which sources are *attempted*, not total recovery effort

### Why it didn't work
The 15-25 budget applies to primary searches. Recovery runs as a separate phase with no budget cap — `recover-failed` tries every eligible failed source across multiple channels (CORE title search, Tavily, DOI landing page). For psychology papers behind APA/Wiley paywalls, CORE almost never has them, and each attempt costs a search. With 50+ failed sources eligible, recovery spirals to 50-60+ searches with near-zero yield.

The `source-acquisition.md` guidance (lines 149-158) says to use `--min-relevance` and `--title-keywords` to reduce recovery candidates, but the agent interpreted these as quality filters on *which* sources to try, not as a mechanism to limit total recovery effort.

### Proposed fix

**A. Add `--max-attempts N` flag to `recover-failed`.** Default 15. After N total recovery attempts across all channels, stop and return results so far. This is the hard budget cap that's missing.

**B. Add domain-aware channel skipping to `recover-failed`.** Track per-channel success rates during recovery. If a channel (e.g., CORE) has 0 successes after 5 attempts, skip it for remaining sources. This is the early-exit that prevents 50 failed CORE queries in a row.

Implementation: In `state.py`'s `recover-failed` handler, maintain a dict `{channel: {"attempts": N, "successes": M}}`. After each attempt, check if the channel's success rate is 0% with 5+ attempts. If so, skip that channel for remaining sources and log the skip.

**C. Update `source-acquisition.md` to frame recovery as budgeted.** Add: "Recovery has a budget too. Default --max-attempts 15. If CORE returns 0 results after 5 tries, stop using CORE for this session — the papers aren't there. Switch to Tavily author-page searches for the remaining high-priority failures."

### Files to change
- `skills/deep-research/scripts/state.py` — add `--max-attempts` flag, add per-channel success tracking and early-exit
- `agents/source-acquisition.md` — add recovery budget guidance, update CLI reference

### Risk
Some recoverable sources may be missed by the budget cap. Mitigated by: (a) the cap applies per channel, so switching channels is still allowed, (b) 15 attempts covers the highest-priority sources, (c) gap-mode can do targeted recovery later.

---

## 4. Findings Deduplication Across Questions

### Problem
84 findings from 17 sources, but the distinct evidence base was closer to 40-50 unique claims. Cross-question duplicates aren't caught because each findings-logger runs in isolation.

### What exists
- Within-question dedup rules in `findings-logger.md` lines 42-47
- Warning about the problem in `findings-logger.md` line 49
- Each logger runs in parallel with no shared state

### Why it didn't work
The dedup rules only apply within a single question's scope. A finding about "categorical perception at the 60% boundary" is genuinely relevant to Q1 (theories), Q4 (categorical perception), and Q5 (methodology), so three independent loggers each log it. The rules say "if two sources report the same conclusion independently, that's one finding with two source citations" — but they don't say "if another logger already logged this finding for a different question, skip it."

Parallel execution makes cross-question dedup impossible without shared state or a post-processing step.

### Proposed fix

**A. Add a `deduplicate-findings` subcommand to `state.py`.** After all findings-loggers complete, run `state deduplicate-findings` which:
1. Groups findings by source citations (findings citing the same source set are candidates)
2. Computes text similarity (simple token overlap ratio) between candidate pairs
3. Merges findings with >70% token overlap: keeps the one with more source citations, adds a `also_relevant_to` field with the other question(s)
4. Returns: `{"merged": N, "remaining": M, "original": K}`

**B. Call this from the orchestrator after step 10 (findings-loggers), before step 11 (gap review).** One additional CLI call, no agent needed.

**C. Update `findings-logger.md` to add cross-reference hints.** When a logger encounters a finding that's primarily about another question, instead of logging a full finding, it should log a lightweight cross-reference: `--text "See Q4 findings on categorical perception boundary — also relevant here" --sources "" --question "Q1: ..."`. This gives the synthesis-writer the connection without creating a duplicate finding. Add guidance: "If a finding's primary evidence is about another question's core topic (e.g., you're logging for Q1 but the finding is really about Q4's categorical perception mechanism), log a 1-sentence cross-reference instead of a full finding."

### Files to change
- `skills/deep-research/scripts/state.py` — add `deduplicate-findings` subcommand
- `agents/findings-logger.md` — add cross-reference guidance
- `skills/deep-research/SKILL.md` — add dedup step after findings-loggers (between steps 10 and 11)

### Risk
Over-merging: two genuinely distinct findings from the same sources could be merged if they use similar vocabulary. Mitigated by: (a) the 70% threshold is conservative, (b) only candidates with overlapping source citations are compared, (c) merged findings preserve both question associations.

---

## 5. Citation Chasing Enforcement

### Problem
5 citation traversals out of 83 total searches (6%), well below the 30-50% target for a literature review topic. The guidance exists but wasn't enforced.

### What exists
- `source-acquisition.md` lines 63-74: Detailed citation chasing requirements — bidirectional traversal, minimum 3 traversals, 30-50% allocation for literature review topics, fallback tree
- SKILL.md line 51: "Validate citation chasing in the manifest... If the agent ran only 1-2 traversals, push back in gap mode"
- The manifest includes a `citation_chasing` block

### Why it didn't work
The 30-50% target is prose guidance that competes with the agent's drive to move through the pipeline. When broad searches return hundreds of sources, the agent sees "coverage" and moves to triage/download rather than investing in traversals. The minimum-3-traversals requirement was met (5 > 3), but the 30-50% aspiration was ignored.

The orchestrator's validation (SKILL.md line 51) says to "push back in gap mode" — but I correctly judged gap mode wasn't worth the cost. So the enforcement mechanism (gap-mode pushback) was bypassed by a legitimate skip decision.

### Proposed fix

**A. Make the `state manifest` command compute and report the citation-chasing ratio.** Add `citation_chasing_ratio` to the manifest output: `traversals_run / (total_searches - recovery_searches)`. This makes the ratio visible without manual calculation.

**B. Add a manifest warning when the ratio is below threshold.** If the brief contains 5+ questions (indicating a review-depth topic) and the citation-chasing ratio is below 25%, the manifest should include a `warnings` array with: `"Citation chasing ratio (X%) below recommended minimum (25%) for review-depth topics. Consider additional traversals before proceeding."` This surfaces the gap even when the orchestrator has already decided to skip gap-mode.

**C. Update `source-acquisition.md` with a hard gate.** After round 2, before proceeding to round 3+, check: "Have I run at least `floor(searches_so_far * 0.25)` citation traversals?" If not, run more traversals before moving to refinement searches. This converts the aspiration into a checkpoint.

### Files to change
- `skills/deep-research/scripts/state.py` — add `citation_chasing_ratio` computation to `manifest` subcommand, add ratio-based warning
- `agents/source-acquisition.md` — add hard checkpoint between rounds 2 and 3

### Risk
Low. Worst case is a few extra citation traversals that return low-yield results, but citation chasing is the highest-precision search strategy for connected literatures — the expected failure mode is too few traversals, not too many.

---

## 6. SKILL.md and Prompt Organization

### Problem
SKILL.md is 377 lines; source-acquisition.md is 474 lines. Total prompt surface across all agents is ~1200+ lines. The "why" explanations are valuable but some sections read as post-incident retrospectives that could live elsewhere.

### What exists
- Delegation keeps agent-specific detail out of SKILL.md
- Step-by-step numbered workflow
- Cross-references to agent prompts
- "Why" blocks after each decision point

### Why it's a concern (not a failure)
This didn't cause a failure in this session — the prompts were followed. But the length increases the risk that under context pressure, the model skims rather than reads closely. The longest sections are incident-specific narratives (e.g., "the temperament session's 32% mismatch rate," "the temperament session's SUGGESTIONS.md identified...") that provide context for decisions but aren't needed on every run.

### Implemented fix (simplified from original plan)

LESSONS.md was prototyped but dropped — it added indirection without clear benefit. The principle-based "why" blocks inline are sufficient; the agent either internalizes the principle or it doesn't, and referencing a separate incident file won't change behavior.

**What was done:**
- Replaced ~5 incident-specific narratives in SKILL.md with general principle statements (e.g., "The temperament session's 32% mismatch rate proved..." → "Download-time keyword checks miss topical mismatches where papers share vocabulary...")
- Replaced ~4 incident-specific narratives in source-acquisition.md similarly
- All principle-based "why" blocks kept inline
- Net reduction: 9 fewer lines, all session-specific references removed

### Files changed
- `skills/deep-research/SKILL.md` — incident narratives replaced with principle statements
- `agents/source-acquisition.md` — same treatment

---

## Implementation Order

Recommended sequence based on impact and independence:

1. **Recovery budget** (§3) — standalone code change, immediate token savings
2. **Download mismatch detection** (§1) — standalone code change, highest impact on data quality
3. **Quality flag granularity** (§2) — standalone code change, fixes audit noise
4. **Findings dedup** (§4) — new subcommand + prompt updates, moderate impact
5. **Citation chasing enforcement** (§5) — manifest computation + prompt update, low risk
6. **Prompt organization** (§6) — editorial, no code changes, lowest urgency
