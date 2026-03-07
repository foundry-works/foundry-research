"""Google Scholar search provider — scrapes search results and fetches citation exports."""

import contextlib
import os
import random
import re
import sys
import tempfile
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

SCHOLAR_URL = "https://scholar.google.com/scholar"

# Cookie values for citation export format
_FORMAT_COOKIE = {
    "bibtex": "4",
    "endnote": "3",
    "ris": "2",
}

# Rate limiting constants
_BASE_DELAY = 2.0
_JITTER = 0.5
_MAX_CONSECUTIVE_FAILURES = 3


def add_arguments(parser):
    parser.add_argument("--format", choices=["bibtex", "ris", "endnote"], default="bibtex", help="Citation export format (default: bibtex)")
    parser.add_argument("--parse", action="store_true", default=False, help="Parse BibTeX into structured JSON")


def search(args) -> dict:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="scholar_")
    client = create_session(session_dir, rate_limits={"scholar.google.com": 0.2})

    try:
        query = args.query
        if not query:
            return error_response(["--query is required for Google Scholar search"], error_code="missing_query")

        limit = args.limit
        offset = args.offset
        cite_format = getattr(args, "format", "bibtex")
        do_parse = getattr(args, "parse", False)

        # Build search URL
        params = {
            "q": query,
            "start": str(offset),
            "num": str(min(limit, 20)),  # Scholar caps at ~20 per page
        }
        url = f"{SCHOLAR_URL}?{urllib.parse.urlencode(params)}"

        # Set cookie for citation format
        cookie_val = _FORMAT_COOKIE.get(cite_format, "4")
        cookies = {"GSP": f"CF={cookie_val}"}

        log(f"Scholar query: {query} (format={cite_format}, offset={offset}, limit={limit})")

        response = client.get(url, cookies=cookies)

        if _is_blocked(response):
            return error_response(
                ["Google Scholar returned CAPTCHA or rate limit. Try again later."],
                error_code="rate_limited",
            )

        if response.status_code != 200:
            return error_response(
                [f"Google Scholar returned status {response.status_code}"],
                error_code="api_error",
            )

        # Parse search results HTML
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")
        entries = _parse_search_results(soup)
        log(f"Found {len(entries)} result entries on page")

        # Find citation (bib) links
        bib_links = _extract_bib_links(soup)
        log(f"Found {len(bib_links)} citation links")

        # Fetch citations for each result
        results = []
        consecutive_failures = 0

        for i, entry in enumerate(entries[:limit]):
            # Rate limiting with jitter
            if i > 0:
                delay = _BASE_DELAY + random.uniform(-_JITTER, _JITTER)
                time.sleep(delay)

            raw_citation = None
            parsed = None

            # Fetch citation if we have a bib link for this entry
            if i < len(bib_links):
                bib_url = bib_links[i]
                if not bib_url.startswith("http"):
                    bib_url = f"https://scholar.google.com{bib_url}"

                try:
                    bib_response = client.get(bib_url, cookies=cookies)

                    if _is_blocked(bib_response):
                        log("Blocked while fetching citation, returning partial results", level="warn")
                        results.append(_build_result(entry, None, None))
                        return _partial_response(results, "rate_limited")

                    if bib_response.status_code == 200:
                        raw_citation = bib_response.text.strip()
                        consecutive_failures = 0

                        if do_parse and cite_format == "bibtex" and raw_citation:
                            parsed = parse_bibtex(raw_citation)
                            # Merge parsed fields into entry
                            if parsed:
                                if parsed.get("title") and not entry.get("title"):
                                    entry["title"] = parsed["title"]
                                if parsed.get("authors"):
                                    entry["authors"] = parsed["authors"]
                                if parsed.get("year"):
                                    entry["year"] = parsed["year"]
                                if parsed.get("venue") and not entry.get("venue"):
                                    entry["venue"] = parsed["venue"]
                    else:
                        consecutive_failures += 1
                        log(f"Citation fetch failed with status {bib_response.status_code}", level="warn")

                except Exception as e:
                    consecutive_failures += 1
                    log(f"Citation fetch error: {e}", level="warn")

                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    log(f"Aborting after {_MAX_CONSECUTIVE_FAILURES} consecutive failures", level="error")
                    results.append(_build_result(entry, raw_citation, parsed))
                    return _partial_response(results, "consecutive_failures")

            result = _build_result(entry, raw_citation, parsed)

            # Normalize through metadata if we have parsed data
            if do_parse and parsed:
                normalized = normalize_paper(parsed, "scholar")
                result["normalized"] = normalized

            results.append(result)

        return success_response(results, total_results=len(results), has_more=False, best_effort=True)

    except Exception as e:
        log(f"Scholar search error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def parse_bibtex(raw: str) -> dict:
    """Parse a BibTeX entry into structured fields."""
    result = {}

    # Match @type{key,
    type_match = re.match(r"@(\w+)\{([^,]*),", raw.strip())
    if type_match:
        result["entry_type"] = type_match.group(1).lower()
        result["citation_key"] = type_match.group(2).strip()

    # Extract field = {value} or field = "value" pairs
    # Handles multi-line values within braces
    field_pattern = re.compile(r"(\w+)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\")", re.DOTALL)
    for match in field_pattern.finditer(raw):
        field_name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3)
        value = re.sub(r"\s+", " ", value).strip()
        result[field_name] = value

    # Split author field on ' and '
    if "author" in result:
        authors_str = result.pop("author")
        result["authors"] = [a.strip() for a in authors_str.split(" and ") if a.strip()]

    # Parse year to int
    if "year" in result:
        with contextlib.suppress(ValueError, TypeError):
            result["year"] = int(result["year"])

    # Map journal/booktitle to venue
    if "journal" in result:
        result["venue"] = result["journal"]
    elif "booktitle" in result:
        result["venue"] = result["booktitle"]

    return result


def _parse_search_results(soup) -> list[dict]:
    """Parse search result entries from Scholar HTML."""
    entries = []

    for div in soup.find_all("div", class_="gs_r gs_or gs_scl"):
        entry = {}

        # Title
        title_tag = div.find("h3", class_="gs_rt")
        if title_tag:
            # Remove [PDF], [HTML] etc. links inside the title
            for span in title_tag.find_all("span"):
                span.decompose()
            entry["title"] = title_tag.get_text(strip=True)
            # Extract URL from title link
            link = title_tag.find("a")
            if link and link.get("href"):
                entry["url"] = link["href"]

        # Author line and snippet
        info_div = div.find("div", class_="gs_a")
        if info_div:
            info_text = info_div.get_text(strip=True)
            entry["author_line"] = info_text
            # Parse authors (before first dash), year, venue
            parts = info_text.split(" - ")
            if parts:
                entry["authors"] = [a.strip() for a in parts[0].split(",") if a.strip()]
            # Try to extract year from the info line
            year_match = re.search(r"\b(19|20)\d{2}\b", info_text)
            if year_match:
                entry["year"] = int(year_match.group(0))

        # Snippet
        snippet_div = div.find("div", class_="gs_rs")
        if snippet_div:
            entry["snippet"] = snippet_div.get_text(strip=True)

        if entry.get("title"):
            entries.append(entry)

    return entries


def _extract_bib_links(soup) -> list[str]:
    """Extract citation export links (scholar.bib) from the page."""
    links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "scholar.bib" in href:
            links.append(href)
    return links


def _is_blocked(response) -> bool:
    """Check if the response indicates a CAPTCHA or rate limiting block."""
    if response.status_code == 429:
        return True
    text = response.text.lower()
    return "captcha" in text or "unusual traffic" in text


def _build_result(entry: dict, raw_citation: str | None, parsed: dict | None) -> dict:
    """Build a result dict from an entry, citation text, and parsed data."""
    return {
        "raw_citation": raw_citation,
        "parsed": parsed,
        "title": entry.get("title", ""),
        "authors": entry.get("authors", []),
        "year": entry.get("year", 0),
        "url": entry.get("url", ""),
        "snippet": entry.get("snippet", ""),
    }


def _partial_response(results: list[dict], reason: str) -> str:
    """Return partial results with an error message."""
    return error_response(
        [f"Search aborted due to {reason}. Returning {len(results)} partial result(s)."],
        partial_results=results,
        error_code=reason,
    )
