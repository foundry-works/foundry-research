"""Gensee search provider — web search via Gensee REST API."""

import os
import tempfile

from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

API_BASE = "https://app.gensee.ai/api"

# Reasonable cap on results
_MAX_RESULTS = 20


def add_arguments(parser):
    parser.add_argument("--search-mode", default="evidence", choices=["evidence", "digest"], help="Search mode (default: evidence). Evidence returns raw content for LLM processing.")


def search(args) -> str:
    api_key = os.environ.get("GENSEE_API_KEY")
    if not api_key:
        return error_response(
            ["GENSEE_API_KEY environment variable not set"],
            error_code="auth_missing",
        )

    session_dir = args.session_dir or tempfile.mkdtemp(prefix="gensee_")
    client = create_session(session_dir, rate_limits={"app.gensee.ai": 1.0})

    try:
        if not args.query or not args.query.strip():
            return error_response(
                ["--query is required for Gensee search"],
                error_code="missing_query",
            )
        return _search(client, args, api_key)
    except Exception as e:
        log(f"Gensee API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _search(client, args, api_key: str) -> str:
    """Search via Gensee's /search endpoint."""
    limit = args.limit
    if limit > _MAX_RESULTS:
        log(f"Capping max_results from {limit} to {_MAX_RESULTS} (Gensee limit)", level="warn")
        limit = _MAX_RESULTS

    body = {
        "query": args.query,
        "max_results": limit,
        "mode": args.search_mode,
    }

    log(f"Gensee search: query={args.query!r} mode={args.search_mode} limit={limit}")
    resp = client.post(
        f"{API_BASE}/search",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    if resp.status_code == 401:
        return error_response(["Gensee API authentication failed — check GENSEE_API_KEY"], error_code="auth_failed")
    if resp.status_code == 402:
        return error_response(["Gensee API payment required — check your Gensee plan"], error_code="payment_required")
    if resp.status_code == 429:
        return error_response(["Gensee API rate limit exceeded"], error_code="rate_limited")
    if resp.status_code != 200:
        return error_response(
            [f"Gensee API returned {resp.status_code}: {resp.text[:500]}"],
            error_code="api_error",
        )

    data = resp.json()
    raw_results = data.get("search_response", [])

    results = []
    for r in raw_results:
        source = {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "abstract": r.get("content", ""),
            "type": "web",
            "provider": "gensee",
        }
        results.append(source)

    return success_response(
        results,
        total_results=len(results),
        provider="gensee",
        query=args.query,
    )
