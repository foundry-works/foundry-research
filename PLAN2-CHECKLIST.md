# Implementation Checklist — Revision Pipeline Improvements

Tracks progress on the 6 improvements from PLAN2.md.

---

## 1. Reviewer Severity Calibration (HIGH)

- [ ] **Edit `agents/synthesis-reviewer.md`** — Add to severity definition section:
  - [ ] Define that `high` MUST have a substantive suggested_fix that changes text
  - [ ] Explain downstream consequence: high count drives verifier gating decisions
  - [ ] Add guidance: "no fix needed" observations go in a separate `observations` section or are downgraded to `low`
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 2. Co-Location Warnings in Dedup (HIGH)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 2b (dedup procedure):
  - [ ] Add step 4: scan for remaining issues targeting the same paragraph after dedup
  - [ ] Add `co_located_with` field listing other issue IDs at same location
- [ ] **Edit `agents/report-reviser.md`** — In planning step:
  - [ ] Add: when issues have `co_located_with`, plan a single combined edit
  - [ ] Compose one replacement that addresses all co-located issues at once
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 3. Structured Skip List for Style Reviewer (HIGH)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 3:
  - [ ] Replace prose skip instruction with: build `skip_locations` JSON array from accuracy issues
  - [ ] Extract `location` field from each high/medium accuracy issue
  - [ ] Pass array in style reviewer agent prompt
- [ ] **Edit `agents/style-reviewer.md`** — Add skip_locations handling:
  - [ ] Accept optional `skip_locations` array
  - [ ] Do not flag style issues matching any skip location
  - [ ] Err on side of skipping for partial overlaps
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 4. Smarter Opportunistic Inclusion (MEDIUM)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 3 (severity filtering):
  - [ ] Replace "under 25 total" threshold with section-matching rule
  - [ ] Include low-severity style issue only if its section matches an existing high/medium issue
  - [ ] Compare section identifier (e.g., "Section 3") across issue locations
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 5. Prior-Revision Manifest for Iterative Runs (MEDIUM)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 1:
  - [ ] Check for existing `revision/revision-manifest.json`
  - [ ] If exists, read and pass resolved issue IDs to each reviewer
- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — After Step 4:
  - [ ] Write reviser manifest to `revision/revision-manifest.json`
- [ ] **Edit `agents/synthesis-reviewer.md`** — Add prior_resolved handling:
  - [ ] Accept optional `prior_resolved` list
  - [ ] Skip re-flagging resolved issues unless fix was insufficient
  - [ ] Focus on: changed text, unreviewed text, new user feedback
- [ ] **Edit `agents/research-verifier.md`** — Same prior_resolved handling
- [ ] **Edit `agents/style-reviewer.md`** — Same prior_resolved handling
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 6. Verifier Gating: Exclude No-Op Highs (LOW)

- [ ] **Edit `skills/deep-research-revision/SKILL.md`** — In verifier gating section:
  - [ ] Add: exclude issues whose suggested_fix indicates no text change
  - [ ] Pattern match for "no change needed," "correctly placed," "no edit required"
- [ ] **Run `./copy-to-skills.sh`** to deploy

---

## Integration Testing

- [ ] Run revision on uncanny-valley session after implementing items 1-3 (HIGH priority)
- [ ] Verify no false-high issues from synthesis-reviewer (item 1)
- [ ] Verify co-located issues produce `co_located_with` field and reviser handles them atomically (item 2)
- [ ] Verify style reviewer receives and respects `skip_locations` array (item 3)
- [ ] Run a second revision pass on the same session to test iterative behavior (item 5)
- [ ] Verify prior manifest is read and reviewers skip already-resolved issues
- [ ] Verify `copy-to-skills.sh` correctly deploys all changed files to `.claude/`
