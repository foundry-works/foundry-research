"""OpenCitations search provider — citation traversal via the OpenCitations Index API."""

import tempfile

from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

# OpenCitations Index API (v2) and Meta API (v1)
INDEX_URL = "https://api.opencitations.net/index/v2"
META_URL = "https://api.opencitations.net/meta/v1"


def add_arguments(parser) -> None:
    """Register OpenCitations-specific CLI flags."""
    parser.add_argument(
        "--cited-by",
        default=None,
        help="DOI to get forward citations for (papers that cite this DOI)",
    )
    parser.add_argument(
        "--references",
        default=None,
        help="DOI to get backward references for (papers this DOI cites)",
    )


def search(args) -> dict:
    """Route to citation traversal based on flags."""
    session_dir = getattr(args, "session_dir", None) or tempfile.mkdtemp(prefix="oc_")

    # OpenCitations has no keyword search — guide users to the right tool
    if getattr(args, "query", None) and not args.cited_by and not args.references:
        return error_response(
            [
                "OpenCitations does not support keyword search. "
                "Use --provider crossref or --provider semantic_scholar for keyword search, "
                "then use --provider opencitations --cited-by DOI or --references DOI for citation traversal."
            ],
            error_code="unsupported_mode",
        )

    if not args.cited_by and not args.references:
        return error_response(
            ["Specify --cited-by DOI or --references DOI for OpenCitations citation traversal."],
            error_code="missing_query",
        )

    # 2.5 req/s = 150/min with margin for the index API
    client = create_session(
        session_dir,
        rate_limits={"api.opencitations.net": 2.5},
    )

    try:
        if args.cited_by:
            return _forward_citations(client, args)
        return _backward_references(client, args)
    except Exception as e:
        log(f"OpenCitations API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _forward_citations(client, args) -> dict:
    """Get papers that cite the given DOI."""
    doi = _clean_doi(args.cited_by)
    limit = getattr(args, "limit", 10)
    offset = getattr(args, "offset", 0)

    url = f"{INDEX_URL}/citations/doi:{doi}"
    log(f"OpenCitations forward citations for: {doi}")
    resp = client.get(url)

    if resp.status_code != 200:
        return _handle_error(resp, doi)

    edges = resp.json()
    if not isinstance(edges, list):
        return error_response([f"Unexpected response type: {type(edges).__name__}"], error_code="api_error")

    total = len(edges)

    # Apply offset/limit
    edges = edges[offset:offset + limit]

    # Extract citing DOIs and edge metadata
    citing_dois = []
    edge_metadata = {}
    for edge in edges:
        citing = _extract_doi_from_id(edge.get("citing", ""))
        if citing:
            citing_dois.append(citing)
            edge_metadata[citing] = {
                "timespan": edge.get("timespan", ""),
                "journal_sc": edge.get("journal_sc", "no"),
                "author_sc": edge.get("author_sc", "no"),
            }

    # Fetch metadata for citing papers
    papers = _fetch_metadata_batch(client, citing_dois, edge_metadata)

    return success_response(
        papers,
        total_results=total,
        provider="opencitations",
        query=args.query if hasattr(args, "query") else None,
        has_more=total > offset + limit,
        mode="citations",
        paper_id=doi,
    )


def _backward_references(client, args) -> dict:
    """Get papers that the given DOI cites."""
    doi = _clean_doi(args.references)
    limit = getattr(args, "limit", 10)
    offset = getattr(args, "offset", 0)

    url = f"{INDEX_URL}/references/doi:{doi}"
    log(f"OpenCitations backward references for: {doi}")
    resp = client.get(url)

    if resp.status_code != 200:
        return _handle_error(resp, doi)

    edges = resp.json()
    if not isinstance(edges, list):
        return error_response([f"Unexpected response type: {type(edges).__name__}"], error_code="api_error")

    total = len(edges)

    # Apply offset/limit
    edges = edges[offset:offset + limit]

    # Extract cited DOIs and edge metadata
    cited_dois = []
    edge_metadata = {}
    for edge in edges:
        cited = _extract_doi_from_id(edge.get("cited", ""))
        if cited:
            cited_dois.append(cited)
            edge_metadata[cited] = {
                "timespan": edge.get("timespan", ""),
                "journal_sc": edge.get("journal_sc", "no"),
                "author_sc": edge.get("author_sc", "no"),
            }

    # Fetch metadata for cited papers
    papers = _fetch_metadata_batch(client, cited_dois, edge_metadata)

    return success_response(
        papers,
        total_results=total,
        provider="opencitations",
        query=args.query if hasattr(args, "query") else None,
        has_more=total > offset + limit,
        mode="references",
        paper_id=doi,
    )


def _fetch_metadata_batch(client, dois: list[str], edge_metadata: dict) -> list[dict]:
    """Batch-fetch metadata from OpenCitations Meta API, up to 10 DOIs per request."""
    if not dois:
        return []

    papers = []
    batch_size = 10

    for i in range(0, len(dois), batch_size):
        batch = dois[i:i + batch_size]
        doi_list = "__".join(f"doi:{d}" for d in batch)
        url = f"{META_URL}/metadata/{doi_list}"

        log(f"Fetching metadata for {len(batch)} DOIs from OpenCitations Meta")
        resp = client.get(url)

        if resp.status_code != 200:
            log(f"Meta API returned {resp.status_code} for batch", level="warn")
            # Fall back to minimal records from DOIs alone
            for doi in batch:
                paper = normalize_paper({"doi": doi, "title": "", "provider": "opencitations"}, "opencitations")
                _attach_edge_metadata(paper, doi, edge_metadata)
                papers.append(paper)
            continue

        meta_items = resp.json()
        if not isinstance(meta_items, list):
            continue

        # Index by DOI for matching
        fetched_dois = set()
        for item in meta_items:
            raw_doi = _extract_doi_from_id(item.get("id", ""))
            if not raw_doi:
                # Try the doi field directly
                raw_doi = item.get("doi", "")
            paper = normalize_paper(item, "opencitations")
            _attach_edge_metadata(paper, raw_doi or paper.get("doi", ""), edge_metadata)
            papers.append(paper)
            if raw_doi:
                fetched_dois.add(raw_doi.lower())

        # Add minimal records for DOIs that weren't in the meta response
        for doi in batch:
            if doi.lower() not in fetched_dois:
                paper = normalize_paper({"doi": doi, "title": "", "provider": "opencitations"}, "opencitations")
                _attach_edge_metadata(paper, doi, edge_metadata)
                papers.append(paper)

    return papers


def _attach_edge_metadata(paper: dict, doi: str, edge_metadata: dict) -> None:
    """Attach citation edge metadata (timespan, self-citation flags) to a paper record."""
    edge = edge_metadata.get(doi, {})
    if not edge:
        # Try case-insensitive match
        doi_lower = doi.lower()
        for k, v in edge_metadata.items():
            if k.lower() == doi_lower:
                edge = v
                break

    paper["timespan"] = edge.get("timespan", "")
    paper["self_citation_journal"] = edge.get("journal_sc", "no") == "yes"
    paper["self_citation_author"] = edge.get("author_sc", "no") == "yes"


def _clean_doi(doi: str) -> str:
    """Strip URL prefix from DOI if present."""
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi


def _extract_doi_from_id(oc_id: str) -> str:
    """Extract DOI from OpenCitations ID format like 'doi:10.1234/foo'."""
    if not oc_id:
        return ""
    # OpenCitations IDs can be space-separated lists; take the DOI part
    for part in oc_id.split():
        if part.startswith("doi:"):
            return part[4:]
    # If the whole string looks like a DOI
    if "/" in oc_id and not oc_id.startswith("http"):
        return oc_id
    return ""


def _handle_error(resp, doi: str) -> dict:
    """Convert HTTP error to error envelope."""
    status = resp.status_code
    if status == 404:
        return error_response([f"DOI not found in OpenCitations: {doi}"], error_code="not_found")
    if status == 429:
        return error_response([f"OpenCitations rate limited (429)"], error_code="rate_limited")

    try:
        body = resp.text[:500]
    except Exception:
        body = "(unreadable)"

    log(f"OpenCitations API error {status}: {body}", level="error")
    return error_response([f"OpenCitations API returned {status}: {body}"], error_code=f"http_{status}")
