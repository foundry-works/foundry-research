# Source Providers

Complete reference for all search providers, download sources, and their configuration.

## Academic Search Providers

> **Why no Google Scholar?** Google Scholar blocks automated access (CAPTCHAs, no public API). The providers below offer comparable coverage through APIs designed for programmatic use.

| Provider | Domain | API Key | Rate Limit | Key Capabilities |
|----------|--------|---------|------------|------------------|
| **Semantic Scholar** | Cross-disciplinary | Optional (`SEMANTIC_SCHOLAR_API_KEY`) | 1 req/s (10 with key) | Keyword search, forward/backward citations, recommendations, author search, citation count filter, fields-of-study filter |
| **OpenAlex** | Cross-disciplinary (strong for social sciences) | Optional (`OPENALEX_API_KEY`) | 10 req/s | Keyword search with pagination, forward/backward citations, year range, open-access filter, sort by citation count or date |
| **arXiv** | Physics, Math, CS, Quantitative Biology/Finance | None | 1 req/s | Keyword search, category filtering, date filtering, PDF download with CAPTCHA detection, PDF-to-markdown conversion |
| **PubMed** | Biomedical & life sciences | Optional (`NCBI_API_KEY`) | 3 req/s (10 with key) | Keyword search, MeSH terms, forward/backward citations, related articles, PMID batch fetch, publication type filter (review/trial/meta-analysis) |
| **bioRxiv / medRxiv** | Biology & medical preprints | Optional (uses OpenAlex key) | 5 req/s | Keyword search (via OpenAlex), DOI lookup, date-range browsing, category filtering, server selection |
| **Crossref** | Cross-disciplinary metadata (DOIs, citations) | None | 0.1 req/s | Keyword search, DOI lookup, year range, work type filter, sort by citation count or date, ISSN/subject filter |
| **CORE** | Open-access papers (global repositories) | Optional (`CORE_API_KEY`) | 0.15 req/s (0.4 with key) | Keyword search, year range, sort by relevance/recency/citations, full-text access (with key) |
| **DBLP** | Computer Science conferences & journals | None | 1 req/s | Publication search, author search, venue search, year range, publication type filter |
| **OpenCitations** | Citation traversal (no keyword search) | None | 2.5 req/s | Forward/backward citations by DOI, batch metadata enrichment, self-citation detection |

## Web Search Providers

One web search provider is required. The system auto-detects which are configured and probes them in order: Tavily, Perplexity, Linkup, GenSee, Exa.

| Provider | API Key | Rate Limit | Key Capabilities |
|----------|---------|------------|------------------|
| **Tavily** | Required (`TAVILY_API_KEY`) | 1 req/s; max 20 results | Web search (basic/advanced), news mode, domain filtering, URL content extraction |
| **Perplexity** | Required (`PERPLEXITY_API_KEY`) | 1 req/s; max 20 results | Web search, domain filtering, recency filter, country/language filter |
| **Linkup** | Required (`LINKUP_API_KEY`) | 1 req/s; max 20 results | Web search (fast/standard/deep), domain filtering, date range, URL content fetching |
| **Exa** | Required (`EXA_API_KEY`) | 1 req/s; max 50 results | Neural/fast/instant search, category filter (company/research paper/news/tweet/financial report), highlights extraction |
| **GenSee** | Required (`GENSEE_API_KEY`) | 1 req/s; max 20 results | Web search with mode selection (evidence/digest) |

## Community & Discussion Providers

| Provider | Domain | API Key | Rate Limit | Key Capabilities |
|----------|--------|---------|------------|------------------|
| **Reddit** | Discussion forums | None | 0.15 req/s (~9 req/min) | Multi-subreddit search, post details with comment tree, link extraction, sort/time filter |
| **Hacker News** | Tech discussion | None | 0.5 req/s | Story/comment/Ask HN search, date filtering, story detail with comments, link extraction |
| **GitHub** | Repositories, code, discussions | Optional (`GITHUB_TOKEN`) | 0.5 req/s | Repo search, code search (requires auth), discussions search, repo details with README, language/stars filter |

## Financial Data Providers

| Provider | Domain | API Key | Rate Limit | Key Capabilities |
|----------|--------|---------|------------|------------------|
| **SEC EDGAR** | SEC filings (10-K, 10-Q, etc.) | Optional (`SEC_EDGAR_EMAIL`) | 10 req/s | Full-text filing search, company filings by ticker, XBRL company facts/concepts, filing download |
| **Yahoo Finance** | Stock prices, financials, company profiles | None | 2s between tickers | Price history, financial statements (annual/quarterly), company profiles, options chains, dividends, institutional holders |

## Download Cascade

When downloading a paper by DOI, sources are tried in order:

| # | Source | Auth | Notes |
|---|--------|------|-------|
| 1 | **OpenAlex** | Optional (`OPENALEX_API_KEY`) | Checks for open-access PDF links |
| 2 | **Unpaywall** | Email (`UNPAYWALL_EMAIL`) | Open-access resolver using DOI |
| 3 | **arXiv** | None | Matches DOI to arXiv preprint |
| 4 | **PubMed Central** | Optional (`NCBI_API_KEY`) | Full-text articles in PMC |
| 5 | **OSF** | Optional (`OSF_TOKEN`) | PsyArXiv, SocArXiv, and other OSF preprints |
| 6 | **Anna's Archive** | Optional (`ANNAS_SECRET_KEY`) | Shadow library; can be disabled |
| 7 | **Sci-Hub** | None (mirror discovery) | Shadow library; can be disabled |

Sources 6 and 7 are grey sources (shadow libraries). They can be disabled via `DEEP_RESEARCH_DISABLED_SOURCES=annas_archive,scihub`. See [grey-sources.md](grey-sources.md) for details.

## Configuration

See [configuration.md](configuration.md) for the full configuration guide including precedence, key setup, and cascade source control.
