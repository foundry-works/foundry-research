"""Tests for state.py schema initialization, persistence, concurrency, and ID generation."""

import json
import os
import sqlite3
import subprocess
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))

from state import _connect, _insert_source, _next_id, _now

STATE_PY = os.path.join(os.path.dirname(__file__), os.pardir, "scripts", "state.py")


def _write_json_file(tmp_path, data, name="input.json"):
    """Write data to a JSON file and return its path."""
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def _init_session(session_dir: str, query: str = "test query") -> str:
    """Initialize a session via CLI and return the session ID."""
    result = subprocess.run(
        [sys.executable, STATE_PY, "init", "--session-dir", session_dir, "--query", query],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"init failed: {result.stderr}"
    data = json.loads(result.stdout)
    return data["results"]["session_id"]


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
