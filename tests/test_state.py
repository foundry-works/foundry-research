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

        expected = {"sessions", "brief", "searches", "sources", "findings", "gaps", "metrics"}
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
        assert data["results"]["evidence_ids"][0] == "ev-001"

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
            "--finding-id", "finding-1", "--evidence-ids", "ev-001",
        )
        assert result.returncode == 0
        assert data["results"]["count"] == 1
        assert "ev-001" in data["results"]["linked_evidence"]


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
            {"id": "ev-001", "claim_text": "Linked handoff claim", "claim_type": "result", "provenance_type": "content_span",
             "primary_question_id": "Q1", "relation": "supports", "evidence_strength": "strong"},
            {"id": "ev-002", "claim_text": "Unlinked handoff claim", "claim_type": "background", "provenance_type": "content_span",
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
             "--evidence-ids", "ev-001"],
            capture_output=True, text=True,
        )

        result = subprocess.run(
            [sys.executable, STATE_PY, "summary", "--write-handoff", "--session-dir", session_dir],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        # Read the handoff file
        handoff_path = os.path.join(session_dir, "synthesis-handoff.json")
        with open(handoff_path) as f:
            handoff = json.load(f)
        assert "evidence_units" in handoff
        assert len(handoff["evidence_units"]) == 1
        assert handoff["evidence_units"][0]["id"] == "ev-001"
        assert handoff["findings"][0]["evidence_ids"] == ["ev-001"]
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
                 "--evidence-ids", f"ev-{i:03d}"],
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
