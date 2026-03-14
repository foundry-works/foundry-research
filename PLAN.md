# Deep Research Pipeline Improvements — Plan (v2)

## Context

Observations from the 2026-03-14 "uncanny valley" research session. This was run **after** the v1 plan's fixes were implemented (path handling, mismatch detection, light gap-mode, quality report in handoff, abstract-only utilization, background task guardrail). The pipeline ran end-to-end: brief-writer → source-acquisition → pre-read validation → 12 parallel readers → 7 parallel findings-loggers → dedup → light gap-mode → synthesis-writer. 14 sources deeply read, 90 findings logged, ~3,850-word report produced.

This plan captures what the v1 fixes addressed well, what problems remain, and new issues surfaced by the session.

---

## What Worked Well (Strengths to Preserve)

### 1. Delegation architecture saves enormous context
The source-acquisition agent absorbed ~24 searches of raw JSON (100-200K tokens) and returned a ~500-token manifest. Readers (12 agents × 20-50K tokens each) kept the orchestrator focused on coordination. **This is the system's biggest win — protect it.**

### 2. Brief-writer produces genuinely useful questions
The adversarial question (Q6: "is the UV an artifact?") generated 15 findings and became one of the richest report sections. The mandatory tradeoffs + adversarial question requirement pays off in synthesis quality.

### 3. Pre-read validation catches waste
Reading 30 lines per source before spawning readers caught 4 tangential sources (chatbot compliance, Pepper robot, VR interaction fidelity metaphor, minimal method article). ~120-200K tokens saved for ~2 minutes of work.

### 4. Findings-logger parallelization is clean
7 agents per question, concurrent, no shared state, followed by `deduplicate-findings`. Zero merges needed — loggers are doing good within-agent dedup.

### 5. Light gap-mode worked exactly as designed (v1 fix validated)
Q4 (modern AI) had thin academic coverage. Light gap-mode (2 web searches → 2 downloads → 2 readers → 3 findings logged directly) resolved the gap in ~5 minutes instead of the ~50 minutes a full acquisition agent would have taken. The "recency vs. coverage" decision heuristic was easy to apply.

### 6. Abstract-only utilization step exists (v1 fix) but wasn't triggered
All questions had 7+ findings, so the <5 threshold was never hit. The step is there for when it's needed. See improvement item 4 below for a threshold adjustment.

---

## What Didn't Work Well

### 1. Tavily failures were invisible for too long
The source-acquisition agent reported "tavily returned no results" across 5+ attempts but didn't escalate this as an API failure vs. legitimate empty results. For a topic where Q4 (modern AI content) depends on web sources, this meant an entire question lost its primary source channel until the orchestrator's gap-mode.

**Root cause:** No connectivity test at session start. No distinction between "provider returned 0 results for this query" and "provider API is broken/misconfigured." The acquisition agent treats both identically.

**Impact:** Q4 had thin coverage until light gap-mode. The 2 web sources found in gap-mode (Frontiers 2025 review, Kramer 2025 AI faces) should have been found in round 1.

### 2. Massive paywall losses — 229/260 sources had no content
The recovery cascade (CORE, tavily, DOI landing page) went 0-for-everything. Key foundational papers (Mori 2012 translation, Gray & Wegner 2012, Mathur & Reichling 2016, Saygin 2012 fMRI) were all paywalled. Effective download rate: ~8%.

**Root cause:** No Unpaywall API integration. No institutional proxy support. CORE search returned nothing for exact-title queries. Tavily was broken (see item 1).

**Impact:** The system over-indexes on open-access journals (Frontiers, PLOS, arXiv) and under-indexes on the foundational literature that often matters most. The report had to caveat that several foundational papers "were inaccessible and could not be directly verified."

### 3. Content mismatches still leaked through (9 caught at download, 4 caught at pre-read)
The v1 mismatch detection improvements helped (9 caught at download time), but 4 more were caught only at the pre-read validation step. These were sources that shared vocabulary with the target topic but covered different specific areas (e.g., src-069 about chatbot compliance barely mentions UV, src-072 about Pepper robot is an overview not UV research).

**Root cause:** These are topical near-misses, not metadata mismatches. The title and abstract share enough keywords to pass relevance checks, but the paper doesn't actually study the uncanny valley.

### 4. Abstract-only utilization threshold is too conservative
The <5 findings threshold was never triggered because all questions had 7+ findings. But several abstract-only sources (src-003 mind perception, src-019 Ho & MacDorman measurement, src-043 persistence through interaction) contained empirical results that would have enriched the report. For example, src-003's finding about "uncanny valley of mind" (appearance × mental capacity interaction) is directly relevant to Q2 and Q4 but was only captured indirectly through other sources.

### 5. The orchestrator prompt is too long (~400 lines)
Under context compression, later steps get degraded attention. The gap-mode decision tree alone is ~50 lines. Provider selection guidance (~20 lines) and session structure (~15 lines) are reference material that doesn't need to be in the hot path.

### 6. No systematic cross-source contradiction detection
The report's strongest insight — the meta-analysis (no negative affect, N=11,053) vs. lab studies (consistent eeriness) contradiction — was caught by the orchestrator's interpretive judgment, not by any structured mechanism. The findings-loggers extract independently per question and can't flag when finding-X from src-A contradicts finding-Y from src-B.

### 7. Reader agents are expensive at Opus tier
12 parallel readers each consumed significant tokens. The `research-reader.md` agent definition may be configured for a higher model than needed. Reader note quality was excellent (caught effect sizes, methodological nuances, cross-study contradictions), but for straightforward empirical papers, a lighter model might suffice.

### 8. Synthesis-writer reference list had incomplete metadata
Several references had `[metadata incomplete]` flags because metadata files don't always have complete author lists, DOIs, or venues — especially for web-downloaded sources. No enrichment step exists between download and synthesis.

---

## Proposed Improvements

### 1. Tavily Connectivity Test and WebSearch Fallback (HIGH PRIORITY)

**Problem:** Tavily silently fails → entire source channels go dark for web-dependent questions.

**Fix:**
- **File: `agents/source-acquisition.md`** — Add at the start of the initial-mode workflow: "Before round 1 searches, run a single test tavily search (e.g., `search --provider tavily --query 'test'`). If it returns an error or 0 results, log a journal entry: 'Tavily API unavailable — using WebSearch for all web queries.' Then for all subsequent web search needs, tell the orchestrator in the manifest that tavily failed so the orchestrator can use `WebSearch` directly."
- **File: `skills/deep-research/SKILL.md`** — Add to step 4: "If the acquisition manifest reports tavily failure, run 2-3 `WebSearch` queries per web-dependent question immediately (don't wait for gap-mode)."

**Why:** Catches the failure in the first 30 seconds instead of discovering it after 24 searches.

### 2. Unpaywall API Integration (HIGH PRIORITY)

**Problem:** 8% effective download rate. Recovery cascade has no open-access discovery step.

**Fix:**
- **File: `skills/deep-research/scripts/download.py`** — Add Unpaywall API as a cascade step before CORE and tavily recovery. Unpaywall is free (requires email), legal, and has high coverage of OA copies (green OA, bronze OA, hybrid OA). Query by DOI: `https://api.unpaywall.org/v2/{doi}?email={email}`. If `best_oa_location.url_for_pdf` is non-null, download from there.
- **File: `skills/deep-research/scripts/_shared/config.py`** — Add `UNPAYWALL_EMAIL` config (not an API key — Unpaywall is free, just needs a contact email).

**Why:** Unpaywall covers ~30% of all DOIs with free legal PDFs. For a session finding 260 sources, this could yield 60-80 additional downloads — a 3-4x improvement over the current 22 valid downloads.

### 3. Web-First Source Mode for Recency-Dependent Questions (HIGH PRIORITY)

**Problem:** The triage system ranks by citation count, which systematically deprioritizes recent web sources and preprints that are the best evidence for emerging topics.

**Fix:**
- **File: `agents/source-acquisition.md`** — Add a "web-first questions" concept: "If the orchestrator flags specific questions as recency-dependent (e.g., 'Q4 is about AI-generated content — web sources are primary'), prioritize those questions' tavily/web results in triage regardless of citation count. Rank web sources for these questions by: (a) publication date, (b) domain authority (arxiv, pmc, acm > blog posts > reddit), (c) keyword relevance to the question."
- **File: `skills/deep-research/SKILL.md`** — In step 4 (source-acquisition handoff), add: "Flag any research questions where recency matters more than citation authority (typically: emerging technologies, current events, recent policy changes). The acquisition agent will prioritize web sources for these questions."

**Why:** The current system is excellent for established academic fields with citation networks. It's structurally weak for topics where the most relevant work is <2 years old.

### 4. Lower Abstract-Only Utilization Threshold (MEDIUM PRIORITY)

**Problem:** The <5 findings threshold is never triggered because findings-loggers are aggressive extractors.

**Fix:**
- **File: `skills/deep-research/SKILL.md`** — Change step 11b trigger from "< 5 findings" to: "If an abstract-only source directly addresses a research question with an empirical result (sample size, effect, conclusion), log a finding regardless of existing finding count. Cap at 2-3 abstract-based findings per question."

**Why:** The threshold-based trigger is about preventing wasted effort on thin questions. But the real value of abstract-based findings is supplementing deep-read evidence with additional data points — this is valuable even when the question already has 7+ findings, especially for topics where many relevant papers are paywalled.

### 5. Orchestrator Prompt Layering (MEDIUM PRIORITY)

**Problem:** SKILL.md is ~400 lines. Under context compression, procedural detail competes with research judgment.

**Fix:**
- Split SKILL.md into:
  - `SKILL.md` — Core workflow (15 steps), command execution rules, delegation patterns. Target: ~200 lines.
  - `REFERENCE.md` — Provider selection guidance, session structure, adaptive guardrails, output format template. Loaded by agents that need it, not always in orchestrator context.
- Move the gap-mode decision tree into a simpler heuristic: "Is the gap about search coverage (papers exist but weren't found) or topic recency (papers don't exist yet)? Coverage → full. Recency → light."

**Why:** Shorter prompts → less degradation under compression → better research judgment in late-session decisions.

### 6. Cross-Source Contradiction Detection (MEDIUM PRIORITY)

**Problem:** Contradictions are the most valuable findings (they're where the interesting research questions live), but they're only caught if the orchestrator happens to notice.

**Fix (option A — CLI extension):**
- **File: `skills/deep-research/scripts/state.py`** — Add `--contradicts finding-NN` optional flag to `log-finding`. When set, creates a `contradictions` row linking the two findings. Add `state contradictions` command to list all flagged contradictions.
- **File: `agents/findings-logger.md`** — Add instruction: "If a finding directly contradicts a previously logged finding (opposite conclusion about the same construct from a different source), use `--contradicts finding-NN`."

**Fix (option B — post-extraction pass):**
- Add a lightweight contradiction-detection step after deduplication (step 11): the orchestrator reads the full findings list and flags contradicting pairs. No new agent needed — the findings are already in context via the summary.

**Why:** Option A is more systematic but requires findings-loggers to know about other questions' findings (they currently don't). Option B is simpler and works within the current architecture. Recommend starting with option B.

### 7. Metadata Enrichment Before Synthesis (LOW PRIORITY)

**Problem:** Incomplete metadata → `[metadata incomplete]` flags in references → lower report quality.

**Fix:**
- **File: `skills/deep-research/scripts/state.py`** — Add `state enrich-metadata` command that queries Crossref API by title for sources with missing DOI, author, or venue fields. Run once after all downloads complete, before synthesis handoff.

**Why:** Crossref title search is free and resolves ~80% of missing DOIs. This is a polish improvement — the report is usable without it, but cleaner references increase credibility.

---

## Non-Changes (Considered but Rejected)

### Automated gap-mode skip decision
Considered adding a flag in `state audit` that automatically recommends skip/run for gap-mode. Rejected: the skip decision is a research judgment about whether thin coverage reflects search quality or genuine literature gaps. The current explicit criteria + journal rationale requirement keeps the human-in-the-loop.

### Parallel pre-read validation via agent
Considered spawning a subagent for batch pre-read. Rejected: inline `Read` calls are cheap (~30 lines × 21 sources), complete in seconds, and keep quality decisions in the orchestrator's context where they inform reader allocation.

### Structured reader output (JSON) instead of narrative notes
Considered having readers produce structured JSON (claims + evidence strength) instead of markdown notes. Rejected for now: narrative notes are more flexible and the synthesis-writer reads them effectively. Structured output would help contradiction detection (item 6) but requires redesigning the reader→findings-logger→writer data flow — too much scope for this iteration.
