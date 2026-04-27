"""Tests for metrics.py evidence metrics."""

import json
import os
import subprocess
import sys

from helpers import init_session as _init_session, run_state as _run_state, write_json_file as _write_json_file

METRICS_PY = os.path.join(os.path.dirname(__file__), os.pardir, "skills", "reflect", "scripts", "metrics.py")
STATE_PY = os.path.join(os.path.dirname(__file__), os.pardir, "skills", "deep-research", "scripts", "state.py")


def _run_metrics(session_dir):
    result = subprocess.run(
        [sys.executable, METRICS_PY, session_dir],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout) if result.stdout.strip() else {}
    return result, data


def _setup_session_with_source(tmp_path):
    """Create a session with one source. Returns session_dir."""
    session_dir = str(tmp_path / "session")
    _init_session(session_dir)

    source_manifest = {
        "title": "Test Source",
        "doi": "10.1234/test",
        "url": "https://example.com/test",
        "provider": "semantic_scholar",
        "type": "academic",
        "citation_count": 10,
    }
    json_file = _write_json_file(tmp_path, source_manifest, "source.json")
    _run_state("add-source", "--session-dir", session_dir, "--from-json", json_file)
    return session_dir


def _add_evidence(tmp_path, session_dir, source_id, units):
    """Add evidence units to a session."""
    manifest = {
        "source_id": source_id,
        "units": units,
    }
    json_file = _write_json_file(tmp_path, manifest, "evidence.json")
    _run_state("add-evidence", "--session-dir", session_dir, "--from-json", json_file)


class TestEvidenceMetricsWithoutTables:
    def test_no_evidence_returns_zeros(self, tmp_path):
        """Session with no evidence units returns zero evidence metrics."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        result, data = _run_metrics(session_dir)
        assert result.returncode == 0
        m = data["metrics"]
        assert m["evidence_units_total"] == 0
        assert m["findings_with_evidence"] == 0
        assert m["findings_without_evidence"] == 0
        assert m["evidence_json_files"] == 0
        assert m["evidence_link_count"] == 0

    def test_findings_arent_penalized_before_evidence_is_used(self, tmp_path):
        """Findings stay neutral when the evidence layer was never used."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        _run_state(
            "log-finding", "--session-dir", session_dir,
            "--text", "Finding before evidence rollout", "--sources", "src-001", "--question", "Q1: test?",
        )

        result, data = _run_metrics(session_dir)
        assert result.returncode == 0
        m = data["metrics"]
        assert m["evidence_units_total"] == 0
        assert m["findings_with_evidence"] == 0
        assert m["findings_without_evidence"] == 0


class TestEvidenceMetricsWithUnits:
    def test_evidence_counts(self, tmp_path):
        """Evidence units produce correct counts and breakdowns."""
        session_dir = _setup_session_with_source(tmp_path)

        _add_evidence(tmp_path, session_dir, "src-001", [
            {
                "id": "ev-001",
                "claim_text": "Test result claim",
                "claim_type": "result",
                "relation": "supports",
                "evidence_strength": "strong",
                "provenance_type": "note",
                "primary_question_id": "Q1",
                "line_start": 10,
                "line_end": 20,
                "quote": "test quote",
            },
            {
                "id": "ev-002",
                "claim_text": "Test method claim",
                "claim_type": "method",
                "relation": "supports",
                "evidence_strength": "moderate",
                "provenance_type": "note",
                "primary_question_id": "Q2",
            },
        ])

        result, data = _run_metrics(session_dir)
        assert result.returncode == 0
        m = data["metrics"]

        assert m["evidence_units_total"] == 2
        assert m["evidence_units_by_claim_type"] == {"result": 1, "method": 1}
        assert m["evidence_units_by_question"] == {"Q1": 1, "Q2": 1}
        assert m["evidence_units_by_source"] == {"src-001": 2}
        assert m["evidence_units_with_spans"] == 1
        assert m["evidence_units_avg_per_source"] == 2.0

    def test_shared_question_ids_count_for_each_question(self, tmp_path):
        """Evidence counts should include all linked question_ids, not just the primary."""
        session_dir = _setup_session_with_source(tmp_path)

        _add_evidence(tmp_path, session_dir, "src-001", [
            {
                "id": "ev-001",
                "claim_text": "Shared claim",
                "claim_type": "result",
                "relation": "supports",
                "evidence_strength": "strong",
                "provenance_type": "note",
                "primary_question_id": "Q2",
                "question_ids": ["Q1", "Q2"],
            },
        ])

        result, data = _run_metrics(session_dir)
        assert result.returncode == 0
        m = data["metrics"]
        assert m["evidence_units_by_question"] == {"Q1": 1, "Q2": 1}

    def test_evidence_json_files_counted(self, tmp_path):
        """Evidence JSON files in evidence/ directory are counted."""
        session_dir = _setup_session_with_source(tmp_path)

        # Create evidence directory and a file
        evidence_dir = os.path.join(session_dir, "evidence")
        os.makedirs(evidence_dir, exist_ok=True)
        with open(os.path.join(evidence_dir, "src-001.json"), "w") as f:
            json.dump({"units": []}, f)

        _, data = _run_metrics(session_dir)
        m = data["metrics"]
        assert m["evidence_json_files"] == 1


class TestEvidenceFindingLinks:
    def test_findings_with_and_without_evidence(self, tmp_path):
        """Linked and unlinked findings are counted correctly."""
        session_dir = _setup_session_with_source(tmp_path)

        # Add evidence
        _add_evidence(tmp_path, session_dir, "src-001", [
            {
                "id": "ev-001",
                "claim_text": "Linked claim",
                "claim_type": "result",
                "relation": "supports",
                "evidence_strength": "strong",
                "provenance_type": "note",
            },
        ])

        # Add two findings
        _run_state(
            "log-finding", "--session-dir", session_dir,
            "--text", "Linked finding", "--sources", "src-001", "--question", "Q1: test?",
        )
        _run_state(
            "log-finding", "--session-dir", session_dir,
            "--text", "Unlinked finding", "--sources", "src-001", "--question", "Q1: test?",
        )

        # Link first finding to evidence
        _run_state(
            "link-finding-evidence", "--session-dir", session_dir,
            "--finding-id", "finding-1", "--evidence-ids", "ev-0001",
        )

        result, data = _run_metrics(session_dir)
        assert result.returncode == 0
        m = data["metrics"]
        assert m["findings_with_evidence"] == 1
        assert m["findings_without_evidence"] == 1
        assert m["evidence_link_count"] == 1


class TestMetricsRegression:
    def test_existing_metrics_still_present(self, tmp_path):
        """Evidence metrics don't break existing metric categories."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        result, data = _run_metrics(session_dir)
        m = data["metrics"]

        # Existing keys still present
        assert "searches_total" in m
        assert "sources_total" in m
        assert "findings_total" in m
        assert "report_exists" in m
        assert "journal_exists" in m

        # New evidence keys present
        assert "evidence_units_total" in m
        assert "findings_with_evidence" in m


class TestSourceFlagMetrics:
    def test_source_quality_and_caution_metrics(self, tmp_path):
        """Reflection metrics include canonical quality counts and caution flags."""
        session_dir = _setup_session_with_source(tmp_path)

        _run_state(
            "set-quality", "--session-dir", session_dir,
            "--id", "src-001", "--quality", "mismatched",
        )
        _run_state(
            "set-source-flag", "--session-dir", session_dir,
            "--source-id", "src-001",
            "--flag", "undated",
            "--rationale", "No publication date available.",
        )

        result, data = _run_metrics(session_dir)
        assert result.returncode == 0
        m = data["metrics"]
        assert m["sources_by_access_quality"]["title_content_mismatch"] == 1
        assert m["source_caution_flags_total"] == 1
        assert m["source_caution_flags_by_flag"] == {"undated": 1}
        assert m["source_caution_flags_by_scope"] == {"run": 1}
        assert m["sources_with_caution_flags"] == 1
