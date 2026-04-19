# Structured Evidence Layer Checklist

## Phase 1: State and Artifact Foundation

- [x] Add `evidence_units` table to `skills/deep-research/scripts/state.py`
  - Include IDs, source linkage, question linkage, claim text, claim type, relation, strength, provenance, structured fields, tags, and timestamps
  - Add indexes for `source_id` and `primary_question_id`
  - Add migration coverage for existing session databases

- [x] Add `finding_evidence` join table to `skills/deep-research/scripts/state.py`
  - Keep `findings` intact for compatibility
  - Make evidence linkage explicit instead of embedding it in prose

- [x] Create state commands for evidence ingestion and retrieval
  - `add-evidence`
  - `add-evidence-batch`
  - `evidence`
  - `link-finding-evidence`
  - optional `evidence-summary`

- [x] Extend session export and handoff paths
  - Update `summary`
  - Update `summary --compact`
  - Update `summary --write-handoff`
  - Update `audit`
  - Include evidence counts and cited-evidence filtering

- [x] Add `evidence/` to the session artifact model
  - Reader-produced JSON should be inspectable on disk
  - Do not make SQLite the only source of truth for evidence extraction artifacts

## Phase 2: Reader Extraction

Highest-leverage phase. The claim-verifier is notes-only — its effectiveness is bounded by what reader notes contain. Evidence units at reading time improve verification coverage without any verifier changes.

- [x] Update `agents/research-reader.md`
  - Require each reader to emit 3-8 load-bearing evidence units per source
  - Keep the markdown note as the human-readable artifact
  - Require compact provenance such as note section or source line span
  - Require short quotes only for fragile or quantitative claims

- [x] Decide and document the evidence manifest schema
  - Source-level envelope
  - Unit-level fields
  - Provenance rules
  - Quantitative field conventions

- [x] Update the deep-research orchestrator in `skills/deep-research/SKILL.md`
  - Readers should ingest evidence after note generation
  - Handoff instructions should mention evidence as a first-class artifact

## Phase 3: Evidence-Backed Findings and Downstream Consumers

- [ ] Update `agents/findings-logger.md`
  - Primary path should read from `state evidence`
  - Note re-reading should become fallback behavior
  - Findings should link back to evidence IDs when logged

- [ ] Update `agents/synthesis-writer.md`
  - Use evidence-linked findings as the canonical support layer
  - Use notes for nuance, limitations, and narrative stitching
  - Require evidence-backed citation assembly in the handoff contract

- [ ] Update `agents/claim-extractor.md`
  - Map from evidence units to verification targets instead of re-parsing the report
  - Use `claim_type` and `structured_data` from evidence units to pre-classify verification priority
  - Fall back to report parsing when evidence units are absent (backward compatible)

- [ ] Update `agents/claim-verifier.md`
  - Check claims against evidence units (which carry provenance spans) instead of raw reader notes
  - Use `line_start`/`line_end` provenance for targeted source reads when needed
  - Use `relation` field to flag contradiction and qualifier claims for priority verification
  - Fall back to notes-only verification when evidence units are absent (current behavior)

## Phase 4: Metrics, Reflection, and Audit

- [ ] Extend `skills/reflect/scripts/metrics.py`
  - `evidence_units_total`
  - `evidence_units_by_question`
  - `evidence_units_by_type`
  - `evidence_units_with_spans`
  - `findings_without_evidence_links`

- [ ] Extend `state audit`
  - Warn on findings with no linked evidence
  - Warn on evidence units with missing source provenance
  - Warn when a question has findings but almost no primary evidence units

## Testing

- [x] Add state tests in `tests/test_state.py`
  - schema creation
  - migrations
  - add/list/query evidence
  - linking evidence to findings
  - handoff export behavior

- [ ] Add quality and provenance tests
  - line-span handling
  - quote truncation rules
  - evidence-unit validation

- [ ] Add end-to-end fixture coverage
  - reader evidence manifest ingestion
  - evidence-aware summary handoff
  - finding linkage persistence

## Documentation

- [x] Add design doc in `docs/structured-evidence-layer.md`
- [ ] Update `docs/architecture.md` after rollout is stable
- [ ] Update example or internal workflow docs if evidence artifacts change the session layout

## Rollout Guardrails

- [x] Keep notes and findings working during migration
- [x] Keep evidence optional in the first release path — claim-extractor and claim-verifier already fall back to report parsing and notes-only verification when evidence units are absent
- [ ] Gate full downstream dependence on evidence until reader extraction is stable
- [ ] Measure handoff size before and after evidence export

## Deferred For Later

- [ ] Claim-check persistence for the verifier
- [ ] Automatic contradiction clustering across sources
- [ ] UI or report appendix that exposes evidence trails directly
