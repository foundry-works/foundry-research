#!/usr/bin/env python3
"""Content & PDF downloader — web extraction, PDF cascade, local ingestion."""

import argparse
import contextlib
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory so _shared imports work when run from any location
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shared.config import get_config, get_session_dir  # noqa: E402
from _shared.doi_utils import extract_arxiv_id, normalize_doi  # noqa: E402
from _shared.html_extract import extract_readable_content  # noqa: E402
from _shared.http_client import create_session  # noqa: E402
from _shared.metadata import (  # noqa: E402
    PAPER_SCHEMA,
    merge_metadata,
    normalize_paper,
    read_source_metadata,
    write_source_metadata,
)
from _shared.mirrors import download_annas_archive, download_scihub  # noqa: E402
from _shared.output import error_response, log, set_quiet, success_response  # noqa: E402
from _shared.pdf_utils import download_pdf, extract_first_page_text, pdf_to_markdown  # noqa: E402
from _shared.quality import (  # noqa: E402
    _extract_candidate_title,
    _extract_keywords,
    assess_quality,
    check_content_mismatch,
)
from _shared.state_client import call_state  # noqa: E402

# arXiv download constraints
_ARXIV_DELAY = 3.0  # seconds between arXiv downloads (ToS)
_CAPTCHA_SIZE_THRESHOLD = 100 * 1024  # 100KB
_CAPTCHA_MARKERS = (b"<html", b"captcha", b"<!doctype")

# PDF cascade source names
_ALL_CASCADE_SOURCES = ["openalex", "unpaywall", "arxiv", "pmc", "osf", "annas_archive", "scihub"]


def _effective_cascade_sources(config: dict) -> list[str]:
    disabled = set(config.get("disabled_sources") or [])
    sources = [s for s in _ALL_CASCADE_SOURCES if s not in disabled]
    if disabled:
        log(f"Disabled cascade sources: {sorted(disabled)}")
    return sources


def _check_title_divergence(content: str, meta: dict) -> str | None:
    """Compare extracted document title against metadata title.

    Returns the extracted title if it diverges significantly from the
    provider-supplied title (Jaccard keyword similarity < 0.6), or None
    if titles are consistent. Used to populate the informational
    ``title_from_content`` metadata field so the synthesis-writer can
    detect version/edition mismatches that pass mismatch detection.
    """
    provider_title = meta.get("title", "")
    if not provider_title:
        return None

    candidate = _extract_candidate_title(content)
    if not candidate or len(candidate) < 10:
        return None

    provider_kws = set(_extract_keywords(provider_title))
    candidate_kws = set(_extract_keywords(candidate))
    if not provider_kws or not candidate_kws:
        return None

    # Jaccard similarity
    intersection = provider_kws & candidate_kws
    union = provider_kws | candidate_kws
    similarity = len(intersection) / len(union) if union else 1.0

    if similarity < 0.6:
        return candidate
    return None


def _get_brief_keywords(session_dir: str) -> list[str]:
    """Extract domain-specific keywords from the research brief in state.db.

    Returns a short list of high-signal terms drawn from the brief's scope
    and questions. These are used by check_content_mismatch() to catch
    off-topic papers that slip past title/author matching (e.g., a geology
    paper matching "uncanny valley" title words in a psychology session).
    """
    import sqlite3

    from _shared.quality import _extract_keywords

    db_path = os.path.join(session_dir, "state.db")
    if not os.path.exists(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT scope, questions FROM brief LIMIT 1"
        ).fetchone()
        conn.close()
    except Exception:
        return []

    if not row:
        return []

    # Combine scope + question text into one blob for keyword extraction
    parts = [row["scope"] or ""]
    try:
        questions = json.loads(row["questions"]) if row["questions"] else []
        for q in questions:
            if isinstance(q, str):
                parts.append(q)
            elif isinstance(q, dict):
                parts.append(q.get("question", "") or q.get("text", ""))
    except (json.JSONDecodeError, TypeError):
        pass

    combined = " ".join(parts)
    if not combined.strip():
        return []

    # Extract keywords, deduplicate, prefer longer (more domain-specific) terms
    kws = _extract_keywords(combined)
    seen: set[str] = set()
    unique: list[str] = []
    for kw in sorted(kws, key=len, reverse=True):
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    # Cap at 15 — enough to cover domain terms without noise
    return unique[:15]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download web content, PDFs, or run multi-source PDF cascade.",
    )

    # Input modes (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--url", help="Web page URL to download and extract")
    input_group.add_argument("--pdf-url", help="Direct PDF URL to download")
    input_group.add_argument("--doi", help="DOI for multi-source PDF cascade")
    input_group.add_argument("--arxiv", help="arXiv ID for PDF download")
    input_group.add_argument("--local-dir", help="Local directory to ingest papers from")
    input_group.add_argument("--from-json", help="JSON file with batch download list")

    # Common flags
    parser.add_argument("--source-id", default=None, help="Source ID (e.g. src-001)")
    parser.add_argument("--session-dir", default=None, help="Session directory")
    parser.add_argument("--to-md", action="store_true", default=False, help="Convert PDFs to markdown")
    parser.add_argument("--parallel", type=int, default=1, help="Parallel downloads for batch mode")

    # Recovery
    parser.add_argument("--retry-sync", action="store_true", default=False,
                        help="Re-sync sources that have on-disk files but pending status in state.db")

    # Metadata flags
    parser.add_argument("--type", default="academic", choices=["academic", "web", "reddit", "code"],
                        help="Source type")
    parser.add_argument("--title", default=None, help="Source title")
    parser.add_argument("--authors", nargs="+", default=None, help="Author names")
    parser.add_argument("--year", type=int, default=None, help="Publication year")
    parser.add_argument("--venue", default=None, help="Publication venue")
    parser.add_argument("--citation-count", type=int, default=None, help="Citation count")
    parser.add_argument("--quiet", action="store_true", help="Suppress stderr log output")
    parser.add_argument("--summary-only", action="store_true",
                        help="Return only counts (success/failed/remaining), with per-source details only for failures")

    return parser


def _sync_to_state(session_dir: str, result: dict) -> bool:
    """Sync content_file and pdf_file paths to state.db after download.

    Returns True if sync succeeded, False on any failure.
    """
    source_id = result.get("source_id")
    if not source_id:
        return False

    update = {}
    if result.get("content_file"):
        content_path = os.path.join(session_dir, result["content_file"])
        if os.path.exists(content_path):
            update["content_file"] = result["content_file"]
        else:
            log(f"content_file claimed but missing: {result['content_file']}")
    if result.get("pdf_file"):
        pdf_path = os.path.join(session_dir, result["pdf_file"])
        if os.path.exists(pdf_path):
            update["pdf_file"] = result["pdf_file"]
        else:
            log(f"pdf_file claimed but missing: {result['pdf_file']}")
    # Only mark downloaded if at least one verified file exists on disk
    if update.get("content_file") or update.get("pdf_file"):
        update["status"] = "downloaded"
    if result.get("quality"):
        update["quality"] = result["quality"]

    if not update:
        # Check if files exist on disk that we didn't pick up — this catches
        # edge cases where download succeeded but result dict lacks the paths
        if source_id:
            sources_dir = os.path.join(session_dir, "sources")
            md_exists = os.path.exists(os.path.join(sources_dir, f"{source_id}.md"))
            pdf_exists = os.path.exists(os.path.join(sources_dir, f"{source_id}.pdf"))
            if md_exists or pdf_exists:
                log(f"WARNING: {source_id} has on-disk files "
                    f"(md={md_exists}, pdf={pdf_exists}) but sync found "
                    f"nothing to update — result dict may be missing paths")
        return True  # nothing to sync is not a failure

    resp = call_state(
        session_dir, "update-source",
        args=["--id", source_id],
        json_data=update,
        timeout=5,
    )
    return resp is not None


def _handle_retry_sync(session_dir: str) -> None:
    """Re-sync sources that have on-disk files but still show pending in state.db."""
    import sqlite3

    db_path = os.path.join(session_dir, "state.db")
    if not os.path.exists(db_path):
        error_response(["No state.db found"], error_code="no_state")
        return

    sources_dir = os.path.join(session_dir, "sources")
    brief_keywords = _get_brief_keywords(session_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Find sources still pending
    rows = conn.execute(
        "SELECT id FROM sources WHERE status = 'pending' OR status IS NULL"
    ).fetchall()
    conn.close()

    synced = []
    failed = []
    skipped = []

    for row in rows:
        sid = row["id"]
        # Check for on-disk files
        md_file = os.path.join(sources_dir, f"{sid}.md")
        pdf_file = os.path.join(sources_dir, f"{sid}.pdf")

        result = {"source_id": sid, "_brief_keywords": brief_keywords}
        has_file = False

        if os.path.exists(md_file):
            result["content_file"] = f"sources/{sid}.md"
            has_file = True
        if os.path.exists(pdf_file):
            result["pdf_file"] = f"sources/{sid}.pdf"
            result["pdf_downloaded"] = True
            has_file = True

        if not has_file:
            skipped.append(sid)
            continue

        # Recover quality from metadata JSON if available
        metadata_dir = os.path.join(sources_dir, "metadata")
        meta_file = os.path.join(metadata_dir, f"{sid}.json")
        meta = {}
        if os.path.exists(meta_file):
            try:
                meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
                result["quality"] = meta.get("quality", "ok")
            except (json.JSONDecodeError, OSError):
                result["quality"] = "ok"
        else:
            result["quality"] = "ok"

        # Re-verify content for sources that look "ok" — catches files
        # downloaded before mismatch/paywall detection was added.
        if result["quality"] == "ok" and os.path.exists(md_file):
            try:
                content = Path(md_file).read_text(encoding="utf-8")
                # Paywall / structural quality check
                qa = assess_quality(content)
                if qa["quality"] != "ok":
                    result["quality"] = qa["quality"]
                    result["quality_details"] = qa["quality_details"]
                    meta["quality"] = qa["quality"]
                    meta["quality_details"] = qa["quality_details"]
                # Semantic mismatch check against expected metadata
                title = meta.get("title", "")
                authors = meta.get("authors")
                if result["quality"] == "ok" and (title or authors):
                    mismatch = check_content_mismatch(
                        content, title=title, authors=authors,
                        abstract=meta.get("abstract", ""),
                        brief_keywords=brief_keywords,
                    )
                    if mismatch["mismatched"]:
                        result["quality"] = "mismatched"
                        meta["quality"] = "mismatched"
                        meta["quality_details"] = {
                            "reason": mismatch["reason"],
                            "title_hits": mismatch["title_hits"],
                            "author_hits": mismatch["author_hits"],
                        }
                        log(f"Retry-sync mismatch for {sid}: {mismatch['reason']}", level="warn")
                # Title divergence check — populate title_from_content
                # when the extracted document title differs from provider metadata.
                if result["quality"] == "ok":
                    alt_title = _check_title_divergence(content, meta)
                    if alt_title:
                        meta["title_from_content"] = alt_title
                        log(f"Title divergence for {sid}: extracted '{alt_title}'", level="info")
                # Persist updated quality back to metadata JSON
                if meta.get("quality") and os.path.exists(meta_file):
                    Path(meta_file).write_text(
                        json.dumps(meta, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
            except OSError:
                pass  # content unreadable — keep whatever quality we had

        if _sync_to_state(session_dir, result):
            synced.append(sid)
        else:
            failed.append(sid)

    success_response({
        "synced": synced,
        "failed": failed,
        "skipped": skipped,
        "total_pending": len(rows),
    })


def _auto_create_web_source(session_dir: str, source_id: str, url: str, meta: dict) -> None:
    """Auto-create a new source entry in state.db for a web download not already tracked."""
    source_data = {
        "title": meta.get("title") or url,
        "url": url,
        "type": "web",
        "provider": "web",
    }
    if meta.get("authors"):
        source_data["authors"] = meta["authors"]
    if meta.get("year"):
        source_data["year"] = meta["year"]

    resp = call_state(
        session_dir, "add-sources",
        json_data=[source_data],
        timeout=5,
    )
    if resp is not None:
        log(f"Auto-created web source in state.db for {url} → {source_id}")


def _resolve_source_id(session_dir: str, source_id: str) -> dict:
    """Look up DOI, URL, and metadata from state.db by source ID.

    Returns dict with keys: doi, url, pdf_url, title, authors, year, venue, type.
    """
    import sqlite3 as _sqlite3

    db_path = os.path.join(session_dir, "state.db")
    if not os.path.exists(db_path):
        error_response([f"No state.db found in {session_dir}"], error_code="no_state")
        sys.exit(0)

    conn = _sqlite3.connect(db_path)
    try:
        conn.row_factory = _sqlite3.Row
        row = conn.execute(
            "SELECT doi, url, pdf_url, title, authors, year, venue, type FROM sources WHERE id = ?",
            (source_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        error_response([f"Source {source_id} not found in state.db"], error_code="source_not_found")
        sys.exit(0)

    return dict(row)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.quiet:
        set_quiet(True)

    # Resolve --source-id as standalone input mode (look up DOI/URL from state.db)
    if args.source_id and not any([args.url, args.pdf_url, args.doi, args.arxiv, args.local_dir, args.from_json]):
        session_dir = get_session_dir(args)
        source_info = _resolve_source_id(session_dir, args.source_id)
        log(f"Resolved {args.source_id}: doi={source_info.get('doi')}, url={source_info.get('url')}")

        # Set download mode based on available identifiers
        if source_info.get("doi"):
            args.doi = source_info["doi"]
            args.to_md = True  # default to markdown conversion for DOI downloads
        elif source_info.get("pdf_url"):
            args.pdf_url = source_info["pdf_url"]
            args.to_md = True
        elif source_info.get("url"):
            args.url = source_info["url"]
            args.type = source_info.get("type") or "web"
        else:
            error_response(
                [f"Source {args.source_id} has no DOI, URL, or PDF URL to download"],
                error_code="no_download_target",
            )

        # Carry metadata from state.db into download
        if not args.title and source_info.get("title"):
            args.title = source_info["title"]
        if not args.year and source_info.get("year"):
            args.year = source_info["year"]
        if not args.venue and source_info.get("venue"):
            args.venue = source_info["venue"]

    # Require at least one input mode
    if not any([args.url, args.pdf_url, args.doi, args.arxiv, args.local_dir, args.from_json]):
        error_response(
            ["No input specified. Use --url, --pdf-url, --doi, --arxiv, --local-dir, --from-json, or --source-id"],
            error_code="missing_input",
        )

    # Resolve session directory
    session_dir = get_session_dir(args)
    config = get_config(session_dir)

    # Handle --retry-sync: re-sync sources with on-disk files but pending DB status
    if args.retry_sync:
        _handle_retry_sync(session_dir)
        return

    # Fetch brief keywords once for content mismatch detection
    brief_keywords = _get_brief_keywords(session_dir)
    if brief_keywords:
        log(f"Brief keywords for mismatch detection: {brief_keywords[:5]}...")

    # Sources directory
    sources_dir = os.path.join(session_dir, "sources")
    metadata_dir = os.path.join(sources_dir, "metadata")
    os.makedirs(metadata_dir, exist_ok=True)

    # Dispatch to handler
    if args.local_dir:
        result = _handle_local_dir(args, session_dir, sources_dir, metadata_dir)
    elif args.from_json:
        result = _handle_batch(args, session_dir, sources_dir, metadata_dir, config,
                               brief_keywords=brief_keywords)
    else:
        client = create_session(session_dir)
        try:
            result = _handle_single(args, client, session_dir, sources_dir, metadata_dir, config,
                                    brief_keywords=brief_keywords)
        finally:
            client.close()

    # Sync downloaded file paths to state.db (if session has state tracking)
    sync_failures = []
    if os.path.exists(os.path.join(session_dir, "state.db")):
        if isinstance(result, list):
            for r in result:
                if not _sync_to_state(session_dir, r):
                    sid = r.get("source_id")
                    if sid:
                        sync_failures.append(sid)
        else:
            if not _sync_to_state(session_dir, result):
                sid = result.get("source_id")
                if sid:
                    sync_failures.append(sid)

    # Output result
    summary_only = getattr(args, "summary_only", False)
    extra = {}
    if sync_failures:
        extra["sync_failures"] = sync_failures
    if isinstance(result, list):
        if summary_only:
            succeeded = [r for r in result if r.get("content_file") or r.get("pdf_file")]
            failed = [r for r in result if not r.get("content_file") and not r.get("pdf_file")]
            summary = {
                "downloaded": len(succeeded),
                "failed": len(failed),
                "total": len(result),
                "failed_sources": [
                    {"source_id": r.get("source_id"), "errors": r.get("errors", [])}
                    for r in failed
                ],
            }
            success_response(summary, total_results=len(result), **extra)
        else:
            success_response(result, total_results=len(result), **extra)
    else:
        if sync_failures:
            result["sync_failures"] = sync_failures
        success_response(result)


def _handle_single(args, client, _session_dir: str, sources_dir: str,
                   metadata_dir: str, config: dict,
                   cancel: threading.Event | None = None,
                   brief_keywords: list[str] | None = None) -> dict:
    """Handle a single download (URL, PDF URL, DOI, or arXiv)."""
    source_id = args.source_id
    if not source_id:
        doi = normalize_doi(args.doi) if args.doi else None
        url = args.url if hasattr(args, "url") else None
        source_id = _lookup_source_id_from_state(_session_dir, doi, url=url)
        if source_id:
            log(f"Matched existing source: {source_id}")
    is_new_source = False
    if not source_id:
        source_id = _generate_source_id(sources_dir)
        is_new_source = True
    result: dict = {
        "source_id": source_id,
        "doi": None,
        "content_file": None,
        "pdf_file": None,
        "content_length": 0,
        "pdf_size_bytes": 0,
        "pdf_downloaded": False,
        "md_converted": False,
        "toc_file": None,
        "source_used": None,
        "sources_tried": [],
        "errors": [],
    }

    # Build initial metadata from CLI flags
    meta = _build_metadata(args, source_id)

    # Store expected metadata for content mismatch detection
    result["_expected_title"] = meta.get("title", "")
    result["_expected_authors"] = meta.get("authors", [])
    result["_expected_abstract"] = meta.get("abstract", "")
    result["_brief_keywords"] = brief_keywords or []

    if args.url:
        _download_web(args.url, source_id, client, sources_dir, meta, result)
        # Auto-create source in state.db for web downloads without an existing source
        if is_new_source and result.get("content_file") and os.path.exists(os.path.join(_session_dir, "state.db")):
            _auto_create_web_source(_session_dir, source_id, args.url, meta)
    elif args.pdf_url:
        _download_direct_pdf(args.pdf_url, source_id, client, sources_dir, args.to_md, result)
        result["source_used"] = "direct"
    elif args.arxiv:
        arxiv_id = args.arxiv
        meta["provider"] = "arxiv"
        meta["url"] = f"https://arxiv.org/abs/{arxiv_id}"
        meta["pdf_url"] = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        result["doi"] = meta.get("doi")
        _download_arxiv(arxiv_id, source_id, client, sources_dir, args.to_md, result)
    elif args.doi:
        doi = normalize_doi(args.doi)
        meta["doi"] = doi
        result["doi"] = doi
        _download_by_doi(doi, source_id, client, sources_dir, metadata_dir,
                         args.to_md, config, result, cancel=cancel)

    # Write metadata
    if result.get("pdf_downloaded"):
        meta["has_pdf"] = True
    if result.get("pdf_file"):
        meta["pdf_url"] = meta.get("pdf_url") or ""
    if result.get("content_file"):
        meta["content_file"] = result["content_file"]
    # Persist quality assessment so retry-sync can recover it from the JSON
    if result.get("quality"):
        meta["quality"] = result["quality"]
    if result.get("quality_details"):
        meta["quality_details"] = result["quality_details"]
    if result.get("title_from_content"):
        meta["title_from_content"] = result["title_from_content"]
    write_source_metadata(metadata_dir, source_id, meta)

    # Auto-enrich from Crossref if DOI available and metadata is sparse
    doi = meta.get("doi")
    if doi and _metadata_needs_enrichment(meta):
        _auto_enrich_crossref(doi, source_id, client, metadata_dir)

    # Prominently log the assigned source ID
    log(f">>> Assigned source ID: {source_id}")

    return result


_MAX_WEB_SIZE = 10 * 1024 * 1024  # 10MB cap on web page downloads
_MAX_WEB_STREAM_SECONDS = 120  # wall-clock cap on web page streaming


_PDF_CONTENT_ERROR = "URL served PDF content, not HTML"


def _stream_web_content(client, url: str, *,
                        max_size: int = _MAX_WEB_SIZE,
                        timeout: int = _MAX_WEB_STREAM_SECONDS) -> tuple[str | None, str | None]:
    """Stream URL and extract readable content.

    Returns (content, error_msg). On success error_msg is None.
    Handles: Content-Length check, streaming size cap, wall-clock timeout,
    PDF detection (via Content-Type and magic bytes), readable content extraction.
    """
    resp = client.get(url, stream=True, timeout=(15, timeout))
    try:
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code} for {url}"

        # Check Content-Type for PDF
        content_type = resp.headers.get("Content-Type", "")
        if "application/pdf" in content_type.lower():
            return None, _PDF_CONTENT_ERROR

        try:
            cl = int(resp.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            cl = 0
        if cl > max_size:
            return None, f"Page too large ({cl} bytes, limit {max_size})"

        chunks: list[bytes] = []
        size = 0
        stream_start = time.monotonic()
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            # Check first chunk for PDF magic bytes
            if not chunks and isinstance(chunk, bytes) and chunk[:4] == b"%PDF":
                return None, _PDF_CONTENT_ERROR

            size += len(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
            if size > max_size:
                return None, f"Page exceeded {max_size // (1024*1024)}MB during download"
            if time.monotonic() - stream_start > timeout:
                return None, f"Streaming exceeded {timeout}s wall-clock limit"
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
    finally:
        resp.close()

    raw = b"".join(chunks)
    html = raw.decode("utf-8", errors="replace")
    content = extract_readable_content(html)
    if not content:
        return None, "No readable content extracted"
    return content, None


def _is_publisher_landing_page(url: str) -> bool:
    """Heuristic: does the URL strongly signal a publisher paywall landing page?

    Conservative — only matches patterns where web extraction almost never
    yields useful paper content.  False negatives (downloading a landing page
    that gets flagged by quality.py later) are acceptable; false positives
    (skipping a URL that actually serves full text) are not.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.lower()

    # ScienceDirect abstract pages
    if "sciencedirect.com" in host and "/abs/" in path:
        return True
    # Springer abstract pages (no /pdf/ or /fulltext/ in path)
    if "link.springer.com" in host and "/article/" in path and "/pdf/" not in path and "/fulltext/" not in path:
        return True
    # Wiley abstract pages
    if "onlinelibrary.wiley.com" in host and "/abs/" in path:
        return True
    # Taylor & Francis abstract pages
    if "tandfonline.com" in host and "/abs/" in path:
        return True
    # SAGE abstract pages
    if "journals.sagepub.com" in host and "/doi/abs/" in path:
        return True
    # IEEE abstract pages
    if "ieeexplore.ieee.org" in host and "/abstract/" in path.rstrip("/"):
        return True

    return False


def _download_web(url: str, source_id: str, client, sources_dir: str,
                  meta: dict, result: dict) -> None:
    """Download web page and extract readable content."""
    log(f"Downloading web content: {url}")

    # Pre-download heuristic: skip known publisher landing pages for academic
    # sources.  These serve paywall HTML that wastes bandwidth and gets flagged
    # as degraded by quality.py anyway.
    if _is_publisher_landing_page(url):
        log(f"Skipping probable publisher landing page: {url}")
        result["errors"].append(f"Skipped publisher landing page (heuristic): {url}")
        result["quality"] = "paywall_page"
        return

    try:
        content, error = _stream_web_content(client, url)

        # URL served PDF instead of HTML — download as PDF and convert
        if error == _PDF_CONTENT_ERROR:
            log(f"URL served PDF content, attempting PDF download: {url}")
            _download_direct_pdf(url, source_id, client, sources_dir,
                                 to_md=True, result=result)
            if result.get("pdf_downloaded"):
                meta["url"] = url
                meta["type"] = "pdf"
                return
            # If PDF download also failed, fall through to error reporting
            if not result["errors"]:
                result["errors"].append(error)
            return

        if error or not content:
            result["errors"].append(error or "No readable content extracted")
            return

        # Save as markdown
        md_path = os.path.join(sources_dir, f"{source_id}.md")
        Path(md_path).write_text(content, encoding="utf-8")

        # Quality check — catch paywall stubs, cookie banners, etc.
        qa = assess_quality(content)

        result["content_file"] = f"sources/{source_id}.md"
        result["content_length"] = len(content)
        result["source_used"] = "web"
        result["quality"] = qa["quality"]
        if qa["quality"] != "ok":
            result["quality_details"] = qa["quality_details"]

        # Semantic mismatch check: does extracted text match expected metadata?
        title = meta.get("title", "")
        authors = meta.get("authors")
        if result["quality"] == "ok" and (title or authors):
            mismatch = check_content_mismatch(
                content, title=title, authors=authors,
                abstract=meta.get("abstract", ""),
                brief_keywords=result.get("_brief_keywords"),
            )
            if mismatch["mismatched"]:
                result["quality"] = "mismatched"
                details = result.get("quality_details") or {}
                details["reasons"] = details.get("reasons", []) + [mismatch["reason"]]
                details["title_hits"] = mismatch["title_hits"]
                details["author_hits"] = mismatch["author_hits"]
                result["quality_details"] = details
                log(f"Content mismatch detected for {source_id}: {mismatch['reason']}", level="warn")

        # Title divergence check for accepted content
        if result["quality"] == "ok":
            alt_title = _check_title_divergence(content, meta)
            if alt_title:
                meta["title_from_content"] = alt_title
                log(f"Title divergence for {source_id}: extracted '{alt_title}'", level="info")

        meta["url"] = url
        meta["type"] = "web"
        log(f"Saved web content: {md_path} ({len(content)} chars, quality={result['quality']})")

    except Exception as e:
        result["errors"].append(f"Web download failed: {e}")


def _download_direct_pdf(url: str, source_id: str, client, sources_dir: str,
                         to_md: bool, result: dict) -> None:
    """Download a PDF from a direct URL."""
    pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
    log(f"Downloading PDF: {url}")

    dl_result = download_pdf(url, pdf_path, client)
    if not dl_result["success"]:
        result["errors"].extend(dl_result["errors"])
        return

    result["pdf_file"] = f"sources/{source_id}.pdf"
    result["pdf_size_bytes"] = dl_result["size_bytes"]
    result["pdf_downloaded"] = True

    if to_md:
        _convert_and_record(pdf_path, source_id, sources_dir, result,
                            title=result.get("_expected_title", ""),
                            authors=result.get("_expected_authors"),
                            abstract=result.get("_expected_abstract", ""))
    else:
        result["quality"] = "ok"


def _download_arxiv(arxiv_id: str, source_id: str, client, sources_dir: str,
                    to_md: bool, result: dict) -> None:
    """Download PDF from arXiv with CAPTCHA detection.

    Uses download_pdf for streaming with size limits. HttpClient handles
    retries on 429/500/502/503/504 internally, so no outer retry loop needed.
    """
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")

    log(f"Downloading arXiv PDF: {arxiv_id}")
    time.sleep(_ARXIV_DELAY)

    result["sources_tried"].append("arxiv")
    result["source_used"] = "arxiv"

    dl_result = download_pdf(pdf_url, pdf_path, client, timeout=60)

    if not dl_result["success"]:
        # Check if the error was an HTML/CAPTCHA response (download_pdf detects this)
        errors = dl_result.get("errors", [])
        if any("HTML instead of PDF" in e for e in errors):
            log(f"CAPTCHA or HTML response detected for arXiv {arxiv_id}", level="warn")
            result["errors"].append("arXiv CAPTCHA detected")
        else:
            result["errors"].extend(errors)
        return

    # Post-download CAPTCHA check: small files that passed PDF magic but are suspicious
    file_size = dl_result["size_bytes"]
    if file_size < _CAPTCHA_SIZE_THRESHOLD:
        with open(pdf_path, "rb") as f:
            head = f.read(1024).lower()
        if any(marker in head for marker in _CAPTCHA_MARKERS):
            log(f"CAPTCHA detected for arXiv {arxiv_id}", level="warn")
            os.unlink(pdf_path)
            result["errors"].append("arXiv CAPTCHA detected")
            return

    result["pdf_file"] = f"sources/{source_id}.pdf"
    result["pdf_size_bytes"] = file_size
    result["pdf_downloaded"] = True

    if to_md:
        _convert_and_record(pdf_path, source_id, sources_dir, result,
                    title=result.get("_expected_title", ""),
                    authors=result.get("_expected_authors"),
                    abstract=result.get("_expected_abstract", ""))
    else:
        result["quality"] = "ok"


def _record_pdf_success(result: dict, source_id: str, source_name: str,
                        pdf_path: str, pdf_size: int, sources_dir: str, to_md: bool) -> None:
    """Record a successful PDF download into the result dict."""
    result["pdf_file"] = f"sources/{source_id}.pdf"
    result["pdf_size_bytes"] = pdf_size
    result["pdf_downloaded"] = True
    result["source_used"] = source_name
    if to_md:
        _convert_and_record(pdf_path, source_id, sources_dir, result,
                            title=result.get("_expected_title", ""),
                            authors=result.get("_expected_authors"),
                            abstract=result.get("_expected_abstract", ""))
    else:
        result["quality"] = "ok"


def _early_mismatch_check(pdf_path: str, result: dict) -> bool:
    """Check if a downloaded PDF is clearly from the wrong paper.

    Extracts first-page text and checks for title keywords, author surnames,
    and brief domain keywords. Returns True if the content is a mismatch
    (caller should skip this source and try the next cascade source).
    """
    title = result.get("_expected_title", "")
    authors = result.get("_expected_authors") or []
    brief_keywords = result.get("_brief_keywords") or []
    if not title and not authors:
        return False  # no metadata to check against

    first_page = extract_first_page_text(pdf_path)
    if not first_page:
        return False  # can't extract text — let full conversion handle it

    from _shared.quality import _extract_keywords
    first_page_lower = first_page.lower()

    title_words = _extract_keywords(title) if title else []
    title_hits = sum(1 for w in title_words if w in first_page_lower) if title_words else 0

    author_hits = 0
    if authors:
        for author in authors[:5]:
            parts = author.split(",")
            surname = parts[0].strip().lower() if parts else ""
            if surname and len(surname) >= 3 and surname in first_page_lower:
                author_hits += 1

    has_title_keywords = len(title_words) >= 2
    has_authors = bool(authors)

    # Primary check: title/author metadata match
    mismatched = False
    if has_title_keywords and has_authors:
        mismatched = title_hits == 0 and author_hits == 0
    elif has_title_keywords:
        mismatched = title_hits == 0
    elif has_authors:
        mismatched = author_hits == 0

    if mismatched:
        return True

    # Brief-keyword gate: catch cross-domain mismatches (e.g., psychology paper
    # returning finance content) even when title words partially match due to
    # shared generic terms. Only flags when title match is also weak.
    # Uses full first-page text (not truncated) since first-page extraction
    # already scopes to page 1.
    brief_hits = 0
    if brief_keywords and title_hits < 3:
        brief_hits = sum(1 for kw in brief_keywords if kw.lower() in first_page_lower)
        if brief_hits == 0:
            return True

    # Title-to-content comparison: extract the actual title from the first
    # lines and compare against expected. Catches PDFs where the content is
    # a completely different paper that happens to share some generic terms.
    if title and title_words and title_hits < 2:
        first_lines = [ln.strip() for ln in first_page[:500].split("\n") if ln.strip()]
        if first_lines:
            candidate_title = first_lines[0]
            if len(first_lines) > 1 and len(first_lines[0]) < 30:
                candidate_title = first_lines[0] + " " + first_lines[1]
            candidate_kws = _extract_keywords(candidate_title)
            expected_kws = set(title_words)
            if candidate_kws and expected_kws:
                overlap = sum(1 for w in candidate_kws if w in expected_kws)
                if overlap == 0 and (not brief_keywords or brief_hits == 0):
                    return True

    return False


def _cleanup_mismatched_download(result: dict, source_id: str, sources_dir: str,
                                  source_name: str) -> bool:
    """Check if a completed download was flagged as mismatched after full conversion.

    If mismatched, delete the generated files and reset result fields so the
    cascade can continue to the next source. Returns True if mismatch was
    detected and cleaned up.
    """
    if result.get("quality") != "mismatched":
        return False

    log(f"Full mismatch detected after conversion from {source_name}, trying next cascade source", level="warn")

    # Remove generated files
    for ext in (".pdf", ".md", ".toc"):
        path = os.path.join(sources_dir, f"{source_id}{ext}")
        if os.path.exists(path):
            os.remove(path)

    # Reset result fields so next cascade source starts clean
    result["pdf_downloaded"] = False
    result["pdf_file"] = None
    result["pdf_size_bytes"] = 0
    result["md_converted"] = False
    result["content_file"] = None
    result["content_length"] = 0
    result["toc_file"] = None
    result["source_used"] = None
    result["quality"] = None
    result.pop("quality_details", None)
    return True


def _download_by_doi(doi: str, source_id: str, client, sources_dir: str,
                     _metadata_dir: str, to_md: bool, config: dict, result: dict,
                     cancel: threading.Event | None = None) -> None:
    """Run PDF cascade for a DOI: OpenAlex → Unpaywall → arXiv → PMC → Anna's → Sci-Hub."""
    log(f"Running PDF cascade for DOI: {doi}")

    # Try each source in order
    for source_name in _effective_cascade_sources(config):
        if cancel and cancel.is_set():
            result["errors"].append("Cancelled during PDF cascade")
            return
        result["sources_tried"].append(source_name)

        pdf_url = None
        try:
            if source_name == "openalex":
                pdf_url = _resolve_openalex(doi, client, config)
            elif source_name == "unpaywall":
                pdf_url = _resolve_unpaywall(doi, client, config)
            elif source_name == "arxiv":
                pdf_url = _resolve_arxiv_for_doi(doi, client)
            elif source_name == "pmc":
                pdf_url = _resolve_pmc(doi, client)
            elif source_name == "osf":
                pdf_url = _resolve_osf(doi, client, config, result.get("title", ""))
            elif source_name == "annas_archive":
                pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
                if download_annas_archive(doi, pdf_path, config, client):
                    if _early_mismatch_check(pdf_path, result):
                        log(f"Early mismatch: {source_name} PDF doesn't match expected metadata, skipping", level="warn")
                        os.remove(pdf_path)
                        continue
                    _record_pdf_success(result, source_id, "annas_archive",
                                        pdf_path, os.path.getsize(pdf_path), sources_dir, to_md)
                    if not _cleanup_mismatched_download(result, source_id, sources_dir, "annas_archive"):
                        return
                continue
            elif source_name == "scihub":
                pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
                if download_scihub(doi, pdf_path, client):
                    if _early_mismatch_check(pdf_path, result):
                        log(f"Early mismatch: {source_name} PDF doesn't match expected metadata, skipping", level="warn")
                        os.remove(pdf_path)
                        continue
                    _record_pdf_success(result, source_id, "scihub",
                                        pdf_path, os.path.getsize(pdf_path), sources_dir, to_md)
                    if not _cleanup_mismatched_download(result, source_id, sources_dir, "scihub"):
                        return
                continue
        except Exception as e:
            log(f"{source_name} lookup failed: {e}", level="warn")
            continue

        if not pdf_url:
            continue

        # Try downloading the resolved PDF URL
        pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
        log(f"Trying {source_name}: {pdf_url}")

        dl_result = download_pdf(pdf_url, pdf_path, client)
        if dl_result["success"]:
            # Early mismatch check before committing to full conversion
            if _early_mismatch_check(pdf_path, result):
                log(f"Early mismatch: {source_name} PDF doesn't match expected metadata, skipping", level="warn")
                os.remove(pdf_path)
                continue
            _record_pdf_success(result, source_id, source_name,
                                pdf_path, dl_result["size_bytes"], sources_dir, to_md)
            if _cleanup_mismatched_download(result, source_id, sources_dir, source_name):
                continue
            return
        log(f"{source_name} PDF download failed: {dl_result['errors']}", level="warn")

    # All sources exhausted — try DOI landing page as abstract fallback
    if not result["pdf_downloaded"]:
        log(f"All PDF cascade sources failed for DOI {doi}. Attempting DOI landing page fallback.", level="warn")
        try:
            landing_url = f"https://doi.org/{doi}"
            content, _err = _stream_web_content(client, landing_url, timeout=30)
            if content and len(content) > 100:
                md_path = os.path.join(sources_dir, f"{source_id}.md")
                Path(md_path).write_text(content, encoding="utf-8")
                result["content_file"] = f"sources/{source_id}.md"
                result["content_length"] = len(content)
                result["source_used"] = "doi_landing_page"
                result["quality"] = "abstract_only"
                result["quality_details"] = {
                    "content_length": len(content),
                    "alpha_ratio": 0.0,
                    "sentence_count": 0,
                    "reasons": ["fallback to DOI landing page — abstract/metadata only, not full text"],
                }
                log(f"DOI landing page fallback succeeded: {len(content)} chars extracted")
                return
        except Exception as e:
            log(f"DOI landing page fallback failed: {e}", level="warn")

        result["errors"].append(f"No PDF found via cascade for DOI {doi}")


def _resolve_openalex(doi: str, client, config: dict) -> str | None:
    """Look up open access PDF URL from OpenAlex."""
    url = f"https://api.openalex.org/works/doi:{doi}"
    headers = {}
    api_key = config.get("openalex_api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = client.get(url, headers=headers, timeout=(15, 15))
    if resp.status_code != 200:
        return None

    data = resp.json()
    oa = data.get("open_access") or {}
    oa_url = oa.get("oa_url") or ""
    if oa_url:
        log(f"OpenAlex found OA URL: {oa_url}")
        return oa_url
    return None


def _resolve_unpaywall(doi: str, client, config: dict) -> str | None:
    """Look up open access PDF URL from Unpaywall."""
    email = config.get("unpaywall_email")
    if not email:
        log("No UNPAYWALL_EMAIL configured, skipping Unpaywall", level="debug")
        return None

    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    resp = client.get(url, timeout=(15, 15))
    if resp.status_code != 200:
        return None

    data = resp.json()
    best_loc = data.get("best_oa_location") or {}
    pdf_url = best_loc.get("url_for_pdf") or best_loc.get("url") or ""
    if pdf_url:
        log(f"Unpaywall found PDF URL: {pdf_url}")
        return pdf_url
    return None


def _resolve_arxiv_for_doi(doi: str, _client) -> str | None:
    """Check if a DOI has an arXiv preprint via OpenAlex external IDs or DOI prefix."""
    # arXiv DOIs start with 10.48550/arXiv.
    if doi.lower().startswith("10.48550/arxiv."):
        # Extract properly: 10.48550/arXiv.YYMM.NNNNN
        parts = doi.split("/", 1)
        if len(parts) == 2:
            suffix = parts[1]
            if suffix.lower().startswith("arxiv."):
                arxiv_id = suffix[6:]  # strip "arXiv."
                return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # Try extracting arXiv ID from DOI string itself
    arxiv_id = extract_arxiv_id(doi)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    return None


def _resolve_pmc(doi: str, client) -> str | None:
    """Look up PMC PDF URL via NCBI ID converter."""
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json"
    try:
        resp = client.get(url, timeout=(15, 15))
        if resp.status_code != 200:
            return None
        data = resp.json()
        records = data.get("records") or []
        for record in records:
            pmcid = record.get("pmcid")
            if pmcid:
                log(f"PMC found PMCID: {pmcid}")
                return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
    except Exception:
        pass
    return None


def _resolve_osf(doi: str, client, config: dict, title: str = "") -> str | None:
    """Look up PDF URL from OSF preprints (PsyArXiv, SocArXiv, EdArXiv, etc.).

    Two paths:
    1. PsyArXiv DOI fast path — DOIs starting with 10.31234/osf.io/ contain the
       preprint ID directly, so we fetch the preprint record and follow the
       primary_file link to get the download URL.
    2. Title search fallback — for non-PsyArXiv DOIs, search OSF preprints by
       title and return the download URL if a single confident match is found.
    """
    headers = {}
    token = config.get("osf_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # --- Fast path: PsyArXiv DOI (10.31234/osf.io/{id}) ---
    psyarxiv_prefix = "10.31234/osf.io/"
    if doi.lower().startswith(psyarxiv_prefix):
        preprint_id = doi[len(psyarxiv_prefix):]
        return _osf_preprint_pdf_url(preprint_id, client, headers)

    # --- Fallback: title search across all OSF preprint providers ---
    if not title:
        return None

    search_url = "https://api.osf.io/v2/preprints/"
    params = {
        "filter[title]": title,
        "page[size]": "5",
    }
    try:
        resp = client.get(search_url, params=params, headers=headers, timeout=(15, 30))
        if resp.status_code != 200:
            return None
        data = resp.json().get("data") or []
        if len(data) == 0:
            return None

        # Pick the first result whose title is a close match
        title_lower = title.lower().strip()
        for item in data:
            attrs = item.get("attributes") or {}
            candidate_title = (attrs.get("title") or "").lower().strip()
            if candidate_title == title_lower:
                preprint_id = item.get("id")
                if preprint_id:
                    url = _osf_preprint_pdf_url(preprint_id, client, headers)
                    if url:
                        return url

    except Exception as e:
        log(f"OSF title search failed: {e}", level="warn")

    return None


def _osf_preprint_pdf_url(preprint_id: str, client, headers: dict) -> str | None:
    """Given an OSF preprint ID, resolve the primary file download URL."""
    preprint_url = f"https://api.osf.io/v2/preprints/{preprint_id}/"
    try:
        resp = client.get(preprint_url, headers=headers, timeout=(15, 15))
        if resp.status_code != 200:
            return None
        preprint_data = resp.json().get("data") or {}

        # Get primary file link
        rels = preprint_data.get("relationships") or {}
        primary_file = rels.get("primary_file") or {}
        pf_links = primary_file.get("links") or {}
        related_href = pf_links.get("related") or {}
        file_url = related_href.get("href") if isinstance(related_href, dict) else related_href
        if not file_url:
            return None

        # Fetch the file record to get the download link
        file_resp = client.get(file_url, headers=headers, timeout=(15, 15))
        if file_resp.status_code != 200:
            return None
        file_data = file_resp.json().get("data") or {}
        file_links = file_data.get("links") or {}
        download_url = file_links.get("download")
        if download_url:
            log(f"OSF found PDF download URL: {download_url}")
            return download_url
    except Exception as e:
        log(f"OSF preprint lookup failed for {preprint_id}: {e}", level="warn")
    return None


def _convert_and_record(pdf_path: str, source_id: str, sources_dir: str, result: dict,
                        title: str = "", authors: list[str] | None = None,
                        abstract: str = "") -> None:
    """Convert PDF to markdown and update result dict."""
    md_path = os.path.join(sources_dir, f"{source_id}.md")
    conv = pdf_to_markdown(pdf_path, md_path)

    if conv["success"]:
        result["md_converted"] = True
        result["content_file"] = f"sources/{source_id}.md"
        result["content_length"] = conv["content_length"]
        result["toc_file"] = f"sources/{source_id}.toc" if conv.get("toc_file") else None
        result["quality"] = conv.get("quality", "ok")
        if conv.get("quality_details"):
            result["quality_details"] = conv["quality_details"]

        # Semantic mismatch check: does extracted text match expected metadata?
        if result["quality"] == "ok" and (title or authors):
            try:
                from pathlib import Path as _Path
                md_text = _Path(md_path).read_text(encoding="utf-8")
                mismatch = check_content_mismatch(
                    md_text, title=title, authors=authors, abstract=abstract,
                    brief_keywords=result.get("_brief_keywords"),
                )
                if mismatch["mismatched"]:
                    result["quality"] = "mismatched"
                    details = result.get("quality_details") or {}
                    details["reasons"] = details.get("reasons", []) + [mismatch["reason"]]
                    details["title_hits"] = mismatch["title_hits"]
                    details["author_hits"] = mismatch["author_hits"]
                    result["quality_details"] = details
                    log(f"Content mismatch detected for {source_id}: {mismatch['reason']}", level="warn")
                # Title divergence check for accepted content
                if result["quality"] == "ok":
                    alt_title = _check_title_divergence(md_text, {"title": title})
                    if alt_title:
                        result["title_from_content"] = alt_title
                        log(f"Title divergence for {source_id}: extracted '{alt_title}'", level="info")
            except Exception as e:
                log(f"Mismatch check failed for {source_id}: {e}", level="debug")
    else:
        result["errors"].append(f"PDF conversion failed (converter: {conv['converter']})")


def _metadata_needs_enrichment(meta: dict) -> bool:
    """Check if metadata is missing key fields that Crossref could provide."""
    return (
        not meta.get("authors")
        or not meta.get("year")
        or not meta.get("venue")
        or not meta.get("abstract")
    )


def _auto_enrich_crossref(doi: str, source_id: str, client, metadata_dir: str) -> None:
    """Auto-enrich metadata from Crossref after download. Best-effort, never fails the download."""
    try:
        url = f"https://api.crossref.org/works/{doi}"
        resp = client.get(url, timeout=(15, 15))
        if resp.status_code != 200:
            log(f"Crossref auto-enrichment failed: HTTP {resp.status_code} for {doi}", level="warn")
            return

        data = resp.json()
        message = data.get("message")
        if not message:
            return

        # Normalize through the standard pipeline
        normalized = normalize_paper(message, "crossref")
        normalized["id"] = source_id

        # Read existing metadata and merge
        existing = read_source_metadata(metadata_dir, source_id)
        if not existing:
            existing = {"id": source_id}

        merged = merge_metadata(existing, normalized)
        write_source_metadata(metadata_dir, source_id, merged)
        log(f"Auto-enriched {source_id} from Crossref (doi: {doi})")
    except Exception as e:
        log(f"Auto-enrichment failed for {source_id}: {e}", level="warn")


def _build_metadata(args, source_id: str) -> dict:
    """Build metadata dict from CLI flags."""
    meta = {k: type(v)() if isinstance(v, list | dict) else v for k, v in PAPER_SCHEMA.items()}
    meta["id"] = source_id
    meta["fetched_at"] = datetime.now(timezone.utc).isoformat()

    if args.type:
        meta["type"] = args.type
    if args.title:
        meta["title"] = args.title
    if args.authors:
        meta["authors"] = args.authors
    if args.year:
        meta["year"] = args.year
    if args.venue:
        meta["venue"] = args.venue
    if args.citation_count is not None:
        meta["citation_count"] = args.citation_count

    # Set DOI/URL from input flags
    if hasattr(args, "doi") and args.doi:
        meta["doi"] = normalize_doi(args.doi)
    if hasattr(args, "url") and args.url:
        meta["url"] = args.url
    if hasattr(args, "pdf_url") and args.pdf_url:
        meta["pdf_url"] = args.pdf_url
    if hasattr(args, "arxiv") and args.arxiv:
        meta["url"] = f"https://arxiv.org/abs/{args.arxiv}"
        meta["pdf_url"] = f"https://arxiv.org/pdf/{args.arxiv}.pdf"
        meta["provider"] = "arxiv"

    return meta


def _lookup_source_id_from_state(session_dir: str, doi: str | None,
                                  url: str | None = None) -> str | None:
    """Look up existing source ID in state.db by DOI or URL."""
    if not doi and not url:
        return None
    db_path = os.path.join(session_dir, "state.db")
    if not os.path.exists(db_path):
        return None
    try:
        import sqlite3

        from _shared.doi_utils import canonicalize_url as _canon_url

        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row

            # Tier 1: DOI match
            if doi:
                row = conn.execute(
                    "SELECT id FROM sources WHERE doi = ?",
                    (normalize_doi(doi),)
                ).fetchone()
                if row:
                    return row["id"]

            # Tier 2: URL match
            if url:
                canon = _canon_url(url)
                row = conn.execute(
                    "SELECT id FROM sources WHERE url = ?",
                    (canon,)
                ).fetchone()
                if row:
                    return row["id"]

            return None
        finally:
            conn.close()
    except Exception:
        return None


_source_id_lock = threading.Lock()


_PENDING_STALENESS = 3600  # 1 hour — stale placeholders are cleaned up


def _generate_source_id(sources_dir: str) -> str:
    """Generate the next sequential source ID (src-001, src-002, etc.).

    Thread-safe: uses a lock so parallel batch workers cannot collide.
    Cleans up stale .pending placeholders from previous failed runs.
    """
    with _source_id_lock:
        existing = set()
        max_n = 0
        metadata_dir = os.path.join(sources_dir, "metadata")
        if os.path.isdir(metadata_dir):
            for name in os.listdir(metadata_dir):
                if name.startswith("src-") and name.endswith(".json"):
                    sid = name[:-5]  # strip .json
                    existing.add(sid)
                    with contextlib.suppress(IndexError, ValueError):
                        max_n = max(max_n, int(sid.split("-")[1]))

        # Also check source files directly
        if os.path.isdir(sources_dir):
            now = time.time()
            for name in os.listdir(sources_dir):
                if name.startswith("src-") and "." in name:
                    base = name.rsplit(".", 1)[0]
                    ext = name.rsplit(".", 1)[1]

                    # Clean up stale .pending placeholders
                    if ext == "pending":
                        path = os.path.join(sources_dir, name)
                        try:
                            if now - os.path.getmtime(path) > _PENDING_STALENESS:
                                os.unlink(path)
                                continue
                        except OSError:
                            pass

                    existing.add(base)
                    with contextlib.suppress(IndexError, ValueError):
                        max_n = max(max_n, int(base.split("-")[1]))

        # Start search from max_n+1 instead of 1 to avoid linear scan
        n = max_n + 1
        while f"src-{n:03d}" in existing:
            n += 1

        # Create a placeholder file to reserve this ID before releasing the lock
        placeholder = os.path.join(sources_dir, f"src-{n:03d}.pending")
        Path(placeholder).touch()

        return f"src-{n:03d}"


def _handle_local_dir(args, _session_dir: str, sources_dir: str, metadata_dir: str) -> list:
    """Ingest papers from a local directory."""
    local_dir = args.local_dir
    if not os.path.isdir(local_dir):
        error_response([f"Directory not found: {local_dir}"], error_code="dir_not_found")
        return []  # unreachable

    log(f"Scanning directory: {local_dir}")
    results = []
    extensions = {".pdf", ".md", ".html", ".htm"}

    # Find all matching files recursively
    files = []
    for root, _, filenames in os.walk(local_dir):
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in extensions:
                files.append(os.path.join(root, fname))

    log(f"Found {len(files)} files to ingest")

    for filepath in files:
        source_id = _generate_source_id(sources_dir)
        ext = os.path.splitext(filepath)[1].lower()
        entry: dict = {
            "source_id": source_id,
            "original_file": filepath,
            "content_file": None,
            "pdf_file": None,
            "md_converted": False,
            "errors": [],
        }

        try:
            if ext == ".pdf":
                # Copy PDF to sources/
                dest_pdf = os.path.join(sources_dir, f"{source_id}.pdf")
                shutil.copy2(filepath, dest_pdf)
                entry["pdf_file"] = f"sources/{source_id}.pdf"

                if args.to_md:
                    md_path = os.path.join(sources_dir, f"{source_id}.md")
                    conv = pdf_to_markdown(dest_pdf, md_path)
                    if conv["success"]:
                        entry["md_converted"] = True
                        entry["content_file"] = f"sources/{source_id}.md"

                # Extract title from filename as fallback
                title = os.path.splitext(os.path.basename(filepath))[0]
                meta = {
                    "id": source_id,
                    "title": title,
                    "type": "academic",
                    "has_pdf": True,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "quality": conv.get("quality", "ok") if args.to_md else "ok",
                }
                write_source_metadata(metadata_dir, source_id, meta)

            elif ext in (".md",):
                dest_md = os.path.join(sources_dir, f"{source_id}.md")
                shutil.copy2(filepath, dest_md)
                entry["content_file"] = f"sources/{source_id}.md"
                entry["quality"] = "ok"

                title = os.path.splitext(os.path.basename(filepath))[0]
                meta = {
                    "id": source_id,
                    "title": title,
                    "type": "academic",
                    "has_pdf": False,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "quality": "ok",
                }
                write_source_metadata(metadata_dir, source_id, meta)

            elif ext in (".html", ".htm"):
                html = Path(filepath).read_text(encoding="utf-8", errors="replace")
                content = extract_readable_content(html)
                dest_md = os.path.join(sources_dir, f"{source_id}.md")
                Path(dest_md).write_text(content, encoding="utf-8")
                entry["content_file"] = f"sources/{source_id}.md"
                entry["quality"] = "ok"

                title = os.path.splitext(os.path.basename(filepath))[0]
                meta = {
                    "id": source_id,
                    "title": title,
                    "type": "web",
                    "has_pdf": False,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "quality": "ok",
                }
                write_source_metadata(metadata_dir, source_id, meta)

        except Exception as e:
            entry["errors"].append(str(e))
            log(f"Failed to ingest {filepath}: {e}", level="error")

        results.append(entry)

    log(f"Ingested {len(results)} files")
    return results


def _make_batch_args(item: dict, to_md: bool) -> argparse.Namespace:
    """Build an args-like namespace from a batch JSON item."""
    return argparse.Namespace(
        url=item.get("url"),
        pdf_url=item.get("pdf_url"),
        doi=item.get("doi"),
        arxiv=item.get("arxiv"),
        source_id=item.get("source_id"),
        to_md=to_md,
        type=item.get("type", "academic"),
        title=item.get("title"),
        authors=item.get("authors"),
        year=item.get("year"),
        venue=item.get("venue"),
        citation_count=item.get("citation_count"),
        local_dir=None,
        from_json=None,
    )


def _handle_batch(args, session_dir: str, sources_dir: str, metadata_dir: str,
                  config: dict, brief_keywords: list[str] | None = None) -> list:
    """Handle batch downloads from a JSON file.

    Supports --parallel N for concurrent downloads (default 1 = serial).
    """
    json_path = args.from_json
    try:
        with open(json_path, encoding="utf-8") as f:
            items = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        error_response([f"Failed to read JSON file: {e}"], error_code="invalid_json")
        return []  # unreachable

    if not isinstance(items, list):
        error_response(["JSON file must contain an array of download items"], error_code="invalid_json")
        return []

    parallel = getattr(args, "parallel", 1) or 1

    if parallel > 1 and len(items) > 1:
        return _handle_batch_parallel(items, args, session_dir, sources_dir, metadata_dir, config, parallel,
                                      brief_keywords=brief_keywords)

    # Serial path
    results = []
    client = create_session(session_dir)
    try:
        for i, item in enumerate(items):
            log(f"Batch download {i + 1}/{len(items)}")
            batch_args = _make_batch_args(item, args.to_md)
            result = _handle_single(batch_args, client, session_dir, sources_dir, metadata_dir, config,
                                    brief_keywords=brief_keywords)
            results.append(result)
    finally:
        client.close()

    return results


_BATCH_ITEM_TIMEOUT = 300  # 5 minutes max per item in parallel batch


def _handle_batch_parallel(items: list, args, session_dir: str, sources_dir: str,
                           metadata_dir: str, config: dict, max_workers: int,
                           brief_keywords: list[str] | None = None) -> list:
    """Download batch items in parallel using ThreadPoolExecutor."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

    results: list[dict | None] = [None] * len(items)
    batch_total_timeout = max(600, len(items) * 60)

    def _download_one(index: int, item: dict, cancel: threading.Event) -> tuple[int, dict]:
        client = create_session(session_dir)
        try:
            if cancel.is_set():
                return index, _timeout_result(item, "Cancelled (batch timeout)")
            item_start = time.monotonic()
            log(f"Batch download {index + 1}/{len(items)} (parallel)")
            batch_args = _make_batch_args(item, args.to_md)
            result = _handle_single(batch_args, client, session_dir, sources_dir, metadata_dir, config,
                                   cancel=cancel, brief_keywords=brief_keywords)
            elapsed = time.monotonic() - item_start
            if elapsed > _BATCH_ITEM_TIMEOUT:
                log(f"Batch item {index + 1} took {elapsed:.0f}s (>{_BATCH_ITEM_TIMEOUT}s limit)", level="warn")
            return index, result
        except Exception as e:
            return index, {
                "source_id": item.get("source_id"),
                "doi": item.get("doi"),
                "errors": [f"Parallel download failed: {e}"],
                "pdf_downloaded": False,
                "content_file": None,
                "pdf_file": None,
            }
        finally:
            client.close()

    cancel_events: dict[int, threading.Event] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for i, item in enumerate(items):
            ev = threading.Event()
            cancel_events[i] = ev
            futures[executor.submit(_download_one, i, item, ev)] = i

        try:
            for future in as_completed(futures, timeout=batch_total_timeout):
                idx = futures[future]
                try:
                    # Wait up to per-item timeout for the result; the thread
                    # runs autonomously so this just caps how long we block.
                    idx, result = future.result(timeout=_BATCH_ITEM_TIMEOUT)
                except TimeoutError:
                    cancel_events[idx].set()
                    result = _timeout_result(items[idx], f"Download timed out after {_BATCH_ITEM_TIMEOUT}s")
                    log(f"Batch item {idx + 1} timed out after {_BATCH_ITEM_TIMEOUT}s", level="warn")
                results[idx] = result
        except TimeoutError:
            # Batch-level timeout from as_completed
            log(f"Batch total timeout ({batch_total_timeout}s) exceeded", level="warn")

    # Check for items that never completed due to batch timeout
    for i, r in enumerate(results):
        if r is None:
            cancel_events[i].set()
            results[i] = _timeout_result(items[i], f"Batch total timeout ({batch_total_timeout}s) exceeded")
            log(f"Batch item {i + 1} did not complete within batch timeout", level="warn")

    return [r for r in results if r is not None]


def _timeout_result(item: dict, reason: str) -> dict:
    """Build a standard error result for timed-out or cancelled items."""
    return {
        "source_id": item.get("source_id"),
        "doi": item.get("doi"),
        "errors": [reason],
        "pdf_downloaded": False,
        "content_file": None,
        "pdf_file": None,
    }


if __name__ == "__main__":
    main()
