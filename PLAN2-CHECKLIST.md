# Revision Pipeline Improvement — Implementation Checklist

## 1. Standardize Output Paths

- [ ] **1a.** Create `revision/` subdirectory convention: update `synthesis-reviewer.md` output path from `notes/review-report.md` to `revision/review-report.md`
- [ ] **1b.** Update `research-verifier.md` output path from `notes/verification-report.md` to `revision/verification-report.md`
- [ ] **1c.** Update `style-reviewer.md` output path from `notes/style-review.md` to `revision/style-review.md`
- [ ] **1d.** Add "Expected Agent Outputs" section to `skills/deep-research-revision/SKILL.md` listing canonical paths for each agent, with a "why" explaining that the orchestrator should not override these paths
- [ ] **1e.** Update SKILL.md agent launch instructions: remove any ad-hoc path overrides, let agents write to their default locations
- [ ] **1f.** Verify: the `revision/` directory doesn't conflict with any existing session directory structure

## 2. Issue Deduplication Before Reviser

- [ ] **2a.** Add dedup step to SKILL.md between issue collection (step 2) and reviser launch (step 3)
- [ ] **2b.** Write dedup logic: group issues by location (same section + paragraph), merge overlapping issues
- [ ] **2c.** Specify merge rules with rationale: prefer more specific suggested_fix (**why:** immediately actionable vs. requires interpretation), elevate to higher severity (**why:** dual-flagged issues have higher confidence), note both sources in `flagged_by` field (**why:** audit trail)
- [ ] **2d.** Add `merged_count` to delivery summary so user knows dedup happened
- [ ] **2e.** Add "why" annotation explaining that dedup prevents the reviser from attempting to edit already-changed text (the reactive recovery at reviser line 114 is a fallback, not a substitute for prevention)

## 3. Merge Reviser Passes

- [ ] **3a.** Restructure SKILL.md workflow: after style reviewer returns, merge accuracy + style issues into one combined list
- [ ] **3b.** Specify combined list ordering with rationale: user feedback first, then accuracy issues by severity, then style issues by severity. **Why accuracy before style:** accuracy edits may change text targeted by style issues
- [ ] **3c.** Launch single reviser with `pass_type: "combined"` and the merged list
- [ ] **3d.** Update `report-reviser.md`: add `"combined"` as valid pass_type, add "why" explaining processing order
- [ ] **3e.** Remove SKILL.md step 5 (separate style revision pass) — fold into the combined step
- [ ] **3f.** Update delivery step: report accuracy and style fixes separately by counting issue ID prefixes (review-N, verify-N = accuracy; style-N = style)
- [ ] **3g.** Add overflow guidance: if combined list exceeds 30 issues, split into two batches (accuracy first, then style). **Why 30:** typical reviser context handles ~25 issues comfortably; 30 gives headroom without risking quality degradation

## 4. Post-Revision Validation

- [ ] **4a.** Extend reviser manifest format in `report-reviser.md`: add `old_text_snippet` (first 80 chars of old_string) and `new_text_snippet` (first 80 chars of new_string) to each edit entry
- [ ] **4b.** Add "why 80 chars" annotation: long enough for uniqueness in a ~200-line report, short enough to not bloat the manifest
- [ ] **4c.** Add validation step in SKILL.md after reviser returns: for each resolved issue, grep report.md for `old_text_snippet` — if found, the edit didn't land
- [ ] **4d.** Add retry logic: if any edits failed validation, re-launch reviser with only failed issues, cap at one retry
- [ ] **4e.** Add "why one retry" annotation to SKILL.md (context drift is fixed by re-reading; deeper problems need human judgment)
- [ ] **4f.** Add failed-validation count to delivery summary

## 5. Conditional Verifier Gating

- [ ] **5a.** Add gating logic to SKILL.md step 2, after both reviewers return
- [ ] **5b.** Define three modes with rationale:
  - Full verification: 3+ high-severity reviewer issues, OR user requests, OR first revision of this report. **Why:** high issue count suggests report quality problems that independent verification catches
  - Targeted verification: 1-2 high-severity issues — pass those claims to verifier. **Why:** focuses expensive Opus+web-search on known problem areas
  - Skip verification: 0 high issues AND prior `verification-report.md` exists. **Why:** reviewer's clean bill + prior verification baseline = low marginal value
- [ ] **5c.** Add "why parallel launch with post-hoc gating" annotation: saves ~2 min in the common case (full mode) vs. sequential launch that always adds reviewer latency
- [ ] **5d.** In targeted mode, pass specific claims to verifier using existing "specific list of claims" input (verifier line 19)
- [ ] **5e.** Log the gating decision for auditability

## 6. Style Reviewer Scope Reduction

- [ ] **6a.** Add `mechanical` boolean to style-reviewer.md issue format
- [ ] **6b.** Define which dimensions are typically mechanical vs. judgment, with rationale:
  - Mechanical: acronym expansion, filler removal, sentence splitting (pattern-matchable, no meaning risk)
  - Judgment: paragraph focus, passive voice in context, list opportunities (require understanding argument flow)
- [ ] **6c.** Update `report-reviser.md`: mechanical issues can be applied with minimal surrounding-context verification. **Why:** these edits don't change meaning by definition (expanding "HMD" to "head-mounted display (HMD)" can't alter an argument), so the reviser's re-read-after-editing step can be lighter
- [ ] **6d.** Add prioritization guidance to style-reviewer.md: scan judgment-intensive dimensions first (paragraph focus, contextual jargon), then sweep for mechanical issues. **Why:** judgment issues are higher-value findings; if the reviewer hits context limits, mechanical issues are the right ones to drop

## Verification

After implementing all changes:
- [ ] Run `/deep-research-revision` on an existing session (e.g., `./deep-research-uncanny-valley` using the `report_draft.md` restored as `report.md`)
- [ ] Confirm: revision artifacts appear in `{session}/revision/`, not in `notes/` or session root
- [ ] Confirm: duplicate issues are merged in the combined list before reaching the reviser
- [ ] Confirm: only one reviser agent is launched (not two)
- [ ] Confirm: post-revision validation step runs and reports results
- [ ] Confirm: delivery summary distinguishes accuracy vs. style fix counts
- [ ] Compare token usage to the baseline run (~400k total) — target ~30% reduction
