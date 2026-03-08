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
