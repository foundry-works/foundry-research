# Implementation Checklist

Tracks progress on the 6 improvements from PLAN.md. Each item maps to a specific file edit.

---

## 1. Reader Agent Path Handling (Bug Fix)

- [ ] **Edit `agents/research-reader.md`** — Replace the "File paths" section (lines 31-33) with explicit path construction guidance and anti-pattern example (doubled directory name)
- [ ] **Test** — Spawn a reader with an absolute session directory path, verify note lands in `{session_dir}/notes/`, not `{session_dir}/{session_dir_basename}/notes/`
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 2. Earlier Content Mismatch Detection (Quality Gate)

- [ ] **Edit `skills/deep-research/scripts/_shared/quality.py`** — In `check_content_mismatch()`:
  - [ ] Add first-page author check (first 3,000 chars instead of 20,000 for author surnames; flag if zero authors AND title_hits < 3)
  - [ ] Add "paywall abstract stub" detector (content < 2,000 real chars + contains paywall markers anywhere → flag as degraded/stub)
- [ ] **Edit `skills/deep-research/scripts/download.py`** — Add stderr log line when `check_content_mismatch()` flags a source, including the reason string
- [ ] **Test** — Run download on a known mismatched source and verify it's caught at download time
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 3. Gap-Mode "Light" Path (New Feature)

- [ ] **Edit `skills/deep-research/SKILL.md`** — In step 14, add "Light gap-mode" subsection:
  - [ ] Define when to use light vs. full gap-mode (topic recency vs. search coverage)
  - [ ] Specify the light workflow: 2-3 tavily searches → direct download → 1-2 readers → log findings
  - [ ] Require journal.md entry explaining the choice
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 4. Source Quality Report in Synthesis Handoff (Data Flow)

- [ ] **Edit `skills/deep-research/scripts/state.py`** — In the `--write-handoff` branch of `cmd_summary()`:
  - [ ] Run the audit logic to get quality breakdown
  - [ ] Include `source_quality_report` in the handoff JSON (counts + ID arrays for each quality tier)
- [ ] **Edit `skills/deep-research/SKILL.md`** — In step 15a, note that `synthesis-handoff.json` now includes the quality report
- [ ] **Edit `agents/synthesis-writer.md`** — Add instruction to use `source_quality_report` from handoff JSON for the Methodology section
- [ ] **Test** — Run `state summary --write-handoff` on the uncanny-valley session and verify `source_quality_report` appears
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 5. Abstract-Only Source Utilization (New Feature)

- [ ] **Edit `skills/deep-research/SKILL.md`** — Add step 9b (abstract-based findings for thin questions):
  - [ ] Define trigger: question has < 5 findings AND abstract-only sources exist for it
  - [ ] Specify workflow: read metadata JSON → log finding with "abstract only" caveat → cap at 2-3 per question
  - [ ] Clarify this runs after findings-loggers complete (step 10), not before
- [ ] **Edit `agents/findings-logger.md`** — In "How to work" section:
  - [ ] Add that when directed by supervisor, loggers may also read `sources/metadata/src-*.json` for abstract-based extraction
  - [ ] Add rule: always include "(abstract only; methodology not verified)" in `--text` for metadata-derived findings
- [ ] **Run `./copy-to-skills.sh`** to deploy

## 6. Prevent Background Task Leakage (Guard Rail)

- [ ] **Edit `agents/source-acquisition.md`** — Strengthen rule 4 (line ~21):
  - [ ] Add "irrecoverable" framing
  - [ ] Add note about notification leakage into orchestrator context
  - [ ] Make consequence explicit: "Background tasks also leak notifications into the orchestrator's context as noise after you've returned"
- [ ] **Run `./copy-to-skills.sh`** to deploy

---

## Integration Testing

- [ ] Run a small research session (simple factual query, ~5 sources) after all edits to verify end-to-end pipeline still works
- [ ] Verify `copy-to-skills.sh` correctly deploys all changed files to `.claude/`
