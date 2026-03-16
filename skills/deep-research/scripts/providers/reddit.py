"""Reddit search provider — search posts, browse subreddits, fetch post details with comments."""

import re
import tempfile

from _shared.http_client import create_session
from _shared.output import error_response, log, success_response

BASE_URL = "https://www.reddit.com"
USER_AGENT = "deep-research/1.0 (academic research tool)"
URL_PATTERN = re.compile(r"https?://[^\s\)]+")


def add_arguments(parser):
    parser.add_argument("--subreddits", nargs="+", default=None, help="Subreddits to search within, e.g. MachineLearning physics")
    parser.add_argument("--sort", default="relevance", choices=["relevance", "hot", "top", "new", "comments"], help="Sort order (default: relevance)")
    parser.add_argument("--time", default="year", choices=["hour", "day", "week", "month", "year", "all"], help="Time filter (default: year)")
    parser.add_argument("--browse", default=None, help="Browse a subreddit by name (no search query needed)")
    parser.add_argument("--post-url", default=None, help="Full Reddit post URL to fetch post and comments")
    parser.add_argument("--post-id", default=None, help="Reddit post ID to fetch post and comments")
    parser.add_argument("--comment-limit", type=int, default=20, help="Max comments to retrieve (default: 20)")


def search(args) -> str:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="reddit_")
    client = create_session(session_dir, user_agent=USER_AGENT, rate_limits={"www.reddit.com": 0.15})

    try:
        if args.post_url:
            return _fetch_post(client, args, url=args.post_url)
        if args.post_id:
            return _fetch_post(client, args, post_id=args.post_id)
        if args.browse:
            return _browse_subreddit(client, args)
        if args.query:
            if args.subreddits:
                return _multi_subreddit_search(client, args)
            return _global_search(client, args)
        return error_response(
            ["No search mode specified. Use --query, --browse, --post-url, or --post-id."],
            error_code="missing_query",
        )
    except Exception as e:
        log(f"Reddit API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _global_search(client, args) -> str:
    params = {"q": args.query, "sort": args.sort, "t": args.time, "limit": args.limit}
    url = f"{BASE_URL}/search.json"

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"Reddit returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    listing = data.get("data", {})
    children = listing.get("children", [])
    after = listing.get("after")

    results = [_format_post(child["data"]) for child in children if child.get("data")]

    return success_response(
        results,
        total_results=len(results),
        provider="reddit",
        query=args.query,
        has_more=bool(after),
    )


def _subreddit_search(client, args, subreddit: str) -> tuple[list[dict], str | None]:
    """Search within a single subreddit, returning (results, after_cursor)."""
    params = {"q": args.query, "restrict_sr": "on", "sort": args.sort, "t": args.time, "limit": args.limit}
    url = f"{BASE_URL}/r/{subreddit}/search.json"

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        log(f"Subreddit search failed for r/{subreddit}: {resp.status_code}", level="warn")
        return [], None

    data = resp.json()
    listing = data.get("data", {})
    children = listing.get("children", [])
    after = listing.get("after")

    results = [_format_post(child["data"]) for child in children if child.get("data")]
    return results, after


def _multi_subreddit_search(client, args) -> str:
    all_results = []
    any_has_more = False

    for sub in args.subreddits:
        log(f"Searching r/{sub}...")
        results, after = _subreddit_search(client, args, sub)
        all_results.extend(results)
        if after:
            any_has_more = True

    # Sort combined results by score descending, trim to limit
    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    all_results = all_results[: args.limit]

    return success_response(
        all_results,
        total_results=len(all_results),
        provider="reddit",
        query=args.query,
        subreddits=args.subreddits,
        has_more=any_has_more,
    )


def _browse_subreddit(client, args) -> str:
    subreddit = args.browse
    sort = args.sort if args.sort in ("hot", "top", "new") else "hot"
    params = {"limit": args.limit}
    if sort == "top":
        params["t"] = args.time
    url = f"{BASE_URL}/r/{subreddit}/{sort}.json"

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"Reddit returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    listing = data.get("data", {})
    children = listing.get("children", [])
    after = listing.get("after")

    results = [_format_post(child["data"]) for child in children if child.get("data")]

    return success_response(
        results,
        total_results=len(results),
        provider="reddit",
        subreddit=subreddit,
        mode="browse",
        sort=sort,
        has_more=bool(after),
    )


def _fetch_post(client, args, url: str | None = None, post_id: str | None = None) -> str:
    if url:
        # Strip trailing slash and append .json
        permalink = url.rstrip("/")
        if permalink.startswith(BASE_URL):
            permalink = permalink[len(BASE_URL):]
        json_url = f"{BASE_URL}{permalink}.json"
    elif post_id:
        json_url = f"{BASE_URL}/comments/{post_id}.json"
    else:
        return error_response(["No post URL or ID provided."], error_code="missing_input")

    params = {"limit": args.comment_limit}
    resp = client.get(json_url, params=params)
    if resp.status_code != 200:
        return error_response([f"Reddit returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    if not isinstance(data, list) or len(data) < 2:
        return error_response(["Unexpected response format from Reddit post endpoint."], error_code="parse_error")

    # First listing is the post, second is comments
    post_listing = data[0].get("data", {}).get("children", [])
    if not post_listing:
        return error_response(["Post not found."], error_code="not_found")

    post_data = post_listing[0].get("data", {})
    post = _format_post(post_data)

    # Flatten comment tree
    comments_listing = data[1].get("data", {}).get("children", [])
    comments = []
    _flatten_comments(comments_listing, comments, depth=0)

    # Extract links from post selftext and comment bodies
    all_text = [post_data.get("selftext", "")]
    all_text.extend(c.get("body", "") for c in comments)
    extracted_links = _extract_links("\n".join(all_text))

    result = {
        "post": post,
        "comments": comments,
        "extracted_links": extracted_links,
    }

    return success_response(
        result,
        total_results=1,
        provider="reddit",
        mode="post_details",
        comment_count=len(comments),
        link_count=len(extracted_links),
    )


def _format_post(post: dict) -> dict:
    return {
        "id": post.get("id", ""),
        "title": post.get("title", ""),
        "author": post.get("author", ""),
        "subreddit": post.get("subreddit", ""),
        "score": post.get("score", 0),
        "upvote_ratio": post.get("upvote_ratio", 0),
        "num_comments": post.get("num_comments", 0),
        "url": post.get("url", ""),
        "permalink": f"https://www.reddit.com{post.get('permalink', '')}",
        "selftext": post.get("selftext", ""),
        "link_flair_text": post.get("link_flair_text"),
        "content_length": len(post.get("selftext", "")),
    }


def _flatten_comments(children: list, out: list, depth: int) -> None:
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {})
        out.append({
            "body": data.get("body", ""),
            "author": data.get("author", ""),
            "score": data.get("score", 0),
            "created_utc": data.get("created_utc", 0),
            "depth": depth,
            "id": data.get("id", ""),
            "parent_id": data.get("parent_id", ""),
        })
        replies = data.get("replies")
        if replies and isinstance(replies, dict):
            nested = replies.get("data", {}).get("children", [])
            _flatten_comments(nested, out, depth + 1)


def _extract_links(text: str) -> list[str]:
    urls = URL_PATTERN.findall(text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        # Strip trailing punctuation that may have been captured
        url = url.rstrip(".,;:!?\"'")
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique
