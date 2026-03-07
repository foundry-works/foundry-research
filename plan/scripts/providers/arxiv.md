# Provider: arXiv

Modeled after [xiv](https://github.com/james-akl/xiv).

## Modes

### Search by Query + Category
```bash
python search.py --provider arxiv \
  --query "transformer efficiency" \
  --categories cs.AI cs.LG cs.CL \
  --limit 20 --sort relevance --days 30
```

### Boolean Category Expressions
```bash
python search.py --provider arxiv \
  --query "reinforcement learning" \
  --category-expr "(cs.AI AND cs.RO) OR cs.LG" --limit 50
```

### Download PDFs for Results
```bash
python search.py --provider arxiv \
  --query "diffusion models" --categories cs.CV \
  --limit 10 --download 1,3-5 \
  --session-dir ./deep-research-{session} --to-md
```

## API

**URL:** `https://export.arxiv.org/api/query?search_query=...&start=0&max_results=N&sortBy=...&sortOrder=descending`

**Query construction:**
```
search_query = (cat:cs.AI OR cat:cs.LG) AND (transformer efficiency)
```

**Response:** Atom XML feed parsed via `xml.etree.ElementTree`.
- Namespace: `http://www.w3.org/2005/Atom` + `http://arxiv.org/schemas/atom`
- Extracts: title, authors, published, updated, abstract, categories, links, DOI, comment

**Auth:** None. Rate limit: generous but polite at 1 RPS.

## Implementation Notes

- **Time-range filtering (`--days N`):** Sort by `submittedDate` descending, request up to 1000, client-side filter by date (API doesn't support date range directly)
- **PDF download with CAPTCHA detection (from xiv):**
  - URL: `https://arxiv.org/pdf/{id}.pdf`
  - 3-second minimum delay between downloads (arXiv ToS)
  - CAPTCHA detection: if file < 100KB, check first 1KB for `<html`, `captcha`, `<!doctype`
  - Exponential backoff on 502/503/504: 1s → 2s → 4s (3 attempts)
  - Delete suspected CAPTCHA files automatically
- **Markdown conversion:** Via `download.py --to-md` (pymupdf4llm)

## Output Fields

Standard fields plus:
- `arxiv_id`: e.g. `2510.14968v1`
- `categories`: all arXiv categories
- `primary_category`: primary category
- `comment`: often contains venue/acceptance info
- `published`, `updated`: ISO dates

## When to Use

- Latest preprints in a specific arXiv category
- Papers from last N days in a subfield
- Fast-moving fields where index lag matters (ML, AI, physics)
- arXiv-specific category taxonomy (cs.AI, cs.CL, math.CO, etc.)
