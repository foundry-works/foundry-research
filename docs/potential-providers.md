# Potential Providers

Candidate providers evaluated for future integration. Organized by category with API details, pricing, and integration notes.

## Academic Search

### NASA ADS (Astrophysics Data System)

- **Domain**: Astrophysics, physics, earth & space sciences
- **Coverage**: 15M+ records, gold standard for astronomy and astrophysics
- **Auth**: Free API key via [ui.adsabs.harvard.edu](https://ui.adsabs.harvard.edu)
- **Rate limit**: Generous for registered users
- **Key capabilities**: Keyword search, forward/backward citations, citation traversal, author search, bibcode-based lookups, year range filtering, full metadata (abstracts, affiliations, arXiv links)
- **Integration notes**: Strong citation graph comparable to Semantic Scholar. Fills a gap in earth/space science coverage. REST API with JSON responses. Would add as academic search provider.

### IEEE Xplore API

- **Domain**: Electrical engineering, computer science, electronics
- **Coverage**: 5M+ documents (journals, conferences, standards)
- **Auth**: Free API key registration at [developer.ieee.org](https://developer.ieee.org)
- **Rate limit**: Varies by key tier
- **Key capabilities**: Keyword search with Boolean operators, metadata retrieval, filtering by publication type, sorting, Python 3 SDK available
- **Integration notes**: Full text behind paywall but metadata and abstracts accessible. Fills the engineering gap not covered by arXiv or DBLP. Would add as academic search provider.

### ERIC (Education Resources Information Center)

- **Domain**: Education research, social sciences
- **Coverage**: 1M+ indexed records (journal articles, reports, conference papers)
- **Auth**: Free government API, no key required
- **Rate limit**: 50 requests/second (Institute of Education Sciences)
- **Key capabilities**: Keyword search, metadata + some full-text, thesaurus-based term search, peer-reviewed filter, publication type filter, date range
- **Integration notes**: Government API, highly stable. Fills education/social science gap. Simple REST API with JSON responses. Would add as academic search provider.

## Web Search

### Brave Search API

- **Domain**: General web search (independent index)
- **Coverage**: 35B+ independently indexed pages (not a Google/Bing proxy)
- **Auth**: API key (`BRAVE_API_KEY`), $5 free monthly credits
- **Pricing**: $5/1,000 queries (Data tier), volume discounts available
- **Rate limit**: 50 QPS
- **Key capabilities**: Web search, news search, image/video search, suggestions, spellcheck, "LLM Context" endpoint (optimized for AI consumption), "Answers" endpoint (extracted answers), Goggles (custom result reranking)
- **Integration notes**: Independent index provides anti-fragility against Google/Bing ecosystem outages. OpenAI SDK-compatible interface. MCP server available. Would add as web search provider alongside Tavily/Perplexity.

## Community & Discussion

### Stack Exchange API

- **Domain**: Q&A across 170+ sites
- **Coverage**: Stack Overflow, Mathematics, Physics, Server Fault, Ask Ubuntu, Super User, Cross Validated (stats), English Language & Usage, and 160+ more
- **Auth**: Optional API key for higher rate limits; reads work without auth
- **Rate limit**: 300 requests/minute with key, 30 without
- **Pricing**: Free (CC-BY-SA licensed content)
- **Key capabilities**: Search across all sites or specific ones, question/answer retrieval, tag-based filtering, user reputation filtering, date range, accepted-answer filtering
- **Integration notes**: Single API covers the entire network via the `site` parameter. Most research-relevant sites:
  - **Stack Overflow** — programming, software engineering
  - **Cross Validated** — statistics, machine learning
  - **Mathematics** — all areas of math
  - **Physics** — general physics Q&A
  - **Bioinformatics** — computational biology
  - **Computational Science** — numerical methods, simulations
  - **Data Science** — ML, data mining
  - **Artificial Intelligence** — AI/ML theory
  - **Philosophy** — academic philosophy
- Would add as community provider alongside Reddit and Hacker News.

## Media & News

### Listen Notes (Podcast Search)

- **Domain**: Podcasts and audio content
- **Coverage**: 3.76M podcasts, 188M+ episodes
- **Auth**: API key required
- **Pricing**: Free tier (mock server for testing); paid tiers for production
- **Rate limit**: Varies by tier
- **Key capabilities**: Full-text search across episodes, episode metadata, podcast metadata, transcript access (some episodes), genre filtering, language filtering, listen score
- **Integration notes**: Node.js and Python SDKs available. Unique content not available through text-based providers. Good for researching topics with significant podcast coverage (tech, science, policy). Would add as a new "Media" category provider.

### NewsAPI

- **Domain**: News articles from 80,000+ sources
- **Coverage**: Global news aggregation
- **Auth**: API key required
- **Pricing**: Free developer tier (100K requests/month, development only); production requires paid plan
- **Rate limit**: Varies by tier
- **Key capabilities**: Keyword search across sources, source-based filtering, date range, country/language filtering, top headlines endpoint
- **Limitations**: Does not return full article content (titles + descriptions only). Production use requires paid plan. Developer tier is restricted to development/testing.
- **Integration notes**: Useful for current-events context. Limited by lack of full article content — would need to pair with a content fetcher. Lower priority due to licensing restrictions on production use.

## Legal

### CourtListener (Free Law Project)

- **Domain**: US case law, PACER documents, legal citations
- **Coverage**: 2,971 jurisdictions, millions of opinions
- **Auth**: Free API token via [courtlistener.com](https://www.courtlistener.com)
- **Pricing**: Free (501(c)(3) non-profit), means-based pricing for heavy use
- **Rate limit**: Generous for registered users
- **Key capabilities**: Case law search, citation network traversal, RECAP PACER integration, judge information, oral argument audio, docket retrieval, bulk data exports
- **Integration notes**: Unique legal coverage not available elsewhere. Strong citation graph. REST API with comprehensive documentation. Would add as a new "Legal" category provider.
