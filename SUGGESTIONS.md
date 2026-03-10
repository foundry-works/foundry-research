# Deep Research Process — Improvement Suggestions

Observations from an uncanny valley research session (2026-03-10). These are process-level improvements, not topic-specific.

## High Impact

### 1. Add a metadata triage step between search and download

**Problem:** The search-to-read funnel is extremely lossy. In this session: 171 sources tracked → 74 downloaded → 18 deep reads → 17 usable. ~56 downloads were wasted effort.

**Suggestion:** After search rounds, scan titles/abstracts of the top ~50 sources and tag ~25 as "read-worthy" before downloading. Only download tagged sources. This could be a new `state triage` command that presents sources sorted by (citation_count × title-relevance) and lets the agent mark priorities, or an automated relevance scorer that checks title keywords against brief questions.

**Why it matters:** Each download batch takes 30-60 seconds. Cutting 56 unnecessary downloads saves ~10 minutes and keeps the source list focused for reader allocation.

### 2. Content verification at download time

**Problem:** Two sources (src-001, src-011) had wrong PDFs — metadata said one paper, downloaded content was a completely different document. This wasn't detected until reader agents wasted time on them.

**Suggestion:** After PDF-to-markdown conversion, check whether the first ~500 characters of the markdown contain at least one significant keyword from the source title (excluding stopwords). If not, flag the source as `quality: "content_mismatch"` in state.db and skip it in subsequent steps. This could be a post-conversion hook in `download.py`.

**Complexity:** Low. Title keywords are already in state.db; the check is a string match, not NLP.

### 3. Make gap resolution a real search round

**Problem:** The gap → search → resolve cycle was perfunctory in practice. Two gaps were logged, briefly searched (one query each), and resolved as "genuine literature gaps" — but more aggressive searching (CORE for open-access versions, Google Scholar via Tavily, citation chasing on the gap-relevant papers) might have improved coverage.

**Suggestion:** The `state audit` output could include a "gap search plan" — for each open gap, suggest 2-3 specific search queries or citation-chase targets. The SKILL.md already says gaps should block synthesis, but the agent needs concrete search actions, not just a warning. Alternatively, a `state gap-search-plan` command could auto-generate suggested queries from gap text + brief questions.

**Why it matters:** Gap resolution is where the process is supposed to be *iterative*, but time pressure and context fatigue make it the most likely step to be shortcut. Structural support (suggested queries, minimum search count per gap) would enforce rigor.

### 4. Improve PubMed source ingestion

**Problem:** PubMed returns PMIDs without metadata by default. Sources entered state.db with no titles, abstracts, or DOIs — making them impossible to triage, prioritize, or download meaningfully. The `--fetch-pmids` flag requires an explicit PMID list, creating a clunky two-step workflow.

**Suggestion:** Have `search --provider pubmed` automatically fetch metadata (title, abstract, DOI, authors, year) for all returned PMIDs before adding to state. This matches how other providers (S2, OpenAlex) work — they return rich metadata inline. The EFetch API call is cheap and could be batched.

**Complexity:** Medium. Requires adding an EFetch call after ESearch in the PubMed provider code. The `--fetch-pmids` flag already has the implementation; it just needs to be auto-triggered.

## Medium Impact

### 5. Smarter citation chasing

**Problem:** `--cited-by` returns recency-biased results (most recent citers first). For mature papers with hundreds of citations, this surfaces tangential 2025-2026 papers (metaverse, virtual influencers) rather than the substantive research network.

**Suggestions:**
- **Default to `--references` over `--cited-by`** for foundational papers — the original paper's bibliography is curated by domain experts and has higher precision.
- **Add a `--min-citations` filter to `--cited-by`** — a citing paper with 50+ citations is more likely to be a substantial contribution than one with 0. S2 API returns citation counts; filtering client-side is trivial.
- **Document the tradeoff in SKILL.md:** "Use `--references` for foundational papers (high-precision, author-curated). Use `--cited-by --min-citations 10` for finding the active research network. Use `--recommendations` only for niche papers where keyword search is failing."

### 6. Citation-weighted reader allocation

**Problem:** Reader agents were allocated somewhat arbitrarily. A few low-citation recent papers got reads while potentially useful mid-citation papers were skipped.

**Suggestion:** After downloads complete, rank sources by `citation_count × relevance_score` (where relevance_score could be as simple as: does the title contain a brief keyword? +1 per keyword match). Read the top N. The SKILL.md could include guidance like: "Allocate readers to the top 15-20 sources by citation-weighted relevance. Papers with <5 citations and no direct keyword match to a brief question are low priority unless they fill a specific gap."

**Why it matters:** Deep reads are the most expensive step (each reader agent takes 30-50 seconds). Allocating them to the highest-value sources improves the evidence base without increasing cost.

### 7. The synthesis handoff loses information

**Problem:** The supervisor summarizes findings for the writer, but this summary is compressed and may lose detail from the actual `log-finding` entries. The writer then reads notes/ independently, potentially missing the structured findings.

**Suggestion:** Include the raw `state summary` output (or at least the findings array) in the synthesis handoff. The writer should see both the supervisor's narrative summary *and* the structured findings with their source citations. Alternatively, the writer could run `state summary` directly — but this requires the writer agent to have Bash access.

### 8. Degraded/paywalled source recovery

**Problem:** After `download-pending --auto-download` reports failed sources, the process moves on. For high-priority papers (high citation count, directly relevant to a brief question), this means potentially missing key evidence.

**Suggestion:** After the first download pass, identify failed sources with citation_count > 50 and title relevance to brief questions. For these, try:
1. CORE provider search by title (institutional repository versions)
2. Tavily search for the paper title + "pdf" (preprint servers, author pages)
3. Download the DOI landing page as a web source (at least get the abstract + any visible text)

This could be a `download --recover-high-priority` flag that auto-identifies and retries important failed sources through alternative channels.

## Low Impact / Nice to Have

### 9. Crossref provider needs better defaults

**Problem:** Crossref search for "uncanny valley review" sorted by `is-referenced-by-count` returned physics and management papers — completely off-topic. Crossref's full-text search is too broad without subject filtering.

**Suggestion:** When using Crossref with `--sort is-referenced-by-count`, require a `--subject` filter or warn that results will be dominated by highly-cited papers from unrelated fields. Alternatively, default Crossref searches to `--sort relevance` rather than allowing citation sorting without subject constraint.

### 10. Search round journaling could be more structured

**Problem:** Journal entries are free-text and depend on the agent remembering to write them. During long sessions, context compression erases reasoning traces, and journal entries become the only persistent memory.

**Suggestion:** Auto-append a structured journal entry after each search round: provider, query, result count, top 3 titles, and a one-line assessment. This could be a post-search hook in the search tool, or a `state journal-search` command that formats the entry from the search log.

### 11. Parallel download resilience

**Problem:** The download batch loop hit an `IndexError` partway through, requiring manual recovery. JSON parsing also failed on some batches due to stderr/stdout mixing.

**Suggestion:** The download loop in SKILL.md should recommend capturing output to a variable and checking exit code before parsing, rather than piping directly to python. The `download.py` batch logic should also handle empty remaining-sources lists more gracefully (the IndexError came from an empty list access).
