# Cumulative Research Vision

## Summary

This document describes a long-term direction for `foundry-research`: making research cumulative across sessions without turning the system back into a monolithic factory.

The core idea is simple:

- a session remains the unit of active work
- a global corpus becomes the unit of accumulated knowledge
- reuse is explicit, inspectable, and reversible

The goal is not to have the agent “remember everything.” The goal is to let one good session make the next related session faster, cheaper, and more reliable.

## Why This Matters

Today, the system is strong within a session:

- it searches broadly
- downloads and validates sources
- extracts notes and evidence
- synthesizes a report
- evaluates quality afterward

But each session largely starts from zero.

That creates three costs.

### 1. Repeated source acquisition

Adjacent topics often rediscover the same papers, same benchmarks, same review articles, and same web sources.

Examples:

- one session on LLM confidence
- another on LLM confidence scoring
- another on calibration in frontier models

These are not separate universes. They are overlapping literatures.

### 2. Repeated deep reading

When a source has already been:

- downloaded
- converted
- summarized
- mapped to questions
- broken into evidence units

it is wasteful to deep-read it again from scratch unless freshness or scope demands it.

### 3. Repeated verification and rediscovery

Some hard-earned session outputs are exactly the things future sessions need:

- source quality judgments
- mismatch detections
- evidence units
- claim checks
- known literature gaps
- “this query pattern works in this domain”

Right now, these mostly remain trapped inside the session that produced them.

## Vision

Build a cumulative research layer that lets sessions publish durable artifacts into a shared corpus and lets future sessions selectively reuse them.

The important constraint is that this should remain a **capability**, not a hidden pipeline.

The agent should still decide:

- whether to reuse a source
- whether an old note is good enough
- whether a previous claim check is still relevant
- whether a prior session’s framing is applicable

The system should provide better inputs to that judgment, not make the judgment disappear.

## Design Principles

### 1. Session-first, corpus-second

The current session remains the active workspace and source of truth for the deliverable.

The cumulative layer is an overlay:

- sessions import from it
- sessions publish to it
- sessions never silently depend on it

### 2. Explicit reuse, never magic reuse

If a session reuses prior work, that should be visible:

- which prior artifact was reused
- from which session it came
- whether it was reused as-is or refreshed

Hidden memory is convenient but dangerous. Inspectable reuse is slower to design but far safer.

### 3. Reuse artifacts, not conclusions

The system should accumulate:

- sources
- metadata
- notes
- evidence units
- claim checks
- mismatch flags

It should not accumulate final conclusions as if they were evergreen facts.

Conclusions are too context-dependent:

- the question changes
- the scope changes
- recency requirements change
- applicability constraints change

The cumulative layer should preserve substrate, not freeze judgment.

### 4. Canonical identity first

Cumulative reuse only works if the same source can be recognized across sessions.

That means the system needs stable canonical identity for:

- DOI
- normalized URL
- source fingerprint or content hash
- source title/author/year fallback matching

Without this, cumulative mode degenerates into duplicate storage with a nicer name.

### 5. Freshness is part of provenance

A reused source is not automatically current.

The cumulative layer should track:

- when a source was last fetched
- when metadata was last enriched
- when a note was written
- when evidence was extracted
- when a claim check was performed

Reuse is strongest for stable literature and weakest for fast-moving topics.

## What Should Become Cumulative

### Canonical sources

One durable registry of sources across sessions.

Each canonical source should have:

- stable global ID
- canonical DOI or URL
- normalized metadata
- known alternate provider records
- content fingerprints
- quality history

### Reusable artifacts

Per-source artifacts that can be imported into a new session:

- markdown content
- PDF
- metadata
- reader notes
- evidence manifests
- source quality judgments

### Reusable verification artifacts

Per-claim or per-source verification records:

- claim text checked
- supporting or contradicting evidence IDs
- verdict
- timestamp
- scope assumptions

These should be reusable only with clear provenance and freshness checks.

### Session-to-session signals

The system should also accumulate process knowledge:

- which providers performed well in a domain
- which query formulations yielded useful results
- which papers were known dead ends
- which gaps looked genuine rather than search failures

This is weaker than source-level truth, but still useful as guidance.

## What Should Not Become Cumulative

- hidden agent chain-of-thought
- final report prose as reusable truth
- automatic query expansion from old sessions without visibility
- stale web claims reused as if they were academic facts
- silent citation carryover

These are exactly the kinds of shortcuts that make systems feel smart while actually weakening trust.

## User Experience

The cumulative layer should feel like explicit import and publish operations, not ambient memory.

### Starting a new session

The agent should be able to ask:

- have we seen this literature before?
- are there canonical sources already available?
- are there reusable notes or evidence packets relevant to this topic?

Then it should decide how to proceed:

- import directly
- refresh selected sources
- ignore prior material and start clean

### During acquisition

Search should be able to surface:

- known canonical sources not yet materialized in the current session
- prior mismatch warnings for a source or provider route
- previously successful recovery paths

### During reading

If a source already has:

- a good note
- durable evidence units
- recent provenance

the agent should be able to:

- reuse the note
- request a targeted refresh
- read only sections likely to have changed

### During synthesis

The writer should know whether a finding is backed by:

- current-session evidence
- imported evidence from an older session
- refreshed evidence after import

That distinction matters for transparency.

## Architecture Direction

### Current model

Today the model is roughly:

```text
session/
  state.db
  sources/
  notes/
  evidence/
  report.md
```

### Cumulative model

The likely direction is:

```text
global-corpus/
  sources/
  metadata/
  notes/
  evidence/
  verification/
  corpus.db

session/
  state.db
  sources/
  notes/
  evidence/
  report.md
  imports.json
```

The session remains self-contained for deliverability.

The corpus becomes the durable backing store for reusable artifacts.

### Key distinction

The session should not become a thin pointer-only view into the corpus.

Why:

- sessions need durable local provenance
- sessions need reproducibility
- sessions should survive corpus evolution
- edits in one session should not silently mutate another session’s truth base

That implies import or materialization, not pure referencing.

## Data Model Concepts

These are conceptual, not final schema commitments.

### `canonical_sources`

One row per globally recognized source.

Suggested fields:

- `global_source_id`
- `doi`
- `canonical_url`
- `title`
- `authors`
- `year`
- `venue`
- `content_hash`
- `latest_quality`
- `first_seen_at`
- `last_seen_at`

### `source_artifacts`

One row per durable artifact for a canonical source.

Suggested fields:

- `artifact_id`
- `global_source_id`
- `artifact_type` (`metadata`, `content`, `note`, `evidence`, `verification`)
- `path`
- `produced_by_session`
- `produced_at`
- `freshness_class`
- `status`

### `session_imports`

Records what a session reused and how.

Suggested fields:

- `session_id`
- `global_source_id`
- `artifact_id`
- `import_mode` (`copied`, `linked`, `refreshed`)
- `imported_at`
- `reason`

### `persisted_claim_checks`

Durable verifier outputs that future sessions can inspect.

Suggested fields:

- `claim_check_id`
- `global_source_id`
- `claim_text`
- `evidence_ids`
- `verdict`
- `checked_at`
- `checked_in_session`
- `scope_note`

## Capability Surface

The cumulative vision likely needs a small set of explicit tools.

Possible commands:

- `state publish-session-artifacts`
- `state corpus-search`
- `state corpus-source --doi ...`
- `state import-source --global-id ...`
- `state import-note --global-id ...`
- `state import-evidence --global-id ...`
- `state refresh-imports`
- `state claim-checks --global-id ...`

The interface should stay small. If this requires a long operational manual, the design has already drifted in the wrong direction.

## Integration With Existing Work

This vision builds naturally on the current structured evidence direction.

The existing evidence layer already proves several important things:

- claims can be preserved as durable objects
- provenance can survive beyond reader notes
- findings can link to evidence explicitly
- downstream agents benefit from structured carry-forward

Cumulative research is the cross-session extension of that same idea.

First the system learned to preserve structure **within** a session.
Next it should learn to preserve the right structure **across** sessions.

## Risks

### Risk: hidden factory behavior

If the cumulative layer silently decides what to reuse, the system stops feeling agentic and starts feeling opaque.

Mitigation:

- require explicit import decisions
- record all reuse in session artifacts
- keep current-session provenance visible

### Risk: stale knowledge pollution

A reused note or claim check may be outdated.

Mitigation:

- track freshness
- force refresh for recency-sensitive domains
- distinguish imported vs refreshed artifacts

### Risk: corpus bloat

If every artifact is stored forever with no canonicalization, the corpus becomes noisy and expensive.

Mitigation:

- canonical source identity
- artifact deduplication by content hash
- lifecycle rules for superseded artifacts

### Risk: conclusion reuse masquerading as evidence reuse

This is the most dangerous failure mode.

Mitigation:

- reuse sources, notes, evidence, and claim checks
- never treat prior report prose as authoritative substrate

## Implementation Slices

### Slice 1: Canonical source registry

Goal:

- dedupe sources across sessions by DOI, URL, and content identity

Value:

- immediate reduction in repeated downloads and repeated metadata enrichment

### Slice 2: Reusable source artifacts

Goal:

- allow a new session to import existing content, notes, and evidence for canonical sources

Value:

- immediate reduction in repeated deep reading

### Slice 3: Reuse-aware acquisition and reading

Goal:

- allow the orchestrator to see prior reusable material before dispatching readers

Value:

- better resource allocation inside the session

### Slice 4: Persisted claim checks

Goal:

- make verification results durable and inspectable across sessions

Value:

- future sessions inherit not just sources, but prior factual validation work

### Slice 5: Corpus-guided strategy

Goal:

- let the agent see which provider/query patterns worked in adjacent sessions

Value:

- improved search efficiency without hard-coding topic-specific strategies

## Success Criteria

The cumulative layer is successful if:

- related sessions import prior artifacts instead of rediscovering them
- repeated deep-reading rates drop for overlapping topics
- source quality improves because known mismatches are not retried blindly
- verification gets cheaper for recurring claims and benchmark facts
- users can always see what was reused and why

It fails if:

- sessions become hard to reproduce
- provenance gets blurrier instead of sharper
- reuse becomes invisible
- the corpus stores old conclusions as if they were still ground truth

## Recommendation

If this direction is pursued, the first step should not be “global memory” in the abstract.

It should be a very concrete capability:

- canonical source registry
- explicit import of prior source artifacts
- visible reuse metadata inside the session

That is the narrowest version that proves value without violating the project’s design principles.
