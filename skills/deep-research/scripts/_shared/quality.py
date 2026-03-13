"""Content quality assessment for converted PDFs and web extracts."""

import re

# Thresholds
_MIN_CONTENT_LENGTH = 500  # chars of real text
_MIN_ALPHA_RATIO = 0.40  # at least 40% alphabetic characters
_MIN_SENTENCE_COUNT = 3  # at least 3 sentences for "ok"
_MIN_LINEBREAKS_PER_CHARS = 500  # <1 break per 500 chars → degraded
_MAX_NON_ALPHA_RATIO = 0.20  # >20% non-alphanumeric → degraded

# Paywall / access-gate markers — case-insensitive substrings scanned in first 50 lines.
# These appear on publisher landing pages served in place of actual paper content.
_PAYWALL_MARKERS = [
    "buy article", "buy this article",
    "subscribe", "subscription required",
    "log in via an institution", "log in via your institution",
    "access this article", "access through your institution",
    "purchase this article", "rent this article",
    "add to cart",
    "USD", "EUR", "GBP",  # price tags
]

# Sentence pattern: starts with uppercase, ends with sentence-ending punctuation
_SENTENCE_RE = re.compile(r"[A-Z][^.!?]*[.!?]")

# Common punctuation that should NOT count as "non-alphanumeric junk"
_NORMAL_PUNCT = set(" \t\n\r.,;:!?'\"-()[]{}/#@&*+=<>|~`^%$_\\")


def _detect_paywall(text: str, max_lines: int = 50) -> str:
    """Return the first paywall marker found in the first *max_lines* lines, or ""."""
    head = "\n".join(text.split("\n", max_lines)[:max_lines]).lower()
    for marker in _PAYWALL_MARKERS:
        if marker.lower() in head:
            return marker
    return ""


def assess_quality(text: str) -> dict:
    """Assess content quality of converted text.

    Returns:
        {
            "quality": "ok" | "degraded" | "empty",
            "quality_details": {
                "content_length": int,
                "alpha_ratio": float,
                "sentence_count": int,
                "reasons": [str],  # why quality was downgraded
            }
        }
    """
    if not text:
        return {
            "quality": "empty",
            "quality_details": {
                "content_length": 0,
                "alpha_ratio": 0.0,
                "sentence_count": 0,
                "reasons": ["no content"],
            },
        }

    # Strip HTML warning comments for assessment
    check_text = text
    while check_text.startswith("<!-- WARNING:"):
        idx = check_text.find("-->")
        if idx >= 0:
            check_text = check_text[idx + 3:].strip()
        else:
            break

    if not check_text:
        return {
            "quality": "empty",
            "quality_details": {
                "content_length": 0,
                "alpha_ratio": 0.0,
                "sentence_count": 0,
                "reasons": ["only warning comments, no content"],
            },
        }

    content_length = len(check_text)
    reasons = []

    # 1. Content length check
    if content_length < _MIN_CONTENT_LENGTH:
        reasons.append(f"content too short ({content_length} chars < {_MIN_CONTENT_LENGTH})")

    # 2. Alphabetic character ratio
    alpha_count = sum(1 for c in check_text if c.isalpha())
    alpha_ratio = alpha_count / content_length if content_length > 0 else 0.0
    if alpha_ratio < _MIN_ALPHA_RATIO:
        reasons.append(f"low alphabetic ratio ({alpha_ratio:.2f} < {_MIN_ALPHA_RATIO})")

    # 3. Sentence detection
    sentences = _SENTENCE_RE.findall(check_text)
    sentence_count = len(sentences)
    if sentence_count < _MIN_SENTENCE_COUNT:
        reasons.append(f"few sentences detected ({sentence_count} < {_MIN_SENTENCE_COUNT})")

    # 4. Linebreak density (from original _check_quality)
    linebreaks = check_text.count("\n")
    if content_length > 0 and linebreaks > 0:
        chars_per_break = content_length / linebreaks
        if chars_per_break > _MIN_LINEBREAKS_PER_CHARS:
            reasons.append(f"low linebreak density ({chars_per_break:.0f} chars/break)")

    # 5. Non-alphanumeric ratio (from original _check_quality)
    non_alpha = sum(1 for c in check_text if not c.isalnum() and c not in _NORMAL_PUNCT)
    if content_length > 0:
        non_alpha_ratio = non_alpha / content_length
        if non_alpha_ratio > _MAX_NON_ALPHA_RATIO:
            reasons.append(f"high non-alphanumeric ratio ({non_alpha_ratio:.2f} > {_MAX_NON_ALPHA_RATIO})")

    # 6. Paywall / access-gate detection (first 50 lines)
    paywall_hit = _detect_paywall(check_text)

    details = {
        "content_length": content_length,
        "alpha_ratio": round(alpha_ratio, 3),
        "sentence_count": sentence_count,
        "reasons": reasons,
    }

    # Paywall pages get their own quality label so downstream can distinguish
    # access-gate pages from genuinely degraded conversions.
    if paywall_hit:
        details["reasons"] = reasons + [f"paywall_page ({paywall_hit})"]
        return {"quality": "degraded", "quality_details": details}

    if not reasons:
        return {"quality": "ok", "quality_details": details}

    # Empty if basically no real content
    if content_length < 50 or (alpha_ratio < 0.1 and sentence_count == 0):
        return {"quality": "empty", "quality_details": details}

    return {"quality": "degraded", "quality_details": details}


_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
    "were", "been", "have", "has", "had", "its", "not", "but", "can",
    "may", "how", "what", "which", "who", "all", "any", "than", "into",
    "our", "their", "between", "about", "more", "also", "does", "new",
    "through", "during", "based", "using", "study", "research", "analysis",
}


def _extract_keywords(text: str, stopwords: set[str] = _STOPWORDS, min_len: int = 3) -> list[str]:
    """Extract non-stopword terms from text (lowercase, 3+ chars)."""
    return [
        w for w in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
        if len(w) >= min_len and w not in stopwords
    ]


def check_content_mismatch(
    text: str,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
) -> dict:
    """Check if extracted text plausibly matches expected metadata.

    Looks for title keywords and author surnames in the text. If zero matches
    are found, the content is likely from the wrong paper (e.g., wrong PDF
    retrieved from a mirror).

    When an abstract is provided, also checks abstract-keyword overlap against
    the content. This catches the failure mode where a paper shares common
    words with the title (e.g., "children" and "behavior") but is about a
    completely different topic (e.g., dental hygiene, not temperament).

    Returns:
        {"mismatched": bool, "title_hits": int, "author_hits": int,
         "abstract_overlap": float | None, "reason": str}
    """
    if not text or (not title and not authors):
        return {"mismatched": False, "title_hits": 0, "author_hits": 0,
                "abstract_overlap": None, "reason": ""}

    text_lower = text[:20000].lower()  # check first ~20k chars for speed

    # Extract meaningful title keywords (3+ chars, skip stopwords)
    title_words = _extract_keywords(title) if title else []
    title_hits = sum(1 for w in title_words if w in text_lower) if title_words else 0

    # Check author surnames (last name before comma, or last word)
    author_hits = 0
    if authors:
        for author in authors[:5]:  # check first 5 authors
            parts = author.split(",")
            surname = parts[0].strip().lower() if parts else ""
            if surname and len(surname) >= 3 and surname in text_lower:
                author_hits += 1

    # Abstract-keyword overlap check
    abstract_overlap = None
    if abstract and len(abstract) >= 50:
        abstract_kws = _extract_keywords(abstract)
        # Deduplicate and take top 10 by length (longer = more domain-specific)
        seen = set()
        unique_kws = []
        for kw in sorted(abstract_kws, key=len, reverse=True):
            if kw not in seen:
                seen.add(kw)
                unique_kws.append(kw)
        abstract_kws = unique_kws[:10]

        if abstract_kws:
            # Check against first 5000 words (~first few pages)
            text_check = text_lower[:15000]
            hits = sum(1 for kw in abstract_kws if kw in text_check)
            abstract_overlap = hits / len(abstract_kws)

    # Mismatch: we have metadata to check against but found nothing
    has_title_keywords = len(title_words) >= 2
    has_authors = bool(authors and len(authors) >= 1)

    if has_title_keywords and has_authors:
        mismatched = title_hits == 0 and author_hits == 0
    elif has_title_keywords:
        mismatched = title_hits == 0
    elif has_authors:
        mismatched = author_hits == 0
    else:
        mismatched = False

    # Abstract-keyword gate: even if title/author passed, flag as mismatched
    # when abstract overlap is very low AND title match is weak.
    # This catches papers that share generic title words but are off-topic.
    # Threshold: title_hits < 3 because generic words (children, behavior,
    # measurement) easily produce 2 hits on completely wrong papers.
    if (not mismatched and abstract_overlap is not None
            and abstract_overlap < 0.2 and title_hits < 3):
        mismatched = True

    reason = ""
    if mismatched:
        parts = []
        parts.append(
            f"{title_hits}/{len(title_words)} title keywords and "
            f"{author_hits}/{len(authors or [])} author surnames found"
        )
        if abstract_overlap is not None:
            parts.append(f"abstract keyword overlap {abstract_overlap:.0%}")
        reason = f"content may be from wrong paper: {', '.join(parts)}"

    return {
        "mismatched": mismatched,
        "title_hits": title_hits,
        "author_hits": author_hits,
        "abstract_overlap": abstract_overlap,
        "reason": reason,
    }
