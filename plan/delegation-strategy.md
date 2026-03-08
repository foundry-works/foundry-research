# Delegation & Model Routing Strategy

## The Supervisor Model

The main Claude conversation acts as a **supervisor**. It holds the research brief, understands the user's intent, tracks what's been found, identifies gaps, and makes judgment calls. It doesn't need to do everything itself — it delegates bounded tasks to **worker subagents** and integrates their results.

This isn't a rigid hierarchy. The supervisor is fluid about what it handles directly vs. delegates. For a 5-source query, it might do everything inline. For a 40-source systematic review, it farms out most of the legwork. The decision is pragmatic: **delegate when the task is bounded, parallelizable, or would bloat the main context with low-value tokens.**

## Execution Model

Delegation uses **Claude Code's native Agent tool** with **pre-defined subagent files** that ship with the skill. No custom orchestration script, no raw API calls, no `delegate.py`.

### How it works

1. The skill ships subagent definitions in `.claude/agents/` (Markdown files with YAML frontmatter).
2. Each subagent specifies its `model` (`haiku`, `sonnet`, or `inherit`), `tools`, and system prompt.
3. The supervisor calls the Agent tool, Claude Code matches the task to a subagent and spawns it at the configured model tier.
4. Multiple Agent tool calls in a single response run in parallel.

### Subagent definitions shipped with the skill

**Note:** There is no `research-searcher` subagent. Search commands (`./search`, `./download`, `./enrich`) emit structured JSON that the supervisor can parse directly — there is no benefit to having an intermediate LLM summarize JSON, and doing so adds hallucination risk. The supervisor runs these CLI commands itself, even when running multiple searches in parallel (multiple Bash tool calls in one response). Subagents are reserved for **unstructured text comprehension** (reading papers, summarizing, verifying claims).

```markdown
# .claude/agents/research-reader.md
---
name: research-reader
description: Read and summarize research source files. Use for batch summarization.
tools: Read, Glob, Write
model: sonnet
---
Read the source file identified in your directive. Write a structured summary to disk, then return a manifest.

You will be assigned **one source** per invocation. Give it your full attention — read carefully,
extract precise evidence, and note methodological details.

## Output rules
- Write the summary to `notes/{source_id}.md` in the session directory (path provided in directive).
- Return ONLY a compact manifest entry to the supervisor — do NOT return the full summary.
  Manifest format: {"source_id": "src-003", "status": "ok", "path": "notes/src-003.md"}
- This keeps the supervisor's context clean. The supervisor will read notes/ files as needed.

## Error handling rules
- NEVER fabricate content. If a file is unreadable, garbled, or empty, say so explicitly.
- If a source file doesn't exist or can't be read, return the manifest with status "unreadable" and the error.
- If document structure is garbled (no headings, scrambled text), note this in the notes file so the supervisor knows the source quality is degraded.
- Always return valid JSON for the manifest.
```

### What this gives us

- **Model routing** — Sonnet for comprehension tasks (summarization, verification, claim checking)
- **Parallel execution** — multiple Agent calls in one response run concurrently
- **No API key management** — subagents inherit the session's credentials
- **Cost control** — Sonnet workers cheaper and faster than Opus for bounded reading tasks
- **Tool restrictions** — reader has Read+Glob+Write only
- **No LLM-in-the-middle for structured data** — supervisor runs CLI commands directly, parsing JSON output without an intermediate Haiku layer

## Model Tiers

| Tier | Model | Strengths | Typical tasks |
|------|-------|-----------|---------------|
| **Opus** (supervisor) | claude-opus-4-6 | Deep reasoning, synthesis, nuance, judgment | Research strategy, report writing, contradiction analysis, running CLI commands + parsing JSON output |
| **Sonnet** (worker) | claude-sonnet-4-6 | Good comprehension, fast, cost-effective | Source summarization, relevance assessment, claim verification |

The supervisor handles all structured/mechanical tasks (search commands, downloads, metadata enrichment) directly — no subagent needed for JSON parsing. Subagents are used only when the task requires **reading comprehension** of unstructured text at a scale that would bloat the supervisor's context.

## What the Supervisor Does

The supervisor holds the **research context** — the accumulated understanding of what's been found, what's missing, what contradicts what, and what the user actually needs. Tasks that require this context stay in the main conversation:

- Designing the research brief and questions
- Deciding search strategy (which providers, what queries, when to stop)
- Assessing coverage ("Q3 is still unanswered, need more sources")
- Resolving contradictions between sources
- Synthesizing findings into the final report
- Interacting with the user (checkpoints, clarifications, steering)

## What Workers Do

Workers receive a **directive** — a self-contained task description with enough context to execute independently. They return **compressed results** that the supervisor integrates.

### Directive Structure

A good directive includes:
- **What to do** (concrete action)
- **Relevant context** (the research question, not the full brief)
- **What to return** (expected output format)

The supervisor doesn't need to micromanage. Give the worker the task and let it figure out the details.

### Common Worker Tasks

#### Parallel Search (supervisor-direct, no subagent)

Search multiple providers simultaneously by issuing multiple Bash tool calls in one response:

```
# Three parallel Bash calls in one response — no subagent needed:
./search --provider semantic_scholar --query "transformer inference optimization" --limit 10 --session-dir {path}
./search --provider openalex --query "transformer inference optimization" --limit 10 --session-dir {path}
./search --provider arxiv --query "transformer inference optimization" --limit 10 --session-dir {path}
```

The supervisor parses the structured JSON output directly. No intermediate LLM summarization — the CLI scripts already return clean `{"status": "ok", "results": [...]}` envelopes.

#### Source Reading & Summarization (subagent)

Deep-read source files and return structured summaries so the supervisor doesn't consume full paper text. **Spawn one subagent per source** — this ensures each paper gets full attention. Run them in parallel.

```
# Three parallel Agent calls, one source each:

Directive: Read source src-003 in {session_dir}.
           Research context: "How do quantization methods affect model accuracy?"

Directive: Read source src-007 in {session_dir}.
           Research context: "How do quantization methods affect model accuracy?"

Directive: Read source src-012 in {session_dir}.
           Research context: "How do quantization methods affect model accuracy?"

Model: Sonnet (needs comprehension and judgment about what matters)
```

The supervisor receives ~100B manifest entries per agent instead of ~60KB of full paper text. Summaries are written to `notes/` on disk.

#### Batch Download (supervisor-direct, no subagent)

Download sources by running CLI commands directly:

```
# Supervisor runs these sequentially or uses --from-json for batch:
./download --doi "10.1234/foo" --source-id src-001 --session-dir {path} --to-md
./state add-source --from-json /tmp/source.json --session-dir {path}
```

For relevance triage after downloading, the supervisor reads the metadata JSON file (`sources/metadata/src-NNN.json` — abstract, authors, venue, citations) directly — this is compact and manageable in context. Only delegate to a reader subagent if deep reading of full paper text is needed.

#### Claim Verification

Before finalizing a report, check that cited claims match source content.

```
Directive: Here is the draft report. For each factual claim with a citation:
           - Read the cited source file
           - Assess: SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / UNVERIFIABLE
           - If unsupported, note what the source actually says
           Return the verification table.

Model: Sonnet (needs careful reading comprehension)
```

#### Citation Graph Exploration (supervisor-direct)

Follow citation chains by running CLI commands directly:

```
# Supervisor runs these and parses the JSON:
./search --provider semantic_scholar --cited-by "DOI:10.xxxx/yyyy" --limit 50 --session-dir {path}
./search --provider semantic_scholar --references "DOI:10.xxxx/yyyy" --limit 50 --session-dir {path}
```

The supervisor filters results (>50 citations, post-2022) from the structured JSON output itself.

## When to Delegate vs. Do Inline

There's no hard threshold. Use judgment:

| Signal | Lean toward delegating | Lean toward inline |
|--------|----------------------|-------------------|
| Source count | 15+ sources | < 10 sources |
| Provider count | 3+ providers per question | 1-2 providers |
| Task independence | Embarrassingly parallel | Sequential / dependent |
| Context cost | Would add 20K+ tokens to main context | Small, manageable reads |
| Reasoning depth | Mechanical / bounded | Needs full research context |

**It's fine to do everything inline for small research sessions.** Delegation is a scaling strategy, not a requirement.

## Parallelization

### The One Rule for Parallelism

**The only parallelization is across different providers.** Each parallel subagent hits a different API domain. That's it.

This is both a rate limit guarantee and a simplicity constraint. No two subagents ever hit the same domain concurrently, so rate limiting is trivially correct — each process owns its domain's rate bucket with no contention.

Examples of valid parallelism (multiple Bash or Agent tool calls in one response):
- 3 **parallel Bash calls** searching Semantic Scholar, OpenAlex, and PubMed simultaneously (supervisor-direct, no subagent — see "Parallel Search" above)
- 2 **parallel Bash calls** downloading from arXiv and PMC simultaneously
- N **parallel Agent calls** for reader subagents, one source per agent

Everything else is sequential:
- Multiple downloads from the same domain → sequential
- Search → triage → download → summarize → synthesize → verify
- Multiple searches on the same provider → sequential
- Summarizing source files → sequential (no rate limit concern, but not worth the subagent overhead)

Because each subagent owns its domain's rate bucket with no contention, cross-process locking is not strictly necessary under the one-domain-per-subagent rule. However, `rate_limiter.py` stores state in SQLite (`state.db`) as a **safety net** — SQLite's native locking handles edge cases like the supervisor and a subagent both hitting the same domain (e.g., during sequential fallback after a subagent failure), or `download.py --parallel` spawning threads against the same domain. No manual lock management needed.

## Context Window Protection

The core benefit: worker results are **compressed** before entering the supervisor's context.

| What the worker processes | What the supervisor receives |
|--------------------------|----------------------------|
| 50KB of search API JSON across 3 providers | 3KB triage table |
| 30KB full paper text | 100B manifest entry (summary written to `notes/`) |
| 10KB of metadata JSON | 200B key fields |
| 40KB of report + source files for verification | 1KB verification table |

The supervisor's context stays focused on **findings, reasoning, and synthesis** — not raw data.

## Failure Handling

Workers can fail (API errors, rate limits, network issues). The supervisor should:

- **Not retry immediately** — if a worker reports API failures, try a different provider or approach
- **Degrade gracefully** — if 2 of 4 parallel searches fail, work with what succeeded
- **Escalate to the user** if failures significantly limit research quality ("I couldn't access PubMed or Semantic Scholar — results may be limited for biomedical sources. Should I continue with what I have?")

## Skill Prompt Integration

The SKILL.md prompt should include a compact delegation reference:

```
## Delegation
You are the supervisor. Use the Agent tool to spawn worker subagents:

- Parallel searches: multiple Agent calls in one response, each hitting a different provider
- Batch work: downloads, metadata extraction, simple filtering
- Comprehension: source summarization, relevance assessment, claim verification

Give workers a clear directive. They return compressed results — not raw data.

For small sessions (< 10 sources), do everything inline.
```
