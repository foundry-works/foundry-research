# Implementation Checklist — Revision Pipeline Improvements

Tracks progress on the 6 improvements from PLAN2.md.

---

## 1. Reviewer Severity Calibration (HIGH)

- [x] **Edit `agents/synthesis-reviewer.md`** — Add to severity definition section:
  - [x] Define that `high` MUST have a substantive suggested_fix that changes text
  - [x] Explain downstream consequence: high count drives verifier gating decisions
  - [x] Add guidance: "no fix needed" observations go in a separate `observations` section or are downgraded to `low`
- [x] **Run `./copy-to-skills.sh`** to deploy

## 2. Co-Location Warnings in Dedup (HIGH)

- [x] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 2b (dedup procedure):
  - [x] Add step 4: scan for remaining issues targeting the same paragraph after dedup
  - [x] Add `co_located_with` field listing other issue IDs at same location
- [x] **Edit `agents/report-reviser.md`** — In planning step:
  - [x] Add: when issues have `co_located_with`, plan a single combined edit
  - [x] Compose one replacement that addresses all co-located issues at once
- [x] **Run `./copy-to-skills.sh`** to deploy

## 3. Structured Skip List for Style Reviewer (HIGH)

- [x] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 3:
  - [x] Replace prose skip instruction with: build `skip_locations` JSON array from accuracy issues
  - [x] Extract `location` field from each high/medium accuracy issue
  - [x] Pass array in style reviewer agent prompt
- [x] **Edit `agents/style-reviewer.md`** — Add skip_locations handling:
  - [x] Accept optional `skip_locations` array
  - [x] Do not flag style issues matching any skip location
  - [x] Err on side of skipping for partial overlaps
- [x] **Run `./copy-to-skills.sh`** to deploy

## 4. Smarter Opportunistic Inclusion (MEDIUM)

- [x] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 3 (severity filtering):
  - [x] Replace "under 25 total" threshold with section-matching rule
  - [x] Include low-severity style issue only if its section matches an existing high/medium issue
  - [x] Compare section identifier (e.g., "Section 3") across issue locations
- [x] **Run `./copy-to-skills.sh`** to deploy

## 5. Prior-Revision Manifest for Iterative Runs (MEDIUM)

- [x] **Edit `skills/deep-research-revision/SKILL.md`** — In Step 1:
  - [x] Check for existing `revision/revision-manifest.json`
  - [x] If exists, read and pass resolved issue IDs to each reviewer
- [x] **Edit `skills/deep-research-revision/SKILL.md`** — After Step 4:
  - [x] Write reviser manifest to `revision/revision-manifest.json`
- [x] **Edit `agents/synthesis-reviewer.md`** — Add prior_resolved handling:
  - [x] Accept optional `prior_resolved` list
  - [x] Skip re-flagging resolved issues unless fix was insufficient
  - [x] Focus on: changed text, unreviewed text, new user feedback
- [x] **Edit `agents/research-verifier.md`** — Same prior_resolved handling
- [x] **Edit `agents/style-reviewer.md`** — Same prior_resolved handling
- [x] **Run `./copy-to-skills.sh`** to deploy

## 6. Verifier Gating: Exclude No-Op Highs (LOW)

- [x] **Edit `skills/deep-research-revision/SKILL.md`** — In verifier gating section:
  - [x] Add: exclude issues whose suggested_fix indicates no text change
  - [x] Pattern match for "no change needed," "correctly placed," "no edit required"
- [x] **Run `./copy-to-skills.sh`** to deploy

---

## Integration Testing

- [ ] Run revision on uncanny-valley session after implementing items 1-3 (HIGH priority)
- [ ] Verify no false-high issues from synthesis-reviewer (item 1)
- [ ] Verify co-located issues produce `co_located_with` field and reviser handles them atomically (item 2)
- [ ] Verify style reviewer receives and respects `skip_locations` array (item 3)
- [ ] Run a second revision pass on the same session to test iterative behavior (item 5)
- [ ] Verify prior manifest is read and reviewers skip already-resolved issues
- [ ] Verify `copy-to-skills.sh` correctly deploys all changed files to `.claude/`
