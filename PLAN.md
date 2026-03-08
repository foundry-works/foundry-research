# Plan: SKILL.md Improvements from Uncanny Valley Reflection

## Context

The `deep-research-uncanny-valley/REFLECTION.md` evaluation (6.5/10) identified six systematic issues where the agent underused state management tools, searched too broadly, and skipped web sources. All six are addressable through SKILL.md guidance changes — no code changes required.

## Target File

`skills/deep-research/SKILL.md`

---

## Change 1: Mandate brief questions in workflow step 2

**Problem:** Agent had research questions (Q1-Q6) in its reasoning but never persisted them via `set-brief`. The `questions` field was `[]` despite findings referencing Q1-Q6.

**Root cause:** Step 2 says "Draft research brief → set-brief" but doesn't specify that the questions array is mandatory or show what good questions look like.

**Change:** Expand step 2 in the Quick-Start Workflow to explicitly require 3-7 concrete research questions in the brief JSON. Add an inline example showing the expected `set-brief` JSON structure with a `questions` array.

**Location:** Lines 16-17 (Quick-Start Workflow, step 2)

---

## Change 2: Add post-synthesis gap-check step

**Problem:** Zero gaps logged despite Q4 having no coverage at all. The agent never called `log-gap`.

**Root cause:** `log-gap` is mentioned in the tools reference and in "Completion signals" but there's no workflow step that prompts the agent to check for gaps.

**Change:** Add a step between current steps 8 and 9 (after logging findings, before audit) that says: review each research question — if any has < 2 supporting sources, call `log-gap`. Also strengthen the "Structured coverage tracking" paragraph to make gap-logging a required practice, not optional.

**Location:** Lines 22-23 (Quick-Start Workflow, steps 8-9), lines 163-164 (Structured coverage tracking paragraph)

---

## Change 3: Reader subagents must call `mark-read`

**Problem:** 11 sources had reader notes in `notes/` but `is_read` was 0 for all 87 sources. The flag was never updated.

**Root cause:** The Delegation section describes what reader subagents do (read paper, write summary to `notes/`) but never instructs them to call `mark-read`.

**Change:** In the Delegation section's source summarization bullet, add that after writing the note to `notes/src-NNN.md`, the reader subagent must also call `mark-read --id src-NNN`. Add `mark-read` to the reader subagent's tool list. Alternatively, instruct the main agent to call `mark-read` for each source after confirming its note file exists.

**Decision:** Have the main agent do it after reader subagents return, since subagents may not have session context. Add a post-reader step: "After all reader subagents complete, call `mark-read` for each source that now has a note in `notes/`."

**Location:** Lines 218-223 (Delegation section, source summarization), and add a step 7.5 in Quick-Start Workflow after reader spawning.

---

## Change 4: Query specificity guidance to prevent off-topic contamination

**Problem:** Queries like "cross-cultural differences individual variation" pulled in food science and emotional regulation papers (20+ off-topic sources out of 87).

**Root cause:** SKILL.md says "narrow based on what emerges" but doesn't warn about generic queries or high result counts.

**Change:** Add a "Search Query Crafting" subsection to the "What Good Research Looks Like" section with three rules:
1. Always include the core topic term in every query (e.g., "uncanny valley cross-cultural" not "cross-cultural differences individual variation")
2. If a search returns >500 results, the query is too broad — add qualifying terms
3. After each search round, spot-check the last few results for relevance — if off-topic, the query needs tightening

**Location:** After the "Iterative search across multiple providers" paragraph (after line 141)

---

## Change 5: Prompt for web source consideration

**Problem:** Topic (uncanny valley) had significant non-academic coverage but no web sources were searched. 71% provider concentration on Semantic Scholar.

**Root cause:** The workflow steps mention web search (step 4) but don't prompt the agent to evaluate whether the topic warrants web sources. Easy to skip.

**Change:** Add a sentence to step 3/4 in the workflow: "Before searching, consider: does this topic have significant non-academic coverage (blogs, news, industry reports, Wikipedia)? If yes, plan at least one web search round." Also add to Provider Selection Guidance a heuristic: "When unsure, search at least 3 providers including one web source."

**Location:** Lines 17-18 (Quick-Start Workflow, steps 3-4), lines 170-184 (Provider Selection Guidance)

---

## Change 6: Default search limit guidance

**Problem:** Search efficiency was 1.4% — 87 sources tracked from 6,168 total results. Individual searches returned 1,000-2,000+ results.

**Root cause:** No guidance on `--limit` values. Agent used provider defaults, which can return thousands.

**Change:** Add limit guidance to the Search tool section and to the "Iterative search" paragraph:
- Initial broad search: `--limit 50` (enough to find key papers)
- Targeted follow-up: `--limit 20`
- Citation/reference traversal: `--limit 10`
- Note: OpenAlex and Semantic Scholar default limits can be very high — always set `--limit` explicitly

**Location:** Lines 45 (Common flags), and the "Iterative search across multiple providers" paragraph (line 140)
