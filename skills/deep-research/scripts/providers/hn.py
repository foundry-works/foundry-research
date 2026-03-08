"""Hacker News search provider — search stories/comments via Algolia API and fetch story details."""

import re
import tempfile
import time

from _shared.html_extract import html_to_text
from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

API_BASE = "https://hn.algolia.com/api/v1"

TYPE_CHOICES = ("story", "comment", "show_hn", "ask_hn")
SORT_CHOICES = ("relevance", "date")

_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def add_arguments(parser):
    parser.add_argument("--type", default="story", choices=TYPE_CHOICES, help="Item type filter (default: story)")
    parser.add_argument("--sort", default="relevance", choices=SORT_CHOICES, help="Sort order (default: relevance)")
    parser.add_argument("--days", type=int, default=None, help="Filter to last N days")
    parser.add_argument("--tags", default=None, help="Additional tag filters (comma-separated)")
    parser.add_argument("--story-id", default=None, help="Fetch full story + comments by item ID")
    parser.add_argument("--comment-limit", type=int, default=30, help="Max comments for story detail (default: 30)")


def search(args) -> dict:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="hn_")
    client = create_session(session_dir, rate_limits={"hn.algolia.com": 0.5})

    try:
        if args.story_id:
            return _fetch_story_detail(client, args)
        return _search_items(client, args)
    except Exception as e:
        log(f"HN API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _search_items(client, args) -> dict:
    query = args.query
    if not query:
        return error_response(["--query is required for HN search"], error_code="missing_query")

    limit = min(args.limit, 1000)
    page = args.offset // limit if args.offset else 0

    # Build tags parameter
    item_type = args.type
    tags = item_type
    if args.tags:
        tags = f"{tags},{args.tags}"

    # Choose endpoint based on sort
    endpoint = "search" if args.sort == "relevance" else "search_by_date"
    url = f"{API_BASE}/{endpoint}?query={query}&tags={tags}&hitsPerPage={limit}&page={page}"

    # Date filter via numericFilters
    if args.days:
        cutoff_ts = int(time.time()) - args.days * 86400
        url += f"&numericFilters=created_at_i>{cutoff_ts}"

    log(f"HN search: {endpoint} query={query!r} type={item_type} page={page}")
    response = client.get(url)

    if response.status_code != 200:
        return error_response(
            [f"HN Algolia API returned status {response.status_code}"],
            error_code="api_error",
        )

    data = response.json()
    hits = data.get("hits", [])
    nb_hits = data.get("nbHits", 0)
    nb_pages = data.get("nbPages", 0)
    current_page = data.get("page", 0)

    results = [_format_hit(hit) for hit in hits]

    return success_response(results, total_results=nb_hits, has_more=(current_page + 1 < nb_pages))


def _format_hit(hit: dict) -> dict:
    """Format a search hit into the standard output shape."""
    return {
        "id": hit["objectID"],
        "title": hit.get("title", ""),
        "author": hit.get("author", ""),
        "url": hit.get("url", ""),
        "points": hit.get("points", 0),
        "num_comments": hit.get("num_comments", 0),
        "created_at": hit.get("created_at", ""),
        "story_text": html_to_text(hit.get("story_text") or ""),
        "hn_url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
    }


def _fetch_story_detail(client, args) -> dict:
    """Fetch a full story with its comment tree."""
    story_id = args.story_id
    url = f"{API_BASE}/items/{story_id}"

    log(f"HN item detail: id={story_id}")
    response = client.get(url)

    if response.status_code != 200:
        return error_response(
            [f"HN Algolia API returned status {response.status_code} for item {story_id}"],
            error_code="api_error",
        )

    data = response.json()

    # Build story dict
    story_text_html = data.get("text") or ""
    story = {
        "id": data.get("id", story_id),
        "title": data.get("title", ""),
        "author": data.get("author", ""),
        "url": data.get("url", ""),
        "points": data.get("points", 0),
        "text": html_to_text(story_text_html),
        "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
    }

    # Flatten comment tree
    comment_limit = args.comment_limit
    comments = []
    _flatten_comments(data.get("children", []), comments, depth=0, limit=comment_limit)

    # Extract links from story url, story text, and all comment text
    extracted_links = set()
    if data.get("url"):
        extracted_links.add(data["url"])
    extracted_links.update(_URL_RE.findall(story_text_html))
    for comment in comments:
        extracted_links.update(comment.get("_raw_links", []))

    # Remove internal _raw_links from comment output
    for comment in comments:
        comment.pop("_raw_links", None)

    result = {
        "story": story,
        "comments": comments,
        "extracted_links": sorted(extracted_links),
    }

    return success_response(result, total_results=1)


def _flatten_comments(children: list, out: list, depth: int, limit: int) -> None:
    """Recursively flatten the comment tree with depth tracking, up to limit total comments."""
    for child in children:
        if len(out) >= limit:
            return

        text_html = child.get("text") or ""
        raw_links = _URL_RE.findall(text_html)
        sub_children = child.get("children", [])

        out.append({
            "id": child.get("id", ""),
            "author": child.get("author", ""),
            "text": html_to_text(text_html),
            "depth": depth,
            "children_count": len(sub_children),
            "created_at": child.get("created_at", ""),
            "_raw_links": raw_links,
        })

        _flatten_comments(sub_children, out, depth + 1, limit)
