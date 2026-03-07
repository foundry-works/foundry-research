# `download.py` — Content & PDF Downloader

**Purpose:** Merged `download_source.py` + `paper_download.py`. Handles web content extraction, direct PDF download, multi-source PDF cascade by DOI, arXiv download, and PDF→Markdown conversion.

## CLI Interface

### Web Content Extraction
```bash
python download.py --url "https://example.com/article" --type web \
  --source-id src-003 --title "Article Title" \
  --session-dir ./deep-research-{session}
```

### Direct PDF Download
```bash
python download.py --pdf-url "https://arxiv.org/pdf/1706.03762" \
  --source-id src-001 --session-dir ./deep-research-{session} --to-md
```

### Multi-Source PDF Cascade by DOI
```bash
python download.py --doi "10.1038/s41586-020-2649-2" \
  --source-id src-001 --session-dir ./deep-research-{session} --to-md
```

### arXiv Download by ID
```bash
python download.py --arxiv "2401.12345" \
  --source-id src-002 --session-dir ./deep-research-{session} --to-md
```

### Local Directory Ingestion
```bash
python download.py --local-dir ./my-papers/ \
  --session-dir ./deep-research-{session} --to-md
```

Walks a directory of existing PDFs (and optionally `.md`/`.html` files), assigns `src-NNN` IDs, converts PDFs to markdown, registers each file in state via `state.py add-sources`. Useful when the user already has a corpus of papers to analyze.

- Recursively finds `*.pdf`, `*.md`, `*.html` files in the directory
- Skips files already registered in state (by filename match)
- Extracts metadata from PDF front pages where possible (title, authors via pymupdf4llm)
- For PDFs: copies to `sources/src-NNN.pdf`, converts to `sources/src-NNN.md` with `--to-md`
- For `.md`/`.html`: copies to `sources/src-NNN.md` (with HTML extraction if needed)
- Registers all ingested files in state as a batch via `add-sources`

### Batch Mode
```bash
python download.py --from-json results.json --parallel 4 \
  --session-dir ./deep-research-{session} --to-md
```

### Metadata Flags (for source metadata JSON)
```bash
python download.py --url "..." --type academic \
  --source-id src-001 --title "Paper Title" \
  --authors "Vaswani, A." "Shazeer, N." \
  --doi "10.48550/arXiv.1706.03762" --year 2017 \
  --venue "NeurIPS" --citation-count 120000 \
  --session-dir ./deep-research-{session}
```

## Output

```json
{
  "source_id": "src-001",
  "doi": "10.1038/s41586-020-2649-2",
  "content_file": "sources/src-001.md",
  "pdf_file": "sources/src-001.pdf",
  "content_length": 15234,
  "pdf_size_bytes": 524288,
  "pdf_downloaded": true,
  "md_converted": true,
  "toc_file": "sources/src-001.toc",
  "source_used": "unpaywall",
  "sources_tried": ["openalex", "unpaywall"],
  "errors": []
}
```

## Multi-Source PDF Resolution Strategy

```
Input: DOI, URL, or arXiv ID
         │
         ▼
┌─────────────────────────┐
│  Normalize Input        │  → Extract DOI, detect arXiv ID, classify URL type
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  Route by Input Type    │
│                         │
│  arXiv ID → arXiv       │  (free, direct, highest priority)
│  PMC URL  → PMC         │  (free, direct)
│  PDF URL  → Direct DL   │  (already have the link)
│  DOI/URL  → OA cascade  │  (see below)
└────────────┬────────────┘
             ▼
┌─────────────────────────────────────────────┐
│  OA Source Cascade (for DOIs)               │
│                                             │
│  1. OpenAlex  (open_access.oa_url)          │  API call needs key; resulting PDF URL is direct
│  2. Unpaywall (best_oa_location.url_for_pdf)│  Needs email, reliable
│  3. arXiv     (if arXiv ID in externalIds)  │  Free preprints
│  4. PMC       (if PMCID in externalIds)     │  Free full text
│  5. Anna's Archive (/scidb/{doi})           │  Aggregates LibGen/Z-Lib/Sci-Hub; see annas-archive.md
│  6. Sci-Hub   (pre-2021 papers only)        │  Last resort fallback
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────┐
│  Download PDF           │  Stream to sources/{id}.pdf
│  Convert to Markdown    │  pymupdf4llm → sources/{id}.md (if --to-md)
└─────────────────────────┘
```

## Source Implementations

| Source | How it works | Coverage | Auth |
|--------|-------------|----------|------|
| **OpenAlex** | `GET api.openalex.org/works/doi:{doi}` → `open_access.oa_url` | Broad OA coverage | API key (for the API call; the resulting OA URL is a direct download) |
| **Unpaywall** | `GET api.unpaywall.org/v2/{doi}?email={email}` → `best_oa_location.url_for_pdf` | Best OA discovery | Email |
| **arXiv** | `GET arxiv.org/pdf/{id}.pdf` | Preprints only | None |
| **PMC** | `GET ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/` | NIH-funded papers | None |
| **Direct PDF** | Download URL directly | When URL ends in `.pdf` | None |
| **Sci-Hub** | Try mirrors → parse HTML for PDF iframe | Pre-2021, ~85% | None |

### Anna's Archive

See [annas-archive.md](./annas-archive.md) for full integration spec. Summary:
- DOI lookup via `/scidb/{doi}` → extract MD5 hash → download
- Optional JSON API with `ANNAS_SECRET_KEY` (faster, more reliable)
- Web scraping fallback (no auth required)
- Aggregates LibGen, Z-Library, and Sci-Hub data — broader coverage than Sci-Hub alone

### Sci-Hub Mirror Strategy

See shared mirror discovery in [annas-archive.md](./annas-archive.md#strategy-wikipedia-as-dynamic-mirror-source).

```python
# Hardcoded fallback mirrors (used only if Wikipedia discovery fails)
FALLBACK_MIRRORS = [
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
    "https://sci-hub.su",
    "https://sci-hub.box",
    "https://sci-hub.red",
    "https://sci-hub.mksa.top",
]
```

**Mirror discovery:** On first Sci-Hub/Anna's Archive attempt per session, curl the Wikipedia articles to extract current mirror domains dynamically. Health-check discovered mirrors, cache working ones for 1 hour. Fall back to hardcoded list only if Wikipedia fetch fails.

- Test discovered mirrors with a known-good DOI to find working ones
- Cache working mirror for 1 hour, blacklist failures for 5 minutes
- Parse response HTML: look for `<iframe id="pdf">` src or `<button onclick="...">` URL
- Only attempt for papers with year ≤ 2020

### arXiv CAPTCHA Detection (from xiv)

- 3-second minimum delay between downloads (arXiv ToS)
- If file < 100KB, check first 1KB for `<html`, `captcha`, `<!doctype`
- Exponential backoff on 502/503/504
- Delete suspected CAPTCHA files automatically

## PDF Handling (consolidated from `_shared/pdf_utils.py`)

```python
def download_pdf(url: str, dest_path: str, timeout: int = 60, max_size_mb: int = 50) -> dict:
    """Download PDF with validation. Returns {"success": bool, "size_bytes": int, "errors": []}."""

def validate_pdf(path: str) -> bool:
    """Check %PDF magic bytes and file isn't truncated."""

def pdf_to_markdown(pdf_path: str, md_path: str, timeout: int = 60) -> dict:
    """Convert PDF to Markdown via pymupdf4llm with a strict timeout (default 60s).
    Also generates a .toc companion file via generate_toc().

    The timeout is enforced via a subprocess wrapper (not a signal-based alarm) so that
    runaway pymupdf4llm processes are reliably killed even when they hang in C extensions.
    SEC filings and 100+ page dissertations are the most common timeout triggers.

    Fallback: If pymupdf4llm fails, hangs past timeout, or crashes (common with malformed PDFs,
    complex two-column LaTeX, or heavy equation rendering), falls back to pypdf for raw text
    extraction. The pypdf fallback produces lower-quality output (no heading detection, no
    layout preservation) but ensures the paper content is never lost entirely. When the fallback
    is used, prepends a warning: '<!-- WARNING: PDF conversion fell back to raw text extraction.
    Layout and headings may be missing. -->'

    After conversion, runs a structural quality check:
    - If the markdown has fewer than 1 line break per 500 characters, or
    - If >20% of characters are non-alphanumeric (excluding whitespace and common punctuation),
    sets quality: "degraded" in the source metadata JSON. This gives Claude a programmatic signal
    to distrust the extracted text and seek the information from abstracts or other sources.

    Returns {"success": bool, "content_length": int, "toc_file": str | None,
             "converter": "pymupdf4llm" | "pypdf", "quality": "ok" | "degraded"}."""

def generate_toc(md_path: str, toc_path: str) -> dict:
    """Scan a converted Markdown file for headings (# lines) and generate a table-of-contents
    file with line numbers. Output format (one per line): 'LINE_NUMBER\tHEADING_LEVEL\tHEADING_TEXT'.
    Example: '450\t2\tMethodology'. Claude can use this to make precise offset/limit reads
    without scanning the entire file. Returns {"headings": int, "toc_file": str}.

    Fallback: If 0 headings are detected (common with two-column PDFs or non-standard layouts),
    prepend a warning line to the .md file: '<!-- WARNING: No headings detected during PDF conversion.
    Document structure may be garbled. Use Grep to locate sections by keyword instead of offset/limit. -->'
    and set toc_file to None in the return value. This signals Claude to fall back to keyword search
    or chunked sequential reading rather than relying on targeted offsets."""
```

## Web Content Extraction

- Fetch via `requests`, extract readable text (strip HTML)
- Uses `_shared/html_extract.py` for `extract_readable_content()`
- Save as `sources/{source-id}.md` with metadata in `sources/metadata/{source-id}.json`

## Metadata / Content Separation

Structured metadata and raw source text are stored in **separate files** to prevent LLM context contamination and schema corruption:

```
sources/
├── metadata/
│   ├── src-001.json     # Structured metadata (machine-parsed)
│   └── src-002.json
├── src-001.md           # Pure markdown content (no frontmatter)
├── src-001.pdf          # PDF when available
├── src-001.toc          # Table of contents (line numbers + headings)
└── src-002.md
```

### Metadata file (`sources/metadata/src-001.json`)

```json
{
  "id": "src-001",
  "title": "Paper Title",
  "authors": ["Author A", "Author B"],
  "year": 2024,
  "url": "https://...",
  "doi": "10.1234/...",
  "pdf_url": "https://...",
  "venue": "Conference/Journal",
  "citation_count": 42,
  "type": "academic",
  "provider": "semantic_scholar",
  "fetched_at": "2026-03-07T14:35:00Z",
  "has_pdf": true,
  "quality": "ok"
}
```

### Why not YAML frontmatter?

1. **LLM contamination:** When reading source files, Claude often attempts to modify embedded YAML frontmatter — hallucinating fields, breaking schema, or corrupting the metadata block. Separating metadata into a JSON file that Python scripts own (and Claude reads but doesn't edit) eliminates this.
2. **Token efficiency:** Reading a source for its text content no longer loads 20-30 lines of metadata into the context window. Claude reads metadata only when it needs it (via `state.py get-source` or by reading the JSON file directly).
3. **Safer parsing:** Python `json.load()` is stricter and more predictable than YAML parsing. No ambiguity around quoting, multi-line strings, or special characters in titles/abstracts.

### Migration from YAML frontmatter

The `_shared/metadata.py` module's `write_source_metadata()` function writes to `sources/metadata/{id}.json` instead of prepending YAML frontmatter to the `.md` file. The `read_source_metadata()` function reads from the JSON file. All other scripts (`state.py get-source`, `enrich.py`, `download.py`) use these functions — they never parse frontmatter from `.md` files directly.

## Phase 2 Extension: Figure/Image Extraction

The current pipeline discards visual information (charts, graphs, figures). In ML, physics, and medicine papers, core findings are often in figures. `pymupdf4llm` can extract images during conversion.

**Extension path (not Phase 1):**
- During `pdf_to_markdown()`, extract images to `sources/src-NNN_figures/`
- Record image paths in metadata JSON: `"figures": ["sources/src-001_figures/fig1.png", ...]`
- Reader subagents can use Claude's multimodal capabilities to analyze figures alongside text
- Add a `--extract-figures` flag to `download.py` (off by default to avoid disk bloat)

## Error Handling

- Per-source timeout: 15s for metadata lookups, 60s for PDF downloads
- Retry: 2 attempts per source with 2s delay
- PDF validation: verify `%PDF` magic bytes
- HTML rejection: detect when server returns HTML instead of PDF
- Size limit: skip PDFs > 50MB with warning
- Graceful degradation: if PDF fails but abstract is available, save abstract-only `.md`

## Dependencies

`_shared/` (config, output, http_client, rate_limiter, doi_utils, metadata, html_extract) + `pymupdf4llm` (for `--to-md`) + `beautifulsoup4` (for HTML parsing) + `curl-cffi` (for Cloudflare bypass).
