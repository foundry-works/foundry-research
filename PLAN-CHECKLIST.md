# Implementation Checklist

## Phase 1: Create the report-reviser agent

- [ ] **`agents/report-reviser.md`**: Write the agent prompt. Key design points:
  - Tools: Read, Glob, Edit (NOT Write — surgical edits only)
  - Input: existing draft path, structured issues list (with IDs), optional user feedback, session directory
  - Core constraint: "Do not modify any section that has no flagged issues"
  - Each edit traces to a specific issue ID
  - Returns manifest: `{status, edits: [{issue_id, location, description}], unresolved: [...]}`
  - Can read `notes/` and `sources/metadata/` for verification context, but NOT full source text
  - User feedback items treated as highest priority

## Phase 2: Create `/deep-research-revision` skill

- [ ] **`skills/deep-research-revision/SKILL.md`**: Write the revision orchestrator prompt. Sections:
  - Activation: user runs `/deep-research-revision <session-dir>`
  - Required argument: session directory path (e.g., `./deep-research-credit-cards`). Fail with clear error if not provided.
  - Input validation: check session directory has `report.md`, `notes/`, `sources/metadata/`
  - User feedback handling: parse free-text into structured directives
  - Pass 1 (Accuracy): spawn synthesis-reviewer + research-verifier in parallel → collect issues → spawn report-reviser
  - Pass 2 (Style): spawn style-reviewer on corrected text → collect issues → spawn report-reviser
  - Delivery: present final report, note any unresolved issues
  - Quick mode: if user provides only content feedback (no automated review needed), skip reviewers and go straight to reviser

## Phase 3: Trim `/deep-research` SKILL.md

- [x] **Remove steps 14b-14d** from `skills/deep-research/SKILL.md`:
  - 14b (launch reviewer + verifier + style-reviewer in parallel) — moves to revision skill
  - 14c (writer revision pass) — replaced by report-reviser in revision skill
  - 14d (deliver report) — replaced by simple "draft complete" message
- [x] **Update step 14a ending**: After synthesis-writer returns, the orchestrator:
  - Reads and presents the draft to the user
  - Notes: "Run `/deep-research-revision` to review and revise, or provide feedback"
  - Logs completion in journal.md
- [x] **Update the Delegation section**: Remove synthesis-reviewer, research-verifier, style-reviewer from the delegation list (they move to the revision skill). Keep synthesis-writer.
- [x] **Update the "Synthesis is delegated" paragraph** in "What Good Research Looks Like" to reflect the new split

## Phase 4: Update copy-to-skills.sh

- [x] Add `skills/deep-research-revision/` to the copy targets — no changes needed, script already globs `skills/*/`
- [x] Verify the new skill directory gets copied to `.claude/skills/deep-research-revision/`

## Phase 5: Update synthesis-writer.md (minor)

- [x] Remove the "On revision passes" return format — the writer no longer does revision
- [x] Remove "Revision instructions (on subsequent invocations)" from "What you receive"
- [x] Simplify: the writer's only job is the initial draft

## Phase 6: Testing

- [ ] Run `./copy-to-skills.sh` — verify new skill and agent are deployed
- [ ] Verify `/deep-research-revision` activates on an existing session with a report.md
- [ ] Test Pass 1: reviewer + verifier find issues → reviser fixes them → report.md updated
- [ ] Test Pass 2: style-reviewer finds issues → reviser fixes them → report.md updated
- [ ] Test user feedback: provide free-text feedback → reviser incorporates it
- [ ] Test user-feedback-only mode: skip automated review, just apply user direction
- [ ] Verify `report_draft.md` is preserved for diffing
- [ ] End-to-end: run `/deep-research` on a test query → review draft → run `/deep-research-revision` with feedback
