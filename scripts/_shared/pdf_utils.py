"""PDF download, validation, conversion to Markdown, and TOC generation."""

import os
import re
import subprocess
import sys
from pathlib import Path

from _shared.output import log

# Quality check thresholds
_MIN_LINEBREAKS_PER_CHARS = 500  # <1 break per 500 chars → degraded
_MAX_NON_ALPHA_RATIO = 0.20  # >20% non-alphanumeric → degraded

# Common punctuation that should NOT count as "non-alphanumeric junk"
_NORMAL_PUNCT = set(" \t\n\r.,;:!?'\"-()[]{}/#@&*+=<>|~`^%$_\\")

# Heading pattern for TOC extraction
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# pymupdf4llm subprocess timeout (seconds)
_PYMUPDF_TIMEOUT = 60

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
        if resp.status_code != 200:
            return {"success": False, "size_bytes": 0, "errors": [f"HTTP {resp.status_code}"]}

        # Check Content-Length if available
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_size_mb * 1024 * 1024:
            return {"success": False, "size_bytes": 0, "errors": [f"PDF too large: {int(content_length)} bytes (limit {max_size_mb}MB)"]}

        # Stream to file
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > max_size_mb * 1024 * 1024:
                    f.close()
                    os.unlink(dest_path)
                    return {"success": False, "size_bytes": size, "errors": [f"PDF exceeded {max_size_mb}MB during download"]}
                f.write(chunk)

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
    quality = _check_quality(md_text)

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
    }


def generate_toc(md_path: str, toc_path: str) -> dict:
    """Extract headings from Markdown and write a TOC file.

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

    for line_num, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            toc_entries.append(f"{line_num}\t{level}\t{heading_text}")

    if not toc_entries:
        return {"headings": 0, "toc_file": None}

    Path(toc_path).write_text("\n".join(toc_entries) + "\n", encoding="utf-8")
    return {"headings": len(toc_entries), "toc_file": toc_path}


def _run_pymupdf4llm(pdf_path: str, timeout: int) -> str | None:
    """Run pymupdf4llm.to_markdown() in a subprocess with a timeout."""
    script = (
        "import sys, pymupdf4llm; "
        "md = pymupdf4llm.to_markdown(sys.argv[1]); "
        "sys.stdout.buffer.write(md.encode('utf-8'))"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, pdf_path],
            capture_output=True,
            timeout=timeout,
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


def _run_pypdf(pdf_path: str) -> str | None:
    """Extract raw text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        log("pypdf not installed, cannot fall back", level="error")
        return None

    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)

    return "\n\n".join(pages) if pages else None


def _check_quality(md_text: str) -> str:
    """Check structural quality of converted markdown.

    Returns "ok" or "degraded".
    """
    if not md_text:
        return "degraded"

    # Strip warning comments for quality check
    check_text = md_text
    if check_text.startswith("<!-- WARNING:"):
        # Skip past the warning line
        idx = check_text.find("-->")
        if idx >= 0:
            check_text = check_text[idx + 3:].strip()

    if not check_text:
        return "degraded"

    # Check linebreak density
    linebreaks = check_text.count("\n")
    chars = len(check_text)
    if chars > 0 and chars / max(linebreaks, 1) > _MIN_LINEBREAKS_PER_CHARS:
        return "degraded"

    # Check non-alphanumeric ratio (excluding normal punctuation and whitespace)
    non_alpha = sum(1 for c in check_text if not c.isalnum() and c not in _NORMAL_PUNCT)
    if chars > 0 and non_alpha / chars > _MAX_NON_ALPHA_RATIO:
        return "degraded"

    return "ok"
