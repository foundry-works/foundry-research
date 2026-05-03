"""Tests for state.py schema initialization, persistence, concurrency, and ID generation."""

import json
import os
import sqlite3
import subprocess
import sys
import threading

from helpers import init_session as _init_session, run_state as _run_state, write_json_file as _write_json_file, STATE_PY
from state import _connect, _insert_source, _next_id, _now


# ---------------------------------------------------------------------------
# 1. Init creates correct schema
# ---------------------------------------------------------------------------

class TestSchemaInit:
    def test_init_creates_all_tables(self, tmp_path):
        """init command creates all required tables."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()

        expected = {
            "sessions", "brief", "searches", "sources", "findings", "gaps", "metrics",
            "source_flags", "report_targets", "report_target_evidence",
            "report_target_findings", "citation_audits", "review_issues",
        }
        assert expected.issubset(tables)

    def test_init_creates_indexes(self, tmp_path):
        """init command creates dedup indexes on sources table."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        conn.close()

        assert "idx_sources_doi" in indexes
        assert "idx_sources_url" in indexes
        assert "idx_sources_title" in indexes

    def test_init_creates_session_row(self, tmp_path):
        """init creates a session record with the query."""
        session_dir = str(tmp_path / "session")
        sid = _init_session(session_dir, query="machine learning survey")

        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()

        assert row is not None
        assert row["query"] == "machine learning survey"

    def test_init_creates_subdirectories(self, tmp_path):
        """init creates sources/, sources/metadata/, notes/ subdirs."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        assert os.path.isdir(os.path.join(session_dir, "sources"))
        assert os.path.isdir(os.path.join(session_dir, "sources", "metadata"))
        assert os.path.isdir(os.path.join(session_dir, "notes"))

    def test_init_creates_journal(self, tmp_path):
        """init creates journal.md file."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        journal = os.path.join(session_dir, "journal.md")
        assert os.path.isfile(journal)


# ---------------------------------------------------------------------------
# 2. Data persists across invocations
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_source_persists_across_invocations(self, tmp_path):
        """Sources added via CLI survive across separate process invocations."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        # Add a source via CLI (--from-json expects a file path)
        json_file = _write_json_file(tmp_path, {
            "title": "Persistent Source Test Paper",
            "doi": "10.1234/persist",
            "provider": "test",
        }, "source.json")
        result = subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"add-source failed: {result.stdout}"

        # Read back via separate connection
        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT title FROM sources WHERE doi = ?", ("10.1234/persist",)).fetchone()
        conn.close()

        assert row is not None
        assert row["title"] == "Persistent Source Test Paper"

    def test_state_json_regenerated(self, tmp_path):
        """state.json is regenerated after mutations."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        state_json = os.path.join(session_dir, "state.json")
        assert os.path.isfile(state_json)


# ---------------------------------------------------------------------------
# 3. Concurrent writes don't corrupt (WAL mode)
# ---------------------------------------------------------------------------

class TestConcurrentWrites:
    def test_wal_mode_enabled(self, tmp_path):
        """Database uses WAL journal mode for concurrency."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_concurrent_inserts_no_corruption(self, tmp_path):
        """Multiple threads inserting sources concurrently don't corrupt data."""
        session_dir = str(tmp_path / "session")
        sid = _init_session(session_dir)
        db_path = str(tmp_path / "session" / "state.db")

        errors = []
        inserted = []

        def insert_source(thread_id):
            try:
                conn = sqlite3.connect(db_path, timeout=20)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=20000")
                conn.row_factory = sqlite3.Row
                src_id = f"src-thread-{thread_id}"
                conn.execute(
                    """INSERT INTO sources (id, session_id, title, authors, provider, added_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (src_id, sid, f"Thread {thread_id} Paper", "[]", "test", _now()),
                )
                conn.commit()
                conn.close()
                inserted.append(src_id)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=insert_source, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent insert errors: {errors}"

        # Verify all 10 rows exist
        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        conn.close()
        assert count == 10


# ---------------------------------------------------------------------------
# 4. Source ID auto-increment
# ---------------------------------------------------------------------------

class TestSourceIDAutoIncrement:
    def test_source_ids_increment(self, tmp_path):
        """Source IDs follow src-001, src-002, ... pattern."""
        session_dir = str(tmp_path / "session")
        sid = _init_session(session_dir)

        conn = _connect(session_dir)
        conn.row_factory = sqlite3.Row

        r1 = _insert_source(conn, sid, {"title": "Paper One", "provider": "test"})
        r2 = _insert_source(conn, sid, {"title": "Paper Two", "provider": "test"})
        r3 = _insert_source(conn, sid, {"title": "Paper Three", "provider": "test"})
        conn.commit()
        conn.close()

        assert r1["id"] == "src-001"
        assert r2["id"] == "src-002"
        assert r3["id"] == "src-003"

    def test_next_id_for_searches(self, tmp_path):
        """Search IDs use search-N pattern."""
        session_dir = str(tmp_path / "session")
        sid = _init_session(session_dir)

        conn = _connect(session_dir)
        conn.row_factory = sqlite3.Row

        id1 = _next_id(conn, "searches", "search", sid)
        assert id1 == "search-1"
        conn.close()


# ---------------------------------------------------------------------------
# 5. Summary output is compact
# ---------------------------------------------------------------------------

class TestSummaryCompact:
    def test_summary_output_structure(self, tmp_path):
        """Summary includes expected keys and compact stats."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        # Add a source to have non-zero stats
        json_file = _write_json_file(tmp_path, {
            "title": "Summary Test Paper With Enough Characters",
            "provider": "semantic_scholar",
        }, "summary_source.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )

        result = subprocess.run(
            [sys.executable, STATE_PY, "summary", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

        data = json.loads(result.stdout)
        results = data["results"]

        assert "search_count" in results
        assert "source_count" in results
        assert results["source_count"] == 1
        assert "sources_by_provider" in results
        assert "sources" in results

    def test_summary_source_list_compact(self, tmp_path):
        """Source entries in summary are compact (id, title, type, provider only)."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        json_file = _write_json_file(tmp_path, {
            "title": "Compact Test Paper For Summary Verification",
            "abstract": "This long abstract should NOT appear in summary",
            "provider": "crossref",
        }, "compact_source.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )

        result = subprocess.run(
            [sys.executable, STATE_PY, "summary", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        sources = data["results"]["sources"]

        assert len(sources) == 1
        entry = sources[0]
        # Summary sources should have compact fields only
        assert "id" in entry
        assert "title" in entry
        assert "provider" in entry
        # Abstract should NOT be in summary source list
        assert "abstract" not in entry


# ---------------------------------------------------------------------------
# 6. Optional support context
# ---------------------------------------------------------------------------

class TestSupportContext:
    def test_support_context_works_without_policy(self, tmp_path):
        """support-context degrades cleanly when evidence-policy.yaml is absent."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        result, data = _run_state("support-context", "--session-dir", session_dir)

        assert result.returncode == 0
        policy = data["results"]["evidence_policy"]
        assert policy["present"] is False
        assert policy["path"] == "evidence-policy.yaml"
        assert policy["fields"]["source_expectations"] is None
        assert policy["fields"]["high_stakes_claim_patterns"] == []

    def test_support_context_reads_policy(self, tmp_path):
        """support-context includes optional run-local policy fields when present."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        with open(os.path.join(session_dir, "evidence-policy.yaml"), "w") as f:
            f.write(
                "\n".join([
                    'source_expectations: "Prefer primary sources for quantitative claims."',
                    'freshness_requirement: "high for current prices"',
                    'inference_tolerance: "low"',
                    "high_stakes_claim_patterns:",
                    "  - current pricing",
                    "  - legal requirements",
                    "known_failure_modes:",
                    "  - treating stale sources as current",
                ])
            )

        result, data = _run_state("support-context", "--session-dir", session_dir)

        assert result.returncode == 0
        policy = data["results"]["evidence_policy"]
        assert policy["present"] is True
        assert policy["fields"]["source_expectations"] == "Prefer primary sources for quantitative claims."
        assert policy["fields"]["freshness_requirement"] == "high for current prices"
        assert policy["fields"]["inference_tolerance"] == "low"
        assert policy["fields"]["high_stakes_claim_patterns"] == ["current pricing", "legal requirements"]
        assert policy["fields"]["known_failure_modes"] == ["treating stale sources as current"]

    def test_write_handoff_includes_support_context(self, tmp_path):
        """summary --write-handoff gives the synthesis writer the optional support context."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        result, data = _run_state("summary", "--write-handoff", "--session-dir", session_dir)

        assert result.returncode == 0
        handoff_path = os.path.join(session_dir, "synthesis-handoff.json")
        assert data["results"]["path"].endswith("synthesis-handoff.json")
        with open(handoff_path) as f:
            handoff = json.load(f)
        assert handoff["support_context"]["schema_version"] == "support-context-v1"
        assert handoff["support_context"]["evidence_policy"]["present"] is False


# ---------------------------------------------------------------------------
# 7. Source caution flags
# ---------------------------------------------------------------------------

class TestSourceFlags:
    def _setup_session_with_source(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Source Flag Test Paper",
            "doi": "10.1234/source-flag",
            "provider": "test",
        }, "source_flag_source.json")
        result, _ = _run_state("add-source", "--session-dir", session_dir, "--from-json", json_file)
        assert result.returncode == 0
        return session_dir

    def test_set_and_list_source_flags(self, tmp_path):
        """Source caution flags are additive scoped annotations."""
        session_dir = self._setup_session_with_source(tmp_path)

        result, data = _run_state(
            "set-source-flag", "--session-dir", session_dir,
            "--source-id", "src-001",
            "--flag", "secondary_source",
            "--rationale", "Review article summarizing primary studies.",
        )
        assert result.returncode == 0
        assert data["results"]["id"] == "sflag-001"
        assert data["results"]["created"] is True

        result, data = _run_state("source-flags", "--session-dir", session_dir, "--source-id", "src-001")
        assert result.returncode == 0
        assert len(data["results"]) == 1
        assert data["results"][0]["flag"] == "secondary_source"
        assert data["results"][0]["applies_to_type"] == "run"

    def test_scoped_source_flags_require_target_id(self, tmp_path):
        """Narrower source caution scopes require applies_to_id."""
        session_dir = self._setup_session_with_source(tmp_path)

        result, data = _run_state(
            "set-source-flag", "--session-dir", session_dir,
            "--source-id", "src-001",
            "--flag", "potentially_stale",
            "--applies-to", "finding",
            "--rationale", "Older source for a current-state finding.",
        )
        assert data["status"] == "error"
        assert "applies-to-id is required" in data["errors"][0]

    def test_source_flag_summary_and_quality_summary(self, tmp_path):
        """Summaries include raw quality aliases, canonical quality counts, and caution counts."""
        session_dir = self._setup_session_with_source(tmp_path)

        _run_state(
            "set-quality", "--session-dir", session_dir,
            "--id", "src-001", "--quality", "mismatched",
        )
        _run_state(
            "set-source-flag", "--session-dir", session_dir,
            "--source-id", "src-001",
            "--flag", "potentially_stale",
            "--applies-to", "finding",
            "--applies-to-id", "finding-1",
            "--rationale", "Source is old for a current pricing claim.",
        )

        result, data = _run_state("source-flag-summary", "--session-dir", session_dir, "--include-rows")
        assert result.returncode == 0
        assert data["results"]["total"] == 1
        assert data["results"]["by_flag"] == {"potentially_stale": 1}
        assert data["results"]["by_scope"] == {"finding": 1}
        assert data["results"]["flags"][0]["applies_to_id"] == "finding-1"

        result, data = _run_state("source-quality-summary", "--session-dir", session_dir)
        assert result.returncode == 0
        assert data["results"]["raw_counts"]["title_content_mismatch"] == 1
        assert data["results"]["access_quality_counts"]["title_content_mismatch"] == 1
        assert data["results"]["source_caution_flags"]["total"] == 1

    def test_support_context_includes_source_flags(self, tmp_path):
        """support-context surfaces source caution flags when present."""
        session_dir = self._setup_session_with_source(tmp_path)
        _run_state(
            "set-source-flag", "--session-dir", session_dir,
            "--source-id", "src-001",
            "--flag", "self_interested_source",
            "--rationale", "Vendor-authored source.",
        )

        result, data = _run_state("support-context", "--session-dir", session_dir)

        assert result.returncode == 0
        assert data["results"]["available_context"]["source_caution_flags"] is True
        flags = data["results"]["source_caution_flags"]
        assert flags["total"] == 1
        assert flags["by_flag"] == {"self_interested_source": 1}

    def test_mark_read_does_not_write_reader_validated_quality(self, tmp_path):
        """Reading a source should not overload access quality with reader validation state."""
        session_dir = self._setup_session_with_source(tmp_path)
        _run_state(
            "set-quality", "--session-dir", session_dir,
            "--id", "src-001", "--quality", "degraded",
        )
        with open(os.path.join(session_dir, "notes", "src-001.md"), "w") as f:
            f.write("# Reader note\n\nThe reader successfully extracted useful notes.")

        result, data = _run_state("mark-read", "--session-dir", session_dir, "--id", "src-001")

        assert result.returncode == 0
        assert "quality_upgraded" not in data["results"]
        _, summary = _run_state("source-quality-summary", "--session-dir", session_dir)
        assert summary["results"]["raw_counts"]["degraded_extraction"] == 1
        assert "reader_validated" not in summary["results"]["raw_counts"]


# ---------------------------------------------------------------------------
# 8. Report grounding manifests
# ---------------------------------------------------------------------------

class TestReportGrounding:
    def _setup_grounded_report(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        source_file = _write_json_file(tmp_path, {
            "title": "Grounding Source",
            "doi": "10.1234/grounding",
            "provider": "test",
        }, "grounding_source.json")
        result, _ = _run_state("add-source", "--session-dir", session_dir, "--from-json", source_file)
        assert result.returncode == 0

        evidence_file = _write_json_file(tmp_path, {
            "source_id": "src-001",
            "units": [
                {
                    "claim_text": "Grounded finding evidence.",
                    "claim_type": "result",
                    "provenance_type": "content_span",
                    "primary_question_id": "Q1",
                }
            ],
        }, "grounding_evidence.json")
        result, _ = _run_state("add-evidence", "--session-dir", session_dir, "--from-json", evidence_file)
        assert result.returncode == 0

        result, _ = _run_state(
            "log-finding", "--session-dir", session_dir,
            "--text", "Grounded finding.",
            "--sources", "src-001",
            "--question-id", "Q1",
            "--evidence-ids", "ev-0001",
        )
        assert result.returncode == 0

        report_path = os.path.join(session_dir, "draft.md")
        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "Grounded paragraph with a citation [1].\n\n"
                "## References\n\n"
                "[1] Grounding Source.\n"
            )

        result, data = _run_state("report-paragraphs", "--session-dir", session_dir, "--report", report_path)
        assert result.returncode == 0
        paragraph = next(p for p in data["results"]["paragraphs"] if p["section"] == "Executive Summary")

        manifest = {
            "schema_version": "report-grounding-v1",
            "report_path": report_path,
            "targets": [
                {
                    "target_id": "rp-001",
                    "section": paragraph["section"],
                    "paragraph": paragraph["paragraph"],
                    "text_hash": paragraph["text_hash"],
                    "text_snippet": paragraph["text_snippet"],
                    "citation_refs": ["[1]"],
                    "source_ids": ["src-001"],
                    "finding_ids": ["finding-1"],
                    "evidence_ids": ["ev-0001"],
                    "warnings": [],
                    "grounding_status": "declared_grounded",
                }
            ],
        }
        manifest_path = os.path.join(session_dir, "report-grounding.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)
        return session_dir, report_path, manifest_path, manifest

    def test_validate_report_grounding_valid_manifest(self, tmp_path):
        """validate-report-grounding accepts a structurally consistent manifest."""
        session_dir, _, manifest_path, _ = self._setup_grounded_report(tmp_path)

        result, data = _run_state("validate-report-grounding", "--session-dir", session_dir, "--manifest", manifest_path)

        assert result.returncode == 0
        assert data["results"]["valid"] is True
        assert data["results"]["summary"]["valid_targets"] == 1
        assert data["results"]["summary"]["ungrounded_paragraphs"] == 0

        _, context = _run_state("support-context", "--session-dir", session_dir)
        assert context["results"]["available_context"]["report_grounding"] is True
        assert context["results"]["report_grounding"]["status"] == "declared_provenance_not_verified"

    def test_validate_report_grounding_stale_hash(self, tmp_path):
        """Stale paragraph hashes are surfaced, not trusted."""
        session_dir, _, manifest_path, manifest = self._setup_grounded_report(tmp_path)
        manifest["targets"][0]["text_hash"] = "sha256:" + ("0" * 64)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        _, data = _run_state("validate-report-grounding", "--session-dir", session_dir, "--manifest", manifest_path)

        target = data["results"]["targets"][0]
        assert data["results"]["valid"] is False
        assert target["status"] == "stale_hash"
        assert target["issues"][0]["code"] == "stale_hash"

    def test_validate_report_grounding_missing_citation(self, tmp_path):
        """Citation refs listed in a target must occur in that target text."""
        session_dir, _, manifest_path, manifest = self._setup_grounded_report(tmp_path)
        manifest["targets"][0]["citation_refs"] = ["[2]"]
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        _, data = _run_state("validate-report-grounding", "--session-dir", session_dir, "--manifest", manifest_path)

        codes = [issue["code"] for issue in data["results"]["targets"][0]["issues"]]
        assert data["results"]["valid"] is False
        assert "citation_ref_missing" in codes

    def test_validate_report_grounding_missing_referenced_ids(self, tmp_path):
        """Missing source, finding, and evidence IDs are surfaced."""
        session_dir, _, manifest_path, manifest = self._setup_grounded_report(tmp_path)
        manifest["targets"][0]["source_ids"] = ["src-999"]
        manifest["targets"][0]["finding_ids"] = ["finding-999"]
        manifest["targets"][0]["evidence_ids"] = ["ev-9999"]
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        _, data = _run_state("validate-report-grounding", "--session-dir", session_dir, "--manifest", manifest_path)

        missing = [
            (issue["field"], issue["id"])
            for issue in data["results"]["targets"][0]["issues"]
            if issue["code"] == "missing_referenced_id"
        ]
        assert data["results"]["valid"] is False
        assert ("source_ids", "src-999") in missing
        assert ("finding_ids", "finding-999") in missing
        assert ("evidence_ids", "ev-9999") in missing

    def test_validate_report_grounding_reports_ungrounded_paragraphs(self, tmp_path):
        """Body paragraphs without grounding entries are audit findings, not hard gates."""
        session_dir, report_path, manifest_path, _ = self._setup_grounded_report(tmp_path)
        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "Grounded paragraph with a citation [1].\n\n"
                "Second ungrounded paragraph.\n\n"
                "## References\n\n"
                "[1] Grounding Source.\n"
            )

        _, data = _run_state("validate-report-grounding", "--session-dir", session_dir, "--manifest", manifest_path)

        assert data["results"]["valid"] is False
        assert data["results"]["summary"]["ungrounded_paragraphs"] == 1
        assert data["results"]["issues"][0]["code"] == "ungrounded_paragraphs"


class TestReportSupportAudit:
    def _setup_support_audit_fixture(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        for name in ("Primary Source", "Secondary Source"):
            source_file = _write_json_file(tmp_path, {
                "title": name,
                "provider": "test",
            }, f"{name.lower().replace(' ', '_')}.json")
            result, _ = _run_state("add-source", "--session-dir", session_dir, "--from-json", source_file)
            assert result.returncode == 0

        _run_state("set-quality", "--session-dir", session_dir, "--id", "src-002", "--quality", "abstract_only")
        _run_state(
            "set-source-flag", "--session-dir", session_dir,
            "--source-id", "src-002",
            "--flag", "secondary_source",
            "--rationale", "Review article used for a local citation.",
        )

        evidence_file = _write_json_file(tmp_path, {
            "source_id": "src-001",
            "units": [
                {
                    "claim_text": "Primary evidence supports the first target.",
                    "claim_type": "result",
                    "provenance_type": "content_span",
                    "primary_question_id": "Q1",
                }
            ],
        }, "audit_evidence.json")
        result, _ = _run_state("add-evidence", "--session-dir", session_dir, "--from-json", evidence_file)
        assert result.returncode == 0

        _run_state(
            "log-finding", "--session-dir", session_dir,
            "--text", "Finding with direct evidence.",
            "--sources", "src-001",
            "--evidence-ids", "ev-0001",
        )
        _run_state(
            "log-finding", "--session-dir", session_dir,
            "--text", "Finding without direct evidence.",
            "--sources", "src-002",
        )

        report_path = os.path.join(session_dir, "draft.md")
        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "First grounded paragraph with direct evidence [1].\n\n"
                "Second paragraph with finding-level grounding only [2].\n\n"
                "Third paragraph has no declared grounding.\n\n"
                "## References\n\n"
                "[1] Primary Source.\n"
                "[2] Secondary Source.\n"
            )

        result, data = _run_state("report-paragraphs", "--session-dir", session_dir, "--report", report_path)
        assert result.returncode == 0
        exec_paragraphs = [p for p in data["results"]["paragraphs"] if p["section"] == "Executive Summary"]
        manifest = {
            "schema_version": "report-grounding-v1",
            "report_path": report_path,
            "targets": [
                {
                    "target_id": "rp-001",
                    "section": exec_paragraphs[0]["section"],
                    "paragraph": exec_paragraphs[0]["paragraph"],
                    "text_hash": exec_paragraphs[0]["text_hash"],
                    "text_snippet": exec_paragraphs[0]["text_snippet"],
                    "citation_refs": ["[1]"],
                    "source_ids": ["src-001"],
                    "finding_ids": ["finding-1"],
                    "evidence_ids": ["ev-0001"],
                    "warnings": [],
                    "support_level": "strong",
                    "grounding_status": "declared_grounded",
                },
                {
                    "target_id": "rp-002",
                    "section": exec_paragraphs[1]["section"],
                    "paragraph": exec_paragraphs[1]["paragraph"],
                    "text_hash": exec_paragraphs[1]["text_hash"],
                    "text_snippet": exec_paragraphs[1]["text_snippet"],
                    "citation_refs": ["[2]"],
                    "source_ids": ["src-002"],
                    "finding_ids": ["finding-2"],
                    "evidence_ids": [],
                    "warnings": [],
                    "support_level": "weak",
                    "grounding_status": "declared_grounded",
                },
            ],
        }
        manifest_path = os.path.join(session_dir, "report-grounding.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        revision_dir = os.path.join(session_dir, "revision")
        os.makedirs(revision_dir, exist_ok=True)
        with open(os.path.join(revision_dir, "citation-audit.json"), "w") as f:
            json.dump({
                "schema_version": "citation-audit-v1",
                "checks": [
                    {
                        "report_target_id": "rp-002",
                        "section": "Executive Summary",
                        "paragraph": 2,
                        "citation_ref": "[2]",
                        "source_ids": ["src-002"],
                        "support_classification": "weak_support",
                        "recommended_action": "weaken_wording",
                        "rationale": "The citation is topically related but does not fully support the paragraph wording.",
                    }
                ],
            }, f)
        with open(os.path.join(revision_dir, "accuracy-issues.json"), "w") as f:
            json.dump({
                "issues": [
                    {
                        "issue_id": "review-1",
                        "severity": "medium",
                        "dimension": "unsupported_claim",
                        "location": "Executive Summary, paragraph 2",
                        "description": "Needs stronger source support.",
                    }
                ],
            }, f)
        return session_dir, manifest_path, manifest

    def test_audit_report_support_aggregates_declared_grounding_and_agent_judgments(self, tmp_path):
        """audit-report-support writes compact declared-grounding and support coverage output."""
        session_dir, _, _ = self._setup_support_audit_fixture(tmp_path)

        result, data = _run_state("audit-report-support", "--session-dir", session_dir)

        assert result.returncode == 0
        summary = data["results"]["summary"]
        assert summary["paragraphs_with_declared_grounding"] == 2
        assert summary["paragraphs_without_grounding"] == 1
        assert summary["targets_with_declared_evidence_links"] == 1
        assert summary["targets_with_only_declared_finding_level_links"] == 1
        assert summary["findings_without_evidence_links"] == 1
        assert summary["targets_depending_on_warned_sources"] == 1
        assert summary["citations_checked_by_audit"] == 1
        assert summary["citations_rejected_or_weakened_by_audit"] == 1
        assert summary["unresolved_review_issues"] == 1
        assert "declared provenance" in data["results"]["provenance_boundary"]["declared_grounding"]

        audit_path = os.path.join(session_dir, "revision", "report-support-audit.json")
        assert os.path.exists(audit_path)
        with open(audit_path) as f:
            audit = json.load(f)
        warned = audit["source_warnings"]["targets_depending_on_warned_sources"]
        assert warned[0]["target_id"] == "rp-002"
        assert {reason["value"] for reason in warned[0]["warnings"]} == {"abstract_only", "secondary_source"}
        assert audit["agent_verified_support"]["weak_support_density_by_section"][0]["weak_count"] == 1

    def test_audit_report_support_surfaces_manifest_validation_failures(self, tmp_path):
        """The support audit carries report-grounding validation failures into its output."""
        session_dir, manifest_path, manifest = self._setup_support_audit_fixture(tmp_path)
        manifest["targets"][0]["citation_refs"] = ["[9]"]
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        result, _ = _run_state("audit-report-support", "--session-dir", session_dir)

        assert result.returncode == 0
        with open(os.path.join(session_dir, "revision", "report-support-audit.json")) as f:
            audit = json.load(f)
        codes = [issue["code"] for issue in audit["validation"]["targets"][0]["issues"]]
        assert audit["validation"]["valid"] is False
        assert "citation_ref_missing" in codes

    def test_citation_audit_contexts_from_report_grounding(self, tmp_path):
        """citation-audit-contexts enumerates local citation contexts from declared grounding."""
        session_dir, _, _ = self._setup_support_audit_fixture(tmp_path)

        result, data = _run_state("citation-audit-contexts", "--session-dir", session_dir)

        assert result.returncode == 0
        assert data["results"]["summary"]["citation_contexts"] == 2
        context_path = os.path.join(session_dir, "revision", "citation-audit-contexts.json")
        assert os.path.exists(context_path)
        with open(context_path) as f:
            contexts = json.load(f)

        first = contexts["contexts"][0]
        second = contexts["contexts"][1]
        assert contexts["schema_version"] == "citation-audit-contexts-v1"
        assert "supported" in contexts["allowed_support_classifications"]
        assert "replace_source" in contexts["allowed_recommended_actions"]
        assert first["report_target_id"] == "rp-001"
        assert first["citation_ref"] == "[1]"
        assert first["cited_source_ids"] == ["src-001"]
        assert first["text_hash"].startswith("sha256:")
        assert second["report_target_id"] == "rp-002"
        assert second["finding_ids"] == ["finding-2"]
        assert second["support_classification"] is None
        assert "not citation support judgments" in contexts["notes"][0]

    def test_audit_report_support_reports_malformed_citation_audit_checks(self, tmp_path):
        """Support audit surfaces malformed citation-audit check records."""
        session_dir, _, _ = self._setup_support_audit_fixture(tmp_path)
        citation_path = os.path.join(session_dir, "revision", "citation-audit.json")
        with open(citation_path, "w") as f:
            json.dump({
                "schema_version": "citation-audit-v1",
                "checks": [
                    {
                        "report_target_id": "rp-001",
                        "citation_ref": "[1]",
                        "cited_source_ids": ["src-001"],
                        "support_classification": "not_a_valid_class",
                        "recommended_action": "keep",
                    }
                ],
            }, f)

        result, _ = _run_state("audit-report-support", "--session-dir", session_dir)

        assert result.returncode == 0
        with open(os.path.join(session_dir, "revision", "report-support-audit.json")) as f:
            audit = json.load(f)
        issue_codes = {issue["code"] for issue in audit["artifact_issues"]["citation_audit"]}
        assert "citation_audit_invalid_support_classification" in issue_codes
        assert "citation_audit_missing_rationale" in issue_codes


class TestRevisionGroundingIntegration:
    def test_validate_edits_marks_grounded_target_for_refresh(self, tmp_path):
        """Post-revision validation reports grounded targets that need manifest refresh."""
        session_dir, report_path, grounding_path, _ = TestReportGrounding()._setup_grounded_report(tmp_path)
        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "Grounded revised paragraph with a citation [1].\n\n"
                "## References\n\n"
                "[1] Grounding Source.\n"
            )

        revision_dir = os.path.join(session_dir, "revision")
        os.makedirs(revision_dir, exist_ok=True)
        revision_manifest = os.path.join(revision_dir, "revision-manifest.json")
        with open(revision_manifest, "w") as f:
            json.dump({
                "passes": [
                    {
                        "pass": "accuracy",
                        "issues": [
                            {
                                "issue_id": "verify-1",
                                "status": "resolved",
                                "report_target_id": "rp-001",
                                "location": "Executive Summary, paragraph 1",
                                "old_text_snippet": "Grounded paragraph with a citation [1].",
                                "new_text_snippet": "Grounded revised paragraph with a citation [1].",
                            }
                        ],
                    }
                ]
            }, f)

        result, data = _run_state(
            "validate-edits",
            "--manifest", revision_manifest,
            "--report", report_path,
            "--grounding-manifest", grounding_path,
            "--pass", "accuracy",
        )

        assert result.returncode == 0
        assert data["results"]["confirmed"] == ["verify-1"]
        refresh = data["results"]["grounding_refresh"]
        assert refresh["summary"]["targets_needing_refresh"] == 1
        target = refresh["targets_needing_refresh"][0]
        assert target["target_id"] == "rp-001"
        assert target["status"] == "needs_refresh"
        assert target["issue_ids"] == ["verify-1"]
        assert target["current_text_hash"] != target["text_hash"]
        assert "manifest_entry_report_target_id" in target["reasons"]

    def test_validate_edits_checks_partial_and_limitation_statuses(self, tmp_path):
        """Validation covers edited non-resolved statuses that still change report text."""
        session_dir, report_path, grounding_path, _ = TestReportGrounding()._setup_grounded_report(tmp_path)
        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "Grounded revised paragraph with a citation [1].\n\n"
                "## References\n\n"
                "[1] Grounding Source.\n"
            )

        revision_dir = os.path.join(session_dir, "revision")
        os.makedirs(revision_dir, exist_ok=True)
        revision_manifest = os.path.join(revision_dir, "revision-manifest.json")
        with open(revision_manifest, "w") as f:
            json.dump({
                "passes": [
                    {
                        "pass": "accuracy",
                        "issues": [
                            {
                                "issue_id": "verify-1",
                                "status": "partially_resolved",
                                "report_target_id": "rp-001",
                                "old_text_snippet": "Grounded paragraph with a citation [1].",
                                "new_text_snippet": "Grounded revised paragraph with a citation [1].",
                            },
                            {
                                "issue_id": "review-1",
                                "status": "accepted_as_limitation",
                                "report_target_id": "rp-001",
                                "old_text_snippet": "Grounded paragraph with a citation [1].",
                                "new_text_snippet": "Grounded revised paragraph with a citation [1].",
                            },
                        ],
                    }
                ]
            }, f)

        result, data = _run_state(
            "validate-edits",
            "--manifest", revision_manifest,
            "--report", report_path,
            "--grounding-manifest", grounding_path,
            "--pass", "accuracy",
        )

        assert result.returncode == 0
        assert data["results"]["confirmed"] == ["verify-1", "review-1"]
        refresh_target = data["results"]["grounding_refresh"]["targets_needing_refresh"][0]
        assert refresh_target["target_id"] == "rp-001"
        assert refresh_target["issue_ids"] == ["verify-1", "review-1"]


class TestReviewIssueTraceability:
    def _setup_review_issue_fixture(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        report_path = os.path.join(session_dir, "report.md")
        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "Original target paragraph with a citation [1].\n\n"
                "Stable hash fallback paragraph [1].\n\n"
                "Original snippet survives in this paragraph [1].\n\n"
                "## References\n\n"
                "[1] Source.\n"
            )

        result, data = _run_state("report-paragraphs", "--session-dir", session_dir, "--report", report_path)
        assert result.returncode == 0
        paragraphs = [p for p in data["results"]["paragraphs"] if p["section"] == "Executive Summary"]
        manifest = {
            "schema_version": "report-grounding-v1",
            "report_path": report_path,
            "targets": [
                {
                    "target_id": "rp-001",
                    "section": paragraphs[0]["section"],
                    "paragraph": paragraphs[0]["paragraph"],
                    "text_hash": paragraphs[0]["text_hash"],
                    "text_snippet": paragraphs[0]["text_snippet"],
                    "citation_refs": ["[1]"],
                    "source_ids": [],
                    "finding_ids": [],
                    "evidence_ids": [],
                    "warnings": [],
                    "not_grounded_reason": "test fixture",
                }
            ],
        }
        grounding_path = os.path.join(session_dir, "report-grounding.json")
        with open(grounding_path, "w") as f:
            json.dump(manifest, f)

        with open(report_path, "w") as f:
            f.write(
                "# Test Report\n\n"
                "## Executive Summary\n\n"
                "Revised target paragraph with a citation [1].\n\n"
                "Stable hash fallback paragraph [1].\n\n"
                "Updated paragraph where snippet survives after revision [1].\n\n"
                "## References\n\n"
                "[1] Source.\n"
            )

        revision_dir = os.path.join(session_dir, "revision")
        os.makedirs(revision_dir, exist_ok=True)
        issues_path = os.path.join(revision_dir, "accuracy-issues.json")
        with open(issues_path, "w") as f:
            json.dump({
                "schema_version": "review-issues-v1",
                "issues": [
                    {
                        "issue_id": "review-1",
                        "dimension": "unsupported_claim",
                        "severity": "medium",
                        "target_type": "report_target",
                        "target_id": "rp-001",
                        "locator": "Executive Summary, paragraph 1",
                        "text_hash": paragraphs[0]["text_hash"],
                        "text_snippet": paragraphs[0]["text_snippet"],
                        "related_source_ids": ["src-001"],
                        "related_evidence_ids": ["ev-0001"],
                        "related_citation_refs": ["[1]"],
                        "status": "open",
                        "rationale": "Target needs a stronger source.",
                        "resolution": None,
                    },
                    {
                        "issue_id": "review-2",
                        "dimension": "missing_context",
                        "severity": "low",
                        "target_type": "report_target",
                        "target_id": "",
                        "locator": "Executive Summary, paragraph 2",
                        "text_hash": paragraphs[1]["text_hash"],
                        "text_snippet": paragraphs[1]["text_snippet"],
                        "status": "open",
                        "rationale": "Hash fallback issue.",
                    },
                    {
                        "issue_id": "review-3",
                        "dimension": "citation_integrity",
                        "severity": "medium",
                        "target_type": "report_target",
                        "target_id": "",
                        "locator": "Executive Summary, paragraph 3",
                        "text_hash": paragraphs[2]["text_hash"],
                        "text_snippet": "snippet survives",
                        "status": "open",
                        "rationale": "Snippet fallback issue.",
                    },
                    {
                        "issue_id": "review-4",
                        "dimension": "internal_contradiction",
                        "severity": "high",
                        "target_type": "report_target",
                        "target_id": "rp-001",
                        "locator": "Executive Summary, paragraph 1",
                        "text_hash": paragraphs[0]["text_hash"],
                        "text_snippet": paragraphs[0]["text_snippet"],
                        "conflicting_target_ids": ["rp-001", "rp-009"],
                        "contradiction_type": "direct_conflict",
                        "final_report_handling": "Resolve in report text or disclose uncertainty.",
                        "status": "open",
                        "rationale": "Two report targets cannot both be true.",
                    },
                ],
            }, f)
        return session_dir, report_path, grounding_path

    def test_review_issues_reconnect_by_target_id_hash_and_snippet(self, tmp_path):
        """review-issues keeps report-target issue identity after report text changes."""
        session_dir, report_path, grounding_path = self._setup_review_issue_fixture(tmp_path)

        result, data = _run_state(
            "review-issues",
            "--session-dir", session_dir,
            "--status", "all",
            "--report", report_path,
            "--grounding-manifest", grounding_path,
        )

        assert result.returncode == 0
        issues = {issue["issue_id"]: issue for issue in data["results"]["issues"]}
        assert data["results"]["schema_version"] == "review-issues-v1"
        assert issues["review-1"]["target_match"]["status"] == "stale_hash"
        assert issues["review-1"]["target_match"]["current_text_hash"] != issues["review-1"]["text_hash"]
        assert issues["review-2"]["target_match"]["status"] == "matched_by_text_hash"
        assert issues["review-3"]["target_match"]["status"] == "matched_by_snippet"
        contradiction = issues["review-4"]["contradiction_candidate"]
        assert contradiction["conflicting_target_ids"] == ["rp-001", "rp-009"]
        assert contradiction["contradiction_type"] == "direct_conflict"
        assert data["results"]["summary"]["contradiction_candidates"] == 1
        assert data["results"]["summary"]["matched_report_target_issues"] == 4

    def test_review_issues_applies_revision_manifest_status_overrides(self, tmp_path):
        """Revision manifest status transitions determine which issues remain open."""
        session_dir, report_path, grounding_path = self._setup_review_issue_fixture(tmp_path)
        manifest_path = os.path.join(session_dir, "revision", "revision-manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({
                "passes": [
                    {
                        "pass": "accuracy",
                        "issues": [
                            {
                                "issue_id": "review-1",
                                "status": "resolved",
                                "action": "Qualified the target paragraph.",
                                "report_target_id": "rp-001",
                            }
                        ],
                    }
                ]
            }, f)

        result, data = _run_state(
            "review-issues",
            "--session-dir", session_dir,
            "--status", "open",
            "--report", report_path,
            "--grounding-manifest", grounding_path,
        )

        assert result.returncode == 0
        assert "review-1" not in {issue["issue_id"] for issue in data["results"]["issues"]}
        assert data["results"]["summary"]["status_counts"]["resolved"] == 1

        _, all_data = _run_state(
            "review-issues",
            "--session-dir", session_dir,
            "--status", "all",
            "--report", report_path,
            "--grounding-manifest", grounding_path,
        )
        review_1 = next(issue for issue in all_data["results"]["issues"] if issue["issue_id"] == "review-1")
        assert review_1["status"] == "resolved"
        assert review_1["status_source"] == "revision-manifest"
        assert review_1["resolution"] == "Qualified the target paragraph."


class TestSupportArtifactIngestion:
    def test_ingest_support_artifacts_tracks_quality_dimensions_and_handoff(self, tmp_path):
        """Support artifacts become queryable state without needing a graph subsystem."""
        session_dir, manifest_path, manifest = TestReportSupportAudit()._setup_support_audit_fixture(tmp_path)
        manifest["targets"][1]["claim_type"] = "quantitative"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        revision_dir = os.path.join(session_dir, "revision")
        with open(os.path.join(revision_dir, "accuracy-issues.json"), "w") as f:
            json.dump({
                "schema_version": "review-issues-v1",
                "issues": [
                    {
                        "issue_id": "review-1",
                        "dimension": "citation_support",
                        "severity": "medium",
                        "target_type": "report_target",
                        "target_id": "rp-002",
                        "locator": "Executive Summary, paragraph 2",
                        "text_hash": manifest["targets"][1]["text_hash"],
                        "text_snippet": manifest["targets"][1]["text_snippet"],
                        "related_source_ids": ["src-002"],
                        "related_citation_refs": ["[2]"],
                        "status": "open",
                        "rationale": "Citation is weak for the quantitative wording.",
                    },
                    {
                        "issue_id": "review-2",
                        "dimension": "missing_context",
                        "severity": "low",
                        "target_type": "report_target",
                        "target_id": "rp-001",
                        "locator": "Executive Summary, paragraph 1",
                        "text_hash": manifest["targets"][0]["text_hash"],
                        "text_snippet": manifest["targets"][0]["text_snippet"],
                        "status": "open",
                        "rationale": "Needs a limitation statement.",
                    },
                ],
            }, f)
        with open(os.path.join(revision_dir, "revision-manifest.json"), "w") as f:
            json.dump({
                "passes": [
                    {
                        "pass": "accuracy",
                        "issues": [
                            {
                                "issue_id": "review-2",
                                "status": "accepted_as_limitation",
                                "resolution": "The limitation is explicitly disclosed in the report.",
                                "report_target_id": "rp-001",
                            }
                        ],
                    }
                ],
            }, f)

        result, data = _run_state(
            "ingest-support-artifacts",
            "--session-dir", session_dir,
            "--grounding-manifest", manifest_path,
        )

        assert result.returncode == 0
        summary = data["results"]["summary"]
        assert summary["report_targets"] == 3
        assert summary["citation_audits"] == 1
        assert summary["review_issues"] == 2
        assert summary["open_issues"] == 1
        metrics = data["results"]["reflection_metrics"]
        assert metrics["report_targets_total"] == 3
        assert metrics["report_targets_with_declared_finding_links"] == 2
        assert metrics["report_targets_with_declared_evidence_links"] == 1
        assert metrics["report_targets_without_grounding"] == 1
        assert metrics["quantitative_or_fragile_targets_without_structured_evidence"] == 1
        assert metrics["report_targets_depending_on_flagged_sources"] == 1
        assert metrics["citations_audited"] == 1
        assert metrics["citations_weakened_or_rejected"] == 1
        assert metrics["reviewer_issues_with_target_ids"] == 2
        assert metrics["reviewer_issues_resolved_before_delivery"] == 1
        assert metrics["unresolved_issues_before_delivery"] == 1

        _, handoff = _run_state("support-handoff", "--session-dir", session_dir, "--limit", "10")
        handoff_results = handoff["results"]
        assert handoff_results["schema_version"] == "support-handoff-v1"
        assert handoff_results["report_targets"]["summary"]["total"] == 3
        assert {target["target_id"] for target in handoff_results["report_targets"]["targets"]} >= {"rp-001", "rp-002"}
        assert handoff_results["open_support_issues"]["summary"]["total"] == 1
        assert handoff_results["open_support_issues"]["issues"][0]["issue_id"] == "review-1"
        assert handoff_results["citation_support_issues"]["summary"]["total"] == 1

        _, metrics_data = _run_state("reflection-metrics", "--session-dir", session_dir)
        assert metrics_data["results"]["metrics"]["unresolved_issues_before_delivery"] == 1
        assert metrics_data["results"]["metrics"]["citations_classified_weak_overstated_or_topically_related_only"] == 1
        assert metrics_data["results"]["metrics"]["unresolved_contradictions_or_limitations_disclosed"] == 1

        _, delivery = _run_state("delivery-audit", "--session-dir", session_dir, "--limit", "10")
        audit = delivery["results"]
        assert audit["schema_version"] == "delivery-audit-v1"
        assert audit["provenance_boundary"]["agent_judgment"].startswith("This is not a readiness score")
        assert audit["success_metrics"]["sources_with_extraction_access_quality_warnings"] == 1
        assert audit["success_metrics"]["sources_with_caution_flags"] == 1
        assert audit["success_metrics"]["findings_with_evidence_links"] == 1
        assert audit["success_metrics"]["findings_without_evidence_links"] == 1
        assert audit["open_issues"]["summary"]["total"] == 1
        assert audit["unresolved_contradictions_or_limitations"]["summary"]["disclosed_or_accepted"] == 1
        assert {item["status"] for item in audit["validation_checklist"]} == {"agent_judgment_required"}

    def test_missing_optional_artifacts_clear_previous_ingested_state(self, tmp_path):
        """Refreshing without optional artifacts should not leave stale queryable rows behind."""
        session_dir, manifest_path, _ = TestReportSupportAudit()._setup_support_audit_fixture(tmp_path)
        result, data = _run_state(
            "ingest-support-artifacts",
            "--session-dir", session_dir,
            "--grounding-manifest", manifest_path,
        )
        assert result.returncode == 0
        assert data["results"]["reflection_metrics"]["report_targets_total"] > 0
        assert data["results"]["reflection_metrics"]["citations_audited"] > 0

        os.remove(manifest_path)
        os.remove(os.path.join(session_dir, "revision", "citation-audit.json"))

        result, data = _run_state(
            "ingest-support-artifacts",
            "--session-dir", session_dir,
            "--grounding-manifest", manifest_path,
        )

        assert result.returncode == 0
        assert data["results"]["report_grounding"]["cleared"] is True
        assert data["results"]["citation_audit"]["cleared"] is True
        metrics = data["results"]["reflection_metrics"]
        assert metrics["report_targets_total"] == 0
        assert metrics["citations_audited"] == 0

        _, handoff = _run_state("support-handoff", "--session-dir", session_dir)
        assert handoff["results"]["report_targets"]["summary"]["total"] == 0
        assert handoff["results"]["citation_support_issues"]["summary"]["total"] == 0


# ---------------------------------------------------------------------------
# Evidence layer tests
# ---------------------------------------------------------------------------

class TestEvidenceSchema:
    def test_init_creates_evidence_tables(self, tmp_path):
        """init creates evidence_units and finding_evidence tables."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()

        assert "evidence_units" in tables
        assert "finding_evidence" in tables

    def test_init_creates_evidence_indexes(self, tmp_path):
        """init creates evidence indexes."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        conn = sqlite3.connect(str(tmp_path / "session" / "state.db"))
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        conn.close()

        assert "idx_evidence_source" in indexes
        assert "idx_evidence_question" in indexes

    def test_init_creates_evidence_directory(self, tmp_path):
        """init creates evidence/ subdirectory."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        assert os.path.isdir(os.path.join(session_dir, "evidence"))


class TestAddEvidence:
    def _setup_session_with_source(self, tmp_path):
        """Helper: init session + add a source, return session_dir."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Evidence Test Paper",
            "doi": "10.1234/evidence-test",
            "provider": "test",
        }, "source.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        return session_dir

    def test_add_single_manifest(self, tmp_path):
        """add-evidence inserts units from a single source manifest."""
        session_dir = self._setup_session_with_source(tmp_path)

        manifest = {
            "source_id": "src-001",
            "generated_by": "research-reader",
            "units": [
                {
                    "primary_question_id": "Q1",
                    "question_ids": ["Q1"],
                    "claim_text": "Only 1 of 8 studies supported the hypothesis.",
                    "claim_type": "result",
                    "relation": "supports",
                    "evidence_strength": "strong",
                    "provenance_type": "content_span",
                    "provenance_path": "sources/src-001.md",
                    "line_start": 103,
                    "line_end": 116,
                    "quote": "Only 1 of 8 studies found the predicted effect.",
                    "structured_data": {"supporting": 1, "total": 8},
                    "tags": ["systematic_review"],
                },
                {
                    "primary_question_id": "Q2",
                    "question_ids": ["Q1", "Q2"],
                    "claim_text": "Movement effects were linear.",
                    "claim_type": "result",
                    "provenance_type": "note_span",
                },
            ],
        }
        json_file = _write_json_file(tmp_path, manifest, "evidence.json")
        result = subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"add-evidence failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["results"]["count"] == 2
        assert len(data["results"]["evidence_ids"]) == 2
        assert data["results"]["evidence_ids"][0] == "ev-0001"

    def test_rejects_unknown_source(self, tmp_path):
        """add-evidence returns error if source_id doesn't exist."""
        session_dir = self._setup_session_with_source(tmp_path)

        manifest = {
            "source_id": "src-999",
            "units": [{"claim_text": "test", "claim_type": "result", "provenance_type": "note_span"}],
        }
        json_file = _write_json_file(tmp_path, manifest, "bad.json")
        result = subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert data["status"] == "error"

    def test_empty_units_list(self, tmp_path):
        """add-evidence with empty units returns empty list."""
        session_dir = self._setup_session_with_source(tmp_path)

        manifest = {"source_id": "src-001", "units": []}
        json_file = _write_json_file(tmp_path, manifest, "empty.json")
        result = subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["results"]["count"] == 0


class TestAddEvidenceBatch:
    def _setup_session_with_sources(self, tmp_path):
        """Helper: init session + 2 sources, return session_dir."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        for i, doi in enumerate(["10.1234/batch-a", "10.1234/batch-b"]):
            json_file = _write_json_file(tmp_path, {
                "title": f"Batch Source {i+1}",
                "doi": doi,
                "provider": "test",
            }, f"src{i}.json")
            subprocess.run(
                [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
                 "--from-json", json_file],
                capture_output=True, text=True,
            )
        return session_dir

    def test_batch_insert(self, tmp_path):
        """add-evidence-batch inserts units from multiple manifests."""
        session_dir = self._setup_session_with_sources(tmp_path)

        manifests = [
            {"source_id": "src-001", "units": [
                {"claim_text": "Claim A", "claim_type": "result", "provenance_type": "content_span",
                 "primary_question_id": "Q1"},
            ]},
            {"source_id": "src-002", "units": [
                {"claim_text": "Claim B", "claim_type": "method", "provenance_type": "note_span",
                 "primary_question_id": "Q2"},
                {"claim_text": "Claim C", "claim_type": "limitation", "provenance_type": "abstract",
                 "primary_question_id": "Q2"},
            ]},
        ]
        json_file = _write_json_file(tmp_path, manifests, "batch.json")
        result = subprocess.run(
            [sys.executable, STATE_PY, "add-evidence-batch", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"batch failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["results"]["count"] == 3


class TestEvidenceQuery:
    def _setup_with_evidence(self, tmp_path):
        """Helper: session + source + 3 evidence units."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Query Test Paper", "doi": "10.1234/query-test", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "Result claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1", "line_start": 10, "line_end": 20},
            {"claim_text": "Method claim", "claim_type": "method", "provenance_type": "note_span",
             "primary_question_id": "Q1"},
            {"claim_text": "Limitation claim", "claim_type": "limitation", "provenance_type": "abstract",
             "primary_question_id": "Q2"},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )
        return session_dir

    def test_query_all(self, tmp_path):
        """evidence with no filters returns all units."""
        session_dir = self._setup_with_evidence(tmp_path)
        result, data = _run_state("evidence", "--session-dir", session_dir)
        assert result.returncode == 0
        assert data["results"]["count"] == 3

    def test_filter_by_source(self, tmp_path):
        """evidence --source-id filters by source."""
        session_dir = self._setup_with_evidence(tmp_path)
        result, data = _run_state("evidence", "--session-dir", session_dir, "--source-id", "src-001")
        assert result.returncode == 0
        assert data["results"]["count"] == 3

    def test_filter_by_question(self, tmp_path):
        """evidence --question-id filters by question."""
        session_dir = self._setup_with_evidence(tmp_path)
        result, data = _run_state("evidence", "--session-dir", session_dir, "--question-id", "Q1")
        assert result.returncode == 0
        assert data["results"]["count"] == 2

    def test_filter_by_claim_type(self, tmp_path):
        """evidence --claim-type filters by type."""
        session_dir = self._setup_with_evidence(tmp_path)
        result, data = _run_state("evidence", "--session-dir", session_dir, "--claim-type", "method")
        assert result.returncode == 0
        assert data["results"]["count"] == 1
        assert data["results"]["units"][0]["claim_text"] == "Method claim"

    def test_filter_by_question_ids_membership(self, tmp_path):
        """evidence --question-id matches question_ids, not only primary ids."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Shared Question Paper", "doi": "10.1234/shared-q", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "Primary Q2 claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q2", "question_ids": ["Q2"], "line_start": 1, "line_end": 5},
            {"claim_text": "Shared Q1/Q2 claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q2", "question_ids": ["Q1", "Q2"], "line_start": 10, "line_end": 15},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )

        result, data = _run_state("evidence", "--session-dir", session_dir, "--question-id", "Q1")
        assert result.returncode == 0
        assert data["results"]["count"] == 1
        assert data["results"]["units"][0]["claim_text"] == "Shared Q1/Q2 claim"


class TestLinkFindingEvidence:
    def test_link_and_query(self, tmp_path):
        """link-finding-evidence creates links between findings and evidence."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        # Add source
        json_file = _write_json_file(tmp_path, {
            "title": "Link Test Paper", "doi": "10.1234/link-test", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        # Add evidence
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "Linked claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1"},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )
        # Add finding
        subprocess.run(
            [sys.executable, STATE_PY, "log-finding", "--session-dir", session_dir,
             "--text", "Test finding", "--sources", "src-001", "--question-id", "Q1"],
            capture_output=True, text=True,
        )
        # Link
        result, data = _run_state(
            "link-finding-evidence", "--session-dir", session_dir,
            "--finding-id", "finding-1", "--evidence-ids", "ev-0001",
        )
        assert result.returncode == 0
        assert data["results"]["count"] == 1
        assert "ev-0001" in data["results"]["linked_evidence"]


class TestEvidenceSummary:
    def test_summary_aggregation(self, tmp_path):
        """evidence-summary returns aggregate counts."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Summary Paper", "doi": "10.1234/ev-summary", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "R1", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1", "line_start": 1, "line_end": 5},
            {"claim_text": "M1", "claim_type": "method", "provenance_type": "note_span",
             "primary_question_id": "Q1"},
            {"claim_text": "L1", "claim_type": "limitation", "provenance_type": "abstract",
             "primary_question_id": "Q2"},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )

        result, data = _run_state("evidence-summary", "--session-dir", session_dir)
        assert result.returncode == 0
        assert data["results"]["total"] == 3
        assert data["results"]["by_claim_type"]["result"] == 1
        assert data["results"]["by_claim_type"]["method"] == 1
        assert data["results"]["by_question"]["Q1"] == 2
        assert data["results"]["by_question"]["Q2"] == 1
        assert data["results"]["with_provenance_spans"] == 1

    def test_summary_counts_shared_question_ids(self, tmp_path):
        """evidence-summary counts evidence against all linked question ids."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Shared Summary Paper", "doi": "10.1234/shared-summary", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "Shared result", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q2", "question_ids": ["Q1", "Q2"], "line_start": 1, "line_end": 5},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )

        result, data = _run_state("evidence-summary", "--session-dir", session_dir)
        assert result.returncode == 0
        assert data["results"]["by_question"]["Q1"] == 1
        assert data["results"]["by_question"]["Q2"] == 1


class TestEvidenceInSummary:
    def test_summary_compact_includes_evidence(self, tmp_path):
        """summary --compact includes evidence counts."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Summary Paper", "doi": "10.1234/sum-ev", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "C1", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1"},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )

        result = subprocess.run(
            [sys.executable, STATE_PY, "summary", "--compact", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert data["results"]["evidence_units_count"] == 1
        assert "Q1" in data["results"]["evidence_units_by_question"]

    def test_write_handoff_includes_evidence(self, tmp_path):
        """summary --write-handoff includes only linked evidence rows."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Handoff Paper", "doi": "10.1234/handoff-ev", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "Linked handoff claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1", "relation": "supports", "evidence_strength": "strong"},
            {"claim_text": "Unlinked handoff claim", "claim_type": "background", "provenance_type": "content_span",
             "primary_question_id": "Q1", "relation": "supports", "evidence_strength": "weak"},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )
        subprocess.run(
            [sys.executable, STATE_PY, "log-finding", "--session-dir", session_dir,
             "--text", "Linked finding", "--sources", "src-001", "--question-id", "Q1",
             "--evidence-ids", "ev-0001"],
            capture_output=True, text=True,
        )

        result = subprocess.run(
            [sys.executable, STATE_PY, "summary", "--write-handoff", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Read the handoff file
        handoff_path = os.path.join(session_dir, "synthesis-handoff.json")
        with open(handoff_path) as f:
            handoff = json.load(f)
        assert "evidence_units" in handoff
        assert len(handoff["evidence_units"]) == 1
        assert handoff["evidence_units"][0]["id"] == "ev-0001"
        assert handoff["findings"][0]["evidence_ids"] == ["ev-0001"]
        assert handoff["evidence_total_count"] == 1

    def test_write_handoff_preserves_legacy_question_text(self, tmp_path):
        """summary --write-handoff keeps question text for old findings without question_id."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        subprocess.run(
            [sys.executable, STATE_PY, "log-finding", "--session-dir", session_dir,
             "--text", "Legacy finding", "--sources", "src-001", "--question", "Legacy question"],
            capture_output=True, text=True,
        )

        subprocess.run(
            [sys.executable, STATE_PY, "summary", "--write-handoff", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        handoff_path = os.path.join(session_dir, "synthesis-handoff.json")
        with open(handoff_path) as f:
            handoff = json.load(f)

        assert handoff["findings"][0]["question"] == "Legacy question"
        assert "question_id" not in handoff["findings"][0]

    def test_write_handoff_keeps_truncated_evidence_consistent(self, tmp_path):
        """Truncated handoffs never leave dangling evidence references."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Large Handoff Paper", "doi": "10.1234/large-handoff", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )

        units = []
        for i in range(1, 26):
            units.append({
                "id": f"ev-{i:03d}",
                "claim_text": f"Claim {i} " + ("x" * 900),
                "claim_type": "result",
                "provenance_type": "content_span",
                "primary_question_id": "Q1",
                "relation": "supports",
                "evidence_strength": "strong",
            })
        ef = _write_json_file(tmp_path, {"source_id": "src-001", "units": units}, "bulk-ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )

        for i in range(1, 26):
            subprocess.run(
                [sys.executable, STATE_PY, "log-finding", "--session-dir", session_dir,
                 "--text", f"Finding {i}", "--sources", "src-001", "--question-id", "Q1",
                 "--evidence-ids", f"ev-{i:04d}"],
                capture_output=True, text=True,
            )

        subprocess.run(
            [sys.executable, STATE_PY, "summary", "--write-handoff", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        handoff_path = os.path.join(session_dir, "synthesis-handoff.json")
        with open(handoff_path) as f:
            handoff = json.load(f)

        exported_ids = {row["id"] for row in handoff.get("evidence_units", [])}
        assert handoff["evidence_truncated"] is True
        assert len(exported_ids) < handoff["evidence_total_count"]
        for finding in handoff["findings"]:
            for evidence_id in finding.get("evidence_ids", []):
                assert evidence_id in exported_ids

        unsupported = {finding["id"] for finding in handoff["findings"] if not finding.get("evidence_ids")}
        assert unsupported == set(handoff["findings_without_evidence"])


class TestEvidenceInAudit:
    def test_audit_includes_evidence(self, tmp_path):
        """audit includes evidence counts and warnings."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)
        json_file = _write_json_file(tmp_path, {
            "title": "Audit Paper", "doi": "10.1234/audit-ev", "provider": "test",
        }, "src.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-source", "--session-dir", session_dir,
             "--from-json", json_file],
            capture_output=True, text=True,
        )
        manifest = {"source_id": "src-001", "units": [
            {"claim_text": "Audit claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1"},
        ]}
        ef = _write_json_file(tmp_path, manifest, "ev.json")
        subprocess.run(
            [sys.executable, STATE_PY, "add-evidence", "--session-dir", session_dir,
             "--from-json", ef],
            capture_output=True, text=True,
        )
        # Add a finding without linking it to evidence
        subprocess.run(
            [sys.executable, STATE_PY, "log-finding", "--session-dir", session_dir,
             "--text", "Unlinked finding", "--sources", "src-001", "--question-id", "Q1"],
            capture_output=True, text=True,
        )

        result = subprocess.run(
            [sys.executable, STATE_PY, "audit", "--brief", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert data["results"]["evidence_units_total"] == 1
        assert "finding-1" in data["results"].get("findings_without_evidence", [])
