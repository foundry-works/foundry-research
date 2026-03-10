"""Semantic Scholar search provider — keyword search, citations, references, recommendations, author search."""

import tempfile

from _shared.config import get_config
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://api.semanticscholar.org/graph/v1"
RECS_URL = "https://api.semanticscholar.org/recommendations/v1/papers"

PAPER_FIELDS = "paperId,title,abstract,authors,citationCount,year,externalIds,url,openAccessPdf,tldr,venue,journal"
# Citations, references, and recommendations endpoints don't support tldr
CITATION_FIELDS = "paperId,title,abstract,authors,citationCount,year,externalIds,url,openAccessPdf,venue,journal"
AUTHOR_FIELDS = "authorId,name,paperCount,citationCount,hIndex"


def add_arguments(parser):
    parser.add_argument("--year-range", default=None, help="Year range filter, e.g. 2020-2024")
    parser.add_argument("--fields-of-study", default=None, help="Fields of study filter, e.g. 'Computer Science'")
    parser.add_argument("--min-citations", type=int, default=None, help="Minimum citation count (client-side filter)")
    parser.add_argument("--sort", default=None, help="Sort order, e.g. 'citationCount:desc'")
    parser.add_argument("--cited-by", default=None, help="Paper ID or DOI to get forward citations for")
    parser.add_argument("--references", default=None, help="Paper ID or DOI to get backward references for")
    parser.add_argument("--recommendations", default=None, help="Paper ID or DOI to get recommendations for")
    parser.add_argument("--author", default=None, help="Author name to search for")


def search(args) -> dict:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="s2_")
    config = get_config(session_dir)
    client = _create_client(session_dir, config)

    try:
        if args.cited_by:
            return _forward_citations(client, args)
        if args.references:
            return _backward_references(client, args)
        if args.recommendations:
            return _get_recommendations(client, args)
        if args.author:
            return _author_search(client, args)
        if args.query:
            return _keyword_search(client, args)
        return error_response(["No search mode specified. Use --query, --cited-by, --references, --recommendations, or --author."], error_code="missing_query")
    except Exception as e:
        log(f"Semantic Scholar API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _create_client(session_dir, config):
    client = create_session(session_dir, rate_limits={"api.semanticscholar.org": 1.0})
    api_key = config.get("semantic_scholar_api_key")
    if api_key:
        client.session.headers["x-api-key"] = api_key
        log("Using Semantic Scholar API key")
    return client


def _keyword_search(client, args) -> dict:
    params = {"query": args.query, "fields": PAPER_FIELDS, "limit": args.limit, "offset": args.offset}

    if args.year_range:
        params["year"] = args.year_range
    if args.fields_of_study:
        params["fieldsOfStudy"] = args.fields_of_study
    if args.sort:
        params["sort"] = args.sort

    url = f"{BASE_URL}/paper/search"
    resp = client.get(url, params=params)

    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected API response type: {type(data).__name__}")
    raw_papers = data.get("data") or []
    total = data.get("total", len(raw_papers))

    papers = _normalize_papers(raw_papers, args.min_citations)

    return success_response(
        papers,
        total_results=total,
        provider="semantic_scholar",
        query=args.query,
        has_more=total > args.offset + args.limit,
    )


def _forward_citations(client, args) -> dict:
    paper_id = args.cited_by
    url = f"{BASE_URL}/paper/{paper_id}/citations"
    params = {"fields": CITATION_FIELDS, "limit": args.limit, "offset": args.offset}

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected API response type: {type(data).__name__}")
    raw_items = data.get("data") or []
    total = data.get("total", len(raw_items))

    raw_papers = [item["citingPaper"] for item in raw_items if item.get("citingPaper")]
    papers = _normalize_papers(raw_papers, args.min_citations)

    # Warn when min_citations filtering removed all results from a highly-cited paper
    warnings = []
    if not papers and total > 0 and args.min_citations is not None:
        warnings.append(
            f"--cited-by returned {total} raw citations but 0 passed --min-citations {args.min_citations} filter. "
            f"Retry without --min-citations or try --provider openalex --cited-by {paper_id}."
        )
        log(warnings[0], level="warn")

    extra = {
        "provider": "semantic_scholar",
        "query": args.query,
        "has_more": total > args.offset + args.limit,
        "mode": "citations",
        "paper_id": paper_id,
    }
    if warnings:
        extra["warnings"] = warnings

    return success_response(papers, total_results=total, **extra)


def _backward_references(client, args) -> dict:
    paper_id = args.references
    url = f"{BASE_URL}/paper/{paper_id}/references"
    params = {"fields": CITATION_FIELDS, "limit": args.limit, "offset": args.offset}

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected API response type: {type(data).__name__}")
    raw_items = data.get("data") or []
    total = data.get("total", len(raw_items))

    raw_papers = [item["citedPaper"] for item in raw_items if item.get("citedPaper")]
    papers = _normalize_papers(raw_papers, args.min_citations)

    return success_response(
        papers,
        total_results=total,
        provider="semantic_scholar",
        query=args.query,
        has_more=total > args.offset + args.limit,
        mode="references",
        paper_id=paper_id,
    )


def _get_recommendations(client, args) -> dict:
    paper_id = args.recommendations
    url = f"{RECS_URL}/forpaper/{paper_id}"
    params = {"fields": CITATION_FIELDS, "limit": args.limit}

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected API response type: {type(data).__name__}")
    raw_papers = data.get("recommendedPapers") or []

    papers = _normalize_papers(raw_papers, args.min_citations)

    return success_response(
        papers,
        total_results=len(papers),
        provider="semantic_scholar",
        query=args.query,
        has_more=False,
        mode="recommendations",
        paper_id=paper_id,
    )


def _author_search(client, args) -> dict:
    url = f"{BASE_URL}/author/search"
    params = {"query": args.author, "fields": AUTHOR_FIELDS, "limit": args.limit, "offset": args.offset}

    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"API returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected API response type: {type(data).__name__}")
    authors = data.get("data") or []
    total = data.get("total", len(authors))

    return success_response(
        authors,
        total_results=total,
        provider="semantic_scholar",
        query=args.author,
        has_more=total > args.offset + args.limit,
        mode="author_search",
    )


def _normalize_papers(raw_papers: list[dict], min_citations: int | None = None) -> list[dict]:
    papers = []
    for raw in raw_papers:
        if not raw or not raw.get("paperId"):
            continue

        paper = normalize_paper(raw, "semantic_scholar")

        # Add extra fields not in the standard schema
        tldr = raw.get("tldr")
        paper["tldr"] = tldr.get("text", "") if isinstance(tldr, dict) else ""
        paper["is_open_access"] = bool((raw.get("openAccessPdf") or {}).get("url"))

        if min_citations is not None and paper.get("citation_count", 0) < min_citations:
            continue

        papers.append(paper)

    return papers
