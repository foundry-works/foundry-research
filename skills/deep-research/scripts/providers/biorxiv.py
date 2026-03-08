"""bioRxiv / medRxiv search provider — preprint browsing, DOI lookup, and keyword search via OpenAlex."""

import tempfile
from datetime import date, timedelta

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.biorxiv.org"
OPENALEX_URL = "https://api.openalex.org"

_DEFAULT_MAILTO = "deep-research-tool@users.noreply.github.com"


def add_arguments(parser) -> None:
    """Register bioRxiv-specific CLI flags."""
    parser.add_argument(
        "--server",
        choices=["biorxiv", "medrxiv", "both"],
        default="both",
        help="Which preprint server to search (default: both)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Look back N days for content listings (default: 30)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter by category, e.g. neuroscience, molecular-biology",
    )
    parser.add_argument(
        "--doi",
        default=None,
        help="Look up a single paper by DOI",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        default=False,
        help="List available categories for bioRxiv/medRxiv and exit",
    )


def search(args) -> dict:
    """Search bioRxiv/medRxiv and return a JSON envelope dict."""
    if getattr(args, "list_categories", False):
        return _list_categories(args)

    session_dir = getattr(args, "session_dir", None) or tempfile.mkdtemp(prefix="biorxiv_")
    query = getattr(args, "query", None)
    doi = getattr(args, "doi", None)

    http = create_session(session_dir)

    try:
        if query:
            return _openalex_search(http, args, session_dir)
        if doi:
            return _doi_lookup(http, args)
        return _browse_by_date(http, args)
    except Exception as e:
        log(f"bioRxiv search failed: {e}", level="error")
        return error_response([f"bioRxiv search failed: {e}"], error_code="provider_error")
    finally:
        http.close()


def _list_categories(args) -> dict:
    """Fetch available categories by sampling recent papers from bioRxiv and/or medRxiv."""
    import requests

    server = getattr(args, "server", "both")
    servers = _resolve_servers(server)

    end = date.today()
    start = end - timedelta(days=90)
    date_range = f"{start.isoformat()}/{end.isoformat()}"

    result: dict[str, list[str]] = {}

    for srv in servers:
        url = f"{BASE_URL}/details/{srv}/{date_range}/0"
        log(f"Fetching {srv} categories from recent papers...")
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            cats: set[str] = set()
            for item in data.get("collection", []):
                cat = item.get("category", "")
                if cat:
                    cats.add(cat)
            result[srv] = sorted(cats)
        except Exception as e:
            log(f"Failed to fetch {srv} categories: {e}", level="error")
            result[srv] = []

    return success_response(result)


def _openalex_search(http, args, session_dir: str) -> dict:
    """Delegate keyword search to OpenAlex, filtering to Cold Spring Harbor Laboratory (bioRxiv/medRxiv)."""
    query = args.query
    limit = min(getattr(args, "limit", 10), 200)

    config = get_config(session_dir)
    api_key = config.get("openalex_api_key")

    params: dict[str, str | int] = {
        "search": query,
        "filter": "doi_starts_with:10.1101",
        "per_page": limit,
    }

    headers: dict[str, str] = {}
    if api_key:
        headers["api_key"] = api_key
    else:
        params["mailto"] = _DEFAULT_MAILTO

    url = f"{OPENALEX_URL}/works"
    log(f"bioRxiv: delegating keyword search to OpenAlex for '{query}'")

    resp = http.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        return _handle_openalex_error(resp)

    data = resp.json()
    meta = data.get("meta", {})
    total_results = meta.get("count", 0)
    raw_results = data.get("results", [])

    results = []
    for work in raw_results:
        paper = normalize_paper(work, "openalex")
        # Override provider to biorxiv since these are preprints
        paper["provider"] = "biorxiv"
        results.append(paper)

    return success_response(
        results,
        total_results=total_results,
        has_more=total_results > limit,
        provider="biorxiv",
        query=query,
    )


def _doi_lookup(http, args) -> dict:
    """Look up a single paper by DOI."""
    doi = args.doi
    server = getattr(args, "server", "both")
    servers = _resolve_servers(server)

    for srv in servers:
        url = f"{BASE_URL}/details/{srv}/{doi}"
        log(f"bioRxiv: DOI lookup {doi} on {srv}")

        resp = http.get(url)
        if resp.status_code != 200:
            continue

        data = resp.json()
        collection = data.get("collection", [])
        if not collection:
            continue

        # Return the most recent version (last in collection)
        item = collection[-1]
        paper = _normalize_biorxiv_item(item)
        return success_response([paper], total_results=1, has_more=False, provider="biorxiv")

    return error_response([f"DOI {doi} not found on {server}"], error_code="not_found")


def _browse_by_date(http, args) -> dict:
    """Browse recent papers by date range, optionally filtered by category."""
    server = getattr(args, "server", "both")
    days = getattr(args, "days", 30)
    limit = getattr(args, "limit", 10)
    offset = getattr(args, "offset", 0)
    category_filter = getattr(args, "category", None)

    servers = _resolve_servers(server)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    date_range = f"{start_date.isoformat()}/{end_date.isoformat()}"

    all_results: list[dict] = []

    for srv in servers:
        cursor = 0
        while len(all_results) < offset + limit:
            url = f"{BASE_URL}/details/{srv}/{date_range}/{cursor}"
            log(f"bioRxiv: fetching {srv} papers, cursor={cursor}")

            resp = http.get(url)
            if resp.status_code != 200:
                log(f"bioRxiv API returned {resp.status_code} for {srv}", level="error")
                break

            data = resp.json()
            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                if category_filter and item.get("category", "") != category_filter:
                    continue
                paper = _normalize_biorxiv_item(item)
                all_results.append(paper)

            # bioRxiv returns 100 per page; stop if fewer returned
            if len(collection) < 100:
                break

            cursor += 100

    # Apply offset and limit
    paged = all_results[offset : offset + limit]

    return success_response(paged, total_results=len(all_results), has_more=len(all_results) > offset + limit, provider="biorxiv")


def _normalize_biorxiv_item(item: dict) -> dict:
    """Normalize a single bioRxiv API item to the unified paper schema."""
    version = item.get("version", "1")
    doi = item.get("doi", "")

    raw = {
        "title": item.get("title", ""),
        "authors": item.get("authors", "").split("; "),
        "doi": doi,
        "abstract": item.get("abstract", ""),
        "year": int(item.get("date", "0000")[:4]),
        "url": f"https://www.biorxiv.org/content/{doi}v{version}",
        "pdf_url": f"https://www.biorxiv.org/content/{doi}v{version}.full.pdf",
    }

    paper = normalize_paper(raw, "biorxiv")
    paper["server"] = item.get("server", "biorxiv")
    paper["category"] = item.get("category", "")
    paper["version"] = item.get("version", "1")
    paper["published_doi"] = item.get("published_doi", "") or item.get("pub_doi", "") or ""
    paper["published_journal"] = item.get("published_journal", "") or item.get("pub_journal", "") or ""

    return paper


def _resolve_servers(server: str) -> list[str]:
    """Convert server flag to list of server names for API calls."""
    if server == "both":
        return ["biorxiv", "medrxiv"]
    return [server]


def _handle_openalex_error(resp) -> dict:
    """Convert an OpenAlex HTTP error response into an error envelope."""
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
