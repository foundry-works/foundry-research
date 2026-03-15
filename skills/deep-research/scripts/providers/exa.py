"""Exa search provider — web search via Exa REST API."""

import os
import tempfile

from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

API_BASE = "https://api.exa.ai"

# Exa allows up to 100, but we cap lower for budget sanity
_MAX_RESULTS = 50


def add_arguments(parser):
    parser.add_argument("--exa-type", default="auto", choices=["auto", "neural", "fast", "instant"], help="Exa search method (default: auto)")
    parser.add_argument("--category", default=None, choices=["company", "research paper", "news", "tweet", "personal site", "financial report", "people"], help="Filter by content category")
    parser.add_argument("--include-domains", nargs="+", default=None, help="Restrict results to these domains")
    parser.add_argument("--exclude-domains", nargs="+", default=None, help="Exclude results from these domains")
    parser.add_argument("--start-published-date", default=None, help="Filter by publication date (ISO 8601, e.g. 2024-01-01T00:00:00.000Z)")
    parser.add_argument("--end-published-date", default=None, help="Filter by publication date (ISO 8601)")
    parser.add_argument("--include-text", nargs="+", default=None, help="Strings that must appear in results")
    parser.add_argument("--exclude-text", nargs="+", default=None, help="Strings that must not appear in results")
    parser.add_argument("--include-highlights", action="store_true", default=False, help="Include relevant text highlights in results")


def search(args) -> dict:
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        return error_response(
            ["EXA_API_KEY environment variable not set"],
            error_code="auth_missing",
        )

    session_dir = args.session_dir or tempfile.mkdtemp(prefix="exa_")
    client = create_session(session_dir, rate_limits={"api.exa.ai": 1.0})

    try:
        if not args.query or not args.query.strip():
            return error_response(
                ["--query is required for Exa search"],
                error_code="missing_query",
            )
        return _search(client, args, api_key)
    except Exception as e:
        log(f"Exa API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _search(client, args, api_key: str) -> dict:
    """Search via Exa's /search endpoint."""
    limit = args.limit
    if limit > _MAX_RESULTS:
        log(f"Capping numResults from {limit} to {_MAX_RESULTS} (Exa limit)", level="warn")
        limit = _MAX_RESULTS

    exa_type = getattr(args, "exa_type", "auto")

    body = {
        "query": args.query,
        "numResults": limit,
        "type": exa_type,
    }

    if args.category:
        body["category"] = args.category
    if args.include_domains:
        body["includeDomains"] = args.include_domains
    if args.exclude_domains:
        body["excludeDomains"] = args.exclude_domains
    if args.start_published_date:
        body["startPublishedDate"] = args.start_published_date
    if args.end_published_date:
        body["endPublishedDate"] = args.end_published_date
    if args.include_text:
        body["includeText"] = args.include_text
    if args.exclude_text:
        body["excludeText"] = args.exclude_text
    if args.include_highlights:
        body["contents"] = {"highlights": True}

    log(f"Exa search: query={args.query!r} type={exa_type} limit={limit}" + (f" category={args.category}" if args.category else ""))
    resp = client.post(
        f"{API_BASE}/search",
        json=body,
        headers={"x-api-key": api_key},
    )

    if resp.status_code == 401:
        return error_response(["Exa API authentication failed — check EXA_API_KEY"], error_code="auth_failed")
    if resp.status_code == 402:
        return error_response(["Exa API payment required — check your Exa plan"], error_code="payment_required")
    if resp.status_code == 429:
        return error_response(["Exa API rate limit exceeded"], error_code="rate_limited")
    if resp.status_code != 200:
        return error_response(
            [f"Exa API returned {resp.status_code}: {resp.text[:500]}"],
            error_code="api_error",
        )

    data = resp.json()
    raw_results = data.get("results", [])

    results = []
    for r in raw_results:
        source = {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "abstract": _build_abstract(r),
            "type": "web",
            "provider": "exa",
        }
        year = _parse_year(r.get("publishedDate"))
        if year:
            source["year"] = year
        if r.get("author"):
            source["author"] = r["author"]
        results.append(source)

    return success_response(
        results,
        total_results=len(results),
        provider="exa",
        query=args.query,
        search_type=data.get("searchType"),
    )


def _build_abstract(r: dict) -> str:
    """Build abstract from highlights or text snippet."""
    # Prefer highlights if available (concise, query-relevant)
    highlights = r.get("highlights")
    if highlights and isinstance(highlights, list):
        return " … ".join(highlights)
    # Fall back to text snippet
    text = r.get("text", "")
    if text:
        return text[:500]
    # Last resort: summary
    return r.get("summary", "")


def _parse_year(date_str: str | None) -> int | None:
    """Extract year from an ISO 8601 date string."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, IndexError):
        return None
