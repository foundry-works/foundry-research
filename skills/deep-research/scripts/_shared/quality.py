"""Content quality assessment for converted PDFs and web extracts."""

import re

# Thresholds
_MIN_CONTENT_LENGTH = 500  # chars of real text
_MIN_ALPHA_RATIO = 0.40  # at least 40% alphabetic characters
_MIN_SENTENCE_COUNT = 3  # at least 3 sentences for "ok"
_MIN_LINEBREAKS_PER_CHARS = 500  # <1 break per 500 chars → degraded
_MAX_NON_ALPHA_RATIO = 0.20  # >20% non-alphanumeric → degraded

# Sentence pattern: starts with uppercase, ends with sentence-ending punctuation
_SENTENCE_RE = re.compile(r"[A-Z][^.!?]*[.!?]")

# Common punctuation that should NOT count as "non-alphanumeric junk"
_NORMAL_PUNCT = set(" \t\n\r.,;:!?'\"-()[]{}/#@&*+=<>|~`^%$_\\")


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

    details = {
        "content_length": content_length,
        "alpha_ratio": round(alpha_ratio, 3),
        "sentence_count": sentence_count,
        "reasons": reasons,
    }

    if not reasons:
        return {"quality": "ok", "quality_details": details}

    # Empty if basically no real content
    if content_length < 50 or (alpha_ratio < 0.1 and sentence_count == 0):
        return {"quality": "empty", "quality_details": details}

    return {"quality": "degraded", "quality_details": details}


def check_content_mismatch(text: str, title: str = "", authors: list[str] | None = None) -> dict:
    """Check if extracted text plausibly matches expected metadata.

    Looks for title keywords and author surnames in the text. If zero matches
    are found, the content is likely from the wrong paper (e.g., wrong PDF
    retrieved from a mirror).

    Returns:
        {"mismatched": bool, "title_hits": int, "author_hits": int, "reason": str}
    """
    if not text or (not title and not authors):
        return {"mismatched": False, "title_hits": 0, "author_hits": 0, "reason": ""}

    text_lower = text[:20000].lower()  # check first ~20k chars for speed

    # Extract meaningful title keywords (3+ chars, skip stopwords)
    _STOPWORDS = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was",
        "were", "been", "have", "has", "had", "its", "not", "but", "can",
        "may", "how", "what", "which", "who", "all", "any", "than", "into",
        "our", "their", "between", "about", "more", "also", "does", "new",
        "through", "during", "based", "using", "study", "research", "analysis",
    }
    title_words = [
        w for w in re.sub(r"[^a-z0-9\s]", " ", title.lower()).split()
        if len(w) >= 3 and w not in _STOPWORDS
    ] if title else []
    title_hits = sum(1 for w in title_words if w in text_lower) if title_words else 0

    # Check author surnames (last name before comma, or last word)
    author_hits = 0
    if authors:
        for author in authors[:5]:  # check first 5 authors
            parts = author.split(",")
            surname = parts[0].strip().lower() if parts else ""
            if surname and len(surname) >= 3 and surname in text_lower:
                author_hits += 1

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

    reason = ""
    if mismatched:
        reason = (
            f"content may be from wrong paper: "
            f"0/{len(title_words)} title keywords and 0/{len(authors or [])} author surnames found in text"
        )

    return {
        "mismatched": mismatched,
        "title_hits": title_hits,
        "author_hits": author_hits,
        "reason": reason,
    }
