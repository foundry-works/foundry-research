# Grey Sources: Anna's Archive and Sci-Hub

foundry-research includes two download sources that operate in legally ambiguous territory. This page explains what they are, why they're included, and how to disable them if you prefer not to use them.

## What Are Grey Sources?

The PDF download cascade tries seven sources in order when downloading a paper by DOI:

1. OpenAlex — open-access PDF URL lookup
2. Unpaywall — open-access PDF URL lookup
3. arXiv — direct PDF for arXiv papers
4. PubMed Central — open-access biomedical literature
5. OSF — preprint servers (PsyArXiv, SocArXiv, etc.)
6. **Anna's Archive** — shadow library aggregator
7. **Sci-Hub** — shadow library

Sources 1–5 are legitimate open-access channels. Sources 6 and 7 are shadow libraries that provide access to paywalled papers without publisher authorization.

### Anna's Archive

Anna's Archive is a search engine and aggregator that indexes content from multiple shadow libraries. It can locate and download paywalled papers that are not available through open-access channels.

- Works by looking up a paper's DOI and finding a cached copy
- Supports a fast API path (requires a paid membership — set `annas_secret_key` in config) and a slower web scraping fallback (free, no account needed)
- Uses mirror discovery to find working domains, with fallback to cached mirrors

### Sci-Hub

Sci-Hub is a shadow library that provides free access to paywalled academic papers. It works by fetching papers through institutional credentials or cached copies.

- Works by accessing a paper's DOI and extracting the PDF from cached copies
- Does not require authentication
- Uses mirror discovery to find working domains

## Why They're Included

There is a strong ethical case for access to academic literature. Most published research is publicly funded, yet much of it ends up behind paywalls that only wealthy institutions can afford. Researchers at smaller universities, in the Global South, or working independently are often locked out of the literature they need — and in many cases helped produce.

Shadow libraries exist because the academic publishing system creates an access problem, not because researchers want to circumvent it. When a publicly funded study is only available through a $40 paywall or a $30,000/year institutional subscription, the barriers are economic, not moral.

foundry-research includes these sources because access to knowledge should not depend on institutional affiliation or budget. They significantly increase download success rates, especially in paywall-heavy fields like psychology, education, and medicine.

They are positioned last in the cascade — every open-access source is tried first. Anna's Archive and Sci-Hub are only attempted when all legitimate sources fail.

## This Is a Personal Choice

That said, using shadow libraries is still a personal decision, and foundry-research respects either choice:

- **If you choose to use them**, they're enabled by default and will try to download papers that the open-access cascade misses.
- **If you choose not to use them**, the cascade simply skips them and works with the remaining five open-access sources.

## How to Disable Grey Sources

### Option 1: Environment Variable

```bash
export DEEP_RESEARCH_DISABLED_SOURCES="annas_archive,scihub"
```

Add this to your shell profile (`~/.bashrc` or `~/.zshrc`) for persistence.

### Option 2: Global Config File

Add to `~/.deep-research/config.json`:

```json
{
  "disabled_sources": ["annas_archive", "scihub"]
}
```

### Option 3: Per-Session Config

Add to your research session's `.config.json`:

```json
{
  "disabled_sources": ["annas_archive", "scihub"]
}
```

## What Happens When Disabled

When grey sources are disabled:

- The cascade tries only the five legitimate open-access sources (OpenAlex, Unpaywall, arXiv, PMC, OSF)
- Download success rates will be lower, especially for papers behind paywalls
- The system still attempts paywall recovery through web search (finding author self-archived copies on institutional repositories, ResearchGate, etc.)
- No error or warning is generated — the sources are simply skipped

## Minimal No-Grey-Sources Config

```bash
# Set a web search key
export TAVILY_API_KEY="tvly-..."

# Configure keys + disable shadow libraries
mkdir -p ~/.deep-research
cat > ~/.deep-research/config.json << 'EOF'
{
  "unpaywall_email": "you@example.com",
  "ncbi_api_key": "...",
  "disabled_sources": ["annas_archive", "scihub"]
}
EOF
```

This gives you full access to all open-access channels without any shadow library usage.
