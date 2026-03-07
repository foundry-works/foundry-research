"""OpenAlex search provider — academic works via the OpenAlex API."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.openalex.org"

# Polite-pool email used when no API key is configured
_DEFAULT_MAILTO = "deep-research-tool@users.noreply.github.com"


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


def search(args) -> dict:
    """Search OpenAlex works and return a JSON envelope dict."""
    query = getattr(args, "query", None)
    if not query:
        return error_response(["--query is required for openalex"], error_code="missing_query")

    limit = min(getattr(args, "limit", 10), 200)  # OpenAlex caps per_page at 200
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
