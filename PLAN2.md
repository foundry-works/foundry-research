# Revision Pipeline Improvement Plan

## Context

After running `/deep-research-revision` on the uncanny valley session (2026-03-13), we identified six areas where the revision pipeline's orchestration layer underperforms despite well-designed individual agents. The agents themselves (synthesis-reviewer, research-verifier, style-reviewer, report-reviser) have good scope, guardrails, and output formats. The problems are in how the orchestrator coordinates them: no conditional logic beyond binary quick/full mode, no inter-agent communication, no deduplication, no post-revision validation, no cost-tiering, and inconsistent output paths.

This plan addresses six improvements to `skills/deep-research-revision/SKILL.md` and the four agent prompts.

---

## 1. Merge Reviser Passes / Cost-Tier the Style Reviser

### Problem
Two separate Opus-tier reviser launches (~110k tokens each) when the reviser processes both lists identically. The `pass_type` field ("accuracy" vs "style") changes nothing in the reviser's behavior — it's audit metadata, not a behavioral switch.

### What exists
- SKILL.md steps 3 and 5 launch separate reviser agents
- `report-reviser.md` accepts `pass_type` but processes all issues the same way
- The rationale at SKILL.md line 145 justifies sequential *reviews* (accuracy before style), not sequential *revisions*

### Proposed fix

**A. Combine into a single reviser pass.** After the style reviewer returns, merge the accuracy and style issues into one list with accuracy issues first (preserving priority order). Launch one reviser with the combined list and `pass_type: "combined"`. The reviser already handles mixed-severity lists — it processes by priority.

**B. If keeping two passes, downgrade the style reviser to Sonnet.** Style edits are mechanical (expand acronyms, split paragraphs, convert prose to lists). The reviser prompt doesn't need Opus-tier reasoning for these. Add guidance in SKILL.md: "For the style pass, use `model: sonnet`."

**Recommendation:** Option A (single combined pass). It saves an entire agent launch and the reviser's existing priority ordering handles the mix naturally. The manifest already distinguishes issues by ID prefix (review-N, verify-N, style-N), so auditability is preserved.

### Files to change
- `skills/deep-research-revision/SKILL.md` — merge steps 3+5 into a single reviser launch after both review passes complete; update delivery step
- `agents/report-reviser.md` — add `"combined"` as a valid `pass_type`; note that accuracy issues should be processed before style issues within the combined list, with a "why" explaining that accuracy edits may change text targeted by style issues

### Risk
A very long combined issues list (30+) could hit context limits in the reviser. Mitigated by: revision sessions typically produce 15-25 total issues, well within budget. If the list exceeds 30, the orchestrator can split into two batches (first 20, then remainder).

---

## 2. Conditional Verifier Gating

### Problem
The verifier always runs in full mode regardless of the synthesis-reviewer's findings. In this session: 96k tokens, ~5 minutes, 10/14 confirmed, 1 net-new finding (also caught by the reviewer). The only conditional logic is the binary quick/full mode split.

### What exists
- SKILL.md lines 75-86: quick mode (user content feedback only) vs full mode (everything)
- Verifier prompt lines 26-34: good internal prioritization (specific numbers > study characterizations > absence claims)
- Verifier has optional "specific list of claims to verify" input (line 19) — but the orchestrator never uses it

### Proposed fix

**A. Add a "targeted verification" mode.** After the synthesis-reviewer returns, the orchestrator evaluates whether full verification is warranted:

- **Full verification** (current behavior): when the reviewer found 3+ high-severity issues, OR when user explicitly requests verification, OR when this is the first revision pass on the report
- **Targeted verification**: when the reviewer found 1-2 high-severity issues, pass those specific claims to the verifier (using the existing "specific list of claims" input) instead of letting it select 8-15 independently
- **Skip verification**: when the reviewer found 0 high-severity issues AND the report has been verified before (indicated by existence of `notes/verification-report.md` from a prior run)

**B. Add the decision logic to SKILL.md step 2.** After the synthesis-reviewer returns (but before collecting verifier results — since they're parallel, this means evaluating after both return), log the gating decision and adjust which verifier findings are used.

**Why not make them sequential (reviewer first, then conditionally launch verifier)?** The reviewer takes ~2 min, the verifier ~5 min. Running them in parallel saves ~2 min in the common case (full mode). Making them sequential saves tokens only in the skip/targeted cases, at the cost of always adding 2 min latency. Since "first revision of a new report" (the most common use) should always run full verification, parallel launch with post-hoc gating is the better default.

**C. For targeted mode, downgrade verifier to Sonnet when only checking local sources.** If all claims to verify have local notes available, Sonnet can do the cross-referencing. Reserve Opus + web search for claims where local sources are absent or insufficient.

### Files to change
- `skills/deep-research-revision/SKILL.md` — add gating logic after step 2 (both reviewers return), document the three modes, add "why" for the parallel-launch-with-post-hoc-gating decision
- `agents/research-verifier.md` — no changes needed (already accepts a specific claims list)

### Risk
Skip mode could miss errors the reviewer didn't catch. Mitigated by: skip only triggers when (a) the reviewer found 0 high issues AND (b) a prior verification exists. The prior verification provides a baseline, and the reviewer's 0-high finding suggests the report is stable.

---

## 3. Post-Revision Validation

### Problem
The orchestrator trusts the reviser's manifest at face value. No automated check confirms that edits actually landed. The reviser's "re-read after editing" instruction (line 122) is aspirational, not enforced. The manifest contains human-readable action descriptions but not machine-verifiable old/new strings.

### What exists
- Reviser prompt line 122: "Re-read after editing" guidance
- Reviser prompt line 114: "If an Edit fails, re-read and retry" error handling
- SKILL.md lines 139-141: "Check manifest for unresolved issues, verify report.md was updated"
- The reviser returns a manifest with `issue_id` and `action` (description), but not the literal text that was changed

### Proposed fix

**A. Extend the reviser manifest to include `old_text_snippet` and `new_text_snippet`.** For each edit, include the first 80 chars of the old and new strings. This makes the manifest machine-verifiable without bloating it. **Why 80 chars:** Long enough to be unique in a ~200-line report (avoiding false-positive grep matches), short enough to not bloat the manifest.

```json
{
  "issue_id": "review-1",
  "location": "Section 3, paragraph 2",
  "action": "Qualified NARS conclusion as instrument-specific",
  "old_text_snippet": "the uncanny valley effect is perceptual and automatic rather than shaped by lea...",
  "new_text_snippet": "the uncanny valley effect may not be shaped by the social-concern dimensions me..."
}
```

**B. Add a validation step in the orchestrator after the reviser pass.** For each resolved issue in the manifest, grep the report for `old_text_snippet`. If found, the edit didn't land — flag it.

**C. If any edits failed validation, re-launch the reviser with only the failed issues.** Cap at one retry. **Why one retry:** The most common failure mode is a prior edit changing surrounding context so the old_string no longer matches. One retry with the current file state fixes this. If it fails twice, the issue is likely a deeper problem (ambiguous old_string, conflicting edits) that needs human judgment, not more retries.

### Files to change
- `agents/report-reviser.md` — add `old_text_snippet` and `new_text_snippet` fields to the manifest format
- `skills/deep-research-revision/SKILL.md` — add validation step after reviser return, add retry logic

### Risk
Low. False positives (snippet appears elsewhere) are possible but unlikely for 80-char snippets. The one-retry cap prevents loops.

---

## 4. Standardize Output Paths

### Problem
Each agent prompt specifies an output path, but the orchestrator doesn't reference those paths — it tells agents where to write ad-hoc. In this session, the synthesis-reviewer wrote to `review_issues.md` (session root) instead of the prompt-specified `notes/review-report.md`. Only the verifier wrote to its specified path.

### What exists
- `synthesis-reviewer.md` line 61: "Write to `notes/review-report.md`"
- `research-verifier.md` line 58: "Write to `notes/verification-report.md`"
- `style-reviewer.md` line 68: "Write to `notes/style-review.md`"
- No path references in SKILL.md

### Proposed fix

**A. Add a `revision/` subdirectory convention.** Revision artifacts are distinct from original research notes — mixing them in `notes/` creates confusion about what came from readers vs. reviewers. Move all revision outputs to `{session}/revision/`:
- `revision/review-report.md`
- `revision/verification-report.md`
- `revision/style-review.md`

**B. Add an "Expected Agent Outputs" section to SKILL.md** listing these canonical paths. **Why explicit in SKILL.md:** The orchestrator doesn't read agent prompt files, so agent-defined conventions are invisible to it unless mirrored in the skill prompt.

**C. In agent launch prompts, do NOT override the output path.** Let agents write to their default locations.

### Files to change
- `skills/deep-research-revision/SKILL.md` — add expected outputs section
- `agents/synthesis-reviewer.md` — change output path to `revision/review-report.md`
- `agents/research-verifier.md` — change output path to `revision/verification-report.md`
- `agents/style-reviewer.md` — change output path to `revision/style-review.md`

### Risk
None. The revision skill is new (used once), no legacy expectations exist.

---

## 5. Issue Deduplication Before Reviser

### Problem
When both the synthesis-reviewer and verifier flag the same issue (as happened with the OFC claim), it appears twice in the combined list with different IDs, phrasings, and suggested fixes. The reviser has to realize they're the same, pick a fix, and handle the Edit tool failing on the second attempt.

### What exists
- SKILL.md assigns distinct ID prefixes (review-N, verify-N) but no dedup step
- Reviser prompt line 114: "If an Edit fails because text was already changed, re-read and retry" — reactive, not preventive
- Reviser prompt line 40: "Group nearby issues that affect the same paragraph" — planning advice that partially addresses this

### Proposed fix

**A. Add a dedup step in the orchestrator between collecting issues and launching the reviser.** When a reviewer issue and verifier issue target the same section/paragraph:

1. Merge into one issue, preferring the more specific suggested_fix. **Why prefer specific:** A fix that says "change X to Y" is immediately actionable. "Verify and correct" requires additional reading, costing tokens.
2. Note both sources in a `flagged_by` field. **Why:** Audit trail — dual-flagged issues have higher confidence.
3. Elevate severity to the higher of the two.

**B. Log merged count for the delivery summary** so the user knows dedup happened.

### Files to change
- `skills/deep-research-revision/SKILL.md` — add dedup step between issue collection and reviser launch

### Risk
Over-merging two different issues at the same location. Mitigated by: the orchestrator evaluates semantic overlap, not just co-location.

---

## 6. Style Reviewer Scope Reduction

### Problem
7 of 13 style issues were mechanical (expand acronyms, add glosses). The style reviewer's 5 dimensions mix mechanical checks (acronym expansion, filler phrases) with subjective judgment (paragraph focus, passive voice in context).

### What exists
- Style-reviewer.md: 5 dimensions with good "what's NOT an issue" guardrails
- Severity calibration distinguishing "substantially impairs readability" from "minor improvement"

### Proposed fix

**A. Add `mechanical` boolean to the style reviewer's issue format.**
- `mechanical: true` — acronym expansion, filler removal, sentence splitting. Pattern-matchable, no meaning risk.
- `mechanical: false` — paragraph focus, passive voice in context, list opportunities. Require understanding argument flow.

**Why this matters for the reviser:** Mechanical issues are safe to apply without re-reading the surrounding paragraph for meaning shifts. Judgment issues require the reviser to verify that the edit preserves argument flow. Distinguishing them lets the reviser allocate attention proportionally.

**B. Add prioritization guidance to style-reviewer.md:** scan judgment-intensive dimensions first, then mechanical. **Why:** Judgment issues are higher-value findings; if the reviewer hits context limits, mechanical issues are the right ones to drop.

**Why not a separate lint pass?** A Haiku-tier lint pass would need a new agent definition, orchestrator step, and output format. The marginal cost of Sonnet catching acronyms alongside judgment calls is lower than the complexity of a new pipeline stage.

### Files to change
- `agents/style-reviewer.md` — add `mechanical` field, dimension classification, prioritization guidance
- `agents/report-reviser.md` — add note that mechanical style issues can be applied with lighter verification

### Risk
Low. The `mechanical` flag is advisory — the reviser's existing constraints (preserve hedging, citations, scope qualifiers) catch over-corrections regardless.

---

## Cross-Cutting: Every Instruction Must Explain Why

All changes to SKILL.md and agent prompts must follow the project convention: instructions say **what**, **how**, and **why**. The "why" helps the agent internalize the principle and apply it to edge cases, not just follow the rule mechanically.

Every new instruction or behavioral change must include a **Why:** annotation. The examples throughout this plan demonstrate the pattern.

---

## Implementation Order

1. **Output path standardization** (section 4) — editorial, zero risk, cleans up audit trail
2. **Issue deduplication** (section 5) — orchestrator-only, reduces reviser confusion
3. **Merge reviser passes** (section 1) — biggest token savings (~100k per run)
4. **Post-revision validation** (section 3) — small format change + bash check, catches silent failures
5. **Conditional verifier gating** (section 2) — most complex, benefits compound over runs
6. **Style reviewer scope reduction** (section 6) — lowest urgency, incremental improvement
