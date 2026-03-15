"""Perplexity search provider — web search via Perplexity Search API."""

import os
import tempfile

from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

API_BASE = "https://api.perplexity.ai"

# Perplexity returns up to 20 results
_MAX_RESULTS = 20


def add_arguments(parser):
    parser.add_argument("--include-domains", nargs="+", default=None, help="Restrict results to these domains (max 20)")
    parser.add_argument("--exclude-domains", nargs="+", default=None, help="Exclude results from these domains (max 20)")
    parser.add_argument("--recency", default=None, choices=["day", "week", "month", "year"], help="Recency filter (mutually exclusive with date filters)")
    parser.add_argument("--after-date", default=None, help="Only results published after this date (MM/DD/YYYY)")
    parser.add_argument("--before-date", default=None, help="Only results published before this date (MM/DD/YYYY)")
    parser.add_argument("--country", default=None, help="ISO country code for regional search")
    parser.add_argument("--language", nargs="+", default=None, help="ISO 639-1 language codes (max 10)")


def search(args) -> dict:
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        return error_response(
            ["PERPLEXITY_API_KEY environment variable not set"],
            error_code="auth_missing",
        )

    session_dir = args.session_dir or tempfile.mkdtemp(prefix="perplexity_")
    client = create_session(session_dir, rate_limits={"api.perplexity.ai": 1.0})

    try:
        if not args.query or not args.query.strip():
            return error_response(
                ["--query is required for Perplexity search"],
                error_code="missing_query",
            )
        return _search(client, args, api_key)
    except Exception as e:
        log(f"Perplexity API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _search(client, args, api_key: str) -> dict:
    """Search via Perplexity's /search endpoint."""
    limit = args.limit
    if limit > _MAX_RESULTS:
        log(f"Capping max_results from {limit} to {_MAX_RESULTS} (Perplexity API limit)", level="warn")
        limit = _MAX_RESULTS

    body = {
        "query": args.query,
        "max_results": limit,
    }

    # Domain filtering — Perplexity uses a single array with `-` prefix for exclusions
    domain_filter = _build_domain_filter(args.include_domains, args.exclude_domains)
    if domain_filter:
        body["search_domain_filter"] = domain_filter

    # Recency and date filters are mutually exclusive
    if args.recency:
        if args.after_date or args.before_date:
            return error_response(
                ["--recency is mutually exclusive with --after-date/--before-date"],
                error_code="invalid_args",
            )
        body["search_recency_filter"] = args.recency
    if args.after_date:
        body["search_after_date_filter"] = args.after_date
    if args.before_date:
        body["search_before_date_filter"] = args.before_date

    if args.country:
        body["country"] = args.country
    if args.language:
        body["language"] = args.language

    log(f"Perplexity search: query={args.query!r} limit={limit}")
    resp = client.post(
        f"{API_BASE}/search",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    if resp.status_code == 401:
        return error_response(["Perplexity API authentication failed — check PERPLEXITY_API_KEY"], error_code="auth_failed")
    if resp.status_code == 429:
        return error_response(["Perplexity API rate limit exceeded"], error_code="rate_limited")
    if resp.status_code != 200:
        return error_response(
            [f"Perplexity API returned {resp.status_code}: {resp.text[:500]}"],
            error_code="api_error",
        )

    data = resp.json()
    raw_results = data.get("results", [])

    results = []
    for r in raw_results:
        source = {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "abstract": r.get("snippet", ""),
            "type": "web",
            "provider": "perplexity",
        }
        year = _parse_year(r.get("date"))
        if year:
            source["year"] = year
        results.append(source)

    return success_response(
        results,
        total_results=len(results),
        provider="perplexity",
        query=args.query,
    )


def _build_domain_filter(include: list | None, exclude: list | None) -> list | None:
    """Build Perplexity's domain filter array.

    Perplexity uses a single `search_domain_filter` array where:
    - Plain domains are allowlisted
    - Domains prefixed with `-` are denylisted
    """
    if not include and not exclude:
        return None
    filters = []
    if include:
        filters.extend(include)
    if exclude:
        filters.extend(f"-{d}" for d in exclude)
    return filters


def _parse_year(date_str: str | None) -> int | None:
    """Extract year from a date string like '2024-01-15' or '2024-01-15T12:00:00Z'."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, IndexError):
        return None
