"""Tests for the deduplicate-findings subcommand."""

import json
import os

from helpers import init_session, run_state, STATE_PY


def _log_finding(session_dir, text, sources, question):
    """Log a finding and return its ID."""
    _, data = run_state(
        "log-finding",
        "--text", text,
        "--sources", sources,
        "--question", question,
        "--session-dir", session_dir,
    )
    return data["results"]["id"]


def _get_findings(session_dir):
    """Return all findings from the summary."""
    _, data = run_state("summary", "--session-dir", session_dir)
    return data["results"]["findings"]


class TestDeduplicateFindings:
    def test_high_overlap_same_sources_merged(self, tmp_path):
        """Two findings with >70% token overlap and shared sources are merged."""
        sd = str(tmp_path / "session")
        init_session(sd)

        _log_finding(sd,
            "Categorical perception shows a sharp boundary at the 60% morph level with significant drop in likability",
            "src-001,src-003",
            "Q1: What mechanisms drive the uncanny valley?")
        _log_finding(sd,
            "Categorical perception demonstrates a sharp boundary at the 60% morph level with a significant decrease in likability ratings",
            "src-001,src-003",
            "Q4: How does categorical perception relate to the uncanny valley?")

        result, data = run_state("deduplicate-findings", "--session-dir", sd)
        assert result.returncode == 0
        assert data["results"]["original"] == 2
        assert data["results"]["merged"] == 1
        assert data["results"]["remaining"] == 1

        # Verify the surviving finding has the also_relevant_to annotation
        findings = _get_findings(sd)
        assert len(findings) == 1
        assert "Also relevant to:" in findings[0]["text"]

    def test_low_overlap_not_merged(self, tmp_path):
        """Two findings with <70% token overlap are not merged even with shared sources."""
        sd = str(tmp_path / "session")
        init_session(sd)

        _log_finding(sd,
            "The uncanny valley effect is driven by categorical perception at perceptual boundaries",
            "src-001,src-003",
            "Q1: What mechanisms drive the uncanny valley?")
        _log_finding(sd,
            "fMRI studies reveal increased amygdala activation during exposure to near-human faces compared to clearly robotic or clearly human faces",
            "src-001,src-003",
            "Q4: What neural correlates underlie the uncanny valley?")

        result, data = run_state("deduplicate-findings", "--session-dir", sd)
        assert result.returncode == 0
        assert data["results"]["original"] == 2
        assert data["results"]["merged"] == 0
        assert data["results"]["remaining"] == 2

        findings = _get_findings(sd)
        assert len(findings) == 2

    def test_different_sources_not_merged(self, tmp_path):
        """Two findings with similar text but no overlapping sources are not merged."""
        sd = str(tmp_path / "session")
        init_session(sd)

        _log_finding(sd,
            "Categorical perception shows a sharp boundary at the 60% morph level with significant drop in likability",
            "src-001,src-003",
            "Q1: What mechanisms drive the uncanny valley?")
        _log_finding(sd,
            "Categorical perception shows a sharp boundary at the 60% morph level with significant drop in likability",
            "src-005,src-007",
            "Q4: How does categorical perception relate to the uncanny valley?")

        result, data = run_state("deduplicate-findings", "--session-dir", sd)
        assert result.returncode == 0
        assert data["results"]["merged"] == 0
        assert data["results"]["remaining"] == 2

    def test_keeper_has_more_sources(self, tmp_path):
        """When merging, the finding with more source citations is kept."""
        sd = str(tmp_path / "session")
        init_session(sd)

        _log_finding(sd,
            "Categorical perception shows a sharp boundary at the 60% morph level with significant drop in likability",
            "src-001",
            "Q1: What mechanisms?")
        _log_finding(sd,
            "Categorical perception shows a sharp boundary at the 60% morph level with significant drop in likability ratings",
            "src-001,src-003,src-005",
            "Q4: How does categorical perception work?")

        run_state("deduplicate-findings", "--session-dir", sd)

        findings = _get_findings(sd)
        assert len(findings) == 1
        # The keeper should be the one with 3 sources
        sources = findings[0]["sources"]
        if isinstance(sources, str):
            sources = json.loads(sources)
        assert len(sources) == 3

    def test_no_findings_returns_zeros(self, tmp_path):
        """With no findings, dedup returns all zeros."""
        sd = str(tmp_path / "session")
        init_session(sd)

        result, data = run_state("deduplicate-findings", "--session-dir", sd)
        assert result.returncode == 0
        assert data["results"]["original"] == 0
        assert data["results"]["merged"] == 0
        assert data["results"]["remaining"] == 0

    def test_custom_threshold(self, tmp_path):
        """Custom threshold changes merge behavior."""
        sd = str(tmp_path / "session")
        init_session(sd)

        # These have moderate overlap — would not merge at 0.7 but would at 0.4
        _log_finding(sd,
            "The uncanny valley effect is driven by categorical perception at perceptual boundaries between human and nonhuman",
            "src-001,src-003",
            "Q1: Mechanisms?")
        _log_finding(sd,
            "Categorical perception at perceptual boundaries underlies eeriness responses to near-human agents and robots",
            "src-001,src-003",
            "Q4: Perception?")

        # First try with default threshold
        result, data = run_state("deduplicate-findings", "--session-dir", sd)
        default_merged = data["results"]["merged"]

        if default_merged == 0:
            # Re-init and re-log for the low threshold test
            sd2 = str(tmp_path / "session2")
            init_session(sd2)
            _log_finding(sd2,
                "The uncanny valley effect is driven by categorical perception at perceptual boundaries between human and nonhuman",
                "src-001,src-003",
                "Q1: Mechanisms?")
            _log_finding(sd2,
                "Categorical perception at perceptual boundaries underlies eeriness responses to near-human agents and robots",
                "src-001,src-003",
                "Q4: Perception?")
            result2, data2 = run_state("deduplicate-findings", "--threshold", "0.3", "--session-dir", sd2)
            assert data2["results"]["merged"] == 1
