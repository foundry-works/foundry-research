"""Tests for consistent JSON envelope structure across provider output."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))

from _shared.output import error_response, success_response


# ---------------------------------------------------------------------------
# 1. JSON envelope structure
# ---------------------------------------------------------------------------

class TestJSONEnvelopeStructure:
    def test_success_envelope_has_required_keys(self, capsys):
        """Success response includes status, results, errors, total_results."""
        success_response([{"title": "Paper"}])
        output = json.loads(capsys.readouterr().out)

        assert output["status"] == "ok"
        assert "results" in output
        assert "errors" in output
        assert "total_results" in output

    def test_success_envelope_errors_empty(self, capsys):
        """Success response always has empty errors list."""
        success_response([])
        output = json.loads(capsys.readouterr().out)
        assert output["errors"] == []

    def test_success_envelope_extra_keys_merged(self, capsys):
        """Extra kwargs are merged into envelope."""
        success_response([], provider="semantic_scholar", query="test")
        output = json.loads(capsys.readouterr().out)
        assert output["provider"] == "semantic_scholar"
        assert output["query"] == "test"

    def test_error_envelope_has_required_keys(self):
        """Error response includes status, results, errors, total_results."""
        with pytest.raises(SystemExit):
            error_response(["Something failed"])

    def test_error_envelope_structure(self, capsys):
        """Error envelope has correct structure when partial results exist."""
        with pytest.raises(SystemExit) as exc_info:
            error_response(["API timeout"], partial_results=[{"title": "Partial"}])

        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"
        assert output["errors"] == ["API timeout"]
        assert output["total_results"] == 1
        assert exc_info.value.code == 0  # partial success → exit 0

    def test_error_envelope_with_error_code(self, capsys):
        """Error code is included when provided."""
        with pytest.raises(SystemExit):
            error_response(["Rate limited"], error_code="rate_limited")

        output = json.loads(capsys.readouterr().out)
        assert output["error_code"] == "rate_limited"


# ---------------------------------------------------------------------------
# 2. Required fields present in all results
# ---------------------------------------------------------------------------

class TestRequiredFields:
    def test_total_results_auto_from_list_length(self, capsys):
        """total_results defaults to len(results) for lists."""
        success_response([1, 2, 3])
        output = json.loads(capsys.readouterr().out)
        assert output["total_results"] == 3

    def test_total_results_auto_from_dict(self, capsys):
        """total_results defaults to 1 for dict results."""
        success_response({"key": "value"})
        output = json.loads(capsys.readouterr().out)
        assert output["total_results"] == 1

    def test_total_results_explicit_override(self, capsys):
        """Explicit total_results overrides auto-calculation."""
        success_response([{"title": "One"}], total_results=100)
        output = json.loads(capsys.readouterr().out)
        assert output["total_results"] == 100

    def test_status_is_ok_for_success(self, capsys):
        success_response([])
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "ok"

    def test_status_is_error_for_failure(self, capsys):
        with pytest.raises(SystemExit):
            error_response(["fail"])
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"


# ---------------------------------------------------------------------------
# 3. Empty results handled gracefully
# ---------------------------------------------------------------------------

class TestEmptyResults:
    def test_empty_list_success(self, capsys):
        """Empty result list → valid success envelope with total_results=0."""
        success_response([])
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "ok"
        assert output["results"] == []
        assert output["total_results"] == 0

    def test_empty_list_with_provider_context(self, capsys):
        """Empty results still include provider context."""
        success_response([], provider="openalex", query="nonexistent topic", has_more=False)
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "ok"
        assert output["results"] == []
        assert output["provider"] == "openalex"
        assert output["has_more"] is False

    def test_empty_dict_success(self, capsys):
        """Empty dict result → valid envelope."""
        success_response({})
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "ok"
        assert output["results"] == {}
        assert output["total_results"] == 1  # dict → 1


# ---------------------------------------------------------------------------
# 4. API errors wrapped in error envelope
# ---------------------------------------------------------------------------

class TestAPIErrorEnvelope:
    def test_total_failure_exits_1(self):
        """Total failure (no partial results) exits with code 1."""
        with pytest.raises(SystemExit) as exc_info:
            error_response(["API returned 500"])
        assert exc_info.value.code == 1

    def test_partial_success_exits_0(self):
        """Partial results present → exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            error_response(["Timeout on page 3"], partial_results=[{"title": "P1"}, {"title": "P2"}])
        assert exc_info.value.code == 0

    def test_multiple_errors_in_list(self, capsys):
        """Multiple error messages are all preserved."""
        with pytest.raises(SystemExit):
            error_response(["Error 1", "Error 2", "Error 3"])
        output = json.loads(capsys.readouterr().out)
        assert len(output["errors"]) == 3

    def test_error_no_code_omits_key(self, capsys):
        """No error_code param → key absent from envelope."""
        with pytest.raises(SystemExit):
            error_response(["fail"])
        output = json.loads(capsys.readouterr().out)
        assert "error_code" not in output

    def test_error_partial_results_counted(self, capsys):
        """Partial results are counted in total_results."""
        with pytest.raises(SystemExit):
            error_response(["timeout"], partial_results=[{"a": 1}, {"b": 2}])
        output = json.loads(capsys.readouterr().out)
        assert output["total_results"] == 2

    def test_unicode_in_error_message(self, capsys):
        """Unicode in error messages is preserved."""
        with pytest.raises(SystemExit):
            error_response(["Fehler: ungültige Eingabe"])
        output = json.loads(capsys.readouterr().out)
        assert "ungültige" in output["errors"][0]
