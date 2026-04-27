# Plan Checklist: Provenance, Grounding, and Support Audit

Source of truth: `plan.md`.

This checklist follows the recommended order in `plan.md` and keeps the core boundary explicit: deterministic tools report structure and consistency; agents make semantic support judgments.

## Cross-Cutting Guardrails

- [x] Re-read `PRINCIPLES.md` before implementation and confirm each slice preserves capabilities rather than a rigid factory.
- [x] Keep the agent in control of semantic judgments, final conclusions, readiness decisions, and limitation tradeoffs.
- [x] Keep deterministic tools limited to structural facts: missing links, missing files, stale hashes, citation locations, unresolved issues, counts, and known flags.
- [ ] Treat writer-produced report grounding as declared provenance until a reviewer, verifier, or reviser audits it.
- [x] Keep every new artifact optional in v1; prompts and commands must degrade cleanly when it is absent.
- [x] Avoid fixed domain modes, permanent domain taxonomies, or core domain-specific evidence hierarchies.
- [x] Avoid a full artifact graph, heavyweight edge taxonomy, automatic contradiction resolution, or hidden pass/fail scoring.
- [x] Expose policy, source warnings, declared grounding, citation audits, and open issues through one compact support-context surface when prompts need them.

## Slice 1: Minimal Optional Run-Local Evidence Policy

Goal: create or revise a local calibration artifact when useful, without adding fixed domain modes or a mandatory phase.

- [x] Choose and document the run-local policy artifact path, such as `evidence-policy.yaml` in the session root.
- [x] Define the v1 policy fields:
  - [x] `source_expectations`
  - [x] `freshness_requirement`
  - [x] `inference_tolerance`
  - [x] `high_stakes_claim_patterns`
  - [x] `known_failure_modes`
- [x] Update `skills/deep-research/SKILL.md` to allow the supervisor to create or revise the policy from the brief and early source landscape when useful.
- [x] Keep policy creation advisory; no command or workflow step should require the policy to exist.
- [x] Add or update a shared support-context formatter that can include the policy when present.
- [x] Feed policy context, when present, to source acquisition, reading, synthesis, claim extraction, claim verification, citation audit, and review prompts.
- [x] Make support checking stricter for high-stakes, quantitative, current, legal, regulatory, or scientific claims when the policy calls for it.
- [x] Keep interpretive synthesis possible when the policy allows more inference tolerance.
- [x] Add tests or fixtures proving prompts and tools still work when the policy is missing.

Success criteria:

- [x] Support expectations adapt to the brief and source landscape.
- [x] The policy remains local to the run.
- [x] No fixed domain taxonomy or mandatory policy phase is introduced.

## Slice 2: Source Quality And Source Caution Flags

Goal: preserve extraction/access quality while adding queryable source caution annotations.

- [x] Audit current `sources.quality` values and map any existing names to the plan's access/extraction semantics without breaking old sessions.
- [x] Keep `sources.quality` focused on access and extraction condition only:
  - [x] `ok`
  - [x] `inaccessible`
  - [x] `abstract_only`
  - [x] `degraded_extraction`
  - [x] `metadata_incomplete`
  - [x] `title_content_mismatch`
- [x] Define source caution flags as additive annotations, not replacements for quality:
  - [x] `secondary_source`
  - [x] `self_interested_source`
  - [x] `undated`
  - [x] `potentially_stale`
  - [x] `low_relevance`
- [x] Do not add `weak_support` as a source flag; keep weak support as a relationship between evidence and a finding, report target, or citation.
- [x] Add a small source-flag state surface, such as `source_flags(session_id, source_id, flag, applies_to_type, applies_to_id, rationale, created_by, created_at)`.
- [x] Support scoped flags with:
  - [x] `applies_to`: `run`, `brief`, `finding`, `report_target`, or `citation`
  - [x] `applies_to_id` when narrower than the run
  - [x] `rationale`
- [x] Keep deduplication, reader validation, validation events, source relationships, reviewer issues, and contradictions separate from source quality.
- [x] Add CLI commands to set source flags.
- [x] Add CLI commands to list source flags by source and by scope.
- [x] Add CLI commands to summarize source quality and caution counts for a session.
- [x] Update `agents/source-acquisition.md` to assign source caution flags when useful.
- [x] Update `agents/research-reader.md` to preserve quality semantics and add scoped caution flags when source context warrants it.
- [x] Update `agents/synthesis-writer.md` to consume source warnings through support context before writing.
- [x] Update `agents/claim-extractor.md`, `agents/claim-verifier.md`, and reviewer prompts to use source warnings as prioritization inputs.
- [x] Add reflection metrics for source quality counts and caution flag counts.
- [x] Add state-layer tests for source flag creation, listing, scoping, and summaries.

Success criteria:

- [x] Agents can mark stale, secondary, self-interested, undated, or low-relevance sources without overwriting extraction quality.
- [x] Synthesis can see source warnings before writing.
- [x] Reflection can report source-quality and source-caution counts across a session.

## Slice 3: Report Grounding Manifest

Goal: have the writer emit `report-grounding.json` alongside `draft.md`.

- [x] Define and document the paragraph-level `report-grounding.json` schema.
- [x] Update `agents/synthesis-writer.md` to write `report-grounding.json` with the final draft.
- [x] Map each substantive body paragraph to a stable report target when possible.
- [x] Include required v1 locator and provenance fields:
  - [x] `target_id`
  - [x] `section`
  - [x] `paragraph`
  - [x] `text_hash`
  - [x] `text_snippet`
  - [x] `citation_refs`
  - [x] `source_ids`
  - [x] `finding_ids`
  - [x] `evidence_ids`
  - [x] `warnings`
- [x] Include optional advisory fields without making them deterministic facts:
  - [x] `grounding_status`
  - [x] `not_grounded_reason`
  - [x] `support_note`
  - [x] `support_level`
  - [x] `claim_type`
- [x] Use `not_grounded_reason` for intentionally ungrounded framing, transitions, scope notes, method notes, and connective tissue.
- [x] Keep paragraph numbers as locators, not identity; reconnect by `target_id`, hash, and snippet after edits.
- [x] Add deterministic manifest consistency validation before any support audit consumes the manifest:
  - [x] Report path exists.
  - [x] Target hashes still match current draft text.
  - [x] Citation references listed for a target actually occur in that target text.
  - [x] Referenced source IDs exist.
  - [x] Referenced finding IDs exist.
  - [x] Referenced evidence IDs exist.
  - [x] Stale or orphaned targets are marked instead of silently trusted.
- [x] Treat missing grounding as an audit finding, not a hard delivery gate.
- [x] Start with a file manifest; defer database tables until the manifest proves useful.
- [x] Add fixture coverage for valid manifests, stale hashes, missing citations, and missing referenced IDs.

Success criteria:

- [x] Most substantive body paragraphs either map to at least one `finding_id` or have an explicit `not_grounded_reason`.
- [x] Quantitative or fragile paragraphs map to evidence IDs when available.
- [x] Unsupported, weakly supported, or intentionally ungrounded paragraphs are explicit.
- [x] Missing, stale, or internally inconsistent grounding entries are surfaced automatically.

## Slice 4: Report Support Audit

Goal: produce a deterministic declared-grounding and support audit from existing state plus `report-grounding.json`.

- [ ] Add a command or script equivalent to `audit-report-support`.
- [ ] Validate `report-grounding.json` before aggregation.
- [ ] Read and aggregate:
  - [ ] Findings
  - [ ] Evidence units
  - [ ] Source extraction/access quality
  - [ ] Source caution flags
  - [ ] Reviewer issues
  - [ ] Citation audit results
  - [ ] Report grounding targets
- [ ] Write compact JSON or markdown audit output under `revision/`.
- [ ] Report paragraphs with declared grounding entries.
- [ ] Report paragraphs without grounding entries.
- [ ] Findings with evidence links.
- [ ] Findings without evidence links.
- [ ] Report targets with declared evidence links.
- [ ] Report targets with only declared finding-level links.
- [ ] Report targets depending on degraded, abstract-only, stale, secondary, or self-interested sources.
- [ ] Citations checked by citation audit.
- [ ] Citations rejected or weakened by citation audit.
- [ ] Unresolved review issues.
- [ ] Sections with high weak-support density based on agent-authored classifications.
- [ ] Clearly distinguish declared grounding paths from agent-verified support judgments.
- [ ] Do not infer semantic support directly from report prose.
- [ ] Add state and fixture tests for audit output and manifest validation failures.

Success criteria:

- [ ] Ungrounded report paragraphs are surfaced automatically.
- [ ] Stale grounding entries, missing referenced objects, and citation-ref mismatches are surfaced automatically.
- [ ] Paragraphs depending on flagged sources are visible.
- [ ] Sections with weak support are measurable when weak support has been classified by an agent.

## Slice 5: Citation Audit Manifest

Goal: produce structured citation audit results without changing the whole pipeline.

- [ ] Define the citation audit output format under `revision/`, such as `citation-audit.json`.
- [ ] Use `report-grounding.json` when present to enumerate local citation contexts.
- [ ] Preserve target fields for each checked citation:
  - [ ] Local claim or paragraph target
  - [ ] `report_target` ID
  - [ ] Section and paragraph locator
  - [ ] Text snippet and hash
  - [ ] Citation reference
  - [ ] Cited source IDs
- [ ] Add support classifications:
  - [ ] `supported`
  - [ ] `weak_support`
  - [ ] `topically_related_only`
  - [ ] `overstated`
  - [ ] `missing_specific_fact`
  - [ ] `needs_additional_source`
  - [ ] `unresolved`
- [ ] Add recommended actions:
  - [ ] `keep`
  - [ ] `weaken_wording`
  - [ ] `split_claim`
  - [ ] `add_source`
  - [ ] `replace_source`
  - [ ] `mark_unresolved`
- [ ] Update `agents/claim-verifier.md` or add a citation-audit prompt path to emit citation-level outcomes when citations are checked.
- [ ] Feed citation audit outcomes into report support audit and revision.
- [ ] Keep citation support classification agent-authored; deterministic helpers only enumerate contexts and aggregate results.
- [ ] Add tests or fixtures for citation audit ingestion and support-audit aggregation.

Success criteria:

- [ ] Checked citations have target IDs, cited source IDs, support classification, rationale, and recommended action.
- [ ] Weak or topically related citations are visible before revision.
- [ ] The reviser can target citation problems directly.

## Slice 6: Revision Integration

Goal: make revision start from declared grounding, verified weak spots, and open issues instead of rediscovering them from prose.

- [ ] Update `skills/deep-research-revision/SKILL.md` to prefer `report-grounding.json` when it exists.
- [ ] Update `agents/claim-extractor.md` to read existing grounded targets first.
- [ ] Keep report parsing as a fallback when grounding is absent or incomplete.
- [ ] Update `agents/claim-verifier.md` to accept grounded target objects with linked `finding_id`, `evidence_id`, `source_id`, citation, locator, snippet, and hash fields.
- [ ] Preserve report target IDs and citation audit outcomes through verification.
- [ ] Prioritize weak, unsupported, quantitative, current, high-stakes, and citation-sensitive targets.
- [ ] Update `agents/report-reviser.md` to carry target IDs, snippets, hashes, and status changes into the revision manifest.
- [ ] After revision, either regenerate grounding for edited passages or explicitly mark stale grounding records as needing refresh.
- [ ] Ensure revision records which declared targets, verified support problems, citation problems, or open issues were fixed.
- [ ] Add regression coverage for grounded-target verification and stale-grounding handling after edits.

Success criteria:

- [ ] Verifier time shifts toward weak, unsupported, quantitative, current, or citation-sensitive targets.
- [ ] Fewer unverifiable outcomes come from report-to-source ambiguity.
- [ ] Revision records which declared targets, verified support problems, or citations were fixed.

## Slice 7: Reviewer-Issue Traceability And Contradiction Candidates

Goal: make review, contradiction handling, and revision outcomes auditable.

- [ ] Define a compact reviewer issue schema with:
  - [ ] `issue_id`
  - [ ] `dimension`
  - [ ] `severity`
  - [ ] `target_type`
  - [ ] `target_id`
  - [ ] `locator`
  - [ ] `text_hash`
  - [ ] `text_snippet`
  - [ ] `related_source_ids`
  - [ ] `related_evidence_ids`
  - [ ] `related_citation_refs`
  - [ ] `status`
  - [ ] `rationale`
  - [ ] `resolution`
- [ ] Support initial target types:
  - [ ] `source`
  - [ ] `evidence_unit`
  - [ ] `finding`
  - [ ] `report_target`
  - [ ] `citation`
- [ ] Support initial issue statuses:
  - [ ] `open`
  - [ ] `resolved`
  - [ ] `partially_resolved`
  - [ ] `accepted_as_limitation`
  - [ ] `rejected_with_rationale`
- [ ] Update `agents/synthesis-reviewer.md` to use target IDs where available.
- [ ] Update `agents/style-reviewer.md` to preserve report locators and target IDs where available.
- [ ] Update `agents/claim-verifier.md` and citation audit output to emit traceable issue targets.
- [ ] Update `agents/report-reviser.md` to record issue status transitions and resolutions.
- [ ] Add issue status tracking in revision artifacts first.
- [ ] List open issues before final delivery.
- [ ] Track contradiction candidates as review issues first, not as a graph subsystem.
- [ ] Define contradiction candidate fields:
  - [ ] Conflicting target IDs
  - [ ] Plain-language description
  - [ ] Contradiction type
  - [ ] Status
  - [ ] Final-report handling
- [ ] Support suggested contradiction types:
  - [ ] `direct_conflict`
  - [ ] `scope_difference`
  - [ ] `temporal_difference`
  - [ ] `method_difference`
  - [ ] `apparent_uncertainty`
  - [ ] `source_quality_conflict`
- [ ] Add fixtures proving review issues survive report edits through target ID, hash, and snippet matching.

Success criteria:

- [ ] Each substantive reviewer issue points to the artifact it criticizes.
- [ ] Revision records whether each issue was resolved, partially resolved, accepted as a limitation, or rejected with rationale.
- [ ] Open issues can be listed before final delivery.

## Slice 8: State Ingestion And Reflection Metrics

Goal: promote useful file manifests into queryable state after they prove valuable.

- [ ] Promote only manifests that have demonstrated repeated value in file form.
- [ ] Add small state tables as needed:
  - [ ] `report_targets`
  - [ ] `report_target_evidence`
  - [ ] `report_target_findings`
  - [ ] `citation_audits`
  - [ ] `review_issues`
- [ ] Add ingestion commands for proven file artifacts, such as report grounding, citation audit results, and review issues.
- [ ] Add compact handoff summaries for grounded report targets and open support issues.
- [ ] Add reflection metrics:
  - [ ] `report_targets_total`
  - [ ] `report_targets_with_declared_finding_links`
  - [ ] `report_targets_with_declared_evidence_links`
  - [ ] `report_targets_without_grounding`
  - [ ] `quantitative_or_fragile_targets_without_structured_evidence`
  - [ ] `report_targets_depending_on_flagged_sources`
  - [ ] `citations_audited`
  - [ ] `citations_weakened_or_rejected`
  - [ ] `reviewer_issues_with_target_ids`
  - [ ] `reviewer_issues_resolved_before_delivery`
  - [ ] `unresolved_issues_before_delivery`
- [ ] Keep output understandable without reading internal code.
- [ ] Add `tests/test_state.py` coverage for ingestion and query behavior.
- [ ] Add `tests/test_metrics.py` coverage for new reflection metrics.
- [ ] Add a small end-to-end fixture that ingests evidence, links findings, emits report grounding, audits support, and records revision outcomes.

Success criteria:

- [ ] Declared grounding coverage and verified support problems become tracked quality dimensions.
- [ ] The schema remains small enough for agents to understand and use.

## Validation Checklist

- [ ] Validate each completed slice against recent completed sessions.
- [ ] Confirm the slice exposes a real failure that was previously hidden.
- [ ] Confirm the slice reduces verifier or reviser ambiguity.
- [ ] Confirm the slice saves tokens or prevents repeated work.
- [ ] Confirm the slice preserves agent judgment.
- [ ] Confirm the output is understandable without reading internal code.
- [ ] Confirm the final report becomes more auditable without forcing a rigid workflow.
- [ ] Remove or simplify any slice that does not improve downstream decisions.

## Success Metrics To Track Across Sessions

- [ ] Number of sources with extraction/access quality warnings.
- [ ] Number of sources with caution flags.
- [ ] Findings with evidence links.
- [ ] Findings without evidence links.
- [ ] Report targets with declared finding links.
- [ ] Report targets with declared evidence links.
- [ ] Report targets without grounding.
- [ ] Report targets depending on flagged sources.
- [ ] Citations audited.
- [ ] Citations classified as weak, overstated, or topically related only.
- [ ] Reviewer issues with target IDs.
- [ ] Reviewer issues resolved before delivery.
- [ ] Unresolved contradictions or limitations disclosed in the report.
- [ ] Confirm metrics improve visibility without becoming a rigid scoring system.

## Deferred Work

- [ ] Defer graph-backed artifact relationships until the MVP proves repeated value.
- [ ] Defer a richer contradiction ledger until review-issue tracking is insufficient.
- [ ] Defer provider-level retrieval yield learning.
- [ ] Defer optional domain packs for specialized citation or evidence norms.
- [ ] Defer evidence trail appendix generation unless user-facing transparency becomes a near-term need.
- [ ] Defer stricter completion gates for smaller or cheaper models.

## Recommended Build Order

1. Minimal optional run-local evidence policy.
2. Source quality and caution flags.
3. Report grounding manifest.
4. Report support audit.
5. Citation audit manifest.
6. Revision integration.
7. Reviewer-issue traceability and contradiction candidates.
8. State ingestion and reflection metrics.

If only one substantive code slice is built first, build the report grounding manifest. If a prompt-only change is allowed before code work, add the minimal optional run-local evidence policy first.
