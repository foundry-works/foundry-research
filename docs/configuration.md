# Configuration

foundry-research uses a 3-layer configuration system for API keys and settings. Higher-priority sources override lower ones.

## Precedence Order

1. **Environment variables** (highest) — set in shell profile or `.env`
2. **Global config** — `~/.deep-research/config.json`
3. **Session config** — `<session-dir>/.config.json` (lowest)

For most users, the global config file is the simplest approach. Some keys (web search providers) only work as environment variables; academic provider keys can go in either the config file or env vars.

## Setting Up Your Config

Create the global config directory and file:

```bash
mkdir -p ~/.deep-research
cat > ~/.deep-research/config.json << 'EOF'
{
  "unpaywall_email": "you@example.com",
  "ncbi_api_key": "...",
  "openalex_api_key": "..."
}
EOF
```

Environment variables can be set in your shell profile (`~/.bashrc`, `~/.zshrc`):

```bash
export TAVILY_API_KEY="tvly-..."
export SEMANTIC_SCHOLAR_API_KEY="..."
```

## Web Search Providers

You need **at least one** web search provider configured. These keys must be set as environment variables — they are not read from `config.json`. The system auto-detects which ones have keys and uses the first available.

| Provider    | Env Variable          | Get a key at                  |
|-------------|-----------------------|-------------------------------|
| Tavily      | `TAVILY_API_KEY`      | [tavily.com](https://tavily.com) |
| Perplexity  | `PERPLEXITY_API_KEY`  | [docs.perplexity.ai](https://docs.perplexity.ai) |
| Linkup      | `LINKUP_API_KEY`      | [api.linkup.so](https://api.linkup.so) |
| Exa         | `EXA_API_KEY`         | [exa.ai](https://exa.ai) |
| GenSee      | `GENSEE_API_KEY`      | [app.gensee.ai](https://app.gensee.ai) |

All web search providers are called directly through their REST APIs. Set the environment variable and the provider works — no additional setup needed.

## Academic Provider Keys

All of these are optional. They increase rate limits, unlock specific data sources, or improve download success rates. These keys can go in either `~/.deep-research/config.json` (using the config key column) or as environment variables.

| Provider          | Config key               | Env variable                  | What it provides                              |
|-------------------|--------------------------|-------------------------------|-----------------------------------------------|
| Semantic Scholar  | `semantic_scholar_api_key` | `SEMANTIC_SCHOLAR_API_KEY`  | Higher rate limits (10 req/s vs 1 req/s)      |
| OpenAlex          | `openalex_api_key`       | `OPENALEX_API_KEY`            | Polite pool access, faster responses           |
| Unpaywall         | `unpaywall_email`        | `UNPAYWALL_EMAIL`             | Open-access PDF URL discovery                  |
| NCBI/PubMed       | `ncbi_api_key`           | `NCBI_API_KEY`                | 10 req/s vs 3 req/s                            |
| GitHub            | `github_token`           | `GITHUB_TOKEN`                | Higher rate limits, code search enabled        |
| CORE              | `core_api_key`           | `CORE_API_KEY`                | 1000 tokens/day, full text access              |
| OSF/PsyArXiv      | `osf_token`              | `OSF_TOKEN`                   | Authenticated OSF preprint access              |
| SEC EDGAR         | `sec_edgar_email`        | `SEC_EDGAR_EMAIL`             | EDGAR financial filings                        |

## Cascade Source Control

The PDF download cascade can be configured to skip specific sources. This is primarily used to disable shadow libraries (see [grey sources](grey-sources.md)).

**Anna's Archive fast downloads** — Anna's Archive works without a key (via web scraping), but a paid membership provides faster, more reliable downloads through their API. Set `ANNAS_SECRET_KEY` (env) or `annas_secret_key` (config file) to enable the fast path. Without it, the scrape fallback is used automatically.

**Via environment variable:**
```bash
export DEEP_RESEARCH_DISABLED_SOURCES="annas_archive,scihub"
```

**Via global config (`~/.deep-research/config.json`):**
```json
{
  "disabled_sources": ["annas_archive", "scihub"]
}
```

Available source names: `openalex`, `unpaywall`, `arxiv`, `pmc`, `osf`, `annas_archive`, `scihub`.

## Minimal Configuration

The absolute minimum for your first research session:

```bash
# 1. A web search key
export TAVILY_API_KEY="tvly-..."

# 2. An email for Unpaywall (improves PDF download success)
mkdir -p ~/.deep-research
echo '{"unpaywall_email": "you@example.com"}' > ~/.deep-research/config.json
```

This gives you web search plus the full open-access download cascade. From there, add academic keys as you need them.

## No-Key Providers

These providers work without any configuration. They cover academic preprints, metadata, citations, community discussion, and financial data:

arXiv, bioRxiv/medRxiv, Crossref, DBLP, OpenCitations, Reddit, Hacker News, yfinance

That's 8 providers available out of the box. Add keys to unlock the providers listed above.
