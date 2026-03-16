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

    # Detect raw PDF bytes stored as text (e.g., PDF fetched via web and
    # saved with .md extension without conversion)
    if text[:4] == "%PDF":
        return {
            "quality": "degraded",
            "quality_details": {
                "content_length": len(text),
                "alpha_ratio": 0.0,
                "sentence_count": 0,
                "reasons": ["pdf_binary_as_text"],
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

    # 7. Paywall abstract stub detector: catches pages that pass quality
    # checks because they include the abstract as real text, but are actually
    # paywall landing pages. Many Springer/Wiley pages pass checks 1-5
    # because their abstracts have enough sentences, alpha chars, and length.
    # Scan the FULL text for paywall markers (not just first 50 lines).
    paywall_stub = False
    if not paywall_hit and content_length < 2000 and not reasons:
        full_lower = check_text.lower()
        for marker in _PAYWALL_MARKERS:
            if marker.lower() in full_lower:
                paywall_stub = True
                paywall_hit = f"stub: {marker}"
                break

    details = {
        "content_length": content_length,
        "alpha_ratio": round(alpha_ratio, 3),
        "sentence_count": sentence_count,
        "reasons": reasons,
    }

    # Paywall pages get their own quality label so downstream can distinguish
    # access-gate pages from genuinely degraded conversions.
    if paywall_hit:
        label = "paywall_stub" if paywall_stub else "paywall_page"
        details["reasons"] = reasons + [f"{label} ({paywall_hit})"]
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


def _extract_candidate_title(text: str) -> str:
    """Extract the document's actual title from the first few lines."""
    first_block = text[:500]
    first_lines = [ln.strip() for ln in first_block.split("\n") if ln.strip()]
    if not first_lines:
        return ""
    candidate = first_lines[0]
    if len(first_lines) > 1 and len(first_lines[0]) < 30:
        # Short first line might be a journal name — combine first two
        candidate = first_lines[0] + " " + first_lines[1]
    return candidate


def check_content_mismatch(
    text: str,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    brief_keywords: list[str] | None = None,
) -> dict:
    """Check if extracted text plausibly matches expected metadata.

    Uses a composite scoring model: each signal (title keywords, author
    surnames, abstract overlap, brief keywords, title-to-title) produces
    a 0-1 score. The weighted average determines the match. This replaces
    the old conjunctive gate logic where ALL gates had to fail — that was
    too lenient because a paper sharing a few generic keywords ("child",
    "development") would pass even when completely off-topic.

    Returns:
        {"mismatched": bool, "match_score": float,
         "scores": {"title_rate": float, "author_rate": float,
                    "abstract_overlap": float|None, "brief_rate": float|None,
                    "title_to_title": float|None},
         "title_hits": int, "author_hits": int,
         "abstract_overlap": float|None, "reason": str}
    """
    if not text or (not title and not authors):
        return {"mismatched": False, "match_score": 1.0,
                "scores": {"title_rate": 1.0, "author_rate": 1.0,
                           "abstract_overlap": None, "brief_rate": None,
                           "title_to_title": None},
                "title_hits": 0, "author_hits": 0,
                "abstract_overlap": None, "reason": ""}

    text_lower = text[:20000].lower()  # check first ~20k chars for speed

    # --- Signal 1: Title keyword hit rate ---
    title_words = _extract_keywords(title) if title else []
    title_hits = sum(1 for w in title_words if w in text_lower) if title_words else 0
    title_rate = (title_hits / len(title_words)) if title_words else 1.0

    # --- Signal 2: Author surname presence ---
    first_page_lower = text[:3000].lower()
    author_hits = 0
    author_first_page_hits = 0
    author_count = 0
    if authors:
        for author in authors[:5]:
            parts = author.split(",")
            surname = parts[0].strip().lower() if parts else ""
            if surname and len(surname) >= 3:
                author_count += 1
                if surname in text_lower:
                    author_hits += 1
                if surname in first_page_lower:
                    author_first_page_hits += 1
    author_rate = (author_hits / author_count) if author_count else 1.0
    # Penalize when authors appear in text but not on first page —
    # legitimate papers almost always list authors on page 1.
    if author_count and author_hits > 0 and author_first_page_hits == 0:
        author_rate *= 0.3  # significant penalty

    # --- Signal 3: Abstract keyword overlap ---
    abstract_overlap = None
    if abstract and len(abstract) >= 50:
        abstract_kws = _extract_keywords(abstract)
        seen = set()
        unique_kws = []
        for kw in sorted(abstract_kws, key=len, reverse=True):
            if kw not in seen:
                seen.add(kw)
                unique_kws.append(kw)
        abstract_kws = unique_kws[:10]
        if abstract_kws:
            text_check = text_lower[:15000]
            hits = sum(1 for kw in abstract_kws if kw in text_check)
            abstract_overlap = hits / len(abstract_kws)

    # --- Signal 4: Brief keyword presence ---
    brief_rate = None
    if brief_keywords:
        text_head = text[:5000].lower()
        brief_hits = sum(1 for kw in brief_keywords if kw.lower() in text_head)
        brief_rate = brief_hits / len(brief_keywords)

    # --- Signal 5: Title-to-title comparison ---
    # Strongest single signal — compare extracted document title against
    # expected title. A food/nutrition paper won't have any overlap with
    # "Child Temperament Questionnaire validation" in its actual title.
    title_to_title = None
    if title and title_words:
        candidate_title = _extract_candidate_title(text)
        if candidate_title:
            candidate_kws = _extract_keywords(candidate_title)
            expected_kws = set(title_words)
            if candidate_kws and expected_kws:
                overlap = sum(1 for w in candidate_kws if w in expected_kws)
                title_to_title = overlap / max(len(candidate_kws), len(expected_kws))

    # --- Composite score ---
    # Weighted average of available signals. Weights reflect diagnostic value:
    # title-to-title is the strongest single indicator; abstract overlap is
    # strong for topic matching; title keywords and authors are supporting.
    weights = []
    scores = []
    if title_words:
        weights.append(2.0)
        scores.append(title_rate)
    if author_count:
        weights.append(1.5)
        scores.append(author_rate)
    if abstract_overlap is not None:
        weights.append(2.5)
        scores.append(abstract_overlap)
    if brief_rate is not None:
        weights.append(2.0)
        scores.append(brief_rate)
    if title_to_title is not None:
        weights.append(3.0)
        scores.append(title_to_title)

    match_score = sum(w * s for w, s in zip(weights, scores, strict=False)) / sum(weights) if weights else 1.0

    # Threshold: flag as mismatched when composite score is low.
    # 0.3 catches papers that share a few generic keywords but are clearly
    # off-topic, while avoiding false positives on legitimate papers that
    # happen to have unusual introductions or reformatted titles.
    _MISMATCH_THRESHOLD = 0.3
    mismatched = match_score < _MISMATCH_THRESHOLD

    # Hard fail: title-to-title overlap below 0.5 is a strong standalone
    # signal even if other scores are moderate (e.g., shared generic terms
    # boost title_rate and brief_rate but the actual document title is wrong).
    # Only hard-fail when title keyword rate is also weak — avoids
    # false positives from reformatted/abbreviated titles in the PDF.
    if not mismatched and title_to_title is not None and title_to_title < 0.15 and title_rate < 0.5:
        mismatched = True

    score_details = {
        "title_rate": round(title_rate, 3),
        "author_rate": round(author_rate, 3),
        "abstract_overlap": round(abstract_overlap, 3) if abstract_overlap is not None else None,
        "brief_rate": round(brief_rate, 3) if brief_rate is not None else None,
        "title_to_title": round(title_to_title, 3) if title_to_title is not None else None,
    }

    reason = ""
    if mismatched:
        parts = []
        parts.append(f"composite match score {match_score:.2f} < {_MISMATCH_THRESHOLD}")
        parts.append(
            f"{title_hits}/{len(title_words)} title keywords, "
            f"{author_hits}/{author_count} authors"
        )
        if abstract_overlap is not None:
            parts.append(f"abstract overlap {abstract_overlap:.0%}")
        if brief_rate is not None:
            parts.append(f"brief keyword rate {brief_rate:.0%}")
        if title_to_title is not None:
            parts.append(f"title-to-title overlap {title_to_title:.0%}")
        reason = f"content may be from wrong paper: {', '.join(parts)}"

    return {
        "mismatched": mismatched,
        "match_score": round(match_score, 3),
        "scores": score_details,
        "title_hits": title_hits,
        "author_hits": author_hits,
        "abstract_overlap": abstract_overlap,
        "reason": reason,
    }
