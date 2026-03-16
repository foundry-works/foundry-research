"""GitHub search provider — repos, code, discussions, and repo details."""

import base64
import os
import tempfile

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.github.com"


def add_arguments(parser):
    parser.add_argument("--type", default="repos", choices=["repos", "code", "discussions"], help="Search type")
    parser.add_argument("--sort", default=None, help="Sort order, e.g. stars, forks, updated, best-match")
    parser.add_argument("--language", default=None, help="Filter by language, e.g. python, rust")
    parser.add_argument("--min-stars", type=int, default=None, help="Minimum star count filter")
    parser.add_argument("--repo", default=None, help="Get details for a specific repo, e.g. huggingface/transformers")
    parser.add_argument("--include-readme", action="store_true", default=False, help="Include README content for --repo mode")


def search(args) -> str:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="gh_")
    config = get_config(session_dir)
    client = _create_client(session_dir, config)

    try:
        if args.repo:
            return _repo_details(client, args, config)
        if args.query:
            search_type = getattr(args, "type", "repos")
            if search_type == "code":
                return _code_search(client, args, config)
            if search_type == "discussions":
                return _discussions_search(client, args, config)
            return _repo_search(client, args, config)
        return error_response(
            ["No search mode specified. Use --query or --repo."],
            error_code="missing_query",
        )
    except Exception as e:
        log(f"GitHub API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _get_token(config: dict) -> str | None:
    """Resolve GitHub token from config, GITHUB_TOKEN, or GH_TOKEN."""
    token = config.get("github_token")
    if token:
        return token
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _create_client(session_dir: str, config: dict):
    client = create_session(session_dir, rate_limits={"api.github.com": 0.5})
    token = _get_token(config)
    if token:
        client.session.headers["Authorization"] = f"Bearer {token}"
        client.session.headers["Accept"] = "application/vnd.github+json"
        log("Using GitHub token for authentication")
    else:
        client.session.headers["Accept"] = "application/vnd.github+json"
        log("No GitHub token found; some endpoints (code search) require auth", level="warn")
    return client


def _build_query(args) -> str:
    """Build the search query string with optional qualifiers."""
    parts = [args.query]
    if args.language:
        parts.append(f"language:{args.language}")
    if args.min_stars is not None:
        parts.append(f"stars:>={args.min_stars}")
    return " ".join(parts)


def _pagination_page(args) -> int:
    """Convert offset/limit to 1-based page number."""
    return (args.offset // args.limit) + 1


def _repo_search(client, args, config: dict) -> str:
    query = _build_query(args)
    page = _pagination_page(args)

    params: dict = {"q": query, "per_page": args.limit, "page": page}
    if args.sort:
        params["sort"] = args.sort

    resp = client.get(f"{BASE_URL}/search/repositories", params=params)
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    total_count = data.get("total_count", 0)
    items = data.get("items", [])

    results = [_normalize_repo(item) for item in items]

    if getattr(args, "include_readme", False):
        for i, item in enumerate(items):
            full_name = item.get("full_name", "")
            if full_name:
                readme = _fetch_readme(client, full_name)
                results[i]["readme_excerpt"] = readme[:2000] if readme else None

    return success_response(
        results,
        total_results=total_count,
        provider="github",
        query=args.query,
        search_type="repos",
        has_more=(page * args.limit < total_count),
    )


def _code_search(client, args, config: dict) -> str:
    token = _get_token(config)
    if not token:
        return error_response(
            ["Code search requires authentication. Set GITHUB_TOKEN or GH_TOKEN."],
            error_code="auth_required",
        )

    query = _build_query(args)
    page = _pagination_page(args)

    params: dict = {"q": query, "per_page": args.limit, "page": page}

    # Request text-match metadata for content excerpts
    headers = {"Accept": "application/vnd.github.text-match+json"}
    resp = client.get(f"{BASE_URL}/search/code", params=params, headers=headers)
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    total_count = data.get("total_count", 0)
    items = data.get("items", [])

    results = [_normalize_code(item) for item in items]

    return success_response(
        results,
        total_results=total_count,
        provider="github",
        query=args.query,
        search_type="code",
        has_more=(page * args.limit < total_count),
    )


def _discussions_search(client, args, config: dict) -> str:
    """Search for discussions using the issues search endpoint with type:discussion qualifier.

    GitHub REST API has no dedicated discussions search endpoint, so we use
    the issues search with a type qualifier as a best-effort fallback.
    """
    query = _build_query(args) + " type:discussion"
    page = _pagination_page(args)

    params: dict = {"q": query, "per_page": args.limit, "page": page}

    resp = client.get(f"{BASE_URL}/search/issues", params=params)
    if resp.status_code != 200:
        log("Discussions search via issues endpoint failed; this is a known limitation", level="warn")
        return error_response(
            [f"API returned {resp.status_code}: {resp.text[:500]}. "
             "Note: GitHub REST API has limited discussions search support."],
            error_code="api_error",
        )

    data = resp.json()
    total_count = data.get("total_count", 0)
    items = data.get("items", [])

    results = [_normalize_discussion(item) for item in items]

    return success_response(
        results,
        total_results=total_count,
        provider="github",
        query=args.query,
        search_type="discussions",
        has_more=(page * args.limit < total_count),
        note="Discussions search uses the issues endpoint as a fallback; results may be incomplete.",
    )


def _repo_details(client, args, config: dict) -> str:
    repo = args.repo
    if "/" not in repo:
        return error_response(
            [f"Invalid repo format '{repo}'. Expected 'owner/repo'."],
            error_code="invalid_input",
        )

    resp = client.get(f"{BASE_URL}/repos/{repo}")
    if resp.status_code == 404:
        return error_response([f"Repository '{repo}' not found."], error_code="not_found")
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    result = _normalize_repo(data)

    if args.include_readme:
        readme_content = _fetch_readme(client, repo)
        if readme_content is not None:
            result["readme_excerpt"] = readme_content[:2000]
        else:
            result["readme_excerpt"] = None
            log(f"Could not fetch README for {repo}", level="warn")

    return success_response(
        result,
        total_results=1,
        provider="github",
        mode="repo_details",
    )


def _fetch_readme(client, repo: str) -> str | None:
    """Fetch and decode the README for a repository. Returns None on failure."""
    resp = client.get(f"{BASE_URL}/repos/{repo}/readme")
    if resp.status_code != 200:
        return None

    data = resp.json()
    content_b64 = data.get("content")
    if not content_b64:
        return None

    try:
        # GitHub returns base64 with newlines; strip them before decoding
        return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")
    except Exception as e:
        log(f"Failed to decode README: {e}", level="warn")
        return None


def _normalize_repo(item: dict) -> dict:
    """Normalize a GitHub repository item to a consistent output dict."""
    license_info = item.get("license") or {}
    return {
        "full_name": item.get("full_name", ""),
        "description": item.get("description", ""),
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "language": item.get("language"),
        "topics": item.get("topics", []),
        "updated_at": item.get("updated_at", ""),
        "license": license_info.get("spdx_id"),
        "open_issues": item.get("open_issues_count", 0),
        "url": item.get("html_url", ""),
    }


def _normalize_code(item: dict) -> dict:
    """Normalize a GitHub code search result item."""
    repo = item.get("repository") or {}
    text_matches = item.get("text_matches") or []
    excerpt = ""
    if text_matches:
        fragments = [m.get("fragment", "") for m in text_matches]
        excerpt = "\n---\n".join(fragments)

    return {
        "repository": repo.get("full_name", ""),
        "path": item.get("path", ""),
        "url": item.get("html_url", ""),
        "content_excerpt": excerpt,
    }


def _normalize_discussion(item: dict) -> dict:
    """Normalize a discussion/issue search result item."""
    return {
        "title": item.get("title", ""),
        "url": item.get("html_url", ""),
        "state": item.get("state", ""),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
        "comments": item.get("comments", 0),
        "body_excerpt": (item.get("body") or "")[:500],
    }
