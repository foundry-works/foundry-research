# Deep Research — Reference

Reference material for the deep research pipeline. The orchestrator's core workflow is in `SKILL.md`. This file contains provider guidance, session structure, adaptive guardrails, and output format — material that subagents and the orchestrator can consult as needed but that doesn't need to be in the hot path during research.

---

## Provider Selection Guidance

Provider selection is handled by the `source-acquisition` agent (see `agents/source-acquisition.md`), but you should understand the landscape to validate the agent's manifest and direct gap-mode searches:

- **Biomedical/clinical:** PubMed + bioRxiv + Semantic Scholar
- **CS/ML/AI:** arXiv + Semantic Scholar + OpenAlex
- **Psychology/cognitive science:** PubMed + Semantic Scholar + OpenAlex + OSF/PsyArXiv (preprints). Note: PubMed's MeSH vocabulary skews biomedical — for cognitive science topics (judgment, decision-making, metacognition), OpenAlex and Semantic Scholar with targeted journal-name queries are often more productive
- **Humanities/social science:** Crossref + OpenAlex + Semantic Scholar
- **Financial:** yfinance + EDGAR + academic providers for context
- **General technical:** tavily + GitHub; Reddit/HN for community perspective
- **When unsure:** at least 3 providers including one web source

---

## Session Structure

```
./deep-research-{session}/
├── state.db              # SQLite — search history + source index (source of truth)
├── journal.md            # Your reasoning scratchpad (append-only)
├── evidence-policy.yaml  # Optional run-local support calibration
├── report-grounding.json # Declared paragraph-level report provenance
├── report.md             # Final report
├── evidence/             # Per-source evidence manifests (from reader subagents)
│   └── src-001.json
├── notes/                # Per-source summaries (from reader subagents)
│   └── src-001.md
└── sources/
    ├── metadata/         # JSON metadata files
    │   └── src-001.json
    ├── src-001.md        # Pure markdown content
    ├── src-001.pdf       # PDF when available
    └── src-001.toc       # Table of contents with line numbers
```

- Initialize: `${CLAUDE_SKILL_DIR}/state init --query "..."`
- Sources and searches are auto-tracked by `${CLAUDE_SKILL_DIR}/search` (no manual step needed)
- Check duplicates: `${CLAUDE_SKILL_DIR}/state check-dup-batch --from-json` (batch)
- Review progress: `${CLAUDE_SKILL_DIR}/state summary`
- Pre-report check: `${CLAUDE_SKILL_DIR}/state audit`

### Evidence Units

Reader agents produce structured evidence manifests (`evidence/src-NNN.json`) alongside markdown notes. Each manifest contains 3-8 load-bearing claim records with source provenance, claim type, and optional quantitative fields. The orchestrator batch-ingests them via `state add-evidence-batch` after all readers complete. Query with `state evidence` (filter by `--source-id`, `--question-id`, `--claim-type`) and aggregate with `state evidence-summary`.

### Source Quality And Caution

`sources.quality` is reserved for access and extraction condition:

- `ok`
- `inaccessible`
- `abstract_only`
- `degraded_extraction`
- `metadata_incomplete`
- `title_content_mismatch`

Legacy sessions may still contain `degraded`, `mismatched`, `empty`, `paywall_stub`, `paywall_page`, or `reader_validated`; `state source-quality-summary` maps those to canonical access/extraction categories without rewriting old state.

Use source caution flags for source authority or context-specific warnings:

- `secondary_source`
- `self_interested_source`
- `undated`
- `potentially_stale`
- `low_relevance`

Set them with `state set-source-flag --source-id src-NNN --flag potentially_stale --applies-to finding --applies-to-id finding-1 --rationale "..."`. List and aggregate them with `state source-flags`, `state source-flag-summary`, and `state source-quality-summary`.

### Optional Evidence Policy

When useful, write a short `evidence-policy.yaml` in the session root. It is advisory calibration for the agents, not required state and not a delivery gate. The v1 fields are:

```yaml
source_expectations: "Prefer primary sources for quantitative, legal, scientific, and current claims."
freshness_requirement: "High for current prices, products, regulations, and fast-changing software capabilities."
inference_tolerance: "low"
high_stakes_claim_patterns:
  - "quantitative claims"
  - "legal or regulatory claims"
known_failure_modes:
  - "treating stale sources as current"
  - "using secondary summaries as primary evidence"
```

Use `state support-context` to format this policy for prompts. If the file is absent, the command still returns valid JSON with `evidence_policy.present: false`.

### Report Grounding Manifest

`report-grounding.json` is a file manifest written beside `draft.md`/`report.md`. It is declared provenance from the writer, not verified support. Deterministic tools may validate structure, hashes, citation locations, and referenced IDs, but an agent still judges semantic support.

V1 schema:

```json
{
  "schema_version": "report-grounding-v1",
  "report_path": "deep-research-topic/draft.md",
  "targets": [
    {
      "target_id": "rp-001",
      "section": "Executive Summary",
      "paragraph": 1,
      "text_hash": "sha256:...",
      "text_snippet": "Paragraph text snippet...",
      "citation_refs": ["[1]", "[3]"],
      "source_ids": ["src-001"],
      "finding_ids": ["finding-1"],
      "evidence_ids": ["ev-0001"],
      "warnings": [],
      "grounding_status": "declared_grounded",
      "not_grounded_reason": null,
      "support_note": "Optional writer-authored note."
    }
  ]
}
```

Required target fields: `target_id`, `section`, `paragraph`, `text_hash`, `text_snippet`, `citation_refs`, `source_ids`, `finding_ids`, `evidence_ids`, and `warnings`.

Optional advisory fields: `grounding_status`, `not_grounded_reason`, `support_note`, `support_level`, and `claim_type`.

Use `state report-paragraphs --report <path>` to get paragraph locators and hashes. Hashes are `sha256:` over paragraph text after collapsing whitespace and trimming ends. Use `state validate-report-grounding` to surface missing manifests, stale hashes, citation-ref mismatches, missing source/finding/evidence IDs, and ungrounded body paragraphs.

### Report Support Audit

`state audit-report-support` writes `revision/report-support-audit.json`. The audit is deterministic: it aggregates declared grounding and existing state, but does not infer semantic support from report prose.

The audit includes:

- Report paragraphs with and without declared grounding entries
- Findings with and without linked evidence units
- Report targets with declared evidence links or only finding-level links
- Targets depending on degraded, abstract-only, stale, secondary, or self-interested sources
- Optional citation-audit results when `revision/citation-audit.json` exists
- Optional unresolved review issues from `revision/*-issues.json`
- Section-level weak-support density from writer or reviewer classifications

The output keeps writer-declared grounding separate from agent-authored support judgments.

### Citation Audit Manifest

Use `state citation-audit-contexts` to write `revision/citation-audit-contexts.json` from `report-grounding.json`. This file enumerates local citation contexts for agent review; it is not itself a support judgment.

After checking citations, agents write `revision/citation-audit.json`:

```json
{
  "schema_version": "citation-audit-v1",
  "status": "audited",
  "checks": [
    {
      "check_id": "cite-001",
      "target_type": "citation",
      "target_id": "rp-001:[4]",
      "report_target_id": "rp-001",
      "local_target": "paragraph",
      "section": "Executive Summary",
      "paragraph": 2,
      "text_hash": "sha256:...",
      "text_snippet": "Local paragraph snippet...",
      "citation_ref": "[4]",
      "cited_source_ids": ["src-004"],
      "support_classification": "weak_support",
      "rationale": "Why the cited source does or does not support the local target.",
      "recommended_action": "weaken_wording"
    }
  ]
}
```

Allowed `support_classification` values: `supported`, `weak_support`, `topically_related_only`, `overstated`, `missing_specific_fact`, `needs_additional_source`, and `unresolved`.

Allowed `recommended_action` values: `keep`, `weaken_wording`, `split_claim`, `add_source`, `replace_source`, and `mark_unresolved`.

### Review Issue Manifest

Reviewer, verifier, citation, and style issues are stored under `revision/*-issues.json` using `schema_version: "review-issues-v1"` before revision. The revision manifest records later status transitions and resolutions.

Compact issue fields:

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

Allowed `target_type` values: `source`, `evidence_unit`, `finding`, `report_target`, and `citation`.

Allowed `status` values: `open`, `resolved`, `partially_resolved`, `accepted_as_limitation`, and `rejected_with_rationale`. `partially_resolved` remains open for delivery purposes.

Contradiction candidates are review issues with extra fields: `conflicting_target_ids`, `contradiction_type`, and `final_report_handling`. Allowed contradiction types: `direct_conflict`, `scope_difference`, `temporal_difference`, `method_difference`, `apparent_uncertainty`, and `source_quality_conflict`.

Use `state review-issues` to list normalized issues and apply `revision/revision-manifest.json` status overrides:

```bash
state review-issues \
  --session-dir deep-research-topic \
  --report deep-research-topic/report.md \
  --grounding-manifest deep-research-topic/report-grounding.json \
  --status open
```

For `report_target` issues, the command reconnects issues to the current report by target ID first, then text hash, then snippet. This lets open issue lists survive localized report edits without creating a full artifact graph.

### Support Artifact Ingestion

The file artifacts remain the source of truth for report grounding, citation audits, and review issues. After those artifacts have proven useful in file form, you can optionally mirror them into small queryable state tables to produce compact handoffs and reflection metrics:

```bash
state ingest-support-artifacts \
  --session-dir deep-research-topic \
  --grounding-manifest deep-research-topic/report-grounding.json \
  --report deep-research-topic/report.md
```

The batch command mirrors available artifacts into:

- `report_targets`
- `report_target_evidence`
- `report_target_findings`
- `citation_audits`
- `review_issues`

Focused commands are available for debugging or partial refreshes: `ingest-report-grounding`, `ingest-citation-audit`, and `ingest-review-issues`. These commands should not be treated as a required delivery gate; rerun them only when the file artifacts change or when a queryable handoff is useful.

Use `state support-handoff` for a compact, agent-readable summary of grounded report targets, weak citation checks, open review issues, and reflection metrics. Use `state reflection-metrics` for just the metric dictionary.

Key reflection metrics:

- `report_targets_total`
- `report_targets_with_declared_finding_links`
- `report_targets_with_declared_evidence_links`
- `report_targets_without_grounding`
- `quantitative_or_fragile_targets_without_structured_evidence`
- `report_targets_depending_on_flagged_sources`
- `citations_audited`
- `citations_weakened_or_rejected`
- `reviewer_issues_with_target_ids`
- `reviewer_issues_resolved_before_delivery`
- `unresolved_issues_before_delivery`

These metrics are audit surfaces. They make repeated review and revision cheaper, but they do not replace agent judgment about whether a report is good enough to deliver.

### Delivery Audit

Use `state delivery-audit` before final delivery to collect the success metrics and validation checklist in one non-gating artifact:

```bash
state delivery-audit \
  --session-dir deep-research-topic \
  --ingest \
  --grounding-manifest deep-research-topic/report-grounding.json \
  --report deep-research-topic/report.md
```

The command reports:

- `success_metrics` using the names from `plan-checklist.md`
- `validation_checklist` entries marked `agent_judgment_required`
- open review issues
- unresolved contradictions or limitations that were accepted/disclosed or still need review

`delivery-audit` deliberately does not emit a pass/fail score. Use it to decide whether to revise, disclose limitations, or deliver.

### Revision Grounding Refresh

`state validate-edits` validates reviser snippets and reports grounded targets that need refresh:

```bash
state validate-edits \
  --manifest deep-research-topic/revision/revision-manifest.json \
  --report deep-research-topic/report.md \
  --grounding-manifest deep-research-topic/report-grounding.json \
  --pass accuracy
```

When revision manifest entries preserve `report_target_id` or target snippets, the response includes `grounding_refresh.targets_needing_refresh`. Treat those targets as stale declared provenance until `report-grounding.json` is regenerated for the edited passages.

---

## Adaptive Guardrails

Defaults with rationale — scale based on query complexity:

| Parameter | Default | Scale down | Scale up |
|-----------|---------|------------|----------|
| Research questions | 3-7 | Simple factual → 1-2 | Broad review → up to 10 |
| Searches per question | 1-3 | Comprehensive initial results → 1 | Niche topic → 3+ |
| Total sources | 15-40 | Simple query → 5-10 | Systematic review → 50+ |
| Sources cited | 10-25 | Scale with report length | |

Don't over-research simple questions. Don't under-research complex ones.

---

## Output Format

```markdown
# [Research Topic]

## Key Findings
- Finding 1 [1][2]
- Finding 2 [3]
- ...

## [Topic-appropriate sections]
### [Sections based on research questions]
...

## Methodology
- Sources deeply read: N (with notes in notes/)
- Abstract-only sources: M
- Web sources: K
- Providers used: [list]
- Session directory: [path]

## References (Sources Read)
[1] Author, "Title," Venue, Year. [URL/DOI] [academic]
[2] Author, "Title," Venue, Year. [URL/DOI] [preprint]
...

## Further Reading
- Author, "Title," Venue, Year. [URL/DOI] — cited for abstract/metadata only
- ...
```

Source type tags in references: `[academic]`, `[web]`, `[preprint]`, `[github]`, `[reddit]`, `[hn]`.

---

## PDF Download Cascade and Grey Sources

The download cascade tries sources in order: OpenAlex → Unpaywall → arXiv → PMC → OSF → Anna's Archive → Sci-Hub. The first five are legitimate open-access channels. The last two are shadow libraries:

- **Anna's Archive** aggregates content from multiple shadow libraries and provides both a free (scraped) download path and a faster API-backed path (requires `annas_secret_key`).
- **Sci-Hub** provides access to paywalled papers without publisher authorization.

Both are enabled by default. To disable them, set `DEEP_RESEARCH_DISABLED_SOURCES="annas_archive,scihub"` as an environment variable, or add `"disabled_sources": ["annas_archive", "scihub"]` to your config. When disabled, the cascade skips them and relies on the five open-access sources plus web-search-based paywall recovery.

---

## Paywall Recovery Beyond the Cascade

The download cascade (OpenAlex → Unpaywall → arXiv → PMC → OSF → Anna's Archive → Sci-Hub) handles the common paths automatically. When it still fails — especially in paywall-heavy fields like psychology, education, or medicine — the underlying principle is that **authors often self-archive their work** outside of publisher paywalls:

- **Institutional repositories** — many universities require faculty to deposit preprints or postprints. A web search for `"{author surname}" "{short title}" filetype:pdf` often surfaces these.
- **Author pages** — ResearchGate, Academia.edu, and personal faculty pages frequently host author-uploaded copies.
- **Discipline-specific preprint servers** — the cascade already checks OSF/PsyArXiv and arXiv, but emerging servers (e.g., EdArXiv, SocArXiv, EarthArXiv) may have coverage the cascade doesn't yet include.

When using web search (Exa/tavily) for recovery, the most effective pattern is `"{exact title}" filetype:pdf` — this finds direct PDF links that the DOI-based cascade missed. Fall back to `"{author surname}" "{short title}"` if the exact title returns nothing.

**Citation rules:**
- Only sources with on-disk `.md` content AND reader notes in `notes/` go in **References (Sources Read)**
- Sources known only from abstracts or search metadata go in **Further Reading**
- The Methodology section must honestly report deep reads vs. abstract-only counts (use `${CLAUDE_SKILL_DIR}/state audit` output)
- Never claim to have "deeply read" a source that has `degraded` (unread) or abstract-only content. Current sessions use `mark-read` to set `is_read`; claim deep reads only when the source has readable on-disk content and a reader note. Legacy `quality: "reader_validated"` values are compatibility input, not a quality value to write in new sessions.
