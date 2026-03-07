# Architecture: Skill + Python Helper Scripts

## File Structure

```
~/.claude/skills/deep-research/
├── SKILL.md                          # Capabilities-based prompt (~200 lines)
└── scripts/
    ├── _shared/
    │   ├── __init__.py
    │   ├── config.py                 # API keys, session dir from env vars / config file
    │   ├── output.py                 # JSON envelope, stderr logging
    │   ├── doi_utils.py              # DOI normalization, extraction, validation
    │   ├── rate_limiter.py           # Token-bucket per-domain rate limiter
    │   ├── http_client.py            # Shared requests session with retries, User-Agent
    │   ├── html_extract.py           # HTML → text, JATS stripping
    │   └── metadata.py              # Paper normalization, JSON metadata I/O
    ├── providers/
    │   ├── __init__.py               # Provider registry
    │   ├── semantic_scholar.py       # search, citations, recommendations, author
    │   ├── openalex.py               # search, open access filtering
    │   ├── arxiv.py                  # search, category-expr, download
    │   ├── pubmed.py                 # search, cited-by, references, related, mesh
    │   ├── biorxiv.py                # preprint search, preprint→publication tracking
    │   ├── scholar.py                # search, bibtex/ris (includes bibtex parser)
    │   ├── github.py                 # repos, code, discussions, README
    │   ├── reddit.py                 # search, browse, post+comments, link extraction
    │   └── hn.py                     # search, story comments, link extraction
    ├── search.py                     # Unified search CLI entry point + arg routing
    ├── download.py                   # Web content, PDF download, DOI cascade, PDF→MD
    ├── enrich.py                     # Crossref DOI enrichment
    └── state.py                      # Search history + source index + dedup
```

22 Python files + 1 SKILL.md + 4 bash wrappers + 1 `requirements.txt`. Claude learns **4 CLI commands** instead of 12.

## Dependency Bootstrapping & CLI Wrappers

```
~/.claude/skills/deep-research/
├── requirements.txt              # Pinned Python dependencies
├── setup.sh                      # One-time bootstrap: creates venv + installs deps
├── search                        # Bash wrapper → .venv/bin/python scripts/search.py
├── download                      # Bash wrapper → .venv/bin/python scripts/download.py
├── enrich                        # Bash wrapper → .venv/bin/python scripts/enrich.py
├── state                         # Bash wrapper → .venv/bin/python scripts/state.py
```

**`requirements.txt`:**
```
requests>=2.31
beautifulsoup4>=4.12
pymupdf4llm>=0.0.10
curl-cffi>=0.7
pyyaml>=6.0
pypdf>=4.0
```

**`setup.sh`:**
```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SKILL_DIR/.venv"

# Require Python 3.10+
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)" >&2
    exit 1
fi

# Check that venv module is available (missing on some Debian/Ubuntu systems)
if [ ! -d "$VENV_DIR" ]; then
    if ! python3 -c "import venv" 2>/dev/null; then
        echo "ERROR: Python venv module not found. Install it with:" >&2
        echo "  sudo apt-get install python3-venv    # Debian/Ubuntu" >&2
        echo "  sudo dnf install python3-libs         # Fedora" >&2
        exit 1
    fi
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -r "$SKILL_DIR/requirements.txt"
fi
echo "$VENV_DIR/bin/python"
```

**Bash wrappers** (identical pattern for all 4 — `search`, `download`, `enrich`, `state`):
```bash
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# Auto-bootstrap venv on first use
[ -d "$DIR/.venv" ] || "$DIR/setup.sh" > /dev/null
exec "$DIR/.venv/bin/python" "$DIR/scripts/$(basename "$0").py" "$@"
```

**Why wrappers instead of `.venv/bin/python`:** LLMs drift on long paths over extended sessions. With wrappers, Claude runs `./search --provider semantic_scholar --query "..."` instead of `.venv/bin/python scripts/search.py ...`. The venv is auto-bootstrapped on first invocation — no setup step needed.

## CLI Interface Summary

| Command | Purpose | Key flags |
|---------|---------|-----------|
| `./search --provider <name>` | Search any provider | `--query`, `--limit`, `--session-dir` + provider-specific flags |
| `./download` | Save content to disk | `--url --type web`, `--pdf-url`, `--doi`, `--arxiv`, `--to-md`, `--from-json` |
| `./enrich` | Fill metadata via Crossref | `--doi` (one or more) |
| `./state` | Session state tracker | See [`scripts/state.md`](./scripts/state.md) for the canonical 16-command interface |

## Research Session Directory (created per research run)

```
./deep-research-{session}/
├── state.db                          # SQLite database — source of truth (search history, source index, rate limits)
├── state.json                        # Read-only JSON snapshot for human debugging (regenerated by `state.py export`; never read by scripts)
├── journal.md                        # Append-only reasoning scratchpad (intermediate thoughts, decisions, contradictions)
├── report.md                         # Final synthesized report
├── notes/                            # Per-source summaries (written by reader subagents)
│   ├── src-001.md                    # Summary + key findings from src-001
│   ├── src-003.md                    # Summary + key findings from src-003
│   └── ...
└── sources/
    ├── metadata/                     # Structured metadata (JSON, machine-owned)
    │   ├── src-001.json
    │   ├── src-002.json
    │   └── ...
    ├── src-001.md                    # Pure markdown content (no frontmatter)
    ├── src-001.pdf                   # Original PDF (academic, when available)
    ├── src-001.toc                   # Table of contents with line numbers (when converted from PDF)
    ├── src-002.md                    # Another source
    ├── src-003.md                    # Web source (no PDF)
    └── ...
```

## Source File Format

### Metadata (`sources/metadata/src-001.json`)

```json
{
  "id": "src-001",
  "title": "Attention Is All You Need",
  "authors": ["Vaswani, A.", "Shazeer, N.", "Parmar, N."],
  "year": 2017,
  "url": "https://arxiv.org/abs/1706.03762",
  "doi": "10.48550/arXiv.1706.03762",
  "pdf_url": "https://arxiv.org/pdf/1706.03762",
  "venue": "NeurIPS",
  "citation_count": 120000,
  "type": "academic",
  "provider": "semantic_scholar",
  "fetched_at": "2026-03-07T14:35:00Z",
  "has_pdf": true,
  "quality": "ok"
}
```

### Content (`sources/src-001.md`)

Pure markdown — no YAML frontmatter, no metadata headers. Just the extracted text content. This prevents Claude from accidentally modifying structured metadata when reading or editing source files, and saves tokens when only the text is needed.

## Why Save Everything to Disk

- **Deterministic verification** — claims checked against the *exact* content used during investigation, not whatever the URL serves later
- **No re-fetch failures** — URLs go down, paywalls appear, rate limits hit
- **Richer synthesis** — Claude can `Read` full source files during report writing
- **Human access to PDFs** — researchers can read the actual papers, not just Claude's summaries
- **Audit trail** — everything the research was based on is preserved

## Why Python Scripts

| Concern | Prompt-only approach | With Python scripts |
|---------|---------------------|-------------------|
| API calls | WebFetch/curl (fragile) | Proper HTTP client with error handling |
| Abstract parsing | Claude parses inverted index (waste of tokens) | Python reconstructs OpenAlex abstracts |
| XML cleanup | Claude strips JATS tags (error-prone) | Regex in Python |
| State management | Read/Write JSON (race-prone) | Atomic read-modify-write with dedup |
| Rate limiting | Hope for the best | Token-bucket per-domain throttle |
| Error handling | Claude interprets HTTP errors | Python returns clean error JSON |

## Academic API Reference

| Provider | Base URL | Auth | Rate Limit | Purpose |
|----------|----------|------|------------|---------|
| **Semantic Scholar** | `api.semanticscholar.org/graph/v1` | Optional `x-api-key` header | 1 RPS | Paper search, forward citations, recommendations |
| **OpenAlex** | `api.openalex.org` | Required `x-api-key` header (free) | 50 RPS | 477M+ works, citation graphs, topic classification |
| **Crossref** | `api.crossref.org` | None (polite pool via `mailto:` User-Agent) | 10 RPS | DOI metadata enrichment (venue, authors, volume, pages) |
| **Google Scholar** | `scholar.google.com` | None (scraping) | ~1 req/5s (conservative) | Discovery search, BibTeX citations |
| **Reddit** | `www.reddit.com/*.json` | None (public JSON) | 10 req/min | Community discussions, practical insights |
| **PubMed/NCBI** | `eutils.ncbi.nlm.nih.gov/entrez/eutils` | Optional `NCBI_API_KEY` | 3 RPS (10 w/ key) | Biomedical literature, MeSH, citation graph |
| **bioRxiv/medRxiv** | `api.biorxiv.org` | None | ~1 RPS (polite) | Biology/medicine preprints |
| **GitHub** | `api.github.com` | Optional `GITHUB_TOKEN` | 10 search/min (30 w/ token) | Repos, code, discussions |
| **Hacker News** | `hn.algolia.com/api/v1` | None | ~1 RPS (polite) | Technical discussions, paper commentary |
| **Unpaywall** | `api.unpaywall.org/v2` | Email param | 100K/day | OA PDF discovery by DOI |
| **Sci-Hub** | Various mirrors | None | ~1 req/5s | Last-resort PDF access (pre-2021 papers) |
| **arXiv** | `export.arxiv.org/api` | None | Generous | Preprint search + PDFs |
| **PMC** | `ncbi.nlm.nih.gov/pmc` | None | 3 RPS | NIH-funded full-text PDFs |
