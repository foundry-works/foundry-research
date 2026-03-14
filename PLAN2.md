# Deep Research Revision Pipeline Improvements — Plan

## Context

Observations from the 2026-03-14 revision of the "uncanny valley" research report. This was the first run of the revision pipeline on a real session: synthesis-reviewer + research-verifier (parallel) → verifier gating → dedup → style-reviewer → combined reviser → post-revision validation. 14 source notes, 77 metadata files, ~3,850-word report. The pipeline produced 30 issues (12 accuracy, 18 style), resolved 23, correctly skipped 5 opportunistic, and validated all edits on first check.

This plan captures what worked, what didn't, and targeted improvements.

---

## What Worked Well (Strengths to Preserve)

### 1. Parallel reviewer launch with post-hoc gating
The synthesis-reviewer (~2.5 min) and research-verifier (~3 min) ran concurrently with ~30s wall-clock difference. First-pass always needs full verification, so the parallel-then-gate design avoids the ~2.5 min penalty of sequential launch. **This is the right default — protect it.**

### 2. Canonical issue schema with reviewer-assigned IDs
Each reviewer assigns its own prefix (`review-N`, `verify-N`, `style-N`) and outputs the same JSON schema. The orchestrator no longer translates between formats or assigns IDs — a previous error-prone step. The reviser received a single ordered list and processed it cleanly.

### 3. Dedup caught a real duplicate
review-4 and verify-1 independently flagged the same "77%" claim with different framings. Without dedup, the reviser would have tried to edit already-changed text and burned tokens on error recovery. The merge rule (prefer more specific fix, elevate severity) produced the right combined issue.

### 4. Post-revision validation was clean
23/23 edits confirmed on first check — `old_text_snippet` absent and `new_text_snippet` present for every resolved issue. No retries needed. This suggests the reviser's edit planning (group nearby issues, process in priority order) is working well.

### 5. Verifier catches genuinely subtle problems
The verifier found: a Bayesian posterior probability written as a frequentist p-value, a category label narrowed beyond what the source actually measured, an unsupported "exclusively" qualifier, and a voice-specific finding overgeneralized to all synthesized voices. These are the errors that matter most — factually plausible but imprecise claims that erode report credibility.

### 6. Style reviewer's jargon detection is valuable
Identified 6 undefined statistical terms (rc, d', OR, gamma, Cronbach's alpha, semantic differential) and 3 unexplained neuroanatomical terms. These are genuine accessibility barriers that the accuracy reviewers don't flag because the terms are used correctly — just not explained.

---

## What Didn't Work Well

### 1. Synthesis-reviewer emitted a high-severity no-op (review-1)

The reviewer flagged an evidence level tag as misattributed (`high` severity) but its own suggested fix said "no change needed." The reviser correctly recognized this and skipped the edit, but the issue consumed a high-severity slot and influenced verifier gating (which counts high-severity reviewer issues to decide full/targeted/skip mode).

**Root cause:** The reviewer's severity calibration doesn't distinguish "I noticed something worth checking" from "this error materially changes a conclusion if left unfixed." The prompt defines severity levels but doesn't enforce that `high` requires a substantive fix.

**Impact:** Minor this run (gating was already full for first-pass). On subsequent passes, a false high could trigger full verification when targeted would suffice — wasting ~5 min and significant tokens.

### 2. Cross-reviewer location overlap creates fragile edit sequences

review-2 and style-5 both targeted the same d'/20% sentence in Section 4 — review-2 about the Bayesian model characterization, style-5 about the lack of d' definition. These are different problems (not duplicates), so dedup correctly kept both. But the reviser had to coordinate two independent edits to the same sentence, which succeeded only because accuracy edits processed first and the style edit targeted a different clause.

**Root cause:** The dedup step handles semantic duplicates but doesn't warn about co-located non-duplicates. The reviser groups "nearby" issues heuristically but has no explicit signal that two issues target the same sentence.

**Impact:** This time it worked. On a denser report with more overlapping issues, this will cause edit failures (old_string no longer matches after a prior edit changed the sentence), triggering the retry mechanism and burning tokens.

### 3. Opportunistic skip rate was high (5/7 skipped)

The adaptive filtering included 7 low-severity style issues as "opportunistic" (total was 23, under the 25 threshold). The reviser correctly skipped 5 of them because there were no nearby higher-priority edits. The cost: the reviser read, planned around, and decided to skip 5 issues — not huge, but non-zero token waste with no output.

**Root cause:** The "under 25" threshold determines inclusion, but the actual skip rate depends on edit geography — how many clean passages have nearby higher-priority edits. For a well-structured report where issues are spread across sections, most passages with only a low-severity issue will be "clean" from the reviser's perspective.

**Impact:** ~500-1000 tokens wasted on planning around issues that will be skipped. Scales with report length and issue count.

### 4. Style reviewer's section-skip instruction was brittle

The orchestrator told the style reviewer to skip specific sections using natural-language descriptions ("Section 3 paragraph 1," "Section 4 paragraphs about AI faces"). This worked this time but depends on the style reviewer correctly interpreting prose descriptions and matching them to report structure.

**Root cause:** No structured mechanism to pass "already-flagged locations" from accuracy reviewers to the style reviewer. The orchestrator manually describes sections to skip in the agent launch prompt.

**Impact:** If the style reviewer misinterprets a skip instruction, it flags a passage that's about to be rewritten for accuracy — wasting a reviser edit attempt and potentially creating a conflict.

### 5. No prior-revision awareness across runs

Each revision pass starts fresh. If the user runs `/deep-research-revision` twice on the same report, the second run's reviewers will re-examine all previously fixed text, confirm most edits are fine, and find few new issues — but at full token cost for all three reviewers.

**Root cause:** The revision pipeline has no concept of "what was already reviewed and fixed." The verifier gating checks for a prior `verification-report.md` to decide full/targeted/skip, but the reviewers themselves don't know which issues were already resolved.

**Impact:** Iterative revision (run → user reviews → run again with feedback) pays full reviewer cost each time. For a ~4,000-word report, that's ~300K tokens across three reviewers for diminishing returns.

### 6. The orchestrator skill prompt doesn't specify how to build the style reviewer's skip list

The SKILL.md describes what the style reviewer should skip ("sections already flagged for substantive changes") but doesn't specify *how* to communicate this. The orchestrator has to improvise — this run, it listed specific sections by prose description in the agent launch prompt. A different orchestrator interpretation might pass line numbers, or issue IDs, or nothing at all.

**Root cause:** The skill prompt explains the *why* (style fixes on text about to be rewritten are wasted) but not the *how* (what format the skip information should take, where it goes in the agent prompt).

---

## Proposed Improvements

### 1. Reviewer Severity Calibration (HIGH PRIORITY)

**Problem:** The synthesis-reviewer emits high-severity issues that require no fix, inflating the count that drives verifier gating decisions.

**Fix:**
- **File: `agents/synthesis-reviewer.md`** — Add to the severity definition section: "A `high` severity issue MUST have a substantive `suggested_fix` that changes report text. If your analysis reveals something worth noting but no text change is needed, either (a) downgrade to `low` with a note that no fix is required, or (b) omit it from the `issues` array and mention it in a separate `observations` section. The orchestrator uses high-severity issue count to make gating decisions — false highs waste downstream resources."

**Why:** The reviewer needs to understand that severity has downstream consequences beyond just prioritization. A false high on a subsequent pass could trigger full verification (5 min, ~90K tokens) when skip mode would suffice. Making the consequence explicit helps the reviewer calibrate — it's not just a label, it's a control signal.

### 2. Co-Location Warnings in Dedup (HIGH PRIORITY)

**Problem:** Two different issues targeting the same sentence create fragile edit sequences that may fail when the first edit changes surrounding text.

**Fix:**
- **File: `skills/deep-research-revision/SKILL.md`** — In the dedup procedure (Step 2b), add after step 3 (merge duplicates): "4. **Flag co-located non-duplicates.** After dedup, scan for remaining issues that target the same paragraph. For each co-located group, add a `co_located_with` field listing the other issue IDs (e.g., `'co_located_with': ['style-5']` on review-2). The reviser uses this signal to process co-located issues as a single atomic edit rather than sequential independent edits."
- **File: `agents/report-reviser.md`** — Add to the planning step: "When issues have a `co_located_with` field, plan a single combined edit that addresses all co-located issues at once. Read the target passage, compose a replacement that fixes all flagged problems, and apply one Edit call. This prevents the second edit's `old_string` from failing because the first edit changed the surrounding text."

**Why:** The current architecture handles this through the reviser's "group nearby issues" heuristic, which is implicit and unreliable. An explicit `co_located_with` signal turns a fragile heuristic into a deterministic grouping. The cost is ~10 lines of orchestrator logic and ~5 lines of reviser instruction.

### 3. Structured Skip List for Style Reviewer (HIGH PRIORITY)

**Problem:** The orchestrator improvises how to tell the style reviewer which sections to skip, using brittle prose descriptions.

**Fix:**
- **File: `skills/deep-research-revision/SKILL.md`** — In Step 3, replace the current prose instruction with: "Build a `skip_locations` list from the accuracy issues: for each high or medium severity accuracy issue, extract its `location` field. Pass this list to the style reviewer in the agent prompt as a JSON array. Example: `'skip_locations': ['Section 3, paragraph 1', 'Section 4, paragraph 2']`."
- **File: `agents/style-reviewer.md`** — Add: "You will receive an optional `skip_locations` array. Do not flag style issues whose location matches any entry in this array — those passages are being edited for accuracy and style fixes would conflict. If a paragraph partially overlaps a skip location, err on the side of skipping."

**Why:** JSON array is unambiguous — no interpretation needed. The style reviewer checks each potential issue's location against the list rather than trying to parse prose descriptions. The orchestrator's job is mechanical (extract locations from accuracy issues) rather than interpretive (describe sections in words).

### 4. Smarter Opportunistic Inclusion (MEDIUM PRIORITY)

**Problem:** The "include lows when under 25 total" threshold includes issues the reviser will almost certainly skip, wasting planning tokens.

**Fix:**
- **File: `skills/deep-research-revision/SKILL.md`** — In Step 3, replace the current threshold with: "Include a low-severity style issue as opportunistic ONLY if its location matches the same section as an existing high or medium severity issue (accuracy or style). Check by comparing the section identifier (e.g., 'Section 3') in the low-severity issue's location against all higher-priority issues' locations. If no match, exclude it — the reviser would skip it anyway."

**Why:** This is a pre-filter that mirrors the reviser's own skip logic. Instead of sending 7 lows and having the reviser skip 5, we send only the 2 that have nearby edits. The reviser processes a smaller list, plans faster, and produces fewer "skipped" manifest entries. The tradeoff: we might occasionally exclude a low that the reviser would have applied. But the reviser's "nearby" heuristic is generous — if the issue isn't even in the same section, it was never going to be applied.

### 5. Prior-Revision Manifest for Iterative Runs (MEDIUM PRIORITY)

**Problem:** Second revision runs pay full reviewer cost re-examining already-fixed text.

**Fix:**
- **File: `skills/deep-research-revision/SKILL.md`** — In Step 1, add: "Check for an existing `revision/revision-manifest.json` from a prior run. If it exists, read it and pass the list of resolved issue IDs to each reviewer in their launch prompt."
- After Step 4 (revision), add: "Write the reviser's manifest to `revision/revision-manifest.json` as structured JSON (issue ID, status, location, fix applied)."
- **File: `agents/synthesis-reviewer.md`** — Add: "You may receive a `prior_resolved` list of issue IDs and their fixes from a previous revision pass. Do not re-flag issues that match a prior resolved entry unless you have new evidence that the fix was insufficient or introduced a new problem. Focus your review on: (a) text that was changed by the prior revision (check for introduced errors), (b) text that was not previously reviewed, (c) any new user feedback."
- Apply the same instruction to `agents/research-verifier.md` and `agents/style-reviewer.md`.

**Why:** The manifest is already produced — this just persists it and feeds it back. Reviewers that see "this claim was already verified and corrected" can skip it in seconds rather than re-reading source notes to confirm it. Expected token savings on second pass: ~40-60% across all three reviewers.

### 6. Verifier Gating: Exclude No-Op Highs from Count (LOW PRIORITY)

**Problem:** The gating logic counts high-severity reviewer issues to decide full/targeted/skip verification. A no-op high (like review-1) inflates this count.

**Fix:**
- **File: `skills/deep-research-revision/SKILL.md`** — In the verifier gating section, add: "When counting high-severity reviewer issues for gating, exclude any issue whose `suggested_fix` indicates no text change is needed (e.g., 'no change needed,' 'correctly placed,' 'no edit required'). These are observations, not actionable issues, and should not influence the verification mode decision."

**Why:** This is a belt-and-suspenders fix alongside improvement 1 (severity calibration). Even if the reviewer is better calibrated, edge cases will still produce no-op highs. Filtering them at the gating step prevents downstream waste. The cost is one sentence of orchestrator logic.

---

## Non-Changes (Considered but Rejected)

### Run style reviewer in parallel with accuracy reviewers
Considered launching all three reviewers simultaneously instead of accuracy-first → style-second. Rejected: the style reviewer needs to know which sections have accuracy issues so it can skip them (improvement 3). Running in parallel would require the style reviewer to flag everything and then the orchestrator to post-filter — adding dedup complexity for ~2-3 minutes of wall-clock savings. The sequential design is simpler and the latency cost is acceptable.

### Have the reviser do its own dedup
Considered removing orchestrator-level dedup and letting the reviser handle duplicates during its planning step. Rejected: the reviser's "group nearby issues" heuristic partially addresses this, but it costs tokens to read, plan around, and attempt edits on duplicates. Removing them before handoff is cheaper and more reliable. The orchestrator has the full issues list in context — the reviser would have to re-derive the same information.

### Structured reviewer output (beyond the issues array)
Considered having reviewers produce additional structured metadata (confidence scores, evidence chain, affected conclusions). Rejected: the current `issues` array with severity/location/description/suggested_fix is sufficient for the reviser's needs. Additional metadata would increase reviewer token cost without clear downstream use — the reviser edits text, it doesn't weigh evidence chains.

### Automatic second revision pass on failed validations
Considered automatically launching a second full revision cycle (not just a retry of failed edits) when validation failures exceed a threshold. Rejected: the current one-retry cap is the right default. If an edit fails twice, the problem is likely deeper (ambiguous text, conflicting edits, or removed content) and needs human judgment. Automatic escalation risks a loop that wastes tokens without converging. The user can always run `/deep-research-revision` again with targeted feedback.
