"""DOI normalization, extraction, validation, and URL canonicalization."""

import re
from urllib.parse import urlparse, urlunparse

# DOI pattern: 10.XXXX/... (registrant code / suffix)
_DOI_RE = re.compile(r'10\.\d{4,9}/[^\s]+')

# arXiv ID patterns: YYMM.NNNNN(vN) or old-style archive/YYMMNNN
_ARXIV_NEW_RE = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?')
_ARXIV_OLD_RE = re.compile(r'([a-z-]+/\d{7})(v\d+)?')


def normalize_doi(doi: str) -> str:
    """Normalize DOI to canonical form.

    - Lowercase
    - Strip URL prefixes (https://doi.org/, http://dx.doi.org/, doi:)
    - Strip trailing punctuation (., ;, ), ])
    """
    doi = doi.strip()
    # Strip common URL prefixes
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi.org/", "dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    # Strip trailing punctuation that often gets captured
    doi = doi.rstrip(".,;)]\u200b ")
    return doi.lower()


def extract_doi(text: str) -> str | None:
    """Extract a DOI from a string (URL, citation text, free text).

    Handles doi.org URLs, 'doi:' prefixes, and raw '10.XXXX/...' patterns.
    Returns normalized DOI or None.
    """
    if not text:
        return None
    match = _DOI_RE.search(text)
    if match:
        return normalize_doi(match.group(0))
    return None


def is_valid_doi(doi: str) -> bool:
    """Validate DOI format (10.XXXX/...). Does NOT check existence."""
    normalized = normalize_doi(doi)
    return bool(_DOI_RE.fullmatch(normalized))


def doi_to_url(doi: str) -> str:
    """Convert DOI to https://doi.org/... resolver URL."""
    return f"https://doi.org/{normalize_doi(doi)}"


def extract_arxiv_id(text: str) -> str | None:
    """Extract arXiv ID from URL or text.

    Handles arxiv.org/abs/, arxiv.org/pdf/, arxiv: prefix, raw YYMM.NNNNN.
    Returns the bare ID (without version suffix) or None.
    """
    if not text:
        return None

    # Strip arxiv: prefix
    cleaned = text.strip()
    if cleaned.lower().startswith("arxiv:"):
        cleaned = cleaned[6:]

    # Strip arxiv.org URL paths
    for pattern in ("arxiv.org/abs/", "arxiv.org/pdf/"):
        idx = cleaned.find(pattern)
        if idx >= 0:
            cleaned = cleaned[idx + len(pattern):]
            # Remove .pdf extension if present
            cleaned = cleaned.removesuffix(".pdf")
            break

    # Try new-style ID (YYMM.NNNNN)
    match = _ARXIV_NEW_RE.search(cleaned)
    if match:
        return match.group(1)

    # Try old-style ID (archive/YYMMNNN)
    match = _ARXIV_OLD_RE.search(cleaned)
    if match:
        return match.group(1)

    return None


def canonicalize_url(url: str) -> str:
    """Canonicalize URL for deduplication.

    Beyond basic normalization (strip fragment, query params, trailing slash),
    applies domain-specific rules:
    - arXiv: /abs/ and /pdf/ variants → /abs/ form
    - bioRxiv/medRxiv: strip version suffix (/v1, /v2)
    - Semantic Scholar: /paper/TITLE-HASH → /paper/HASH
    - PMC: /pdf/ variant → base article URL
    - doi.org: extract and normalize DOI
    """
    if not url:
        return url

    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.rstrip("/")

    # doi.org resolver → normalize to canonical DOI URL
    if host in ("doi.org", "dx.doi.org"):
        doi = normalize_doi(path.lstrip("/"))
        return f"https://doi.org/{doi}"

    # arXiv: unify abs/pdf variants
    if "arxiv.org" in host:
        arxiv_id = extract_arxiv_id(url)
        if arxiv_id:
            return f"https://arxiv.org/abs/{arxiv_id}"

    # bioRxiv / medRxiv: strip version suffix
    if host in ("www.biorxiv.org", "biorxiv.org", "www.medrxiv.org", "medrxiv.org"):
        path = re.sub(r'/v\d+$', '', path)

    # Semantic Scholar: /paper/TITLE-HASH → /paper/HASH
    if "semanticscholar.org" in host:
        match = re.search(r'/paper/(?:.*-)?([0-9a-f]{40})$', path, re.IGNORECASE)
        if match:
            path = f"/paper/{match.group(1)}"

    # PMC: strip /pdf/ variant
    if "ncbi.nlm.nih.gov" in host:
        path = re.sub(r'/pdf/?$', '', path)

    # Reconstruct with scheme and host only (no query, fragment)
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))
