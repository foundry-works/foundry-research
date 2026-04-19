# Structured Evidence Layer Plan

## Objective

Add a first-class structured evidence capability between reading and synthesis so the pipeline stops relying on prose-only handoffs for its most important claims.

The proposal is to introduce `evidence_units`: machine-readable claim records with source provenance, question mapping, evidence strength, and optional quantitative fields. Readers extract them close to the source; findings become clusters of evidence units rather than standalone prose blobs.

## Why This Is The Highest-Leverage Improvement

The current pipeline is already strong at source acquisition, content validation, session state, and review orchestration. The weakest link is the knowledge handoff:

- Reader output is rich but lives mostly in markdown notes.
- `findings` are stored as free text plus source IDs, which loses claim-level structure.
- The synthesis writer must re-parse notes to recover what the source actually said.
- The verifier samples only a small subset of claims because exhaustive traceability is too expensive.

This creates the main quality bottleneck: the system has good sources, but its evidence representation becomes lossy before drafting.

## Proposal Summary

Introduce a structured evidence layer with three core pieces:

1. `evidence_units` in session state
2. On-disk evidence manifests per source
3. Updated agent prompts and handoffs that use evidence units as the canonical claim substrate

Each evidence unit should capture:

- `source_id`
- `question_ids`
- `claim_text`
- `claim_type` such as `result`, `method`, `limitation`, `contradiction`, `background`
- `relation` such as `supports`, `contradicts`, `qualifies`
- `evidence_strength`
- provenance fields such as note path, content path, line span, and short quote
- optional structured quantitative fields

## Principles Fit

This aligns with `PRINCIPLES.md`:

- It adds a capability, not a monolithic factory.
- It improves agent judgment by giving agents better inputs.
- It preserves composability: readers extract, state stores, loggers cluster, writers synthesize.
- It improves observability because claims become auditable without re-reading every note.

## Rollout Phases

### Phase 1: State and Artifact Foundation

Add the data model and storage layer without changing orchestration behavior yet.

- Add `evidence_units` and `finding_evidence` tables to `skills/deep-research/scripts/state.py`
- Add state commands for adding, listing, and exporting evidence
- Add `evidence/` as a session artifact directory for reader-produced JSON manifests
- Extend `summary`, `summary --compact`, `summary --write-handoff`, and `audit` to expose evidence counts and coverage

Deliverable:

- Evidence can be stored, queried, and exported even if the rest of the pipeline still works from notes and findings.

### Phase 2: Reader Extraction

Make the reader the first producer of structured evidence. This is the highest-leverage phase: the claim-verifier is now notes-only, so its effectiveness is bounded by what reader notes contain. Structured evidence units at reading time directly improve verification coverage without changing the verifier architecture.

- Update `agents/research-reader.md` so each reader writes both:
  - a human-readable note in `notes/`
  - a structured evidence manifest in `evidence/`
- Ingest reader evidence through new `state add-evidence-batch` commands
- Require short provenance spans and compact quotes for load-bearing claims

Deliverable:

- Each deeply-read source yields 3-8 evidence units with durable provenance.
- The claim-verifier gains richer structured inputs without any verifier changes.

### Phase 3: Evidence-Backed Findings and Downstream Consumers (DONE)

Wire evidence into findings, synthesis, and verification in one pass. The two-phase verifier (claim-extractor + claim-verifier) makes this lighter than the original plan assumed — evidence units map naturally to the extractor's claim schema and the verifier's provenance needs.

- [x] `state.py`: `log-finding` accepts `--evidence-ids`; `deduplicate-findings` propagates evidence links when merging
- [x] `agents/findings-logger.md`: queries `state evidence --question-id` as primary input, links findings to evidence via `--evidence-ids`, returns evidence_ids in manifest
- [x] `state.py` handoff: per-finding `evidence_ids` attached in `summary --write-handoff`
- [x] `agents/synthesis-writer.md`: reads `synthesis-handoff.json` first, uses evidence units for citation precision, flags findings without evidence as lower confidence
- [x] `agents/claim-extractor.md`: cross-references `state evidence` per source, adds `matched_evidence_ids` and `evidence_strength` to claims manifest
- [x] `agents/claim-verifier.md`: uses evidence provenance spans for targeted source reads (preferred), note-reading as fallback
- [x] Revision skill: passes state CLI path to claim-extractor and claim-verifier for evidence queries

Deliverable:

- Findings become auditable summaries of explicit evidence, not free-floating prose.
- Drafting and verification run from a shared evidence substrate with better citation precision and lower re-parsing cost.

### Phase 4: Metrics, Reflection, and Tightening (DONE)

Measure whether the feature actually improves quality and efficiency.

- [x] Extend `skills/reflect/scripts/metrics.py` with evidence metrics
- [x] Add audit checks for findings with no linked evidence
- [x] Add handoff-size guardrails so structured evidence does not become token bloat
- [x] Update architecture docs after the feature is stable

Deliverable:

- The new layer is measurable, not just conceptually cleaner.

## Expected Wins

- Better citation traceability: claim to finding to evidence unit to source span
- Better synthesis quality: less information loss between reading and writing
- Better verification coverage: claim-extractor maps evidence units to verification targets; claim-verifier checks against structured provenance instead of raw notes
- Better token efficiency: findings loggers stop re-reading the full note set for every question
- Better observability: quality gaps become visible at the claim level

## Main Risks

### Risk 1: Over-structuring the reader task

If the schema is too rigid, readers will either fail or produce junk.

Mitigation:

- Keep the initial schema small
- Limit extraction to load-bearing claims
- Store optional detail in JSON blobs instead of forcing full normalization

### Risk 2: Token and artifact bloat

Structured evidence can become noisy if every note sentence becomes a unit.

Mitigation:

- Cap units per source
- Keep quotes short
- Export only cited or relevant evidence in `summary --write-handoff`

### Risk 3: Migration complexity

Replacing the current findings flow all at once is unnecessary risk.

Mitigation:

- Keep `findings` and notes as compatible layers during rollout
- Introduce evidence links before making evidence the primary downstream input

## Success Criteria

The feature is successful if it produces all of the following:

- Most report claims can be traced to at least one evidence unit
- The claim-verifier can check more load-bearing claims using evidence unit provenance instead of raw note reads
- Findings coverage can be measured by evidence counts, not just prose counts
- The writer needs fewer note re-reads to draft a well-cited report
- Reflection metrics can detect unsupported findings and thin evidence clusters

## Immediate Scope

This plan does not require redesigning the whole pipeline. The first milestone is narrower:

- schema
- CLI
- reader extraction

That is enough to prove whether the capability improves the pipeline before deeper changes land. Reader extraction is prioritized because the two-phase verifier architecture makes evidence units at reading time immediately useful — the claim-verifier gains richer inputs without any verifier-side changes.
