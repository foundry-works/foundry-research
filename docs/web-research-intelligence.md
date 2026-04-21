# Web Research Intelligence Mode

`foundry-research` is strongest when the user's question behaves like an academic literature review: the evidence is relatively stable, source quality maps to papers and citations, and deep reading a bounded set of full-text PDFs produces durable synthesis.

Many useful research questions do not behave that way. They are web-native, current, operational, or institution-specific. The important evidence may live in documentation sites, changelogs, standards pages, support articles, government pages, trust centers, model cards, benchmark leaderboards, advisories, company pages, GitHub repositories, issue trackers, practitioner writeups, community discussion, and news archives.

The current pipeline can search those sources, but it still tends to evaluate and synthesize them with academic defaults. That creates predictable failure modes:

- Search snippets and secondary summaries can be treated as evidence instead of leads to verify.
- Fast-changing facts such as version names, feature availability, policy terms, benchmark scores, dates, prices, certifications, or deprecation timelines can go stale during or soon after a report.
- Citation bundles can obscure which source supports which exact claim.
- Source count can overstate coverage when many pages repeat the same underlying fact.
- Domain structure can be missed: the most relevant evidence may be several clicks deep inside docs, changelogs, release notes, FAQs, or policy pages that a keyword search only partially surfaces.

The goal of web research intelligence mode is not "market research." Market and competitive intelligence is one subtype. The broader goal is to let the system investigate current web evidence with the same rigor it brings to academic evidence.

## Current Web Provider Use

The web provider integrations are useful, but shallow relative to what the providers now expose.

### Perplexity

Current implementation:

- Uses Perplexity Search API through `skills/deep-research/scripts/providers/perplexity.py`
- Calls `POST /search`
- Stores title, URL, snippet, date-derived year, and basic filters

Not currently used:

- Sonar answer models
- Citation-grounded answer generation
- Search-context-size control
- Synthesized answer plus cited result set as a first-pass source discovery artifact

For web research intelligence, Sonar-style queries could be useful for discovery questions like "what official sources should be checked for this policy?" or "which pages document this feature change?" The generated answer should not be cited directly as final evidence, but its citations and search results can guide targeted extraction from primary sources.

### Tavily

Current implementation:

- Uses Tavily Search via `POST /search`
- Supports `--search-depth basic|advanced`
- Supports `--topic general|news`
- Supports domain filters
- Supports Tavily Extract via `--urls`, calling `POST /extract`
- Supports `--extract-depth basic|advanced`
- Supports optional raw content inclusion

Not currently used:

- Tavily Crawl via `POST /crawl`
- Tavily Map
- Crawl instructions for site-specific discovery
- Query-reranked extraction chunks
- Structured crawling of documentation sites, policy pages, changelog sections, support centers, or other multi-page evidence domains

For web-native questions, Tavily Crawl is likely more important than more keyword searches. A keyword search can find many summaries; a crawl of the authoritative domain can collect the actual pages that should support the claim.

### Exa

Current implementation:

- Uses Exa Search through `skills/deep-research/scripts/providers/exa.py`
- Calls `POST /search`
- Supports `--exa-type auto|neural|fast|instant`
- Supports category filters such as `company`, `research paper`, `news`, `tweet`, `personal site`, `financial report`, and `people`
- Supports domain, date, and text filters
- Can request highlights with `--include-highlights`

Not currently used:

- Exa Contents API for full text, highlights, summaries, freshness control, and subpage crawling
- Exa Answer API for answer-plus-citations discovery
- Exa Research API for structured research outputs with citations
- Find-similar workflows from a known authoritative page
- Deep search modes or structured output workflows

For web research intelligence, Exa is especially useful for finding semantically related pages and extracting dense highlights. It should be treated as more than a ranked-link provider: search can identify candidate sources, contents can extract evidence from those sources, and answer/research modes can act as discovery layers whose citations are then verified directly.

### Linkup

Current implementation:

- Uses Linkup Search through `skills/deep-research/scripts/providers/linkup.py`
- Calls `POST /search` with `outputType: "searchResults"`
- Supports `--depth fast|standard|deep`
- Supports domain and date filters
- Supports Linkup Fetch via `--urls`, calling `POST /fetch`

Not currently used:

- `outputType: "sourcedAnswer"`
- `outputType: "structured"` with a JSON schema
- Inline citations
- Source inclusion for structured outputs
- Async Linkup Research tasks via `POST /research` and result polling

For web research intelligence, Linkup's value is not just web search. Its agentic `deep` mode and sourced or structured outputs could help answer focused web questions while preserving source provenance. The system should still verify final claims against fetched or extracted source pages rather than citing generated answers directly.

### GenSee

Current implementation:

- Uses GenSee search through `skills/deep-research/scripts/providers/gensee.py`
- Calls the search endpoint with `mode: evidence|digest`
- Stores title, URL, and returned content

Not currently used:

- Thinking/reasoning-based web retrieval mode
- Direct-answer synthesis with references
- Visited URL lists or explicit crawl traces
- Multilingual search behavior
- Deep-crawl/validated-reference outputs described in GenSee's API materials

For web research intelligence, GenSee is closer to a high-level search agent than a low-level search API. Its answer and reasoning modes may be useful for hard discovery problems, especially when the answer requires several searches or browsing steps. As with Sonar, Exa Answer, or Linkup sourced answers, generated answers should be used to discover and prioritize sources, not as primary evidence without verification.

## Desired Mode Split

The pipeline should classify the research type before acquisition:

| Mode | Evidence shape | Primary retrieval pattern |
|------|----------------|---------------------------|
| Academic literature review | Papers, citation graphs, methods/results sections | Academic providers, citation chasing, PDF download |
| Web research intelligence | Docs, policies, changelogs, advisories, standards, support pages, official statements | Web search, crawl/extract, source authority checks |
| Technical ecosystem scan | Docs, repos, issues, benchmarks, model cards, implementation reports | GitHub, web crawl/extract, benchmark sources, community sources |
| Financial/company research | Filings, earnings materials, investor pages, market data, analyst context | EDGAR, yfinance, official investor relations, web |
| Community/practitioner scan | Forums, issues, HN/Reddit, blogs, case studies, field reports | GitHub, HN, Reddit, web extract |

A production LLM model comparison belongs in web research intelligence with a technical ecosystem flavor. It is not primarily an academic literature review, even when some academic sources are relevant.

## Web Research Workflow

Recommended flow:

1. **Define a source authority ladder.** For each claim type, identify preferred sources before searching.
   - Product or API behavior: official docs, API references, changelogs, model cards
   - Policy or legal terms: official policy pages, terms of service, regulatory pages, trust centers
   - Security/compliance: trust centers, audit/certification pages, advisories, government or standards-body material
   - Technical performance: original benchmark leaderboards, model cards, reproducible eval reports, independent evals with methodology
   - Operational reliability: status pages, incident reports, release notes, issue trackers
   - Adoption or field experience: case studies, practitioner reports, GitHub issues, HN/Reddit, with explicit source-quality caveats

2. **Use broad web search for discovery.** Search should identify candidate domains and pages, not settle claims.

3. **Crawl or extract authoritative domains.** Once the likely source domain is known, use crawl/extract to collect the relevant subtree instead of relying on snippets.

4. **Extract structured facts before synthesis.** Build tables or records before prose:
   - claim text
   - source URL
   - source type and authority tier
   - retrieved date
   - published or last-updated date when available
   - quoted or extracted support
   - volatility level
   - conflicts or caveats

5. **Represent conflicts explicitly.** If sources disagree, keep both with dates and provenance until a higher-authority source resolves the conflict.

6. **Use claim-specific citations.** Every current factual claim should trace to the exact page or extracted row that supports it. Avoid citation bundles for volatile claims.

7. **Make freshness visible.** The final report should say "checked on YYYY-MM-DD" for volatile sections and should separate durable analysis from current web facts.

8. **Run specialist verification.** For web-heavy topics, reviewers should check source authority, freshness, quoted support, and whether secondary sources were improperly treated as primary evidence.

## Provider Roadmap

High-value additions:

1. **Perplexity Sonar provider mode**
   - Add a `sonar` mode alongside raw Perplexity Search.
   - Store the generated answer, citations, and returned search results.
   - Treat Sonar output as discovery metadata by default, not primary evidence.

2. **Tavily Crawl provider mode**
   - Add `--crawl-url`, `--crawl-instructions`, `--max-depth`, `--max-breadth`, `--limit`, `--select-paths`, and `--exclude-paths`.
   - Ingest crawled pages as web sources with `raw_content`.
   - Use for docs, support centers, standards pages, trust centers, changelogs, release notes, and other multi-page evidence domains.

3. **Tavily Extract enrichment**
   - Pass query/reranking parameters where available.
   - Preserve extracted chunks and full raw content separately.
   - Prefer extract over generic downloader for JS-heavy or docs-style pages.

4. **Exa contents/answer/research modes**
   - Add contents extraction for full text, highlights, summaries, freshness control, and subpage crawling.
   - Add answer/research modes as discovery layers that return cited source sets.
   - Add find-similar support for expanding from a known authoritative source.

5. **Linkup sourced and structured outputs**
   - Add `sourcedAnswer` and `structured` output modes.
   - Support inline citations and source inclusion where available.
   - Add async research task creation and polling for broad web investigations.

6. **GenSee reasoning/direct retrieval modes**
   - Support direct/digested retrieval separately from reasoning-based retrieval.
   - Preserve references, visited URLs, and crawl traces when returned.
   - Use multilingual and deep-crawl behavior for discovery-heavy questions.

7. **Authority-aware triage**
   - Score sources by authority for the claim type, not just relevance.
   - Official docs should outrank summaries for product, policy, legal, and availability claims.
   - Independent evaluations should outrank vendor marketing for performance claims.
   - Community sources should be valuable for field experience, not treated as authoritative for official facts.

8. **Freshness-aware state fields**
   - Track `retrieved_at`, `published_at`, `last_updated`, `source_authority`, and `volatility`.
   - Allow audits to flag stale volatile claims.

9. **Structured web evidence output**
   - Add a table-building or record-building phase before synthesis.
   - Generate report claims from normalized web evidence rows rather than from prose notes alone.

## Success Criteria

A web research intelligence run should be considered good when:

- Current, volatile claims are backed by primary or high-authority sources.
- Extracted facts include checked dates, source URLs, and exact support.
- Conflicting sources are reconciled or shown as conflicts.
- Secondary sources are used mainly for leads, synthesis, and context.
- Community and practitioner sources are clearly separated from official or primary evidence.
- The report's confidence ratings reflect source authority, freshness, independent corroboration, and volatility, not just source count.
