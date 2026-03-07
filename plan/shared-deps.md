# Shared Dependencies (`_shared/`)

7 utility modules used across all scripts.

```
scripts/
├── _shared/
│   ├── __init__.py
│   ├── config.py             # API keys, session dir from env vars / config file
│   ├── output.py             # JSON envelope, stderr logging
│   ├── doi_utils.py          # DOI normalization, extraction, validation
│   ├── rate_limiter.py       # Token-bucket per-domain rate limiter
│   ├── http_client.py        # Shared requests session with retries, User-Agent
│   ├── html_extract.py       # HTML → text, JATS stripping
│   └── metadata.py           # Paper normalization, JSON metadata I/O
```

## What Was Consolidated / Dropped

| Original Module | Disposition | Rationale |
|-----------------|-------------|-----------|
| `dedup.py` | → `state.py` | Dedup logic only used by state management |
| `pdf_utils.py` | → `download.py` | PDF handling only used by download |
| `bibtex_parser.py` | → `providers/scholar.py` | BibTeX parsing only used by Scholar provider |
| `credibility.py` | **Dropped** | Claude judges credibility from metadata it already has |

## Dependency Matrix

| Package | Used by | Purpose |
|---------|---------|---------|
| `requests` | All scripts (via `http_client.py`) | HTTP client |
| `beautifulsoup4` | `providers/scholar.py`, `download.py` (via `html_extract.py`) | HTML parsing |
| `pymupdf4llm` | `download.py` | PDF → Markdown conversion (primary) |
| `pypdf` | `download.py` | PDF → raw text extraction (fallback when pymupdf4llm fails/hangs) |
| `curl-cffi` | `download.py` | Cloudflare bypass for Sci-Hub mirrors |
| `pyyaml` | Config file parsing, subagent definitions | YAML config serialization (no longer used for source metadata) |

---

## `config.py` — Shared Configuration

Used by all scripts that need API keys or session context.

```python
def get_config() -> dict:
    """Load config from (in priority order):
    1. Environment variables: SEMANTIC_SCHOLAR_API_KEY, OPENALEX_API_KEY, UNPAYWALL_EMAIL, etc.
    2. Config file: ~/.deep-research/config.json
    3. Session-dir local config: {session_dir}/.config.json
    Returns dict with all known keys (None for unset)."""

def get_session_dir(args) -> str:
    """Resolve session directory from --session-dir arg or $DEEP_RESEARCH_SESSION_DIR env var.
    Creates directory + sources/ subdirectory if they don't exist."""
```

---

## `output.py` — Consistent JSON Output Envelope

Used by all scripts for stdout output.

```python
def success_response(results: list | dict, total_results: int = None, **extra) -> str:
    """Return JSON envelope: {"status": "ok", "results": ..., "errors": [], "total_results": N, ...extra}.
    Prints to stdout. total_results defaults to len(results) if not provided."""

def error_response(errors: list[str], partial_results: list | dict = None) -> str:
    """Return JSON envelope: {"status": "error", "results": [...], "errors": [...], "total_results": N}.
    Exit code 0 if partial results, 1 if total failure."""

def log(message: str, level: str = "info") -> None:
    """Log to stderr (not stdout, to keep JSON output clean)."""
```

**Canonical envelope** (used by all scripts):
```json
{
  "status": "ok" | "error",
  "results": [...],
  "errors": [],
  "total_results": N
}
```
**`search.py`** uses this envelope exactly. **`download.py`** and **`enrich.py`** use a compatible but purpose-specific shape — they always include `status` and `errors`, but replace `results`/`total_results` with keys appropriate to their output (e.g., `source_id`, `content_file` for downloads; `results` array for enrichment). The key contract: every script returns JSON to stdout with `"status"` and `"errors"` fields, exits 0 on success/partial, exits 1 on total failure.

---

## `doi_utils.py` — DOI Normalization & Extraction

Used by search providers, `enrich.py`, `download.py`, and `state.py` (dedup).

```python
def normalize_doi(doi: str) -> str:
    """Normalize DOI to canonical form: lowercase, strip URL prefixes (doi.org/, dx.doi.org/, https://), strip trailing punctuation."""

def extract_doi(text: str) -> str | None:
    """Extract DOI from a string (URL, citation text, free text). Handles doi.org URLs, 'doi:' prefixes, raw '10.XXXX/...' patterns."""

def is_valid_doi(doi: str) -> bool:
    """Validate DOI format (10.XXXX/...). Does NOT check existence."""

def doi_to_url(doi: str) -> str:
    """Convert DOI to https://doi.org/... resolver URL."""

def extract_arxiv_id(text: str) -> str | None:
    """Extract arXiv ID from URL or text (handles arxiv.org/abs/, arxiv.org/pdf/, arxiv: prefix, raw YYMM.NNNNN)."""

def canonicalize_url(url: str) -> str:
    """Canonicalize URL for deduplication. Beyond basic normalization (strip fragment, query, trailing slash),
    applies domain-specific rules:
    - arXiv: arxiv.org/abs/XXXX and arxiv.org/pdf/XXXX.pdf → arxiv.org/abs/XXXX
    - bioRxiv/medRxiv: strip version suffix (/v1, /v2) → base DOI URL
    - Semantic Scholar: /paper/HASH and /paper/TITLE-HASH → /paper/HASH
    - PMC: /pmc/articles/PMCNNN/ and /pmc/articles/PMCNNN/pdf/ → /pmc/articles/PMCNNN/
    - doi.org resolver URLs: extract DOI and normalize via normalize_doi()
    """
```

**Why shared:** DOIs appear in every script — search results, enrichment lookups, download identifiers, deduplication keys. Inconsistent normalization would cause dedup failures and broken lookups. URL canonicalization catches duplicates that simple fragment/query stripping misses (e.g., `arxiv.org/abs/2401.12345` vs `arxiv.org/pdf/2401.12345.pdf`).

---

## `rate_limiter.py` — Unified Rate Limiting

All API calls go through a shared rate limiter to prevent IP bans and respect API limits.

**Strategy:** Token-bucket per domain with configurable rates.

```python
# Default rate limits (requests per second)
RATE_LIMITS = {
    "api.semanticscholar.org": 1.0,
    "api.openalex.org": 10.0,
    "api.crossref.org": 10.0,
    "api.unpaywall.org": 10.0,
    "scholar.google.com": 0.2,
    "www.reddit.com": 0.15,
    "eutils.ncbi.nlm.nih.gov": 3.0,
    "api.biorxiv.org": 1.0,
    "api.github.com": 0.5,
    "hn.algolia.com": 1.0,
    "sci-hub.*": 0.2,
    "arxiv.org": 1.0,
    "ncbi.nlm.nih.gov": 3.0,
    "_default": 2.0,
}
```

**Features:**
- Token-bucket algorithm with burst allowance (burst = 2× rate)
- Per-domain tracking (not global) so slow APIs don't block fast ones
- Exponential backoff on 429/503 responses (2s → 4s → 8s → 16s → 30s cap)
- Random jitter (±20%) on all delays to avoid thundering herd
- Thread-safe (for `download.py --parallel`)
- **Cross-process safe** via SQLite — rate limit state stored in `{session_dir}/state.db` (shared with `state.py`). SQLite handles its own locking natively, works reliably across platforms (Unix, Windows, WSL, Docker volumes, NFS), and eliminates the need for manual `fcntl.flock()`, stale lock recovery, or exponential backoff logic.
- All script invocations (sequential or parallel subagents) respect shared rate limits through SQLite's built-in WAL mode and busy timeout (`PRAGMA busy_timeout = 20000`).

**Usage:**
```python
from _shared.rate_limiter import RateLimiter

limiter = RateLimiter(session_dir="./deep-research-{session}")
limiter.wait("api.semanticscholar.org")  # blocks until safe to request
response = requests.get(url)
if response.status_code == 429:
    limiter.backoff("api.semanticscholar.org")
```

---

## `http_client.py` — Shared HTTP Session

Wraps `requests` with:
- Automatic rate limiter integration
- Retry with exponential backoff (3 attempts)
- Configurable User-Agent rotation
- Timeout defaults (15s connect, 30s read)
- 429/503 detection with backoff signaling

---

## `html_extract.py` — HTML → Text Extraction

Used by `download.py` (web source content), `providers/scholar.py` (parsing Scholar result pages), `providers/hn.py` (stripping HTML from comments).

```python
def html_to_text(html: str) -> str:
    """Extract readable text from HTML. Uses BeautifulSoup if available, falls back to regex tag stripping."""

def extract_readable_content(html: str) -> str:
    """Extract main article content, stripping nav/header/footer/sidebar. Best-effort heuristic."""

def strip_jats_xml(text: str) -> str:
    """Strip JATS XML tags from academic abstracts (common in Crossref/OpenAlex responses)."""
```

---

## `metadata.py` — Paper Metadata Normalization & JSON Metadata I/O

Used by search providers, `download.py`, `enrich.py`, and `state.py`.

```python
def normalize_paper(raw: dict, provider: str) -> dict:
    """Normalize paper metadata from any provider into a unified schema.
    Handles provider-specific quirks:
    - Semantic Scholar: authors as [{"name": "..."}] → ["Name"]
    - OpenAlex: abstract_inverted_index → plain text, authorships → author names
    - Crossref: date-parts [[2024, 3, 15]] → year int, title as array → string
    - Google Scholar BibTeX: parsed fields → unified dict
    """

def merge_metadata(existing: dict, new: dict) -> dict:
    """Merge metadata from multiple providers. Fill missing fields only, don't overwrite.
    Field-specific priority (best source per field):
    - venue, volume, issue, pages, year, is_retracted: Crossref > OpenAlex > Semantic Scholar > Scholar
    - abstract, topics, fields_of_study: OpenAlex > Semantic Scholar > Crossref > Scholar
    - citation_count: Semantic Scholar > OpenAlex > Crossref > Scholar
    - authors: Crossref > Semantic Scholar > OpenAlex > Scholar
    - peer_reviewed, publication_types: PubMed > Crossref > OpenAlex
    Never overwrite a non-empty field with an empty/null value from a higher-priority source."""

def write_source_metadata(metadata_dir: str, source_id: str, metadata: dict) -> None:
    """Write metadata to sources/metadata/{source_id}.json."""

def read_source_metadata(metadata_dir: str, source_id: str) -> dict:
    """Read metadata from sources/metadata/{source_id}.json."""

# Unified paper schema (minus credibility/curation fields — those are Claude's job)
PAPER_SCHEMA = {
    "id": str,           # source ID (src-001)
    "title": str,
    "authors": list,     # ["Last, First", ...] normalized
    "year": int,
    "abstract": str,
    "doi": str,          # normalized via doi_utils
    "url": str,
    "pdf_url": str,
    "venue": str,
    "citation_count": int,
    "type": str,         # "academic" | "web" | "reddit" | "hn" | "github"
    "provider": str,     # "semantic_scholar" | "openalex" | "crossref" | "scholar" | "pubmed" | "arxiv" | "biorxiv" | "web"
    "fetched_at": str,   # ISO 8601
    "has_pdf": bool,
    "peer_reviewed": bool | None,   # True = published in peer-reviewed venue, False = preprint/web, None = unknown
    "is_retracted": bool,           # from Crossref retraction detection
    "publication_types": list,      # from PubMed: ["Review", "Clinical Trial", "Meta-Analysis", etc.]
    "quality": str,                 # "ok" | "degraded" — set by pdf_to_markdown structural check
}
```

**Why shared:** Every script that touches paper data needs to produce/consume the same schema. Without centralized normalization, each script would implement its own author parsing, date handling, and abstract reconstruction.
