# Deep Research Revision Pipeline Improvements — Plan

## Context

Observations from the 2026-03-14 revision of the "uncanny valley" research report. 25 issues found (12 accuracy, 13 style), all resolved in a single reviser pass. The pipeline worked end-to-end but several structural issues made the orchestrator's job fragile and defeated the designed validation step.

---

## 1. Enforce Structured Reviser Manifest (Bug Fix)

### Problem
The reviser agent prompt (`agents/report-reviser.md`) specifies returning `old_text_snippet` and `new_text_snippet` (80 chars each) per edit in the manifest. The actual manifest returned only prose `action` descriptions. This broke post-revision validation — Step 4b in `skills/deep-research-revision/SKILL.md` describes an algorithmic check (is `old_text_snippet` still present? is `new_text_snippet` now present?) that couldn't execute without these fields.

The orchestrator fell back to manually reading the full revised report, which worked but defeats the purpose of structured validation.

### Fix
**File: `agents/report-reviser.md`** — The manifest format section needs to be more explicit. Currently it describes the fields in prose. Add:

1. A concrete JSON schema for the manifest entry with all required fields
2. A few-shot example showing a complete manifest entry with `old_text_snippet` and `new_text_snippet`
3. Make the instruction imperative: "Each entry MUST include `old_text_snippet` and `new_text_snippet`" rather than describing them as part of the format

**Why the current prompt fails:** The reviser sees the manifest format described alongside many other instructions. Under context pressure (25 edits across a long report), it shortcuts to the minimum viable manifest — issue ID + action description. A concrete example with required fields is harder to shortcut than a prose description.

### Validation
After fix, run a revision pass and check that the manifest JSON includes `old_text_snippet` and `new_text_snippet` for every resolved entry.

---

## 2. Standardize Reviewer Output Format (Data Flow)

### Problem
The three reviewers (synthesis-reviewer, research-verifier, style-reviewer) return issues in different structures:

- **Synthesis-reviewer**: `{severity, dimension, location, description, suggested_fix}` — closest to the target format
- **Research-verifier**: Returns a different structure with `high_priority_issues` containing `{claim, report_location, verdict, evidence}` — no `severity`, no `suggested_fix`, different field names
- **Style-reviewer**: Adds `mechanical` and `text` fields, uses `suggested_fix` but adds `dimension` values specific to style

The orchestrator must manually translate all three formats into a unified issues list, assign IDs, and compose a ~3000-word prompt for the reviser. This translation is error-prone — a misassigned ID, missed issue, or incorrect merge propagates silently.

### Fix
Define a canonical issue schema that all three reviewers output:

```json
{
  "issue_id": "string (reviewer assigns, e.g. 'review-1', 'verify-1', 'style-1')",
  "severity": "high | medium | low",
  "location": "string (section + paragraph)",
  "description": "string (what's wrong)",
  "suggested_fix": "string (specific edit suggestion)",
  "dimension": "string (e.g. 'citation_integrity', 'unsupported_claim', 'jargon', 'passive_voice')"
}
```

**File: `agents/synthesis-reviewer.md`** — Already close. Add `issue_id` field with `review-N` prefix. The reviewer currently returns issues without IDs.

**File: `agents/research-verifier.md`** — Restructure `high_priority_issues` output to match the canonical schema. Map `claim` → `description`, `report_location` → `location`, add `severity` (all verifier issues are high by default — they're factual errors), add `suggested_fix` derived from the `evidence` field. Keep the full verification report as-is for audit purposes, but add a `issues` array at the top level matching the canonical format.

**File: `agents/style-reviewer.md`** — Already close. Add `issue_id` field with `style-N` prefix. Keep `mechanical` flag as an additional field (it's useful metadata for the reviser).

**File: `skills/deep-research-revision/SKILL.md`** — Simplify the orchestrator's assembly step. Instead of manually translating three different formats, the orchestrator reads the `issues` array from each reviewer's output and concatenates them. Dedup and ordering logic remains in the skill prompt, but the translation step disappears.

**Why standardize at the reviewer level, not the orchestrator level:** The reviewers know their issues best — they can assign meaningful IDs and severity at creation time. The orchestrator doing this after the fact requires interpreting prose descriptions to assign severity, which is a judgment call that should stay with the reviewer.

### Validation
Run a revision pass and verify that all three reviewer outputs include `issues` arrays with the canonical fields. Check that the orchestrator's assembly step is a mechanical merge, not a translation.

---

## 3. Adaptive Severity Filtering for Style Issues (Improvement)

### Problem
The skill prompt says "collect all high and medium severity style issues." This hard cutoff dropped 7 low-severity style issues from the uncanny valley revision, including:
- Expanding EMG/CG acronyms on first use (Section 3.2) — a genuine readability fix
- Explaining "morphing artifacts" (Section 1.1) — helps non-specialist readers
- Splitting a 52-word sentence (Section 6.2)

Meanwhile, some medium issues were marginal (converting a 3-item list to bullets). The hard severity threshold treats all mediums equally and all lows equally, which doesn't match actual editorial value.

### Fix
**File: `skills/deep-research-revision/SKILL.md`** — Replace the hard severity cutoff with an adaptive approach:

1. Always include all high and medium severity style issues
2. Include low-severity style issues when the total combined issues list (accuracy + style) is under 25. **Why 25:** The reviser comfortably handles ~25 issues per pass. If accuracy issues already consume most of that budget, low-severity style issues should yield. If the accuracy load is light, low-severity fixes are free additions.
3. When including low-severity style issues, mark them as `priority: "opportunistic"` in the issues list — the reviser applies them if it's already editing nearby text, but doesn't force an edit on an otherwise-clean passage.

**File: `agents/report-reviser.md`** — Add handling for `priority: "opportunistic"` issues: apply only when the target passage is already being edited for a higher-priority issue. Skip if the passage is untouched. **Why:** This avoids the risk of introducing edit conflicts on clean text for marginal gains, while capturing low-hanging fruit when the reviser is already in the neighborhood.

### Validation
Run a revision on a report with < 15 accuracy issues and verify that low-severity style issues appear in the reviser's input and are applied where nearby text was already edited.

---

## 4. Simplify Verifier Gating for First Pass (Cleanup)

### Problem
The three-mode verifier gating logic (full/targeted/skip) only matters on subsequent revision passes. On first pass — the most common case — it always resolves to "full" because no prior `revision/verification-report.md` exists. The orchestrator still evaluates all gating conditions and logs the decision, spending tokens on what's effectively a constant.

### Fix
**File: `skills/deep-research-revision/SKILL.md`** — Add a short-circuit at the top of the verifier gating section:

```
**Short-circuit:** If this is the first revision pass (no prior `revision/verification-report.md`), use full verification. Skip the gating evaluation entirely — the conditions below only differentiate behavior on subsequent passes.
```

Move the existing three-mode logic under a "Subsequent passes" subheading so the orchestrator doesn't need to read it on first pass.

**Why this matters:** Not about token savings — it's about cognitive load on the orchestrator. The gating logic is ~300 words of conditional reasoning. On first pass, all of that resolves to one outcome. Making the common case obvious reduces the chance of the orchestrator misapplying the logic.

### Validation
Run a first-pass revision and verify the orchestrator logs "first pass — full verification (short-circuit)" without evaluating the three-mode conditions.

---

## Non-Changes (Considered but Rejected)

### Assembly script in Python
Considered moving the issue assembly (ID assignment, dedup, ordering, merge) into a Python script in `skills/deep-research-revision/scripts/`. Rejected: the assembly logic is tightly coupled to the reviewers' output interpretation and the skill prompt's ordering rules. A script would need to parse three different markdown reports, which is more fragile than the orchestrator reading structured JSON. Fix #2 (standardized output) makes the assembly simple enough that a script adds complexity without benefit.

### Separate accuracy and style reviser passes
The old pipeline ran two separate reviser launches. The current combined pass worked well (25 edits, zero failures, accuracy-before-style ordering correct). No change needed — the merge was a good simplification.

### Retry budget increase
The skill allows one retry for failed validations. Zero edits failed in this run. The one-retry cap is reasonable — if an edit fails twice, it needs human judgment, not more retries. No change.
