"""OpenAlex search provider — academic works via the OpenAlex API."""

import tempfile

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.openalex.org"

# Polite-pool email used when no API key is configured
_DEFAULT_MAILTO = "deep-research-tool@users.noreply.github.com"

# Cap cursor pagination to avoid unbounded API calls on large --offset values.
# 10 pages × 200 per_page = 2000 results — beyond this, relevance degrades anyway.
_MAX_CURSOR_PAGES = 10


def add_arguments(parser) -> None:
    """Register OpenAlex-specific CLI flags."""
    parser.add_argument(
        "--year-range",
        default=None,
        help="Filter by publication year range, e.g. 2020-2024",
    )
    parser.add_argument(
        "--open-access-only",
        action="store_true",
        default=False,
        help="Return only open-access works",
    )
    parser.add_argument(
        "--sort",
        default=None,
        dest="sort",
        help="Sort order, e.g. cited_by_count:desc or publication_date:desc",
    )
    parser.add_argument(
        "--cited-by",
        default=None,
        dest="cited_by",
        help="DOI or OpenAlex Work ID — return papers that cite this work (forward citations)",
    )
    parser.add_argument(
        "--references",
        default=None,
        help="DOI or OpenAlex Work ID — return papers cited by this work (backward references)",
    )


def search(args) -> dict:
    """Search OpenAlex works and return a JSON envelope dict."""
    # Citation traversal modes
    cited_by = getattr(args, "cited_by", None)
    references = getattr(args, "references", None)
    if cited_by or references:
        return _citation_traversal(args, cited_by=cited_by, references=references)

    query = getattr(args, "query", None)
    if not query:
        return error_response(["--query is required for openalex"], error_code="missing_query")

    raw_limit = getattr(args, "limit", 10)
    limit = min(raw_limit, 200)  # OpenAlex caps per_page at 200
    if raw_limit > 200:
        log(f"OpenAlex: --limit {raw_limit} exceeds API max of 200; capping to 200", level="warn")
    offset = getattr(args, "offset", 0)
    session_dir = getattr(args, "session_dir", None) or tempfile.mkdtemp(prefix="openalex_")

    config = get_config(session_dir)
    api_key = config.get("openalex_api_key")

    http = create_session(session_dir)

    try:
        # Build query parameters
        params: dict[str, str | int] = {
            "search": query,
            "per_page": limit,
        }

        # Authentication: API key header or polite mailto param
        headers: dict[str, str] = {}
        if api_key:
            headers["api_key"] = api_key
        else:
            params["mailto"] = _DEFAULT_MAILTO

        # Build filters
        filters = _build_filters(args)
        if filters:
            params["filter"] = ",".join(filters)

        # Sort
        sort_value = getattr(args, "sort", None)
        if sort_value:
            params["sort"] = sort_value

        # Pagination: OpenAlex uses cursor-based pagination.
        # For offset > 0 we must skip pages by advancing the cursor.
        params["cursor"] = "*"  # initial cursor

        results = []
        total_results = 0
        next_cursor = None
        pages_to_skip = offset // limit if limit > 0 else 0
        items_to_skip = offset % limit if limit > 0 else 0

        # Advance through pages to reach the requested offset
        if pages_to_skip >= _MAX_CURSOR_PAGES:
            log(f"OpenAlex: offset {offset} requires {pages_to_skip} pages of cursor pagination "
                f"(max {_MAX_CURSOR_PAGES}). Capping.", level="warn")
            pages_to_skip = _MAX_CURSOR_PAGES - 1
            items_to_skip = 0

        for page_num in range(pages_to_skip + 1):
            url = f"{BASE_URL}/works"
            log(f"OpenAlex request: page {page_num + 1}, cursor={params.get('cursor', '*')[:20]}...")

            resp = http.get(url, params=params, headers=headers)

            if resp.status_code != 200:
                return _handle_error(resp)

            data = resp.json()
            meta = data.get("meta", {})
            total_results = meta.get("count", 0)
            next_cursor = meta.get("next_cursor")

            if page_num < pages_to_skip:
                # Still skipping pages — advance cursor
                if not next_cursor:
                    # Ran out of results before reaching offset
                    return success_response([], total_results=total_results, has_more=False)
                params["cursor"] = next_cursor
                continue

            # This is the target page
            raw_results = data.get("results", [])

            # Skip remaining items within the page if offset isn't page-aligned
            if items_to_skip > 0:
                raw_results = raw_results[items_to_skip:]

            results = [_normalize_work(work) for work in raw_results]

        return success_response(results, total_results=total_results, has_more=bool(next_cursor))

    except Exception as e:
        log(f"OpenAlex search failed: {e}", level="error")
        return error_response([f"OpenAlex search failed: {e}"], error_code="provider_error")
    finally:
        http.close()


def _resolve_openalex_id(identifier: str, http, headers: dict, params_base: dict) -> str | None:
    """Resolve a DOI or OpenAlex ID to an OpenAlex Work ID (W-prefixed).

    Accepts: DOI (10.xxx or DOI:10.xxx), OpenAlex ID (W1234 or https://openalex.org/W1234),
    or Semantic Scholar hex ID (ignored — returns None).
    """
    identifier = identifier.strip()

    # Already an OpenAlex ID
    if identifier.startswith("W") and identifier[1:].isdigit():
        return identifier
    if identifier.startswith("https://openalex.org/W"):
        return identifier.split("/")[-1]

    # DOI — look up via OpenAlex
    doi = identifier
    if doi.startswith("DOI:"):
        doi = doi[4:]
    if "/" in doi:
        url = f"{BASE_URL}/works/https://doi.org/{doi}"
        try:
            resp = http.get(url, params=params_base, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                oa_id = data.get("id", "")
                if oa_id:
                    return oa_id.split("/")[-1]  # extract W-ID from URL
        except Exception as e:
            log(f"OpenAlex DOI lookup failed for {doi}: {e}", level="warn")
    return None


def _citation_traversal(args, cited_by: str | None = None, references: str | None = None) -> dict:
    """Citation traversal via OpenAlex filter API.

    - cited_by: return papers that cite the given work (forward citations)
      Uses filter=cites:WORK_ID
    - references: return papers cited by the given work (backward references)
      Uses filter=cited_by:WORK_ID
    """
    identifier = cited_by or references
    limit = min(getattr(args, "limit", 10), 200)
    session_dir = getattr(args, "session_dir", None) or __import__("tempfile").mkdtemp(prefix="openalex_")

    config = get_config(session_dir)
    api_key = config.get("openalex_api_key")
    http = create_session(session_dir)

    headers: dict[str, str] = {}
    params_base: dict[str, str] = {}
    if api_key:
        headers["api_key"] = api_key
    else:
        params_base["mailto"] = _DEFAULT_MAILTO

    try:
        # Resolve identifier to OpenAlex Work ID
        work_id = _resolve_openalex_id(identifier, http, headers, params_base)
        if not work_id:
            return error_response(
                [f"Could not resolve '{identifier}' to an OpenAlex Work ID. "
                 "Pass a DOI (e.g., 10.1234/abc) or OpenAlex ID (e.g., W1234567890)."],
                error_code="resolve_failed",
            )

        # Build filter: cites for forward citations, cited_by for backward references
        if cited_by:
            filter_str = f"cites:{work_id}"
            mode = "cited_by"
        else:
            filter_str = f"cited_by:{work_id}"
            mode = "references"

        params = {
            **params_base,
            "filter": filter_str,
            "per_page": limit,
            "sort": "cited_by_count:desc",
            "cursor": "*",
        }

        # Apply additional filters
        extra_filters = _build_filters(args)
        if extra_filters:
            params["filter"] = ",".join([filter_str] + extra_filters)

        url = f"{BASE_URL}/works"
        log(f"OpenAlex {mode}: {identifier} → {work_id}")
        resp = http.get(url, params=params, headers=headers)

        if resp.status_code != 200:
            return _handle_error(resp)

        data = resp.json()
        meta = data.get("meta", {})
        total_results = meta.get("count", 0)
        raw_results = data.get("results", [])
        results = [_normalize_work(work) for work in raw_results]

        # Apply min_citations filter if specified
        min_citations = getattr(args, "min_citations", None)
        if min_citations:
            results = [r for r in results if (r.get("citation_count") or 0) >= min_citations]

        return success_response(
            results,
            total_results=total_results,
            has_more=bool(meta.get("next_cursor")),
            mode=mode,
            paper_id=identifier,
        )
    except Exception as e:
        log(f"OpenAlex citation traversal failed: {e}", level="error")
        return error_response([f"OpenAlex citation traversal failed: {e}"], error_code="provider_error")
    finally:
        http.close()


def _build_filters(args) -> list[str]:
    """Build OpenAlex filter components from CLI args."""
    filters: list[str] = []

    year_range = getattr(args, "year_range", None)
    if year_range:
        # Expect format YYYY-YYYY
        filters.append(f"publication_year:{year_range}")

    open_access_only = getattr(args, "open_access_only", False)
    if open_access_only:
        filters.append("is_oa:true")

    return filters


def _normalize_work(work: dict) -> dict:
    """Normalize a single OpenAlex work to the unified paper schema with extra fields."""
    paper = normalize_paper(work, "openalex")

    # Extra OpenAlex-specific fields
    oa = work.get("open_access") or {}
    paper["is_open_access"] = oa.get("is_oa", False)
    paper["oa_url"] = oa.get("oa_url") or ""

    percentile = work.get("cited_by_percentile_year") or {}
    paper["cited_by_percentile"] = percentile.get("min")

    topics = work.get("topics") or []
    paper["topics"] = [t.get("display_name", "") for t in topics if t.get("display_name")]

    return paper


def _handle_error(resp) -> dict:
    """Convert an HTTP error response into an error envelope."""
    status = resp.status_code

    try:
        body = resp.json()
        message = body.get("message", resp.text[:500])
    except Exception:
        message = resp.text[:500]

    if status == 403:
        error_code = "auth_failed"
    elif status == 429:
        error_code = "rate_limited"
    else:
        error_code = f"http_{status}"

    log(f"OpenAlex API error {status}: {message}", level="error")
    return error_response([f"OpenAlex API returned {status}: {message}"], error_code=error_code)
