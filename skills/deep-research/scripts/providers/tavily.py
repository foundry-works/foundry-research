"""Tavily search provider — web search and page extraction via Tavily REST API."""

import os
import tempfile

from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

API_BASE = "https://api.tavily.com"

# Tavily hard-limits max_results at 20
_MAX_RESULTS = 20


def add_arguments(parser):
    parser.add_argument("--search-depth", default="basic", choices=["basic", "advanced"], help="Search depth (default: basic). Advanced does deeper scraping.")
    parser.add_argument("--topic", default="general", choices=["general", "news"], help="Search topic (default: general). News enables published_date.")
    parser.add_argument("--include-domains", nargs="+", default=None, help="Restrict results to these domains")
    parser.add_argument("--exclude-domains", nargs="+", default=None, help="Exclude results from these domains")
    parser.add_argument("--urls", nargs="+", default=None, help="Switch to extract mode: extract content from these URLs")
    parser.add_argument("--extract-depth", default="basic", choices=["basic", "advanced"], help="Extraction depth for --urls mode (default: basic)")
    parser.add_argument("--include-raw-content", action="store_true", default=False, help="Include full page content in search results (can be very large)")


def search(args) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return error_response(
            ["TAVILY_API_KEY environment variable not set"],
            error_code="auth_missing",
        )

    session_dir = args.session_dir or tempfile.mkdtemp(prefix="tavily_")
    client = create_session(session_dir, rate_limits={"api.tavily.com": 1.0})

    try:
        if args.urls:
            return _extract(client, args, api_key)
        if not args.query or not args.query.strip():
            return error_response(
                ["--query is required for Tavily search"],
                error_code="missing_query",
            )
        return _search(client, args, api_key)
    except Exception as e:
        log(f"Tavily API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _search(client, args, api_key: str) -> dict:
    """Search via Tavily's /search endpoint."""
    limit = args.limit
    if limit > _MAX_RESULTS:
        log(f"Capping max_results from {limit} to {_MAX_RESULTS} (Tavily API limit)", level="warn")
        limit = _MAX_RESULTS

    body = {
        "query": args.query,
        "search_depth": args.search_depth,
        "topic": args.topic,
        "max_results": limit,
        "include_raw_content": args.include_raw_content,
    }
    if args.include_domains:
        body["include_domains"] = args.include_domains
    if args.exclude_domains:
        body["exclude_domains"] = args.exclude_domains

    log(f"Tavily search: query={args.query!r} depth={args.search_depth} topic={args.topic} limit={limit}")
    resp = client.post(
        f"{API_BASE}/search",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    if resp.status_code == 401:
        return error_response(["Tavily API authentication failed — check TAVILY_API_KEY"], error_code="auth_failed")
    if resp.status_code == 429:
        return error_response(["Tavily API rate limit exceeded"], error_code="rate_limited")
    if resp.status_code != 200:
        return error_response(
            [f"Tavily API returned {resp.status_code}: {resp.text[:500]}"],
            error_code="api_error",
        )

    data = resp.json()
    raw_results = data.get("results", [])

    results = []
    for r in raw_results:
        source = {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "abstract": r.get("content", ""),
            "type": "web",
        }
        year = _parse_year(r.get("published_date"))
        if year:
            source["year"] = year
        if args.include_raw_content and r.get("raw_content"):
            source["raw_content"] = r["raw_content"]
        results.append(source)

    return success_response(
        results,
        total_results=len(results),
        provider="tavily",
        query=args.query,
        response_time=data.get("response_time"),
    )


def _extract(client, args, api_key: str) -> dict:
    """Extract content from URLs via Tavily's /extract endpoint."""
    body = {
        "urls": args.urls,
        "extract_depth": args.extract_depth,
    }

    log(f"Tavily extract: {len(args.urls)} URL(s) depth={args.extract_depth}")
    resp = client.post(
        f"{API_BASE}/extract",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    if resp.status_code == 401:
        return error_response(["Tavily API authentication failed — check TAVILY_API_KEY"], error_code="auth_failed")
    if resp.status_code == 429:
        return error_response(["Tavily API rate limit exceeded"], error_code="rate_limited")
    if resp.status_code != 200:
        return error_response(
            [f"Tavily API returned {resp.status_code}: {resp.text[:500]}"],
            error_code="api_error",
        )

    data = resp.json()
    raw_results = data.get("results", [])
    failed = data.get("failed_results", [])

    results = []
    for r in raw_results:
        url = r.get("url", "")
        results.append({
            "title": _title_from_url(url),
            "url": url,
            "abstract": r.get("raw_content", "")[:500],
            "raw_content": r.get("raw_content", ""),
            "type": "web",
        })

    if failed:
        log(f"Tavily extract: {len(failed)} URL(s) failed", level="warn")

    return success_response(
        results,
        total_results=len(results),
        provider="tavily",
        mode="extract",
        failed_urls=failed,
    )


def _parse_year(date_str: str | None) -> int | None:
    """Extract year from a date string like '2024-01-15' or '2024-01-15T12:00:00Z'."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, IndexError):
        return None


def _title_from_url(url: str) -> str:
    """Derive a readable title from a URL."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        # Use last path segment, replace hyphens/underscores with spaces
        segment = path.rsplit("/", 1)[-1]
        # Remove file extension
        if "." in segment:
            segment = segment.rsplit(".", 1)[0]
        return segment.replace("-", " ").replace("_", " ").title()
    return parsed.hostname or url
