# Structured Evidence Layer

## Summary

This document proposes a new capability for `foundry-research`: a structured evidence layer between reading and synthesis.

The current pipeline already does four hard things well:

- source acquisition across many providers
- download and content-quality validation
- session state tracking
- multi-agent review and revision

Its weakest point is the representation of evidence after reading. The system gathers high-quality sources, but the most important claims become progressively less structured as they move from source content to notes to findings to report prose.

The proposed fix is to add `evidence_units`: machine-readable claim records with durable provenance.

## Current Problem

Today the knowledge flow looks like this:

1. the reader reads `sources/src-NNN.md`
2. the reader writes a markdown note in `notes/src-NNN.md`
3. a findings logger reads many notes and writes prose findings
4. the synthesis writer reads notes again to draft the report
5. the verifier samples a subset of report claims because full traceability is expensive

This creates three recurring failure modes.

### 1. Claim-level provenance is lost

The reader may extract a precise statement such as:

- only 1 of 8 studies supported the naive hypothesis
- 17 studies met inclusion criteria
- movement effects were linear rather than nonlinear

But once this becomes a `finding`, the state layer stores only prose and source IDs. The exact claim boundaries, local provenance, and quantitative fields are no longer first-class.

### 2. Downstream agents re-parse prose to recover structure

`agents/findings-logger.md` currently reads the full note set per question. `agents/synthesis-writer.md` then reads notes again to recover support for each paragraph. This duplicates work and makes accuracy depend on repeated prose interpretation rather than stable evidence objects.

### 3. Verification budget is spent on discovery, not checking

`agents/research-verifier.md` correctly focuses on 5-10 load-bearing claims because exhaustive claim tracing is too expensive. Without structured evidence, the verifier must first reconstruct what the draft is probably grounded in before it can verify anything.

## Goals

- Preserve claim-level structure after reading
- Make findings auditable at the evidence-unit level
- Reduce repeated note parsing across questions and downstream agents
- Improve citation precision and verification coverage
- Keep the design capability-oriented, inspectable, and composable

## Non-Goals

- Replace the orchestrator with a rigid pipeline
- Eliminate markdown notes
- Fully automate synthesis or contradiction resolution
- Build a heavy knowledge graph before proving value

## Proposed Design

### New Concept: `evidence_units`

An evidence unit is the smallest durable claim object that downstream agents should reason over.

Each evidence unit represents one load-bearing fact, limitation, contradiction, or method detail extracted from one source.

Examples:

- "Only 1 of 8 studies supported the naive uncanny valley hypothesis"
- "The final systematic review sample was 17 studies"
- "Movement effects were linear rather than nonlinear in the reviewed studies"
- "The study used 80 real robot faces rather than morphed images"
- "Trust effects failed to replicate for the male stimulus set"

### Design Constraints

The evidence layer should:

- remain easy for agents to produce
- be queryable by source and by question
- preserve enough provenance for targeted re-reading
- avoid turning every note sentence into a database row

The right granularity is a small set of load-bearing units per source, not exhaustive annotation.

## Session Artifacts

Add a new directory to the session structure:

```text
deep-research-{session}/
├── evidence/
│   └── src-001.json
├── notes/
├── sources/
├── state.db
├── state.json
├── journal.md
└── report.md
```

Why both disk and SQLite:

- disk artifacts preserve observability and raw extraction output
- SQLite supports querying, aggregation, and handoff export

The reader should write `evidence/src-NNN.json`, then ingest that file into state.

## Data Model

### Table: `evidence_units`

Recommended columns:

```sql
CREATE TABLE evidence_units (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    primary_question_id TEXT,
    question_ids TEXT NOT NULL DEFAULT '[]',
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'supports',
    evidence_strength TEXT,
    provenance_type TEXT NOT NULL,
    provenance_path TEXT,
    line_start INTEGER,
    line_end INTEGER,
    quote TEXT,
    structured_data TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (source_id) REFERENCES sources(id)
);
```

Recommended indexes:

```sql
CREATE INDEX idx_evidence_source ON evidence_units(session_id, source_id);
CREATE INDEX idx_evidence_question ON evidence_units(session_id, primary_question_id);
```

### Table: `finding_evidence`

Keep `findings` as a compatibility layer, but make the evidence linkage explicit.

```sql
CREATE TABLE finding_evidence (
    session_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary',
    PRIMARY KEY (finding_id, evidence_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

This lets one finding aggregate several units and lets one evidence unit support more than one synthesized finding if needed.

## Evidence Unit Schema

Reader-produced JSON should use a source envelope with a units array.

```json
{
  "source_id": "src-026",
  "generated_by": "research-reader",
  "units": [
    {
      "primary_question_id": "Q1",
      "question_ids": ["Q1"],
      "claim_text": "Only 1 of 8 studies supported the naive uncanny valley hypothesis.",
      "claim_type": "result",
      "relation": "supports",
      "evidence_strength": "strong",
      "provenance_type": "content_span",
      "provenance_path": "sources/src-026.md",
      "line_start": 103,
      "line_end": 116,
      "quote": "Only 1 of 8 studies found the predicted non-linear effect.",
      "structured_data": {
        "supporting_studies": 1,
        "tested_studies": 8
      },
      "tags": ["systematic_review", "replication", "nonlinear_effect"]
    }
  ]
}
```

## Field Semantics

### `claim_type`

Keep the first version small:

- `result`
- `method`
- `limitation`
- `contradiction`
- `background`

### `relation`

This should describe how the unit relates to the assigned question or claim cluster:

- `supports`
- `contradicts`
- `qualifies`

### `structured_data`

Use a JSON blob for optional structured numbers rather than over-normalizing immediately.

Good candidates:

- sample sizes
- counts
- percentages
- p-values
- confidence intervals
- effect sizes
- year or study window

This is intentionally flexible in version 1.

### Provenance

Use the strongest provenance available:

- `content_span`
- `note_span`
- `abstract`
- `metadata_only`

Rules:

- line spans are preferred when available
- quotes should be short and only used where they help verification
- provenance can be partial, but must not be fabricated

## CLI Changes

Add the following commands to `skills/deep-research/scripts/state.py`.

### Write commands

- `add-evidence --from-json FILE`
- `add-evidence-batch --from-json FILE`
- `link-finding-evidence --finding-id ID --evidence ids`

### Read commands

- `evidence`
- `evidence --source-id src-026`
- `evidence --question-id Q1`
- `evidence --claim-type contradiction`
- `evidence-summary`

### Export changes

Extend:

- `summary`
- `summary --compact`
- `summary --write-handoff`
- `audit`

Recommended additions:

- evidence unit counts by question
- evidence unit counts by claim type
- findings with no linked evidence
- cited evidence only in handoff export

## Agent Changes

### `agents/research-reader.md`

Current behavior:

- write one markdown note
- return a small manifest

Proposed behavior:

- keep the markdown note
- also write `evidence/src-NNN.json`
- ingest evidence via state
- extract 3-8 load-bearing evidence units

Reader guidance changes:

- do not try to encode every note sentence
- prioritize quantitative claims, conclusions, limitations, and contradictions
- include provenance for numbers and fragile claims

### `agents/findings-logger.md`

Current behavior:

- read all notes for one question
- log prose findings

Proposed behavior:

- query `state evidence --question-id`
- cluster evidence units into distinct findings
- link each finding to evidence IDs
- use note reads only when the evidence units are ambiguous or thin

This should materially reduce repeated note parsing across questions.

### `agents/synthesis-writer.md`

Current behavior:

- read notes
- reassemble claims from prose

Proposed behavior:

- treat evidence-linked findings as the canonical support layer
- use notes for nuance, methodological detail, and narrative stitching
- prefer evidence units when building paragraphs with citations

### `agents/claim-extractor.md` and `agents/claim-verifier.md`

The old monolithic `research-verifier` was split into a two-phase architecture:

- **claim-extractor** reads the report and identifies load-bearing claims
- **claim-verifier** checks one pre-extracted claim against local reader notes

Current behavior:

- claim-extractor parses the report to identify 5-10 load-bearing claims
- claim-verifier checks each claim against reader notes (notes-only, no web search)

Proposed behavior:

- claim-extractor maps from evidence units to verification targets instead of re-parsing the report
- claim-verifier checks claims against evidence units (which carry provenance spans) instead of raw notes
- use `line_start`/`line_end` provenance for targeted source reads
- use `relation` field to flag contradiction and qualifier claims
- both agents fall back to current behavior when evidence units are absent

## Migration Strategy

### Step 1: Add state and disk artifacts

Do not change downstream behavior yet.

Success condition:

- readers can emit evidence manifests
- state can ingest and query them

### Step 2: Reader extraction (highest leverage)

Make the reader the first producer of structured evidence. This is the highest-leverage step because the claim-verifier is notes-only — its effectiveness is bounded by what reader notes contain. Evidence units at reading time improve verification coverage without any verifier changes.

Success condition:

- each deeply-read source yields 3-8 evidence units with durable provenance
- the claim-verifier gains richer structured inputs without verifier-side changes

**Status: Complete.** Implementation notes:

- Readers write `evidence/src-NNN.json` to disk (not in the return manifest) to avoid token bloat in the orchestrator's context. The return manifest includes an `evidence_count` field for routing.
- The orchestrator batch-ingests all evidence manifests via `state add-evidence-batch` after all readers complete (step 8b in SKILL.md), before the source quality report.
- The schema is documented inline in `agents/research-reader.md` rather than a separate reference file — Haiku readers have no way to read an external schema without an extra tool call.
- Gap-mode dedup: the orchestrator checks `state evidence --source-id` before ingesting to prevent duplicates from re-read sources.
- Sessions without evidence files are fully backward compatible — the ingestion step is skipped.

### Step 3: Wire evidence into findings, synthesis, and verification

Do findings, synthesis, and verifier integration in one pass. The two-phase verifier (claim-extractor + claim-verifier) makes this lighter than a monolithic verifier — evidence units map naturally to the extractor's claim schema and the verifier's provenance needs.

Success condition:

- findings link to explicit evidence IDs
- the writer uses evidence-linked findings as the canonical support layer
- claim-extractor maps from evidence units instead of re-parsing the report
- claim-verifier checks against evidence unit provenance instead of raw notes

### Step 4: Measure and tighten

Add metrics and audit checks.

Success condition:

- evidence coverage is measurable per question and per finding
- handoff size is bounded

## Why This Fits The Repo

This is a capability, not a factory.

The design does not hard-code synthesis or replace agent reasoning. It improves the substrate the agents reason over:

- readers still decide what matters
- findings loggers still decide how to cluster
- writers still decide how to synthesize
- verifiers still decide what is load-bearing

The system becomes more inspectable and less lossy without swallowing the agent.

## Risks And Mitigations

### Risk: readers produce low-value units

Mitigation:

- keep the schema small
- cap units per source
- prompt for load-bearing claims only

### Risk: provenance spans are unreliable

Mitigation:

- allow partial provenance in v1
- prefer exact spans for numbers and contradictions
- keep quotes short and optional

### Risk: handoff JSON gets too large

Mitigation:

- include only evidence linked to active findings or open gaps in `summary --write-handoff`
- keep quote fields truncated

### Risk: schema complexity outruns value

Mitigation:

- use JSON blobs for optional numeric structure
- do not normalize every possible metric in v1
- keep current notes and findings intact until the evidence layer proves useful

## Success Metrics

Recommended metrics to add in `skills/reflect/scripts/metrics.py`:

- `evidence_units_total`
- `evidence_units_by_question`
- `evidence_units_by_type`
- `evidence_units_with_spans`
- `findings_without_evidence_links`

Recommended operational goals:

- most report claims map to at least one evidence unit
- verifier throughput increases for load-bearing claims
- unsupported finding rates drop
- question coverage can be measured by evidence counts, not only finding counts

## Future Extensions

Not required for the initial rollout, but compatible with this design:

- persisted verifier claim checks
- contradiction clustering across sources
- report appendix with evidence trails
- export of evidence-backed bibliographic packets for external review

## Recommended First Implementation Slice

The best first slice is:

1. `state.py` schema and commands
2. `research-reader.md` evidence manifest output

Reader extraction is prioritized because the two-phase verifier architecture (claim-extractor + claim-verifier) makes evidence units at reading time immediately useful — the claim-verifier gains richer inputs without any verifier-side changes. That is the smallest version that proves the idea.
