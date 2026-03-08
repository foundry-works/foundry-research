#!/usr/bin/env python3
"""Content & PDF downloader — web extraction, PDF cascade, local ingestion."""

import argparse
import json
import os
import shutil
import sys
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
    write_source_metadata,
)
from _shared.mirrors import download_annas_archive, download_scihub  # noqa: E402
from _shared.output import error_response, log, set_quiet, success_response  # noqa: E402
from _shared.pdf_utils import download_pdf, pdf_to_markdown, validate_pdf  # noqa: E402

# arXiv download constraints
_ARXIV_DELAY = 3.0  # seconds between arXiv downloads (ToS)
_CAPTCHA_SIZE_THRESHOLD = 100 * 1024  # 100KB
_CAPTCHA_MARKERS = (b"<html", b"captcha", b"<!doctype")

# PDF cascade source names
CASCADE_SOURCES = ["openalex", "unpaywall", "arxiv", "pmc", "annas_archive", "scihub"]


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

    # Metadata flags
    parser.add_argument("--type", default="academic", choices=["academic", "web", "reddit", "code"],
                        help="Source type")
    parser.add_argument("--title", default=None, help="Source title")
    parser.add_argument("--authors", nargs="+", default=None, help="Author names")
    parser.add_argument("--year", type=int, default=None, help="Publication year")
    parser.add_argument("--venue", default=None, help="Publication venue")
    parser.add_argument("--citation-count", type=int, default=None, help="Citation count")
    parser.add_argument("--quiet", action="store_true", help="Suppress stderr log output")

    return parser


def _sync_to_state(session_dir: str, result: dict) -> None:
    """Sync content_file and pdf_file paths to state.db after download."""
    source_id = result.get("source_id")
    if not source_id:
        return

    update = {}
    if result.get("content_file"):
        update["content_file"] = result["content_file"]
    if result.get("pdf_file"):
        update["pdf_file"] = result["pdf_file"]
    if result.get("pdf_downloaded") or result.get("content_file"):
        update["status"] = "downloaded"
    if result.get("quality"):
        update["quality"] = result["quality"]

    if not update:
        return

    try:
        import subprocess
        import tempfile

        # Write update as a temp JSON file (state.py requires file-only --from-json)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=session_dir, delete=False) as tf:
            json.dump(update, tf)
            tmp_path = tf.name

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        state_script = os.path.join(scripts_dir, "state.py")
        cmd = [
            sys.executable, state_script, "update-source",
            "--id", source_id,
            "--from-json", tmp_path,
            "--session-dir", session_dir,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        log(f"Failed to sync download to state: {e}", level="warn")


def _auto_create_web_source(session_dir: str, source_id: str, url: str, meta: dict) -> None:
    """Auto-create a new source entry in state.db for a web download not already tracked."""
    try:
        import subprocess
        import tempfile

        source_data = {
            "title": meta.get("title") or url,
            "url": url,
            "type": "web",
            "provider": "web",
        }
        # Include optional metadata if available
        if meta.get("authors"):
            source_data["authors"] = meta["authors"]
        if meta.get("year"):
            source_data["year"] = meta["year"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=session_dir, delete=False) as tf:
            json.dump([source_data], tf)
            tmp_path = tf.name

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        state_script = os.path.join(scripts_dir, "state.py")
        cmd = [
            sys.executable, state_script, "add-sources",
            "--from-json", tmp_path,
            "--session-dir", session_dir,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                log(f"Auto-created web source in state.db for {url} → {source_id}")
            else:
                log(f"Failed to auto-create web source: {proc.stderr}", level="warn")
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        log(f"Failed to auto-create web source: {e}", level="warn")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.quiet:
        set_quiet(True)

    # Require at least one input mode
    if not any([args.url, args.pdf_url, args.doi, args.arxiv, args.local_dir, args.from_json]):
        error_response(
            ["No input specified. Use --url, --pdf-url, --doi, --arxiv, --local-dir, or --from-json"],
            error_code="missing_input",
        )

    # Resolve session directory
    session_dir = get_session_dir(args)
    config = get_config(session_dir)

    # Sources directory
    sources_dir = os.path.join(session_dir, "sources")
    metadata_dir = os.path.join(sources_dir, "metadata")
    os.makedirs(metadata_dir, exist_ok=True)

    # Dispatch to handler
    if args.local_dir:
        result = _handle_local_dir(args, session_dir, sources_dir, metadata_dir)
    elif args.from_json:
        result = _handle_batch(args, session_dir, sources_dir, metadata_dir, config)
    else:
        client = create_session(session_dir)
        try:
            result = _handle_single(args, client, session_dir, sources_dir, metadata_dir, config)
        finally:
            client.close()

    # Sync downloaded file paths to state.db (if session has state tracking)
    if os.path.exists(os.path.join(session_dir, "state.db")):
        if isinstance(result, list):
            for r in result:
                _sync_to_state(session_dir, r)
        else:
            _sync_to_state(session_dir, result)

    # Output result
    if isinstance(result, list):
        success_response(result, total_results=len(result))
    else:
        success_response(result)


def _handle_single(args, client, _session_dir: str, sources_dir: str,
                   metadata_dir: str, config: dict) -> dict:
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
                         args.to_md, config, result)

    # Write metadata
    if result.get("pdf_downloaded"):
        meta["has_pdf"] = True
    if result.get("pdf_file"):
        meta["pdf_url"] = meta.get("pdf_url") or ""
    if result.get("content_file"):
        meta["content_file"] = result["content_file"]
    write_source_metadata(metadata_dir, source_id, meta)

    # Prominently log the assigned source ID
    log(f">>> Assigned source ID: {source_id}")

    return result


def _download_web(url: str, source_id: str, client, sources_dir: str,
                  meta: dict, result: dict) -> None:
    """Download web page and extract readable content."""
    log(f"Downloading web content: {url}")
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            result["errors"].append(f"HTTP {resp.status_code} for {url}")
            return

        html = resp.text
        content = extract_readable_content(html)
        if not content:
            result["errors"].append("No readable content extracted")
            return

        # Save as markdown
        md_path = os.path.join(sources_dir, f"{source_id}.md")
        Path(md_path).write_text(content, encoding="utf-8")

        result["content_file"] = f"sources/{source_id}.md"
        result["content_length"] = len(content)
        result["source_used"] = "web"

        meta["url"] = url
        meta["type"] = "web"
        log(f"Saved web content: {md_path} ({len(content)} chars)")

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
        _convert_and_record(pdf_path, source_id, sources_dir, result)


def _download_arxiv(arxiv_id: str, source_id: str, client, sources_dir: str,
                    to_md: bool, result: dict) -> None:
    """Download PDF from arXiv with CAPTCHA detection."""
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")

    log(f"Downloading arXiv PDF: {arxiv_id}")
    time.sleep(_ARXIV_DELAY)

    for attempt in range(3):
        try:
            resp = client.get(pdf_url, timeout=(15, 60))
            if resp.status_code in (502, 503, 504):
                wait = 2 ** attempt
                log(f"arXiv returned {resp.status_code}, retrying in {wait}s", level="warn")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                result["errors"].append(f"arXiv HTTP {resp.status_code}")
                result["source_used"] = "arxiv"
                result["sources_tried"].append("arxiv")
                return

            content = resp.content

            # CAPTCHA detection
            if len(content) < _CAPTCHA_SIZE_THRESHOLD:
                head = content[:1024].lower()
                if any(marker in head for marker in _CAPTCHA_MARKERS):
                    log(f"CAPTCHA detected for arXiv {arxiv_id}", level="warn")
                    result["errors"].append("arXiv CAPTCHA detected")
                    result["source_used"] = "arxiv"
                    result["sources_tried"].append("arxiv")
                    return

            Path(pdf_path).write_bytes(content)

            if not validate_pdf(pdf_path):
                os.unlink(pdf_path)
                result["errors"].append("arXiv returned invalid PDF")
                result["sources_tried"].append("arxiv")
                return

            result["pdf_file"] = f"sources/{source_id}.pdf"
            result["pdf_size_bytes"] = len(content)
            result["pdf_downloaded"] = True
            result["source_used"] = "arxiv"
            result["sources_tried"].append("arxiv")

            if to_md:
                _convert_and_record(pdf_path, source_id, sources_dir, result)
            return

        except Exception as e:
            if attempt == 2:
                result["errors"].append(f"arXiv download failed: {e}")
                result["sources_tried"].append("arxiv")

    result["source_used"] = "arxiv"


def _download_by_doi(doi: str, source_id: str, client, sources_dir: str,
                     _metadata_dir: str, to_md: bool, config: dict, result: dict) -> None:
    """Run PDF cascade for a DOI: OpenAlex → Unpaywall → arXiv → PMC → Anna's → Sci-Hub."""
    log(f"Running PDF cascade for DOI: {doi}")

    # Try each source in order
    for source_name in CASCADE_SOURCES:
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
            elif source_name == "annas_archive":
                pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
                if download_annas_archive(doi, pdf_path, config, client):
                    result["pdf_file"] = f"sources/{source_id}.pdf"
                    result["pdf_size_bytes"] = os.path.getsize(pdf_path)
                    result["pdf_downloaded"] = True
                    result["source_used"] = "annas_archive"
                    if to_md:
                        _convert_and_record(pdf_path, source_id, sources_dir, result)
                    return
                continue
            elif source_name == "scihub":
                pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
                if download_scihub(doi, pdf_path, client):
                    result["pdf_file"] = f"sources/{source_id}.pdf"
                    result["pdf_size_bytes"] = os.path.getsize(pdf_path)
                    result["pdf_downloaded"] = True
                    result["source_used"] = "scihub"
                    if to_md:
                        _convert_and_record(pdf_path, source_id, sources_dir, result)
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
            result["pdf_file"] = f"sources/{source_id}.pdf"
            result["pdf_size_bytes"] = dl_result["size_bytes"]
            result["pdf_downloaded"] = True
            result["source_used"] = source_name

            if to_md:
                _convert_and_record(pdf_path, source_id, sources_dir, result)
            return
        log(f"{source_name} PDF download failed: {dl_result['errors']}", level="warn")

    # All sources exhausted — try DOI landing page as abstract fallback
    if not result["pdf_downloaded"]:
        log(f"All PDF cascade sources failed for DOI {doi}. Attempting DOI landing page fallback.", level="warn")
        try:
            landing_url = f"https://doi.org/{doi}"
            resp = client.get(landing_url, timeout=(15, 30))
            if resp.status_code == 200 and resp.text:
                content = extract_readable_content(resp.text)
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
        arxiv_id = doi.split(".", 2)[-1] if doi.count(".") >= 3 else None
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


def _convert_and_record(pdf_path: str, source_id: str, sources_dir: str, result: dict) -> None:
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
    else:
        result["errors"].append(f"PDF conversion failed (converter: {conv['converter']})")


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
        conn.row_factory = sqlite3.Row

        # Tier 1: DOI match
        if doi:
            row = conn.execute(
                "SELECT id FROM sources WHERE doi = ?",
                (normalize_doi(doi),)
            ).fetchone()
            if row:
                conn.close()
                return row["id"]

        # Tier 2: URL match
        if url:
            canon = _canon_url(url)
            row = conn.execute(
                "SELECT id FROM sources WHERE url = ?",
                (canon,)
            ).fetchone()
            if row:
                conn.close()
                return row["id"]

        conn.close()
        return None
    except Exception:
        return None


def _generate_source_id(sources_dir: str) -> str:
    """Generate the next sequential source ID (src-001, src-002, etc.)."""
    existing = set()
    metadata_dir = os.path.join(sources_dir, "metadata")
    if os.path.isdir(metadata_dir):
        for name in os.listdir(metadata_dir):
            if name.startswith("src-") and name.endswith(".json"):
                existing.add(name[:-5])  # strip .json

    # Also check source files directly
    if os.path.isdir(sources_dir):
        for name in os.listdir(sources_dir):
            if name.startswith("src-") and "." in name:
                existing.add(name.rsplit(".", 1)[0])

    n = 1
    while f"src-{n:03d}" in existing:
        n += 1
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

                title = os.path.splitext(os.path.basename(filepath))[0]
                meta = {
                    "id": source_id,
                    "title": title,
                    "type": "academic",
                    "has_pdf": False,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                write_source_metadata(metadata_dir, source_id, meta)

            elif ext in (".html", ".htm"):
                html = Path(filepath).read_text(encoding="utf-8", errors="replace")
                content = extract_readable_content(html)
                dest_md = os.path.join(sources_dir, f"{source_id}.md")
                Path(dest_md).write_text(content, encoding="utf-8")
                entry["content_file"] = f"sources/{source_id}.md"

                title = os.path.splitext(os.path.basename(filepath))[0]
                meta = {
                    "id": source_id,
                    "title": title,
                    "type": "web",
                    "has_pdf": False,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
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
                  config: dict) -> list:
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
        return _handle_batch_parallel(items, args, session_dir, sources_dir, metadata_dir, config, parallel)

    # Serial path
    results = []
    client = create_session(session_dir)
    try:
        for i, item in enumerate(items):
            log(f"Batch download {i + 1}/{len(items)}")
            batch_args = _make_batch_args(item, args.to_md)
            result = _handle_single(batch_args, client, session_dir, sources_dir, metadata_dir, config)
            results.append(result)
    finally:
        client.close()

    return results


def _handle_batch_parallel(items: list, args, session_dir: str, sources_dir: str,
                           metadata_dir: str, config: dict, max_workers: int) -> list:
    """Download batch items in parallel using ThreadPoolExecutor."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[dict | None] = [None] * len(items)

    def _download_one(index: int, item: dict) -> tuple[int, dict]:
        client = create_session(session_dir)
        try:
            log(f"Batch download {index + 1}/{len(items)} (parallel)")
            batch_args = _make_batch_args(item, args.to_md)
            result = _handle_single(batch_args, client, session_dir, sources_dir, metadata_dir, config)
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

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_download_one, i, item): i for i, item in enumerate(items)}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    return [r for r in results if r is not None]


if __name__ == "__main__":
    main()
