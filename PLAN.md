# Deep Research Improvement Plan

Based on the uncanny valley session reflection and SUGGESTIONS.md. Organized by impact-to-effort ratio.

---

## Tier 1: High impact, low effort

### 1. PubMed auto-fetch metadata

**Problem:** `_keyword_search` and `_mesh_search` in `pubmed.py` default to returning bare PMIDs (`{pmid, url}`) — no title, abstract, or DOI. When `search.py:_add_sources_to_state` filters for `item.get("title")`, these all get silently dropped. This caused 51 PubMed results to vanish in the uncanny valley session.

**Fix:** Default `--fetch` to `True` when a session is active (i.e., `args.session_dir` is set or auto-discovered). The `_efetch_papers` implementation already exists and returns full metadata — it's just gated behind an opt-in flag. When no session is active, keep the current behavior (bare PMIDs are fine for standalone queries).

**Files:** `skills/deep-research/scripts/providers/pubmed.py`

**Why:** Without metadata, PubMed sources can't be triaged, prioritized, or downloaded. This is a silent data loss bug, not a feature gap.

### 2. Crossref sort without subject warning

**Problem:** `--sort is-referenced-by-count` without `--subject` returns highly-cited papers from unrelated fields (physics, management). The uncanny valley session journal noted these as "garbage."

**Fix (code):** In the Crossref provider, emit a warning log when `--sort is-referenced-by-count` is used without `--subject`. Don't block the query — just make the issue visible.

**Fix (guidance):** Add to SKILL.md provider table or search guidance: "Always pair `--sort is-referenced-by-count` with `--subject` to avoid cross-discipline contamination."

**Files:** `skills/deep-research/scripts/providers/crossref.py`, `skills/deep-research/SKILL.md`

### 3. Download batch IndexError guard

**Problem:** The download batch loop hits an `IndexError` when the remaining-sources list is empty. JSON parsing also fails on some batches due to stderr/stdout mixing.

**Fix:** Add a guard in `state.py`'s `download-pending` handler for empty source lists before indexing. Review the batch loop for edge cases where all sources in a batch fail and the list is exhausted mid-iteration.

**Files:** `skills/deep-research/scripts/state.py`

---

## Tier 2: Medium impact, medium effort

### 4. Gap resolution as a real search round

**Problem:** The gap→search→resolve cycle was perfunctory in practice. Two gaps were logged, briefly searched (one query each), and resolved as "genuine literature gaps." The agent needs concrete search actions, not just a warning.

**Fix (guidance):** Strengthen SKILL.md step 13 (pre-report gap checkpoint):
- "For each open gap, run at least 2 targeted searches: one keyword query using terminology from the relevant papers, and one citation chase on the most gap-relevant paper."
- "A gap resolved after only 1 search query is suspicious — the default assumption should be that more searching is needed, not that the literature is empty."
- "If a gap genuinely can't be resolved (sparse literature), the journal entry must cite specific failed search strategies, not just assert the gap exists."

**Optional (code):** Add a `state gap-search-plan` command that reads open gaps + brief questions and outputs suggested search queries. Low priority — the guidance change is the main lever.

**Files:** `skills/deep-research/SKILL.md`, optionally `skills/deep-research/scripts/state.py`

### 5. Citation chasing guidance improvements

**Problem:** `--cited-by` returns recency-biased results. For foundational papers with hundreds of citations, this surfaces tangential recent work rather than the substantive research network.

**Fix (guidance):** Add to SKILL.md citation chasing section:
- "Prefer `--references` for foundational papers (high-precision, author-curated bibliography). The original paper's reference list is a domain expert's reading list."
- "Use `--cited-by` for recent papers where you want to find who built on them."
- "For foundational papers with 200+ citations, `--cited-by` without filtering returns noise. Prefer `--references` or use `--cited-by` with manual triage of results by citation count."

**Optional (code):** Add `--min-citations N` filter to the Semantic Scholar provider's `--cited-by` mode. S2 API returns `citationCount` per result — this is a client-side filter, trivial to implement.

**Files:** `skills/deep-research/SKILL.md`, optionally `skills/deep-research/scripts/providers/semantic_scholar.py`

### 6. Citation-weighted reader allocation

**Problem:** Reader agents were allocated somewhat arbitrarily. Low-citation recent papers got reads while potentially useful mid-citation papers were skipped.

**Fix (guidance):** Add to SKILL.md after the download step:
- "After downloads complete, triage sources for reading. Prioritize by: (a) citation count — highly-cited papers are more likely to be substantive; (b) title relevance — does the title contain keywords from a brief question?; (c) recency for the topic — a 2024 paper with 5 citations may be more relevant than a 2010 paper with 50 if the field has evolved."
- "Allocate readers to the top 15-20 sources by this ranking. Papers with <5 citations, no keyword match to brief questions, and not filling a specific gap are low priority."
- "Check `quality` field in source metadata before spawning readers — skip sources with `quality: 'mismatched'` or `quality: 'degraded'`. The content mismatch detector runs at download time and flags wrong-PDF downloads."

**Files:** `skills/deep-research/SKILL.md`

**Why this is guidance, not code:** The ranking heuristic is simple enough for the agent to apply from metadata already in state.db. Building a scoring command would over-engineer a judgment call.

### 7. Synthesis handoff improvements

**Problem:** The supervisor summarizes findings for the writer, but this compressed summary may lose detail. The writer should see both the narrative summary and the structured findings.

**Fix (guidance):** Update SKILL.md step 15a:
- "Include the raw `state summary` JSON output (or at least the findings array with source citations) in the writer handoff, alongside your narrative summary."
- "The writer should see: (1) research brief, (2) structured findings from `log-finding` entries with their source IDs, (3) gap analysis, (4) audit stats. The structured findings are the evidence backbone — don't compress them into a paragraph."

**Files:** `skills/deep-research/SKILL.md`

---

## Tier 3: Nice-to-have / longer-term

### 8. Metadata triage step

**Problem:** The search-to-read funnel is extremely lossy. 171 sources tracked → 74 downloaded → 18 deep reads → 17 usable. ~56 downloads were wasted.

**Fix (code):** Add a `state triage` command that presents sources sorted by `citation_count × title-keyword-relevance` and lets the agent mark priorities before downloading. Only download tagged sources.

**Fix (guidance):** Add a triage step between search and download in SKILL.md: "After search rounds complete, review the top ~50 sources by citation count. Mark the top ~25 as read-worthy before downloading. Skip sources with off-topic titles or zero citations unless they fill a specific gap."

**Files:** `skills/deep-research/scripts/state.py`, `skills/deep-research/SKILL.md`

**Why deferred:** The triage heuristic needs design work. What counts as "title-keyword-relevance"? The `check_content_mismatch` function has keyword extraction logic that could be reused, but the scoring model needs thought. The guidance change alone provides most of the value.

### 9. Failed source recovery

**Problem:** After `download-pending --auto-download` reports failures, high-priority papers (high citation count, directly relevant) are just skipped. For important sources, alternative channels exist.

**Fix (code):** Add a `download --recover-high-priority` flag that:
1. Identifies failed sources with `citation_count > 50` and title relevance to brief questions
2. Tries CORE search by title (institutional repository versions)
3. Tries Tavily search for `"paper title" pdf` (preprint servers, author pages)
4. Falls back to downloading the DOI landing page as a web source (at least get abstract + visible text)

**Files:** `skills/deep-research/scripts/download.py`, `skills/deep-research/scripts/state.py`

**Why deferred:** The existing DOI cascade already covers 6 sources. The recovery step is a second-pass strategy that helps in specific cases (paywalled high-value papers). Worth building, but after the higher-impact items.

### 10. Structured search journaling

**Problem:** Journal entries are free-text and depend on the agent remembering to write them. During long sessions, context compression erases reasoning traces. 27 lines for a 182-source session is sparse.

**Fix (code):** Auto-append a structured journal entry after each search round in `search.py`: provider, query, result count, top 3 result titles, one-line assessment. Append to `journal.md` in the session directory.

**Fix (guidance):** Strengthen journaling guidance in SKILL.md with a template:
```
## Search: {provider} — "{query}" ({N} results)
Top results: {title1}, {title2}, {title3}
Assessment: {one-line: relevant/partially relevant/off-topic, key finding, next step}
```

**Files:** `skills/deep-research/scripts/search.py`, `skills/deep-research/SKILL.md`

**Why deferred:** The code change risks cluttering journal.md with boilerplate if the agent also writes manual entries. The guidance template is the safer first step.

---

## Already done (verify only)

### Content mismatch detection at download time

`check_content_mismatch` in `quality.py` runs at `download.py:756-770` after PDF conversion. Sets `quality: "mismatched"` when title keywords and author surnames are absent from extracted text. This is working — the uncanny valley session's src-001/src-011 issue was that readers were spawned before checking quality. The fix is in reader allocation guidance (#6 above): "Check `quality` field before spawning readers."

### Reader agent quality check

Add to `agents/research-reader.md`: "Before reading, check the source metadata's `quality` field. If `quality` is `mismatched` or `degraded`, note this in the summary and don't treat the content as authoritative for the stated paper." This is a small agent prompt change bundled with #6.
