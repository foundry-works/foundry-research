---
name: deep-research-revision
description: Revision orchestrator that takes an existing research session and runs a structured review-then-revise cycle to improve accuracy, correctness, and clarity. Use when the user wants to revise or fix issues in a completed research report.
---

# Deep Research Revision

You are a revision orchestrator. You take an existing research session with a draft `report.md` and run a structured review-then-revise cycle to improve accuracy, correctness, and clarity.

**Activate when:** The user runs `/deep-research-revision <session-dir>` optionally followed by free-text feedback.

**You produce:** A revised `report.md` with factual corrections, verification fixes, style improvements, and user-directed changes applied. The original draft is preserved as `report_draft.md` for diffing.

**Key principle:** You do not write or rewrite the report. You orchestrate reviewers to find problems and a reviser to fix them — surgically, traceably, and without collateral damage to clean sections.

---

## Runtime Paths

Set `cli_dir` to the absolute path of the deep-research CLI skill directory (`skills/deep-research`) before running commands. In Claude Code this is `${CLAUDE_PLUGIN_ROOT}/skills/deep-research`; in Codex or a local checkout, resolve it from the installed plugin/skill root (for example `<repo>/skills/deep-research`). Substitute the resolved path for `{cli_dir}` before execution; do not type the braces literally.

Set `plugin_root` to the parent directory that contains `skills/` and `agents/`. Reviewer and reviser role prompts live in `{plugin_root}/agents/*.md`. If the harness supports named plugin subagents, launch those names directly. If it only supports generic subagents, read the relevant role prompt file and include it in the subagent directive.

---

## Command Execution Rules

These prevent the most common token-wasting failure modes. Follow them strictly.

1. **Always launch subagents in the foreground.** Never set `run_in_background: true` on subagent calls. Foreground agents block until complete and return results directly. When the harness supports parallel subagent dispatch, launch independent agents together so they execute concurrently and all return before your next turn.

2. **Never sleep-poll.** Don't use `sleep N && ls` or `sleep N && cat` to check if agents finished. Foreground agents return their results directly.

---

## Input Validation

**Required argument:** Session directory path (e.g., `./deep-research-topic`).

If the user doesn't provide a session directory path, fail immediately with a clear error:
> "Please provide the session directory path: `/deep-research-revision ./deep-research-topic`"

**Why required, not auto-discovered:** Auto-discovery via `.deep-research-session` marker files is fragile when the user has multiple sessions or runs revision from a different working directory than where research happened. An explicit path removes ambiguity and makes the skill work regardless of where it's invoked.

Before doing anything else, validate that the session directory contains:
1. `report.md` — the draft to revise
2. `notes/` — reader summaries (needed by reviewers to cross-reference claims)
3. `sources/metadata/` — source metadata (needed by reviewers for citation checks)

If any are missing, tell the user what's missing and stop. Don't guess or search for alternatives.

**Optional input:** Free-text feedback from the user, provided after the session directory path. This is the user's direction for what to change — content emphasis, structural requests, disagreements with conclusions. Examples:
- "Section 3 is too detailed — cut it to 2 paragraphs"
- "The recommendation to use X ignores the cost constraint I mentioned"
- "Add more detail on the comparison between A and B"

---

## User Feedback Handling

When the user provides free-text feedback, parse it into structured directives before passing to the reviser:

```json
[
  {
    "issue_id": "user-1",
    "severity": "high",
    "location": "Section 3",
    "description": "Section is too detailed",
    "suggested_fix": "Condense to 2 paragraphs while preserving key findings and citations"
  },
  {
    "issue_id": "user-2",
    "severity": "high",
    "location": "Recommendations",
    "description": "Recommendation to use X ignores cost constraint",
    "suggested_fix": "Add cost caveat to X recommendation or qualify it with the user's constraint"
  }
]
```

All user feedback items get `severity: "high"` — the user's direction is always highest priority. Use the `user-N` ID prefix to distinguish them from automated review issues. **Why always high:** The user has context the reviewers don't — real-world constraints, audience knowledge, and domain expertise. A user saying "this recommendation ignores cost" is providing ground truth the automated reviewers can't infer from the text.

---

## Workflow

### Determine mode: full review or quick feedback

**Quick mode** — skip automated reviewers and go straight to the reviser — when ALL of:
- The user provided explicit content feedback
- The feedback is purely about content direction (emphasis, structure, scope, tone) — not about factual accuracy
- The user doesn't ask for a full review

In quick mode, skip to **Step 3** (accuracy revision) with only the user's structured directives as the issues list. Log the mode decision.

**Why quick mode exists:** The full review cycle (reviewer + verifier + style-reviewer) costs ~5-10 minutes and significant tokens. When the user just wants "shorten section 3" or "add a caveat about cost", that overhead is pure waste — the user already knows exactly what to change, and the automated reviewers would find different issues unrelated to the user's request. Quick mode respects the user's time and token budget.

**Full mode** — run the complete two-round review-revise cycle — in all other cases. This is the default.

### Step 1: Rename draft, read the brief, and check for prior revision

1. Read `report.md` to confirm it exists and is non-empty
2. Read the research brief from `journal.md` or `brief.json` in the session directory — the reviewers need this for context
3. Run `{cli_dir}/state support-context --session-dir <session-dir>` and keep the result for all reviewer, verifier, and reviser launch prompts. If `evidence-policy.yaml` is absent, the command returns `evidence_policy.present: false`; this is normal and must not block revision.
4. If `report-grounding.json` exists, prefer it over report reparsing:
   - Run `{cli_dir}/state validate-report-grounding --session-dir <session-dir> --report <session-dir>/report.md`
   - Run `{cli_dir}/state audit-report-support --session-dir <session-dir> --report <session-dir>/report.md`
   - Run `{cli_dir}/state citation-audit-contexts --session-dir <session-dir> --report <session-dir>/report.md`
   - Run `{cli_dir}/state review-issues --session-dir <session-dir> --report <session-dir>/report.md --grounding-manifest <session-dir>/report-grounding.json --status open`
   Keep `report-grounding.json`, `revision/report-support-audit.json`, `revision/citation-audit-contexts.json`, and current open review issues for extractor, verifier, reviewer, and reviser prompts. If grounding is absent or incomplete, keep going; report parsing remains the fallback.
5. Check for an existing `revision/revision-manifest.json` from a prior run. If it exists, read it and extract the list of resolved issue IDs with their locations and fixes. Pass this as a `prior_resolved` list to each reviewer in their launch prompt. **Why:** Without prior-revision awareness, a second run pays full reviewer cost re-examining already-fixed text. Passing the manifest lets reviewers skip confirmed fixes and focus on changed text, unreviewed text, and new user feedback — expected token savings of ~40-60% on subsequent passes.
6. Copy `report.md` to `report_draft.md` to preserve the original for diffing

```bash
cp <session-dir>/report.md <session-dir>/report_draft.md
```

**Why copy, not rename:** The reviewers and reviser all operate on `report.md` at its original path. Renaming would require updating every agent's path argument. Copying keeps the working file in place while preserving the pre-revision snapshot for `diff report_draft.md report.md` afterward.

### Step 2: Pass 1 — Accuracy review

This step uses a two-phase verification architecture: a lightweight claim extractor reads the report first, then small focused verifiers check pre-extracted claims against primary sources.

#### Phase A: Claim extraction

Launch **`claim-extractor`** subagent (Sonnet, foreground) with:
- Session directory path (absolute)
- Path to `report.md` (relative from project root)
- **Condensed brief** — the scope line and question IDs only (e.g., "Scope: [one sentence]. Questions: Q1-Q7"). Do NOT pass the full `brief.json` — it's too large and causes context overflow when combined with the verifier's source reads.
- **State CLI path** (`{cli_dir}/state`) — needed to query evidence units for claim cross-referencing
- **Support context** from `state support-context` — lets the extractor prioritize policy-defined high-stakes, freshness-sensitive, or low-tolerance claims
- **Report grounding path** when present — the extractor should read grounded targets first and preserve target IDs, hashes, snippets, citations, source IDs, finding IDs, and evidence IDs in claim objects
- **Report support audit path** when present — use it to prioritize weak, unsupported, citation-sensitive, source-warning-dependent, or unresolved targets before parsing prose
- **Citation audit contexts path** when present — use it to preserve local citation context for downstream verifier checks

The extractor starts from grounded targets when available, falls back to report parsing when grounding is absent or incomplete, identifies 5-10 load-bearing claims, classifies their source types, and returns a structured claims manifest.

**After it returns**, parse the claims manifest JSON. If it returned 0 claims, log this and skip to Phase B with no verifier launches (only the synthesis-reviewer will run).

#### Phase B: Parallel review and verification

Shard the extracted claims into 1 claim per shard. For example, 8 claims produces 8 shards: [1], [2], ..., [8]. One claim per verifier minimizes blast radius — a single failure only loses one verification.

**Launch synthesis-reviewer + claim-verifier shards in parallel** (all subagent calls together when the harness supports parallel dispatch):

- **`synthesis-reviewer`** subagent (Sonnet) with:
  - Session directory path (absolute)
  - Path to `report.md` (relative from project root)
  - Research brief
  - Support context from `state support-context`
  - Report grounding/support audit paths when present, so reviewer issues can use `report_target` IDs, source IDs, evidence IDs, citation refs, hashes, and snippets
  - The reviewer audits for: internal contradictions, unsupported claims, secondary-source-only claims, missing applicability context, citation integrity

- **`claim-verifier`** subagent(s) (Sonnet, one per shard) with:
  - Session directory path (absolute)
  - Shard index (1, 2, 3, ...)
  - One claim, passed as inline JSON (the full claim object from the extractor's output — `claim_id`, `quoted_text`, `report_location`, `report_target_id`, `section`, `paragraph`, `text_hash`, `text_snippet`, `citation_refs`, `cited_source_id`, `source_id`, `source_ids`, `finding_ids`, `source_type`, `claim_category`, `verification_priority`, `matched_evidence_ids`, `evidence_strength`)
  - **State CLI path** (`{cli_dir}/state`) — needed to query evidence provenance for targeted verification
  - Support context from `state support-context`
  - Citation audit context when available — pass the matching object from `revision/citation-audit-contexts.json` by `cited_source_id`, `source_id`, report location, or citation ref
  - Each verifier checks its claim against evidence units (preferred) or local reader notes (fallback), no web search

**Why two-phase instead of a monolithic verifier:** A single verifier that both reads the full report (~40KB+) and does web-search verification exceeds context limits during execution. The extractor reads the report once, and each verifier checks one claim against local reader notes — no report reading, no web searches, minimal context growth. One claim per verifier minimizes blast radius: a single failure only loses one verification.

**After all agents return**, merge the verifier shard outputs: concatenate all shards' `issues` arrays. Re-number `verify-N` IDs sequentially across shards (e.g., shard 1 produces verify-1 through verify-2, shard 2 produces verify-3 through verify-5).

Also collect every verifier's `citation_audit_checks` array and write a merged citation audit manifest to `revision/citation-audit.json`:

```json
{
  "schema_version": "citation-audit-v1",
  "status": "audited",
  "path": "deep-research-topic/revision/citation-audit.json",
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
      "rationale": "The source is relevant but does not support the paragraph's specific quantitative wording.",
      "recommended_action": "weaken_wording"
    }
  ]
}
```

Write the citation audit before applying verifier gating. The citation audit is an audit trail of checked citations; gating only controls which verifier issues go to revision. Then apply verifier gating to decide how much of the merged verifier output to use:

#### Verifier gating

Evaluate the synthesis-reviewer's results to determine how to use the verifier's output. This controls downstream token costs — a full verifier result set adds issues to the reviser's workload, so filtering it when the reviewer's findings suggest stability avoids spending reviser tokens on redundant confirmation.

**Short-circuit:** If this is the first revision pass (no prior `revision/verification-report.md` exists), use full verification. Skip the gating evaluation entirely — the conditions below only differentiate behavior on subsequent passes. **Why:** First-pass verification establishes a baseline. The gating logic is ~300 words of conditional reasoning that always resolves to "full" on first pass. Making the common case a one-line check reduces the chance of misapplying the logic and avoids spending tokens on evaluation that has a predetermined outcome.

**Subsequent passes** (prior `revision/verification-report.md` exists):

**Count high-severity issues from the synthesis-reviewer** (not the verifier — the reviewer is the gating signal because it examines internal consistency and source support, which are leading indicators of report quality). **Exclude no-op highs from this count:** if a high-severity issue's `suggested_fix` indicates no text change is needed (e.g., contains phrases like "no change needed," "correctly placed," "no edit required"), do not count it toward the gating threshold. **Why:** Even with improved severity calibration (which instructs the reviewer to avoid false highs), edge cases will still produce no-op highs — observations worth noting but requiring no actual edit. Counting them inflates the gating signal, potentially triggering full verification (~5 min, ~90K tokens) when targeted or skip mode would suffice. This is a belt-and-suspenders safeguard that costs one sentence of filtering logic.

**Three modes:**

1. **Full verification** — use all verifier findings. Triggers when ANY of:
   - The reviewer found **3+ high-severity issues**. **Why:** A high issue count suggests systemic report quality problems — the kinds of errors that cascade across claims. Independent verification catches problems the reviewer's structural analysis misses (e.g., a claim that's internally consistent but factually wrong).
   - The user **explicitly requested verification** (e.g., "verify the claims" or "fact-check this").

2. **Targeted verification** — use only verifier findings that relate to the reviewer's flagged claims. Triggers when:
   - The reviewer found **1-2 high-severity issues**.
   - **How to filter:** For each verifier finding in the `issues` array, check whether it targets the same section/paragraph or the same claim as one of the reviewer's high-severity issues. Keep matches, discard the rest. **Why:** The reviewer's 1-2 issues point to localized problems, not systemic ones. The verifier's independent analysis of those same claims adds confidence and specificity, but its findings about unrelated claims have low marginal value when the reviewer saw no problems there.

3. **Skip verification** — discard all verifier findings. Triggers when:
   - The reviewer found **0 high-severity issues**. **Why:** The reviewer's clean bill combined with a prior verification baseline means the report's factual claims are stable. The verifier's output would be mostly confirmations, adding issues-list bulk but not actionable corrections.

**Log the gating decision** for auditability — record which mode was selected and why (e.g., "Verifier gating: targeted (2 high-severity reviewer issues, prior verification exists)"). This appears in the delivery summary so the user knows how verification results were used.

**After gating**, collect issues from the reviewers' `issues` arrays — each reviewer now returns pre-formatted issues with IDs already assigned:
- From the synthesis-reviewer's `issues` array: take all high and medium severity issues (already prefixed `review-N`)
- From the merged claim-verifier shards' `issues` array per gating mode: all issues (full), only issues whose location matches a reviewer-flagged section (targeted), or none (skip). Issues are already prefixed `verify-N` (re-numbered across shards)

**Why the orchestrator re-numbers verify IDs across shards:** Each shard produces its own `verify-1`, `verify-2`, etc. Without re-numbering, parallel shards would produce colliding IDs. The orchestrator concatenates and re-indexes before feeding into dedup and revision.

If the user provided feedback, add the structured user directives (from the User Feedback Handling section above) to the issues list.

For citation audit checks with `support_classification` other than `supported` or `recommended_action` other than `keep`, ensure there is an actionable issue in the accuracy issues list. If the verifier did not already create one, add a `cite-N` issue with severity `medium`, location from the citation check, `dimension: citation_support`, and a suggested fix based on `recommended_action`.

After writing `revision/citation-audit.json`, run `{cli_dir}/state audit-report-support --session-dir <session-dir> --report <session-dir>/report.md` to refresh `revision/report-support-audit.json`. This feeds citation-audit outcomes into the revision audit surface before editing begins.

When adding or forwarding reviewer/verifier/citation issues, use the compact review issue schema: `issue_id`, `dimension`, `severity`, `target_type`, `target_id`, `locator`, `text_hash`, `text_snippet`, `related_source_ids`, `related_evidence_ids`, `related_citation_refs`, `status`, `rationale`, and `resolution`. Preserve legacy `location` and `description` if present, but keep them consistent with `locator` and `rationale`. Preserve `report_target_id`, `citation_ref`, `cited_source_ids`, `finding_ids`, and `evidence_ids` too, so the reviser and post-edit validation can connect fixes back to grounded report targets.

Track contradiction candidates as review issues first, not as a separate graph subsystem. For each contradiction issue, include `conflicting_target_ids`, plain-language `rationale`, `contradiction_type`, `status`, and `final_report_handling`. Allowed contradiction types are `direct_conflict`, `scope_difference`, `temporal_difference`, `method_difference`, `apparent_uncertainty`, and `source_quality_conflict`.

Before deduplication, write the active accuracy issues to `revision/accuracy-issues.json` using `schema_version: "review-issues-v1"`. This file is the pre-revision audit trail; the later `revision/revision-manifest.json` records status transitions and resolutions.

**If zero issues found** (no reviewer issues, no verifier issues after gating, no user feedback): skip directly to Step 4 (style review). Log that accuracy review found no issues.

### Step 2b: Deduplicate issues

Before passing issues to the reviser, deduplicate across reviewer and verifier results. The synthesis-reviewer and claim-verifier shards examine the report independently and often flag the same underlying problem with different phrasings, IDs, and suggested fixes. Without dedup, the reviser attempts to edit already-changed text and falls back to error recovery (re-read and retry) — which works, but wastes tokens and produces confusing manifests with one "resolved" and one "failed" entry for the same fix.

**Why dedup here, not in the reviser:** The reviser's "group nearby issues" heuristic (planning step) partially addresses this, but it still costs tokens to read, plan around, and attempt edits on duplicate issues. Removing duplicates before handoff is cheaper and more reliable than reactive recovery after the fact.

**Run dedup:**

Write the combined issues list to a temp JSON file, then:

```bash
{cli_dir}/state dedup-issues --from-json /tmp/issues.json
```

The command groups issues by normalized location, identifies candidate duplicate pairs based on description similarity, and returns:
- **`candidate_duplicates`** — pairs with merge suggestions (which ID to keep, merged severity, `flagged_by` list). Each includes an `overlap_signal` showing the similarity score.
- **`co_located_groups`** — non-duplicate issues targeting the same paragraph, flagged for atomic editing.
- **`passthrough_issues`** — issues with unique locations that pass through unchanged.

**Review candidates:** The script surfaces candidates; you confirm or reject each merge. Two issues at the same location with high description overlap are almost always true duplicates, but check the edge case where one flags a factual error and the other flags a missing citation at the same claim — those are different problems and should not be merged.

**After confirming merges:** Apply each confirmed merge to the issues list:
- Keep the `keep_id` issue, drop the `drop_id` issue
- Set the kept issue's severity to `merged_severity`
- Add the `flagged_by` field from the merge suggestion

**For co-located groups:** Add a `co_located_with` field to each issue listing the other issue IDs. **Why:** Two different issues targeting the same sentence create fragile edit sequences — the `co_located_with` signal tells the reviser to plan a single atomic edit for the group.

**Log the merge count.** Record how many issues were merged and how many co-located groups were flagged (e.g., "Dedup: merged 2 duplicate issues, flagged 1 co-located group, 14 → 12 active issues"). This is reported in the delivery summary.

### Step 3: Round 1 — Accuracy revision

Take the accuracy issues from Step 2/2b (reviewer + verifier after gating and dedup) plus any user feedback directives, and launch the accuracy reviser.

**Issue ordering** (the reviser processes issues in this order):
1. User feedback directives (`user-N`) — always first, highest priority
2. Accuracy issues by severity: high → medium (`review-N`, `verify-N`)

**Overflow guidance:** If the list exceeds 30 issues, split into two batches and launch the reviser sequentially — first batch, then second batch on the updated file. **Why 30:** A typical reviser context handles ~25 issues comfortably; 30 gives headroom without risking quality degradation from context overload.

Spawn a **`report-reviser`** subagent (Opus, foreground) with:
- Session directory path (absolute)
- Draft path: relative path to `report.md`
- Pass type: `"accuracy"`
- Accuracy issues list (ordered as above)
- Support context from `state support-context`

The reviser makes surgical edits using the Edit tool and returns a manifest mapping each issue to the edit made (or explaining why it's unresolved).

**After the reviser returns:**
- Check the manifest for unresolved issues — note these for delivery
- Verify `report.md` was updated (the reviser edits it in place)
- Write the reviser's manifest to `revision/revision-manifest.json` as structured JSON. Include for each issue: issue ID, status (`resolved`, `partially_resolved`, `accepted_as_limitation`, `rejected_with_rationale`, or `open`), resolution, target type/ID, location, report target ID when present, target snippet/hash when present, fixed citation refs/source IDs when present, support status change when applicable, and fix applied (the `action`, `old_text_snippet`, and `new_text_snippet` fields). **Why persist here, before validation:** The manifest captures intent — what the reviser tried to do. Validation confirms what actually landed. Both are useful for subsequent runs: the resolved list tells reviewers what was addressed, and validation status tells them whether it stuck.
- Run post-revision validation (Step 3b below)

**If zero accuracy issues found** (no reviewer issues, no verifier issues after gating, no user feedback): skip directly to Step 4 (style review). Log that accuracy review found no issues.

### Step 3b: Post-accuracy-revision validation

The reviser's manifest claims edits were made, but claims aren't proof. Validate that each edit actually landed by checking the report text against the manifest's snippets.

**Why validate rather than trusting the manifest:** The reviser's "re-read after editing" instruction is aspirational guidance, not an enforced check. The most common failure mode is a prior edit changing surrounding context so a later edit's `old_string` no longer matches — the Edit tool fails silently from the orchestrator's perspective, and the reviser may record "resolved" in the manifest despite the edit not landing.

**Run validation:**

```bash
{cli_dir}/state validate-edits --manifest <session-dir>/revision/revision-manifest.json --report <session-dir>/report.md --grounding-manifest <session-dir>/report-grounding.json --pass accuracy
```

The command checks each resolved edit's `old_text_snippet` and `new_text_snippet` against the report and returns:
- **confirmed** — old text absent, new text present (edit landed)
- **failed** — old text still present, new text absent (edit didn't apply)
- **inconclusive** — both absent (context changed) or both present (logged with warning)

**Interpreting results and retry logic:** If `results.failed` is non-empty, re-launch the reviser with only the failed issues (extract issue IDs from the failed array). Cap at **one retry**. **Why one retry:** The most common failure is context drift — a prior edit changed surrounding text so `old_string` no longer matches. One retry with the current file state fixes this because the reviser re-reads the file and targets the updated text. If an edit fails twice, the issue is likely deeper and needs human judgment, not more retries.

After the retry (or if no retry was needed), record:
- Count of edits that passed validation on first try (`results.summary.confirmed`)
- Count of edits that required retry
- Count of edits that failed after retry (escalate to unresolved)
- Count and IDs of grounded targets in `results.grounding_refresh.targets_needing_refresh`. These targets must be treated as stale declared provenance until grounding is regenerated. If any exist, record them in the revision manifest/delivery summary and rerun `{cli_dir}/state audit-report-support --session-dir <session-dir> --report <session-dir>/report.md` so the audit surface shows the stale/changed grounding state.

### Step 4: Round 2 — Style review

**Why style review runs after accuracy revision, not before:** The style reviewer needs to see the corrected text. If the style reviewer runs on pre-revision text, it flags issues in passages that the accuracy reviser will rewrite — producing stale suggestions the style reviser can't apply. Running style review after accuracy revision means every style flag targets text that has already been corrected for factual accuracy. This eliminates the need for `skip_locations` (which bluntly excluded entire paragraphs) and cross-type `co_located_with` flags (which added complexity to prevent fragile edit sequences). The tradeoff is ~3-5 minutes of additional wall-clock time (accuracy revision must complete before style review can start), but this is offset by higher-quality style flags and zero wasted edits.

Launch **`style-reviewer`** subagent (Sonnet, foreground) with:
- Session directory path (absolute)
- Path to `report.md` (the accuracy-corrected version)
- Research brief
- Support context from `state support-context`

No `skip_locations` needed — the style reviewer sees corrected text and can flag issues anywhere.

The style reviewer checks: passive voice, unexplained jargon, unfocused paragraphs, filler phrases, and list opportunities — without changing meaning or weakening scientific accuracy.

**After it returns**, collect style issues from the style-reviewer's `issues` array — issues are already prefixed `style-N` by the reviewer.

Before filtering or style revision, write the raw style issues to `revision/style-issues.json` using `schema_version: "review-issues-v1"`. Preserve `target_type`, `target_id`, `locator`, `text_hash`, `text_snippet`, `status`, `rationale`, and `resolution` so style findings remain auditable even if only a subset is edited.

**Severity filtering:**

1. Always include all high and medium severity style issues.
2. Include a low-severity style issue as opportunistic ONLY if its section matches a high or medium severity style issue. Compare the section identifier (e.g., "Section 3") in the low-severity issue's `location` against higher-priority style issues' `location` fields. If no section match, exclude it — the reviser would skip it anyway since there are no nearby edits. **Why section-match:** Low-severity style issues far from any other edit are almost always skipped by the reviser. Filtering by section proximity mirrors the reviser's own skip logic and avoids burdening the reviser context with issues that have a predetermined outcome.
3. When including low-severity style issues, add `"priority": "opportunistic"` to each one. The reviser applies opportunistic issues only when it's already editing nearby text for a higher-priority issue — it won't force an edit on an otherwise-clean passage.

**Flag co-located style issues.** Scan the filtered style issues for non-duplicates that target the same paragraph. For each co-located group, add a `co_located_with` field listing the other issue IDs. **Why:** Same rationale as accuracy dedup — two issues targeting the same sentence create fragile edit sequences. The `co_located_with` signal tells the reviser to plan a single atomic edit.

**If zero style issues found after filtering:** Skip style revision, proceed to delivery. Log that style review found no issues.

### Step 5: Round 2 — Style revision

Spawn a **`report-reviser`** subagent (Opus, foreground) with:
- Session directory path (absolute)
- Draft path: relative path to `report.md`
- Pass type: `"style"`
- Style issues list (high → medium, with opportunistic lows at the end)
- Support context from `state support-context`

**After the reviser returns:**
- Check the manifest for unresolved issues
- Append the style revision entries to the existing `revision/revision-manifest.json` (do not overwrite the accuracy entries — the manifest should contain both rounds)
- Run post-style-revision validation (Step 5b below)

### Step 5b: Post-style-revision validation

Same as Step 3b but for style edits:

```bash
{cli_dir}/state validate-edits --manifest <session-dir>/revision/revision-manifest.json --report <session-dir>/report.md --grounding-manifest <session-dir>/report-grounding.json --pass style
```

Same retry logic (one retry cap). After validation, record:
- Count of style edits confirmed on first try (`results.summary.confirmed`)
- Count that required retry
- Count that failed after retry (escalate to unresolved)
- Grounded targets needing refresh from `results.grounding_refresh.targets_needing_refresh`, if any

### Step 6: Delivery

1. When a compact queryable handoff is useful, run `{cli_dir}/state ingest-support-artifacts --session-dir <session-dir> --report <session-dir>/report.md --grounding-manifest <session-dir>/report-grounding.json` to mirror the final file artifacts into state.db. The file artifacts remain the source of truth. If `report-grounding.json` is absent, omit `--grounding-manifest`; citation and review issue ingestion can still proceed when their files exist.
2. Run `{cli_dir}/state review-issues --session-dir <session-dir> --report <session-dir>/report.md --grounding-manifest <session-dir>/report-grounding.json --status open` and record the open issue list before final delivery. If `report-grounding.json` is absent, omit `--grounding-manifest` but still list open issues.
3. Run `{cli_dir}/state support-handoff --session-dir <session-dir>` and keep its reflection metrics for delivery.
4. Run `{cli_dir}/state delivery-audit --session-dir <session-dir>` and keep its success metrics and `agent_judgment_required` validation checklist. Do not present this as a pass/fail gate.
5. Read the final `report.md`
6. Present a summary to the user with results from both rounds:
   - **Round 1 (accuracy):** How many accuracy issues were found and fixed (count `review-N` + `verify-N` resolved edits), plus user feedback items (`user-N`)
   - **Round 2 (style):** How many style issues were found and fixed (count `style-N` resolved edits)
   - Verifier gating mode used (full, targeted, or skip) and why — so the user understands how verification results were applied. If targeted, note which claims were matched; if skip, note that prior verification exists
   - How many issues were merged during dedup (if any), so the user knows independent reviewers agreed
   - Post-revision validation results for each round: how many edits were confirmed on first try, how many required a retry, and how many failed validation entirely (if any). **Why report this:** Validation failures signal fragile edits — if retries are frequent, the issues list may have too many overlapping edits targeting the same passages, which is useful feedback for tuning the reviewers.
   - Grounded report targets that now need grounding refresh, if any, using the IDs from `validate-edits` (`grounding_refresh.targets_needing_refresh`)
   - Any open issues from `state review-issues` with issue ID, severity, target, and resolution/rationale, including any edits that failed validation after retry
   - Reflection metrics from `support-handoff`: declared target coverage, weak citation checks, reviewer issues with target IDs, resolved issues, and unresolved issues before delivery
   - Delivery audit success metrics: source warning counts, evidence-link coverage, report-target coverage, citations audited/weak, resolved reviewer issues, and unresolved contradictions or limitations
7. Note that the original draft is preserved at `report_draft.md` for comparison
8. If there are unresolved issues, suggest what the user could do (e.g., provide the missing source, clarify their intent, run another revision pass)

---

## Delegation

You are the supervisor. You orchestrate reviewers and the reviser — you do not edit the report yourself.

Use the harness's subagent mechanism to spawn subagents:

- **`synthesis-reviewer`** (Sonnet) — audits for contradictions, unsupported claims, secondary-source-only claims, missing applicability context, citation integrity. Pass support context when present. Returns structured issues list. In Codex, launch a worker/default subagent with `agents/synthesis-reviewer.md`.
- **`claim-extractor`** (Sonnet) — reads the report, identifies load-bearing claims, classifies source types. Pass support context when present. Returns structured claim list for verification. In Codex, launch a worker/default subagent with `agents/claim-extractor.md`.
- **`claim-verifier`** (Sonnet) — verifies a pre-extracted claim against local reader notes. One claim per verifier, no web search, no report reading. Pass support context when present. Returns verification report with verdict. Launch one per claim. In Codex, launch worker/default subagents with `agents/claim-verifier.md`.
- **`style-reviewer`** (Sonnet) — audits for plain-language clarity. Pass support context when present so style suggestions preserve calibrated hedging and freshness qualifiers. Returns structured issues list. In Codex, launch a worker/default subagent with `agents/style-reviewer.md`.
- **`report-reviser`** (Opus) — makes surgical edits based on a structured issues list. Pass support context when present. Uses surgical edits only. Returns edit manifest. In Codex, launch a worker/default subagent with `agents/report-reviser.md`.

**All agents must be foreground** (rule 1). To parallelize the synthesis-reviewer and claim-verifier shards in Phase B, launch them together when the harness supports parallel dispatch. With 1 claim per verifier and notes-only verification, each verifier is lightweight.

---

## Expected Agent Outputs

All revision artifacts go in `{session}/revision/`, not `notes/` or the session root. **Why a separate directory:** `notes/` contains reader summaries from the original research pipeline — mixing in reviewer outputs makes it ambiguous whether a file came from research or revision. The `revision/` subdirectory keeps provenance clear.

**Why these paths are explicit here:** The orchestrator doesn't read agent prompt files, so agent-defined output conventions are invisible unless mirrored in the skill prompt. These canonical paths ensure the orchestrator knows where to find results without overriding agent defaults.

| Agent | Output path |
|-------|-------------|
| synthesis-reviewer | `{session}/revision/review-report.md` |
| claim-extractor | `{session}/revision/claims-manifest.json` |
| claim-verifier | `{session}/revision/verification-report-{shard_index}.md` |
| merged citation audit | `{session}/revision/citation-audit.json` |
| accuracy issue manifest | `{session}/revision/accuracy-issues.json` |
| style-reviewer | `{session}/revision/style-review.md` |
| style issue manifest | `{session}/revision/style-issues.json` |
| revision status manifest | `{session}/revision/revision-manifest.json` |

**Do not override these paths** when launching agents. Let each agent write to its default location — the paths above match what the agent prompts specify. **Why no overrides:** Ad-hoc path overrides in agent launch prompts diverge from the agent's own conventions, causing outputs to land in unexpected locations. When the orchestrator and agent disagree on where files go, downstream steps that read those files break silently.

---

## What This Skill Does NOT Do

- **No new research.** This skill does not search for sources, download papers, or run the research pipeline. If the user needs more sources, they should run `/deep-research` again or do targeted searches manually.
- **No report generation from scratch.** The reviser edits an existing draft — it does not synthesize a new one. If `report.md` doesn't exist, this skill can't help.
- **No structural reorganization.** The reviser fixes flagged issues, not report architecture. If the user wants the report reorganized (different section order, merged sections, new sections), that's a new synthesis task, not a revision. **Why:** Reorganization requires re-synthesizing the narrative flow across sections — the Edit tool can't do this safely because moving content between sections risks orphaned citations, broken cross-references, and lost context. That's the synthesis-writer's job, not the reviser's.
