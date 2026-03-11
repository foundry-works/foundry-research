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
    result_count INTEGER NOT NULL,
    ingested_count INTEGER,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    UNIQUE(session_id, provider, query)
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
    quality REAL,
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


def _connect(session_dir: str, readonly: bool = False) -> sqlite3.Connection:
    db_path = os.path.join(session_dir, "state.db")
    if readonly and not os.path.exists(db_path):
        error_response([f"state.db not found in {session_dir}"])
    uri = f"file:{db_path}" + ("?mode=ro" if readonly else "")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    # Migrate: add columns to searches (for existing DBs)
    if readonly:
        # Open a brief writable connection for migrations, then close it
        rw_uri = f"file:{db_path}"
        try:
            rw_conn = sqlite3.connect(rw_uri, uri=True)
            for col, defn in [
                ("ingested_count", "INTEGER"),
                ("search_mode", "TEXT NOT NULL DEFAULT 'keyword'"),
            ]:
                try:
                    rw_conn.execute(f"ALTER TABLE searches ADD COLUMN {col} {defn}")
                    rw_conn.commit()
                except sqlite3.OperationalError:
                    pass  # column already exists
            rw_conn.close()
        except Exception:
            pass  # DB may not exist yet or truly readonly filesystem
    else:
        for col, defn in [
            ("ingested_count", "INTEGER"),
            ("search_mode", "TEXT NOT NULL DEFAULT 'keyword'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE searches ADD COLUMN {col} {defn}")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists
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
    try:
        conn.execute(
            "INSERT INTO searches (id, session_id, provider, query, search_mode, result_count, ingested_count, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (search_id, sid, args.provider, args.query, search_mode, args.result_count, ingested_count, _now())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        success_response({"duplicate": True, "provider": args.provider, "query": args.query})
        return

    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": search_id, "provider": args.provider, "query": args.query, "search_mode": search_mode})


def cmd_add_source(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_dict(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    result = _insert_source(conn, sid, data)
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
            result = _insert_source(conn, sid, source)
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


def _insert_source(conn: sqlite3.Connection, session_id: str, data: dict) -> dict:
    """Insert a single source with dedup. Returns result dict."""
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
           pdf_url, venue, citation_count, type, provider, content_file, pdf_file, added_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, session_id, title, json.dumps(authors), year,
         data.get("abstract"), doi, url, data.get("pdf_url"),
         data.get("venue"), data.get("citation_count"),
         data.get("type", "academic"), data.get("provider", "unknown"),
         data.get("content_file"), data.get("pdf_file"), _now())
    )
    return {"id": source_id, "title": title, "duplicate": False}


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


def cmd_log_finding(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    finding_id = _next_id(conn, "findings", "finding", sid)

    source_ids = [s.strip() for s in args.sources.split(",")] if args.sources else []
    conn.execute(
        "INSERT INTO findings (id, session_id, text, sources, question, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (finding_id, sid, args.text, json.dumps(source_ids), args.question, _now())
    )
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": finding_id, "text": args.text})


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
        "SELECT id, provider, query, search_mode, result_count, ingested_count, timestamp FROM searches WHERE session_id = ? ORDER BY id",
        (sid,)
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


def cmd_sources(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT id, title, type, provider, doi, url, citation_count, added_at FROM sources WHERE session_id = ? ORDER BY id",
        (sid,)
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
    source_rows = conn.execute("SELECT id, title, type, provider FROM sources WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
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
    success_response({
        "brief": brief_data,
        "search_count": search_count,
        "source_count": source_count,
        "sources_by_type": sources_by_type,
        "sources_by_provider": sources_by_provider,
        "sources": source_list,
        "findings": findings_list,
        "gaps": gaps_list,
        "metrics": metrics_list,
    })


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
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": args.id, "is_read": True})


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

def cmd_download_pending(args):
    """List or download sources that have no on-disk content."""
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        """SELECT id, title, doi, url, pdf_url, type, status
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
    log(f"Found {len(pending)} sources without on-disk content")

    batch_size = getattr(args, "batch_size", None)
    total_pending = len(pending)

    if args.auto_download and pending:
        # Apply batch-size limit: process only the first N, caller loops until remaining=0
        if batch_size and batch_size < len(pending):
            log(f"Batch size {batch_size}: processing first {batch_size} of {len(pending)} pending")
            pending = pending[:batch_size]

        timeout_override = getattr(args, "timeout", None)
        _auto_download_pending(args.session_dir, pending, args.parallel, timeout_override, total_pending)
        return

    success_response(pending, total_results=total_pending)


def _auto_download_pending(session_dir: str, pending: list, parallel: int, timeout_override: int | None = None, total_pending: int | None = None) -> None:
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
        success_response({"downloaded": 0, "message": "No downloadable sources found"})
        return

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
    success_response({
        "downloaded": downloaded,
        "failed": len(remaining),
        "failed_sources": sorted(remaining),
        "batch_size": len(source_attempts),
        "remaining": remaining_pending,
    })


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
    degraded = []
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
                degraded.append(sid_val)
            elif quality == "mismatched":
                mismatched.append(sid_val)
            elif quality == "abstract_only":
                abstract_only.append(sid_val)
        elif isinstance(quality, (int, float)) and quality < 0.5:
            degraded.append(sid_val)

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

    # Build warnings
    warnings = []
    for sid_val in degraded:
        warnings.append(f"{sid_val} has degraded PDF quality — do not claim deep reading")
    for sid_val in mismatched:
        warnings.append(f"{sid_val} has mismatched content — downloaded PDF may be wrong paper")
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
    log(f"Degraded quality:    {len(degraded)}  ({', '.join(degraded)})" if degraded else "Degraded quality:    0")
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
    audit_result = {
        "sources_tracked": len(sources),
        "sources_downloaded": total_downloaded,
        "downloaded_ids": downloaded,
        "sources_with_notes": deep_reads,
        "notes_ids": with_notes,
        "degraded_quality": degraded,
        "mismatched_content": mismatched,
        "abstract_only": abstract_only,
        "no_content": no_content,
        "findings_count": len(findings),
        "findings_by_question": {k: len(v) for k, v in findings_by_question.items()},
        "open_gaps": len(gaps),
        "sparse_questions": sparse_questions,
        "methodology": {
            "deep_reads": deep_reads,
            "abstract_only": total_abstract_only,
            "web_sources": web_sources,
        },
        "warnings": warnings,
    }

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

def cmd_triage(args):
    """Rank sources by citation count × title-keyword-relevance to brief questions.

    Outputs sources in priority tiers (high/medium/low) to help the agent decide
    which sources to download and read. Sources with quality issues are flagged.
    """
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    # Load brief questions for relevance scoring
    brief_row = conn.execute("SELECT * FROM brief WHERE session_id = ?", (sid,)).fetchone()
    question_terms = _extract_question_terms(json.loads(brief_row["questions"])) if brief_row else []

    # Load all sources
    sources = [dict(r) for r in conn.execute(
        "SELECT id, title, authors, year, doi, url, pdf_url, citation_count, type, provider, "
        "content_file, pdf_file, is_read, quality, status "
        "FROM sources WHERE session_id = ? ORDER BY id", (sid,)
    ).fetchall()]
    conn.close()

    # Score each source
    import math
    scored = []
    for s in sources:
        title = (s.get("title") or "").lower()

        # Title keyword relevance: count how many brief-question keywords appear in title
        keyword_hits = sum(1 for t in question_terms if t in title) if question_terms else 0
        # Normalize to 0-1 range (cap at 5 hits)
        relevance = min(keyword_hits / 5.0, 1.0) if question_terms else 0.5

        # Citation score: log-scale to avoid extreme skew from mega-cited papers
        cite_count = s.get("citation_count") or 0
        cite_score = math.log1p(cite_count)  # log(1 + citations)

        # Combined score: citation_score × (0.5 + relevance)
        # The 0.5 base ensures even 0-relevance papers with high citations get some score
        score = cite_score * (0.5 + relevance)

        # Check on-disk status
        sources_dir = os.path.join(args.session_dir, "sources")
        has_content = False
        if s.get("content_file"):
            has_content = os.path.exists(os.path.join(args.session_dir, s["content_file"]))
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
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Assign priority tiers
    top_n = getattr(args, "top", 25)
    for i, item in enumerate(scored):
        if item["quality_flag"]:
            item["priority"] = "skip"
        elif i < top_n // 2:
            item["priority"] = "high"
        elif i < top_n:
            item["priority"] = "medium"
        else:
            item["priority"] = "low"

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
            "brief_keywords_used": len(question_terms),
        },
        "top_sources": [
            {"id": s["id"], "title": s["title"], "citation_count": s["citation_count"], "tier": s["priority"], "score": s["score"]}
            for s in scored if s["priority"] in ("high", "medium")
        ],
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
        """SELECT id, title, doi, url, pdf_url, citation_count, type
           FROM sources WHERE session_id = ?
           AND content_file IS NULL AND pdf_file IS NULL
           ORDER BY citation_count DESC NULLS LAST""",
        (sid,)
    ).fetchall()
    conn.close()

    sources_dir = os.path.join(args.session_dir, "sources")
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
        keyword_hits = sum(1 for t in question_terms if t in title) if question_terms else 0

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
            })

    if not failed:
        success_response({"recovered": 0, "message": "No high-priority failed sources found"})
        return

    log(f"Found {len(failed)} high-priority failed sources for recovery")

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    search_script = os.path.join(scripts_dir, "search.py")
    download_script = os.path.join(scripts_dir, "download.py")

    recovered = []
    still_failed = []

    for item in failed:
        sid_val = item["source_id"]
        title = item["title"] or ""
        doi = item.get("doi")

        # Check if recovered by a previous pass in this loop
        if any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
            recovered.append(sid_val)
            continue

        # Strategy 1: CORE search by title
        success = False
        if title:
            try:
                cmd = [
                    sys.executable, search_script,
                    "--provider", "core",
                    "--query", title[:200],
                    "--limit", "3",
                    "--session-dir", args.session_dir,
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
                                        success = True
                                        break
                    except (json.JSONDecodeError, TypeError):
                        pass
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"CORE recovery failed for {sid_val}: {e}", level="debug")

        if success:
            continue

        # Strategy 2: Tavily search for "title pdf"
        if title:
            try:
                cmd = [
                    sys.executable, search_script,
                    "--provider", "tavily",
                    "--query", f'"{title[:150]}" pdf',
                    "--limit", "3",
                    "--session-dir", args.session_dir,
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
                                        success = True
                                        break
                    except (json.JSONDecodeError, TypeError):
                        pass
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"Tavily recovery failed for {sid_val}: {e}", level="debug")

        if success:
            continue

        # Strategy 3: DOI landing page as web source
        if doi:
            try:
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
                        success = True
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"DOI landing page recovery failed for {sid_val}: {e}", level="debug")

        if not success:
            still_failed.append(sid_val)

    success_response({
        "recovered": len(recovered),
        "recovered_sources": recovered,
        "still_failed": len(still_failed),
        "still_failed_sources": still_failed,
        "attempted": len(failed),
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

    # gap-search-plan
    p = sub.add_parser("gap-search-plan")
    p.add_argument("--session-dir", **_sd)

    # searches
    p = sub.add_parser("searches")
    p.add_argument("--session-dir", **_sd)

    # sources
    p = sub.add_parser("sources")
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
    p.add_argument("--quality", type=float, required=True)
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
    p.add_argument("--session-dir", **_sd)

    # audit
    p = sub.add_parser("audit")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if audit finds warnings")
    p.add_argument("--session-dir", **_sd)

    # triage
    p = sub.add_parser("triage")
    p.add_argument("--top", type=int, default=25, help="Number of sources to mark as high+medium priority (default 25)")
    p.add_argument("--session-dir", **_sd)

    # recover-failed
    p = sub.add_parser("recover-failed")
    p.add_argument("--min-citations", type=int, default=50, help="Minimum citations to consider high-priority (default 50)")
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
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
