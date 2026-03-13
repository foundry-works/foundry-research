# Plan: Reduce Orchestrator Context Pressure Through CLI Output Compaction

## Diagnosis

The orchestrator runs out of context not because it's doing too much *thinking* — but because the CLI tools return too much *noise*. The biggest offenders:

- **`state sources`** returns 11 fields per source × 30-50 sources = 10-50KB per call, called 3-5 times per session.
- **`state summary`** returns full findings text + full source list + full gap details = 5-20KB, landing in the orchestrator's context right before synthesis — the most context-pressured phase.
- **`state audit`** returns full ID arrays (`downloaded_ids`, `notes_ids`, `no_content`) listing 20-40 IDs each, when the orchestrator only needs counts.

## Design Principle

From blogpost2.md: *"Factorize the factorizable, leave the judgment to the model."*

CLI output formatting is factorizable. Research judgment (gap analysis, coverage assessment, synthesis strategy) is not. We shrink the factories — we don't move thinking out of the orchestrator.

### What we're NOT doing (and why)

- **No "pre-read validator" agent.** Pre-read validation is lightweight judgment informed by the orchestrator's full research context. An agent would make pass/fail decisions without knowing the brief, the coverage landscape, or what gaps need filling. The orchestrator sometimes notices "this source is about X, not Y, but X might still be useful for Q4" — a validator agent can't do that.
- **No "coverage analyst" agent.** Gap detection and strategy is the core judgment call of the research process. Delegating it to an agent that received manifests as input text (decontextualized from the research journey) would be building a sub-factory. The orchestrator deciding "Q3 is thin, let's target it with citation chasing on paper X" is exactly the thinking that should stay with the thinker.
- **No "synthesis prep" agent.** The narrative key-findings summary is an interpretive act. The orchestrator has lived the research journey — it knows which sources were mismatched, which gaps resisted filling, what surprised it. A prep agent would be narrating a journey it didn't take.

## Changes

### 1. `state sources --compact` (state.py)

**Current:** Returns `id, title, type, provider, doi, url, citation_count, content_file, pdf_file, quality, added_at` for every source. At 30-50 sources, this is 10-50KB.

**Change:** Add `--compact` flag that returns only `id, title, quality, content_file` — the four fields the orchestrator actually uses when deciding what to read and what to skip. ~80% output reduction.

Also add `--fields` flag for arbitrary field selection: `--fields id,title,doi` returns only those columns. This future-proofs against needing different field subsets without adding more boolean flags.

**Why these fields:** The orchestrator uses `sources` for: (a) pre-read validation — needs `id` + `content_file` to know what to Read, (b) quality checks — needs `quality` to skip mismatched/degraded, (c) journal logging — needs `title` for human-readable entries. Everything else (`doi`, `url`, `citation_count`, `provider`, `added_at`) is used by the source-acquisition agent in its own context, not by the orchestrator.

### 2. `state summary --compact` (state.py)

**Current:** Returns the full brief, full source list (id + title + type + provider), full findings list (id + text + sources + question), full gaps list, and metrics. At 20+ findings with multi-sentence text and citation arrays, this is 5-20KB.

**Change:** Add `--compact` flag that returns:
- `brief`: just the questions list (not scope or completeness_criteria)
- `search_count`, `source_count` (counts only)
- `sources_by_type`, `sources_by_provider` (distribution maps, already compact)
- `findings_by_question`: `{"Q1: What mechanisms...": 4, "Q2: Does it replicate?": 1}` — counts per question, not the findings themselves
- `gaps`: kept as-is (usually <5 items, small)
- Omit: `sources` array, `findings` array, `metrics` array

**Why:** The orchestrator uses `summary` for coverage assessment: "Which questions have thin findings? How many sources do I have? Are there open gaps?" It doesn't need the findings *text* — that's for the synthesis-writer. The compact version gives the orchestrator exactly the decision-making data it needs in ~1-2KB instead of 5-20KB.

### 3. `state summary --write-handoff` (state.py)

**Current:** The orchestrator calls `state summary`, receives the full 5-20KB response in context, then passes findings + gaps + brief to the synthesis-writer as part of the Agent prompt.

**Change:** Add `--write-handoff` flag that writes the full summary (findings with text, gaps, brief, methodology stats) to `synthesis-handoff.json` in the session directory and returns only `{"path": "deep-research-topic/synthesis-handoff.json", "findings_count": 24, "gaps_count": 2}`.

The orchestrator passes the file path to the synthesis-writer, which reads it directly. The full findings data never enters the orchestrator's context.

**Why this isn't "moving thinking":** The orchestrator still writes its narrative key-findings summary (the interpretive layer) based on what it already knows from living the research journey — reader manifests, gap analysis, quality report. It just doesn't need to hold the raw structured findings in its context to do that. The structured data is for the synthesis-writer's citation precision, not for the orchestrator's judgment.

### 4. `state audit --brief` (state.py)

**Current:** Returns full ID arrays: `downloaded_ids` (20-40 IDs), `notes_ids` (15-25 IDs), `no_content` (5-20 IDs), `abstract_only` (0-10 IDs). These arrays are useful for debugging but the orchestrator only needs counts.

**Change:** Add `--brief` flag that replaces ID arrays with counts:
- `downloaded_ids` → `sources_downloaded` (count, already present)
- `notes_ids` → `sources_with_notes` (count, already present)
- `no_content` → `no_content_count`
- `abstract_only` → `abstract_only_count`
- Keep: `degraded_quality` and `mismatched_content` as arrays (small, and the orchestrator needs to know *which* sources are problematic)
- Keep: `findings_by_question`, `sparse_questions`, `gaps`, `methodology`, `warnings` (all decision-relevant)

**Why keep degraded/mismatched as arrays:** The orchestrator passes mismatched source IDs to the gap-mode source-acquisition agent (step 13 in SKILL.md). These are typically 0-5 IDs — small, and the orchestrator needs the specific IDs, not just a count.

### 5. Update SKILL.md

Update workflow references to use compact variants:
- Step 8 (mark-read): Note that `state sources --compact` is sufficient for source listing
- Step 12 (audit): Recommend `state audit --brief` for the pre-synthesis check
- Step 14a (synthesis handoff): Use `state summary --write-handoff` instead of `state summary`, pass the file path to the synthesis-writer
- "Keep in your context" section: Note compact variants

### 6. Update source-acquisition.md

The source-acquisition agent runs in its own context, so it can use the full (non-compact) variants. No changes needed — but add a note that `--compact` exists in case the agent wants to use it for its own context management on large sessions.

## Expected Impact

| Command | Current output | With compaction | Savings per call |
|---------|---------------|-----------------|------------------|
| `state sources` (30 sources) | ~15KB | ~3KB (`--compact`) | ~12KB |
| `state sources` (50 sources) | ~30KB | ~5KB (`--compact`) | ~25KB |
| `state summary` (20 findings) | ~10KB | ~1.5KB (`--compact`) | ~8.5KB |
| `state summary` (synthesis handoff) | ~10KB in context | ~200B in context | ~10KB |
| `state audit` (25 sources) | ~4KB | ~2KB (`--brief`) | ~2KB |

Over a full session (3-5 `sources` calls + 1-2 `summary` calls + 1 `audit` call): **~50-100KB total savings** from the orchestrator's context. At ~4 tokens per character, that's **~12-25K tokens** freed — enough for several more tool calls or agent coordination rounds.

## Implementation Order

1. `state sources --compact` + `--fields` — highest frequency, biggest per-call savings
2. `state summary --write-handoff` — biggest single-call savings, directly unblocks the synthesis bottleneck
3. `state summary --compact` — used for coverage assessment between read/synthesis phases
4. `state audit --brief` — smallest impact but trivial to implement
5. SKILL.md updates — reference new flags in the workflow
6. Copy to `.claude/` via `./copy-to-skills.sh` and test
