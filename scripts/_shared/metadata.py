"""Paper metadata normalization, merge logic, and JSON I/O."""

import json
import re as _re
from datetime import datetime, timezone
from pathlib import Path

from _shared.doi_utils import normalize_doi
from _shared.html_extract import strip_jats_xml

# Unified paper schema — all fields with defaults
PAPER_SCHEMA = {
    "id": "",
    "title": "",
    "authors": [],
    "year": 0,
    "abstract": "",
    "doi": "",
    "url": "",
    "pdf_url": "",
    "venue": "",
    "citation_count": 0,
    "type": "academic",
    "provider": "",
    "fetched_at": "",
    "has_pdf": False,
    "peer_reviewed": None,
    "is_retracted": False,
    "publication_types": [],
    "quality": "ok",
}

# Which provider is best for each field (later in list = higher priority)
# Spec ordering: Crossref > OpenAlex > Semantic Scholar > PubMed > others
_FIELD_PRIORITY = {
    "venue": ["pubmed", "semantic_scholar", "openalex", "crossref"],
    "volume": ["pubmed", "semantic_scholar", "openalex", "crossref"],
    "issue": ["pubmed", "semantic_scholar", "openalex", "crossref"],
    "pages": ["pubmed", "semantic_scholar", "openalex", "crossref"],
    "year": ["pubmed", "semantic_scholar", "openalex", "crossref"],
    "is_retracted": ["pubmed", "semantic_scholar", "openalex", "crossref"],
    "abstract": ["crossref", "semantic_scholar", "openalex"],
    "topics": ["crossref", "semantic_scholar", "openalex"],
    "fields_of_study": ["crossref", "semantic_scholar", "openalex"],
    "citation_count": ["crossref", "openalex", "semantic_scholar"],
    "authors": ["openalex", "semantic_scholar", "crossref"],
    "peer_reviewed": ["openalex", "crossref", "pubmed"],
    "publication_types": ["openalex", "crossref", "pubmed"],
}

# Default precedence for fields not explicitly listed
_DEFAULT_PRIORITY = ["biorxiv", "arxiv", "pubmed", "semantic_scholar", "openalex", "crossref"]


def normalize_paper(raw: dict, provider: str) -> dict:
    """Normalize paper metadata from any provider into the unified schema.

    Handles provider-specific quirks for authors, abstracts, dates, etc.

    Args:
        raw: Raw metadata dict from a provider API response.
        provider: Provider name (semantic_scholar, openalex, crossref, scholar, etc.)

    Returns:
        Dict conforming to PAPER_SCHEMA.
    """
    paper = {k: type(v)() if isinstance(v, list | dict) else v for k, v in PAPER_SCHEMA.items()}
    paper["provider"] = provider
    paper["fetched_at"] = datetime.now(timezone.utc).isoformat()

    if provider == "semantic_scholar":
        paper = _normalize_semantic_scholar(paper, raw)
    elif provider == "openalex":
        paper = _normalize_openalex(paper, raw)
    elif provider == "crossref":
        paper = _normalize_crossref(paper, raw)
    elif provider == "pubmed":
        paper = _normalize_pubmed(paper, raw)
    elif provider == "arxiv":
        paper = _normalize_arxiv(paper, raw)
    elif provider == "biorxiv":
        paper = _normalize_biorxiv(paper, raw)
    else:
        # Generic: copy matching fields directly
        for key in PAPER_SCHEMA:
            if key in raw and raw[key] is not None:
                paper[key] = raw[key]
        # Normalize authors in generic path
        if paper.get("authors"):
            paper["authors"] = [_reformat_author(a) for a in paper["authors"]]

    # Normalize DOI if present
    doi = paper["doi"]
    if isinstance(doi, str) and doi:
        paper["doi"] = normalize_doi(doi)

    # Clean abstract of JATS tags
    abstract = paper["abstract"]
    if isinstance(abstract, str) and abstract:
        paper["abstract"] = strip_jats_xml(abstract)

    return paper


def _normalize_semantic_scholar(paper: dict, raw: dict) -> dict:
    paper["title"] = raw.get("title", "")
    paper["doi"] = raw.get("externalIds", {}).get("DOI", "") or raw.get("doi", "")
    paper["url"] = raw.get("url", "")
    paper["abstract"] = raw.get("abstract", "") or ""
    paper["year"] = raw.get("year") or 0
    paper["venue"] = raw.get("venue", "") or raw.get("journal", {}).get("name", "") or ""
    paper["citation_count"] = raw.get("citationCount") or 0
    paper["pdf_url"] = (raw.get("openAccessPdf") or {}).get("url", "") or ""
    paper["has_pdf"] = bool(paper["pdf_url"])
    paper["is_retracted"] = raw.get("isRetracted", False) or False

    # Authors: [{"name": "First Last"}] → ["Last, First"]
    authors = raw.get("authors") or []
    paper["authors"] = [_reformat_author(a.get("name", "")) for a in authors if a.get("name")]

    return paper


def _normalize_openalex(paper: dict, raw: dict) -> dict:
    paper["title"] = raw.get("title", "") or ""
    paper["doi"] = (raw.get("doi") or "").replace("https://doi.org/", "")
    paper["url"] = raw.get("id", "") or ""
    paper["year"] = raw.get("publication_year") or 0
    paper["venue"] = _extract_openalex_venue(raw)
    paper["citation_count"] = raw.get("cited_by_count") or 0
    paper["type"] = "academic"
    paper["is_retracted"] = raw.get("is_retracted", False) or False

    # Abstract from inverted index
    abstract_inv = raw.get("abstract_inverted_index")
    if abstract_inv:
        paper["abstract"] = _reconstruct_abstract(abstract_inv)
    else:
        paper["abstract"] = ""

    # Authors from authorships
    authorships = raw.get("authorships") or []
    paper["authors"] = [
        _reformat_author(a.get("author", {}).get("display_name", ""))
        for a in authorships
        if a.get("author", {}).get("display_name")
    ]

    # PDF URL from open access
    oa = raw.get("open_access") or {}
    paper["pdf_url"] = oa.get("oa_url", "") or ""
    paper["has_pdf"] = bool(paper["pdf_url"])

    return paper


def _normalize_crossref(paper: dict, raw: dict) -> dict:
    # Title is an array in Crossref
    titles = raw.get("title") or []
    paper["title"] = titles[0] if titles else ""

    paper["doi"] = raw.get("DOI", "")
    paper["url"] = raw.get("URL", "") or f"https://doi.org/{raw.get('DOI', '')}"
    paper["venue"] = (raw.get("container-title") or [""])[0]
    paper["abstract"] = raw.get("abstract", "") or ""
    paper["is_retracted"] = raw.get("is-retracted", False) or False

    # Year from date-parts: [[2024, 3, 15]]
    paper["year"] = _extract_crossref_year(raw)

    # Citation count
    paper["citation_count"] = raw.get("is-referenced-by-count") or 0

    # Authors from author array
    authors = raw.get("author") or []
    paper["authors"] = [
        f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
        for a in authors
        if a.get("family")
    ]

    return paper



def _normalize_pubmed(paper: dict, raw: dict) -> dict:
    paper["title"] = raw.get("title", "") or ""
    paper["doi"] = raw.get("doi", "") or ""
    paper["url"] = raw.get("url", "") or ""
    paper["abstract"] = raw.get("abstract", "") or ""
    paper["year"] = _parse_year(raw.get("year") or raw.get("pubdate"))
    paper["authors"] = [_reformat_author(a) for a in (raw.get("authors") or [])]
    paper["venue"] = raw.get("source", "") or raw.get("fulljournalname", "") or ""
    paper["peer_reviewed"] = True  # PubMed entries are peer-reviewed by definition
    paper["publication_types"] = raw.get("publication_types") or raw.get("pubtype") or []
    return paper


def _normalize_arxiv(paper: dict, raw: dict) -> dict:
    for key in PAPER_SCHEMA:
        if key in raw and raw[key] is not None:
            paper[key] = raw[key]
    paper["provider"] = "arxiv"
    paper["peer_reviewed"] = False  # arXiv is preprints
    if paper.get("authors"):
        paper["authors"] = [_reformat_author(a) for a in paper["authors"]]
    return paper


def _normalize_biorxiv(paper: dict, raw: dict) -> dict:
    for key in PAPER_SCHEMA:
        if key in raw and raw[key] is not None:
            paper[key] = raw[key]
    paper["provider"] = "biorxiv"
    paper["peer_reviewed"] = False  # bioRxiv is preprints
    if paper.get("authors"):
        paper["authors"] = [_reformat_author(a) for a in paper["authors"]]
    return paper


def _reformat_author(name: str) -> str:
    """Convert 'First Last' to 'Last, First' format."""
    if not name or "," in name:
        return name  # Already in "Last, First" format or empty
    parts = name.strip().split()
    if len(parts) < 2:
        return name
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


_YEAR_RE = _re.compile(r'\b(19|20)\d{2}\b')


def _parse_year(value) -> int:
    """Parse year from various formats: int, 'YYYY-MM-DD', 'YYYY', '2024 Jan', etc."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value if 1900 <= value <= 2100 else 0
    if isinstance(value, float):
        return int(value) if 1900 <= value <= 2100 else 0
    if isinstance(value, str):
        value = value.strip()
        # Try direct int parse first
        try:
            year = int(value[:4])
            if 1900 <= year <= 2100:
                return year
        except (ValueError, IndexError):
            pass
        # Try regex for embedded year
        match = _YEAR_RE.search(value)
        if match:
            return int(match.group(0))
    return 0


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct plain text from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    # Build word→position mapping, then sort by position
    words: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            words.append((pos, word))
    words.sort(key=lambda x: x[0])
    return " ".join(w for _, w in words)


def _extract_crossref_year(raw: dict) -> int:
    """Extract year from Crossref date-parts format."""
    for date_field in ("published-print", "published-online", "issued", "created"):
        date_info = raw.get(date_field)
        if date_info and "date-parts" in date_info:
            parts = date_info["date-parts"]
            if parts and parts[0] and parts[0][0]:
                return int(parts[0][0])
    return 0


def _extract_openalex_venue(raw: dict) -> str:
    """Extract venue name from OpenAlex primary_location or host_venue."""
    loc = raw.get("primary_location") or {}
    source = loc.get("source") or {}
    return source.get("display_name", "") or ""


def merge_metadata(existing: dict, new: dict) -> dict:
    """Merge metadata from multiple providers with deterministic precedence.

    Fill missing fields only — never overwrite a non-empty field with
    an empty/null value from a higher-priority source.

    Args:
        existing: Current metadata dict.
        new: New metadata to merge in.

    Returns:
        Merged metadata dict.
    """
    result = dict(existing)
    new_provider = new.get("provider", "")
    existing_provider = existing.get("provider", "")

    for key, value in new.items():
        if key in ("id", "fetched_at"):
            continue  # Never overwrite ID or timestamp

        # Skip empty/null/zero values from new source
        if _is_empty(value):
            continue

        existing_value = result.get(key)

        # If existing is empty, always fill
        if _is_empty(existing_value):
            result[key] = value
            continue

        # Both have values — check field-level priority
        priority_list = _FIELD_PRIORITY.get(key, _DEFAULT_PRIORITY)
        new_rank = _provider_rank(new_provider, priority_list)
        existing_rank = _provider_rank(existing_provider, priority_list)
        if new_rank > existing_rank:
            result[key] = value

    return result


def _is_empty(value) -> bool:
    """Check if a value is empty/null/zero (should not overwrite)."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list) and not value:
        return True
    return isinstance(value, int | float) and value == 0


def _provider_rank(provider: str, priority_list: list[str]) -> int:
    """Get provider rank from a priority list. Higher = better."""
    try:
        return priority_list.index(provider)
    except ValueError:
        return -1


def write_source_metadata(metadata_dir: str, source_id: str, metadata: dict) -> None:
    """Write metadata to sources/metadata/{source_id}.json."""
    path = Path(metadata_dir)
    path.mkdir(parents=True, exist_ok=True)
    filepath = path / f"{source_id}.json"
    filepath.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_source_metadata(metadata_dir: str, source_id: str) -> dict:
    """Read metadata from sources/metadata/{source_id}.json.

    Returns empty dict if file doesn't exist.
    """
    filepath = Path(metadata_dir) / f"{source_id}.json"
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
