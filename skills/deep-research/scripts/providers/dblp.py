"""DBLP search provider — CS publication search, author search, and venue lookup."""

import tempfile

from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

# DBLP API endpoints — primary and mirror (Trier).
# The primary server occasionally returns 500; the mirror is independently hosted.
_BASES = ["https://dblp.org", "https://dblp.uni-trier.de"]
_PUBL_PATH = "/search/publ/api"
_AUTHOR_PATH = "/search/author/api"
_VENUE_PATH = "/search/venue/api"


def add_arguments(parser) -> None:
    """Register DBLP-specific CLI flags."""
    parser.add_argument(
        "--author",
        default=None,
        help="Search for authors by name",
    )
    parser.add_argument(
        "--venue",
        default=None,
        help="Search for venues (conferences/journals) by name",
    )
    parser.add_argument(
        "--year-range",
        default=None,
        help="Filter by year range, e.g. 2020-2024 (appended as year filter to query)",
    )
    parser.add_argument(
        "--type",
        default=None,
        dest="pub_type",
        help="Filter by publication type: Conference_and_Workshop_Papers, Journal_Articles, etc.",
    )


def search(args) -> dict:
    """Route to publication, author, or venue search."""
    session_dir = getattr(args, "session_dir", None) or tempfile.mkdtemp(prefix="dblp_")

    # Conservative 1 req/s per domain — DBLP has no published limit but returns 429 when exceeded
    client = create_session(
        session_dir,
        rate_limits={"dblp.org": 1.0, "dblp.uni-trier.de": 1.0},
    )

    try:
        if getattr(args, "author", None):
            return _author_search(client, args)
        if getattr(args, "venue", None):
            return _venue_search(client, args)
        if getattr(args, "query", None):
            return _publication_search(client, args)
        return error_response(
            ["Specify --query, --author, or --venue for DBLP search."],
            error_code="missing_query",
        )
    except Exception as e:
        log(f"DBLP API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _dblp_get(client, path: str, params: dict):
    """Try DBLP request on primary server, fall back to Trier mirror on 5xx."""
    for base in _BASES:
        url = base + path
        resp = client.get(url, params=params)
        if resp.status_code < 500:
            return resp
        log(f"DBLP {base} returned {resp.status_code}, trying next mirror", level="warn")
    return resp  # return last response if all mirrors fail


def _publication_search(client, args) -> dict:
    """Search DBLP publications by keyword."""
    query = args.query
    limit = min(getattr(args, "limit", 10), 1000)
    offset = getattr(args, "offset", 0)

    # Build query with optional filters
    q = query
    year_range = getattr(args, "year_range", None)
    if year_range:
        parts = year_range.split("-")
        if len(parts) == 2:
            # DBLP supports year: filter syntax in the query
            q += f" year:{parts[0]}-{parts[1]}:"
        elif len(parts) == 1:
            q += f" year:{parts[0]}:"

    pub_type = getattr(args, "pub_type", None)
    if pub_type:
        q += f" type:{pub_type}:"

    params = {"q": q, "format": "json", "h": limit, "f": offset}
    log(f"DBLP publication search: {q}")
    resp = _dblp_get(client, _PUBL_PATH, params)

    if resp.status_code != 200:
        return _handle_error(resp)

    data = resp.json()
    result = data.get("result", {})
    hits_wrapper = result.get("hits", {})
    total = int(hits_wrapper.get("@total", 0))
    hits = hits_wrapper.get("hit", [])

    if not isinstance(hits, list):
        hits = [hits] if hits else []

    papers = []
    for hit in hits:
        info = hit.get("info", {})
        if not info:
            continue
        paper = normalize_paper(info, "dblp")
        papers.append(paper)

    return success_response(
        papers,
        total_results=total,
        provider="dblp",
        query=query,
        has_more=total > offset + limit,
    )


def _author_search(client, args) -> dict:
    """Search DBLP for authors."""
    query = args.author
    limit = min(getattr(args, "limit", 10), 1000)
    offset = getattr(args, "offset", 0)

    params = {"q": query, "format": "json", "h": limit, "f": offset}
    log(f"DBLP author search: {query}")
    resp = _dblp_get(client, _AUTHOR_PATH, params)

    if resp.status_code != 200:
        return _handle_error(resp)

    data = resp.json()
    result = data.get("result", {})
    hits_wrapper = result.get("hits", {})
    total = int(hits_wrapper.get("@total", 0))
    hits = hits_wrapper.get("hit", [])

    if not isinstance(hits, list):
        hits = [hits] if hits else []

    authors = []
    for hit in hits:
        info = hit.get("info", {})
        if not info:
            continue
        author = {
            "name": info.get("author", ""),
            "url": info.get("url", ""),
            "notes": {},
        }
        # Extract note fields (affiliation, etc.)
        notes = info.get("notes", {})
        if isinstance(notes, dict):
            note = notes.get("note", {})
            if isinstance(note, dict):
                author["notes"] = {note.get("@type", "note"): note.get("text", "")}
            elif isinstance(note, list):
                author["notes"] = {n.get("@type", "note"): n.get("text", "") for n in note if isinstance(n, dict)}
        authors.append(author)

    return success_response(
        authors,
        total_results=total,
        provider="dblp",
        query=query,
        has_more=total > offset + limit,
        mode="author_search",
    )


def _venue_search(client, args) -> dict:
    """Search DBLP for venues (conferences/journals)."""
    query = args.venue
    limit = min(getattr(args, "limit", 10), 1000)
    offset = getattr(args, "offset", 0)

    params = {"q": query, "format": "json", "h": limit, "f": offset}
    log(f"DBLP venue search: {query}")
    resp = _dblp_get(client, _VENUE_PATH, params)

    if resp.status_code != 200:
        return _handle_error(resp)

    data = resp.json()
    result = data.get("result", {})
    hits_wrapper = result.get("hits", {})
    total = int(hits_wrapper.get("@total", 0))
    hits = hits_wrapper.get("hit", [])

    if not isinstance(hits, list):
        hits = [hits] if hits else []

    venues = []
    for hit in hits:
        info = hit.get("info", {})
        if not info:
            continue
        venue = {
            "name": info.get("venue", ""),
            "acronym": info.get("acronym", ""),
            "type": info.get("type", ""),
            "url": info.get("url", ""),
        }
        venues.append(venue)

    return success_response(
        venues,
        total_results=total,
        provider="dblp",
        query=query,
        has_more=total > offset + limit,
        mode="venue_search",
    )


def _handle_error(resp) -> dict:
    """Convert HTTP error to error envelope."""
    status = resp.status_code
    if status == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        return error_response(
            [f"DBLP rate limited (429). Retry after {retry_after}s."],
            error_code="rate_limited",
        )

    try:
        body = resp.text[:500]
    except Exception:
        body = "(unreadable)"

    log(f"DBLP API error {status}: {body}", level="error")
    return error_response([f"DBLP API returned {status}: {body}"], error_code=f"http_{status}")
