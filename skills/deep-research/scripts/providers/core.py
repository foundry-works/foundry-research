"""CORE search provider — open-access academic papers via the CORE API."""

import tempfile

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.core.ac.uk/v3"


def add_arguments(parser) -> None:
    """Register CORE-specific CLI flags."""
    parser.add_argument(
        "--year-range",
        default=None,
        help="Filter by publication year range, e.g. 2020-2024",
    )
    parser.add_argument(
        "--sort",
        default=None,
        choices=["relevance", "recency", "cited_by_count"],
        help="Sort order (default: relevance)",
    )
    parser.add_argument(
        "--open-access-only",
        action="store_true",
        default=False,
        help="Return only works with full text available (default behavior for CORE, but makes it explicit)",
    )
    parser.add_argument(
        "--core-id",
        default=None,
        help="Look up a single work by CORE ID",
    )


def search(args) -> str:
    """Search CORE works and return a JSON envelope dict.

    Works with or without an API key:
    - Authenticated (personal plan): 1000 tokens/day, 25/min, full-text available
    - Unauthenticated: 100 tokens/day, 10/min, no full-text
    Free API key registration: https://core.ac.uk/services/api
    """
    session_dir = getattr(args, "session_dir", None) or tempfile.mkdtemp(prefix="core_")
    config = get_config(session_dir)
    api_key = config.get("core_api_key")

    # Rate limit: 25/min authenticated (~2.4s between), 10/min unauth (~6s between)
    rate = 0.4 if api_key else 0.15
    http = create_session(session_dir, rate_limits={"api.core.ac.uk": rate})
    if api_key:
        http.session.headers["Authorization"] = f"Bearer {api_key}"
    else:
        log("No CORE API key — using unauthenticated access (100 tokens/day, no full-text). "
            "Set CORE_API_KEY for higher limits.", level="warn")

    try:
        # Single work lookup
        core_id = getattr(args, "core_id", None)
        if core_id:
            return _id_lookup(http, core_id)

        # Keyword search
        query = getattr(args, "query", None)
        if not query:
            return error_response(
                ["--query is required for core (or use --core-id for single lookup)"],
                error_code="missing_query",
            )
        return _keyword_search(http, args)

    except Exception as e:
        log(f"CORE search failed: {e}", level="error")
        return error_response([f"CORE search failed: {e}"], error_code="provider_error")
    finally:
        http.close()


def _keyword_search(http, args) -> str:
    """Execute a keyword search against CORE /search/works."""
    query = args.query
    limit = min(getattr(args, "limit", 10), 100)  # CORE caps at 100
    offset = getattr(args, "offset", 0)

    # Build the query with year filter if specified
    search_query = query
    year_range = getattr(args, "year_range", None)
    if year_range:
        parts = year_range.split("-")
        if len(parts) == 2:
            search_query += f" yearPublished>={parts[0]} yearPublished<={parts[1]}"
        elif len(parts) == 1:
            search_query += f" yearPublished={parts[0]}"

    body = {
        "q": search_query,
        "limit": limit,
        "offset": offset,
    }

    # Sort
    sort = getattr(args, "sort", None)
    if sort:
        sort_map = {
            "relevance": "relevance",
            "recency": "publishedDate:desc",
            "cited_by_count": "citationCount:desc",
        }
        body["sort"] = sort_map.get(sort, sort)

    url = f"{BASE_URL}/search/works"
    log(f"CORE search: query={query!r}, limit={limit}, offset={offset}")
    resp = http.post(url, json=body)

    if resp.status_code != 200:
        return _handle_error(resp)

    data = resp.json()
    total = data.get("totalHits", 0)
    raw_results = data.get("results", [])

    papers = [_normalize_work(item) for item in raw_results if item.get("title")]

    return success_response(
        papers,
        total_results=total,
        provider="core",
        query=query,
        has_more=total > offset + limit,
    )


def _id_lookup(http, core_id: str) -> str:
    """Look up a single work by CORE ID."""
    url = f"{BASE_URL}/works/{core_id}"
    log(f"CORE ID lookup: {core_id}")
    resp = http.get(url)

    if resp.status_code == 404:
        return error_response([f"CORE ID not found: {core_id}"], error_code="not_found")
    if resp.status_code != 200:
        return _handle_error(resp)

    item = resp.json()
    if not item.get("title"):
        return error_response([f"CORE ID returned empty record: {core_id}"], error_code="empty_result")

    paper = _normalize_work(item)
    return success_response([paper], total_results=1, provider="core", query=core_id)


def _clean_author(name: str) -> str:
    """Clean CORE author names — some records have JATS XML prefixes (eSurname, eGiven)."""
    import re
    parts = name.split(", ")
    cleaned = []
    for part in parts:
        part = re.sub(r"^[a-z](?=[A-Z])", "", part.strip())
        cleaned.append(part)
    result = ", ".join(cleaned)
    result = re.sub(r"\be(?=[A-Z])", "", result)
    return result


def _normalize_work(item: dict) -> dict:
    """Normalize a CORE work item to the unified paper schema."""
    # Build a raw dict that _normalize_core in metadata.py can handle,
    # or normalize inline since CORE isn't in metadata.py yet.
    raw = {
        "title": item.get("title", ""),
        "doi": (item.get("doi") or "").replace("https://doi.org/", ""),
        "abstract": item.get("abstract", "") or item.get("fullTextSnippet", "") or "",
        "year": item.get("yearPublished") or 0,
        "url": _best_url(item),
        "citation_count": item.get("citationCount") or 0,
        "authors": [
            _clean_author(a.get("name", "")) for a in (item.get("authors") or []) if a.get("name")
        ],
        "venue": _extract_venue(item),
        "type": "academic",
        "provider": "core",
    }

    paper = normalize_paper(raw, "core")

    # CORE-specific fields
    paper["core_id"] = item.get("id") or ""
    paper["has_full_text"] = bool(item.get("fullText") or item.get("downloadUrl"))

    # PDF/download URL — CORE's main value-add
    download_url = item.get("downloadUrl") or ""
    if download_url:
        paper["pdf_url"] = download_url
        paper["has_pdf"] = True

    # Source repository
    data_provider = item.get("dataProvider") or {}
    if isinstance(data_provider, dict):
        paper["repository"] = data_provider.get("name", "")
    elif isinstance(data_provider, str):
        paper["repository"] = data_provider

    # Language
    language = item.get("language") or {}
    if isinstance(language, dict):
        paper["language"] = language.get("code", "")

    return paper


def _best_url(item: dict) -> str:
    """Pick the best URL from a CORE record."""
    # Prefer DOI URL, then CORE display URL, then download URL
    doi = item.get("doi") or ""
    if doi:
        clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        return f"https://doi.org/{clean}"
    # CORE URLs
    core_id = item.get("id")
    if core_id:
        return f"https://core.ac.uk/works/{core_id}"
    return item.get("downloadUrl") or item.get("sourceFulltextUrls", [""])[0] or ""


def _extract_venue(item: dict) -> str:
    """Extract venue/journal name from a CORE record."""
    journals = item.get("journals") or []
    if journals:
        j = journals[0]
        if isinstance(j, dict):
            return j.get("title", "") or j.get("name", "")
        if isinstance(j, str):
            return j
    return item.get("publisher", "") or ""


def _handle_error(resp) -> str:
    """Convert an HTTP error response into an error envelope."""
    status = resp.status_code
    try:
        body = resp.json()
        message = body.get("message", "") or body.get("error", "") or resp.text[:500]
    except Exception:
        message = resp.text[:500]

    if status == 401:
        error_code = "auth_failed"
        message = f"CORE API key invalid or expired: {message}"
    elif status == 429:
        error_code = "rate_limited"
    else:
        error_code = f"http_{status}"

    log(f"CORE API error {status}: {message}", level="error")
    return error_response([f"CORE API returned {status}: {message}"], error_code=error_code)
