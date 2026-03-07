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
from _shared.output import error_response, log, success_response  # noqa: E402
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

    if not update:
        return

    try:
        import subprocess

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        state_script = os.path.join(scripts_dir, "state.py")
        cmd = [
            sys.executable, state_script, "update-source",
            "--id", source_id,
            "--from-json", json.dumps(update),
            "--session-dir", session_dir,
        ]
        subprocess.run(cmd, capture_output=True, timeout=5)
    except Exception as e:
        log(f"Failed to sync download to state: {e}", level="warn")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

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
    source_id = args.source_id or _generate_source_id(sources_dir)
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
                if _download_annas_archive(doi, pdf_path, config):
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
                if _download_scihub(doi, pdf_path):
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

    # All sources exhausted
    if not result["pdf_downloaded"]:
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


def _handle_batch(args, session_dir: str, sources_dir: str, metadata_dir: str,
                  config: dict) -> list:
    """Handle batch downloads from a JSON file."""
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

    results = []
    client = create_session(session_dir)

    try:
        for item in items:
            # Build args-like namespace from JSON item
            batch_args = argparse.Namespace(
                url=item.get("url"),
                pdf_url=item.get("pdf_url"),
                doi=item.get("doi"),
                arxiv=item.get("arxiv"),
                source_id=item.get("source_id"),
                to_md=args.to_md,
                type=item.get("type", "academic"),
                title=item.get("title"),
                authors=item.get("authors"),
                year=item.get("year"),
                venue=item.get("venue"),
                citation_count=item.get("citation_count"),
                local_dir=None,
                from_json=None,
            )
            result = _handle_single(batch_args, client, session_dir, sources_dir, metadata_dir, config)
            results.append(result)
    finally:
        client.close()

    return results


# ---------------------------------------------------------------------------
# Anna's Archive integration
# ---------------------------------------------------------------------------

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ANNAS_FALLBACK_MIRRORS = [
    "annas-archive.li",
    "annas-archive.gd",
    "annas-archive.gl",
    "annas-archive.pk",
    "annas-archive.vg",
]

_SCIHUB_FALLBACK_MIRRORS = [
    "sci-hub.se",
    "sci-hub.st",
    "sci-hub.ru",
    "sci-hub.su",
    "sci-hub.box",
    "sci-hub.red",
    "sci-hub.mksa.top",
]

# Wikipedia pages for mirror discovery
_MIRROR_SOURCES = {
    "annas": "https://en.wikipedia.org/wiki/Anna%27s_Archive",
    "scihub": "https://en.wikipedia.org/wiki/Sci-Hub",
}

_MIRROR_PATTERNS = {
    "annas": r"annas-archive\.([a-z]{2,6})",
    "scihub": r"sci-hub\.([a-z]{2,6})",
}

# Session-level mirror cache
_mirror_cache: dict[str, tuple[str | None, float]] = {}
_MIRROR_CACHE_TTL = 3600  # 1 hour


def _discover_mirrors(service: str) -> list[str]:
    """Fetch Wikipedia article and extract mirror domains."""
    import re as _re

    url = _MIRROR_SOURCES[service]
    pattern = _MIRROR_PATTERNS[service]
    fallbacks = _ANNAS_FALLBACK_MIRRORS if service == "annas" else _SCIHUB_FALLBACK_MIRRORS

    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=15)
        resp.raise_for_status()
        tlds = set(_re.findall(pattern, resp.text))
        base = "annas-archive" if service == "annas" else "sci-hub"
        discovered = [f"{base}.{tld}" for tld in tlds]
        if discovered:
            log(f"Discovered {len(discovered)} {service} mirrors from Wikipedia")
            return discovered
    except Exception as e:
        log(f"Wikipedia mirror discovery failed for {service}: {e}", level="warn")

    return list(fallbacks)


def _find_working_mirror(service: str) -> str | None:
    """Find a working mirror, using cache when available."""
    # Check cache
    if service in _mirror_cache:
        cached_mirror, cached_at = _mirror_cache[service]
        if time.time() - cached_at < _MIRROR_CACHE_TTL:
            return cached_mirror

    mirrors = _discover_mirrors(service)
    for mirror in mirrors:
        try:
            import requests
            resp = requests.head(
                f"https://{mirror}",
                headers={"User-Agent": _BROWSER_UA},
                timeout=10,
                allow_redirects=True,
            )
            if resp.status_code < 500:
                log(f"Found working {service} mirror: {mirror}")
                _mirror_cache[service] = (mirror, time.time())
                return mirror
        except Exception:
            continue

    log(f"No working {service} mirror found", level="warn")
    _mirror_cache[service] = (None, time.time())
    return None


def _download_annas_archive(doi: str, dest_path: str, config: dict) -> bool:
    """Try downloading a paper via Anna's Archive.

    Strategy:
    1. Look up DOI via /scidb/{doi} to get MD5 hash
    2. If ANNAS_SECRET_KEY is set, use fast_download API
    3. Otherwise, scrape the download page
    """
    mirror = _find_working_mirror("annas")
    if not mirror:
        return False

    secret_key = config.get("annas_secret_key")
    md5_hash = _annas_search_doi(doi, mirror)
    if not md5_hash:
        return False

    # Try API download first if key is available
    if secret_key:
        if _annas_download_api(md5_hash, secret_key, mirror, dest_path):
            return True
        log("Anna's Archive API download failed, trying scrape fallback", level="warn")

    # Scrape fallback
    return _annas_download_scrape(md5_hash, mirror, dest_path)


def _annas_search_doi(doi: str, mirror: str) -> str | None:
    """Look up a DOI on Anna's Archive and extract an MD5 hash."""
    import re as _re

    url = f"https://{mirror}/scidb/{doi}"
    try:
        import requests
        resp = requests.get(
            url,
            headers={"User-Agent": _BROWSER_UA},
            timeout=15,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            log(f"Anna's Archive returned {resp.status_code} for DOI {doi}", level="debug")
            return None

        # Extract MD5 hashes from /md5/ links
        md5_matches = _re.findall(r'/md5/([a-f0-9]{32})', resp.text, _re.IGNORECASE)
        if md5_matches:
            log(f"Anna's Archive found MD5: {md5_matches[0]} for DOI {doi}")
            return md5_matches[0]

        log(f"No MD5 hash found on Anna's Archive for DOI {doi}", level="debug")
        return None
    except Exception as e:
        log(f"Anna's Archive DOI lookup failed: {e}", level="warn")
        return None


def _annas_download_api(md5: str, secret_key: str, mirror: str, dest: str) -> bool:
    """Download via Anna's Archive JSON API (requires API key)."""
    url = f"https://{mirror}/dyn/api/fast_download.json?md5={md5}&key={secret_key}"
    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=15)
        if resp.status_code != 200:
            return False

        data = resp.json()
        download_url = data.get("download_url")
        if not download_url:
            return False

        # Download the actual file
        pdf_resp = requests.get(
            download_url,
            headers={"User-Agent": _BROWSER_UA},
            timeout=60,
            stream=True,
        )
        if pdf_resp.status_code != 200:
            return False

        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in pdf_resp.iter_content(chunk_size=64 * 1024):
                f.write(chunk)

        if validate_pdf(dest):
            log(f"Anna's Archive API download successful: {dest}")
            return True

        os.unlink(dest)
        return False
    except Exception as e:
        log(f"Anna's Archive API download failed: {e}", level="warn")
        if os.path.exists(dest):
            os.unlink(dest)
        return False


def _annas_download_scrape(md5: str, mirror: str, dest: str) -> bool:
    """Download via Anna's Archive web scraping (no auth needed)."""
    import re as _re

    url = f"https://{mirror}/md5/{md5}"
    try:
        import requests
        resp = requests.get(
            url,
            headers={"User-Agent": _BROWSER_UA},
            timeout=15,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return False

        # Look for download links in the page
        # Common patterns: direct download links, LibGen mirrors, etc.
        download_urls = _re.findall(
            r'href="(https?://[^"]+)"[^>]*>.*?(?:download|GET|PDF)',
            resp.text, _re.IGNORECASE | _re.DOTALL,
        )

        for dl_url in download_urls[:3]:  # Try first 3 matches
            try:
                pdf_resp = requests.get(
                    dl_url,
                    headers={"User-Agent": _BROWSER_UA},
                    timeout=60,
                    stream=True,
                )
                if pdf_resp.status_code != 200:
                    continue

                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in pdf_resp.iter_content(chunk_size=64 * 1024):
                        f.write(chunk)

                if validate_pdf(dest):
                    log(f"Anna's Archive scrape download successful: {dest}")
                    return True
                os.unlink(dest)
            except Exception:
                if os.path.exists(dest):
                    os.unlink(dest)
                continue

        return False
    except Exception as e:
        log(f"Anna's Archive scrape failed: {e}", level="warn")
        if os.path.exists(dest):
            os.unlink(dest)
        return False


# ---------------------------------------------------------------------------
# Sci-Hub integration
# ---------------------------------------------------------------------------

def _download_scihub(doi: str, dest_path: str) -> bool:
    """Try downloading a paper via Sci-Hub (pre-2021 papers only).

    Uses a dedicated HttpClient with 0.2 RPS rate limit for Sci-Hub mirrors.
    """
    import re as _re

    mirror = _find_working_mirror("scihub")
    if not mirror:
        return False

    # Create a rate-limited client for Sci-Hub (0.2 RPS as per config)
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="scihub_")
    scihub_client = create_session(
        tmp_dir,
        user_agent=_BROWSER_UA,
        rate_limits={mirror: 0.2},
    )

    url = f"https://{mirror}/{doi}"
    try:
        resp = scihub_client.get(url, timeout=(15, 30))
        if resp.status_code != 200:
            log(f"Sci-Hub returned {resp.status_code}", level="debug")
            return False

        # Extract PDF URL from iframe or embed
        pdf_url = None

        iframe_match = _re.search(
            r'<iframe[^>]+(?:id=["\']pdf["\']|src=["\']([^"\']+\.pdf[^"\']*)["\'])[^>]*>',
            resp.text, _re.IGNORECASE,
        )
        if iframe_match:
            pdf_url = iframe_match.group(1)

        if not pdf_url:
            embed_match = _re.search(
                r'<embed[^>]+src=["\']([^"\']+\.pdf[^"\']*)["\']',
                resp.text, _re.IGNORECASE,
            )
            if embed_match:
                pdf_url = embed_match.group(1)

        if not pdf_url:
            onclick_match = _re.search(
                r'location\.href\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']',
                resp.text, _re.IGNORECASE,
            )
            if onclick_match:
                pdf_url = onclick_match.group(1)

        if not pdf_url:
            log("Sci-Hub: could not find PDF URL in response", level="debug")
            return False

        # Normalize the PDF URL
        if pdf_url.startswith("//"):
            pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"):
            pdf_url = f"https://{mirror}{pdf_url}"

        # Download the PDF (rate limiter enforces 0.2 RPS)
        dl_result = download_pdf(pdf_url, dest_path, scihub_client)
        if dl_result["success"]:
            log(f"Sci-Hub download successful: {dest_path}")
            return True
        return False

    except Exception as e:
        log(f"Sci-Hub download failed: {e}", level="warn")
        if os.path.exists(dest_path):
            os.unlink(dest_path)
        return False
    finally:
        scihub_client.close()


if __name__ == "__main__":
    main()
