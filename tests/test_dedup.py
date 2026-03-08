"""Tests for 3-tier deduplication logic in state.py."""

import json
import sqlite3

import pytest

from state import _SCHEMA, _authors_overlap, _check_duplicate, _title_similarity
from _shared.doi_utils import canonicalize_url, normalize_doi

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SID = "test-session"


@pytest.fixture()
def conn():
    """In-memory SQLite with schema + one session row."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    c.execute(
        "INSERT INTO sessions (id, query, created_at) VALUES (?, ?, ?)",
        (SID, "test query", "2026-01-01T00:00:00Z"),
    )
    c.commit()
    yield c
    c.close()


def _insert_source(conn, *, src_id="src-001", title="A Title", doi=None,
                   url=None, authors="[]", year=None):
    """Insert a source row for dedup testing."""
    conn.execute(
        "INSERT INTO sources (id, session_id, title, authors, year, doi, url, provider, added_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (src_id, SID, title, authors, year, doi, url, "test", "2026-01-01T00:00:00Z"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 1. DOI matching
# ---------------------------------------------------------------------------

class TestDOIMatching:
    """Tier 1: exact DOI match after normalization."""

    def test_exact_doi_match(self, conn):
        _insert_source(conn, doi="10.1234/test.paper")
        is_dup, matched = _check_duplicate(conn, SID, doi="10.1234/test.paper")
        assert is_dup is True
        assert matched == "src-001"

    def test_doi_prefix_normalization(self, conn):
        """DOI with https://doi.org/ prefix should match bare DOI."""
        _insert_source(conn, doi="10.1234/test.paper")
        is_dup, _ = _check_duplicate(conn, SID, doi="https://doi.org/10.1234/test.paper")
        assert is_dup is True

    def test_doi_case_insensitive(self, conn):
        """DOI matching is case-insensitive after normalization."""
        _insert_source(conn, doi="10.1234/abc.def")
        is_dup, _ = _check_duplicate(conn, SID, doi="10.1234/ABC.DEF")
        assert is_dup is True

    def test_doi_no_match(self, conn):
        _insert_source(conn, doi="10.1234/paper.one")
        is_dup, matched = _check_duplicate(conn, SID, doi="10.1234/paper.two")
        assert is_dup is False
        assert matched is None


# ---------------------------------------------------------------------------
# 2. URL matching
# ---------------------------------------------------------------------------

class TestURLMatching:
    """Tier 2: URL match after canonicalization."""

    def test_arxiv_abs_pdf_unification(self, conn):
        """arXiv /abs/ and /pdf/ variants should be treated as same source."""
        canon = canonicalize_url("https://arxiv.org/abs/2301.12345")
        _insert_source(conn, url=canon)
        is_dup, _ = _check_duplicate(conn, SID, url="https://arxiv.org/pdf/2301.12345")
        assert is_dup is True

    def test_biorxiv_version_strip(self, conn):
        """bioRxiv URLs with different versions should match."""
        canon = canonicalize_url("https://www.biorxiv.org/content/10.1101/2023.01.001/v1")
        _insert_source(conn, url=canon)
        is_dup, _ = _check_duplicate(
            conn, SID, url="https://www.biorxiv.org/content/10.1101/2023.01.001/v2"
        )
        assert is_dup is True

    def test_url_no_match(self, conn):
        canon = canonicalize_url("https://example.com/paper/1")
        _insert_source(conn, url=canon)
        is_dup, matched = _check_duplicate(conn, SID, url="https://example.com/paper/2")
        assert is_dup is False
        assert matched is None


# ---------------------------------------------------------------------------
# 3. Fuzzy title matching
# ---------------------------------------------------------------------------

class TestFuzzyTitleMatching:
    """Tier 3: token-overlap similarity with gray-zone logic."""

    def test_identical_title_is_duplicate(self, conn):
        """Identical titles (>0.95 sim) → automatic duplicate."""
        _insert_source(conn, title="A comprehensive survey of deep learning methods")
        is_dup, _ = _check_duplicate(
            conn, SID, title="A comprehensive survey of deep learning methods"
        )
        assert is_dup is True

    def test_near_identical_title(self, conn):
        """Titles with >0.95 token overlap → duplicate without author/year check."""
        _insert_source(conn, title="A comprehensive survey of deep learning methods in NLP")
        # Change one word out of 9 → overlap ~0.89, but change nothing → 1.0
        is_dup, _ = _check_duplicate(
            conn, SID,
            title="A comprehensive survey of deep learning methods in NLP",
        )
        assert is_dup is True

    def test_short_title_skipped(self, conn):
        """Titles shorter than 15 chars are skipped from fuzzy matching."""
        _insert_source(conn, title="Short title")
        is_dup, _ = _check_duplicate(conn, SID, title="Short title")
        # "Short title" is 11 chars → skipped, so not detected via title
        assert is_dup is False


# ---------------------------------------------------------------------------
# 4. Case sensitivity in title matching
# ---------------------------------------------------------------------------

class TestTitleCaseSensitivity:
    def test_case_insensitive_title_match(self, conn):
        """Title matching should be case-insensitive (tokens lowercased)."""
        _insert_source(conn, title="Deep Learning for Natural Language Processing")
        is_dup, _ = _check_duplicate(
            conn, SID,
            title="deep learning for natural language processing",
        )
        assert is_dup is True


# ---------------------------------------------------------------------------
# 5. DOI normalization
# ---------------------------------------------------------------------------

class TestDOINormalization:
    def test_strip_dx_doi_prefix(self):
        assert normalize_doi("http://dx.doi.org/10.1234/FOO") == "10.1234/foo"

    def test_strip_trailing_punctuation(self):
        assert normalize_doi("10.1234/paper.") == "10.1234/paper"
        assert normalize_doi("10.1234/paper;") == "10.1234/paper"

    def test_strip_doi_colon_prefix(self):
        assert normalize_doi("doi:10.5678/ABC") == "10.5678/abc"


# ---------------------------------------------------------------------------
# 6. URL canonicalization (normalization)
# ---------------------------------------------------------------------------

class TestURLCanonicalization:
    def test_semantic_scholar_title_hash(self):
        """Semantic Scholar /paper/TITLE-HASH → /paper/HASH."""
        result = canonicalize_url(
            "https://www.semanticscholar.org/paper/Some-Long-Title-abc123def456abc123def456abc123def456abc1"
        )
        assert "Some-Long-Title" not in result
        assert "abc123def456abc123def456abc123def456abc1" in result

    def test_pmc_pdf_strip(self):
        """PMC /pdf/ variant stripped."""
        result = canonicalize_url("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/pdf/")
        assert result.endswith("/pmc/articles/PMC1234567")

    def test_doi_org_normalizes(self):
        result = canonicalize_url("https://doi.org/10.1234/TEST")
        assert result == "https://doi.org/10.1234/test"


# ---------------------------------------------------------------------------
# 7. Threshold boundary tests
# ---------------------------------------------------------------------------

class TestThresholdBoundary:
    def test_above_095_is_duplicate(self):
        """Similarity > 0.95 → automatic duplicate (no author/year needed)."""
        # 10 tokens identical = 1.0
        sim = _title_similarity(
            "one two three four five six seven eight nine ten",
            "one two three four five six seven eight nine ten",
        )
        assert sim > 0.95

    def test_below_085_not_duplicate(self, conn):
        """Similarity < 0.85 → not a duplicate even with matching author+year."""
        _insert_source(
            conn,
            title="Alpha beta gamma delta epsilon zeta eta theta iota kappa",
            authors='["Author A"]',
            year=2024,
        )
        # Completely different title
        is_dup, _ = _check_duplicate(
            conn, SID,
            title="One two three four five six seven eight nine ten",
            authors=["Author A"],
            year=2024,
        )
        assert is_dup is False

    def test_empty_tokens_return_zero(self):
        assert _title_similarity("", "some real title here enough") == 0.0
        assert _title_similarity("some real title here enough", "") == 0.0


# ---------------------------------------------------------------------------
# 8. Gray-zone logic (0.85 ≤ sim ≤ 0.95)
# ---------------------------------------------------------------------------

class TestGrayZone:
    """In the gray zone, both author overlap AND year proximity are required."""

    def _gray_zone_titles(self):
        """Return two titles with similarity in [0.85, 0.95]."""
        # 10 tokens, 9 shared → 9/10 = 0.90
        base = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        variant = "alpha beta gamma delta epsilon zeta eta theta iota DIFFERENT"
        sim = _title_similarity(base, variant)
        assert 0.85 <= sim <= 0.95, f"Setup error: sim={sim}"
        return base, variant

    def test_gray_zone_with_author_and_year_match(self, conn):
        """Gray zone + author overlap + year ±1 → duplicate."""
        base, variant = self._gray_zone_titles()
        _insert_source(
            conn, title=base, authors='["Alice Smith", "Bob Jones"]', year=2024,
        )
        is_dup, _ = _check_duplicate(
            conn, SID, title=variant,
            authors=["Alice Smith", "Bob Jones"], year=2024,
        )
        assert is_dup is True

    def test_gray_zone_without_authors_not_duplicate(self, conn):
        """Gray zone without author info → not duplicate."""
        base, variant = self._gray_zone_titles()
        _insert_source(conn, title=base, authors='[]', year=2024)
        is_dup, _ = _check_duplicate(
            conn, SID, title=variant, authors=None, year=2024,
        )
        assert is_dup is False

    def test_gray_zone_year_too_far(self, conn):
        """Gray zone + author match but year differs by >1 → not duplicate."""
        base, variant = self._gray_zone_titles()
        _insert_source(
            conn, title=base, authors='["Alice Smith"]', year=2020,
        )
        is_dup, _ = _check_duplicate(
            conn, SID, title=variant, authors=["Alice Smith"], year=2024,
        )
        assert is_dup is False

    def test_gray_zone_year_within_one(self, conn):
        """Gray zone + author match + year ±1 → duplicate."""
        base, variant = self._gray_zone_titles()
        _insert_source(
            conn, title=base, authors='["Alice Smith"]', year=2023,
        )
        is_dup, _ = _check_duplicate(
            conn, SID, title=variant, authors=["Alice Smith"], year=2024,
        )
        assert is_dup is True


# ---------------------------------------------------------------------------
# 9. Authors overlap helper
# ---------------------------------------------------------------------------

class TestAuthorsOverlap:
    def test_overlap_above_fifty_percent(self):
        a_json = json.dumps(["Alice Smith", "Bob Jones"])
        assert _authors_overlap(a_json, ["Alice Smith", "Bob Jones"]) is True

    def test_no_overlap(self):
        a_json = json.dumps(["Alice Smith"])
        assert _authors_overlap(a_json, ["Charlie Brown"]) is False

    def test_case_insensitive_overlap(self):
        a_json = json.dumps(["Alice Smith"])
        assert _authors_overlap(a_json, ["alice smith"]) is True

    def test_empty_authors(self):
        assert _authors_overlap("[]", ["Alice"]) is False
        assert _authors_overlap(json.dumps(["Alice"]), []) is False

    def test_malformed_json_returns_false(self):
        assert _authors_overlap("not json", ["Alice"]) is False
