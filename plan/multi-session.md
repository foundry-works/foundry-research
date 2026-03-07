# Multi-Session Research Architecture

> **Phase 3 — Future Work.** This document describes an evolution of the single-skill MVP (Phase 1). It introduces `project.py`, evidence tracking, and phase-based skills with a router. Do not implement until Phase 1 is stable and tested, and the Phase 2 financial extension is complete. The MVP uses `state.py` with the 16-command interface defined in [`scripts/state.md`](./scripts/state.md). Phase 2 adds 4 financial metrics commands.

## The Problem with Single-Session

The current plan assumes one continuous session: brief → search → read → synthesize → done. This breaks down for serious research because:

- **Context exhaustion** — a 40-source investigation can't fit deep reading + synthesis + verification into one context window
- **No iteration** — real research is nonlinear; you read, rethink your questions, search again, re-read with new eyes
- **No separation of concerns** — gathering requires breadth, analysis requires depth, synthesis requires narrative, verification requires skepticism. These are different cognitive modes that benefit from different prompts and context budgets
- **No checkpoint/resume** — if a session dies mid-research, you lose everything that was in Claude's reasoning but not on disk

## Design Principle: Artifacts Over Context

The core shift: **what matters is what's on disk, not what's in context.** Each session reads from and writes to a shared project directory. Sessions are ephemeral; artifacts are permanent.

This means every important piece of reasoning must be externalized:
- Not "Claude remembers the contradiction between papers 3 and 7" → but a `notes/src-003.md` file that says "Contradicts src-007 on sample size effects"
- Not "Claude knows Q2 is well-covered" → but a `project.yaml` with coverage assessments per question
- Not "Claude has a mental model of the evidence" → but an `evidence.yaml` mapping claims → sources → assessments

---

## Project Directory Structure

```
research-projects/<project-name>/
├── project.yaml                # Research brief, questions, status, coverage
├── evidence/                   # Claims → sources → assessments (split per research question)
│   ├── Q1.yaml                 # Evidence for research question 1
│   ├── Q2.yaml                 # Evidence for research question 2
│   └── ...                     # Skills load only the questions they need
├── journal.md                  # Append-only research narrative (the journey)
│
├── sources/                    # Downloaded content (same as current plan)
│   ├── src-001.md              # Pure markdown content (no frontmatter)
│   ├── src-001.pdf             # Original PDF when available
│   ├── src-002.md
│   └── ...
│
├── notes/                      # Reading notes (one per source, created during analyze)
│   ├── src-001.md              # Structured reading notes for source 1
│   ├── src-003.md              # Not every source gets notes — only deep-read ones
│   └── ...
│
├── searches/                   # Search result logs (raw, for audit/replay)
│   ├── search-001.json         # Provider, query, results, timestamp
│   ├── search-002.json
│   └── ...
│
├── drafts/                     # Synthesis outputs (versioned)
│   ├── draft-v1.md             # First synthesis attempt
│   ├── draft-v2.md             # Post-verification revision
│   └── draft-final.md          # After editing
│
└── reviews/                    # Verification and editing artifacts
    ├── verify-v1.md            # Claim verification table
    └── edit-notes.md           # Copy-editing changelog
```

### Why This Structure

- **`sources/`** stays the same as current plan — proven format, human-readable, machine-parseable
- **`notes/`** externalizes deep reading so future sessions don't re-read sources
- **`journal.md`** captures the research narrative — why things changed, what surprised us, how understanding evolved. Append-only. The journey, not just the destination
- **`searches/`** separated from project state so search history is auditable without bloating the main project file
- **`drafts/`** versioned so you can see how the report evolved; verification operates on a specific draft version
- **`reviews/`** keeps verification and editing artifacts separate from the report itself

---

## Artifact Formats

### project.yaml

The central coordination file. Every skill reads this first to understand what's been done and what's needed.

```yaml
id: "proj-20260307-143022"
query: "How do quantization methods affect large language model accuracy?"
created_at: "2026-03-07T14:30:22Z"
status: gathering  # gathering | analyzing | synthesizing | verifying | editing | complete

brief:
  scope: "Compare post-training quantization methods for LLMs >10B parameters"
  questions:
    - id: Q1
      text: "What are the main PTQ approaches (GPTQ, AWQ, SqueezeLLM, etc.)?"
      status: covered  # open | partial | covered
      source_count: 7
    - id: Q2
      text: "How do they compare on perplexity degradation vs compression ratio?"
      status: partial
      source_count: 3
      gap: "Missing data on models >70B parameters"
    - id: Q3
      text: "What are the hardware requirements and inference speed implications?"
      status: open
      source_count: 1
  completeness_criteria: "Each question answered with 2+ academic sources and 1+ benchmark"

sources:
  total: 18
  by_type: { academic: 12, preprint: 3, web: 2, github: 1 }
  by_status: { downloaded: 18, notes_written: 8, cited_in_draft: 0 }

searches:
  total: 9
  providers_used: [semantic_scholar, openalex, arxiv, github]

findings:
  - id: F1
    text: "GPTQ achieves 3-4 bit quantization with <1% perplexity increase on models >13B"
    sources: [src-003, src-007, src-012]
    question: Q1
    confidence: high
    timestamp: "2026-03-07T15:20:00Z"
  - id: F2
    text: "AWQ outperforms GPTQ on instruction-following benchmarks but not perplexity"
    sources: [src-008, src-014]
    question: Q2
    confidence: medium
    timestamp: "2026-03-07T15:45:00Z"

gaps:
  - id: G1
    text: "No sources on quantization effects for models >70B parameters"
    question: Q2
    status: open
  - id: G2
    text: "Missing inference speed benchmarks on consumer GPUs"
    question: Q3
    status: resolved
    resolved_by: [src-015, src-016]

current_draft: null  # path to current draft, or null if not yet synthesized
```

### notes/src-003.md — Reading Notes

Created during the **analyze** phase. Structured so a future session can understand this source without re-reading the original.

```markdown
---
source_id: src-003
read_depth: full        # full | sections | abstract_only
read_at: "2026-03-07T15:10:00Z"
relevance: high         # high | medium | low
questions: [Q1, Q2]
---

## Core Argument
GPTQ uses one-shot weight quantization based on approximate second-order information.
Achieves 3-4 bit precision with minimal accuracy loss on models ≥13B parameters.

## Key Evidence
- Table 3: OPT-175B at 3-bit GPTQ shows 0.3 perplexity increase over FP16 (p.7)
- Table 5: BLOOM-176B at 4-bit GPTQ shows 0.1 perplexity increase (p.9)
- Inference speedup: 3.2x on A100 for INT4 vs FP16 (Section 5.2)

## Methodology
- Evaluated on OPT (125M–175B), BLOOM (560M–176B)
- Metrics: perplexity on WikiText-2, C4; zero-shot accuracy on 6 benchmarks
- Calibration: 128 random samples from C4 training set

## Limitations
- No evaluation on instruction-tuned models
- Calibration sensitivity not explored (only C4 tested)
- Hardware benchmarks only on A100, no consumer GPU data

## Connections
- Contradicts src-007 on whether 3-bit is viable for <13B models
  (src-007 reports significant degradation at 3-bit for 7B models)
- Complements src-012 which extends GPTQ with activation-aware calibration
```

### evidence.yaml — Evidence Map

Accumulates across sessions. Maps claims to supporting/contradicting evidence. This is what the synthesis skill consumes.

```yaml
claims:
  - id: C1
    text: "Post-training quantization to 4-bit preserves >99% of model accuracy for LLMs above 13B parameters"
    status: supported  # supported | contested | unsupported | unverified
    supporting:
      - source: src-003
        detail: "Table 3: OPT-175B at 4-bit shows 0.1 perplexity increase"
        strength: strong
      - source: src-007
        detail: "LLaMA-65B at 4-bit within 0.5% on MMLU"
        strength: strong
      - source: src-012
        detail: "AWQ-quantized LLaMA-2-70B matches FP16 on MT-Bench"
        strength: strong
    contradicting:
      - source: src-007
        detail: "LLaMA-7B at 4-bit drops 2.1% on MMLU — effect is size-dependent"
        strength: moderate
        note: "Not a true contradiction — claim specifies >13B"
    questions: [Q1, Q2]

  - id: C2
    text: "AWQ outperforms GPTQ on instruction-following benchmarks"
    status: contested
    supporting:
      - source: src-008
        detail: "AWQ scores 7.2 vs GPTQ's 6.8 on MT-Bench at 4-bit"
        strength: moderate
    contradicting:
      - source: src-014
        detail: "No significant difference on AlpacaEval at 4-bit"
        strength: moderate
    questions: [Q2]
```

### journal.md — Research Journal

Append-only narrative that captures the research *journey* — the reasoning, pivots, surprises, and evolving understanding that don't belong in structured state files. Every skill appends to the journal whenever something important shifts.

**Two complementary views of the project:**
- `project.yaml` = **current state** — "here's where things stand right now"
- `journal.md` = **narrative arc** — "here's how we got here and why"

The journal serves three purposes:
1. **Context recovery** — a future session reads the journal to understand not just *what* was done but *why*, catching nuance that structured fields can't capture
2. **Synthesis input** — the synthesize skill uses the journal to understand the research's intellectual trajectory, not just its data points
3. **User transparency** — the user can read the journal to see how Claude's understanding evolved

```markdown
# Research Journal: Post-Training Quantization for LLMs

## Session 1 — Initial Gathering (2026-03-07 14:30)
Skill: research-gather

Started with the user's query about quantization methods and LLM accuracy. Decomposed
into 5 research questions covering approaches, accuracy tradeoffs, hardware implications,
deployment practices, and future directions.

Initial search across Semantic Scholar, OpenAlex, and arXiv returned a rich landscape —
this is a heavily-studied area with clear methodological camps (GPTQ-family vs AWQ-family
vs mixed-precision approaches). Downloaded 22 sources.

**Key observation:** The literature splits cleanly between "pure quantization" papers
(algorithmic contributions) and "systems" papers (how to deploy quantized models
efficiently). Our research questions span both, which means we'll need sources from
both communities.

**Coverage assessment:** Q1 (approaches) is well-covered — the field is mature enough
that survey papers exist. Q2 (accuracy tradeoffs) has good data but mostly for models
≤65B. Q3 (hardware) is sparse — most papers benchmark on A100 only. Will need targeted
searching.

## Session 2 — Targeted Gathering (2026-03-07 16:00)
Skill: research-gather

Focused on the gaps: hardware diversity (Q3) and real-world deployment (Q5). Searched
GitHub for implementation repos and Reddit for deployment experience reports.

**Surprise finding:** The Reddit/HN sources are more valuable than expected for Q5.
Academic papers rarely discuss deployment pain points (memory fragmentation, batch size
sensitivity, quantization-aware serving frameworks). Community sources fill this gap well.

Added 6 sources. Q3 still needs work — almost no published benchmarks on consumer GPUs
(RTX 4090, etc.), which matters for the "accessibility" angle of the research.

## Session 3 — Deep Analysis, Part 1 (2026-03-08 09:00)
Skill: research-analyze

Deep-read the 8 most-cited sources. The core insight emerging: **quantization effects
are not linear with model size.** There's a threshold around 13B parameters where
quantization becomes nearly lossless. Below that, accuracy drops are significant and
method-dependent.

**Important contradiction found:** src-003 (GPTQ paper) claims 3-bit is viable for
all tested models, but src-007 (LLaMA quantization study) shows significant degradation
at 3-bit for 7B models. Resolution: src-003 tested on OPT architecture, src-007 on
LLaMA. The effect appears architecture-dependent, not universal. This nuance is critical
for the report — can't make blanket claims about "3-bit quantization."

**Reframing:** Original Q1 asked "what are the main approaches?" but the more interesting
question is emerging as "when does each approach work best?" The approaches are well-known;
the selection criteria are not. Updated research brief to reflect this.

## Session 5 — Synthesis (2026-03-08 14:00)
Skill: research-synthesize

Writing the draft. The evidence map has 14 claims, mostly well-supported. Organizing
around the "scale threshold" insight from Session 3 rather than the original question
structure — it tells a better story and the user's questions are still answered, just
in a more insightful frame.

**Weak spots in the draft:**
- Section on consumer GPU performance relies on a single Reddit benchmark post.
  Flagged for the user — this is the best available data but not peer-reviewed.
- The "future directions" section is speculative by nature. Kept it short and clearly
  labeled as forward-looking rather than evidence-based.

## Session 6 — Verification (2026-03-08 15:30)
Skill: research-verify

Found one claim I'd overstated: draft said "quantization is lossless above 70B" but no
source actually demonstrates this — they test up to 65B/70B and show *minimal* loss, not
zero. Changed to "near-lossless" with the specific numbers. Small difference in wording,
significant difference in accuracy.

Also caught a citation error: attributed a hardware benchmark to src-012 but it was
actually in src-015. Fixed.
```

**Format rules:**
- Append-only — never edit or delete previous entries
- One entry per session, written at the end of the session
- Timestamped with session number and skill name
- Focus on **reasoning, pivots, surprises, and interpretive shifts** — not mechanical actions (those are in `project.yaml` and `searches/`)
- Keep each entry to ~100-300 words — this is a log, not a report
- Bold key observations and surprises so they're scannable

**What goes in the journal vs. other artifacts:**

| Content | Where it goes | Why |
|---------|--------------|-----|
| "Searched Semantic Scholar for X, got 12 results" | `searches/`, `project.yaml` | Mechanical — structured data |
| "The literature splits into two camps and our questions span both" | `journal.md` | Interpretive insight |
| "src-003 contradicts src-007 on 3-bit viability" | `evidence.yaml`, `notes/` | Structured evidence |
| "The contradiction is architecture-dependent, not a real disagreement" | `journal.md` | Reasoning about evidence |
| "Reframed Q1 from 'what approaches exist' to 'when does each work best'" | `journal.md` + `project.yaml` | Journal captures *why*, project.yaml captures the new question text |
| "Coverage for Q2 is now partial with 3 sources" | `project.yaml` | Structured state |
| "Q2 coverage is weaker than it looks — sources agree but all use the same benchmark" | `journal.md` | Qualitative assessment |

### reviews/verify-v1.md — Verification Report

Created by the **verify** skill after reading the draft against sources.

```markdown
---
draft: drafts/draft-v1.md
verified_at: "2026-03-08T10:30:00Z"
claims_checked: 23
supported: 19
partially_supported: 2
unsupported: 1
unverifiable: 1
---

## Verification Results

| # | Claim (from draft) | Source | Verdict | Note |
|---|-------------------|--------|---------|------|
| 1 | "GPTQ achieves <1% perplexity increase at 4-bit" | src-003 | SUPPORTED | Table 3 confirms 0.1-0.3 increase |
| 2 | "AWQ consistently outperforms GPTQ" | src-008, src-014 | PARTIALLY_SUPPORTED | True on MT-Bench, not on AlpacaEval |
| 3 | "Quantization is lossless above 70B parameters" | — | UNSUPPORTED | No source makes this claim; draft overstates |
| 4 | "SqueezeLLM achieves 3-bit with no degradation" | src-009 | PARTIALLY_SUPPORTED | Paper says "minimal" not "no" degradation |
| ... | ... | ... | ... | ... |

## Recommended Changes
1. **Line 47:** Change "consistently outperforms" → "outperforms on instruction-following benchmarks (MT-Bench) but shows comparable results on other evaluations"
2. **Line 82:** Remove claim about lossless quantization at 70B — no source supports this
3. **Line 95:** Change "no degradation" → "minimal degradation (<0.5 perplexity points)"

## Missing Citations
- Paragraph 3, sentence 2: factual claim about hardware requirements has no citation
- Section 4.1: cost comparison table cites "industry benchmarks" without specific source
```

---

## The Five Skills

Each skill is a separate SKILL.md with access to the same Python tools. They share the project directory and artifacts. Each has a distinct cognitive mode and context budget strategy.

### Shared Across All Skills

All skills:
1. Start by reading `project.yaml` to understand current state
2. Read `journal.md` to understand how the research has evolved
3. Append a journal entry at session end capturing key reasoning, pivots, and surprises
4. Update `project.yaml` status and coverage after their work

All skills have access to the same Python tools (search.py, download.py, enrich.py, state.py → project.py).

### Skill 1: research-gather

**Cognitive mode:** Breadth-first exploration. Cast a wide net, triage efficiently.

**When to use:** Starting a new project, filling gaps, expanding coverage.

**Context budget:**
- Search results: ~20K tokens (bulk of context)
- Project state: ~3K
- Triage decisions: ~5K
- Minimal source reading (abstracts only via `sources/metadata/` JSON files)

**What it does:**
1. If new project: create `project.yaml`, design research brief, decompose into questions
2. If continuing: read `project.yaml`, identify open questions and gaps
3. Search across providers (delegating parallel searches to workers)
4. Triage results: relevant/maybe/skip
5. Download relevant sources to `sources/`
6. Register sources in `project.yaml`
7. Assess coverage: which questions are now covered, partial, or still open?
8. Log any new gaps discovered

**What it produces:**
- Downloaded source files in `sources/`
- Updated `project.yaml` with new sources and coverage assessment
- Search logs in `searches/`

**What it does NOT do:**
- Deep-read sources (that's analyze)
- Write findings or evidence claims (that's analyze)
- Draft the report (that's synthesize)

**Session end state:**
Claude reports to user: "Gathered N sources across M providers. Questions Q1 and Q2 look well-covered. Q3 still has gaps around [topic]. Recommend an analyze session next, or another gather session focused on [gap]."

### Skill 2: research-analyze

**Cognitive mode:** Depth-first comprehension. Read carefully, extract precisely, connect across sources.

**Context budget:**
- Full source text: ~40-60K tokens (bulk of context)
- Existing notes: ~5K (to avoid re-reading)
- Project state: ~3K
- Note-writing: ~10K

**What it does:**
1. Read `project.yaml` for questions and source list
2. Read existing `notes/` to see what's already been analyzed
3. Pick the next batch of un-analyzed sources (prioritize by relevance)
4. Deep-read each source: intro, methods, results, conclusion
5. Write structured reading notes to `notes/src-NNN.md`
6. Extract claims and add to `evidence.yaml`
7. Identify contradictions between sources
8. Update coverage assessment in `project.yaml`
9. Log findings and any new gaps

**What it produces:**
- Reading notes in `notes/`
- Claims in `evidence.yaml`
- Updated findings and gaps in `project.yaml`

**Key behavior — spanning sessions:**
If there are 25 sources and only 8 can be deeply read per session, the skill handles 8 and reports: "Analyzed 8 of 25 sources. 17 remaining. Key findings so far: [summary]. Recommend continuing analysis in another session."

The next analyze session picks up from the notes and evidence already on disk.

**Delegation:**
Sonnet workers can summarize lower-priority sources in parallel while Claude deep-reads the most important ones.

### Skill 3: research-synthesize

**Cognitive mode:** Narrative construction. Weave evidence into a coherent story.

**Context budget:**
- Evidence map (`evidence.yaml`): ~5-10K
- Reading notes (all): ~10-20K
- Key source sections (targeted reads): ~15-20K
- Draft writing: ~10-15K

**What it does:**
1. Read `project.yaml` for brief, questions, findings
2. Read `evidence.yaml` for the full claim map
3. Read all `notes/` files for per-source summaries
4. Organize by theme/question, not by source
5. Write the draft to `drafts/draft-v1.md`
6. For each claim in the draft, verify it matches `evidence.yaml` and cite specific sources
7. Flag weak areas: claims with only one source, contested claims, gaps
8. Update `project.yaml`: set `current_draft`, update status to `verifying`

**What it produces:**
- `drafts/draft-v1.md` — complete report draft with citations
- Updated `project.yaml`

**Critical constraint:** The synthesis skill should **not** search for new sources or do fresh downloads. It works from what's already gathered and analyzed. If it discovers a gap, it logs it and flags it to the user — who can then run another gather session.

**This separation is important:** it prevents synthesis from becoming an endless loop of "oh I need one more source." The evidence cutoff is explicit.

### Skill 4: research-verify

**Cognitive mode:** Adversarial skepticism. Try to break every claim.

**Context budget:**
- Draft text: ~10K
- Source files (targeted reads to verify specific claims): ~40-50K
- Verification table: ~5K

**What it does:**
1. Read the current draft from `drafts/draft-v1.md`
2. Read `evidence.yaml` for the claim map
3. For each factual claim in the draft:
   a. Identify the cited source(s)
   b. Read the relevant section of the source file
   c. Assess: SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / UNVERIFIABLE
   d. If partially supported or unsupported, note what the source actually says
4. Check for uncited claims (factual statements without references)
5. Check for citation errors (source doesn't say what's attributed to it)
6. Write verification report to `reviews/verify-v1.md`
7. Produce a revised draft `drafts/draft-v2.md` with fixes applied

**What it produces:**
- `reviews/verify-v1.md` — detailed verification table
- `drafts/draft-v2.md` — revised draft with unsupported claims fixed
- Updated `project.yaml`

**Delegation:**
This is a great candidate for Sonnet workers. Each worker takes a section of the draft + relevant source files and returns a verification table. The supervisor merges and resolves conflicts.

### Skill 5: research-edit

**Cognitive mode:** Craft and precision. Polish prose, not content.

**Context budget:**
- Draft text: ~10-15K
- Style/format requirements: ~2K
- Editing output: ~10-15K

**What it does:**
1. Read the latest draft (post-verification)
2. Check structural coherence: does the report flow? Are transitions smooth?
3. Check for:
   - Repetition (same point made in multiple sections)
   - Hedging excess ("it seems that perhaps there might be evidence suggesting...")
   - Passive voice overuse
   - Inconsistent terminology
   - Citation format consistency
   - Section length balance
4. Fix prose issues while preserving meaning and citations
5. Format references consistently
6. Write final draft to `drafts/draft-final.md`
7. Produce edit changelog to `reviews/edit-notes.md`
8. Update `project.yaml`: status → complete

**What it produces:**
- `drafts/draft-final.md` — publication-ready report
- `reviews/edit-notes.md` — what was changed and why
- Updated `project.yaml`

**What it does NOT do:**
- Change factual content or claims
- Add or remove citations
- Re-verify claims (that was done in verify)

---

## Context Recovery Protocol

The most critical design element. When a new session starts, how does Claude efficiently recover the project state?

### The Recovery Stack

Every skill starts with the same recovery sequence:

```
1. Read project.yaml              (~1-3K tokens)  — brief, questions, coverage, status
2. Read journal.md                (~2-5K tokens)  — the research narrative so far
3. Read evidence.yaml             (~2-5K tokens)  — all claims and evidence links
4. Optionally read notes/         (~5-15K tokens) — if doing analysis or synthesis
5. Optionally read latest draft   (~5-10K tokens) — if doing verify or edit
```

Total recovery cost: **~5-30K tokens** depending on the skill. This is manageable even for large projects.

**Why the journal is step 2:** After understanding *what* the project is (project.yaml), the journal tells you *how the thinking has evolved* — before you look at the structured evidence. This means the skill starts with the right interpretive frame. A new gather session reads the journal and knows "we reframed Q1, the real question is about scale thresholds" before deciding what to search for. A synthesis session reads the journal and knows "the Reddit sources are unexpectedly valuable for Q5" before deciding how to weight sources.

### Why This Works

The key insight: **each artifact type serves a different recovery need.**

| Artifact | Answers | Read by |
|----------|---------|---------|
| `project.yaml` | "What are we researching? What's done? What's missing?" | All skills |
| `journal.md` | "How has the research evolved? What surprised us? Why did we change direction?" | All skills |
| `evidence.yaml` | "What do we know? How confident? What's contested?" | analyze, synthesize, verify |
| `notes/` | "What did we learn from each source?" | analyze (avoid re-reading), synthesize |
| `searches/` | "What searches have we run?" | gather (avoid re-searching) |
| `drafts/` | "What does the current report look like?" | verify, edit |

No single artifact needs to contain everything. Context recovery is a **selective read** based on what the current skill needs.

---

## project.py — Replacing state.py

`project.py` replaces `state.py` with project-scoped operations. Same CLI philosophy but richer commands.

```bash
# Project lifecycle
python project.py init --query "..." --project-dir ./research-projects/<name>
python project.py set-brief --json '{...}' --project-dir ...
python project.py status --project-dir ...              # compact status for CLI output

# Source management (same as state.py)
python project.py add-source --json '{...}' --project-dir ...
python project.py check-dup --doi/--url/--title --project-dir ...

# Search tracking
python project.py log-search --provider X --query "..." --result-count N --project-dir ...

# Evidence management (NEW)
python project.py add-claim --json '{...}' --project-dir ...
python project.py update-claim --id C1 --status contested --project-dir ...
python project.py link-evidence --claim C1 --source src-003 --type supporting --detail "..." --project-dir ...

# Findings and gaps (same as state.py)
python project.py log-finding --text "..." --sources "..." --question Q1 --project-dir ...
python project.py log-gap --text "..." --question Q3 --project-dir ...
python project.py resolve-gap --gap-id G1 --sources "src-019,src-020" --project-dir ...

# Coverage assessment (NEW)
python project.py update-coverage --question Q1 --status covered --project-dir ...
python project.py coverage --project-dir ...             # coverage report across all questions

# Journal (NEW — append-only research narrative)
python project.py journal --text "..." --skill research-gather --project-dir ...
python project.py journal --text "..." --tag pivot --project-dir ...      # tag notable entries
python project.py journal --text "..." --tag contradiction --project-dir ...
python project.py journal --text "..." --tag surprise --project-dir ...

# Context recovery (NEW — replaces state.py summary)
python project.py context --project-dir ...              # full recovery dump for skill startup
python project.py context --brief-only --project-dir ... # just brief + status
```

### What Changed from state.py

| state.py | project.py | Why |
|----------|-----------|-----|
| `init` (session) | `init` (project) | Project scope, not session scope |
| `summary` | `context` | Richer, skill-aware recovery |
| — | `journal` | Append-only research narrative |
| — | `add-claim`, `link-evidence` | Evidence map management |
| — | `update-coverage` | Per-question coverage tracking |
| `log-search` | `log-search` (unchanged) | Same |
| `add-source` | `add-source` (unchanged) | Same |

---

## Cross-Session Flow: A Worked Example

**User asks:** "I need a comprehensive review of post-training quantization methods for large language models."

### Session 1 — Gather (45 min)

```
User: /research-gather
      "comprehensive review of post-training quantization methods for LLMs"

Claude reads: nothing yet (new project)
Claude does:
  - Creates project directory
  - Designs research brief with 5 questions
  - Searches Semantic Scholar, OpenAlex, arXiv (parallel workers)
  - Triages 45 search results → 22 relevant
  - Downloads 22 sources
  - Assesses coverage: Q1 strong, Q2 partial, Q3-Q5 sparse
  - Writes journal entry: "Literature splits into pure-quantization and systems camps.
    Our questions span both. Q1 is mature — surveys exist. Q3 hardware coverage is sparse."

Claude reports: "Project initialized with 22 sources. Q1 (approaches) well-covered.
  Q2 (accuracy tradeoffs) needs more benchmarking papers. Q3-Q5 need targeted searches.
  Recommend another gather session for Q3 (hardware/speed) or start analyzing what we have."

Artifacts written:
  project.yaml, 22 source files, 8 search logs, journal.md
```

### Session 2 — Gather (20 min)

```
User: /research-gather (continue)
      "focus on Q3 hardware requirements and Q5 real-world deployment"

Claude reads: project.yaml (2K), journal.md (500B)
Claude does:
  - Targeted searches on GitHub (implementations), Reddit (deployment stories)
  - Downloads 6 more sources
  - Q3 now partial, Q5 now partial
  - Writes journal entry: "Reddit/HN sources unexpectedly valuable for Q5 — academic
    papers rarely discuss deployment pain points. Consumer GPU benchmarks still missing."

Artifacts updated: project.yaml, 6 source files, 3 search logs, journal.md
```

### Session 3 — Analyze (50 min)

```
User: /research-analyze

Claude reads: project.yaml, journal.md, evidence.yaml (empty)
Claude does:
  - Picks top 10 sources by relevance
  - Deep-reads each, writes notes to notes/
  - Extracts 8 claims into evidence.yaml
  - Finds 2 contradictions, 1 new gap
  - Writes journal entry: "Core insight emerging — quantization effects aren't linear
    with model size, there's a ~13B threshold. src-003 vs src-007 contradiction is
    architecture-dependent, not a real disagreement. Reframing Q1 from 'what approaches'
    to 'when does each work best.'"

Artifacts written: 10 notes files, evidence.yaml (8 claims)
Artifacts updated: project.yaml (findings, gaps, coverage, reframed Q1), journal.md
```

### Session 4 — Analyze (30 min)

```
User: /research-analyze (continue)

Claude reads: project.yaml, journal.md, evidence.yaml, existing notes (10 files)
Claude does:
  - Picks remaining 18 un-analyzed sources
  - Deep-reads 8 most relevant, abstract-only for rest
  - Adds 6 more claims to evidence.yaml
  - Updates existing claims with new supporting evidence
  - Writes journal entry: "Remaining sources mostly confirm existing claims. One new
    thread: mixed-precision approaches (different bits for different layers) may
    supersede uniform quantization. Not enough sources to make this a main section
    but worth noting."

Artifacts written: 8 more notes files, updated evidence.yaml, journal.md
```

### Session 5 — Synthesize (40 min)

```
User: /research-synthesize

Claude reads: project.yaml, journal.md, evidence.yaml (14 claims), all notes (18 files)
Claude does:
  - Reads journal — sees the "scale threshold" insight and the Q1 reframing
  - Organizes around the scale threshold narrative rather than original question order
  - Writes draft-v1.md organized by theme
  - Flags 3 weak areas (single-source claims)
  - Writes journal entry: "Organizing around scale threshold insight from Session 3.
    Consumer GPU section relies on one Reddit post — flagged as weak but best available.
    Future directions kept short — speculative by nature."

Artifacts written: drafts/draft-v1.md, journal.md
Artifacts updated: project.yaml (current_draft, status → verifying)
```

### Session 6 — Verify (30 min)

```
User: /research-verify

Claude reads: project.yaml, journal.md, drafts/draft-v1.md, evidence.yaml
Claude does:
  - Walks each claim in draft against source files
  - Finds 2 unsupported claims, 3 partially supported
  - Produces verification table
  - Writes corrected draft-v2.md
  - Writes journal entry: "Caught overstated claim — 'lossless above 70B' not supported,
    changed to 'near-lossless.' Also fixed a citation attribution error (src-012 → src-015).
    Draft is now clean."

Artifacts written: reviews/verify-v1.md, drafts/draft-v2.md, journal.md
Artifacts updated: project.yaml (status stays verifying until clean)
```

### Session 7 — Edit (20 min)

```
User: /research-edit

Claude reads: project.yaml, drafts/draft-v2.md
Claude does:
  - Tightens prose, fixes hedging
  - Normalizes citation format
  - Balances section lengths
  - Writes final draft

Artifacts written: drafts/draft-final.md, reviews/edit-notes.md
Artifacts updated: project.yaml (status → complete)
```

**Total: 7 sessions, ~4 hours of Claude time, 28 sources, 14 verified claims.**

Compare to single-session: would need to fit all of this into one context window, with no ability to iterate or checkpoint.

---

## What This Means for Implementation

### What stays from the current plan
- All Python tools (search.py, download.py, enrich.py, providers/)
- Shared utilities (_shared/)
- Source file format (separate metadata JSON + pure markdown)
- Delegation strategy (supervisor + workers)
- Provider selection heuristics

### What changes
1. **`state.py` → `project.py`** — richer, project-scoped, with evidence/coverage/session tracking
2. **1 SKILL.md → 5 SKILL.md files** — each ~100-150 lines, focused on one cognitive mode
3. **New artifact types** — notes, evidence map, verification reports, session log
4. **Directory structure** — project-level instead of session-level
5. **Context recovery protocol** — defined sequence for each skill to resume efficiently

### Implementation order (revised)

1. Shared utilities (unchanged)
2. `project.py` (expanded from state.py)
3. Provider modules (unchanged)
4. `search.py`, `download.py`, `enrich.py` (unchanged, but `--session-dir` → `--project-dir`)
5. Five SKILL.md files (new)
6. Testing: run a real multi-session research project end-to-end

### Skill prompt sizes (estimated)

| Skill | Lines | Focus of prompt |
|-------|-------|-----------------|
| research-gather | ~120 | Search strategy, triage, coverage assessment, when to stop gathering |
| research-analyze | ~130 | Deep reading strategy, note format, evidence extraction, contradiction detection |
| research-synthesize | ~120 | Narrative construction, organizing by theme, citing evidence, handling gaps |
| research-verify | ~100 | Claim checking protocol, verification verdicts, producing correction recommendations |
| research-edit | ~80 | Prose quality, consistency, formatting, what NOT to change |
| **Total** | **~550** | vs. ~230 for single skill — but each session only loads one |

---

## Orchestration: Who Decides What Happens Next?

Three modes of interaction, all using the same skills and artifacts. The difference is only who decides when to transition between phases.

### Mode 1: Manual — User Picks Each Skill

```
/research-gather "quantization methods for LLMs"
... user reviews artifacts, decides what's next ...
/research-gather "focus on hardware benchmarks for Q3"
... later ...
/research-analyze
... later ...
/research-synthesize
```

The user invokes specific skills by name. Each skill reads project state, does its work, reports results, and stops. The user decides what to run next based on their own judgment.

**Good for:** Power users, steering research direction, skipping or repeating phases, non-standard workflows (e.g., analyze → gather → analyze → synthesize, skipping verify).

**Skill interface:** Each skill is a separate slash command: `/research-gather`, `/research-analyze`, `/research-synthesize`, `/research-verify`, `/research-edit`.

### Mode 2: Guided — Agent Recommends, User Approves

```
/research "quantization methods for LLMs"
```

A single entry point skill (`/research`) that acts as a **router**. It reads project state and recommends the next action:

```
New project or no existing project:
  → "I'll start by gathering sources. Here's the research brief I'd propose: [brief].
     Sound good, or would you like to adjust the scope?"
  → runs research-gather

Continuing project, sources gathered but not analyzed:
  → "We have 28 sources. 8 have been analyzed. I'd recommend continuing analysis —
     there are 20 unread sources including 5 highly-cited papers. Or we could start
     synthesizing from what we have so far. What would you prefer?"
  → user picks → runs appropriate skill

Continuing project, analysis complete:
  → "Evidence map has 14 claims across all 5 questions. Coverage looks solid except
     Q3 (hardware) which has only 2 sources. Options:
     (a) Gather more for Q3 before synthesizing
     (b) Synthesize now and flag Q3 as a known limitation
     What do you think?"
  → user picks → runs appropriate skill

After synthesis:
  → "Draft is ready (3,200 words, 23 citations). Ready for verification?"

After verification:
  → "2 claims corrected, draft updated. Ready for final editing?"
```

**Good for:** Most users. Natural conversation flow. User stays in control but doesn't need to know the skill names or internals.

**Implementation:** The router is **not a separate skill that invokes other skills** — Claude Code does not support a skill programmatically swapping the active skill or executing another `/command` autonomously. Instead, the router is a **single unified `/research` skill** that contains the prompt instructions for all five cognitive phases. It dynamically adapts its behavior based on the project state:

1. Reads `project.yaml` and `journal.md` to determine current phase
2. Loads only the phase-relevant prompt section (gather, analyze, synthesize, verify, or edit)
3. Presents a recommendation with rationale
4. Waits for user input
5. Executes the chosen phase's behavior inline within the same skill context

The SKILL.md for `/research` is structured with clearly delineated phase sections. On each invocation, Claude reads the project state and activates the appropriate phase's instructions. This avoids the need for inter-skill invocation while preserving the cognitive separation between phases.

**Key design choice:** The router doesn't just silently pick a phase — it explains *why* it's recommending that action and gives the user alternatives. This builds trust and keeps the user informed about the research trajectory.

**Manual mode still works:** The individual `/research-gather`, `/research-analyze`, etc. commands are separate SKILL.md files that contain only their phase's instructions. They exist for power users who want direct control, bypassing the router entirely.

### Mode 3: Autonomous — Agent Drives

```
/research "quantization methods for LLMs" --auto
```

The agent runs the full pipeline within a single session (or across multiple if context runs out), making all transition decisions itself. It pauses only for:
- Confirmation of the initial research brief
- Ambiguous scope decisions that need user input
- Completion (presenting the final report)

```
Claude: "Starting autonomous research on 'quantization methods for LLMs.'

  Research brief:
  [brief with 5 questions]

  I'll gather sources, analyze them, synthesize a report, verify claims,
  and polish the output. I'll check in if I hit any major decision points.
  Okay to proceed?"

User: "go"

Claude: [runs gather → analyze → synthesize → verify → edit]
  [writes journal entries at each transition]
  [may pause if a gap requires user input on scope]

Claude: "Research complete. Report saved to drafts/draft-final.md.
  28 sources, 14 verified claims, 3,200 words. Here's the summary: ..."
```

**Good for:** Users who want the output, not the process. Quick questions that don't need iterative steering.

**Implementation:** Same unified `/research` skill with `--auto` flag that suppresses the "what would you prefer?" checkpoints and makes transition decisions based on heuristics. Phase transitions happen inline — Claude finishes gather behavior, re-reads project state, and switches to analyze behavior within the same session:

| Project state | Auto decision |
|--------------|---------------|
| No sources | Gather |
| Sources but coverage < 70% | Gather more (up to 2 rounds, then proceed) |
| Sources gathered, < 50% analyzed | Analyze |
| Sources analyzed, no draft | Synthesize |
| Draft exists, not verified | Verify |
| Verified, not edited | Edit |
| Edited | Done |

**Guardrail for auto mode:** Cap total autonomous actions (e.g., max 3 gather rounds, max 2 analysis passes) to prevent runaway research. Log everything to the journal so the user can review the decision trail afterward.

### How This Affects Skill Design

The three modes don't require different skill implementations — they require a **thin routing layer** on top of the same five skills.

```
User-facing commands:
  /research              → router skill (guided mode, default)
  /research --auto       → router skill (autonomous mode)
  /research-gather       → gather skill directly (manual mode)
  /research-analyze      → analyze skill directly (manual mode)
  /research-synthesize   → synthesize skill directly (manual mode)
  /research-verify       → verify skill directly (manual mode)
  /research-edit         → edit skill directly (manual mode)
```

The unified `/research` SKILL.md (~300 lines) contains all five phase sections plus routing logic. The five standalone phase skills (~60-80 lines each) are subsets for manual mode. This means some prompt content is duplicated between the unified skill and the standalone skills, but the duplication is intentional — it keeps each skill self-contained and avoids fragile cross-file prompt dependencies.

### Cross-Session Continuity in Each Mode

| Mode | Session boundary behavior |
|------|--------------------------|
| **Manual** | User starts a new session, invokes a specific skill. Skill recovers from artifacts. |
| **Guided** | User starts a new session, says `/research` (or just "continue research"). Router reads project state, recommends next step. |
| **Autonomous** | If context runs out mid-auto, the journal + project state let the next session resume. User says `/research --auto` again and it picks up where it left off. |

In all three modes, **the artifacts are the continuity mechanism**. The mode only affects who decides the next transition — the project directory, journal, evidence map, notes, and drafts are identical regardless.

---

## Open Questions

1. **Router vs. separate skills:** Is the router a 6th SKILL.md, or is it the "main" skill that delegates to the others? Leaning toward: it's the main `/research` skill, and the phase skills are internal (but directly invocable for manual mode).

2. **Auto mode within a single session:** Can autonomous mode actually complete a full research project in one session? For simple queries (5-10 sources), probably yes. For complex ones (30+ sources), context will run out. The auto mode needs to gracefully handle "I've used 70% of my context, time to checkpoint and tell the user to start a new session."

3. **Project management:** Who creates the project? Should `research-gather` auto-create on first run, or should there be a separate `research-init` step?

4. **Evidence.yaml scaling:** For very large projects (50+ sources, 30+ claims), evidence.yaml might get large. **Decision: split by research question.** Use `evidence/Q1.yaml`, `evidence/Q2.yaml`, etc. so that `analyze` and `verify` skills only load the evidence relevant to the specific question they're working on. The `synthesize` skill loads all evidence files but benefits from the smaller per-file size for targeted reads.

5. **Parallel skills:** Could you run two gather sessions in parallel (different questions)? The project.yaml would need conflict-safe writes.

6. **User-in-the-loop during analysis:** Should the analyze skill pause and ask the user about ambiguous interpretations, or just log them as notes? Different research styles may prefer different answers.

7. **Journal length management:** For long projects (10+ sessions), the journal could grow beyond what's useful for context recovery. Options: (a) keep it growing and let skills read selectively (last N entries + tagged entries), (b) have the synthesize skill produce a "journal summary" that compresses the narrative, (c) cap at a token budget and auto-summarize older entries. Leaning toward (a) — the journal is small per-entry (~200 words) and 10 sessions is only ~2K words.

8. **Journal vs. notes overlap:** Reading notes capture per-source insights; the journal captures cross-source reasoning. There's natural overlap (e.g., "src-003 contradicts src-007" might appear in both). Is this redundancy useful (different audiences: notes for source-level work, journal for project-level thinking) or wasteful? Leaning toward: useful — they serve different purposes and the duplication is small.

9. **Single-session fast path:** The router MUST have a fast-path bypass for simple queries. If the router estimates the query needs < 5 sources (factual lookup, narrow question, single-concept explanation), it should execute the entire pipeline inline within one prompt — search, read, synthesize — without generating `evidence.yaml`, `journal.md` entries, or splitting into separate gather/analyze/synthesize skills. Heuristics for fast-path: query is a single question (not comparative/systematic), no multi-domain coverage needed, user didn't request "deep" or "comprehensive" research. Don't force 5 separate cognitive modes for a 5-source question.

---

## Design Recommendations (from critique review)

These recommendations should be addressed during Phase 2 implementation.

### Consolidate semantically overlapping claims in evidence tracking

Before adding a new claim to `evidence.yaml`, the `analyze` skill should review existing claims for semantic overlap. If a new claim is essentially the same as an existing one (e.g., "GPTQ works well on 13B models" vs "Models over 13B see minimal loss with GPTQ"), append the new source to the existing claim's source list rather than creating a duplicate entry. This prevents `evidence.yaml` from bloating with near-identical claims across sessions.

**Implementation:** This requires an LLM-driven consolidation step — simple string matching won't catch semantic duplicates. Two options:

1. **Inline in analyze skill prompt:** Instruct the analyze skill to read existing claims before adding new ones, and explicitly merge when overlap is detected. Cheaper but relies on prompt compliance.
2. **`project.py consolidate-claims` command:** A dedicated pass that sends the full claim list to a Sonnet subagent for clustering and merging. More reliable but adds a step. Run periodically (e.g., after every analyze session) rather than on every claim insertion.

Recommend option 1 for the default path (analyze skill merges inline) with option 2 available as a manual cleanup command for large projects where drift accumulates.

### Prefer direct file I/O over CLI wrappers for declarative state

`project.py` should only wrap operations that involve complex logic: dedup checks, coverage math, search history queries. For declarative state — `evidence.yaml`, reading notes, draft text — let Claude use standard Read/Write/Edit tools directly. LLMs are better at reading and writing structured text natively than formatting strings into CLI arguments. This reduces syntax overhead and ID mismatch errors.

### Enforce a ceiling on context recovery payload

For deep reviews with 40+ sources, `evidence.yaml` and `notes/` will grow large. Constantly re-reading 30K tokens of notes on every turn degrades attention and increases cost.

**Compression strategy:** Implement a `compress` phase that runs when `notes/` exceeds a token threshold (~15K tokens across all files):

1. **Aggregate verified claims:** When 5+ sources agree on a claim and it's considered resolved, consolidate into a `summary-evidence.md` that captures the consensus with citation references but drops per-source detail.
2. **Archive granular notes:** Move individual `notes/src-NNN.md` files for resolved claims into `notes/archive/`. They remain on disk for reference but are excluded from the context recovery payload.
3. **Token ceiling:** Maintain a strict ceiling on the recovery payload (~15K tokens). The `synthesize` skill reads `summary-evidence.md` + active (unresolved) `notes/` files + `evidence.yaml`. Archived notes are only loaded on demand when a specific claim needs re-verification.

This compression should be triggered automatically by the router when entering a new session, not left to individual skills to manage ad-hoc.

### Force checkpoint before context exhaustion

If an `--auto` session approaches the context window limit, it must not silently degrade. Since Claude cannot reliably introspect its own token usage mid-turn, use a **hard turn counter** instead of a token percentage estimate:

- **Turn limit:** After N agent turns in auto mode (suggested: 15-20 turns for gather, 10 turns for analyze/synthesize), force a checkpoint regardless of perceived progress.
- **Source count trigger:** If total sources exceed 25 in a single session, force a checkpoint — this correlates with context pressure more reliably than turn counting.
- **Checkpoint action:** Update `journal.md` with current status and next steps, ensure all state is on disk, then yield to the user: *"Session checkpoint saved. Run `/research --auto` to resume from where I left off."*

These are blunt instruments, but they're reliable. A token-percentage heuristic would be better if Claude gains introspection capabilities in the future.
