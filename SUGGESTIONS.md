# Improvement Suggestions from Uncanny Valley Session Reflection

Session: `deep-research-uncanny-valley/` (March 2026)
Overall score: 7.4/10 — Good

---

## Tier 1: High-Impact Process Improvements

### 1. Enforce systematic citation chasing after round 1

**Problem:** Only 1 `--references` search and 1 failed `--cited-by` search were run out of 16 total searches. Citation chasing is described in SKILL.md as "the highest-value search strategy available" but was barely used. The `--cited-by` on Kätsyri 2015 (438 citations) returned 0 results and was never retried or investigated.

**Why it matters:** Citation networks have higher precision than keyword search. A paper citing Kätsyri (2015) is almost certainly about the uncanny valley; a keyword match for "uncanny valley cross-cultural" pulls in food science and music theory (both appeared in this session). Underusing citation chasing means relying on noisier keyword searches to fill the same role.

**Suggested fix:** Add a structured checkpoint after round 1 search results are reviewed. The agent should:
1. Identify 3-5 highest-impact papers (by citation count × relevance)
2. Run `--references PAPER_ID --limit 10` on each (5 searches minimum)
3. Run `--cited-by PAPER_ID --min-citations N --limit 10` on the 2-3 most foundational
4. Run `--recommendations PAPER_ID --limit 10` on at least 1 key paper

This should produce 8-15 citation traversal searches, not 1-2. Consider adding a SKILL.md guardrail: "If fewer than 3 citation traversal searches have been run after round 1, pause and run them before proceeding to downloads."

**Possible implementation:** Add a `state citation-chase-check` command that compares the number of references/cited-by searches against the number of high-citation sources and warns if the ratio is low.

### 2. Triage before downloading, not after

**Problem:** `triage --top 30` was run but its output wasn't used to prioritize downloads. Instead, all 273 sources were batch-downloaded, resulting in 10 download loop iterations where the last 6 produced 0-1 new downloads each. 85% of sources (232) were never downloadable.

**Why it matters:** Each download batch takes 30-60 seconds of subprocess time. Running 10 batches on 273 sources when only ~40 were ever going to succeed wasted ~5 minutes. More importantly, the triage ranking wasn't used to prioritize *which* sources to attempt first, meaning high-priority paywalled papers got the same treatment as low-relevance ones.

**Suggested fix:** Restructure the download workflow in SKILL.md:
1. Run `triage --top 30` immediately after search rounds complete
2. Download only high+medium priority sources first (`download-pending` should accept a `--priority high,medium` filter, or sources should be downloaded by ID)
3. After priority downloads complete, assess: are gaps still open? If yes, attempt remaining sources. If no, skip.
4. For high-priority sources that failed download, run `recover-failed` and consider `--provider core` searches

**Possible implementation:** Add `--priority` flag to `download-pending` that filters by triage tier. Or add a `download-triaged` command that only downloads sources above a threshold score.

### 3. Add reader-level fact-checking for quantitative claims

**Problem:** The reader agent for src-027 (Diel & MacDorman 2021) reported "680 participants, 6,800 ratings" when the actual study had 136 participants (yielding 1,360 ratings in a within-subjects design). This 5x inflation propagated through findings logging, the draft report, and was only caught by the verifier agent — the last line of defense.

**Why it matters:** Quantitative claims (sample sizes, effect sizes, percentages) are the most verifiable and most consequential facts in a research report. A reader who spots an inflated N will question the entire report's credibility. The error likely arose from the reader agent misinterpreting a table or confusing total data points with participants.

**Suggested fix:** Update the reader agent prompt (`agents/research-reader.md`) to include:
- "For key quantitative claims (sample sizes, effect sizes, p-values), cross-check by reading the Methods section directly. Do not rely on abstract or results-section summaries alone."
- "Flag any numbers that seem unusually large or precise in a `## Claims to Verify` section of the note, so downstream agents can prioritize fact-checking."

**Possible implementation:** Add a `claims_to_verify` field to the reader manifest return value. The supervisor can then pass these to the verifier agent as priority targets.

---

## Tier 2: Moderate-Impact Process Improvements

### 4. Run CORE searches when download rates are low

**Problem:** The download success rate was 15% (41/273). The SKILL.md recommends CORE ("indexes 46M+ hosted full texts from institutional repositories") when many sources are paywalled, but no CORE searches were run.

**Why it matters:** Many psychology papers that fail the DOI cascade (Unpaywall → arXiv → PMC → Anna's Archive → Sci-Hub) have open-access versions in institutional repositories that CORE indexes. Running the same queries through CORE after round 1 could recover 5-15 additional full texts.

**Suggested fix:** Add a download-rate checkpoint: after the first download batch, if success rate is below 30%, automatically suggest CORE searches for the top queries. Consider adding this to the SKILL.md workflow as a conditional step.

### 5. Improve gap-resolution search quality

**Problem:** The 4 round-2 searches for Q5 (individual differences) were poorly targeted. Semantic Scholar returned "Encyclopedia of human behavior" and "Autism Spectrum Disorders in Iran" for "uncanny valley individual differences personality autism cross-cultural". PubMed returned 0 results for a similarly broad query.

**Why it matters:** Gap resolution searches that return off-topic results waste a search slot and create a false sense of "we tried." The SKILL.md says to use "terminology from the relevant papers" — but the agent used generic terms instead of field-specific vocabulary discovered in round 1.

**Suggested fix:** The `gap-search-plan` command already generates suggested queries, but it was run after the gap searches, not before. Reorder the workflow: run `gap-search-plan` first, then execute its suggestions. Additionally, gap-resolution queries should use specific terminology from already-read papers (e.g., "uncanny valley autism configural processing" rather than "individual differences personality autism cross-cultural").

### 6. Improve triage command output format

**Problem:** The `triage` command's `top_sources` field returns a list of source ID strings without metadata. The agent had to run separate `get-source` calls to understand what was triaged, adding unnecessary round-trips.

**Suggested fix:** Have `triage` return objects with `{id, title, citation_count, tier, score}` instead of bare ID strings. This lets the agent make download/read priority decisions from a single command output.

### 7. Write more substantive journal entries

**Problem:** The journal is 1,344 words but ~80% is auto-generated search logs. The manually written assessment section is about 300 words — one entry covering the entire session. The SKILL.md recommends entries "at natural decision points: after each search round, after reading key papers, when you notice a pattern or contradiction."

**Why it matters:** In longer sessions, context compression erases reasoning traces. The journal is the only artifact that survives compression. A thin journal means the agent loses track of strategy decisions, emerging patterns, and dead ends.

**Suggested fix:** Add structured checkpoints to the SKILL.md workflow where journal entries are required (not optional):
1. After round 1 searches complete: assessment of what was found
2. After reader agents complete: emerging patterns and contradictions
3. After gap resolution: what was tried and what remains
4. Before synthesis handoff: coverage summary and key tensions

Consider adding a `journal-check` command that warns if the journal has fewer than N manually-written entries.

---

## Tier 3: Lower-Priority Improvements

### 8. Investigate `--cited-by` reliability for highly-cited papers

**Problem:** `--cited-by` on Kätsyri 2015 (438 citations) returned 0 results despite the `--min-citations 20` filter. The journal logged this search but the agent didn't investigate or retry.

**Suggested fix:** Add error handling guidance to SKILL.md: "If `--cited-by` returns 0 results for a paper with >100 known citations, retry without `--min-citations` filter, or try the same paper on a different provider (OpenAlex also supports citation traversal)." Consider adding a warning in the search CLI when cited-by returns 0 for a paper with known high citation count.

### 9. Track secondary-source citation chains

**Problem:** Mitchell et al. (2011) is cited throughout the report for cross-modal mismatch findings, but was never directly read — it's cited only via the de Borst & de Gelder review (src-076). The report flags this, but the synthesis-reviewer had to catch it manually.

**Suggested fix:** Add a `source_type` or `citation_chain` field to findings. When a finding cites a source that itself cites another paper for the claim, the finding should note the chain depth. The audit command could then flag "findings with chain depth > 1" as needing primary verification.

### 10. Streamline PubMed two-step workflow

**Problem:** PubMed search returns only PMIDs, requiring a separate `--fetch-pmids` call with all IDs as arguments. The initial attempt failed because `--fetch-pmids` expected explicit PMID arguments. This two-step process is more fragile than single-step providers.

**Suggested fix:** Add a `--fetch` flag to PubMed searches that automatically fetches metadata for returned PMIDs in a single call (this may already exist as `--fetch` based on the search CLI help). If not, consider making metadata fetch the default behavior for PubMed searches, since PMIDs without metadata aren't useful for triage.

---

## Bugs Observed

| Issue | Severity | Details |
|-------|----------|---------|
| `--cited-by` 0 results for 438-citation paper | Medium | S2 API may have reliability issues for highly-cited papers, or `--min-citations` filter applied before results were fetched |
| Reader agent inflated participant count 5x | Medium | src-027 notes say "680 participants" when paper has 136. Likely confused total ratings with participants |
| `triage` output format unhelpful | Low | Returns bare source IDs instead of objects with metadata |
| PubMed `--fetch-pmids` argument format | Low | Required explicit PMID list as positional args; initial call failed |
