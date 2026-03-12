# Deep Research Improvement Plan

Improvements identified from the 2026-03-12 temperament measurement research session. That session surfaced systemic problems in the source acquisition and validation pipeline: 31% metadata-content mismatch rate on deep reads, off-topic papers dominating triage, and wasted reader agent tokens on irrelevant sources.

---

## 1. LLM-Powered Abstract Relevance Scoring

**Problem:** Triage ranks sources by `log(citations) * keyword_hits_in_title`. This lets high-citation off-topic papers (e.g., "SPIRIT 2013" at 6932 cites, a clinical trial protocol) rank above directly relevant papers with moderate citations. Keyword matching on titles alone cannot judge semantic relevance — "emotion regulation in preschoolers" is highly relevant to a temperament measurement review, but shares few literal keywords.

**Solution:** A CLI tool (`scripts/triage-relevance`) that uses Claude Code CLI in headless mode (Haiku) to score abstract relevance against the research brief. The source-acquisition agent calls it via Bash mid-pipeline, between search ingestion and download decisions.

### Design

**Input:** Research brief (scope + questions) + batch of abstracts from state.db.

**Output:** Per-source relevance score written back to state.db. Suggested schema: add `relevance_score` (float 0-1) and `relevance_rationale` (text) columns to the sources table.

**Flow inside source-acquisition pipeline:**
```
search → ingest → triage-relevance (Haiku via claude -p) → download (using relevance scores) → return manifest
```

**Implementation:**
1. New script: `skills/deep-research/scripts/triage-relevance` (Python, executable)
2. Pulls brief from state.db + top N source abstracts (default N=60, configurable)
3. Batches abstracts (15-20 per call to balance quality vs. cost) with the brief
4. Calls `claude -p "..." --model haiku --output-format json` for each batch
5. Parses JSON response: array of `{id, score, rationale}`
6. Writes scores back to `sources` table (`relevance_score`, `relevance_rationale`)
7. Exits 0 with JSON envelope like all other CLI tools

**Triage integration:** Modify `cmd_triage` in `state.py` to use `relevance_score` when available:
```python
# If LLM relevance score exists, use it; otherwise fall back to keyword matching
if s.get("relevance_score") is not None:
    relevance = s["relevance_score"]
else:
    relevance = min(keyword_hits / 5.0, 1.0)
```

**Prompt design for Haiku:** The prompt should include the full brief scope + questions, then a numbered list of abstracts. Ask for:
- `score`: 0.0 (irrelevant) to 1.0 (directly addresses a research question)
- `rationale`: One sentence explaining the relevance judgment
- `questions`: Which brief question IDs (Q1-Q7) this source could address

**Cost estimate:** 60 abstracts × ~250 words each = ~15K tokens input per session. At Haiku pricing, negligible. Multiple batches add prompt overhead but stay under 30K total.

**Source-acquisition agent integration:** Update `agents/source-acquisition.md` to include a step between ingestion and download:
```
search → ingest sources → run triage-relevance → download top-scored sources → triage → recover → return
```

### Why this approach

- **No new dependencies:** Uses `claude` CLI already available in the environment
- **Stays inside acquisition pipeline:** Source-acquisition agent calls it via Bash, no agent-spawning needed
- **Haiku is fast and cheap:** Relevance scoring is classification, not reasoning
- **Graceful fallback:** If `claude` CLI isn't available or fails, `cmd_triage` falls back to keyword matching
- **Abstracts are already in state.db:** No new data collection needed — search providers populate them at ingestion time

---

## 2. Content Validation at Download Time

**Problem:** 6 of 19 deep-read candidates (31%) had content that didn't match their metadata. src-051 (declared: IBQ-R short forms) contained Italian conference proceedings. src-758 (declared: multi-informant validity) was a gastroenterology paper. Each mismatched reader agent wasted 15-30K tokens discovering the mismatch, and gap resolution was sometimes illusory — gaps were "resolved" by sources that turned out to be wrong content.

**Solution:** After PDF→markdown conversion in `download.py`, check whether the title and/or key terms from the metadata appear in the first ~1000 characters of the converted content. If they don't, flag the source as `quality: "mismatched"` in state.db immediately. This prevents reader agents from being spawned on bad content and prevents false gap resolution.

### Design

**Implementation in `download.py`:**
- After `_convert_pdf_to_md()` or direct markdown download succeeds
- Read first 1000 chars of the content file
- Check if the source title (or significant title words) appears in the content
- If < 2 significant title words (4+ chars) appear → set `quality = "mismatched"`
- Log the mismatch to journal.md for transparency

**Triage integration:** `cmd_triage` already skips `quality: "mismatched"` sources (line 1548). No change needed.

**Why simple string matching is sufficient here:** We're not judging relevance (that's the abstract scorer's job). We're catching gross mismatches — a paper about IBD thrombosis will never contain "temperament" or "questionnaire" or "infant behavior." Simple title-word checking catches these with near-zero false positives.

---

## 3. Triage Keyword Floor Reduction

**Problem:** The triage formula `score = cite_score * (0.5 + relevance)` has a 0.5 floor, meaning papers with zero keyword relevance and high citations still get significant scores. "SPIRIT 2013" (6932 cites, 0 relevance) scores `log(6933) * 0.5 = 4.4`, beating a highly relevant paper with 50 citations.

**Solution:** Reduce the floor from 0.5 to 0.1 in `cmd_triage`. This makes the formula:
```python
score = cite_score * (0.1 + relevance)
```

With this change, a 6932-cite paper with 0 relevance scores `8.8 * 0.1 = 0.88`, while a 50-cite paper with full relevance scores `3.9 * 1.1 = 4.3`. The relevant paper wins by 5x.

**This is a one-line change** in `state.py` line 1533. Low risk, high impact. Should be done regardless of whether items 1 or 2 are implemented.

---

## 4. `recover-failed` Topical Filtering

**Problem:** `recover-failed` retries downloads for high-citation sources that failed initial download, but doesn't filter by topical relevance. In the temperament session, it pulled in papers about eating disorders, internet addiction, and COVID depression — all high-citation but completely off-topic.

**Solution:** `recover-failed` should check `relevance_score` (from item 1) or at minimum do keyword matching against the brief before attempting recovery. Skip sources with relevance_score < 0.3 or zero keyword hits.

---

## 5. `state sync-files` Command

**Problem:** `content_file` / `has_content` in state.db can get out of sync with what's actually on disk. During the temperament session, many sources showed as not having content in queries even though `.md` files existed. This made triage and reader allocation harder.

**Solution:** New `state sync-files` command that walks `sources/` and updates `content_file` in state.db for any source whose file exists on disk but isn't recorded. Also clears `content_file` for records pointing to files that no longer exist.

---

## 6. Source-Acquisition Agent Prompt Updates

**Problem:** The source-acquisition agent prompt doesn't mention relevance scoring, content validation, or the pitfalls observed in the temperament session.

**Solution:** Update `agents/source-acquisition.md` to:
- Include the `triage-relevance` step in its pipeline
- Warn about metadata-content mismatches and how to spot them
- Set a search budget (15-25 searches for initial round) to prevent the 90-search excess
- Require topical filtering before `recover-failed`

---

## 7. Gap Resolution Verification

**Problem:** In the temperament session, the source-acquisition agent reported gaps as "resolved" after downloading new sources — but those sources turned out to be metadata-content mismatches (src-758 was a gastroenterology paper) or unreadable stubs (src-840). The orchestrator called `resolve-gap` based on the agent's manifest without verifying the new sources actually contained relevant content. This created false confidence in coverage.

**Solution:** Before calling `resolve-gap`, verify that at least one newly downloaded source for that gap has:
1. Passed content validation (not flagged as `quality: "mismatched"` — see item 2)
2. A reader note confirming relevance to the gap's question

This is primarily a prompt-level change in `skills/deep-research/SKILL.md` (step 11, gap-mode). The orchestrator should not call `resolve-gap` based solely on the source-acquisition manifest. Instead: spawn readers for the new gap-mode sources first, check their coverage signals, and only then resolve gaps where a reader confirmed relevant content.

**Secondary safeguard:** The source-acquisition agent prompt (`agents/source-acquisition.md`) should be updated to caveat its gap resolution claims — report "potentially resolved (N sources downloaded)" rather than "fully resolved," since it cannot verify content quality.

---

## 8. Orchestrator Pre-Read Check

**Problem:** Even with content validation at download time, some edge cases may slip through (e.g., content that contains the title words but is actually a different paper, or garbled PDFs that happen to contain relevant words). The orchestrator currently spawns readers without any verification.

**Solution:** Add guidance in `skills/deep-research/SKILL.md` for the orchestrator to read the first 20-30 lines of each source file before spawning a reader agent. If the content is clearly off-topic, garbled, or a stub, skip it. Cost: one `Read` call per source (~trivial) vs. a full agent invocation (~20-50K tokens).

This is a prompt-level change, not a code change. Add it to the "Delegation" section of SKILL.md.

Note: With item 2 (content validation at download time) implemented, this becomes a secondary defense. But it catches edge cases that string matching misses — e.g., a paper that contains the title words but is actually a different edition or a review that merely cites the target paper.

---

## 9. Open-Access PDF Recovery via Web Search

**Problem:** The download cascade (Semantic Scholar → CORE → DOI landing page → Tavily) fails on paywalled papers from major publishers (Wiley, Elsevier, APA, Cambridge). In the temperament session, every foundational paper (Rothbart's CBQ, IBQ-R, Goldsmith's Lab-TAB, "What Is Temperament Now?") was inaccessible — despite the CBQ paper being freely hosted on Rothbart's own lab site at Bowdoin College. The pipeline never thought to look there.

**Key insight:** Authors often self-host their most-cited papers on personal websites, lab pages, or university repositories. A simple web search with the first author's name and title keywords reliably finds these copies when API-based downloads fail.

**Solution:** Add a web search fallback step to the download recovery pipeline. When a high-priority source fails the standard cascade, try:

1. `"{first author last name}" "{key title words}" PDF` — catches author lab sites, personal pages, university repositories, and project sites
2. `"{paper title}" PDF` — broad search for any hosted copy (preprint servers, institutional repositories, ResearchGate, Academia.edu, OSF, etc.)

**Note on `filetype:pdf`:** Testing showed that `filetype:pdf` works well with Tavily (found Rothbart's CBQ paper via Sci-Hub, UMD repository, and ResearchGate) but fails with WebSearch (returned zero PDF results for the same query). Since the source-acquisition agent uses Tavily via the search CLI, `filetype:pdf` is viable for this use case. Plain "PDF" as a keyword also works and is provider-agnostic.

**Tavily features we should leverage for recovery:**
- `search_depth: advanced` — deeper scraping, more likely to find actual PDFs (costs 2 credits vs. 1 for basic)
- `include_raw_content` — can verify a result is actual paper content vs. a landing page
- Currently unexposed in our CLI: `exact_match`, `time_range`, `start_date`/`end_date` — could help narrow recovery searches

**Implementation options:**

- **Option A (source-acquisition agent guidance):** Add instructions in `agents/source-acquisition.md` for the agent to run web searches (via Tavily or WebSearch) as a manual fallback for paywalled high-priority papers. The agent already has access to search tools; it just needs the prompt to try author-name searches. Low implementation cost, relies on agent judgment.

- **Option B (automated in download.py):** Add a `_try_web_search_fallback()` step in the download cascade after DOI/CORE/Tavily fail. Uses `claude -p` (Haiku) or a simple web search API call to find open-access URLs, then attempts download. More reliable but requires code changes.

- **Option C (recover-failed enhancement):** Add web search as a recovery strategy in `cmd_recover_failed`. After the standard cascade fails, try web searches for the top N highest-priority unrecovered sources. Keeps the main download path simple.

**Recommendation:** Start with Option A (prompt-only, immediate) and evaluate whether Option B or C is worth the code investment based on recovery rates.

---

## 10. Enforce Orchestrator Journal Entries

**Problem:** SKILL.md says to use journal.md "aggressively" for persistent memory across context compressions, but the guidance is vague and easily ignored. In the temperament session, zero orchestrator-level journal entries were written. If context compression had kicked in, the orchestrator would have lost all reasoning traces — what was tried, what worked, coverage assessments, synthesis strategy.

**Solution:** Strengthen the journal guidance in `skills/deep-research/SKILL.md` with specific trigger points where journal entries are mandatory:

1. **After brief is set:** Log the research questions and initial search strategy
2. **After source-acquisition returns:** Log the manifest summary — source counts, coverage assessment, identified gaps
3. **After readers complete:** Log coverage analysis — which questions have strong vs. thin evidence, emerging patterns, contradictions between sources
4. **After gap-mode returns:** Log what was resolved, what remains open, synthesis strategy
5. **Before synthesis handoff:** Log the narrative key findings summary that will be given to the writer

Each entry should be 3-5 lines, not paragraphs. The goal is breadcrumbs for a compressed context, not a narrative log.

**This is a prompt-only change** in SKILL.md. No code changes needed.
