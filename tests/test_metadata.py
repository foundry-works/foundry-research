"""Tests for metadata normalization, author formatting, year extraction, and JSON I/O."""

from _shared.metadata import (
    PAPER_SCHEMA,
    _extract_crossref_year,
    _is_empty,
    _parse_year,
    _reformat_author,
    merge_metadata,
    normalize_paper,
    read_source_metadata,
    write_source_metadata,
)
from _shared.doi_utils import extract_doi


# ---------------------------------------------------------------------------
# 1. Author format normalization
# ---------------------------------------------------------------------------

class TestAuthorFormats:
    """Author names are converted to 'Last, First' across providers."""

    def test_first_last_to_last_first(self):
        assert _reformat_author("Alice Smith") == "Smith, Alice"

    def test_already_last_first_unchanged(self):
        assert _reformat_author("Smith, Alice") == "Smith, Alice"

    def test_three_part_name(self):
        """Middle names stay with given names."""
        assert _reformat_author("Alice B. Smith") == "Smith, Alice B."

    def test_single_name_unchanged(self):
        assert _reformat_author("Aristotle") == "Aristotle"

    def test_empty_string_unchanged(self):
        assert _reformat_author("") == ""

    def test_semantic_scholar_author_list(self):
        """Semantic Scholar provides {"name": "First Last"} dicts."""
        raw = {
            "title": "Test",
            "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
        }
        paper = normalize_paper(raw, "semantic_scholar")
        assert paper["authors"] == ["Smith, Alice", "Jones, Bob"]

    def test_crossref_family_given_format(self):
        """Crossref provides {"family": "Last", "given": "First"}."""
        raw = {
            "title": ["Test Paper"],
            "author": [
                {"family": "Smith", "given": "Alice"},
                {"family": "Jones", "given": "Bob"},
            ],
        }
        paper = normalize_paper(raw, "crossref")
        assert paper["authors"] == ["Smith, Alice", "Jones, Bob"]

    def test_openalex_display_name(self):
        """OpenAlex provides display_name in authorships."""
        raw = {
            "title": "Test",
            "authorships": [
                {"author": {"display_name": "Alice Smith"}},
                {"author": {"display_name": "Bob Jones"}},
            ],
        }
        paper = normalize_paper(raw, "openalex")
        assert paper["authors"] == ["Smith, Alice", "Jones, Bob"]

    def test_generic_provider_authors(self):
        """Generic provider path handles author list normalization."""
        raw = {"title": "Test", "authors": ["Alice Smith", "Bob Jones"]}
        paper = normalize_paper(raw, "web")
        assert paper["authors"] == ["Smith, Alice", "Jones, Bob"]


# ---------------------------------------------------------------------------
# 2. Year extraction from various formats
# ---------------------------------------------------------------------------

class TestYearExtraction:
    def test_integer_year(self):
        assert _parse_year(2024) == 2024

    def test_iso_date_string(self):
        assert _parse_year("2024-03-15") == 2024

    def test_year_only_string(self):
        assert _parse_year("2024") == 2024

    def test_year_month_string(self):
        assert _parse_year("2024 Jan") == 2024

    def test_month_year_string(self):
        assert _parse_year("Jan 2024") == 2024

    def test_float_year(self):
        assert _parse_year(2024.0) == 2024

    def test_none_returns_zero(self):
        assert _parse_year(None) == 0

    def test_out_of_range_returns_zero(self):
        assert _parse_year(1800) == 0
        assert _parse_year(2200) == 0

    def test_empty_string_returns_zero(self):
        assert _parse_year("") == 0

    def test_crossref_date_parts(self):
        raw = {"published-print": {"date-parts": [[2024, 3, 15]]}}
        assert _extract_crossref_year(raw) == 2024

    def test_crossref_fallback_to_issued(self):
        raw = {"issued": {"date-parts": [[2023]]}}
        assert _extract_crossref_year(raw) == 2023

    def test_crossref_no_date(self):
        assert _extract_crossref_year({}) == 0


# ---------------------------------------------------------------------------
# 3. DOI in various fields
# ---------------------------------------------------------------------------

class TestDOIFields:
    def test_doi_normalized_in_normalize_paper(self):
        """DOI is normalized regardless of provider."""
        raw = {"title": "Test", "doi": "https://doi.org/10.1234/TEST"}
        paper = normalize_paper(raw, "pubmed")
        assert paper["doi"] == "10.1234/test"

    def test_semantic_scholar_external_ids(self):
        """Semantic Scholar DOI from externalIds."""
        raw = {
            "title": "Test",
            "externalIds": {"DOI": "10.1234/PAPER"},
        }
        paper = normalize_paper(raw, "semantic_scholar")
        assert paper["doi"] == "10.1234/paper"

    def test_openalex_doi_url_stripped(self):
        """OpenAlex provides DOI as full URL."""
        raw = {"title": "Test", "doi": "https://doi.org/10.5678/OA-TEST"}
        paper = normalize_paper(raw, "openalex")
        assert paper["doi"] == "10.5678/oa-test"

    def test_crossref_doi_field(self):
        raw = {"title": ["Test"], "DOI": "10.9999/CR.Test"}
        paper = normalize_paper(raw, "crossref")
        assert paper["doi"] == "10.9999/cr.test"

    def test_extract_doi_from_text(self):
        assert extract_doi("See https://doi.org/10.1234/foo.bar for details") == "10.1234/foo.bar"

    def test_extract_doi_returns_none_for_no_match(self):
        assert extract_doi("No DOI here") is None


# ---------------------------------------------------------------------------
# 4. Unicode handling
# ---------------------------------------------------------------------------

class TestUnicodeHandling:
    def test_unicode_author_name(self):
        result = _reformat_author("José García")
        assert result == "García, José"

    def test_unicode_title_preserved(self):
        raw = {"title": "Über die Quantenmechanik", "authors": []}
        paper = normalize_paper(raw, "pubmed")
        assert paper["title"] == "Über die Quantenmechanik"

    def test_unicode_round_trip_json(self, tmp_path):
        """Unicode characters survive write→read cycle."""
        metadata = {
            "title": "日本語のテスト",
            "authors": ["Müller, André", "García, José"],
            "abstract": "Résumé with ñ and ü characters",
        }
        write_source_metadata(str(tmp_path), "src-001", metadata)
        loaded = read_source_metadata(str(tmp_path), "src-001")
        assert loaded["title"] == metadata["title"]
        assert loaded["authors"] == metadata["authors"]
        assert loaded["abstract"] == metadata["abstract"]

    def test_ensure_ascii_false_in_output(self, tmp_path):
        """Written JSON preserves non-ASCII (no \\uXXXX escapes)."""
        metadata = {"title": "Ölçüm"}
        write_source_metadata(str(tmp_path), "src-002", metadata)
        raw_text = (tmp_path / "src-002.json").read_text(encoding="utf-8")
        assert "Ölçüm" in raw_text
        assert "\\u" not in raw_text


# ---------------------------------------------------------------------------
# 5. Round-trip JSON serialization
# ---------------------------------------------------------------------------

class TestRoundTripJSON:
    def test_write_then_read_all_fields(self, tmp_path):
        """All PAPER_SCHEMA fields survive write→read."""
        paper = {k: type(v)() if isinstance(v, list | dict) else v for k, v in PAPER_SCHEMA.items()}
        paper["title"] = "Test Paper"
        paper["authors"] = ["Smith, Alice", "Jones, Bob"]
        paper["year"] = 2024
        paper["doi"] = "10.1234/test"
        paper["citation_count"] = 42
        paper["is_retracted"] = False
        paper["publication_types"] = ["journal-article"]

        write_source_metadata(str(tmp_path), "src-rt", paper)
        loaded = read_source_metadata(str(tmp_path), "src-rt")

        for key in PAPER_SCHEMA:
            assert loaded[key] == paper[key], f"Field '{key}' mismatch"

    def test_read_missing_file_returns_empty_dict(self, tmp_path):
        result = read_source_metadata(str(tmp_path), "nonexistent")
        assert result == {}

    def test_read_malformed_json_returns_empty_dict(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{", encoding="utf-8")
        result = read_source_metadata(str(tmp_path), "bad")
        assert result == {}


# ---------------------------------------------------------------------------
# 6. Merge metadata with provider precedence
# ---------------------------------------------------------------------------

class TestMergeMetadata:
    def test_fill_empty_field(self):
        existing = {"title": "Test", "venue": "", "provider": "pubmed"}
        new = {"venue": "Nature", "provider": "crossref"}
        result = merge_metadata(existing, new)
        assert result["venue"] == "Nature"

    def test_never_overwrite_with_empty(self):
        existing = {"title": "Good Title", "venue": "Nature", "provider": "crossref"}
        new = {"venue": "", "provider": "pubmed"}
        result = merge_metadata(existing, new)
        assert result["venue"] == "Nature"

    def test_higher_priority_overwrites(self):
        """Crossref has higher priority than pubmed for venue."""
        existing = {"venue": "Old Venue", "provider": "pubmed"}
        new = {"venue": "Nature", "provider": "crossref"}
        result = merge_metadata(existing, new)
        assert result["venue"] == "Nature"

    def test_lower_priority_does_not_overwrite(self):
        existing = {"venue": "Nature", "provider": "crossref"}
        new = {"venue": "Other", "provider": "pubmed"}
        result = merge_metadata(existing, new)
        assert result["venue"] == "Nature"

    def test_id_never_overwritten(self):
        existing = {"id": "original", "provider": "pubmed"}
        new = {"id": "new-id", "provider": "crossref"}
        result = merge_metadata(existing, new)
        assert result["id"] == "original"

    def test_is_empty_helper(self):
        assert _is_empty(None) is True
        assert _is_empty("") is True
        assert _is_empty("  ") is True
        assert _is_empty([]) is True
        assert _is_empty(0) is True
        assert _is_empty("text") is False
        assert _is_empty(42) is False
        assert _is_empty(["a"]) is False
