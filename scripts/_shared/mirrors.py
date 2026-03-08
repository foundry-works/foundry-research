"""Mirror discovery and download for Anna's Archive and Sci-Hub.

All HTTP requests go through the shared HttpClient for consistent rate limiting.
"""

import os
import re
import time

from _shared.output import log
from _shared.pdf_utils import download_pdf

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


def _discover_mirrors(service: str, client) -> list[str]:
    """Fetch Wikipedia article and extract mirror domains."""
    url = _MIRROR_SOURCES[service]
    pattern = _MIRROR_PATTERNS[service]
    fallbacks = _ANNAS_FALLBACK_MIRRORS if service == "annas" else _SCIHUB_FALLBACK_MIRRORS

    try:
        resp = client.get(url, timeout=(15, 15))
        resp.raise_for_status()
        tlds = set(re.findall(pattern, resp.text))
        base = "annas-archive" if service == "annas" else "sci-hub"
        discovered = [f"{base}.{tld}" for tld in tlds]
        if discovered:
            log(f"Discovered {len(discovered)} {service} mirrors from Wikipedia")
            return discovered
    except Exception as e:
        log(f"Wikipedia mirror discovery failed for {service}: {e}", level="warn")

    return list(fallbacks)


def _find_working_mirror(service: str, client) -> str | None:
    """Find a working mirror, using cache when available."""
    if service in _mirror_cache:
        cached_mirror, cached_at = _mirror_cache[service]
        if time.time() - cached_at < _MIRROR_CACHE_TTL:
            return cached_mirror

    mirrors = _discover_mirrors(service, client)
    for mirror in mirrors:
        try:
            resp = client.get(f"https://{mirror}", timeout=(10, 10), allow_redirects=True)
            if resp.status_code < 500:
                log(f"Found working {service} mirror: {mirror}")
                _mirror_cache[service] = (mirror, time.time())
                return mirror
        except Exception:
            continue

    log(f"No working {service} mirror found", level="warn")
    _mirror_cache[service] = (None, time.time())
    return None


# ---------------------------------------------------------------------------
# Anna's Archive
# ---------------------------------------------------------------------------


def download_annas_archive(doi: str, dest_path: str, config: dict, client) -> bool:
    """Try downloading a paper via Anna's Archive.

    Strategy:
    1. Look up DOI via /scidb/{doi} to get MD5 hash
    2. If ANNAS_SECRET_KEY is set, use fast_download API
    3. Otherwise, scrape the download page
    """
    mirror = _find_working_mirror("annas", client)
    if not mirror:
        return False

    secret_key = config.get("annas_secret_key")
    md5_hash = _annas_search_doi(doi, mirror, client)
    if not md5_hash:
        return False

    if secret_key:
        if _annas_download_api(md5_hash, secret_key, mirror, dest_path, client):
            return True
        log("Anna's Archive API download failed, trying scrape fallback", level="warn")

    return _annas_download_scrape(md5_hash, mirror, dest_path, client)


def _annas_search_doi(doi: str, mirror: str, client) -> str | None:
    """Look up a DOI on Anna's Archive and extract an MD5 hash."""
    url = f"https://{mirror}/scidb/{doi}"
    try:
        resp = client.get(url, timeout=(15, 15), allow_redirects=True)
        if resp.status_code != 200:
            log(f"Anna's Archive returned {resp.status_code} for DOI {doi}", level="debug")
            return None

        md5_matches = re.findall(r'/md5/([a-f0-9]{32})', resp.text, re.IGNORECASE)
        if md5_matches:
            log(f"Anna's Archive found MD5: {md5_matches[0]} for DOI {doi}")
            return md5_matches[0]

        log(f"No MD5 hash found on Anna's Archive for DOI {doi}", level="debug")
        return None
    except Exception as e:
        log(f"Anna's Archive DOI lookup failed: {e}", level="warn")
        return None


def _annas_download_api(md5: str, secret_key: str, mirror: str, dest: str, client) -> bool:
    """Download via Anna's Archive JSON API (requires API key)."""
    url = f"https://{mirror}/dyn/api/fast_download.json?md5={md5}&key={secret_key}"
    try:
        resp = client.get(url, timeout=(15, 15))
        if resp.status_code != 200:
            return False

        data = resp.json()
        download_url = data.get("download_url")
        if not download_url:
            return False

        dl_result = download_pdf(download_url, dest, client, timeout=60)
        if dl_result["success"]:
            log(f"Anna's Archive API download successful: {dest}")
            return True

        if os.path.exists(dest):
            os.unlink(dest)
        return False
    except Exception as e:
        log(f"Anna's Archive API download failed: {e}", level="warn")
        if os.path.exists(dest):
            os.unlink(dest)
        return False


def _annas_download_scrape(md5: str, mirror: str, dest: str, client) -> bool:
    """Download via Anna's Archive web scraping (no auth needed)."""
    url = f"https://{mirror}/md5/{md5}"
    try:
        resp = client.get(url, timeout=(15, 15), allow_redirects=True)
        if resp.status_code != 200:
            return False

        download_urls = re.findall(
            r'href="(https?://[^"]+)"[^>]*>.*?(?:download|GET|PDF)',
            resp.text, re.IGNORECASE | re.DOTALL,
        )

        for dl_url in download_urls[:3]:
            try:
                dl_result = download_pdf(dl_url, dest, client, timeout=60)
                if dl_result["success"]:
                    log(f"Anna's Archive scrape download successful: {dest}")
                    return True
                if os.path.exists(dest):
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
# Sci-Hub
# ---------------------------------------------------------------------------


def download_scihub(doi: str, dest_path: str, client) -> bool:
    """Try downloading a paper via Sci-Hub (pre-2021 papers only)."""
    mirror = _find_working_mirror("scihub", client)
    if not mirror:
        return False

    url = f"https://{mirror}/{doi}"
    try:
        resp = client.get(url, timeout=(15, 30))
        if resp.status_code != 200:
            log(f"Sci-Hub returned {resp.status_code}", level="debug")
            return False

        # Extract PDF URL from iframe or embed
        pdf_url = None

        iframe_match = re.search(
            r'<iframe[^>]+(?:id=["\']pdf["\']|src=["\']([^"\']+\.pdf[^"\']*)["\'])[^>]*>',
            resp.text, re.IGNORECASE,
        )
        if iframe_match:
            pdf_url = iframe_match.group(1)

        if not pdf_url:
            embed_match = re.search(
                r'<embed[^>]+src=["\']([^"\']+\.pdf[^"\']*)["\']',
                resp.text, re.IGNORECASE,
            )
            if embed_match:
                pdf_url = embed_match.group(1)

        if not pdf_url:
            onclick_match = re.search(
                r'location\.href\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']',
                resp.text, re.IGNORECASE,
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

        dl_result = download_pdf(pdf_url, dest_path, client)
        if dl_result["success"]:
            log(f"Sci-Hub download successful: {dest_path}")
            return True
        return False

    except Exception as e:
        log(f"Sci-Hub download failed: {e}", level="warn")
        if os.path.exists(dest_path):
            os.unlink(dest_path)
        return False
