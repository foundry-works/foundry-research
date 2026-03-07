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

from _shared.doi_utils import canonicalize_url, normalize_doi
from _shared.output import error_response, success_response

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
    result_count INTEGER NOT NULL,
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
        print(json.dumps({"status": "error", "errors": [f"state.db not found in {session_dir}"], "results": [], "total_results": 0}))
        sys.exit(1)
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
    data = _load_json_dict(args.from_json)
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

    try:
        conn.execute(
            "INSERT INTO searches (id, session_id, provider, query, result_count, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (search_id, sid, args.provider, args.query, args.result_count, _now())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        success_response({"duplicate": True, "provider": args.provider, "query": args.query})
        return

    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"id": search_id, "provider": args.provider, "query": args.query})


def cmd_add_source(args):
    data = _load_json_dict(args.from_json)
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    result = _insert_source(conn, sid, data)
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response(result)


def cmd_add_sources(args):
    data = _load_json_list(args.from_json)

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
    data = _load_json_list(args.from_json)

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


def cmd_searches(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT id, provider, query, result_count, timestamp FROM searches WHERE session_id = ? ORDER BY id",
        (sid,)
    ).fetchall()
    conn.close()
    success_response([dict(r) for r in rows])


def cmd_sources(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    rows = conn.execute(
        "SELECT id, title, type, provider, doi, url, added_at FROM sources WHERE session_id = ? ORDER BY id",
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
    data = _load_json_dict(args.from_json)
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
    data = _load_json_list(args.from_json)

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


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Session state tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p = sub.add_parser("init")
    p.add_argument("--query", required=True)
    p.add_argument("--session-dir", required=True)

    # export
    p = sub.add_parser("export")
    p.add_argument("--session-dir", required=True)

    # set-brief
    p = sub.add_parser("set-brief")
    p.add_argument("--from-json", required=True)
    p.add_argument("--session-dir", required=True)

    # log-search
    p = sub.add_parser("log-search")
    p.add_argument("--provider", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--result-count", type=int, required=True)
    p.add_argument("--session-dir", required=True)

    # add-source
    p = sub.add_parser("add-source")
    p.add_argument("--from-json", required=True)
    p.add_argument("--session-dir", required=True)

    # add-sources
    p = sub.add_parser("add-sources")
    p.add_argument("--from-json", required=True)
    p.add_argument("--session-dir", required=True)

    # check-dup
    p = sub.add_parser("check-dup")
    p.add_argument("--doi", default=None)
    p.add_argument("--url", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--session-dir", required=True)

    # check-dup-batch
    p = sub.add_parser("check-dup-batch")
    p.add_argument("--from-json", required=True)
    p.add_argument("--session-dir", required=True)

    # log-finding
    p = sub.add_parser("log-finding")
    p.add_argument("--text", required=True)
    p.add_argument("--sources", default=None)
    p.add_argument("--question", default=None)
    p.add_argument("--session-dir", required=True)

    # log-gap
    p = sub.add_parser("log-gap")
    p.add_argument("--text", required=True)
    p.add_argument("--question", default=None)
    p.add_argument("--session-dir", required=True)

    # resolve-gap
    p = sub.add_parser("resolve-gap")
    p.add_argument("--gap-id", required=True)
    p.add_argument("--session-dir", required=True)

    # searches
    p = sub.add_parser("searches")
    p.add_argument("--session-dir", required=True)

    # sources
    p = sub.add_parser("sources")
    p.add_argument("--session-dir", required=True)

    # get-source
    p = sub.add_parser("get-source")
    p.add_argument("--id", required=True)
    p.add_argument("--session-dir", required=True)

    # update-source
    p = sub.add_parser("update-source")
    p.add_argument("--id", required=True)
    p.add_argument("--from-json", required=True)
    p.add_argument("--session-dir", required=True)

    # summary
    p = sub.add_parser("summary")
    p.add_argument("--session-dir", required=True)

    # mark-read
    p = sub.add_parser("mark-read")
    p.add_argument("--id", required=True)
    p.add_argument("--session-dir", required=True)

    # set-status
    p = sub.add_parser("set-status")
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--session-dir", required=True)

    # add-tag
    p = sub.add_parser("add-tag")
    p.add_argument("--id", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--session-dir", required=True)

    # list-sources
    p = sub.add_parser("list-sources")
    p.add_argument("--session-dir", required=True)

    # search-sources
    p = sub.add_parser("search-sources")
    p.add_argument("--query", required=True)
    p.add_argument("--session-dir", required=True)

    # set-quality
    p = sub.add_parser("set-quality")
    p.add_argument("--id", required=True)
    p.add_argument("--quality", type=float, required=True)
    p.add_argument("--session-dir", required=True)

    # log-metric
    p = sub.add_parser("log-metric")
    p.add_argument("--ticker", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--unit", default="USD")
    p.add_argument("--period", default=None)
    p.add_argument("--filed-date", default=None)
    p.add_argument("--session-dir", required=True)

    # log-metrics
    p = sub.add_parser("log-metrics")
    p.add_argument("--from-json", required=True)
    p.add_argument("--session-dir", required=True)

    # get-metrics
    p = sub.add_parser("get-metrics")
    p.add_argument("--ticker", required=True)
    p.add_argument("--session-dir", required=True)

    # get-metric
    p = sub.add_parser("get-metric")
    p.add_argument("--metric", required=True)
    p.add_argument("--session-dir", required=True)

    args = parser.parse_args()

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
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
