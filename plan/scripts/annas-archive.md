# Anna's Archive Integration

**Purpose:** Add Anna's Archive as an additional source in the OA PDF cascade in `download.py`, alongside Sci-Hub. Anna's Archive aggregates LibGen, Sci-Hub, Z-Library, and other shadow libraries into a single search interface with both scraping and API access paths.

## Reference Implementation

Cloned from [iosifache/annas-mcp](https://github.com/iosifache/annas-mcp) (Go). Key patterns extracted below.

## How It Works

Anna's Archive provides two access methods:

### 1. JSON API (requires donation + API key)

```
GET https://{mirror}/dyn/api/fast_download.json?md5={hash}&key={secret_key}
→ {"download_url": "https://..."}
```

- Requires `ANNAS_SECRET_KEY` (obtained after donating)
- Returns a direct download URL
- Most reliable method

### 2. Web Scraping (no auth required)

```
Search:  GET https://{mirror}/search?q={query}&content={book_any|journal}
SciDB:   GET https://{mirror}/scidb/{doi}  → redirects to search results
Detail:  GET https://{mirror}/md5/{hash}   → paper metadata page
```

- Parse HTML for `<a href="/md5/...">` links to extract MD5 hashes
- Extract metadata from `div.max-w-full` containers
- Requires `User-Agent` spoofing (DDoS-Guard protection)
- More fragile, breaks when HTML structure changes

## Integration into download.py OA Cascade

Updated cascade with Anna's Archive added as step 5 (before Sci-Hub):

```
OA Source Cascade (for DOIs):

  1. OpenAlex     (open_access.oa_url)
  2. Unpaywall    (best_oa_location.url_for_pdf)
  3. arXiv        (if arXiv ID in externalIds)
  4. PMC          (if PMCID in externalIds)
  5. Anna's Archive  (search by DOI via /scidb/{doi})
  6. Sci-Hub      (pre-2021 papers only, last resort)
```

### Why Anna's Archive Before Sci-Hub

- Aggregates multiple sources (LibGen, Z-Library, Sci-Hub data) — broader coverage
- Has papers newer than 2021 (Sci-Hub stopped uploading in 2021)
- SciDB endpoint provides DOI-based lookup without needing a search query
- Can fall back to keyword search if DOI lookup fails

## Implementation

### Python Approach (not Go)

The reference implementation uses Go + Colly for HTML scraping. Our Python implementation should use:

- `httpx` or `curl-cffi` for HTTP (Cloudflare/DDoS-Guard bypass)
- `beautifulsoup4` for HTML parsing
- Same selector patterns as the Go implementation

### Core Functions

```python
def annas_search_doi(doi: str, mirror: str) -> Optional[str]:
    """Look up DOI via /scidb/{doi}, extract MD5 hash from results.
    Returns MD5 hash if found, None otherwise."""

def annas_search_query(query: str, content_type: str, mirror: str) -> list[dict]:
    """Search by keyword. content_type: 'book_any' or 'journal'.
    Returns list of {title, authors, hash, format, size, url}."""

def annas_download_api(md5: str, secret_key: str, mirror: str, dest: str) -> bool:
    """Download via JSON API (fast_download). Requires API key.
    Returns True on success."""

def annas_download_scrape(md5: str, mirror: str, dest: str) -> bool:
    """Download via web scraping fallback. No auth needed.
    Returns True on success."""
```

### Download Strategy

```
Input: DOI
  │
  ▼
annas_search_doi(doi)  →  MD5 hash
  │
  ├─ If ANNAS_SECRET_KEY set:
  │    annas_download_api(hash, key)  →  PDF
  │
  └─ Else / if API fails:
       annas_download_scrape(hash)  →  PDF
```

## Mirror Discovery

### Strategy: Wikipedia as Dynamic Mirror Source

Both Sci-Hub and Anna's Archive have mirrors that frequently change due to domain seizures. Rather than hardcoding mirrors that rot, we use Wikipedia articles as a community-maintained source of truth.

**Discovery flow (on first use per session):**

```
1. Curl Wikipedia article for the service
2. Extract domains matching the pattern (e.g., `sci-hub\.\w+`, `annas-archive\.\w+`)
3. Health-check each discovered domain with a lightweight request
4. Cache working mirrors for 1 hour, blacklist failures for 5 minutes
5. Fall back to hardcoded list only if Wikipedia fetch fails
```

#### Wikipedia URLs for Mirror Discovery

```python
MIRROR_SOURCES = {
    "scihub": "https://en.wikipedia.org/wiki/Sci-Hub",
    "annas":  "https://en.wikipedia.org/wiki/Anna%27s_Archive",
}

# Regex patterns to extract domains from Wikipedia HTML
MIRROR_PATTERNS = {
    "scihub": r"sci-hub\.([a-z]{2,6})",
    "annas":  r"annas-archive\.([a-z]{2,6})",
}
```

#### Implementation

```python
import re
import httpx

def discover_mirrors(service: str) -> list[str]:
    """Fetch Wikipedia article and extract mirror domains.

    Args:
        service: 'scihub' or 'annas'
    Returns:
        List of discovered domain strings (e.g., ['sci-hub.se', 'sci-hub.ru'])
    """
    url = MIRROR_SOURCES[service]
    pattern = MIRROR_PATTERNS[service]

    try:
        resp = httpx.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=15)
        resp.raise_for_status()
        matches = set(re.findall(pattern, resp.text))
        base = "sci-hub" if service == "scihub" else "annas-archive"
        return [f"{base}.{tld}" for tld in matches]
    except Exception:
        return FALLBACK_MIRRORS[service]

def find_working_mirror(service: str) -> Optional[str]:
    """Discover mirrors, health-check them, return first working one."""
    mirrors = discover_mirrors(service)
    for mirror in mirrors:
        try:
            resp = httpx.head(f"https://{mirror}", timeout=10, follow_redirects=True)
            if resp.status_code < 500:
                return mirror
        except Exception:
            continue
    return None
```

### Hardcoded Fallback Mirrors

Used only if Wikipedia fetch fails:

```python
FALLBACK_MIRRORS = {
    "annas": [
        "annas-archive.li",
        "annas-archive.gd",
        "annas-archive.gl",
        "annas-archive.pk",
        "annas-archive.vg",
    ],
    "scihub": [
        "sci-hub.se",
        "sci-hub.st",
        "sci-hub.ru",
        "sci-hub.su",
        "sci-hub.box",
        "sci-hub.red",
        "sci-hub.mksa.top",
    ],
}
```

### Mirror Health Check

- Test mirrors on first use per session
- Cache working mirror for 1 hour
- Blacklist failures for 5 minutes
- Fall through to next mirror on failure
- Log which mirror was used for debugging

**Reminder:** Sci-Hub has not uploaded new papers since 2021. Only attempt for papers with year <= 2020.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANNAS_SECRET_KEY` | No | Anna's Archive API key (from donation). Enables fast_download API. |
| `ANNAS_DOWNLOAD_PATH` | No | Download directory (defaults to session sources dir) |
| `ANNAS_BASE_URL` | No | Override mirror URL (defaults to auto-discovery) |

## Anti-Detection

Anna's Archive uses DDoS-Guard. Requirements:
- Realistic `User-Agent` header (browser-like)
- `curl-cffi` for TLS fingerprint matching (same as Sci-Hub)
- Rate limiting: 2-second minimum between requests
- Handle HTTP 403/429 with exponential backoff

## Data Structures

```python
@dataclass
class AnnasResult:
    title: str
    authors: str
    hash: str           # MD5 hash, key identifier
    format: str         # PDF, EPUB, etc.
    size: str           # "2.3MB"
    language: str
    publisher: str
    url: str            # Full URL on Anna's Archive
    source: str = "annas_archive"
```

## Limitations

- Web scraping approach is fragile — HTML selectors can break with site updates
- API requires donation (not free)
- Domain availability is unpredictable due to legal action
- DDoS-Guard can block automated access
- Some results may be books, not papers — need to filter by `content=journal` for academic use
