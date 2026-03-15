"""Linkup search provider — web search and page extraction via Linkup REST API."""

import os
import tempfile

from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

API_BASE = "https://api.linkup.so/v1"

# Reasonable cap on results
_MAX_RESULTS = 20


def add_arguments(parser):
    parser.add_argument("--depth", default="standard", choices=["fast", "standard", "deep"], help="Search depth (default: standard)")
    parser.add_argument("--include-domains", nargs="+", default=None, help="Restrict results to these domains (max 100)")
    parser.add_argument("--exclude-domains", nargs="+", default=None, help="Exclude results from these domains (max 100)")
    parser.add_argument("--from-date", default=None, help="Filter results published after this date (ISO 8601)")
    parser.add_argument("--to-date", default=None, help="Filter results published before this date (ISO 8601)")
    parser.add_argument("--urls", nargs="+", default=None, help="Switch to fetch mode: extract content from these URLs as markdown")


def search(args) -> dict:
    api_key = os.environ.get("LINKUP_API_KEY")
    if not api_key:
        return error_response(
            ["LINKUP_API_KEY environment variable not set"],
            error_code="auth_missing",
        )

    session_dir = args.session_dir or tempfile.mkdtemp(prefix="linkup_")
    client = create_session(session_dir, rate_limits={"api.linkup.so": 1.0})

    try:
        if args.urls:
            return _fetch(client, args, api_key)
        if not args.query or not args.query.strip():
            return error_response(
                ["--query is required for Linkup search"],
                error_code="missing_query",
            )
        return _search(client, args, api_key)
    except Exception as e:
        log(f"Linkup API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _search(client, args, api_key: str) -> dict:
    """Search via Linkup's /search endpoint."""
    limit = args.limit
    if limit > _MAX_RESULTS:
        log(f"Capping max_results from {limit} to {_MAX_RESULTS} (Linkup limit)", level="warn")
        limit = _MAX_RESULTS

    body = {
        "q": args.query,
        "depth": args.depth,
        "outputType": "searchResults",
        "numResults": limit,
    }

    if args.include_domains:
        body["includeDomains"] = args.include_domains
    if args.exclude_domains:
        body["excludeDomains"] = args.exclude_domains
    if args.from_date:
        body["fromDate"] = args.from_date
    if args.to_date:
        body["toDate"] = args.to_date

    log(f"Linkup search: query={args.query!r} depth={args.depth} limit={limit}")
    resp = client.post(
        f"{API_BASE}/search",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    if resp.status_code == 401:
        return error_response(["Linkup API authentication failed — check LINKUP_API_KEY"], error_code="auth_failed")
    if resp.status_code == 429:
        return error_response(["Linkup API rate limit exceeded"], error_code="rate_limited")
    if resp.status_code != 200:
        return error_response(
            [f"Linkup API returned {resp.status_code}: {resp.text[:500]}"],
            error_code="api_error",
        )

    data = resp.json()
    raw_results = data.get("results", [])

    results = []
    for r in raw_results:
        source = {
            "title": r.get("name", ""),
            "url": r.get("url", ""),
            "abstract": r.get("content", ""),
            "type": "web",
            "provider": "linkup",
        }
        results.append(source)

    return success_response(
        results,
        total_results=len(results),
        provider="linkup",
        query=args.query,
    )


def _fetch(client, args, api_key: str) -> dict:
    """Extract content from URLs via Linkup's /fetch endpoint."""
    results = []
    failed = []

    for url in args.urls:
        body = {"url": url}
        log(f"Linkup fetch: {url}")

        try:
            resp = client.post(
                f"{API_BASE}/fetch",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )

            if resp.status_code != 200:
                log(f"Linkup fetch failed for {url}: {resp.status_code}", level="warn")
                failed.append(url)
                continue

            data = resp.json()
            markdown = data.get("markdown", "")
            results.append({
                "title": _title_from_url(url),
                "url": url,
                "abstract": markdown[:500],
                "raw_content": markdown,
                "type": "web",
                "provider": "linkup",
            })
        except Exception as e:
            log(f"Linkup fetch error for {url}: {e}", level="warn")
            failed.append(url)

    if failed:
        log(f"Linkup fetch: {len(failed)} URL(s) failed", level="warn")

    return success_response(
        results,
        total_results=len(results),
        provider="linkup",
        mode="fetch",
        failed_urls=failed,
    )


def _title_from_url(url: str) -> str:
    """Derive a readable title from a URL."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        segment = path.rsplit("/", 1)[-1]
        if "." in segment:
            segment = segment.rsplit(".", 1)[0]
        return segment.replace("-", " ").replace("_", " ").title()
    return parsed.hostname or url
