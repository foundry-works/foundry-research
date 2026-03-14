# Reflect Skill Rewrite — Checklist

## Pre-flight
- [ ] Re-read `PRINCIPLES.md` to ensure the rewrite aligns
- [ ] Re-read current `skills/reflect/SKILL.md` for any details to preserve
- [ ] Check deep research `SKILL.md` and `REFERENCE.md` for artifact/schema details the reflect skill references

## Rewrite `skills/reflect/SKILL.md`

### Header & purpose
- [ ] State explicit purpose: benchmark session quality for pipeline hill-climbing
- [ ] Explain the dual audience: structured JSON for aggregation, narrative markdown for understanding

### Artifact map & queries
- [ ] Preserve the inputs table (state.db, report.md, journal.md, sources/metadata, notes/)
- [ ] Preserve the sqlite3 query examples
- [ ] Update any queries that reference incorrect or outdated schema
- [ ] Add queries for any metrics not currently covered (e.g., ingested_count, findings per question)

### Three-layer architecture
- [ ] Write Layer 1 section: deterministic metrics — enumerate every metric with its query/glob, no interpretation
- [ ] Write Layer 2 section: contextual interpretation — detection framework for session type, domain, scale, constraints
- [ ] Write Layer 3 section: scoring — calibration anchors, not lookup tables

### Dimension rewrites
- [ ] **Search Strategy** — replace provider-count thresholds with rationale about corpus bias; explain when zero-result searches are valid exploration
- [ ] **Source Quality** — remove mechanical concentration penalty; explain when concentration is appropriate; fix source-ID-gaps false positive; clarify quality field semantics
- [ ] **Coverage** — keep question-to-finding mapping; add "was the question actually answered" evaluation; keep empty-tracking penalty
- [ ] **Report Quality** — replace fixed citation density thresholds with contextual guidance; keep phantom reference detection; keep contradiction awareness
- [ ] **Process Efficiency** — fix search efficiency ratio explanation; evaluate journal against 5 mandatory milestones from deep research SKILL.md; clarify state management usage
- [ ] **Infrastructure** — remove source-ID-gaps metric; keep orphaned sources and metadata mismatches; add tool failure / state bug detection

### Scoring
- [ ] Write calibration anchors (9-10, 7-8, 5-6, 3-4, 1-2) with qualitative descriptions, not lookup tables
- [ ] Remove fixed weights — agent weighs dimensions contextually with justification
- [ ] Provide weight guidance: suggest default emphasis but let agent shift based on session context
- [ ] Overall score is still a weighted average, but weights are agent-determined per session

### Adaptive context detection
- [ ] Replace 3 hard-coded session types with detection framework (domain, scale, constraint, scope signals)
- [ ] Explain how detected context should influence dimension weighting and interpretation
- [ ] Give examples of contexts and how they shift evaluation (without hard-coding them)

### Recommendations section
- [ ] Require recommendations to point to specific pipeline files/prompts
- [ ] Require what-to-change specificity (current behavior → desired behavior → metric to watch)
- [ ] Cap at 3-5 recommendations, ordered by expected impact on overall score

### Bugs & Infrastructure
- [ ] Elevate from footnote to prominent section
- [ ] Require reproduction details: query, file, command, expected vs. actual
- [ ] Distinguish pipeline bugs (fixable in code) from session-specific issues (one-off)

### Output format
- [ ] Write narrative markdown template (similar to current but with interpretation sections)
- [ ] Write `reflection.json` schema: dimensions array (name, weight, score, justification), overall score, metrics object, session metadata, recommendations array, bugs array
- [ ] Instruct agent to write `reflection.json` to session directory
- [ ] Keep narrative as primary output to the user

### Process section
- [ ] Rewrite process as guidance, not rigid control flow
- [ ] Explain the three layers as a natural progression: observe → interpret → score
- [ ] Note that for small sessions, layers can be compressed

## Post-write
- [ ] Review the rewrite against each principle in PRINCIPLES.md
- [ ] Verify all sqlite3 queries reference correct table/column names from state.py schema
- [ ] Check that no metrics penalize correct pipeline behavior (dedup gaps, appropriate concentration, exploratory searches)
- [ ] Ensure the skill doesn't duplicate guidance already in deep research SKILL.md or REFERENCE.md — reference, don't repeat
- [ ] Run `./copy-to-skills.sh` to deploy
