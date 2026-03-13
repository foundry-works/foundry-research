# Plan: Two-Stage Research Pipeline & Dedicated Revision

## Problem

The current `/deep-research` skill tries to do everything in one session: research gathering, initial draft, review, and revision. By the time synthesis happens, the orchestrator's context is polluted with search manifests, reader coordination, and gap analysis. The revision step reuses the synthesis-writer agent — but drafting and revising are fundamentally different tasks, and cramming all reviewer feedback (factual + style) into one pass forces the writer to triage competing priorities on the fly.

## Design

Split the pipeline into two independent skills with a clean handoff point, and create a dedicated revision agent that makes surgical edits rather than regenerating the report.

### Stage 1: `/deep-research` — Research & Draft

Everything up to and including the initial draft. This is the current SKILL.md steps 1-14a, ending when `report.md` is written to disk. The orchestrator's job is done once the synthesis-writer returns a draft.

**What changes:**
- Remove steps 14b-14d (review/revise/deliver) from the current SKILL.md
- The skill ends by telling the user: "Draft is at `report.md`. Review it, then run `/deep-research-revision` when ready."
- All research infrastructure (state.py, search, download, agents for acquisition/reading/findings/brief/synthesis-writer) stays exactly as-is

**Why stop here:** The draft is the natural handoff point. The user has something to read and react to. They might want to redirect the report before spending tokens on revision. They might be happy with the draft as-is. And the revision orchestrator gets a fresh context focused entirely on quality.

### Stage 2: `/deep-research-revision` — Review & Revise

A new skill that takes an existing session directory with a `report.md` and runs a structured review→revise cycle.

**Required input:** Session directory path — the user must provide this as an argument (e.g., `/deep-research-revision ./deep-research-credit-cards`). The skill validates that `report.md`, `notes/`, and `sources/metadata/` exist at that path. No auto-discovery — the user explicitly tells us what to revise.

**Why required, not auto-discovered:** Auto-discovery via `.deep-research-session` marker files is fragile when the user has multiple sessions, or when running revision in a different working directory than where research happened. An explicit path removes ambiguity and makes the skill work regardless of where the user invokes it from.

**Optional input:** User feedback — free-text direction like "section 3 is too long" or "I disagree with the conclusion about X". This gets incorporated into the revision instructions alongside automated review findings.

**Pass 1 — Accuracy:**
1. Launch `synthesis-reviewer` + `research-verifier` in parallel (same response message, foreground)
2. Collect all high/medium issues from reviewer + all contradicted/partially-supported claims from verifier
3. If user provided feedback, add it as a separate "User feedback" section in the revision instructions
4. Rename `report.md` → `report_draft.md` (preserve original for diffing)
5. Launch `report-reviser` with: the draft path, the accuracy issues list, user feedback, session directory
6. Reviser makes targeted edits, writes updated `report.md`

**Pass 2 — Style:**
1. Launch `style-reviewer` on the corrected `report.md`
2. Collect all high/medium style issues
3. Launch `report-reviser` with: the corrected draft, the style issues list, session directory
4. Reviser makes targeted edits to final `report.md`

**Why two passes, not parallel:** Style fixes applied to text containing factual errors are wasted work — the text will change when errors are fixed. Running accuracy first means the style reviewer sees correct text, and the reviser has a simpler job each time. The cost is ~2-3 minutes of sequential execution, which is trivial compared to the research phase.

**Why user feedback in Pass 1:** User direction is closer to "accuracy" than "style" — it's about content, emphasis, and conclusions. Incorporating it in the accuracy pass means the style reviewer sees text that already reflects the user's intent.

### New Agent: `report-reviser`

A dedicated agent for making targeted edits to an existing report based on a structured issues list.

**Key differences from synthesis-writer:**

| Dimension | synthesis-writer | report-reviser |
|-----------|-----------------|----------------|
| Input | Notes, findings, metadata, brief | Existing draft + issue list |
| Operation | Blank-page synthesis | Surgical edits to flagged sections |
| Tools | Read, Glob, Write | Read, Glob, **Edit** |
| Core rule | Build coherent narrative from evidence | Fix what's broken, leave the rest alone |
| Risk to mitigate | Missing evidence, weak structure | Collateral damage to unflagged sections |

**Why Edit, not Write:** The synthesis-writer uses `Write` because it generates the whole file. The reviser uses `Edit` because it should only touch specific passages. This is a structural constraint that prevents the "regenerate everything" failure mode — `Edit` requires specifying exact text to replace, which forces targeted changes.

**Agent prompt design principles:**
- "Do not modify any section that has no flagged issues" — explicit constraint
- Each edit must trace to a specific issue ID from the review
- Return a manifest mapping issue IDs to the edits made (for audit trail)
- If an issue requires context the reviser doesn't have (e.g., needs to check a source), flag it as unresolved rather than guessing

### User Feedback Flow

When the user runs `/deep-research-revision` with feedback:

```
/deep-research-revision ./deep-research-credit-cards
User: "Section 3 is too detailed — cut it to 2 paragraphs.
       Also, the recommendation to use X ignores the cost constraint I mentioned."
```

The revision orchestrator:
1. Parses user feedback into structured directives
2. Adds them to the Pass 1 revision instructions under a "User feedback" header
3. The reviser treats user feedback as highest priority (above reviewer issues)
4. The manifest explicitly tracks which user feedback items were addressed

This also means the user can run `/deep-research-revision` with *only* user feedback (no automated review) for quick iterations. The orchestrator should detect "no automated review needed" when the user's feedback is purely about content direction, not accuracy.

## What Stays the Same

- All research infrastructure (state.py, search, download scripts)
- All research-phase agents (source-acquisition, research-reader, findings-logger, brief-writer)
- The synthesis-writer agent (still does initial drafting)
- The three reviewer agents (synthesis-reviewer, research-verifier, style-reviewer)
- Session directory structure
- State database schema

## File Changes

### New files:
- `skills/deep-research-revision/SKILL.md` — revision orchestrator prompt
- `agents/report-reviser.md` — dedicated revision agent prompt

### Modified files:
- `skills/deep-research/SKILL.md` — remove steps 14b-14d, add "draft complete" ending
- `copy-to-skills.sh` — add the new skill directory to the copy list

### Unchanged files:
- `agents/synthesis-writer.md` — still does initial drafting only
- `agents/synthesis-reviewer.md` — unchanged
- `agents/style-reviewer.md` — unchanged
- `agents/research-verifier.md` — unchanged
- `agents/brief-writer.md` — unchanged
- `agents/source-acquisition.md` — unchanged
- `agents/research-reader.md` — unchanged
- `agents/findings-logger.md` — unchanged
- All scripts in `skills/deep-research/scripts/` — unchanged

## Open Questions

1. **Should `/deep-research-revision` support multiple rounds?** E.g., user reviews the revised report, gives more feedback, runs revision again. The current design supports this naturally (it just reads whatever `report.md` is on disk), but should we explicitly version drafts (`report_v1.md`, `report_v2.md`) for audit trail?

2. **Should the revision orchestrator auto-detect when to skip style review?** If the accuracy pass found zero issues and the user's feedback was content-only, the style pass might be redundant if it already ran once. But this adds complexity — probably better to always run both passes and let the style reviewer return zero issues if the text is clean.

3. **Should the reviser have access to source files?** The current design gives it Read access to `notes/` and `sources/metadata/` so it can verify claims when fixing accuracy issues. But giving it access to full source text (`sources/src-NNN.md`) risks context bloat. Probably: metadata + notes yes, full source text no — if it needs the full source, flag as unresolved.
