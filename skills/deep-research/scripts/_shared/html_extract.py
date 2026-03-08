"""HTML to text extraction and JATS XML stripping."""

import re

# Tags whose content should be removed entirely
_STRIP_TAGS = {"script", "style", "noscript", "svg", "iframe"}

# Tags considered non-content for readable extraction
_NAV_TAGS = {"nav", "header", "footer", "aside", "menu", "menuitem"}

# JATS XML tags commonly found in academic abstracts
_JATS_RE = re.compile(r"</?jats:[^>]+>", re.IGNORECASE)

# Generic HTML tag pattern
_TAG_RE = re.compile(r"<[^>]+>")

# Multiple whitespace/newlines
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Extract readable text from HTML.

    Uses BeautifulSoup if available, falls back to regex tag stripping.
    """
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style/etc
        for tag in soup.find_all(_STRIP_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        # Fallback: regex-based stripping
        text = _regex_strip(html)

    return _clean_whitespace(text)


def extract_readable_content(html: str) -> str:
    """Extract main article content, stripping nav/header/footer/sidebar.

    Best-effort heuristic. Uses BeautifulSoup if available.
    """
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Remove non-content elements
        for tag in soup.find_all(_STRIP_TAGS | _NAV_TAGS):
            tag.decompose()

        # Try to find main content container
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", {"role": "main"})
            or soup.find("div", class_=re.compile(r"content|article|post|entry", re.I))
        )

        target = main or soup.body or soup
        text = target.get_text(separator="\n")
    except ImportError:
        text = _regex_strip(html)

    return _clean_whitespace(text)


def strip_jats_xml(text: str) -> str:
    """Strip JATS XML tags from academic abstracts.

    Common in Crossref/OpenAlex responses (e.g., <jats:p>, <jats:italic>).
    """
    if not text:
        return ""
    return _clean_whitespace(_JATS_RE.sub("", text))


def _regex_strip(html: str) -> str:
    """Fallback HTML stripping using regex when BeautifulSoup is unavailable."""
    # Remove content of script/style tags
    for tag in _STRIP_TAGS:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace <br>, <p>, <div>, <li> with newlines
    html = re.sub(r"<(?:br|/p|/div|/li|/tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    return _TAG_RE.sub("", html)


def _clean_whitespace(text: str) -> str:
    """Normalize whitespace: collapse spaces, limit consecutive newlines."""
    lines = []
    for line in text.splitlines():
        line = _MULTI_SPACE_RE.sub(" ", line).strip()
        lines.append(line)
    text = "\n".join(lines)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()
