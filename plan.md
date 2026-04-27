# Plan: Provenance, Grounding, and Support Audit

## Purpose

Roll the provenance and report-grounding planning threads into one implementation roadmap.

The goal is to make research reports more auditable without turning the system into a rigid factory, a fixed domain taxonomy, or a heavyweight artifact graph. The system should preserve enough structured provenance for agents to inspect support, identify weak spots, and revise precisely.

## Design Constraint

This plan must stay aligned with `PRINCIPLES.md`:

- Build capabilities, not factories.
- Keep the agent in the driver's seat.
- Prefer simple, loosely coupled tools that return structured data.
- Add structure only when it improves agent judgment.
- Keep observability simple enough that the system remains understandable.

The implementation should surface better evidence and review inputs. It should not automatically decide the final research conclusion, hide judgment inside code, or force every run through a new mandatory control flow.

Important boundary:

- Deterministic tools may report structural facts: missing links, flagged sources, citation locations, unresolved issues, and coverage counts.
- Agents make semantic judgments: whether a source supports a claim, whether a citation overstates evidence, whether a limitation is acceptable, and whether a report is ready to deliver.
- Writer-provided grounding is declared provenance, not verified support. Deterministic tools should label it as declared grounding until an agent has audited citation fit or claim support.

## Unifying Thesis

The missing layer is not a general artifact graph. It is a lightweight provenance layer that connects:

```text
sources + source annotations -> evidence units -> findings -> report paragraphs/claims -> citations -> review issues
```

The repo already has much of the first half:

- sources
- source access/extraction quality
- structured evidence units
- findings
- links from findings to evidence
- sampled claim extraction and verification
- pre-report audit and reflection metrics

The next step is to make the final report itself auditable by adding:

- source caution flags that do not overload extraction quality
- optional run-local evidence policy
- report grounding
- deterministic declared-grounding coverage reporting
- citation audit manifests
- traceable reviewer issues

## Core Boundary

Keep the core domain-neutral, but allow run-local calibration.

The core should track generic evidence infrastructure:

- source access and extraction quality
- source caution flags, including the scope they apply to when the concern is context-sensitive
- evidence provenance
- finding support
- declared report grounding
- citation fit judgments
- unresolved review issues
- contradiction candidates
- coverage metrics

Domain-specific expectations, when they are useful, should live in a short run-local evidence policy, not in fixed modes such as `medical`, `legal`, `ML`, or `market_research`.

The policy is an agent-owned calibration note, not a required phase. It can be created, revised, or omitted depending on the brief and source landscape. Tools should consume it when present and degrade cleanly when it is absent.

Example:

```yaml
source_expectations: "Prefer primary sources for quantitative, legal, and scientific claims."
inference_tolerance: "low"
freshness_requirement: "high for prices, products, current events, and regulations"
known_failure_modes:
  - "overgeneralizing from single studies"
  - "using secondary summaries as primary evidence"
  - "treating stale sources as current"
```

This handles support-checking calibration without turning the system into a permanent domain taxonomy.

To keep agents loosely coupled to the implementation details, expose policy, source warnings, declared grounding, citation audit outcomes, and open review issues through one small support-context formatter when prompts need them. The formatter should return structured JSON or compact markdown and should not decide what the agent must do next.

## Non-Goals

Do not build these in the first implementation:

- a full artifact graph
- many graph edge types such as `overstates`, `weakens`, or `resolves`
- fixed domain modes
- domain-specific evidence hierarchies in core state
- automated contradiction resolution
- a mandatory new pipeline phase
- a rigid pass/fail scoring system
- large rubric-generation machinery
- treating unvalidated manifest data as authoritative state

Promote heavier structure only after repeated cross-session failures show that prompt guidance and simpler structured state are not enough.

## Target Capabilities

### 1. Source Quality And Source Caution Flags

Add first-class source caution flags without overloading the existing source quality model.

Important distinction:

- `sources.quality` remains the access/extraction condition of a source.
- Source caution flags are additive annotations that can have multiple values per source.
- Claim support judgments do not belong on the source itself.

Initial access/extraction quality values:

- `ok`
- `inaccessible`
- `abstract_only`
- `degraded_extraction`
- `metadata_incomplete`
- `title_content_mismatch`

Initial source caution flags:

- `secondary_source`
- `self_interested_source`
- `undated`
- `potentially_stale`
- `low_relevance`

Do not use `weak_support` as a source flag. Weak support is a relationship between evidence and a finding, report claim, or citation.

Treat `potentially_stale` and `low_relevance` as context-sensitive unless they are clearly intrinsic to the source. A source may be stale for a current-pricing claim but adequate for historical background; it may be low relevance for one report target and useful for another. Store enough scope metadata for the agent to interpret the warning:

- `applies_to`: `run`, `brief`, `finding`, `report_target`, or `citation`
- `applies_to_id`, when narrower than the run
- `rationale`

Do not use source quality for validation, identity, or relational judgments:

- `duplicate` belongs in source deduplication or source relationship state.
- `reader_validated` belongs in a validation event or reader status.
- `source_quality_conflict` belongs in reviewer issues or contradiction candidates with explicit related targets.

Why this matters:

- It preserves the existing quality field's meaning.
- It improves synthesis and verification immediately.
- It gives the agent better inputs without taking over judgment.
- It is useful across academic, technical, policy, web, and market research.

Expected output:

- queryable source caution flags in session state
- source-quality and caution summaries in session metrics
- warnings surfaced in synthesis, verification, and review handoffs

### 2. Run-Local Evidence Policy

Capture support-checking calibration, when useful, in a short local artifact generated from the brief and early source landscape.

When present, the policy should be created or revised early enough to inform:

- source acquisition
- reading and evidence extraction
- synthesis writing
- claim extraction
- claim verification
- citation audit
- synthesis review

Keep the artifact small. It can start as text or lightweight YAML. It should remain advisory: no command should require it in order to run, and no command should treat it as a hidden gate.

Likely fields:

- `source_expectations`
- `freshness_requirement`
- `inference_tolerance`
- `high_stakes_claim_patterns`
- `known_failure_modes`

Success condition:

Exact-support checking can be stricter for high-stakes, quantitative, current, legal, regulatory, or scientific claims and more tolerant for interpretive synthesis where appropriate, without adding fixed domain modes or a mandatory policy phase.

### 3. Report Grounding Manifest

Make the final report auditable as written.

The synthesis writer should try to emit a compact grounding manifest alongside the report:

```text
draft.md
report-grounding.json
```

Version 1 should be paragraph-level, not an exhaustive claim graph. It should map each substantive body paragraph to declared grounding when possible:

- stable report target ID
- section and paragraph locator
- text hash
- rendered text snippet
- citation references used in the paragraph
- cited source IDs
- upstream finding IDs
- upstream evidence IDs
- warnings that affect the paragraph
- optional grounding status or not-grounded reason
- optional support note

Do not require `support_level` or `claim_type` in v1. If the writer includes them, treat them as advisory agent-authored labels, not deterministic facts.

Example:

```json
{
  "report_path": "deep-research-topic/draft.md",
  "targets": [
    {
      "target_id": "rp-001",
      "section": "Executive Summary",
      "paragraph": 2,
      "text_hash": "sha256:...",
      "text_snippet": "Configural processing and category conflict have the strongest support...",
      "citation_refs": ["[3]", "[8]", "[14]"],
      "source_ids": ["src-003", "src-011", "src-024"],
      "finding_ids": ["finding-2", "finding-7"],
      "evidence_ids": ["ev-0004", "ev-0011", "ev-0032"],
      "warnings": [],
      "grounding_status": "declared_grounded"
    }
  ]
}
```

Paragraph numbers are locators, not identity. The stable target ID plus text hash/snippet lets reviewers and revisers reconnect issues after edits.

Missing grounding is an audit finding, not a hard delivery gate. Some paragraphs may be intentionally ungrounded because they are framing, transitions, scope notes, method notes, or synthesis connective tissue. In those cases, the manifest can include `not_grounded_reason`; the agent decides whether to revise, disclose a limitation, or proceed.

The writer-authored manifest is author-declared provenance. A reviewer, verifier, or reviser may validate it, annotate it, or revise it, but deterministic tooling must not treat it as proof that the paragraph is semantically supported.

Before any support audit relies on the manifest, run deterministic consistency checks:

- the report path exists
- each target text hash still matches the current draft text
- citation references listed in a target actually occur in the target text
- referenced source IDs, finding IDs, and evidence IDs exist in available state
- stale or orphaned targets are marked instead of silently trusted

Start with a file manifest. Add database tables only after the manifest proves useful.

### 4. Citation Audit Manifest

Add a citation audit capability that checks whether a cited source supports the local sentence or paragraph where it is used.

The audit may use deterministic helpers to enumerate citation contexts from `report-grounding.json`, but the support classification is an agent judgment.

The audit should classify each checked citation as:

- `supported`
- `weak_support`
- `topically_related_only`
- `overstated`
- `missing_specific_fact`
- `needs_additional_source`
- `unresolved`

The audit should recommend one action:

- `keep`
- `weaken_wording`
- `split_claim`
- `add_source`
- `replace_source`
- `mark_unresolved`

Important constraint:

The audit advises. The reviser or orchestrating agent decides how to change the report.

### 5. Evidence Coverage And Report Support Audit

Add a declared-grounding and support audit report that summarizes weak spots before delivery.

The deterministic audit should first validate the grounding manifest, then report:

- report paragraphs with declared grounding entries
- report paragraphs without grounding entries
- findings with evidence links
- findings without evidence links
- report targets with declared evidence links
- report targets with only declared finding-level links
- report targets depending on degraded, abstract-only, stale, secondary, or self-interested sources
- citations checked by citation audit
- citations rejected or weakened by citation audit
- unresolved review issues
- sections with high weak-support density, based on agent-authored classifications

The audit should not infer semantic support directly from prose. It should aggregate validated declared grounding, existing evidence links, source flags, and agent-authored audit outcomes. Its output should distinguish declared grounding paths from agent-verified support judgments.

This is an audit surface, not a hidden automatic gate. The agent can decide whether the report is good enough, needs revision, or should disclose limitations.

### 6. Reviewer-Issue Traceability

Make reviewer issues point to concrete targets and preserve enough locator data to survive edits.

Initial target types:

- `source`
- `evidence_unit`
- `finding`
- `report_target`
- `citation`

Use `report_target` for paragraph-level report locations. Keep section, paragraph number, snippet, and hash as locator metadata instead of creating a separate paragraph target namespace.

Initial fields:

- `issue_id`
- `dimension`
- `severity`
- `target_type`
- `target_id`
- `locator`
- `text_hash`
- `text_snippet`
- `related_source_ids`
- `related_evidence_ids`
- `related_citation_refs`
- `status`
- `rationale`
- `resolution`

Initial issue statuses:

- `open`
- `resolved`
- `partially_resolved`
- `accepted_as_limitation`
- `rejected_with_rationale`

This makes revision outcomes inspectable without requiring a full graph.

### 7. Contradiction Candidates

Track contradictions as review issues first, not as a graph subsystem.

Initial fields:

- conflicting target IDs
- plain-language description
- contradiction type
- status
- final-report handling

Suggested contradiction types:

- `direct_conflict`
- `scope_difference`
- `temporal_difference`
- `method_difference`
- `apparent_uncertainty`
- `source_quality_conflict`

This preserves disagreements while avoiding premature automated contradiction resolution.

## Implementation Slices

### Slice 1: Minimal Run-Local Evidence Policy

Goal:

Create or revise the calibration artifact when useful without adding fixed domain modes.

Likely changes:

- Add a short optional evidence policy artifact generated from the brief and early source landscape.
- Keep it as text or lightweight YAML.
- Feed it to source acquisition, synthesis, verification, citation audit, and review prompts through a shared support-context surface when available.
- Ensure commands and prompts still work when it is absent.

Success criteria:

- Support checking adapts to question risk and source landscape.
- The policy remains local to the run.
- No permanent domain taxonomy is introduced.
- No mandatory pipeline phase is introduced.

### Slice 2: Source Quality And Caution Flags

Goal:

Preserve extraction/access quality while adding queryable source caution annotations.

Likely changes:

- Keep existing `sources.quality` semantics for access and extraction status.
- Add a small source-flag state surface, such as `source_flags(session_id, source_id, flag, applies_to_type, applies_to_id, rationale, created_by, created_at)`.
- Keep deduplication, reader validation, and contradiction state separate from source extraction quality.
- Add CLI commands to set, list, and summarize source flags.
- Update acquisition, reader, synthesis, verification, and review guidance to apply and consume flags through the shared support context where practical.
- Include quality and caution counts in reflection metrics.

Success criteria:

- Agents can mark sources as stale, secondary, self-interested, undated, or low relevance, with scope when needed, without overwriting extraction quality.
- Synthesis can see source warnings before writing.
- Reflection can report source-quality and source-caution counts across a session.

### Slice 3: Report Grounding Manifest

Goal:

Have the writer emit `report-grounding.json` alongside `draft.md`.

Likely changes:

- Update `agents/synthesis-writer.md`.
- Define the paragraph-level manifest schema.
- Ask the writer to ground substantive body paragraphs when possible, or record a concise `not_grounded_reason` for paragraphs that are framing, transitions, scope notes, method notes, or otherwise intentionally ungrounded.
- Add deterministic manifest consistency validation before support audits consume the manifest.
- Include text hash/snippet, citations, source IDs, finding IDs, evidence IDs, and warnings.
- Treat support labels as optional advisory fields, not required v1 data, and treat the manifest itself as writer-declared provenance until reviewed.

Success criteria:

- Most substantive body paragraphs either map to at least one `finding_id` or have an explicit `not_grounded_reason`.
- Quantitative or fragile paragraphs map to evidence IDs when available.
- Unsupported, weakly supported, or intentionally ungrounded paragraphs are explicit rather than hidden behind prose.
- Missing, stale, or internally inconsistent grounding entries are surfaced automatically.

### Slice 4: Report Support Audit

Goal:

Use existing state plus `report-grounding.json` to produce a declared-grounding and support audit.

Likely changes:

- Add a command or script equivalent to `audit-report-support`.
- Read findings, evidence units, source quality, source flags, reviewer issues, and report grounding.
- Validate grounding entries against the current draft and available state before aggregation.
- Write a compact JSON or markdown audit under `revision/`.
- Keep the command deterministic: aggregate declared grounding and agent-authored classifications rather than judging support from prose.

Success criteria:

- Ungrounded report paragraphs are surfaced automatically.
- Stale grounding entries, missing referenced objects, and citation-ref mismatches are surfaced automatically.
- Paragraphs depending on flagged sources are visible.
- Sections with weak support are measurable when weak support has been classified by an agent.

### Slice 5: Citation Audit Manifest

Goal:

Produce structured citation audit results without changing the whole pipeline.

Likely changes:

- Add a citation audit output format under `revision/`.
- Update claim verification guidance to emit citation-level outcomes when citations are checked.
- Use `report-grounding.json` when available so audit starts from writer-declared grounding.

Success criteria:

- A checked citation has a local claim or paragraph target, cited source IDs, support classification, rationale, and recommended action.
- Weak or topically related citations are visible before revision.
- The reviser can target citation problems directly.

### Slice 6: Revision Integration

Goal:

Make revision start from declared grounding, verified weak spots, and open issues instead of rediscovering them from prose.

Likely changes:

- Update `skills/deep-research-revision/SKILL.md`.
- Update `agents/claim-extractor.md` to prefer report grounding when present.
- Update `agents/claim-verifier.md` to preserve report target IDs and citation audit outcomes.
- Update `agents/report-reviser.md` to carry target IDs, snippets, hashes, and status changes into the revision manifest.

Success criteria:

- Verifier time shifts toward weak, unsupported, quantitative, current, or citation-sensitive targets.
- Fewer unverifiable outcomes come from report-to-source ambiguity.
- Revision records which declared targets, verified support problems, or citations were fixed.

### Slice 7: Reviewer-Issue Traceability

Goal:

Make review and revision outcomes auditable.

Likely changes:

- Define a compact reviewer issue schema.
- Update synthesis reviewer, style reviewer, claim verifier, citation audit, and report reviser guidance to use target IDs where available.
- Add issue status tracking in revision artifacts first.
- Promote issue state into SQLite only after file artifacts prove useful.

Success criteria:

- Each substantive reviewer issue points to the artifact it criticizes.
- Revision records whether each issue was resolved, partially resolved, accepted as a limitation, or rejected with rationale.
- Open issues can be listed before final delivery.

### Slice 8: State Ingestion And Reflection Metrics

Goal:

Promote useful manifests into queryable state once the file-based version has proven value.

Possible additions:

- `report_targets`
- `report_target_evidence`
- `report_target_findings`
- `citation_audits`
- `review_issues`

Reflection metrics:

- report targets total
- report targets with declared finding links
- report targets with declared evidence links
- report targets without grounding
- quantitative or fragile targets without structured evidence, when classified
- citations audited
- citations weakened or rejected
- reviewer issues with target IDs
- unresolved issues before delivery

Success criteria:

- Declared grounding coverage and verified support problems become tracked quality dimensions.
- The schema remains small enough that agents can understand the output without reading internal code.

## Recommended Order

1. Minimal optional run-local evidence policy.
2. Source quality and caution flags.
3. Report grounding manifest.
4. Report support audit.
5. Citation audit manifest.
6. Revision integration.
7. Reviewer-issue traceability and contradiction candidates.
8. State ingestion and reflection metrics.

If only one substantive code slice is built first, build the report grounding manifest. It connects the already-existing evidence layer to the final report, which is where support currently becomes hardest to inspect.

If a prompt-only change is allowed before code work, add the minimal optional run-local evidence policy first so later slices can inherit the same calibration when the agent chooses to use it.

## Validation

Validate each slice against recent completed sessions.

Useful checks:

- Does this expose a real failure that was previously hidden?
- Does it reduce verifier or reviser ambiguity?
- Does it save tokens or prevent repeated work?
- Does it preserve agent judgment?
- Is the output understandable without reading internal code?
- Does it make the final report more auditable without forcing a rigid workflow?

If a slice does not improve downstream decisions, remove or simplify it.

## Success Metrics

Track these across sessions:

- number of sources with extraction/access quality warnings
- number of sources with caution flags
- findings with evidence links
- findings without evidence links
- report targets with declared finding links
- report targets with declared evidence links
- report targets without grounding
- report targets depending on flagged sources
- citations audited
- citations classified as weak, overstated, or topically related only
- reviewer issues with target IDs
- reviewer issues resolved before delivery
- unresolved contradictions or limitations disclosed in the report

The metrics should make reliability visible. They should not become a rigid scoring system that overrides the agent's judgment.

## Deferred Work

Only consider these after the MVP has shown repeated value:

- graph-backed artifact relationships
- richer contradiction ledger
- provider-level retrieval yield learning
- optional domain packs for specialized citation or evidence norms
- evidence trail appendix
- stricter completion gates for smaller or cheaper models

## Recommendation

Build the smallest provenance layer that makes agents better writers, reviewers, and revisers.

The combined plan is:

- keep source extraction quality separate from source caution flags
- calibrate evidence expectations locally to the run when useful
- declare report grounding as the report is written
- audit declared grounding coverage, verified support problems, and citation fit
- make reviewer issues target concrete artifacts
- ingest only the manifests that prove useful

This preserves the report-grounding plan's concrete path while keeping the broader provenance proposal faithful to `PRINCIPLES.md`.
