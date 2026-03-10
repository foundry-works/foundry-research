"""Crossref search provider — academic works via the Crossref REST API."""

import tempfile

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.crossref.org"

# Polite-pool email — Crossref gives faster responses with a mailto param
_DEFAULT_MAILTO = "deep-research-tool@users.noreply.github.com"


def add_arguments(parser) -> None:
    """Register Crossref-specific CLI flags."""
    parser.add_argument(
        "--year-range",
        default=None,
        help="Filter by publication year range, e.g. 2020-2024",
    )
    parser.add_argument(
        "--type",
        default=None,
        dest="work_type",
        help="Filter by work type: journal-article, book-chapter, proceedings-article, etc.",
    )
    parser.add_argument(
        "--sort",
        default=None,
        choices=["relevance", "published", "is-referenced-by-count", "references-count"],
        help="Sort order (default: relevance)",
    )
    parser.add_argument(
        "--order",
        default="desc",
        choices=["asc", "desc"],
        help="Sort direction (default: desc)",
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Filter by subject, e.g. 'psychology' or 'computer science'",
    )
    parser.add_argument(
        "--issn",
        default=None,
        help="Filter to a specific journal by ISSN",
    )
    parser.add_argument(
        "--doi",
        default=None,
        help="Look up a single work by DOI",
    )


def search(args) -> dict:
    """Search Crossref works and return a JSON envelope dict."""
    session_dir = getattr(args, "session_dir", None) or tempfile.mkdtemp(prefix="crossref_")
    config = get_config(session_dir)

    http = create_session(session_dir, rate_limits={"api.crossref.org": 0.1})

    try:
        # DOI lookup mode
        doi = getattr(args, "doi", None)
        if doi:
            return _doi_lookup(http, doi, config)

        # Keyword search mode
        query = getattr(args, "query", None)
        if not query:
            return error_response(
                ["--query is required for crossref (or use --doi for single lookup)"],
                error_code="missing_query",
            )
        return _keyword_search(http, args, config)

    except Exception as e:
        log(f"Crossref search failed: {e}", level="error")
        return error_response([f"Crossref search failed: {e}"], error_code="provider_error")
    finally:
        http.close()


def _keyword_search(http, args, config: dict) -> dict:
    """Execute a keyword search against Crossref /works."""
    query = args.query
    limit = min(getattr(args, "limit", 10), 1000)
    offset = getattr(args, "offset", 0)

    params: dict[str, str | int] = {
        "query": query,
        "rows": limit,
        "offset": offset,
        "mailto": config.get("crossref_mailto", _DEFAULT_MAILTO),
    }

    # Filters
    filters = _build_filters(args)
    if filters:
        params["filter"] = ",".join(filters)

    # Sort
    sort = getattr(args, "sort", None)
    if sort:
        params["sort"] = sort
        params["order"] = getattr(args, "order", "desc")
        # Warn when citation sort is used without subject — returns highly-cited
        # papers from unrelated fields (physics, management) instead of the target discipline.
        if sort == "is-referenced-by-count" and not getattr(args, "subject", None):
            log("WARNING: --sort is-referenced-by-count without --subject returns cross-discipline noise. "
                "Add --subject to constrain results to the target field.", level="warn")

    url = f"{BASE_URL}/works"
    log(f"Crossref search: query={query!r}, limit={limit}, offset={offset}")
    resp = http.get(url, params=params)

    if resp.status_code != 200:
        return _handle_error(resp)

    data = resp.json()
    message = data.get("message", {})
    raw_items = message.get("items", [])
    total = message.get("total-results", len(raw_items))

    papers = [_normalize_work(item) for item in raw_items if item.get("title")]

    return success_response(
        papers,
        total_results=total,
        provider="crossref",
        query=query,
        has_more=total > offset + limit,
    )


def _doi_lookup(http, doi: str, config: dict) -> dict:
    """Look up a single work by DOI."""
    # Strip URL prefix if present
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

    url = f"{BASE_URL}/works/{doi}"
    params = {"mailto": config.get("crossref_mailto", _DEFAULT_MAILTO)}
    log(f"Crossref DOI lookup: {doi}")
    resp = http.get(url, params=params)

    if resp.status_code == 404:
        return error_response([f"DOI not found: {doi}"], error_code="not_found")
    if resp.status_code != 200:
        return _handle_error(resp)

    data = resp.json()
    item = data.get("message", {})
    if not item.get("title"):
        return error_response([f"DOI returned empty record: {doi}"], error_code="empty_result")

    paper = _normalize_work(item)
    return success_response([paper], total_results=1, provider="crossref", query=doi)


def _build_filters(args) -> list[str]:
    """Build Crossref filter string from CLI args."""
    filters: list[str] = []

    year_range = getattr(args, "year_range", None)
    if year_range:
        parts = year_range.split("-")
        if len(parts) == 2:
            filters.append(f"from-pub-date:{parts[0]}")
            filters.append(f"until-pub-date:{parts[1]}")
        elif len(parts) == 1:
            filters.append(f"from-pub-date:{parts[0]}")
            filters.append(f"until-pub-date:{parts[0]}")

    work_type = getattr(args, "work_type", None)
    if work_type:
        filters.append(f"type:{work_type}")

    issn = getattr(args, "issn", None)
    if issn:
        filters.append(f"issn:{issn}")

    subject = getattr(args, "subject", None)
    if subject:
        filters.append(f"has-abstract:true")

    return filters


def _normalize_work(item: dict) -> dict:
    """Normalize a Crossref work item to the unified paper schema."""
    paper = normalize_paper(item, "crossref")

    # Extra Crossref-specific fields
    paper["references_count"] = item.get("references-count") or 0
    paper["is_open_access"] = bool(
        any(
            link.get("content-type") == "application/pdf"
            for link in (item.get("link") or [])
        )
    )

    # License info
    licenses = item.get("license") or []
    if licenses:
        paper["license"] = licenses[0].get("URL", "")

    # Subject categories
    paper["subjects"] = item.get("subject") or []

    # PDF link if available
    links = item.get("link") or []
    for link in links:
        if link.get("content-type") == "application/pdf":
            paper["pdf_url"] = link.get("URL", "")
            paper["has_pdf"] = True
            break

    return paper


def _handle_error(resp) -> dict:
    """Convert an HTTP error response into an error envelope."""
    status = resp.status_code
    try:
        body = resp.json()
        message = body.get("message", resp.text[:500])
        if isinstance(message, dict):
            message = str(message)
    except Exception:
        message = resp.text[:500]

    if status == 429:
        error_code = "rate_limited"
    else:
        error_code = f"http_{status}"

    log(f"Crossref API error {status}: {message}", level="error")
    return error_response([f"Crossref API returned {status}: {message}"], error_code=error_code)
