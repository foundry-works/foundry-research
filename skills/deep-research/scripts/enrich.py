#!/usr/bin/env python3
"""DOI metadata enrichment with provider cascade: Crossref → OpenAlex → Semantic Scholar."""

import argparse
import json
import os
import sys
import time

# Add parent directory so _shared imports work when run from any location
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shared.doi_utils import normalize_doi  # noqa: E402
from _shared.http_client import create_session  # noqa: E402
from _shared.metadata import (  # noqa: E402
    _safe_int,
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

# Semantic Scholar fields to request (matches providers/semantic_scholar.py)
_S2_FIELDS = "paperId,title,abstract,authors,citationCount,year,externalIds,url,openAccessPdf,venue,journal,isRetracted"

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich DOIs with bibliographic metadata (Crossref → OpenAlex → Semantic Scholar cascade).",
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
        help="Email for Crossref/OpenAlex polite pool (higher rate limits)",
    )
    parser.add_argument(
        "--session-dir", default=None,
        help="Session directory (for rate limiter state and metadata merge)",
    )
    parser.add_argument(
        "--citation-data", action="store_true", default=False,
        help="Also fetch OpenCitations citation/reference counts for each DOI",
    )
    parser.add_argument(
        "--force", action="store_true", default=False,
        help="Re-fetch metadata even for already-enriched sources",
    )
    parser.add_argument(
        "--timeout", type=int, default=120,
        help="Wall-clock timeout in seconds for OpenCitations pass and metadata cascade (default: 120)",
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

    # Configure rate limits: polite pool gets higher rates
    crossref_rate = 10.0 if args.mailto else 1.0
    openalex_rate = 10.0  # OpenAlex polite pool just needs mailto param
    clients = _create_clients(session_dir, user_agent, crossref_rate, openalex_rate)

    # Metadata directory for merge operations
    metadata_dir = os.path.join(session_dir, "sources", "metadata")
    source_ids = args.source_id or []

    results = []
    errors = []
    stats = {"attempted": len(args.doi), "skipped": 0, "crossref_success": 0,
             "openalex_fallback": 0, "s2_fallback": 0, "failed": 0}

    # Dedup DOIs (preserve order and parallel source_id alignment)
    seen_dois: set[str] = set()
    deduped: list[tuple[int, str]] = []
    for i, raw_doi in enumerate(args.doi):
        norm = normalize_doi(raw_doi)
        if norm not in seen_dois:
            seen_dois.add(norm)
            deduped.append((i, raw_doi))

    cascade_deadline = time.monotonic() + args.timeout

    try:
        for i, raw_doi in deduped:
            doi = normalize_doi(raw_doi)
            source_id = source_ids[i] if i < len(source_ids) else None
            log(f"Enriching DOI: {doi}" + (f" (source: {source_id})" if source_id else ""))

            # Skip already-enriched sources unless --force
            if source_id and args.session_dir and not args.force and _is_already_enriched(source_id, metadata_dir):
                log(f"Already enriched {source_id} (Crossref), skipping (use --force to re-fetch)")
                stats["skipped"] += 1
                continue

            # Check cascade wall-clock deadline
            if time.monotonic() > cascade_deadline:
                log(f"Metadata cascade timeout ({args.timeout}s) — skipping remaining DOIs", level="warn")
                errors.append(f"Metadata cascade timed out after {args.timeout}s")
                break

            try:
                data = _fetch_metadata_cascade(doi, clients, args.mailto)
                if data:
                    provider = data.get("_provider", "unknown")
                    if provider == "crossref":
                        stats["crossref_success"] += 1
                    elif provider == "openalex":
                        stats["openalex_fallback"] += 1
                    elif provider == "semantic_scholar":
                        stats["s2_fallback"] += 1
                    # Merge into existing source metadata if source_id provided
                    if source_id and args.session_dir:
                        _merge_into_source(data, source_id, metadata_dir)
                        data["merged_into"] = source_id
                    results.append(data)
                else:
                    stats["failed"] += 1
                    errors.append(f"No data found for DOI: {doi} (all providers failed)")
            except Exception as e:
                stats["failed"] += 1
                log(f"Failed to enrich {doi}: {e}", level="error")
                errors.append(f"Error for {doi}: {e}")
    finally:
        for c in clients.values():
            c.close()

    # OpenCitations enrichment pass (additive — runs after metadata cascade)
    if args.citation_data and results:
        _enrich_with_opencitations(results, session_dir, errors, timeout=args.timeout)

    # Always include errors in response — even on partial success
    if results:
        success_response(results, total_results=len(results), errors=errors,
                         enrichment_stats=stats)
    else:
        error_response(errors, partial_results=results, error_code="enrichment_failed",
                       enrichment_stats=stats)


def _create_clients(session_dir: str, user_agent: str, crossref_rate: float, openalex_rate: float) -> dict:
    """Create per-provider HTTP clients with appropriate rate limits."""
    return {
        "crossref": create_session(
            session_dir,
            user_agent=user_agent,
            rate_limits={"api.crossref.org": crossref_rate},
        ),
        "openalex": create_session(
            session_dir,
            user_agent=user_agent,
            rate_limits={"api.openalex.org": openalex_rate},
        ),
        "semantic_scholar": create_session(
            session_dir,
            rate_limits={"api.semanticscholar.org": 1.0},
        ),
    }


def _is_already_enriched(source_id: str, metadata_dir: str) -> bool:
    """Check if a source already has Crossref-specific enrichment.

    Sources populated by Semantic Scholar or OpenAlex have basic fields (title, authors,
    year, venue) but lack Crossref-specific data: volume, issue, pages, retraction status,
    and authoritative venue names. Only skip if Crossref has already contributed.
    """
    existing = read_source_metadata(metadata_dir, source_id)
    if not existing:
        return False
    # Require that Crossref specifically has enriched this source — not just any provider.
    # S2/OpenAlex fill title/authors/year/venue but miss volume/issue/pages/retraction.
    enriched_by = existing.get("enriched_by", [])
    if isinstance(enriched_by, list) and "crossref" in enriched_by:
        return True
    # Legacy check: if provider itself is crossref, it came from Crossref originally
    return existing.get("provider") == "crossref"


def _fetch_metadata_cascade(doi: str, clients: dict, mailto: str | None = None) -> dict | None:
    """Try Crossref → OpenAlex → Semantic Scholar, return first success or None.

    Crossref is tried first because it's authoritative for venue, year, and retraction data.
    OpenAlex and Semantic Scholar serve as fallbacks for preprints, DataCite DOIs, and
    very new papers that Crossref may not yet index.
    """
    # 1. Crossref (authoritative for venue/year/retraction)
    data = _fetch_crossref(doi, clients["crossref"])
    if data:
        return data

    # 2. OpenAlex fallback
    log(f"Crossref miss for {doi}, trying OpenAlex", level="debug")
    data = _fetch_openalex(doi, clients["openalex"], mailto)
    if data:
        return data

    # 3. Semantic Scholar fallback
    log(f"OpenAlex miss for {doi}, trying Semantic Scholar", level="debug")
    data = _fetch_semantic_scholar(doi, clients["semantic_scholar"])
    if data:
        return data

    log(f"All providers failed for DOI: {doi}", level="warn")
    return None


def _merge_into_source(enrichment_data: dict, source_id: str, metadata_dir: str) -> None:
    """Merge enrichment data into existing source metadata using precedence rules."""
    existing = read_source_metadata(metadata_dir, source_id)
    if not existing:
        log(f"No existing metadata for {source_id}, writing fresh", level="debug")
        existing = {"id": source_id}

    # Normalize through the standard pipeline using the provider tag
    provider = enrichment_data.get("_provider", "crossref")
    normalized = normalize_paper(enrichment_data, provider)
    normalized["id"] = source_id  # preserve source ID

    # Merge with deterministic precedence
    merged = merge_metadata(existing, normalized)

    # Track which providers have enriched this source
    enriched_by = merged.get("enriched_by", [])
    if not isinstance(enriched_by, list):
        enriched_by = []
    if provider not in enriched_by:
        enriched_by.append(provider)
    merged["enriched_by"] = enriched_by

    write_source_metadata(metadata_dir, source_id, merged)
    log(f"Merged {provider} metadata into {source_id}")


def _to_enrichment_result(normalized: dict, doi: str, provider: str) -> dict:
    """Convert normalize_paper() output to the enrichment result format."""
    return {
        "doi": doi,
        "title": normalized.get("title", ""),
        "authors": normalized.get("authors", []),
        "year": normalized.get("year", 0),
        "venue": normalized.get("venue", ""),
        "abstract": normalized.get("abstract", ""),
        "cited_by_count": normalized.get("citation_count", 0),
        "is_retracted": normalized.get("is_retracted", False),
        "url": normalized.get("url", "") or f"https://doi.org/{doi}",
        "pdf_url": normalized.get("pdf_url", ""),
        "_provider": provider,
    }


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

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        log(f"Crossref returned invalid JSON for {doi}", level="warn")
        return None

    message = data.get("message")
    if not message:
        return None

    normalized = normalize_paper(message, "crossref")
    if not normalized.get("title"):
        return None

    return _to_enrichment_result(normalized, doi, "crossref")


def _fetch_openalex(doi: str, client, mailto: str | None = None) -> dict | None:
    """Fetch metadata from OpenAlex API for a single DOI.

    Uses the works endpoint with DOI lookup. The mailto param enables the polite pool.
    """
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    params = {}
    if mailto:
        params["mailto"] = mailto

    try:
        resp = client.get(url, params=params, timeout=(15, 30))
    except Exception as e:
        log(f"OpenAlex request failed for {doi}: {e}", level="warn")
        return None

    if resp.status_code == 404:
        log(f"DOI not found on OpenAlex: {doi}", level="warn")
        return None
    if resp.status_code != 200:
        log(f"OpenAlex returned {resp.status_code} for {doi}", level="warn")
        return None

    try:
        raw = resp.json()
    except (json.JSONDecodeError, ValueError):
        log(f"OpenAlex returned invalid JSON for {doi}", level="warn")
        return None

    normalized = normalize_paper(raw, "openalex")
    if not normalized.get("title"):
        return None

    return _to_enrichment_result(normalized, doi, "openalex")


def _fetch_semantic_scholar(doi: str, client) -> dict | None:
    """Fetch metadata from Semantic Scholar API for a single DOI.

    S2 is rate-limited to 1 RPS without an API key, so this is the last-resort fallback.
    """
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    params = {"fields": _S2_FIELDS}

    try:
        resp = client.get(url, params=params, timeout=(15, 30))
    except Exception as e:
        log(f"Semantic Scholar request failed for {doi}: {e}", level="warn")
        return None

    if resp.status_code == 404:
        log(f"DOI not found on Semantic Scholar: {doi}", level="warn")
        return None
    if resp.status_code != 200:
        log(f"Semantic Scholar returned {resp.status_code} for {doi}", level="warn")
        return None

    try:
        raw = resp.json()
    except (json.JSONDecodeError, ValueError):
        log(f"Semantic Scholar returned invalid JSON for {doi}", level="warn")
        return None

    normalized = normalize_paper(raw, "semantic_scholar")
    if not normalized.get("title"):
        return None

    return _to_enrichment_result(normalized, doi, "semantic_scholar")




def _enrich_with_opencitations(results: list[dict], session_dir: str, errors: list[str],
                               timeout: int = 120) -> None:
    """Add OpenCitations citation/reference counts to enrichment results.

    If OpenCitations fails for a DOI, the cascade result's cited_by_count is preserved —
    OC data is purely additive and never overwrites existing citation counts.
    """
    oc_client = create_session(
        session_dir,
        rate_limits={"api.opencitations.net": 2.5},
    )
    oc_base = "https://api.opencitations.net/index/v2"
    deadline = time.monotonic() + timeout

    try:
        for item in results:
            if time.monotonic() > deadline:
                log(f"OpenCitations batch timeout ({timeout}s) — skipping remaining DOIs", level="warn")
                errors.append(f"OpenCitations pass timed out after {timeout}s")
                break

            doi = item.get("doi", "")
            if not doi:
                continue

            # Citation count (forward)
            try:
                resp = oc_client.get(f"{oc_base}/citation-count/doi:{doi}")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        item["opencitations_citation_count"] = _safe_int(data[0].get("count", 0))
                    elif isinstance(data, dict):
                        item["opencitations_citation_count"] = _safe_int(data.get("count", 0))
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
                        item["opencitations_reference_count"] = _safe_int(data[0].get("count", 0))
                    elif isinstance(data, dict):
                        item["opencitations_reference_count"] = _safe_int(data.get("count", 0))
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
