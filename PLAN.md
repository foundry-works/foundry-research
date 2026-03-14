# Plan: Rewrite Reflect Skill for Benchmarking

## Goal

Rewrite `skills/reflect/SKILL.md` so it produces accurate, comparable session evaluations that enable hill-climbing pipeline quality over time. The current skill fuses deterministic metrics with rigid lookup-table scoring, producing misleading benchmarks (Goodhart's law) and preventing the evaluating agent from exercising contextual judgment.

## Design Decisions

### Three-layer evaluation architecture

**Layer 1 — Deterministic metrics.** Mechanically computed from state.db and the filesystem. No agent judgment. These are the raw instrument readings, reproducible across runs. They go into `reflection.json` for aggregation.

**Layer 2 — Contextual interpretation.** The agent detects the session type (academic lit review, product comparison, financial analysis, emerging topic, etc.) from the brief, provider mix, and source types — then evaluates what the metrics *mean* for this kind of session. This is where "70% PubMed in a clinical review is appropriate" lives.

**Layer 3 — Scoring.** Per-dimension scores on a fixed 1-10 scale with short justifications. Dimensions and scale are standardized for comparability. Scoring logic is agent judgment, not table lookup. Calibration anchors (not thresholds) guide the agent.

### Dual output format

- **`reflection.json`** — structured scores, metrics, session metadata. What you aggregate and chart across sessions.
- **Narrative markdown** — human-readable assessment with interpretive context. What you read when a score moves and you want to understand why.

### Dimensions (revised)

Keep the same six dimensions but rewrite their guidance:

1. **Search Strategy (20%)** — Replace provider-count thresholds with rationale: provider diversity reduces corpus bias, query evolution shows adaptive methodology, zero-result searches may be exploratory (not wasteful). Teach the agent to evaluate strategy appropriateness for the domain.

2. **Source Quality (20%)** — Remove mechanical concentration penalty. Explain why diversity matters (corpus bias) and when concentration is appropriate (domain-specialized databases). Fix the source-ID-gaps metric (dedup creates gaps by design — not a bug). Clarify PDF quality evaluation with the actual state.db schema.

3. **Coverage (25%)** — Keep question-to-finding mapping and source-backing metrics. Add guidance on evaluating whether the *user's question was actually answered*, not just whether structured tracking was used.

4. **Report Quality (20%)** — Replace fixed citation density thresholds with contextual guidance. A synthesis paragraph weaving 3 sources into one insight is well-written, not under-cited. Keep phantom reference detection (that's a real bug). Keep contradiction awareness.

5. **Process Efficiency (10%)** — Fix the search efficiency ratio explanation. Clarify ingested_count vs result_count. Evaluate journal.md against the 5 mandatory milestone entries from the deep research SKILL.md.

6. **Infrastructure (5%)** — Remove source-ID-gaps metric (false positive). Keep orphaned sources, metadata mismatches, cascade failures. Elevate tool bugs and state management failures as high-signal findings.

### Scoring calibration

Replace lookup tables with calibration anchors:
- **9-10:** This dimension had no meaningful issues. The pipeline performed as well as could be expected for this session type.
- **7-8:** Minor issues that didn't materially impact the output. Clear room for improvement but nothing broken.
- **5-6:** Issues that noticeably impacted the output. A user reading the report would notice the quality gap.
- **3-4:** Significant failures in this dimension. The report is weakened in ways that matter.
- **1-2:** This dimension fundamentally failed. The pipeline needs structural changes here.

The agent maps observations to this scale using judgment, grounding each score in specific evidence. No lookup tables.

### Adaptive context detection

Replace 3 hard-coded session types with a detection framework. Teach the agent to identify session characteristics from artifacts and adjust evaluation accordingly:

- **Domain signal:** Provider mix, source types, search terms → academic, financial, technical, medical, product, mixed
- **Scale signal:** Source count, search count → small (<10), medium (10-30), large (30+)
- **Constraint signal:** Download failures, tavily availability, paywall rate → constrained vs. unconstrained access
- **Scope signal:** Brief question count, question breadth → narrow factual vs. broad review

The agent weighs dimensions based on what matters for the detected context. Broad lit review → coverage weight up. Small factual query → process efficiency weight down. Paywall-heavy session → source quality interpretation adjusts for access constraints.

### Pipeline-specific recommendations

Recommendations must point to specific files and sections in the pipeline:
- Which skill/agent prompt to change
- What the current behavior is and what it should be
- Which metric would indicate improvement

Generic advice like "use more providers" is not actionable for hill-climbing.

### Bugs & Infrastructure section elevated

Tool failures, state management bugs, and infrastructure issues are the highest-ROI findings for pipeline improvement. Elevate from footnote to prominent section. Include reproduction details (queries, files, commands).

## Scope

- Rewrite `skills/reflect/SKILL.md` (the only file in the skill)
- Run `./copy-to-skills.sh` to deploy for testing

## Out of scope

- Adding new Python scripts or tools to the reflect skill (it's a prompt-only skill that uses sqlite3 and existing tools)
- Changing the deep research or revision skills
- Building aggregation tooling for reflection.json (future work)
