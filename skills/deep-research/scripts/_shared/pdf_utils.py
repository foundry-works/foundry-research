"""PDF download, validation, conversion to Markdown, and TOC generation."""

import os
import re
import subprocess
import sys
from pathlib import Path

from _shared.output import log
from _shared.quality import assess_quality

# Heading pattern for TOC extraction
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Heuristic patterns for academic section headings in plain-text PDFs
# Matches "1. Introduction", "2.1. Design", "1.3.2. Differences from..."
_NUMBERED_SECTION_RE = re.compile(
    r"^(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z\s,:\-–—]{2,80})$"
)
_ALLCAPS_SECTION_RE = re.compile(
    r"^([A-Z]{3,}(?:\s+[A-Z&]{2,}){0,5})$"
)
_ACADEMIC_SECTIONS = {
    "abstract", "introduction", "background", "related work",
    "methods", "method", "methodology", "materials and methods",
    "experimental setup", "experimental design",
    "results", "findings", "analysis",
    "discussion", "general discussion", "limitations",
    "conclusion", "conclusions", "concluding remarks", "summary",
    "references", "bibliography",
    "acknowledgements", "acknowledgments",
    "appendix", "appendices",
    "supplementary material", "supplementary materials",
    "data availability", "competing interests", "author contributions",
    "participants", "stimuli", "procedure", "design",
    "measures", "dependent variables", "independent variables",
    "statistical analysis", "data analysis",
}

# pymupdf4llm subprocess timeout (seconds)
_PYMUPDF_TIMEOUT = 60

# Memory limit for PDF conversion subprocesses (2 GB)
_SUBPROCESS_MEM_LIMIT = 2 * 1024 * 1024 * 1024

# Max markdown output size (50 MB) — prevents OOM when parent captures subprocess stdout
_MAX_MD_OUTPUT = 50 * 1024 * 1024


def _make_mem_limiter():
    """Return a preexec_fn that caps subprocess RSS, or None if unsupported."""
    try:
        import resource
        def _limit():
            resource.setrlimit(resource.RLIMIT_AS, (_SUBPROCESS_MEM_LIMIT, _SUBPROCESS_MEM_LIMIT))
        return _limit
    except (ImportError, AttributeError):
        # Windows or missing RLIMIT_AS
        return None

# PDF magic bytes
_PDF_MAGIC = b"%PDF"

# Warnings prepended to degraded/headingless markdown
_FALLBACK_WARNING = (
    "<!-- WARNING: PDF conversion fell back to raw text extraction. "
    "Layout and headings may be missing. -->\n\n"
)
_NO_HEADINGS_WARNING = (
    "<!-- WARNING: No headings detected during PDF conversion. "
    "Document structure may be garbled. Use Grep to locate sections "
    "by keyword instead of offset/limit. -->\n\n"
)


def download_pdf(
    url: str,
    dest_path: str,
    client,
    timeout: int = 60,
    max_size_mb: int = 50,
) -> dict:
    """Download a PDF from a URL with validation.

    Args:
        url: PDF URL to download.
        dest_path: Local file path to save the PDF.
        client: HttpClient instance for the request.
        timeout: Read timeout in seconds.
        max_size_mb: Maximum file size in MB.

    Returns:
        {"success": bool, "size_bytes": int, "errors": []}
    """
    try:
        resp = client.get(url, timeout=(15, timeout), stream=True)
        try:
            if resp.status_code != 200:
                return {"success": False, "size_bytes": 0, "errors": [f"HTTP {resp.status_code}"]}

            # Check Content-Length if available
            content_length = resp.headers.get("Content-Length")
            if content_length:
                try:
                    cl_bytes = int(content_length)
                except (ValueError, TypeError):
                    cl_bytes = 0
                if cl_bytes > max_size_mb * 1024 * 1024:
                    return {"success": False, "size_bytes": 0, "errors": [f"PDF too large: {cl_bytes} bytes (limit {max_size_mb}MB)"]}

            # Stream to file
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            size = 0
            oversize = False
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > max_size_mb * 1024 * 1024:
                        oversize = True
                        break
                    f.write(chunk)
        finally:
            resp.close()

        if oversize:
            os.unlink(dest_path)
            return {"success": False, "size_bytes": size, "errors": [f"PDF exceeded {max_size_mb}MB during download"]}

        # Validate the downloaded file
        if not validate_pdf(dest_path):
            # Check if it's HTML (server returned error page instead of PDF)
            with open(dest_path, "rb") as f:
                head = f.read(1024).lower()
            if b"<html" in head or b"<!doctype" in head or b"captcha" in head:
                os.unlink(dest_path)
                return {"success": False, "size_bytes": size, "errors": ["Server returned HTML instead of PDF"]}
            os.unlink(dest_path)
            return {"success": False, "size_bytes": size, "errors": ["Invalid PDF (bad magic bytes or truncated)"]}

        return {"success": True, "size_bytes": size, "errors": []}

    except Exception as e:
        # Clean up partial file
        if os.path.exists(dest_path):
            os.unlink(dest_path)
        return {"success": False, "size_bytes": 0, "errors": [str(e)]}


def validate_pdf(path: str) -> bool:
    """Check that a file starts with %PDF magic bytes and is not truncated."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != _PDF_MAGIC:
                return False
            # Check minimum viable size (a valid PDF is at least ~60 bytes)
            f.seek(0, 2)
            size = f.tell()
            return size >= 64
    except OSError:
        return False


def pdf_to_markdown(
    pdf_path: str,
    md_path: str,
    timeout: int = _PYMUPDF_TIMEOUT,
) -> dict:
    """Convert PDF to Markdown with pymupdf4llm (primary) and pypdf (fallback).

    Runs pymupdf4llm in a subprocess to enforce a strict timeout.
    If it fails or times out, falls back to pypdf raw text extraction.

    After conversion, runs a quality check and generates a TOC.

    Returns:
        {"success": bool, "content_length": int, "toc_file": str | None,
         "converter": "pymupdf4llm" | "pypdf", "quality": "ok" | "degraded"}
    """
    md_text = None
    converter = "pymupdf4llm"

    # Try pymupdf4llm via subprocess (enforces timeout even if C code hangs)
    try:
        md_text = _run_pymupdf4llm(pdf_path, timeout)
    except Exception as e:
        log(f"pymupdf4llm failed for {pdf_path}: {e}", level="warn")

    # Fallback to pypdf
    if md_text is None:
        converter = "pypdf"
        try:
            md_text = _run_pypdf(pdf_path)
            if md_text:
                md_text = _FALLBACK_WARNING + md_text
        except Exception as e:
            log(f"pypdf fallback also failed for {pdf_path}: {e}", level="error")
            return {
                "success": False,
                "content_length": 0,
                "toc_file": None,
                "converter": converter,
                "quality": "degraded",
            }

    if not md_text:
        return {
            "success": False,
            "content_length": 0,
            "toc_file": None,
            "converter": converter,
            "quality": "degraded",
        }

    # Quality check
    qa = assess_quality(md_text)
    quality = qa["quality"]
    quality_details = qa["quality_details"]

    if quality == "degraded":
        log(f"PDF conversion quality is degraded — content may be unusable: {quality_details.get('reasons', [])}", level="warn")

    # Write markdown
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    Path(md_path).write_text(md_text, encoding="utf-8")

    # Generate TOC
    toc_path = md_path.replace(".md", ".toc")
    toc_result = generate_toc(md_path, toc_path)
    toc_file = toc_result.get("toc_file")

    # If no headings detected, prepend warning
    if toc_file is None and not md_text.startswith("<!-- WARNING:"):
        md_text = _NO_HEADINGS_WARNING + md_text
        Path(md_path).write_text(md_text, encoding="utf-8")

    return {
        "success": True,
        "content_length": len(md_text),
        "toc_file": toc_file,
        "converter": converter,
        "quality": quality,
        "quality_details": quality_details,
    }


def generate_toc(md_path: str, toc_path: str) -> dict:
    """Extract headings from Markdown and write a TOC file.

    Uses markdown heading syntax first, then falls back to heuristic
    detection of academic section headings (ALL-CAPS lines, numbered
    sections, known section names) when markdown headings are sparse.

    Output format: LINE_NUMBER<tab>HEADING_LEVEL<tab>HEADING_TEXT

    Returns:
        {"headings": int, "toc_file": str | None}
    """
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except OSError:
        return {"headings": 0, "toc_file": None}

    lines = text.splitlines()
    toc_entries = []

    # Pass 1: explicit markdown headings
    for line_num, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            toc_entries.append(f"{line_num}\t{level}\t{heading_text}")

    # Pass 2: heuristic detection if markdown headings are sparse (<=3)
    if len(toc_entries) <= 3:
        heading_lines = {int(e.split("\t")[0]) for e in toc_entries}
        for line_num, line in enumerate(lines, start=1):
            if line_num in heading_lines:
                continue
            stripped = line.strip()
            if not stripped or len(stripped) > 120:
                continue

            # Numbered sections: "1. Introduction", "2.1. Participants", "1.3.2. Differences"
            m = _NUMBERED_SECTION_RE.match(stripped)
            if m:
                num_part = m.group(1)
                depth = num_part.count(".") + 2  # "1" -> level 2, "1.1" -> level 3
                toc_entries.append(f"{line_num}\t{depth}\t{stripped}")
                heading_lines.add(line_num)
                continue

            # ALL-CAPS lines (<=6 words, letters and spaces only)
            m = _ALLCAPS_SECTION_RE.match(stripped)
            if m and len(stripped.split()) <= 6:
                toc_entries.append(f"{line_num}\t2\t{stripped.title()}")
                heading_lines.add(line_num)
                continue

            # Known academic section names (case-insensitive, standalone short lines)
            if stripped.lower() in _ACADEMIC_SECTIONS and len(stripped) < 50:
                toc_entries.append(f"{line_num}\t2\t{stripped.title()}")
                heading_lines.add(line_num)

        # Re-sort by line number after heuristic additions
        toc_entries.sort(key=lambda e: int(e.split("\t")[0]))

    if not toc_entries:
        return {"headings": 0, "toc_file": None}

    Path(toc_path).write_text("\n".join(toc_entries) + "\n", encoding="utf-8")
    return {"headings": len(toc_entries), "toc_file": toc_path}


def _run_pymupdf4llm(pdf_path: str, timeout: int) -> str | None:
    """Run pymupdf4llm.to_markdown() in a subprocess with a timeout.

    Output is truncated at _MAX_MD_OUTPUT inside the subprocess to prevent
    the parent from buffering unbounded stdout into memory.
    """
    limit = _MAX_MD_OUTPUT
    script = (
        "import sys, pymupdf4llm; "
        "md = pymupdf4llm.to_markdown(sys.argv[1]); "
        f"out = md.encode('utf-8')[:{limit}]; "
        "sys.stdout.buffer.write(out)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, pdf_path],
            capture_output=True,
            timeout=timeout,
            preexec_fn=_make_mem_limiter(),
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            log(f"pymupdf4llm subprocess failed: {stderr}", level="warn")
            return None
        text = result.stdout.decode("utf-8", errors="replace")
        return text if text.strip() else None
    except subprocess.TimeoutExpired:
        log(f"pymupdf4llm timed out after {timeout}s for {pdf_path}", level="warn")
        return None


_MAX_PYPDF_PAGES = 500  # cap to prevent OOM on huge documents


def extract_first_page_text(pdf_path: str, timeout: int = 15) -> str | None:
    """Extract text from the first page of a PDF for quick mismatch checks.

    Uses pypdf in a subprocess with a short timeout. Returns None on failure.
    """
    script = (
        "import sys; from pypdf import PdfReader; "
        "reader = PdfReader(sys.argv[1]); "
        "text = reader.pages[0].extract_text() if reader.pages else ''; "
        "sys.stdout.buffer.write((text or '').encode('utf-8')[:8000])"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, pdf_path],
            capture_output=True,
            timeout=timeout,
            preexec_fn=_make_mem_limiter(),
        )
        if result.returncode != 0:
            return None
        text = result.stdout.decode("utf-8", errors="replace")
        return text if text.strip() else None
    except (subprocess.TimeoutExpired, Exception):
        return None


def _run_pypdf(pdf_path: str, timeout: int = _PYMUPDF_TIMEOUT) -> str | None:
    """Extract raw text from PDF using pypdf in a subprocess with timeout.

    Runs in a subprocess for memory isolation and timeout enforcement,
    matching the pattern used by _run_pymupdf4llm.  Output is truncated
    at _MAX_MD_OUTPUT to prevent unbounded parent memory usage.
    """
    out_limit = _MAX_MD_OUTPUT
    script = (
        "import sys; from pypdf import PdfReader; "
        f"reader = PdfReader(sys.argv[1]); "
        f"limit = min(len(reader.pages), {_MAX_PYPDF_PAGES}); "
        "pages = [p.extract_text() or '' for p in reader.pages[:limit]]; "
        "text = '\\n\\n'.join(p for p in pages if p); "
        f"sys.stdout.buffer.write(text.encode('utf-8')[:{out_limit}])"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, pdf_path],
            capture_output=True,
            timeout=timeout,
            preexec_fn=_make_mem_limiter(),
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if "No module named" in stderr:
                log("pypdf not installed, cannot fall back", level="error")
            else:
                log(f"pypdf subprocess failed: {stderr}", level="warn")
            return None
        text = result.stdout.decode("utf-8", errors="replace")
        return text if text.strip() else None
    except subprocess.TimeoutExpired:
        log(f"pypdf timed out after {timeout}s for {pdf_path}", level="warn")
        return None


