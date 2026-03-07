# Implementation Order

## Step 1: Shared Utilities (`_shared/`)

1. `config.py` — env vars, config file, session dir resolution
2. `output.py` — JSON envelope, stderr logging
3. `doi_utils.py` — DOI normalization, extraction, validation
4. `rate_limiter.py` — token-bucket per-domain rate limiter
5. `http_client.py` — requests session with rate limiting, retries, User-Agent
6. `html_extract.py` — HTML → text, JATS stripping
7. `metadata.py` — paper normalization, JSON metadata I/O

## Step 2: State Tracker

8. `state.py` — search history, source index, dedup logic

## Step 3: Search Providers (parallelizable — each provider is independent)

9. `search.py` CLI entry point + provider registry (`providers/__init__.py`)
10. `providers/semantic_scholar.py` — search, citations, recommendations, author
11. `providers/openalex.py` — search, open access filtering
12. `providers/arxiv.py` — search, category-expr, download
13. `providers/pubmed.py` — search, cited-by, references, related, MeSH
14. `providers/biorxiv.py` — preprint search, preprint→publication tracking
15. `providers/scholar.py` — search, BibTeX/RIS (includes BibTeX parser)
16. `providers/github.py` — repos, code, discussions, README
17. `providers/reddit.py` — search, browse, post+comments, link extraction
18. `providers/hn.py` — search, story comments, link extraction

## Step 4: Download + Enrich

19. `download.py` — web content, PDF download, DOI cascade, PDF→Markdown, local ingestion
    - Anna's Archive integration (DOI lookup via `/scidb/{doi}`, mirror discovery via Wikipedia scraping)
    - Sci-Hub mirror update (Wikipedia-based dynamic discovery)
    - Local directory ingestion (`--local-dir`)
20. `enrich.py` — Crossref DOI metadata enrichment

## Step 5: Skill Prompt + Subagent Definitions

21. `SKILL.md` — ~200 line capabilities-based prompt
22. `.claude/agents/research-reader.md` — Sonnet subagent for source summarization and verification (no searcher subagent — supervisor runs CLI directly)

## Step 6: Automated Tests

24. Write and run automated test suite per [`tests.md`](./tests.md):
    - Dedup edge cases (DOI/URL/title collisions)
    - Rate-limit/backoff behavior
    - Metadata normalization across providers
    - State schema compatibility across resumed sessions
    - HTTP error handling
    - Provider output format consistency

## Step 7: Integration Testing

25. Test with 4 queries:
    - General/technical: "What is WebAssembly and why does it matter?"
    - Comparative: "Compare PostgreSQL vs MySQL for high-write workloads"
    - Academic/CS: "Current state of quantum error correction approaches in 2025-2026"
    - Biomedical: "CRISPR delivery mechanisms for in vivo gene therapy"
26. Verify: source files on disk (`.md` readable, PDFs openable)
27. Verify: state.db tracks searches and sources, no duplicates (via `state.py summary`)
28. Verify: report citations backed by on-disk sources
29. Iterate on SKILL.md based on output quality

---

## Phase 2: Financial Analysis Extension

Depends on Phase 1 (Steps 1–7) being complete. The financial providers reuse shared utilities, state tracking, and download infrastructure from Phase 1.

### Step 8: State Schema Extension

30. Add `metrics` table to `state.py` — new commands: `log-metric`, `log-metrics`, `get-metrics`, `get-metric`
31. Update `summary` command to include metrics section when metrics exist

### Step 9: Financial Providers (parallelizable)

32. `providers/yfinance.py` — profile, history, financials, options, dividends, holders
    - **Dependency:** `yfinance` added to `requirements.txt`
    - Register `query2.finance.yahoo.com` with conservative rate limits in `rate_limiter.py`
33. `providers/edgar.py` — EFTS full-text search, company filings, XBRL company facts/concepts, filing download
    - CIK resolution via `company_tickers.json` with session-level cache
    - Filing document download integrates with `download.py` HTML→Markdown pipeline

### Step 10: SKILL.md Update

34. Add financial provider reference card to SKILL.md (yfinance modes, EDGAR modes, when to use each)
35. Add financial research workflow guidance (screening → deep dive → SEC verification → synthesis)
36. Add math caveat: output raw tables from providers, do not compute derived metrics without explicit caveats

### Step 11: Financial Tests

37. Write automated tests per `tests.md` Section 7:
    - yfinance provider: valid/invalid tickers, multi-ticker batching, field handling, rate limit
    - EDGAR provider: CIK resolution, EFTS search, XBRL facts, accession formatting, User-Agent
    - Metrics state: log/retrieve/dedup/summary integration

### Step 12: Financial Integration Testing

38. Test with 3 financial queries:
    - Single company deep dive: "Analyze NVIDIA's financial position and growth trajectory"
    - Sector comparison: "Compare Tesla, Ford, and GM on profitability and valuation"
    - Filing analysis: "What are the key risk factors in Apple's most recent 10-K?"
39. Verify: metrics persisted in state.db, no redundant yfinance calls
40. Verify: SEC filing content extracted and readable in sources/
41. Verify: report cross-references yfinance data with EDGAR filings where applicable
