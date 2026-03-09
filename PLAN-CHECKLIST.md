# Phase 1.5 Implementation Checklist

## Step 1: Synthesis Writer Agent
- [ ] Write `agents/synthesis-writer.md` prompt
  - [ ] Define input format (brief, questions, source notes, gaps, findings)
  - [ ] Define output format (structured markdown report)
  - [ ] Guidance: theme-based synthesis, not source-by-source
  - [ ] Guidance: cite every factual claim, flag confidence level
  - [ ] Guidance: include applicability caveats where relevant
- [ ] Smoke test: run on an existing session's notes and compare output to current reports

## Step 2: Synthesis Reviewer Agent
- [ ] Write `agents/synthesis-reviewer.md` prompt
  - [ ] Define input format (draft report + source notes for cross-reference)
  - [ ] Define output format (structured issues list with severity, location, description, suggested fix)
  - [ ] Check: internal contradictions (same entity, conflicting claims)
  - [ ] Check: unsupported claims (assertion without citation)
  - [ ] Check: secondary-source-only claims (key findings lacking primary source)
  - [ ] Check: missing applicability context (stated as actionable without feasibility)
  - [ ] Check: citation integrity (reference supports what it's cited for)
- [ ] Smoke test: run on a report with known issues (e.g., the cc-biz-class report)

## Step 3: Research Verifier Agent
- [ ] Write `agents/research-verifier.md` prompt
  - [ ] Define input format (draft report or claim list)
  - [ ] Define output format (per-claim: status, source type, evidence, primary source if found)
  - [ ] Guidance: identify which claims are load-bearing (report's conclusions depend on them)
  - [ ] Guidance: distinguish primary vs. secondary sources
  - [ ] Guidance: search for primary sources when claim rests on secondary only
  - [ ] Guidance: verdict categories — confirmed / contradicted / unverifiable / partially supported
- [ ] Smoke test: run on the cc-biz-class report's Bilt → AA claim and Etihad contradiction

## Step 4: SKILL.md — Clarification Step
- [ ] Add assumption-surfacing guidance to clarification workflow section
  - [ ] Identify 2-3 assumptions in the query
  - [ ] Surface them to user before generating brief
  - [ ] Include examples spanning use cases (product, academic, medical)
- [ ] Keep it concise — this is guidance, not a rigid protocol

## Step 5: SKILL.md — Applicability Research Pass
- [ ] Add workflow step: after findings established, before synthesis
  - [ ] Targeted searches for real-world feasibility of key findings
  - [ ] Domain-agnostic framing with examples
- [ ] Integrate into the existing workflow sequence (between gap resolution and synthesis)

## Step 6: SKILL.md — Synthesis Workflow Integration
- [ ] Update synthesis section to use writer → reviewer → verifier flow
  - [ ] Supervisor hands off to synthesis-writer (not writing report itself)
  - [ ] Supervisor routes reviewer feedback to writer for revision
  - [ ] Supervisor triggers verifier on draft, routes results to writer
  - [ ] Supervisor delivers final report
- [ ] Document the handoff format (what the supervisor passes to each agent)

## Step 7: Run `copy-to-skills.sh` and End-to-End Test
- [ ] Run `./copy-to-skills.sh` to deploy to `.claude/`
- [ ] Full end-to-end test with a new research query
- [ ] Compare output quality against cc-biz-class baseline
- [ ] Verify: does the clarification step surface assumptions?
- [ ] Verify: does the reviewer catch contradictions?
- [ ] Verify: does the verifier flag secondary-source-only claims?
- [ ] Verify: does the report include applicability caveats?
