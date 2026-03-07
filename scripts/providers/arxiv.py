"""arXiv search provider — keyword search with category filtering and date ranges."""

import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

API_URL = "https://export.arxiv.org/api/query"

# XML namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

SORT_CHOICES = ("relevance", "lastUpdatedDate", "submittedDate")


def add_arguments(parser):
    parser.add_argument("--categories", nargs="+", default=None, help="Category filters, e.g. cs.AI cs.LG cs.CL")
    parser.add_argument("--category-expr", default=None, help='Category expression, e.g. "(cs.AI AND cs.RO) OR cs.LG"')
    parser.add_argument("--sort", default="relevance", choices=SORT_CHOICES, help="Sort order (default: relevance)")
    parser.add_argument("--days", type=int, default=None, help="Filter to last N days (client-side)")
    parser.add_argument("--download", default=None, help='Download PDFs for result indices, e.g. "1,3-5"')
    parser.add_argument("--to-md", action="store_true", default=False, help="Convert downloaded PDFs to markdown via pymupdf4llm")


def search(args) -> dict:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="arxiv_")
    client = create_session(session_dir, rate_limits={"export.arxiv.org": 1.0})

    try:
        query = _build_query(args)
        if not query:
            return error_response(["--query is required for arXiv search"], error_code="missing_query")

        sort_by = args.sort
        limit = args.limit
        offset = args.offset

        # When filtering by days, fetch more results to compensate for client-side filtering
        fetch_limit = limit
        if args.days:
            fetch_limit = min(limit * 3, 1000)
            sort_by = "submittedDate"

        url = (
            f"{API_URL}"
            f"?search_query={quote(query, safe='():')}"
            f"&start={offset}"
            f"&max_results={fetch_limit}"
            f"&sortBy={sort_by}"
            f"&sortOrder=descending"
        )

        log(f"arXiv query: {query}")
        response = client.get(url)

        if response.status_code != 200:
            return error_response(
                [f"arXiv API returned status {response.status_code}"],
                error_code="api_error",
            )

        results, total = _parse_response(response.text)

        # Client-side date filtering
        if args.days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
            results = [r for r in results if _parse_iso_date(r.get("published", "")) >= cutoff]
            results = results[:limit]

        # Download PDFs if requested
        if args.download and results:
            download_indices = _parse_indices(args.download)
            downloaded = _download_pdfs(client, results, download_indices, session_dir, args.to_md)
            for idx, info in downloaded.items():
                if 0 <= idx < len(results):
                    results[idx]["downloaded_pdf"] = info.get("path")
                    results[idx]["pdf_md"] = info.get("md_path")
                    results[idx]["download_error"] = info.get("error")

        return success_response(results, total_results=total, has_more=(offset + limit < total))

    except Exception as e:
        log(f"arXiv API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _build_query(args) -> str:
    """Construct the arXiv search_query string from args."""
    base_query = args.query
    if not base_query:
        return ""

    text_part = f"all:{base_query}"

    # --category-expr takes precedence over --categories
    if args.category_expr:
        cat_expr = _convert_category_expr(args.category_expr)
        return f"({cat_expr}) AND {text_part}"

    if args.categories:
        cat_parts = " OR ".join(f"cat:{c}" for c in args.categories)
        return f"({cat_parts}) AND {text_part}"

    return text_part


def _convert_category_expr(expr: str) -> str:
    """Convert category names in an expression to cat:name format.

    E.g. '(cs.AI AND cs.RO) OR cs.LG' -> '(cat:cs.AI AND cat:cs.RO) OR cat:cs.LG'
    """
    # Match category identifiers like cs.AI, math.CO, etc. — word chars and dots
    # but not already prefixed with cat:
    return re.sub(r'(?<!cat:)\b([a-z][a-z0-9-]*\.[A-Z][A-Za-z]+)\b', r'cat:\1', expr)


def _parse_response(xml_text: str) -> tuple[list[dict], int]:
    """Parse arXiv Atom XML response into a list of paper dicts and total count."""
    root = ET.fromstring(xml_text)

    # Total results from opensearch
    total_el = root.find("opensearch:totalResults", NS)
    total = int(total_el.text) if total_el is not None and total_el.text else 0

    results = []
    for entry in root.findall("atom:entry", NS):
        paper = _parse_entry(entry)
        if paper:
            results.append(paper)

    return results, total


def _parse_entry(entry: ET.Element) -> dict | None:
    """Parse a single <entry> element into a normalized paper dict."""
    # Extract arxiv_id from <id> tag: http://arxiv.org/abs/2401.12345v1 -> 2401.12345v1
    id_el = entry.find("atom:id", NS)
    if id_el is None or not id_el.text:
        return None
    id_url = id_el.text.strip()
    arxiv_id = id_url.rsplit("/", 1)[-1] if "/" in id_url else id_url

    # Title (may contain newlines)
    title_el = entry.find("atom:title", NS)
    title = _clean_text(title_el.text) if title_el is not None and title_el.text else ""

    # Abstract / summary
    summary_el = entry.find("atom:summary", NS)
    abstract = _clean_text(summary_el.text) if summary_el is not None and summary_el.text else ""

    # Authors
    authors = []
    for author_el in entry.findall("atom:author", NS):
        name_el = author_el.find("atom:name", NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    # Dates
    published_el = entry.find("atom:published", NS)
    published = published_el.text.strip() if published_el is not None and published_el.text else ""

    updated_el = entry.find("atom:updated", NS)
    updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""

    # Links
    abs_url = ""
    pdf_url = ""
    for link_el in entry.findall("atom:link", NS):
        rel = link_el.get("rel", "")
        href = link_el.get("href", "")
        link_title = link_el.get("title", "")
        if rel == "alternate":
            abs_url = href
        elif link_title == "pdf":
            pdf_url = href

    # Categories
    primary_cat = ""
    primary_el = entry.find("arxiv:primary_category", NS)
    if primary_el is not None:
        primary_cat = primary_el.get("term", "")

    categories = []
    for cat_el in entry.findall("atom:category", NS):
        term = cat_el.get("term", "")
        if term:
            categories.append(term)

    # DOI (optional)
    doi_el = entry.find("arxiv:doi", NS)
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else ""

    # Comment (optional, often contains venue info)
    comment_el = entry.find("arxiv:comment", NS)
    comment = comment_el.text.strip() if comment_el is not None and comment_el.text else ""

    # Year from published date
    year = int(published[:4]) if len(published) >= 4 else 0

    # Build raw dict for normalize_paper
    raw = {
        "id": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "year": year,
        "url": abs_url,
        "pdf_url": pdf_url,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "categories": categories,
        "primary_category": primary_cat,
        "comment": comment,
        "published": published,
        "updated": updated,
    }

    paper = normalize_paper(raw, "arxiv")

    # Add extras not in PAPER_SCHEMA
    paper["arxiv_id"] = arxiv_id
    paper["categories"] = categories
    paper["primary_category"] = primary_cat
    paper["comment"] = comment
    paper["published"] = published
    paper["updated"] = updated

    return paper


def _clean_text(text: str) -> str:
    """Strip and collapse whitespace (arXiv titles/abstracts often have embedded newlines)."""
    return " ".join(text.split())


def _parse_iso_date(date_str: str) -> datetime:
    """Parse an ISO date string to a timezone-aware datetime. Returns epoch on failure."""
    if not date_str:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        cleaned = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_indices(spec: str) -> list[int]:
    """Parse index spec like '1,3-5' into [0, 2, 3, 4] (0-based)."""
    indices = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            indices.extend(range(int(lo) - 1, int(hi)))
        else:
            indices.append(int(part) - 1)
    return sorted(set(indices))


_PDF_DELAY = 3.0  # arXiv ToS: minimum 3s between downloads
_CAPTCHA_SIZE_THRESHOLD = 100 * 1024  # 100KB
_CAPTCHA_MARKERS = (b"<html", b"captcha", b"<!doctype")


def _download_pdfs(client, results: list[dict], indices: list[int], session_dir: str, to_md: bool) -> dict[int, dict]:
    """Download PDFs for specified result indices with CAPTCHA detection."""
    import time
    from pathlib import Path

    out_dir = Path(session_dir) / "sources" / "pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: dict[int, dict] = {}

    for idx in indices:
        if idx < 0 or idx >= len(results):
            continue
        paper = results[idx]
        pdf_url = paper.get("pdf_url", "")
        if not pdf_url:
            downloaded[idx] = {"error": "no pdf_url"}
            continue

        arxiv_id = paper.get("arxiv_id", f"paper_{idx}").replace("/", "_")
        pdf_path = out_dir / f"{arxiv_id}.pdf"

        log(f"Downloading PDF for {arxiv_id}...")
        time.sleep(_PDF_DELAY)

        info: dict = {}
        for attempt in range(3):
            try:
                resp = client.get(pdf_url, timeout=(15, 60))
                if resp.status_code in (502, 503, 504):
                    wait = 1 * (2 ** attempt)
                    log(f"Got {resp.status_code}, retrying in {wait}s", level="warn")
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    info = {"error": f"HTTP {resp.status_code}"}
                    break

                content = resp.content
                # CAPTCHA detection: small file with HTML markers
                if len(content) < _CAPTCHA_SIZE_THRESHOLD:
                    head = content[:1024].lower()
                    if any(marker in head for marker in _CAPTCHA_MARKERS):
                        log(f"CAPTCHA detected for {arxiv_id}, skipping", level="warn")
                        info = {"error": "captcha_detected"}
                        break

                pdf_path.write_bytes(content)
                info = {"path": str(pdf_path)}
                log(f"Saved {pdf_path} ({len(content)} bytes)")

                if to_md:
                    md_path = _convert_to_md(pdf_path)
                    if md_path:
                        info["md_path"] = str(md_path)
                break
            except Exception as e:
                if attempt == 2:
                    info = {"error": str(e)}
                else:
                    time.sleep(1 * (2 ** attempt))

        downloaded[idx] = info

    return downloaded


def _convert_to_md(pdf_path) -> str | None:
    """Convert a PDF to markdown using pymupdf4llm."""
    from pathlib import Path

    try:
        import pymupdf4llm
        md_text = pymupdf4llm.to_markdown(str(pdf_path))
        md_path = Path(str(pdf_path).replace(".pdf", ".md"))
        md_path.write_text(md_text, encoding="utf-8")
        log(f"Converted to markdown: {md_path}")
        return str(md_path)
    except ImportError:
        log("pymupdf4llm not installed, skipping markdown conversion", level="warn")
        return None
    except Exception as e:
        log(f"Markdown conversion failed: {e}", level="warn")
        return None
