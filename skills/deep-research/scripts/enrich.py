#!/usr/bin/env python3
"""Crossref DOI metadata enrichment — looks up DOIs and returns bibliographic data."""

import argparse
import os
import sys

# Add parent directory so _shared imports work when run from any location
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shared.doi_utils import normalize_doi  # noqa: E402
from _shared.html_extract import strip_jats_xml  # noqa: E402
from _shared.http_client import create_session  # noqa: E402
from _shared.metadata import (  # noqa: E402  # noqa: E402
    merge_metadata,
    normalize_paper,
    read_source_metadata,
    write_source_metadata,
)
from _shared.output import error_response, log, set_quiet, success_response  # noqa: E402

# Crossref API base URL
_API_URL = "https://api.crossref.org/works"

# Default User-Agent (without mailto → ~1 RPS; with mailto → polite pool 10 RPS)
_UA_TEMPLATE = "deep-research/1.0 (mailto:{email})"
_UA_DEFAULT = "deep-research/1.0 (academic research tool)"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich DOIs with Crossref bibliographic metadata.",
    )
    parser.add_argument(
        "--doi", action="append", required=True,
        help="DOI to enrich (can be specified multiple times)",
    )
    parser.add_argument(
        "--source-id", action="append", default=None,
        help="Source ID to merge metadata into (parallel with --doi, e.g. --doi X --source-id src-001)",
    )
    parser.add_argument(
        "--mailto", default=None,
        help="Email for Crossref polite pool (10 RPS instead of ~1 RPS)",
    )
    parser.add_argument(
        "--session-dir", default=None,
        help="Session directory (for rate limiter state and metadata merge)",
    )
    parser.add_argument(
        "--citation-data", action="store_true", default=False,
        help="Also fetch OpenCitations citation/reference counts for each DOI",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress stderr log output")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.quiet:
        set_quiet(True)

    # Resolve session dir (optional for enrich — only used for rate limiter)
    from _shared.config import _discover_session_dir_from_marker
    session_dir = args.session_dir or os.environ.get("DEEP_RESEARCH_SESSION_DIR") or _discover_session_dir_from_marker()
    if not session_dir:
        import tempfile
        session_dir = tempfile.mkdtemp(prefix="enrich_")

    # Build User-Agent for polite pool
    user_agent = _UA_TEMPLATE.format(email=args.mailto) if args.mailto else _UA_DEFAULT

    # Configure rate limits: 10 RPS with polite pool, 1 RPS without
    rate = 10.0 if args.mailto else 1.0
    client = create_session(
        session_dir,
        user_agent=user_agent,
        rate_limits={"api.crossref.org": rate},
    )

    # Metadata directory for merge operations
    metadata_dir = os.path.join(session_dir, "sources", "metadata")
    source_ids = args.source_id or []

    results = []
    errors = []

    try:
        for i, raw_doi in enumerate(args.doi):
            doi = normalize_doi(raw_doi)
            source_id = source_ids[i] if i < len(source_ids) else None
            log(f"Enriching DOI: {doi}" + (f" (source: {source_id})" if source_id else ""))

            try:
                data = _fetch_crossref(doi, client)
                if data:
                    # Merge into existing source metadata if source_id provided
                    if source_id and args.session_dir:
                        _merge_into_source(data, source_id, metadata_dir)
                        data["merged_into"] = source_id
                    results.append(data)
                else:
                    errors.append(f"No data found for DOI: {doi}")
            except Exception as e:
                log(f"Failed to enrich {doi}: {e}", level="error")
                errors.append(f"Error for {doi}: {e}")
    finally:
        client.close()

    # OpenCitations enrichment pass (additive — runs after Crossref)
    if args.citation_data and results:
        _enrich_with_opencitations(results, session_dir, errors)

    if results or not errors:
        success_response(results, total_results=len(results))
    else:
        error_response(errors, partial_results=results, error_code="enrichment_failed")


def _merge_into_source(crossref_data: dict, source_id: str, metadata_dir: str) -> None:
    """Merge Crossref enrichment data into existing source metadata using precedence rules."""
    existing = read_source_metadata(metadata_dir, source_id)
    if not existing:
        log(f"No existing metadata for {source_id}, writing fresh", level="debug")
        existing = {"id": source_id}

    # Normalize Crossref data through the standard pipeline
    normalized = normalize_paper(crossref_data, "crossref")
    normalized["id"] = source_id  # preserve source ID

    # Merge with deterministic precedence (Crossref is highest priority for most fields)
    merged = merge_metadata(existing, normalized)
    write_source_metadata(metadata_dir, source_id, merged)
    log(f"Merged Crossref metadata into {source_id}")


def _fetch_crossref(doi: str, client) -> dict | None:
    """Fetch metadata from Crossref API for a single DOI."""
    url = f"{_API_URL}/{doi}"

    resp = client.get(url, timeout=(15, 30))
    if resp.status_code == 404:
        log(f"DOI not found on Crossref: {doi}", level="warn")
        return None
    if resp.status_code != 200:
        log(f"Crossref returned {resp.status_code} for {doi}", level="warn")
        return None

    data = resp.json()
    message = data.get("message")
    if not message:
        return None

    return _parse_crossref(message, doi)


def _parse_crossref(msg: dict, doi: str) -> dict:
    """Parse Crossref API message into enrichment result."""
    # Title (array in Crossref)
    titles = msg.get("title") or []
    title = titles[0] if titles else ""

    # Authors
    authors = []
    for author in msg.get("author") or []:
        family = author.get("family", "")
        given = author.get("given", "")
        if family:
            name = f"{family}, {given}".strip(", ") if given else family
            authors.append(name)

    # Year from date-parts (check multiple fields)
    year = _extract_year(msg)

    # Venue
    venue_list = msg.get("container-title") or []
    venue = venue_list[0] if venue_list else ""

    # Abstract (strip JATS XML tags)
    abstract = msg.get("abstract", "") or ""
    if abstract:
        abstract = strip_jats_xml(abstract)

    # Retraction detection
    is_retracted = msg.get("is-retracted", False) or False

    # Check update-to array for retraction notices
    if not is_retracted:
        for update in msg.get("update-to") or []:
            if update.get("type") == "retraction":
                is_retracted = True
                break

    # Check if this record IS a retraction notice
    if msg.get("type") == "retraction":
        is_retracted = True

    return {
        "doi": doi,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "volume": msg.get("volume", "") or "",
        "issue": msg.get("issue", "") or "",
        "pages": msg.get("page", "") or "",
        "publisher": msg.get("publisher", "") or "",
        "abstract": abstract,
        "cited_by_count": msg.get("is-referenced-by-count") or 0,
        "type": msg.get("type", "") or "",
        "is_retracted": is_retracted,
        "url": msg.get("URL", "") or f"https://doi.org/{doi}",
    }


def _extract_year(msg: dict) -> int:
    """Extract year from Crossref date-parts format.

    Checks: published-print → published-online → issued → created
    Format: {"date-parts": [[2024, 3, 15]]}
    """
    for field in ("published-print", "published-online", "issued", "created"):
        date_info = msg.get(field)
        if date_info and "date-parts" in date_info:
            parts = date_info["date-parts"]
            if parts and parts[0] and parts[0][0]:
                return int(parts[0][0])
    return 0


def _enrich_with_opencitations(results: list[dict], session_dir: str, errors: list[str]) -> None:
    """Add OpenCitations citation/reference counts to enrichment results."""
    oc_client = create_session(
        session_dir,
        rate_limits={"api.opencitations.net": 2.5},
    )
    oc_base = "https://api.opencitations.net/index/v2"

    try:
        for item in results:
            doi = item.get("doi", "")
            if not doi:
                continue

            # Citation count (forward)
            try:
                resp = oc_client.get(f"{oc_base}/citation-count/doi:{doi}")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        item["opencitations_citation_count"] = int(data[0].get("count", 0))
                    elif isinstance(data, dict):
                        item["opencitations_citation_count"] = int(data.get("count", 0))
                    log(f"OpenCitations citation count for {doi}: {item.get('opencitations_citation_count', 'N/A')}")
                else:
                    log(f"OpenCitations citation-count returned {resp.status_code} for {doi}", level="warn")
            except Exception as e:
                log(f"OpenCitations citation-count failed for {doi}: {e}", level="warn")
                errors.append(f"OpenCitations citation-count error for {doi}: {e}")

            # Reference count (backward)
            try:
                resp = oc_client.get(f"{oc_base}/reference-count/doi:{doi}")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        item["opencitations_reference_count"] = int(data[0].get("count", 0))
                    elif isinstance(data, dict):
                        item["opencitations_reference_count"] = int(data.get("count", 0))
                    log(f"OpenCitations reference count for {doi}: {item.get('opencitations_reference_count', 'N/A')}")
                else:
                    log(f"OpenCitations reference-count returned {resp.status_code} for {doi}", level="warn")
            except Exception as e:
                log(f"OpenCitations reference-count failed for {doi}: {e}", level="warn")
                errors.append(f"OpenCitations reference-count error for {doi}: {e}")
    finally:
        oc_client.close()


if __name__ == "__main__":
    main()
