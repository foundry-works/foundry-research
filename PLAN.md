# Phase 1.5: Synthesis & Verification Agents

## Problem

The deep-research skill produces reports with four categories of error that an expert would catch:

1. **Unexamined assumptions** — the system takes the query's framing as given instead of probing what it assumes (e.g., "best new card" assumes a new ecosystem is the answer, when vertical consolidation in the existing ecosystem might be better)
2. **Unverified claims** — factual claims sourced from secondary sources (affiliate blogs, review sites) aren't cross-checked against primary/authoritative sources (official partner lists, actual award charts)
3. **Internal contradictions** — the report can assert X in one section and not-X in another without noticing
4. **Missing applicability context** — findings are stated as facts without assessing real-world feasibility (a redemption sweet spot that's nearly impossible to book; a card requiring $20K spend in 3 months presented without caveat)

These are domain-agnostic problems. They appear in product research (credit cards) and would appear equally in academic research (citing a finding from a review without checking the original study; reporting an effect size without noting it hasn't replicated).

## Solution

Three new agents + SKILL.md workflow updates. All work within the current single-session architecture and are forward-compatible with Phase 3 multi-session.

### New Agents

#### `agents/synthesis-writer.md` (Opus)

Dedicated report writer that receives a clean handoff: research brief, key findings, source notes, identified gaps. Operates in its own context window without search logistics clutter.

**Why a separate agent:** Synthesis is the task that most benefits from (a) a strong model and (b) a clean context. The supervisor agent's context is polluted with search state, download logs, and tool coordination by the time synthesis happens. A dedicated writer gets a fresh window focused entirely on integration and narrative.

**Inputs:** Research brief, research questions, all source notes from `notes/`, gap analysis, key findings summary.

**Outputs:** Draft report in markdown. Structured so the reviewer can audit it.

#### `agents/synthesis-reviewer.md` (Sonnet)

Audits the draft report for quality issues the writer may have introduced. Returns a structured list of problems for the writer to fix.

**Checks:**
- **Internal contradictions** — entity X is claimed to have property A in one place and property B in another
- **Unsupported claims** — assertions that don't trace back to any cited source
- **Secondary-source-only claims** — key findings that rest entirely on blogs/reviews without primary source verification
- **Missing applicability context** — findings stated as actionable without feasibility assessment
- **Citation integrity** — references exist and support what they're cited for

**Why Sonnet:** This is structured checklist auditing — scan for contradictions, check citations match claims, flag missing caveats. Pattern-matching against a defined set of checks. Doesn't require the deep reasoning of Opus.

#### `agents/research-verifier.md` (Opus)

Takes the N most important claims from the report and attempts to verify each against primary/authoritative sources. Runs after the draft is written.

**Workflow:**
1. Extract key claims the report depends on (the verifier identifies these, not the supervisor)
2. For each claim, distinguish the current source type (primary vs. secondary)
3. For claims resting on secondary sources, search for and check the primary source
4. Return a verification report: confirmed / contradicted / unverifiable, with evidence

**Why separate from the reviewer:** The reviewer reads the report for internal quality. The verifier does external research — it needs to make web searches, read new sources, and check facts against authoritative references. Different tools, different task.

### SKILL.md Workflow Updates

#### Clarification Step Enhancement

Current: the system generates a research brief and questions, asks the user to approve.

New: before generating the brief, explicitly identify 2-3 assumptions embedded in the query and surface them to the user. Examples:
- "Your query assumes X — is that intentional, or should we also consider Y?"
- "This question could be interpreted as [narrow framing] or [broad framing] — which do you mean?"

This is guidance-only — no code, no agents. Just better prompting in the clarification workflow section of SKILL.md.

#### Applicability/Feasibility Research Pass

After the main research rounds identify key findings, add a targeted research pass that asks: "How reliable/accessible/practical is [finding] in real-world conditions?"

- Product research: "Can you actually book this redemption? How often is availability released?"
- Academic research: "Has this effect replicated? In what populations/settings?"
- Medical research: "What are the contraindications? What do clinical guidelines say vs. individual studies?"

This is a SKILL.md workflow step — the supervisor triggers targeted searches after findings are established but before synthesis begins.

### Writer → Reviewer Loop

The intended flow:

```
Supervisor (research complete, notes written)
    │
    ├─→ synthesis-writer (draft report)
    │       │
    │       ├─→ synthesis-reviewer (audit draft)
    │       │       │
    │       │       └─→ returns issues list
    │       │
    │       └─→ synthesis-writer (revise based on issues)
    │
    ├─→ research-verifier (verify key claims)
    │       │
    │       └─→ returns verification report
    │
    └─→ synthesis-writer (final revision incorporating verification)
```

The supervisor orchestrates but doesn't do synthesis itself. It passes materials to the writer, routes reviewer/verifier feedback back to the writer, and delivers the final report.

## Agent Roster (after this work)

| Agent | Model | File | Role |
|-------|-------|------|------|
| `research-reader` | Sonnet | `agents/research-reader.md` (exists) | Summarize individual sources |
| `synthesis-writer` | Opus | `agents/synthesis-writer.md` (new) | Draft and revise reports |
| `synthesis-reviewer` | Sonnet | `agents/synthesis-reviewer.md` (new) | Audit drafts for quality issues |
| `research-verifier` | Opus | `agents/research-verifier.md` (new) | Verify claims against primary sources |

## Forward Compatibility

These agents map directly to Phase 3's planned skill decomposition:

| Phase 1.5 Agent | Phase 3 Skill |
|-----------------|---------------|
| `synthesis-writer` | `research-synthesize` |
| `synthesis-reviewer` | Part of `research-verify` |
| `research-verifier` | Part of `research-verify` |
| Clarification improvements | Part of `research-gather` |

When Phase 3 lands, the agent prompts can be reused with minimal modification. The main change will be that they operate across sessions via `project.yaml` rather than within a single supervisor session.
