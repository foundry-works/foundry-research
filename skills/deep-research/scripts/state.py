#!/usr/bin/env python3
"""Session state tracker — SQLite-backed search history, source dedup, findings, gaps, and metrics."""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

# Add parent directory so _shared imports work when run from any location
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shared.config import get_session_dir, write_session_marker
from _shared.doi_utils import canonicalize_url, normalize_doi
from _shared.output import error_response, log, set_quiet, success_response

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=20000;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brief (
    session_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    questions TEXT NOT NULL,
    completeness_criteria TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    search_mode TEXT NOT NULL DEFAULT 'keyword',
    search_type TEXT NOT NULL DEFAULT 'manual',
    result_count INTEGER NOT NULL,
    ingested_count INTEGER,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    UNIQUE(session_id, provider, query, search_mode)
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    year INTEGER,
    abstract TEXT,
    doi TEXT,
    url TEXT,
    pdf_url TEXT,
    venue TEXT,
    citation_count INTEGER,
    type TEXT DEFAULT 'academic',
    provider TEXT NOT NULL,
    content_file TEXT,
    pdf_file TEXT,
    is_read INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    quality TEXT,
    relevance_score REAL,
    relevance_rationale TEXT,
    status TEXT DEFAULT 'pending',
    added_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_sources_doi ON sources(session_id, doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(session_id, url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_title ON sources(session_id, title);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    text TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    question TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS gaps (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    text TEXT NOT NULL,
    question TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    metric TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT DEFAULT 'USD',
    period TEXT,
    source TEXT NOT NULL,
    filed_date TEXT,
    logged_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    UNIQUE(session_id, ticker, metric, period, source)
);
"""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column_name, column_definition)
    ("searches", "ingested_count", "INTEGER"),
    ("searches", "search_mode", "TEXT NOT NULL DEFAULT 'keyword'"),
    ("searches", "search_type", "TEXT NOT NULL DEFAULT 'manual'"),
    ("sources", "relevance_score", "REAL"),
    ("sources", "relevance_rationale", "TEXT"),
]


def _migrate_schema(db_path: str) -> None:
    """Run ALTER TABLE migrations in a dedicated writable connection.

    Single source of truth for the migration column list — called once
    before the main connection is returned, regardless of readonly mode.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}", uri=True)
        try:
            for table, col, defn in _MIGRATIONS:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # column already exists

            # Migrate UNIQUE constraint on searches to include search_mode.
            # SQLite can't ALTER constraints, so we drop the old unique index
            # (if it exists as a separate index) and create one that includes
            # search_mode. The CREATE TABLE constraint is already updated for
            # new databases; this handles databases created before the change.
            try:
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_searches_unique_v2 "
                    "ON searches(session_id, provider, query, search_mode)"
                )
                conn.commit()
            except sqlite3.OperationalError:
                pass  # index already exists or table doesn't exist yet
        finally:
            conn.close()
    except Exception:
        pass  # DB may not exist yet or truly readonly filesystem


def _connect(session_dir: str, readonly: bool = False) -> sqlite3.Connection:
    db_path = os.path.join(session_dir, "state.db")
    if readonly and not os.path.exists(db_path):
        error_response([f"state.db not found in {session_dir}"])
    _migrate_schema(db_path)
    uri = f"file:{db_path}" + ("?mode=ro" if readonly else "")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _get_session_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT id FROM sessions LIMIT 1").fetchone()
    if not row:
        error_response(["No session found. Run init first."])
    return row["id"]


def _next_id(conn: sqlite3.Connection, table: str, prefix: str, session_id: str) -> str:
    row = conn.execute(f"SELECT COUNT(*) as c FROM {table} WHERE session_id = ?", (session_id,)).fetchone()
    return f"{prefix}-{row['c'] + 1:03d}" if prefix == "src" else f"{prefix}-{row['c'] + 1}"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _title_similarity(a: str, b: str) -> float:
    """Token-overlap similarity between two titles."""
    tokens_a = set(re.findall(r'\w+', a.lower()))
    tokens_b = set(re.findall(r'\w+', b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / max(len(tokens_a), len(tokens_b))


def _authors_overlap(a_json: str, b_authors: list) -> bool:
    """Check if >= 50% of authors overlap."""
    try:
        a_list = json.loads(a_json) if isinstance(a_json, str) else a_json
    except (json.JSONDecodeError, TypeError):
        return False
    if not a_list or not b_authors:
        return False
    # Normalize: lowercase, strip whitespace
    norm_a = {a.lower().strip() for a in a_list if a}
    norm_b = {b.lower().strip() for b in b_authors if b}
    if not norm_a or not norm_b:
        return False
    overlap = len(norm_a & norm_b)
    return overlap >= len(min(norm_a, norm_b, key=len)) * 0.5


def _check_duplicate(conn: sqlite3.Connection, session_id: str,
                     doi: str | None = None, url: str | None = None,
                     title: str | None = None, authors: list | None = None,
                     year: int | None = None) -> tuple[bool, str | None]:
    """3-tier dedup check. Returns (is_dup, matched_source_id)."""
    # Tier 1: DOI
    if doi:
        norm = normalize_doi(doi)
        row = conn.execute(
            "SELECT id FROM sources WHERE session_id = ? AND doi = ?",
            (session_id, norm)
        ).fetchone()
        if row:
            return True, row["id"]

    # Tier 2: URL
    if url:
        canon = canonicalize_url(url)
        row = conn.execute(
            "SELECT id FROM sources WHERE session_id = ? AND url = ?",
            (session_id, canon)
        ).fetchone()
        if row:
            return True, row["id"]

    # Tier 3: Fuzzy title
    if title and len(title) >= 15:
        rows = conn.execute(
            "SELECT id, title, authors, year FROM sources WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        for row in rows:
            sim = _title_similarity(title, row["title"])
            if sim > 0.95:
                return True, row["id"]
            if sim >= 0.85:
                # Gray zone: require author + year match
                if authors and _authors_overlap(row["authors"], authors):
                    if year and row["year"] and abs(year - row["year"]) <= 1:
                        return True, row["id"]

    return False, None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Common stop words shared across term extraction. Context-specific extras
# can be passed via the extra_stop parameter.
_STOP_WORDS = frozenset({
    "this", "that", "with", "from", "have", "been", "only", "about", "more",
    "than", "some", "into", "also", "very", "just", "most", "does", "each",
    "after", "before", "which", "their", "there", "where", "when", "what",
    "should", "would", "could", "will", "best", "many", "much",
})

_STRIP_CHARS = ".,;:()\"'?!"


def _extract_terms(texts: list[str], extra_stop: set[str] | None = None) -> list[str]:
    """Extract keywords (4+ chars, stop-filtered) from free text. Deduped, order preserved."""
    stop = _STOP_WORDS | extra_stop if extra_stop else _STOP_WORDS
    terms: list[str] = []
    for text in texts:
        for w in text.lower().split():
            w = w.strip(_STRIP_CHARS)
            if len(w) >= 4 and w not in stop:
                terms.append(w)
    return list(dict.fromkeys(terms))


def _extract_question_terms(questions: list) -> list[str]:
    """Extract keywords from research questions (str or {text: str} dicts)."""
    texts = [q if isinstance(q, str) else q.get("text", str(q)) for q in questions]
    return _extract_terms(texts)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    session_dir = args.session_dir
    os.makedirs(session_dir, exist_ok=True)
    for subdir in ("sources", "sources/metadata", "notes"):
        os.makedirs(os.path.join(session_dir, subdir), exist_ok=True)

    journal_path = os.path.join(session_dir, "journal.md")
    if not os.path.exists(journal_path):
        with open(journal_path, "w") as f:
            f.write(f"# Research Journal\n\nSession initialized: {_now()}\n\n")

    conn = _connect(session_dir)
    conn.executescript(_SCHEMA)

    # Generate session ID from timestamp
    now = datetime.now(timezone.utc)
    session_id = f"dr-{now.strftime('%Y%m%d-%H%M%S')}"

    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, query, created_at) VALUES (?, ?, ?)",
        (session_id, args.query, _now())
    )
    conn.commit()
    _regenerate_snapshot(session_dir, conn, session_id)
    conn.close()

    # Write marker file for auto-discovery by subsequent commands
    write_session_marker(session_dir)
    log(f"Session marker written to .deep-research-session (auto-discovery enabled)")

    success_response({"session_id": session_id, "session_dir": session_dir})


def _regenerate_snapshot(session_dir: str, conn: sqlite3.Connection, sid: str) -> str:
    """Regenerate state.json from SQLite. Called after every write operation."""
    session = dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone())

    brief_row = conn.execute("SELECT * FROM brief WHERE session_id = ?", (sid,)).fetchone()
    brief = None
    if brief_row:
        brief = dict(brief_row)
        brief["questions"] = json.loads(brief["questions"])

    searches = [dict(r) for r in conn.execute("SELECT * FROM searches WHERE session_id = ? ORDER BY id", (sid,)).fetchall()]
    sources = [dict(r) for r in conn.execute("SELECT * FROM sources WHERE session_id = ? ORDER BY id", (sid,)).fetchall()]
    for s in sources:
        s["authors"] = json.loads(s["authors"]) if s.get("authors") else []
        s["tags"] = json.loads(s["tags"]) if s.get("tags") else []

    findings = [dict(r) for r in conn.execute("SELECT * FROM findings WHERE session_id = ? ORDER BY id", (sid,)).fetchall()]
    for f in findings:
        f["sources"] = json.loads(f["sources"]) if f.get("sources") else []

    gaps = [dict(r) for r in conn.execute("SELECT * FROM gaps WHERE session_id = ? ORDER BY id", (sid,)).fetchall()]

    metrics_rows = conn.execute("SELECT * FROM metrics WHERE session_id = ? ORDER BY ticker, metric", (sid,)).fetchall()
    metrics_list = [dict(r) for r in metrics_rows]

    sources_by_type: dict[str, int] = {}
    sources_by_provider: dict[str, int] = {}
    for s in sources:
        t = s.get("type", "unknown")
        sources_by_type[t] = sources_by_type.get(t, 0) + 1
        p = s.get("provider", "unknown")
        sources_by_provider[p] = sources_by_provider.get(p, 0) + 1

    export_data = {
        "session_id": session["id"],
        "query": session["query"],
        "created_at": session["created_at"],
        "brief": brief,
        "searches": searches,
        "sources": sources,
        "findings": findings,
        "gaps": gaps,
        "metrics": metrics_list,
        "stats": {
            "total_searches": len(searches),
            "total_sources": len(sources),
            "sources_by_type": sources_by_type,
            "sources_by_provider": sources_by_provider,
        },
    }

    export_path = os.path.join(session_dir, "state.json")
    with open(export_path, "w") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    return export_path


def cmd_export(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    path = _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"path": path})


def cmd_set_brief(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_dict(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    questions = data.get("questions", [])
    conn.execute(
        """INSERT OR REPLACE INTO brief (session_id, scope, questions, completeness_criteria, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (sid, data["scope"], json.dumps(questions), data.get("completeness_criteria"), _now())
    )
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"scope": data["scope"], "questions": questions})


def cmd_log_search(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    search_id = _next_id(conn, "searches", "search", sid)

    ingested_count = getattr(args, "ingested_count", None)
    search_mode = getattr(args, "search_mode", "keyword") or "keyword"
    search_type = getattr(args, "search_type", "manual") or "manual"
    try:
        conn.execute(
            "INSERT INTO searches (id, session_id, provider, query, search_mode, search_type, result_count, ingested_count, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (search_id, sid, args.provider, args.query, search_mode, search_type, args.result_count, ingested_count, _now())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        success_response({"duplicate": True, "provider": args.provider, "query": args.query})
        return

    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": search_id, "provider": args.provider, "query": args.query, "search_mode": search_mode, "search_type": search_type})


def cmd_add_source(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_dict(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    result = _insert_source(conn, sid, data, session_dir=args.session_dir)
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response(result)


def cmd_add_sources(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_list(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)

    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    added = []
    duplicates = []
    errors = []

    for i, source in enumerate(data):
        try:
            result = _insert_source(conn, sid, source, session_dir=args.session_dir)
            if result.get("duplicate"):
                duplicates.append({"index": i, "title": source.get("title", ""), "matched": result["matched"]})
            else:
                added.append({"index": i, "id": result["id"], "title": source.get("title", "")})
        except Exception as e:
            errors.append({"index": i, "error": str(e)})

    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"added": added, "duplicates": duplicates, "errors": errors})


def _insert_source(conn: sqlite3.Connection, session_id: str, data: dict,
                   session_dir: str | None = None) -> dict:
    """Insert a single source with dedup. Returns result dict.

    When session_dir is provided, also writes a metadata JSON file at ingestion
    time so that all sources are inspectable on disk, not just downloaded ones.
    """
    doi = normalize_doi(data["doi"]) if data.get("doi") else None
    url = canonicalize_url(data.get("url", "")) or None
    title = data.get("title", "")
    authors = data.get("authors", [])
    year = data.get("year")

    is_dup, matched_id = _check_duplicate(conn, session_id, doi=doi, url=url,
                                           title=title, authors=authors, year=year)
    if is_dup:
        return {"duplicate": True, "matched": matched_id}

    source_id = _next_id(conn, "sources", "src", session_id)
    conn.execute(
        """INSERT INTO sources (id, session_id, title, authors, year, abstract, doi, url,
           pdf_url, venue, citation_count, type, provider, content_file, pdf_file,
           relevance_score, added_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, session_id, title, json.dumps(authors), year,
         data.get("abstract"), doi, url, data.get("pdf_url"),
         data.get("venue"), data.get("citation_count"),
         data.get("type", "academic"), data.get("provider", "unknown"),
         data.get("content_file"), data.get("pdf_file"),
         data.get("relevance_score"), _now())
    )

    # Write metadata JSON at ingestion time so triage and audit have access
    # to all source metadata on disk, not just downloaded sources.
    if session_dir:
        _write_ingestion_metadata(session_dir, source_id, data, doi, url)

    return {"id": source_id, "title": title, "duplicate": False}


def _write_ingestion_metadata(session_dir: str, source_id: str, data: dict,
                              doi: str | None, url: str | None) -> None:
    """Write a partial metadata JSON file at source ingestion time.

    If a metadata file already exists (e.g., from a prior search that found the
    same source via a different path), merge rather than overwrite.
    """
    try:
        metadata_dir = os.path.join(session_dir, "sources", "metadata")
        os.makedirs(metadata_dir, exist_ok=True)
        filepath = os.path.join(metadata_dir, f"{source_id}.json")

        meta = {
            "id": source_id,
            "title": data.get("title", ""),
            "authors": data.get("authors", []),
            "doi": doi,
            "url": url,
            "provider": data.get("provider", "unknown"),
            "year": data.get("year"),
            "venue": data.get("venue"),
            "citation_count": data.get("citation_count"),
            "abstract": data.get("abstract"),
            "type": data.get("type", "academic"),
            "pdf_url": data.get("pdf_url"),
        }
        # Remove None values to keep files clean
        meta = {k: v for k, v in meta.items() if v is not None}

        if os.path.exists(filepath):
            # Merge with existing — don't overwrite fields that already have values
            try:
                existing = json.loads(open(filepath, encoding="utf-8").read())
                for k, v in meta.items():
                    if k not in existing or existing[k] is None:
                        existing[k] = v
                meta = existing
            except (json.JSONDecodeError, OSError):
                pass  # overwrite corrupt file

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception:
        pass  # best-effort — don't fail the insert


def cmd_check_dup(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    is_dup, matched = _check_duplicate(conn, sid, doi=args.doi, url=args.url, title=args.title)
    conn.close()
    success_response({"is_duplicate": is_dup, "matched": matched})


def cmd_check_dup_batch(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_list(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)

    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    results = []
    for i, item in enumerate(data):
        is_dup, matched = _check_duplicate(
            conn, sid,
            doi=item.get("doi"), url=item.get("url"), title=item.get("title"),
            authors=item.get("authors"), year=item.get("year")
        )
        results.append({"index": i, "is_dup": is_dup, "matched": matched})

    conn.close()
    success_response(results)


def _normalize_question(conn: sqlite3.Connection, session_id: str, question: str) -> str:
    """Normalize question text by fuzzy-matching against brief questions.

    If the incoming question is a close match (token overlap > 0.9) to a brief
    question, substitute the brief text. This prevents truncated or slightly
    reworded questions from creating duplicate keys in findings_by_question.
    """
    if not question:
        return question
    try:
        row = conn.execute(
            "SELECT questions FROM brief WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return question
        brief_questions = json.loads(row["questions"])
        if not isinstance(brief_questions, list):
            return question
        best_match = question
        best_score = 0.0
        for bq in brief_questions:
            if not isinstance(bq, str):
                continue
            score = _token_overlap(question, bq)
            if score > best_score:
                best_score = score
                best_match = bq
        if best_score > 0.9 and best_match != question:
            log(f"Normalized question text (overlap={best_score:.2f}): {question!r} → {best_match!r}")
            return best_match
    except Exception:
        pass
    return question


def cmd_log_finding(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    finding_id = _next_id(conn, "findings", "finding", sid)

    question = _normalize_question(conn, sid, args.question)
    source_ids = [s.strip() for s in args.sources.split(",")] if args.sources else []
    conn.execute(
        "INSERT INTO findings (id, session_id, text, sources, question, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (finding_id, sid, args.text, json.dumps(source_ids), question, _now())
    )
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": finding_id, "text": args.text})


def _token_overlap(a: str, b: str) -> float:
    """Token-overlap ratio between two text strings (case-insensitive)."""
    tokens_a = set(re.findall(r'\w+', a.lower()))
    tokens_b = set(re.findall(r'\w+', b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / max(len(tokens_a), len(tokens_b))


def cmd_deduplicate_findings(args):
    """Merge cross-question duplicate findings based on source overlap and text similarity."""
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT id, text, sources, question FROM findings WHERE session_id = ? ORDER BY id",
        (sid,)
    ).fetchall()
    findings = []
    for r in rows:
        sources = json.loads(r["sources"]) if r["sources"] else []
        findings.append({
            "id": r["id"],
            "text": r["text"],
            "sources": set(sources),
            "question": r["question"] or "",
        })

    original_count = len(findings)
    threshold = args.threshold

    # Build candidate pairs: findings that share at least one source citation
    merged_ids: set[str] = set()  # IDs absorbed into another finding
    merge_map: dict[str, list[str]] = {}  # kept_id -> list of also_relevant_to questions

    for i in range(len(findings)):
        if findings[i]["id"] in merged_ids:
            continue
        for j in range(i + 1, len(findings)):
            if findings[j]["id"] in merged_ids:
                continue
            fi, fj = findings[i], findings[j]
            # Require overlapping source citations
            if not (fi["sources"] & fj["sources"]):
                continue
            # Compute text similarity
            overlap = _token_overlap(fi["text"], fj["text"])
            if overlap < threshold:
                continue
            # Merge: keep the one with more source citations
            if len(fj["sources"]) > len(fi["sources"]):
                keeper, absorbed = fj, fi
            else:
                keeper, absorbed = fi, fj
            merged_ids.add(absorbed["id"])
            # Track cross-question relevance
            if absorbed["question"] and absorbed["question"] != keeper["question"]:
                merge_map.setdefault(keeper["id"], []).append(absorbed["question"])

    # Delete merged findings and update keeper texts with also_relevant_to
    if merged_ids:
        placeholders = ",".join("?" for _ in merged_ids)
        conn.execute(
            f"DELETE FROM findings WHERE id IN ({placeholders}) AND session_id = ?",
            [*merged_ids, sid]
        )
        # For keepers with cross-question relevance, append the info to their text
        for keeper_id, questions in merge_map.items():
            q_list = "; ".join(questions)
            conn.execute(
                "UPDATE findings SET text = text || ? WHERE id = ? AND session_id = ?",
                (f" [Also relevant to: {q_list}]", keeper_id, sid)
            )
        conn.commit()
        _regenerate_snapshot(args.session_dir, conn, sid)

    merged_count = len(merged_ids)
    remaining_count = original_count - merged_count
    conn.close()
    success_response({
        "merged": merged_count,
        "remaining": remaining_count,
        "original": original_count,
    })


def cmd_log_gap(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    gap_id = _next_id(conn, "gaps", "gap", sid)

    conn.execute(
        "INSERT INTO gaps (id, session_id, text, question, status, timestamp) VALUES (?, ?, ?, ?, 'open', ?)",
        (gap_id, sid, args.text, args.question, _now())
    )
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": gap_id, "text": args.text})


def cmd_resolve_gap(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    cur = conn.execute(
        "UPDATE gaps SET status = 'resolved' WHERE id = ? AND session_id = ?",
        (args.gap_id, sid)
    )
    if cur.rowcount == 0:
        conn.close()
        error_response([f"Gap {args.gap_id} not found"])
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": args.gap_id, "status": "resolved"})


def cmd_gap_search_plan(args):
    """Generate suggested search queries for each open gap based on gap text, question, and existing sources."""
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    # Load open gaps
    gaps = [dict(r) for r in conn.execute(
        "SELECT * FROM gaps WHERE session_id = ? AND status = 'open' ORDER BY id", (sid,)
    ).fetchall()]

    if not gaps:
        conn.close()
        return success_response({"gaps": [], "message": "No open gaps found"})

    # Load existing searches to avoid suggesting duplicates
    existing_searches = conn.execute(
        "SELECT provider, query FROM searches WHERE session_id = ?", (sid,)
    ).fetchall()
    existing_queries = {(r["provider"], r["query"].lower()) for r in existing_searches}

    # Load sources with high citation counts for citation chase suggestions
    sources = conn.execute(
        "SELECT id, title, citation_count, provider FROM sources WHERE session_id = ? AND citation_count > 0 ORDER BY citation_count DESC LIMIT 50",
        (sid,)
    ).fetchall()

    conn.close()

    plans = []
    for gap in gaps:
        gap_text = gap["text"]
        gap_question = gap.get("question", "")

        # Extract key terms from gap text and associated question
        gap_extra = {"coverage", "insufficient", "sources", "evidence", "research", "needs"}
        texts = [gap_text] + ([gap_question] if gap_question else [])
        all_terms = _extract_terms(texts, extra_stop=gap_extra)

        suggested_searches = []

        # Suggestion 1: keyword search using gap + question terms
        if len(all_terms) >= 2:
            keyword_query = " ".join(all_terms[:5])
            suggested_searches.append({
                "type": "keyword",
                "query": keyword_query,
                "providers": ["semantic_scholar", "pubmed", "openalex"],
                "rationale": f"Keyword search using terms from gap text and question"
            })

        # Suggestion 2: find most-cited source related to this gap for citation chase
        gap_relevant_sources = []
        for s in sources:
            title_lower = (s["title"] or "").lower()
            if any(t in title_lower for t in all_terms[:3]):
                gap_relevant_sources.append(dict(s))
        if gap_relevant_sources:
            best = gap_relevant_sources[0]
            suggested_searches.append({
                "type": "citation_chase",
                "source_id": best["id"],
                "source_title": best["title"],
                "citation_count": best["citation_count"],
                "rationale": f"Citation chase on most-cited relevant source ({best['citation_count']} citations)"
            })

        # Mark which suggestions are already covered by existing searches
        for s in suggested_searches:
            if s["type"] == "keyword":
                s["already_searched"] = any(
                    s["query"].lower() in eq for _, eq in existing_queries
                )

        plans.append({
            "gap_id": gap["id"],
            "gap_text": gap_text,
            "question": gap_question,
            "key_terms": all_terms[:8],
            "suggested_searches": suggested_searches,
        })

    success_response({"gaps": plans, "total_open": len(plans)})


def cmd_searches(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT id, provider, query, search_mode, search_type, result_count, ingested_count, timestamp FROM searches WHERE session_id = ? ORDER BY id",
        (sid,)
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


def cmd_sources(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    # --providers: return only provider distribution counts (no source list)
    if getattr(args, "providers", False):
        rows = conn.execute(
            "SELECT provider, COUNT(*) as count FROM sources WHERE session_id = ? GROUP BY provider ORDER BY count DESC",
            (sid,)
        ).fetchall()
        conn.close()
        success_response({p["provider"]: p["count"] for p in rows})
        return

    # Determine which columns to SELECT
    _all_source_cols = ("id", "title", "type", "provider", "doi", "url",
                        "citation_count", "content_file", "pdf_file", "quality", "added_at")
    _compact_cols = ("id", "title", "quality", "content_file")

    fields = getattr(args, "fields", None)
    compact = getattr(args, "compact", False)

    if compact and not fields:
        select_cols = _compact_cols
    elif fields:
        requested = [f.strip() for f in fields.split(",")]
        invalid = [f for f in requested if f not in _all_source_cols]
        if invalid:
            conn.close()
            error_response([f"Invalid field(s): {', '.join(invalid)}. Allowed: {', '.join(_all_source_cols)}"])
            return
        select_cols = tuple(requested)
    else:
        select_cols = _all_source_cols

    # Build query with optional filters
    clauses = ["session_id = ?"]
    params: list = [sid]

    title_contains = getattr(args, "title_contains", None)
    if title_contains:
        clauses.append("title LIKE ?")
        params.append(f"%{title_contains}%")

    min_citations = getattr(args, "min_citations", None)
    if min_citations is not None:
        clauses.append("citation_count >= ?")
        params.append(min_citations)

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT {', '.join(select_cols)} FROM sources WHERE {where} ORDER BY id",
        params
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


def cmd_get_source(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    row = conn.execute("SELECT * FROM sources WHERE id = ? AND session_id = ?", (args.id, sid)).fetchone()
    if not row:
        conn.close()
        error_response([f"Source {args.id} not found"])

    result = dict(row)
    result["authors"] = json.loads(result["authors"]) if result.get("authors") else []
    conn.close()
    success_response(result)


def cmd_update_source(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_dict(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    # Verify source exists
    row = conn.execute("SELECT * FROM sources WHERE id = ? AND session_id = ?", (args.id, sid)).fetchone()
    if not row:
        conn.close()
        error_response([f"Source {args.id} not found"])

    # Merge: only update non-null fields from data
    updatable = ("title", "authors", "year", "abstract", "doi", "url", "pdf_url",
                 "venue", "citation_count", "type", "provider", "content_file", "pdf_file",
                 "is_read", "tags", "quality", "status")
    sets = []
    vals = []
    for field in updatable:
        if field in data and data[field] is not None:
            if field in ("authors", "tags"):
                sets.append(f"{field} = ?")
                vals.append(json.dumps(data[field]))
            elif field == "doi":
                sets.append(f"{field} = ?")
                vals.append(normalize_doi(data[field]))
            elif field == "url":
                sets.append(f"{field} = ?")
                vals.append(canonicalize_url(data[field]))
            else:
                sets.append(f"{field} = ?")
                vals.append(data[field])

    if not sets:
        conn.close()
        success_response({"id": args.id, "updated": False})
        return

    vals.extend([args.id, sid])
    conn.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id = ? AND session_id = ?", vals)
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": args.id, "updated": True, "fields": [s.split(" = ")[0] for s in sets]})


def cmd_summary(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    # Brief
    brief_data = None
    brief = conn.execute("SELECT * FROM brief WHERE session_id = ?", (sid,)).fetchone()
    if brief:
        brief_data = {
            "scope": brief["scope"],
            "questions": json.loads(brief["questions"]),
            "completeness_criteria": brief["completeness_criteria"],
        }

    # Searches
    search_count = conn.execute("SELECT COUNT(*) as c FROM searches WHERE session_id = ?", (sid,)).fetchone()["c"]

    # Sources
    source_count = conn.execute("SELECT COUNT(*) as c FROM sources WHERE session_id = ?", (sid,)).fetchone()["c"]
    sources_by_type: dict[str, int] = {}
    sources_by_provider: dict[str, int] = {}
    source_rows = conn.execute("SELECT id, title, type, provider, quality FROM sources WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    source_list = []
    for r in source_rows:
        t = r["type"] or "unknown"
        sources_by_type[t] = sources_by_type.get(t, 0) + 1
        p = r["provider"] or "unknown"
        sources_by_provider[p] = sources_by_provider.get(p, 0) + 1
        source_list.append({"id": r["id"], "title": r["title"], "type": t, "provider": p})

    # Findings
    finding_rows = conn.execute("SELECT * FROM findings WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    findings_list = []
    for r in finding_rows:
        findings_list.append({
            "id": r["id"], "text": r["text"],
            "sources": json.loads(r["sources"]) if r["sources"] else [],
            "question": r["question"],
        })

    # Gaps
    gap_rows = conn.execute("SELECT * FROM gaps WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    gaps_list = []
    for r in gap_rows:
        gaps_list.append({"id": r["id"], "text": r["text"], "question": r["question"], "status": r["status"]})

    # Metrics
    metric_rows = conn.execute(
        "SELECT ticker, metric, value, period, source FROM metrics WHERE session_id = ? ORDER BY ticker, metric", (sid,)
    ).fetchall()
    metrics_list = [dict(r) for r in metric_rows]

    conn.close()

    full_result = {
        "brief": brief_data,
        "search_count": search_count,
        "source_count": source_count,
        "sources_by_type": sources_by_type,
        "sources_by_provider": sources_by_provider,
        "sources": source_list,
        "findings": findings_list,
        "gaps": gaps_list,
        "metrics": metrics_list,
    }

    # --write-handoff: write full summary to file, return only path + counts
    if getattr(args, "write_handoff", False):
        # Build source quality report from DB quality field + on-disk notes
        notes_dir = os.path.join(args.session_dir, "notes")
        quality_tiers: dict[str, list[str]] = {
            "on_topic_with_evidence": [],
            "abstract_only_relevant": [],
            "degraded_unread": [],
            "mismatched": [],
            "reader_validated": [],
        }
        for r in source_rows:
            sid_val = r["id"]
            q = r["quality"] or ""
            has_note = os.path.exists(os.path.join(notes_dir, f"{sid_val}.md"))
            if q == "mismatched":
                quality_tiers["mismatched"].append(sid_val)
            elif q == "reader_validated":
                quality_tiers["reader_validated"].append(sid_val)
            elif q == "abstract_only":
                quality_tiers["abstract_only_relevant"].append(sid_val)
            elif q == "degraded" and not has_note:
                quality_tiers["degraded_unread"].append(sid_val)
            elif has_note:
                quality_tiers["on_topic_with_evidence"].append(sid_val)

        full_result["source_quality_report"] = {
            k: {"count": len(v), "ids": v} for k, v in quality_tiers.items()
        }

        handoff_path = os.path.join(args.session_dir, "synthesis-handoff.json")
        with open(handoff_path, "w") as f:
            json.dump(full_result, f, indent=2)
        rel_path = os.path.relpath(handoff_path)
        success_response({
            "path": rel_path,
            "findings_count": len(findings_list),
            "gaps_count": len(gaps_list),
            "source_count": source_count,
        })
        return

    # --compact: counts and coverage indicators only
    if getattr(args, "compact", False):
        # Build findings-per-question count map
        findings_by_question: dict[str, int] = {}
        for f in findings_list:
            q = f.get("question") or "unassigned"
            findings_by_question[q] = findings_by_question.get(q, 0) + 1

        success_response({
            "brief": {"questions": brief_data["questions"]} if brief_data else None,
            "search_count": search_count,
            "source_count": source_count,
            "sources_by_type": sources_by_type,
            "sources_by_provider": sources_by_provider,
            "findings_count": len(findings_list),
            "findings_by_question": findings_by_question,
            "gaps": gaps_list,
        })
        return

    success_response(full_result)


# ---------------------------------------------------------------------------
# Missing commands: mark-read, set-status, add-tag, list-sources, search-sources, set-quality
# ---------------------------------------------------------------------------

def cmd_mark_read(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    cur = conn.execute(
        "UPDATE sources SET is_read = 1 WHERE id = ? AND session_id = ?",
        (args.id, sid)
    )
    if cur.rowcount == 0:
        conn.close()
        error_response([f"Source {args.id} not found"])

    # Auto-upgrade degraded → reader_validated if a note file exists.
    # A reader that successfully extracted content and wrote a note is strong
    # evidence that the source is usable despite initial quality concerns
    # (e.g., PDF raw-text fallback that's actually readable).
    quality_upgraded = False
    row = conn.execute(
        "SELECT quality FROM sources WHERE id = ? AND session_id = ?",
        (args.id, sid)
    ).fetchone()
    if row and row["quality"] == "degraded":
        note_path = os.path.join(args.session_dir, "notes", f"{args.id}.md")
        if os.path.exists(note_path):
            conn.execute(
                "UPDATE sources SET quality = 'reader_validated' WHERE id = ? AND session_id = ?",
                (args.id, sid)
            )
            quality_upgraded = True

    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    result = {"id": args.id, "is_read": True}
    if quality_upgraded:
        result["quality_upgraded"] = "degraded → reader_validated"
    success_response(result)


def cmd_set_status(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    cur = conn.execute(
        "UPDATE sources SET status = ? WHERE id = ? AND session_id = ?",
        (args.status, args.id, sid)
    )
    if cur.rowcount == 0:
        conn.close()
        error_response([f"Source {args.id} not found"])
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": args.id, "status": args.status})


def cmd_add_tag(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    row = conn.execute("SELECT tags FROM sources WHERE id = ? AND session_id = ?", (args.id, sid)).fetchone()
    if not row:
        conn.close()
        error_response([f"Source {args.id} not found"])

    tags = json.loads(row["tags"]) if row["tags"] else []
    if args.tag not in tags:
        tags.append(args.tag)
    conn.execute("UPDATE sources SET tags = ? WHERE id = ? AND session_id = ?",
                 (json.dumps(tags), args.id, sid))
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": args.id, "tags": tags})


def cmd_list_sources(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT id, title, type, provider, doi, url, is_read, status, quality, tags, added_at FROM sources WHERE session_id = ? ORDER BY id",
        (sid,)
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        results.append(d)
    conn.close()
    success_response(results)


def cmd_search_sources(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    query = f"%{args.query}%"
    rows = conn.execute(
        """SELECT id, title, type, provider, doi, url, abstract, is_read, status
           FROM sources WHERE session_id = ? AND (title LIKE ? OR abstract LIKE ? OR doi LIKE ? OR url LIKE ?)
           ORDER BY id""",
        (sid, query, query, query, query)
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


def cmd_set_quality(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    cur = conn.execute(
        "UPDATE sources SET quality = ? WHERE id = ? AND session_id = ?",
        (args.quality, args.id, sid)
    )
    if cur.rowcount == 0:
        conn.close()
        error_response([f"Source {args.id} not found"])
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": args.id, "quality": args.quality})


def cmd_log_metric(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    conn.execute(
        """INSERT OR REPLACE INTO metrics
           (session_id, ticker, metric, value, unit, period, source, filed_date, logged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, args.ticker, args.metric, args.value,
         getattr(args, "unit", "USD") or "USD",
         getattr(args, "period", None),
         args.source,
         getattr(args, "filed_date", None),
         _now())
    )
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"ticker": args.ticker, "metric": args.metric, "value": args.value})


def cmd_log_metrics(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_list(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)

    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    logged = []

    for item in data:
        conn.execute(
            """INSERT OR REPLACE INTO metrics
               (session_id, ticker, metric, value, unit, period, source, filed_date, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, item["ticker"], item["metric"], item["value"],
             item.get("unit", "USD"), item.get("period"),
             item["source"], item.get("filed_date"), _now())
        )
        logged.append({"ticker": item["ticker"], "metric": item["metric"]})

    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response(logged)


def cmd_get_metrics(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT * FROM metrics WHERE session_id = ? AND ticker = ? ORDER BY metric",
        (sid, args.ticker)
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


def cmd_get_metric(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT * FROM metrics WHERE session_id = ? AND metric = ? ORDER BY ticker",
        (sid, args.metric)
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# download-pending
# ---------------------------------------------------------------------------

def _prioritize_by_gaps(session_dir: str, pending: list) -> list:
    """Reorder pending sources so gap-relevant ones come first.

    Scores each source title against open gap terms (text + question fields).
    Sources with matches sort first (by match count desc), others keep original order.
    """
    try:
        conn = _connect(session_dir, readonly=True)
        sid = _get_session_id(conn)
        gaps = conn.execute(
            "SELECT text, question FROM gaps WHERE session_id = ? AND status = 'open'",
            (sid,)
        ).fetchall()
        conn.close()
    except Exception:
        return pending  # DB issue — skip prioritization silently

    if not gaps:
        return pending

    gap_texts = []
    for g in gaps:
        if g["text"]:
            gap_texts.append(g["text"])
        if g["question"]:
            gap_texts.append(g["question"])
    gap_terms = set(_extract_terms(gap_texts))

    if not gap_terms:
        return pending

    # Score each source by how many gap terms appear in its title
    scored = []
    for src in pending:
        title_lower = (src.get("title") or "").lower()
        score = sum(1 for t in gap_terms if t in title_lower)
        scored.append((score, src))

    boosted = sum(1 for s, _ in scored if s > 0)
    if boosted:
        log(f"Gap prioritization: {boosted} sources boosted ahead of {len(scored) - boosted} others")

    # Stable sort: gap-relevant first (desc score), then original order
    scored.sort(key=lambda x: -x[0])
    return [src for _, src in scored]


def cmd_download_pending(args):
    """List or download sources that have no on-disk content."""
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        """SELECT id, title, doi, url, pdf_url, type, status, relevance_score
           FROM sources WHERE session_id = ?
           AND content_file IS NULL AND pdf_file IS NULL
           ORDER BY id""",
        (sid,)
    ).fetchall()
    conn.close()

    # Filter out sources that exist on disk even if DB has NULL content_file/pdf_file
    sources_dir = os.path.join(args.session_dir, "sources")
    pending = []
    skipped_on_disk = 0
    skipped_irrelevant = 0
    min_relevance = getattr(args, "min_relevance", None)
    for r in rows:
        sid_val = r["id"]
        # Defense in depth: check disk even when DB says no content
        on_disk = any(
            os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}"))
            for ext in (".md", ".pdf")
        )
        if on_disk:
            skipped_on_disk += 1
            continue

        # Skip sources with relevance_score at or below the floor.
        # Sources with NULL relevance_score (not yet scored) are kept —
        # the filter only blocks sources that were scored and found irrelevant.
        if min_relevance is not None:
            score = r["relevance_score"]
            if score is not None and score <= min_relevance:
                skipped_irrelevant += 1
                continue

        item = {"source_id": sid_val, "title": r["title"], "type": r["type"] or "academic"}
        if r["doi"]:
            item["doi"] = r["doi"]
        if r["url"]:
            item["url"] = r["url"]
        if r["pdf_url"]:
            item["pdf_url"] = r["pdf_url"]
        pending.append(item)

    if skipped_on_disk:
        log(f"{skipped_on_disk} sources already on disk, skipping")
    if skipped_irrelevant:
        log(f"{skipped_irrelevant} sources skipped (relevance_score <= {min_relevance})")

    # Gap-aware prioritization: boost sources whose titles match open gap terms
    if getattr(args, "prioritize_gaps", False) and pending:
        pending = _prioritize_by_gaps(args.session_dir, pending)

    log(f"Found {len(pending)} sources without on-disk content")

    batch_size = getattr(args, "batch_size", None)
    total_pending = len(pending)
    max_batches = getattr(args, "max_batches", None)

    if args.auto_download and not pending:
        resp = {
            "downloaded": 0,
            "failed": 0,
            "failed_sources": [],
            "batch_size": batch_size or 0,
            "batches_run": 0,
            "remaining": 0,
            "message": "nothing_pending",
        }
        if skipped_irrelevant:
            resp["skipped_irrelevant"] = skipped_irrelevant
        success_response(resp)
        return

    if args.auto_download and pending:
        timeout_override = getattr(args, "timeout", None)

        if max_batches and max_batches > 1 and batch_size:
            # Multi-batch loop: run up to N iterations, re-querying pending each time
            total_downloaded = 0
            total_failed_sources: list[str] = []
            batches_run = 0

            for batch_num in range(max_batches):
                if not pending:
                    break
                batch = pending[:batch_size] if batch_size < len(pending) else pending
                if batch_num > 0:
                    log(f"Batch {batch_num + 1}/{max_batches}: {len(batch)} sources")

                result = _auto_download_pending(args.session_dir, batch, args.parallel, timeout_override, total_pending)
                batches_run += 1
                total_downloaded += result["downloaded"]

                # Re-query pending from disk (not DB) to see what's still missing
                if batch_num < max_batches - 1:
                    new_pending = []
                    for item in pending[len(batch):]:  # items we haven't tried yet
                        sid_val = item["source_id"]
                        on_disk = any(
                            os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}"))
                            for ext in (".md", ".pdf")
                        )
                        if not on_disk:
                            new_pending.append(item)
                    pending = new_pending
                    total_pending = len(pending) + total_downloaded
                else:
                    total_failed_sources = result["failed_sources"]

            remaining_after = total_pending - total_downloaded
            if remaining_after < 0:
                remaining_after = 0
            success_response({
                "downloaded": total_downloaded,
                "failed": len(total_failed_sources),
                "failed_sources": total_failed_sources,
                "batch_size": batch_size,
                "batches_run": batches_run,
                "remaining": remaining_after,
            })
            return

        # Single batch (original behavior)
        if batch_size and batch_size < len(pending):
            log(f"Batch size {batch_size}: processing first {batch_size} of {len(pending)} pending")
            pending = pending[:batch_size]

        result = _auto_download_pending(args.session_dir, pending, args.parallel, timeout_override, total_pending)
        success_response(result)
        return

    success_response(pending, total_results=total_pending)


def _auto_download_pending(session_dir: str, pending: list, parallel: int, timeout_override: int | None = None, total_pending: int | None = None) -> dict:
    """Auto-download all pending sources with fallback across identifier types.

    Runs up to 3 passes: DOI cascade first, then pdf_url for failures, then url.
    Each pass only includes sources that still lack on-disk content, so successful
    downloads from earlier passes aren't retried.
    """
    import subprocess
    import tempfile

    sources_dir = os.path.join(session_dir, "sources")
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    download_script = os.path.join(scripts_dir, "download.py")

    # Build per-source identifier lists for fallback ordering
    # Each source gets a list of (identifier_type, entry_dict) to try in order
    source_attempts: dict[str, list[tuple[str, dict]]] = {}
    for item in pending:
        sid = item["source_id"]
        attempts = []
        if item.get("doi"):
            attempts.append(("doi", {"source_id": sid, "doi": item["doi"]}))
        if item.get("pdf_url"):
            attempts.append(("pdf_url", {"source_id": sid, "pdf_url": item["pdf_url"]}))
        if item.get("url"):
            attempts.append(("url", {"source_id": sid, "url": item["url"], "type": "web"}))
        if not attempts:
            log(f"Skipping {sid} — no DOI, URL, or PDF URL", level="warn")
            continue
        source_attempts[sid] = attempts

    if not source_attempts:
        return {"downloaded": 0, "failed": 0, "failed_sources": [], "batch_size": 0, "remaining": total_pending or 0}

    all_results = []
    remaining = set(source_attempts.keys())
    max_pass = max(len(v) for v in source_attempts.values())

    for pass_idx in range(max_pass):
        if not remaining:
            break

        # Build batch for this pass: take the next untried identifier for each remaining source
        batch = []
        for sid in list(remaining):
            attempts = source_attempts[sid]
            if pass_idx < len(attempts):
                batch.append(attempts[pass_idx][1])

        if not batch:
            break

        # Determine identifier type from the first batch entry's actual attempt
        # (can't use arbitrary remaining source — it may have fewer attempts than pass_idx)
        id_type = "?"
        for sid in remaining:
            attempts = source_attempts[sid]
            if pass_idx < len(attempts):
                id_type = attempts[pass_idx][0]
                break
        if pass_idx > 0:
            log(f"Fallback pass {pass_idx + 1}: retrying {len(batch)} sources via {id_type}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=session_dir, delete=False) as tf:
            json.dump(batch, tf)
            tmp_path = tf.name

        cmd = [
            sys.executable, download_script,
            "--from-json", tmp_path,
            "--to-md",
            "--session-dir", session_dir,
            "--parallel", str(parallel),
        ]

        timeout = timeout_override if timeout_override is not None else min(480, max(300, len(batch) * 30))
        log(f"Downloading {len(batch)} sources (parallel={parallel}, timeout: {timeout}s)...")
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
            os.unlink(tmp_path)

            if result.returncode == 0:
                try:
                    output = json.loads(result.stdout.decode())
                    # Collect results from this pass
                    if isinstance(output, dict) and "results" in output:
                        pass_results = output["results"]
                    elif isinstance(output, list):
                        pass_results = output
                    else:
                        pass_results = []
                    all_results.extend(pass_results if isinstance(pass_results, list) else [pass_results])
                except json.JSONDecodeError:
                    pass
            else:
                stderr_text = result.stderr.decode()[-500:] if result.stderr else ""
                log(f"Download pass {pass_idx + 1} failed (exit {result.returncode}): {stderr_text}", level="warn")
        except subprocess.TimeoutExpired:
            os.unlink(tmp_path)
            log(f"Download pass {pass_idx + 1} timed out after {timeout}s", level="warn")
        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            log(f"Download pass {pass_idx + 1} failed: {e}", level="warn")

        # Check which sources now have files on disk — remove them from remaining
        newly_resolved = set()
        for sid in remaining:
            on_disk = any(
                os.path.exists(os.path.join(sources_dir, f"{sid}{ext}"))
                for ext in (".md", ".pdf")
            )
            if on_disk:
                newly_resolved.add(sid)
        remaining -= newly_resolved

        if newly_resolved:
            log(f"Pass {pass_idx + 1}: {len(newly_resolved)} sources downloaded, {len(remaining)} still pending")

    downloaded = len(source_attempts) - len(remaining)
    remaining_pending = (total_pending - downloaded) if total_pending is not None else len(remaining)
    return {
        "downloaded": downloaded,
        "failed": len(remaining),
        "failed_sources": sorted(remaining),
        "batch_size": len(source_attempts),
        "remaining": remaining_pending,
    }


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

def cmd_audit(args):
    """Pre-report audit: check source coverage, quality, and readiness."""
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    # Load all sources
    sources = [dict(r) for r in conn.execute(
        "SELECT * FROM sources WHERE session_id = ? ORDER BY id", (sid,)
    ).fetchall()]

    # Load brief for research questions
    brief_row = conn.execute("SELECT * FROM brief WHERE session_id = ?", (sid,)).fetchone()
    questions = []
    if brief_row:
        questions = json.loads(brief_row["questions"])

    # Load findings
    findings = [dict(r) for r in conn.execute(
        "SELECT * FROM findings WHERE session_id = ? ORDER BY id", (sid,)
    ).fetchall()]
    for f in findings:
        f["sources"] = json.loads(f["sources"]) if f.get("sources") else []

    # Load searches for methodology stats
    all_searches = conn.execute(
        "SELECT search_type FROM searches WHERE session_id = ?", (sid,)
    ).fetchall()
    searches_by_type = {}
    for s in all_searches:
        st = s["search_type"] if "search_type" in s.keys() else "manual"
        searches_by_type[st] = searches_by_type.get(st, 0) + 1

    # Load gaps
    gaps = [dict(r) for r in conn.execute(
        "SELECT * FROM gaps WHERE session_id = ? AND status = 'open' ORDER BY id", (sid,)
    ).fetchall()]

    conn.close()

    # Check on-disk files
    notes_dir = os.path.join(args.session_dir, "notes")
    sources_dir = os.path.join(args.session_dir, "sources")

    downloaded = []
    with_notes = []
    degraded_unread = []
    reader_validated = []
    mismatched = []
    no_content = []
    abstract_only = []

    for s in sources:
        sid_val = s["id"]
        has_content = False

        # Check content file
        if s.get("content_file"):
            content_path = os.path.join(args.session_dir, s["content_file"])
            if os.path.exists(content_path):
                has_content = True
        # Also check if file exists even without content_file in DB
        if not has_content:
            for ext in (".md", ".pdf"):
                if os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")):
                    has_content = True
                    break

        if has_content:
            downloaded.append(sid_val)
        else:
            no_content.append(sid_val)

        # Check notes
        note_path = os.path.join(notes_dir, f"{sid_val}.md")
        if os.path.exists(note_path):
            with_notes.append(sid_val)

        # Check quality
        quality = s.get("quality")
        if isinstance(quality, str):
            if quality == "degraded":
                degraded_unread.append(sid_val)
            elif quality == "reader_validated":
                reader_validated.append(sid_val)
            elif quality == "mismatched":
                mismatched.append(sid_val)
            elif quality == "abstract_only":
                abstract_only.append(sid_val)
        elif isinstance(quality, (int, float)) and quality < 0.5:
            degraded_unread.append(sid_val)

    # Build question text list from brief
    question_texts = []
    for q in questions:
        question_texts.append(q if isinstance(q, str) else q.get("text", str(q)))

    # Match a finding's question field to brief questions.
    # Agents sometimes use abbreviated labels ("Q1", "Q3: What mechanisms...")
    # instead of the full question text, so we try:
    #   1. Exact match
    #   2. Finding question is a prefix/substring of a brief question
    #   3. Brief question starts with the finding's question text
    #   4. "Q<N>" pattern matches the Nth question (1-indexed)
    import re
    _qn_pattern = re.compile(r"^Q(\d+)\b")

    def _match_question(finding_q: str) -> str:
        """Return the matching brief question text, or the original string."""
        if finding_q in question_texts:
            return finding_q
        fq_lower = finding_q.lower().strip()
        # Check Q<N> pattern first (e.g. "Q1", "Q3: What mechanisms...")
        m = _qn_pattern.match(finding_q)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(question_texts):
                return question_texts[idx]
        # Substring/prefix matching
        for qt in question_texts:
            qt_lower = qt.lower()
            if fq_lower in qt_lower or qt_lower.startswith(fq_lower):
                return qt
        return finding_q

    # Count findings per question
    findings_by_question: dict[str, list[str]] = {}
    for f in findings:
        q = _match_question(f.get("question") or "unassigned")
        findings_by_question.setdefault(q, []).append(f["id"])

    # Identify questions with insufficient coverage
    sparse_questions = []
    for q_text in question_texts:
        count = len(findings_by_question.get(q_text, []))
        if count < 2:
            sparse_questions.append({"question": q_text, "finding_count": count})

    # Methodology stats
    deep_reads = len(with_notes)
    total_downloaded = len(downloaded)
    total_abstract_only = len(no_content) + len(abstract_only)
    web_sources = sum(1 for s in sources if (s.get("type") or "").lower() == "web")

    # Detect downloaded sources with null content_file — these are invisible
    # to readers and audit despite having files on disk
    downloaded_no_content_file = []
    for s in sources:
        if (s.get("status") == "downloaded"
                and not s.get("content_file")
                and s["id"] in downloaded):
            downloaded_no_content_file.append(s["id"])

    # Build warnings
    warnings = []
    for sid_val in degraded_unread:
        warnings.append(f"{sid_val} has degraded PDF quality — do not claim deep reading")
    for sid_val in mismatched:
        warnings.append(f"{sid_val} has mismatched content — downloaded PDF may be wrong paper")
    if downloaded_no_content_file:
        warnings.append(
            f"{len(downloaded_no_content_file)} source(s) have status='downloaded' but null "
            f"content_file despite on-disk files: {', '.join(downloaded_no_content_file[:10])}. "
            f"Run 'state sync-files' to fix."
        )
    for sq in sparse_questions:
        warnings.append(f'"{sq["question"]}" has insufficient coverage ({sq["finding_count"]} findings)')
    if no_content:
        warnings.append(f"{len(no_content)} sources have no on-disk content (abstract-only)")
    if len(gaps) > 0:
        warnings.append(f"{len(gaps)} open research gaps remain")

    # Human-readable summary to stderr
    log("=== Pre-Report Audit ===")
    log(f"Sources tracked:     {len(sources)}")
    log(f"Sources downloaded:  {total_downloaded}  ({', '.join(downloaded[:10])}{'...' if len(downloaded) > 10 else ''})")
    log(f"Sources with notes:  {deep_reads}  ({', '.join(with_notes[:10])}{'...' if len(with_notes) > 10 else ''})")
    log(f"Degraded (unread):   {len(degraded_unread)}  ({', '.join(degraded_unread)})" if degraded_unread else "Degraded (unread):   0")
    log(f"Reader validated:    {len(reader_validated)}  ({', '.join(reader_validated)})" if reader_validated else "Reader validated:    0")
    log(f"Mismatched content:  {len(mismatched)}  ({', '.join(mismatched)})" if mismatched else "Mismatched content:  0")
    log(f"Abstract only:       {len(abstract_only)}  ({', '.join(abstract_only)})" if abstract_only else "Abstract only:       0")
    log(f"Findings logged:     {len(findings)}")
    log(f"Open gaps:           {len(gaps)}")
    if sparse_questions:
        qs = ", ".join(sq["question"][:40] for sq in sparse_questions)
        log(f"Sparse coverage:     {qs}")
    log("")
    if warnings:
        log("WARNINGS:")
        for w in warnings:
            log(f"  - {w}", level="warn")
    log("")
    log("Methodology stats (use these in report):")
    log(f"  Deep reads: {deep_reads}")
    log(f"  Abstract-only: {total_abstract_only}")
    log(f"  Web sources: {web_sources}")

    # JSON result
    use_brief = getattr(args, "brief", False)

    audit_result = {
        "sources_tracked": len(sources),
        "sources_downloaded": total_downloaded,
        "sources_with_notes": deep_reads,
        "degraded_unread": degraded_unread,
        "reader_validated": reader_validated,
        "mismatched_content": mismatched,
        "findings_count": len(findings),
        "findings_by_question": {k: len(v) for k, v in findings_by_question.items()},
        "open_gaps": len(gaps),
        "gaps": [{"id": g["id"], "text": g["text"], "question": g.get("question"), "status": g["status"]} for g in gaps],
        "sparse_questions": sparse_questions,
        "downloaded_no_content_file": downloaded_no_content_file,
        "methodology": {
            "deep_reads": deep_reads,
            "abstract_only": total_abstract_only,
            "web_sources": web_sources,
            "searches": {
                "total": len(all_searches),
                **searches_by_type,
            },
        },
        "warnings": warnings,
    }

    # --brief: omit large ID arrays, use counts only
    # (degraded_unread, reader_validated, and mismatched_content stay as arrays — orchestrator needs specific IDs)
    if not use_brief:
        audit_result["downloaded_ids"] = downloaded
        audit_result["notes_ids"] = with_notes
        audit_result["abstract_only"] = abstract_only
        audit_result["no_content"] = no_content
    else:
        audit_result["abstract_only_count"] = len(abstract_only)
        audit_result["no_content_count"] = len(no_content)

    # --strict: exit non-zero if warnings exist
    if getattr(args, "strict", False) and warnings:
        error_response(
            [f"Audit found {len(warnings)} warning(s)"],
            partial_results=audit_result,
            error_code="audit_warnings",
        )
    else:
        success_response(audit_result)


# ---------------------------------------------------------------------------
# triage
# ---------------------------------------------------------------------------

def _score_sources(conn, session_id: str, session_dir: str, top_n: int = 25, title_filter: str | None = None) -> tuple[list[dict], int]:
    """Score and tier-rank sources by citation count × relevance to brief questions.

    Returns (scored_list, brief_keywords_count). Each scored dict has 'priority'
    assigned (high/medium/low/skip). Reusable by both cmd_triage and cmd_manifest.
    """
    import math

    # Load brief questions for relevance scoring
    brief_row = conn.execute("SELECT * FROM brief WHERE session_id = ?", (session_id,)).fetchone()
    question_terms = _extract_question_terms(json.loads(brief_row["questions"])) if brief_row else []

    # Load sources (with optional title filter)
    _src_cols = ("id, title, authors, year, doi, url, pdf_url, citation_count, type, provider, "
                 "content_file, pdf_file, is_read, quality, relevance_score, relevance_rationale, status")
    if title_filter:
        sources = [dict(r) for r in conn.execute(
            f"SELECT {_src_cols} FROM sources WHERE session_id = ? AND title LIKE ? ORDER BY id",
            (session_id, f"%{title_filter}%")
        ).fetchall()]
    else:
        sources = [dict(r) for r in conn.execute(
            f"SELECT {_src_cols} FROM sources WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()]

    # Score each source
    scored = []
    for s in sources:
        title = (s.get("title") or "").lower()

        # Title keyword relevance: count how many brief-question keywords appear in title
        keyword_hits = sum(1 for t in question_terms if t in title) if question_terms else 0

        # Prefer LLM relevance score when available; fall back to keyword matching
        if s.get("relevance_score") is not None:
            relevance = s["relevance_score"]
        else:
            relevance = min(keyword_hits / 5.0, 1.0) if question_terms else 0.5

        # Citation score: log-scale to avoid extreme skew from mega-cited papers
        cite_count = s.get("citation_count") or 0
        cite_score = math.log1p(cite_count)  # log(1 + citations)

        # Combined score: citation_score × (0.1 + relevance)
        # The 0.1 floor keeps zero-relevance papers from dominating via citations alone
        score = cite_score * (0.1 + relevance)

        # Check on-disk status
        sources_dir = os.path.join(session_dir, "sources")
        has_content = False
        if s.get("content_file"):
            has_content = os.path.exists(os.path.join(session_dir, s["content_file"]))
        if not has_content:
            for ext in (".md", ".pdf"):
                if os.path.exists(os.path.join(sources_dir, f"{s['id']}{ext}")):
                    has_content = True
                    break

        quality = s.get("quality")
        quality_flag = None
        if isinstance(quality, str) and quality in ("mismatched", "degraded", "empty"):
            quality_flag = quality
        elif isinstance(quality, (int, float)) and quality < 0.5:
            quality_flag = "low_score"

        scored.append({
            "id": s["id"],
            "title": s.get("title", ""),
            "citation_count": cite_count,
            "keyword_hits": keyword_hits,
            "score": round(score, 2),
            "has_content": has_content,
            "is_read": bool(s.get("is_read")),
            "quality_flag": quality_flag,
            "doi": s.get("doi"),
            "type": s.get("type", "academic"),
            "provider": s.get("provider"),
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Assign priority tiers
    for i, item in enumerate(scored):
        if item["quality_flag"]:
            item["priority"] = "skip"
        elif i < top_n // 2:
            item["priority"] = "high"
        elif i < top_n:
            item["priority"] = "medium"
        else:
            item["priority"] = "low"

    return scored, len(question_terms)


def cmd_triage(args):
    """Rank sources by citation count × title-keyword-relevance to brief questions.

    Outputs sources in priority tiers (high/medium/low) to help the agent decide
    which sources to download and read. Sources with quality issues are flagged.
    """
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    top_n = getattr(args, "top", 25)
    title_filter = getattr(args, "title_contains", None)

    scored, brief_keywords_used = _score_sources(conn, sid, args.session_dir, top_n, title_filter)
    conn.close()

    # Summary stats
    high = [s for s in scored if s["priority"] == "high"]
    medium = [s for s in scored if s["priority"] == "medium"]
    skip = [s for s in scored if s["priority"] == "skip"]

    success_response({
        "sources": scored,
        "summary": {
            "total": len(scored),
            "high_priority": len(high),
            "medium_priority": len(medium),
            "skip_quality": len(skip),
            "brief_keywords_used": brief_keywords_used,
        },
        "top_sources": [
            {"id": s["id"], "title": s["title"], "citation_count": s["citation_count"], "tier": s["priority"], "score": s["score"]}
            for s in scored if s["priority"] in ("high", "medium")
        ],
    })


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def cmd_manifest(args):
    """Pre-assembled manifest for the source-acquisition agent.

    Single readonly query that gathers data from all tables and returns the
    compact JSON the agent used to assemble manually from 4-5 separate commands.
    Supports --mode initial (full pipeline summary) and --mode gap (targeted
    follow-up summary).
    """
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    mode = getattr(args, "mode", "initial")
    top_n = getattr(args, "top", 30)

    if mode == "gap":
        _manifest_gap(conn, sid, args.session_dir, top_n)
    else:
        _manifest_initial(conn, sid, args.session_dir, top_n)


def _manifest_initial(conn, session_id: str, session_dir: str, top_n: int):
    """Build the initial-mode manifest."""
    # --- Searches ---
    search_rows = conn.execute(
        "SELECT provider, query, search_mode, search_type, result_count, ingested_count FROM searches WHERE session_id = ?",
        (session_id,)
    ).fetchall()
    searches_run = len(search_rows)
    sources_found = sum(r["result_count"] or 0 for r in search_rows)
    recovery_searches = sum(1 for r in search_rows if r["search_type"] == "recovery")

    # --- Sources ---
    source_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM sources WHERE session_id = ?", (session_id,)
    ).fetchone()["cnt"]

    provider_rows = conn.execute(
        "SELECT provider, COUNT(*) as count FROM sources WHERE session_id = ? GROUP BY provider ORDER BY count DESC",
        (session_id,)
    ).fetchall()
    provider_distribution = {r["provider"]: r["count"] for r in provider_rows}

    # --- Downloads ---
    sources_dir = os.path.join(session_dir, "sources")
    all_sources = conn.execute(
        "SELECT id, content_file, pdf_file, quality FROM sources WHERE session_id = ?",
        (session_id,)
    ).fetchall()

    success_count = 0
    failed_count = 0
    for s in all_sources:
        has_content = False
        if s["content_file"]:
            has_content = os.path.exists(os.path.join(session_dir, s["content_file"]))
        if not has_content:
            for ext in (".md", ".pdf"):
                if os.path.exists(os.path.join(sources_dir, f"{s['id']}{ext}")):
                    has_content = True
                    break
        quality = s["quality"]
        is_quality_flagged = isinstance(quality, str) and quality in ("mismatched", "degraded", "empty")
        if has_content and not is_quality_flagged:
            success_count += 1
        elif not has_content and not is_quality_flagged:
            failed_count += 1
        # quality-flagged sources are neither success nor failed — they're excluded

    remaining = failed_count  # sources without content and not quality-flagged

    # --- Triage tiers ---
    scored, _ = _score_sources(conn, session_id, session_dir, top_n)
    triage_tiers = {"high": 0, "medium": 0, "low": 0, "skip": 0}
    for s in scored:
        tier = s.get("priority", "low")
        triage_tiers[tier] = triage_tiers.get(tier, 0) + 1

    # --- Top papers ---
    top_papers = [
        {"id": s["id"], "title": s["title"], "citations": s["citation_count"], "provider": s.get("provider", "")}
        for s in scored[:5]
    ]

    # --- Coverage assessment ---
    brief_row = conn.execute("SELECT * FROM brief WHERE session_id = ?", (session_id,)).fetchone()
    coverage_assessment = {}
    if brief_row:
        questions = json.loads(brief_row["questions"])
        high_medium = [s for s in scored if s["priority"] in ("high", "medium")]
        for i, q in enumerate(questions):
            q_text = q if isinstance(q, str) else q.get("text", str(q))
            q_terms = _extract_terms([q_text])
            matching = sum(
                1 for s in high_medium
                if any(t in (s.get("title") or "").lower() for t in q_terms)
            )
            if matching >= 5:
                strength = "strong"
            elif matching >= 3:
                strength = "moderate"
            else:
                strength = "thin"
            label = f"Q{i+1}: {q_text}"
            # Truncate long question text for readability
            if len(label) > 80:
                label = label[:77] + "..."
            coverage_assessment[label] = f"{strength} ({matching} sources)"

    # --- Gaps ---
    gap_rows = conn.execute(
        "SELECT id, text, status FROM gaps WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    gaps_logged = [f"{r['id']}: {r['text']}" for r in gap_rows if r["status"] == "open"]

    # --- Citation chasing ---
    citation_searches = conn.execute(
        "SELECT result_count, ingested_count FROM searches WHERE session_id = ? AND search_mode IN ('cited_by', 'references')",
        (session_id,)
    ).fetchall()
    traversals_run = len(citation_searches)
    sources_from_chasing = sum(r["ingested_count"] or 0 for r in citation_searches)
    primary_searches = searches_run - recovery_searches
    citation_chasing_ratio = round(traversals_run / max(1, primary_searches), 2)

    # --- Warnings ---
    warnings = []
    num_questions = 0
    if brief_row:
        questions_list = json.loads(brief_row["questions"])
        num_questions = len(questions_list)
        if num_questions >= 5 and citation_chasing_ratio < 0.25:
            warnings.append(
                f"Citation chasing ratio ({citation_chasing_ratio:.0%}) below recommended minimum (25%) "
                f"for review-depth topics ({num_questions} questions). "
                f"Consider additional traversals before proceeding."
            )

    conn.close()

    result = {
        "searches_run": searches_run,
        "sources_found": sources_found,
        "sources_after_dedup": source_count,
        "provider_distribution": provider_distribution,
        "downloads": {
            "success": success_count,
            "failed": failed_count,
            "remaining": remaining,
        },
        "triage_tiers": triage_tiers,
        "top_papers": top_papers,
        "coverage_assessment": coverage_assessment,
        "gaps_logged": gaps_logged,
        "citation_chasing": {
            "traversals_run": traversals_run,
            "sources_from_chasing": sources_from_chasing,
            "citation_chasing_ratio": citation_chasing_ratio,
        },
    }
    if warnings:
        result["warnings"] = warnings
    success_response(result)


def _manifest_gap(conn, session_id: str, session_dir: str, top_n: int):
    """Build the gap-mode manifest."""
    # All gaps
    gap_rows = conn.execute(
        "SELECT id, text, status FROM gaps WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()

    gaps_addressed = sum(1 for r in gap_rows if r["status"] == "resolved")

    # For open gaps, check if any new high/medium sources match their terms
    scored, _ = _score_sources(conn, session_id, session_dir, top_n)
    high_medium = [s for s in scored if s["priority"] in ("high", "medium")]

    potentially_resolved = []
    unresolvable = []
    for gap in gap_rows:
        if gap["status"] == "resolved":
            continue
        gap_terms = _extract_terms([gap["text"]])
        matching = sum(
            1 for s in high_medium
            if s["has_content"] and any(t in (s.get("title") or "").lower() for t in gap_terms)
        )
        if matching > 0:
            potentially_resolved.append(gap["id"])
        else:
            unresolvable.append({"gap_id": gap["id"], "reason": f"No new high/medium sources with content match gap terms"})

    # New sources/downloads — count sources added after initial acquisition
    # (approximation: sources whose id number is higher than the gap threshold)
    new_source_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM sources WHERE session_id = ?", (session_id,)
    ).fetchone()["cnt"]

    sources_dir = os.path.join(session_dir, "sources")
    all_sources = conn.execute(
        "SELECT id, content_file, pdf_file FROM sources WHERE session_id = ?", (session_id,)
    ).fetchall()
    new_downloads = sum(
        1 for s in all_sources
        if s["content_file"] and os.path.exists(os.path.join(session_dir, s["content_file"]))
        or any(os.path.exists(os.path.join(sources_dir, f"{s['id']}{ext}")) for ext in (".md", ".pdf"))
    )

    conn.close()

    success_response({
        "gaps_addressed": gaps_addressed,
        "gaps_potentially_resolved": len(potentially_resolved),
        "gaps_potentially_resolved_ids": potentially_resolved,
        "gaps_unresolvable": unresolvable,
        "new_sources": new_source_count,
        "new_downloads": new_downloads,
    })


# ---------------------------------------------------------------------------
# recover-failed
# ---------------------------------------------------------------------------

def cmd_recover_failed(args):
    """Identify high-priority failed downloads and retry via alternative channels.

    Finds sources that failed download (have no on-disk content) with either
    high citation count or high title relevance, then attempts recovery via:
    1. CORE search by title (institutional repository versions)
    2. Tavily search for "title pdf" (preprint servers, author pages)
    3. DOI landing page as web source (at least get abstract + visible text)
    """
    import subprocess

    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    # Load brief questions for relevance scoring
    brief_row = conn.execute("SELECT * FROM brief WHERE session_id = ?", (sid,)).fetchone()
    question_terms = _extract_question_terms(json.loads(brief_row["questions"])) if brief_row else []

    # Find sources without on-disk content
    rows = conn.execute(
        """SELECT id, title, doi, url, pdf_url, citation_count, type,
                  relevance_score
           FROM sources WHERE session_id = ?
           AND content_file IS NULL AND pdf_file IS NULL
           ORDER BY citation_count DESC NULLS LAST""",
        (sid,)
    ).fetchall()
    conn.close()

    sources_dir = os.path.join(args.session_dir, "sources")
    # Parse CLI-supplied title keywords for filtering
    min_relevance = getattr(args, "min_relevance", 0.3)
    title_kw_arg = getattr(args, "title_keywords", "") or ""
    title_keywords = [k.strip().lower() for k in title_kw_arg.split(",") if k.strip()]

    failed = []
    for r in rows:
        sid_val = r["id"]
        on_disk = any(
            os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}"))
            for ext in (".md", ".pdf")
        )
        if on_disk:
            continue

        title = (r["title"] or "").lower()
        cite_count = r["citation_count"] or 0
        rel_score = r["relevance_score"]
        keyword_hits = sum(1 for t in question_terms if t in title) if question_terms else 0

        # --min-relevance gate: skip sources scored below threshold.
        # Without an LLM score, fall back to keyword hits as a weaker signal.
        if rel_score is not None and rel_score < min_relevance:
            continue
        if rel_score is None and keyword_hits == 0 and question_terms:
            continue

        # --title-keywords gate: if caller supplied keywords, require at
        # least one match in the source title to avoid recovering off-topic
        # high-citation papers (e.g., PRISMA guidelines, COVID burden studies).
        if title_keywords and not any(kw in title for kw in title_keywords):
            continue

        # High-priority: citation_count > threshold OR high title relevance
        min_citations = getattr(args, "min_citations", 50)
        is_high_priority = cite_count >= min_citations or keyword_hits >= 2

        if is_high_priority:
            failed.append({
                "source_id": sid_val,
                "title": r["title"],
                "doi": r["doi"],
                "url": r["url"],
                "citation_count": cite_count,
                "keyword_hits": keyword_hits,
                "relevance_score": rel_score,
            })

    if not failed:
        success_response({"recovered": 0, "message": "No high-priority failed sources found"})
        return

    log(f"Found {len(failed)} high-priority failed sources for recovery")

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    search_script = os.path.join(scripts_dir, "search.py")
    download_script = os.path.join(scripts_dir, "download.py")

    max_attempts = getattr(args, "max_attempts", 15) or 15
    recovered = []
    still_failed = []
    total_attempts = 0
    channel_stats = {"core": {"attempts": 0, "successes": 0},
                     "tavily": {"attempts": 0, "successes": 0},
                     "doi": {"attempts": 0, "successes": 0}}
    skipped_channels = []
    budget_exhausted = False

    def _channel_available(ch: str) -> bool:
        """Return False if a channel should be skipped (0 successes after 5+ attempts)."""
        s = channel_stats[ch]
        return not (s["attempts"] >= 5 and s["successes"] == 0)

    for item in failed:
        sid_val = item["source_id"]
        title = item["title"] or ""
        doi = item.get("doi")

        # Check if recovered by a previous pass in this loop
        if any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
            recovered.append(sid_val)
            continue

        # Budget check: stop if we've exhausted max attempts
        if total_attempts >= max_attempts:
            if not budget_exhausted:
                log(f"Recovery budget exhausted ({max_attempts} attempts). Stopping.")
                budget_exhausted = True
            still_failed.append(sid_val)
            continue

        # Strategy 1: CORE search by title
        success = False
        if title and _channel_available("core"):
            try:
                channel_stats["core"]["attempts"] += 1
                total_attempts += 1
                cmd = [
                    sys.executable, search_script,
                    "--provider", "core",
                    "--query", title[:200],
                    "--limit", "3",
                    "--session-dir", args.session_dir,
                    "--search-type", "recovery",
                ]
                proc = subprocess.run(cmd, capture_output=True, timeout=30)
                if proc.returncode == 0:
                    try:
                        result = json.loads(proc.stdout.decode())
                        results = result.get("results", {})
                        if isinstance(results, dict):
                            results = results.get("results", [])
                        # Look for a result with a download_url or pdf_url
                        for r in (results if isinstance(results, list) else []):
                            pdf_url = r.get("pdf_url") or r.get("download_url")
                            if pdf_url:
                                # Try downloading this PDF
                                dl_cmd = [
                                    sys.executable, download_script,
                                    "--pdf-url", pdf_url,
                                    "--source-id", sid_val,
                                    "--to-md",
                                    "--session-dir", args.session_dir,
                                ]
                                dl_proc = subprocess.run(dl_cmd, capture_output=True, timeout=60)
                                if dl_proc.returncode == 0:
                                    if any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
                                        log(f"Recovered {sid_val} via CORE")
                                        recovered.append(sid_val)
                                        channel_stats["core"]["successes"] += 1
                                        success = True
                                        break
                    except (json.JSONDecodeError, TypeError):
                        pass
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"CORE recovery failed for {sid_val}: {e}", level="debug")

            # Check if CORE should be skipped going forward
            if not _channel_available("core") and "core" not in skipped_channels:
                skipped_channels.append("core")
                log("CORE channel skipped: 0 successes after 5 attempts")

        if success:
            continue
        if total_attempts >= max_attempts:
            still_failed.append(sid_val)
            continue

        # Strategy 2: Tavily search for "title pdf"
        if title and _channel_available("tavily"):
            try:
                channel_stats["tavily"]["attempts"] += 1
                total_attempts += 1
                cmd = [
                    sys.executable, search_script,
                    "--provider", "tavily",
                    "--query", f'"{title[:150]}" pdf',
                    "--limit", "3",
                    "--session-dir", args.session_dir,
                    "--search-type", "recovery",
                ]
                proc = subprocess.run(cmd, capture_output=True, timeout=30)
                if proc.returncode == 0:
                    try:
                        result = json.loads(proc.stdout.decode())
                        results = result.get("results", {})
                        if isinstance(results, dict):
                            results = results.get("results", [])
                        for r in (results if isinstance(results, list) else []):
                            url = r.get("url", "")
                            if url and url.lower().endswith(".pdf"):
                                dl_cmd = [
                                    sys.executable, download_script,
                                    "--pdf-url", url,
                                    "--source-id", sid_val,
                                    "--to-md",
                                    "--session-dir", args.session_dir,
                                ]
                                dl_proc = subprocess.run(dl_cmd, capture_output=True, timeout=60)
                                if dl_proc.returncode == 0:
                                    if any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
                                        log(f"Recovered {sid_val} via Tavily PDF search")
                                        recovered.append(sid_val)
                                        channel_stats["tavily"]["successes"] += 1
                                        success = True
                                        break
                    except (json.JSONDecodeError, TypeError):
                        pass
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"Tavily recovery failed for {sid_val}: {e}", level="debug")

            # Check if Tavily should be skipped going forward
            if not _channel_available("tavily") and "tavily" not in skipped_channels:
                skipped_channels.append("tavily")
                log("Tavily channel skipped: 0 successes after 5 attempts")

        if success:
            continue
        if total_attempts >= max_attempts:
            still_failed.append(sid_val)
            continue

        # Strategy 3: DOI landing page as web source
        if doi and _channel_available("doi"):
            try:
                channel_stats["doi"]["attempts"] += 1
                total_attempts += 1
                doi_url = f"https://doi.org/{doi}"
                dl_cmd = [
                    sys.executable, download_script,
                    "--url", doi_url,
                    "--source-id", sid_val,
                    "--type", "web",
                    "--session-dir", args.session_dir,
                ]
                dl_proc = subprocess.run(dl_cmd, capture_output=True, timeout=60)
                if dl_proc.returncode == 0:
                    if any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
                        log(f"Recovered {sid_val} via DOI landing page")
                        recovered.append(sid_val)
                        channel_stats["doi"]["successes"] += 1
                        success = True
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"DOI landing page recovery failed for {sid_val}: {e}", level="debug")

            # Check if DOI should be skipped going forward
            if not _channel_available("doi") and "doi" not in skipped_channels:
                skipped_channels.append("doi")
                log("DOI channel skipped: 0 successes after 5 attempts")

        if not success:
            still_failed.append(sid_val)

    success_response({
        "recovered": len(recovered),
        "recovered_sources": recovered,
        "still_failed": len(still_failed),
        "still_failed_sources": still_failed,
        "attempted": total_attempts,
        "eligible": len(failed),
        "budget_exhausted": budget_exhausted,
        "skipped_channels": skipped_channels,
        "channel_stats": channel_stats,
    })


# ---------------------------------------------------------------------------
# JSON loading helper
# ---------------------------------------------------------------------------

def _load_json_dict(path: str) -> dict:
    """Load JSON file expected to contain an object."""
    data = _load_json_raw(path)
    if not isinstance(data, dict):
        error_response(["Expected JSON object"])
        raise SystemExit(1)
    return data


def _load_json_list(path: str) -> list:
    """Load JSON file expected to contain an array."""
    data = _load_json_raw(path)
    if not isinstance(data, list):
        error_response(["Expected JSON array"])
        raise SystemExit(1)
    return data


def _load_json_raw(path: str) -> dict | list:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        error_response([f"File not found: {path}"])
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        error_response([f"Invalid JSON in {path}: {e}"])
        raise SystemExit(1)


def _resolve_json_input(args) -> tuple[str, bool]:
    """Resolve JSON input source: --from-json FILE or --from-stdin.

    When --from-stdin is used, reads stdin into a temp file and returns its path.
    Returns (path, is_temp) — caller must clean up temp files via _cleanup_json_input.
    """
    if getattr(args, "from_json", None):
        return args.from_json, False
    if getattr(args, "from_stdin", False):
        import tempfile
        try:
            raw = sys.stdin.read()
            data = json.loads(raw)  # validate JSON
        except json.JSONDecodeError as e:
            error_response([f"Invalid JSON from stdin: {e}"])
            raise SystemExit(1)
        # Write to temp file so _load_json_raw works uniformly
        session_dir = getattr(args, "session_dir", None) or "."
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=session_dir, delete=False)
        json.dump(data, tf)
        tf.close()
        return tf.name, True
    error_response(["No JSON input specified. Use --from-json FILE or --from-stdin"])
    raise SystemExit(1)


def _cleanup_json_input(path: str, is_temp: bool) -> None:
    """Remove temp file created by _resolve_json_input if needed."""
    if is_temp:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# sync-files
# ---------------------------------------------------------------------------

def cmd_sync_files(args):
    """Reconcile content_file in state.db with what actually exists on disk.

    Walks sources/ looking for {source_id}.md or {source_id}.pdf files and
    updates content_file for any source whose file exists but isn't recorded.
    Also clears content_file for records pointing to files that no longer exist.
    """
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    sources_dir = os.path.join(args.session_dir, "sources")

    if not os.path.isdir(sources_dir):
        success_response({
            "linked": 0,
            "cleared": 0,
            "message": "No sources/ directory found"
        })
        return

    # Build map of source_id -> on-disk file path (prefer .md over .pdf)
    disk_files = {}  # source_id -> relative path from session_dir
    for fname in os.listdir(sources_dir):
        name, ext = os.path.splitext(fname)
        if ext not in (".md", ".pdf"):
            continue
        # Only override if we don't already have .md (prefer .md)
        if name not in disk_files or ext == ".md":
            disk_files[name] = os.path.join("sources", fname)

    # Get all sources for this session
    rows = conn.execute(
        "SELECT id, content_file FROM sources WHERE session_id = ?",
        (sid,)
    ).fetchall()

    linked = 0
    cleared = 0

    for row in rows:
        src_id = row["id"]
        current = row["content_file"]
        on_disk = disk_files.get(src_id)

        if on_disk and not current:
            # File exists on disk but not recorded in DB
            conn.execute(
                "UPDATE sources SET content_file = ? WHERE id = ? AND session_id = ?",
                (on_disk, src_id, sid)
            )
            linked += 1
            log(f"Linked {src_id} -> {on_disk}")
        elif current and not on_disk:
            # DB record points to file that doesn't exist
            full_path = os.path.join(args.session_dir, current)
            if not os.path.exists(full_path):
                conn.execute(
                    "UPDATE sources SET content_file = NULL WHERE id = ? AND session_id = ?",
                    (src_id, sid)
                )
                cleared += 1
                log(f"Cleared missing content_file for {src_id} (was {current})")

    conn.commit()

    if linked > 0 or cleared > 0:
        _regenerate_snapshot(args.session_dir, conn, sid)

    conn.close()

    success_response({
        "linked": linked,
        "cleared": cleared,
        "total_on_disk": len(disk_files),
        "total_sources": len(rows),
    })


# ---------------------------------------------------------------------------
# cleanup-orphans
# ---------------------------------------------------------------------------

def cmd_cleanup_orphans(args):
    """Remove metadata files on disk that have no matching source in state.db.

    After deduplication removes sources from the database, their metadata JSON
    files remain on disk. This command compares sources/metadata/src-NNN.json
    files against source IDs in state.db and deletes orphans.
    """
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    metadata_dir = os.path.join(args.session_dir, "sources", "metadata")
    if not os.path.isdir(metadata_dir):
        conn.close()
        success_response({
            "removed": 0,
            "kept": 0,
            "message": "No sources/metadata/ directory found"
        })
        return

    # Get all source IDs in state.db
    rows = conn.execute(
        "SELECT id FROM sources WHERE session_id = ?", (sid,)
    ).fetchall()
    conn.close()
    db_ids = {row["id"] for row in rows}

    # Scan metadata files on disk
    removed = []
    kept = 0
    for fname in os.listdir(metadata_dir):
        if not fname.endswith(".json"):
            continue
        source_id = fname[:-5]  # strip .json
        if source_id not in db_ids:
            filepath = os.path.join(metadata_dir, fname)
            try:
                os.remove(filepath)
                removed.append(source_id)
                log(f"Removed orphan: {fname}")
            except OSError as e:
                log(f"Failed to remove {fname}: {e}")
        else:
            kept += 1

    success_response({
        "removed": len(removed),
        "removed_ids": removed[:20],  # cap list to avoid huge output
        "kept": kept,
        "db_sources": len(db_ids),
    })


def cmd_enrich_metadata(args):
    """Enrich sources with missing DOI/author/venue from Crossref title search.

    Queries Crossref API by title for sources missing DOI, authors, or venue.
    Updates both state.db and on-disk metadata JSON files.
    """
    import urllib.parse
    import urllib.request

    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    metadata_dir = os.path.join(args.session_dir, "sources", "metadata")

    # Find sources with missing metadata
    rows = conn.execute(
        """SELECT id, title, doi, authors, venue
           FROM sources WHERE session_id = ?
           AND (doi IS NULL OR authors = '[]' OR venue IS NULL OR venue = '')""",
        (sid,)
    ).fetchall()

    if not rows:
        conn.close()
        success_response({"enriched": 0, "attempted": 0, "message": "No sources with missing metadata"})
        return

    enriched = 0
    attempted = 0
    errors = []

    for row in rows:
        src_id = row["id"]
        title = row["title"]
        if not title or len(title) < 10:
            continue

        attempted += 1
        try:
            # Query Crossref by title
            encoded_title = urllib.parse.quote(title)
            url = f"https://api.crossref.org/works?query.title={encoded_title}&rows=1&select=DOI,author,container-title,published-print,published-online"
            req = urllib.request.Request(url, headers={
                "User-Agent": "DeepResearch/1.0 (mailto:research@example.com)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            items = data.get("message", {}).get("items", [])
            if not items:
                continue

            item = items[0]
            # Verify title similarity before applying (basic check)
            cr_title = item.get("title", [""])[0].lower() if item.get("title") else ""
            if not cr_title or len(set(title.lower().split()) & set(cr_title.split())) < 3:
                continue

            updates = {}
            db_updates = {}

            # DOI
            if not row["doi"] and item.get("DOI"):
                updates["doi"] = item["DOI"]
                db_updates["doi"] = item["DOI"]

            # Authors
            if row["authors"] == "[]" and item.get("author"):
                author_list = []
                for a in item["author"]:
                    name_parts = []
                    if a.get("given"):
                        name_parts.append(a["given"])
                    if a.get("family"):
                        name_parts.append(a["family"])
                    if name_parts:
                        author_list.append(" ".join(name_parts))
                if author_list:
                    updates["authors"] = author_list
                    db_updates["authors"] = json.dumps(author_list)

            # Venue
            if not row["venue"] and item.get("container-title"):
                venue = item["container-title"][0] if item["container-title"] else None
                if venue:
                    updates["venue"] = venue
                    db_updates["venue"] = venue

            if not db_updates:
                continue

            # Update state.db
            set_clauses = ", ".join(f"{k} = ?" for k in db_updates)
            values = list(db_updates.values()) + [src_id, sid]
            conn.execute(
                f"UPDATE sources SET {set_clauses} WHERE id = ? AND session_id = ?",
                values,
            )

            # Update on-disk metadata JSON
            from _shared.metadata import read_source_metadata, write_source_metadata
            meta = read_source_metadata(metadata_dir, src_id)
            if meta:
                meta.update(updates)
                write_source_metadata(metadata_dir, src_id, meta)

            enriched += 1
            log(f"Enriched {src_id}: {', '.join(db_updates.keys())}")

        except Exception as e:
            errors.append(f"{src_id}: {str(e)}")
            continue

    conn.commit()
    conn.close()

    result = {
        "enriched": enriched,
        "attempted": attempted,
        "total_missing": len(rows),
    }
    if errors:
        result["errors"] = errors[:5]  # Cap error list
    success_response(result)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Session state tracker")
    parser.add_argument("--quiet", action="store_true", help="Suppress stderr log output (for pipeline use)")
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p = sub.add_parser("init")
    p.add_argument("--query", required=True)
    p.add_argument("--session-dir", required=True)

    # All other subcommands get --session-dir as optional (auto-discovered)
    _sd = {"default": None, "help": "Session directory (auto-discovered from .deep-research-session marker if omitted)"}

    # export
    p = sub.add_parser("export")
    p.add_argument("--session-dir", **_sd)

    # set-brief
    p = sub.add_parser("set-brief")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # log-search
    p = sub.add_parser("log-search")
    p.add_argument("--provider", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--search-mode", default="keyword",
                   choices=["keyword", "cited_by", "references", "recommendations", "author", "browse", "fetch"],
                   help="Search mode (default: keyword)")
    p.add_argument("--search-type", default="manual",
                   choices=["manual", "recovery", "citation"],
                   help="Search type: manual (agent-initiated), recovery (recover-failed), citation (citation chasing)")
    p.add_argument("--result-count", type=int, required=True)
    p.add_argument("--ingested-count", type=int, default=None, help="Actual number of results ingested")
    p.add_argument("--session-dir", **_sd)

    # add-source
    p = sub.add_parser("add-source")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # add-sources
    p = sub.add_parser("add-sources")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # check-dup
    p = sub.add_parser("check-dup")
    p.add_argument("--doi", default=None)
    p.add_argument("--url", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--session-dir", **_sd)

    # check-dup-batch
    p = sub.add_parser("check-dup-batch")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # log-finding
    p = sub.add_parser("log-finding")
    p.add_argument("--text", required=True)
    p.add_argument("--sources", default=None)
    p.add_argument("--question", default=None)
    p.add_argument("--session-dir", **_sd)

    # log-gap
    p = sub.add_parser("log-gap")
    p.add_argument("--text", required=True)
    p.add_argument("--question", default=None)
    p.add_argument("--session-dir", **_sd)

    # resolve-gap
    p = sub.add_parser("resolve-gap")
    p.add_argument("--gap-id", required=True)
    p.add_argument("--session-dir", **_sd)

    # deduplicate-findings
    p = sub.add_parser("deduplicate-findings")
    p.add_argument("--threshold", type=float, default=0.7, help="Token overlap threshold for merging (default 0.7)")
    p.add_argument("--session-dir", **_sd)

    # gap-search-plan
    p = sub.add_parser("gap-search-plan")
    p.add_argument("--session-dir", **_sd)

    # searches
    p = sub.add_parser("searches")
    p.add_argument("--session-dir", **_sd)

    # sources
    p = sub.add_parser("sources")
    p.add_argument("--title-contains", default=None, help="Filter sources by title substring (case-insensitive)")
    p.add_argument("--min-citations", type=int, default=None, help="Only sources with >= N citations")
    p.add_argument("--providers", action="store_true", help="Return only provider distribution counts (no source list)")
    p.add_argument("--compact", action="store_true", help="Return only id, title, quality, content_file (shorthand for --fields id,title,quality,content_file)")
    p.add_argument("--fields", default=None, help="Comma-separated list of columns to return (e.g. --fields id,title,doi)")
    p.add_argument("--session-dir", **_sd)

    # get-source
    p = sub.add_parser("get-source")
    p.add_argument("--id", required=True)
    p.add_argument("--session-dir", **_sd)

    # update-source
    p = sub.add_parser("update-source")
    p.add_argument("--id", required=True)
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # summary
    p = sub.add_parser("summary")
    p.add_argument("--compact", action="store_true", help="Return counts and coverage indicators only (omit full findings/sources/metrics)")
    p.add_argument("--write-handoff", action="store_true", help="Write full summary to synthesis-handoff.json, return only path and counts")
    p.add_argument("--session-dir", **_sd)

    # mark-read
    p = sub.add_parser("mark-read")
    p.add_argument("--id", required=True)
    p.add_argument("--session-dir", **_sd)

    # set-status
    p = sub.add_parser("set-status")
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--session-dir", **_sd)

    # add-tag
    p = sub.add_parser("add-tag")
    p.add_argument("--id", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--session-dir", **_sd)

    # list-sources
    p = sub.add_parser("list-sources")
    p.add_argument("--session-dir", **_sd)

    # search-sources
    p = sub.add_parser("search-sources")
    p.add_argument("--query", required=True)
    p.add_argument("--session-dir", **_sd)

    # set-quality
    p = sub.add_parser("set-quality")
    p.add_argument("--id", required=True)
    p.add_argument("--quality", type=str, choices=["ok", "abstract_only", "degraded", "mismatched", "reader_validated"], required=True)
    p.add_argument("--session-dir", **_sd)

    # log-metric
    p = sub.add_parser("log-metric")
    p.add_argument("--ticker", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--unit", default="USD")
    p.add_argument("--period", default=None)
    p.add_argument("--filed-date", default=None)
    p.add_argument("--session-dir", **_sd)

    # log-metrics
    p = sub.add_parser("log-metrics")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # get-metrics
    p = sub.add_parser("get-metrics")
    p.add_argument("--ticker", required=True)
    p.add_argument("--session-dir", **_sd)

    # get-metric
    p = sub.add_parser("get-metric")
    p.add_argument("--metric", required=True)
    p.add_argument("--session-dir", **_sd)

    # download-pending
    p = sub.add_parser("download-pending")
    p.add_argument("--auto-download", action="store_true", help="Immediately download all pending sources")
    p.add_argument("--batch-size", type=int, default=15, help="Max sources per batch (default 15). Caller loops until remaining=0.")
    p.add_argument("--parallel", type=int, default=3, help="Parallel downloads for --auto-download (default 3)")
    p.add_argument("--timeout", type=int, default=None, help="Override download timeout in seconds (default: min(480, max(300, batch*30)))")
    p.add_argument("--prioritize-gaps", action="store_true", default=False, help="Reorder pending sources so gap-relevant ones download first")
    p.add_argument("--max-batches", type=int, default=None, help="Loop up to N batch iterations (re-querying pending between each). Returns aggregate totals with batches_run field.")
    p.add_argument("--min-relevance", type=float, default=None,
                   help="Skip sources with relevance_score at or below this value (e.g. 0.0). "
                        "Sources with no score (NULL) are still downloaded. Default: no filter.")
    p.add_argument("--session-dir", **_sd)

    # audit
    p = sub.add_parser("audit")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if audit finds warnings")
    p.add_argument("--brief", action="store_true", help="Replace ID arrays with counts (keep degraded_unread/reader_validated/mismatched as arrays)")
    p.add_argument("--session-dir", **_sd)

    # triage
    p = sub.add_parser("triage")
    p.add_argument("--top", type=int, default=25, help="Number of sources to mark as high+medium priority (default 25)")
    p.add_argument("--title-contains", default=None, help="Pre-filter: only score sources whose title contains this substring")
    p.add_argument("--session-dir", **_sd)

    # recover-failed
    p = sub.add_parser("recover-failed")
    p.add_argument("--min-citations", type=int, default=50, help="Minimum citations to consider high-priority (default 50)")
    p.add_argument("--min-relevance", type=float, default=0.3,
                   help="Skip sources with relevance_score below this threshold (default 0.3)")
    p.add_argument("--title-keywords", type=str, default="",
                   help="Comma-separated keywords; require at least one match in source title to attempt recovery")
    p.add_argument("--max-attempts", type=int, default=15,
                   help="Maximum total recovery attempts across all channels (default 15). "
                        "Channels with 0 successes after 5 attempts are auto-skipped.")
    p.add_argument("--session-dir", **_sd)

    # manifest
    p = sub.add_parser("manifest")
    p.add_argument("--mode", choices=["initial", "gap"], default="initial", help="Manifest mode (default: initial)")
    p.add_argument("--top", type=int, default=30, help="Number of top sources to include in triage scoring (default 30)")
    p.add_argument("--session-dir", **_sd)

    # enrich-metadata
    p = sub.add_parser("enrich-metadata")
    p.add_argument("--session-dir", **_sd)

    # sync-files
    p = sub.add_parser("sync-files")
    p.add_argument("--session-dir", **_sd)

    # cleanup-orphans
    p = sub.add_parser("cleanup-orphans")
    p.add_argument("--session-dir", **_sd)

    args = parser.parse_args()

    if args.quiet:
        set_quiet(True)

    # Resolve session-dir via auto-discovery for all commands except init
    if args.command != "init":
        args.session_dir = get_session_dir(args)

    commands = {
        "init": cmd_init,
        "export": cmd_export,
        "set-brief": cmd_set_brief,
        "log-search": cmd_log_search,
        "add-source": cmd_add_source,
        "add-sources": cmd_add_sources,
        "check-dup": cmd_check_dup,
        "check-dup-batch": cmd_check_dup_batch,
        "log-finding": cmd_log_finding,
        "log-gap": cmd_log_gap,
        "resolve-gap": cmd_resolve_gap,
        "deduplicate-findings": cmd_deduplicate_findings,
        "gap-search-plan": cmd_gap_search_plan,
        "searches": cmd_searches,
        "sources": cmd_sources,
        "get-source": cmd_get_source,
        "update-source": cmd_update_source,
        "summary": cmd_summary,
        "mark-read": cmd_mark_read,
        "set-status": cmd_set_status,
        "add-tag": cmd_add_tag,
        "list-sources": cmd_list_sources,
        "search-sources": cmd_search_sources,
        "set-quality": cmd_set_quality,
        "log-metric": cmd_log_metric,
        "log-metrics": cmd_log_metrics,
        "get-metrics": cmd_get_metrics,
        "get-metric": cmd_get_metric,
        "download-pending": cmd_download_pending,
        "audit": cmd_audit,
        "triage": cmd_triage,
        "recover-failed": cmd_recover_failed,
        "enrich-metadata": cmd_enrich_metadata,
        "sync-files": cmd_sync_files,
        "cleanup-orphans": cmd_cleanup_orphans,
        "manifest": cmd_manifest,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
