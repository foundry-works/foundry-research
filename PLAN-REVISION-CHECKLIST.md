# Revision Pipeline — Implementation Checklist

Tracks progress on the 4 improvements from PLAN-REVISION.md. Each item maps to a specific file edit.

---

## 1. Enforce Structured Reviser Manifest (Bug Fix)

- [ ] **Edit `agents/report-reviser.md`** — In the manifest format section:
  - [ ] Add concrete JSON schema with all required fields (`issue_id`, `status`, `old_text_snippet`, `new_text_snippet`, `action`)
  - [ ] Add a few-shot example showing a complete manifest entry
  - [ ] Make `old_text_snippet` and `new_text_snippet` explicitly required with imperative language
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 2. Standardize Reviewer Output Format (Data Flow)

- [ ] **Edit `agents/synthesis-reviewer.md`** — Add `issue_id` field with `review-N` prefix to the output format; add top-level `issues` JSON array
- [ ] **Edit `agents/research-verifier.md`** — Add `issues` array matching canonical schema (map claim→description, report_location→location, add severity/suggested_fix); keep full verification report for audit
- [ ] **Edit `agents/style-reviewer.md`** — Add `issue_id` field with `style-N` prefix to the output format; add top-level `issues` JSON array
- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — Simplify assembly step to read `issues` arrays from each reviewer and concatenate; remove manual translation logic
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 3. Adaptive Severity Filtering for Style Issues (Improvement)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 3/Step 4:
  - [ ] Replace hard "high and medium only" cutoff with adaptive rule (include low when total < 25)
  - [ ] Add `priority: "opportunistic"` marker for included low-severity issues
- [ ] **Edit `agents/report-reviser.md`** — Add handling for `priority: "opportunistic"` issues (apply only when nearby text already edited)
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 4. Simplify Verifier Gating for First Pass (Cleanup)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 2 verifier gating section:
  - [ ] Add short-circuit for first pass (no prior verification-report.md → full verification, skip gating evaluation)
  - [ ] Move three-mode logic under "Subsequent passes" subheading
- [ ] **Run `./copy-to-skills.sh`** to deploy

---

## Integration Testing

- [ ] Run a revision pass on an existing session after all edits to verify the pipeline still works end-to-end
- [ ] Verify reviser manifest includes `old_text_snippet` / `new_text_snippet` fields
- [ ] Verify reviewer outputs include standardized `issues` arrays
- [ ] Verify `copy-to-skills.sh` correctly deploys all changed files
