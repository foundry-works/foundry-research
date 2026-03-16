#!/usr/bin/env python3
"""Compute all Layer 1 deterministic metrics for a deep-research session.

Outputs a single JSON object to stdout. Exit 0 always; errors are collected
in a top-level "errors" array (following the deep-research output convention,
but self-contained — no cross-skill imports).

Usage:
    python3 metrics.py SESSION_DIR
"""

import json
import re
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for a table."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _count_glob(directory: Path, pattern: str) -> int:
    """Count files matching a glob pattern in directory."""
    return len(list(directory.glob(pattern)))


# ---------------------------------------------------------------------------
# Search metrics
# ---------------------------------------------------------------------------

def _search_metrics(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()
    cols = _table_columns(conn, "searches")

    total = cur.execute("SELECT count(*) FROM searches").fetchone()[0]

    # ingested_count may not exist in older sessions
    if "ingested_count" in cols:
        zero_ingested = cur.execute(
            "SELECT count(*) FROM searches "
            "WHERE (ingested_count = 0 OR ingested_count IS NULL) AND result_count > 0"
        ).fetchone()[0]
    else:
        zero_ingested = None

    providers = [r[0] for r in cur.execute("SELECT DISTINCT provider FROM searches").fetchall()]

    modes = (
        [r[0] for r in cur.execute("SELECT DISTINCT search_mode FROM searches").fetchall()]
        if "search_mode" in cols else []
    )
    types = (
        [r[0] for r in cur.execute("SELECT DISTINCT search_type FROM searches").fetchall()]
        if "search_type" in cols else []
    )

    by_provider = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT provider, count(*) FROM searches GROUP BY provider ORDER BY count(*) DESC"
        ).fetchall()
    }

    return {
        "searches_total": total,
        "searches_zero_ingested": zero_ingested,
        "search_providers": providers,
        "search_modes": modes,
        "search_types": types,
        "searches_by_provider": by_provider,
    }


# ---------------------------------------------------------------------------
# Source metrics
# ---------------------------------------------------------------------------

def _source_metrics(conn: sqlite3.Connection, session_dir: Path) -> dict:
    cur = conn.cursor()

    total = cur.execute("SELECT count(*) FROM sources").fetchone()[0]
    downloaded = cur.execute("SELECT count(*) FROM sources WHERE status = 'downloaded'").fetchone()[0]
    with_notes = cur.execute("SELECT count(*) FROM sources WHERE is_read = 1").fetchone()[0]
    with_doi = cur.execute(
        "SELECT count(*) FROM sources WHERE doi IS NOT NULL AND doi != ''"
    ).fetchone()[0]
    with_venue = cur.execute(
        "SELECT count(*) FROM sources WHERE venue IS NOT NULL AND venue != ''"
    ).fetchone()[0]
    with_citations = cur.execute(
        "SELECT count(*) FROM sources WHERE citation_count IS NOT NULL"
    ).fetchone()[0]

    orphaned = cur.execute(
        "SELECT count(*) FROM sources "
        "WHERE status = 'downloaded' AND (content_file IS NULL OR content_file = '')"
    ).fetchone()[0]

    by_provider = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT provider, count(*) FROM sources GROUP BY provider ORDER BY count(*) DESC"
        ).fetchall()
    }
    by_type = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT type, count(*) FROM sources GROUP BY type ORDER BY count(*) DESC"
        ).fetchall()
    }
    by_quality = {
        (r[0] or "null"): r[1]
        for r in cur.execute(
            "SELECT quality, count(*) FROM sources GROUP BY quality ORDER BY count(*) DESC"
        ).fetchall()
    }
    by_status = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT status, count(*) FROM sources GROUP BY status ORDER BY count(*) DESC"
        ).fetchall()
    }
    by_year = {
        str(r[0]): r[1]
        for r in cur.execute(
            "SELECT year, count(*) FROM sources WHERE year IS NOT NULL "
            "GROUP BY year ORDER BY year DESC"
        ).fetchall()
    }

    # Infrastructure cross-checks
    metadata_count = _count_glob(session_dir / "sources" / "metadata", "*.json")
    notes_on_disk = _count_glob(session_dir / "notes", "*.md")

    return {
        "sources_total": total,
        "sources_downloaded": downloaded,
        "sources_with_notes": with_notes,
        "sources_with_doi": with_doi,
        "sources_with_venue": with_venue,
        "sources_with_citations": with_citations,
        "sources_orphaned": orphaned,
        "sources_by_provider": by_provider,
        "sources_by_type": by_type,
        "sources_by_quality": by_quality,
        "sources_by_status": by_status,
        "sources_by_year": by_year,
        "metadata_json_count": metadata_count,
        "notes_on_disk": notes_on_disk,
    }


# ---------------------------------------------------------------------------
# Coverage metrics
# ---------------------------------------------------------------------------

def _coverage_metrics(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()

    findings_total = cur.execute("SELECT count(*) FROM findings").fetchone()[0]

    by_question = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT question, count(*) FROM findings GROUP BY question"
        ).fetchall()
    }

    unsourced = cur.execute(
        "SELECT count(*) FROM findings "
        "WHERE sources IS NULL OR sources = '[]' OR sources = ''"
    ).fetchone()[0]

    gaps_total = cur.execute("SELECT count(*) FROM gaps").fetchone()[0]
    gaps_resolved = cur.execute("SELECT count(*) FROM gaps WHERE status = 'resolved'").fetchone()[0]
    gaps_open = cur.execute("SELECT count(*) FROM gaps WHERE status = 'open'").fetchone()[0]

    return {
        "findings_total": findings_total,
        "findings_by_question": by_question,
        "findings_unsourced": unsourced,
        "gaps_total": gaps_total,
        "gaps_resolved": gaps_resolved,
        "gaps_open": gaps_open,
    }


# ---------------------------------------------------------------------------
# Report metrics
# ---------------------------------------------------------------------------

def _report_metrics(session_dir: Path) -> dict:
    report_path = session_dir / "report.md"
    if not report_path.exists():
        return {
            "report_exists": False,
            "report_word_count": 0,
            "report_section_count": 0,
            "report_reference_count": 0,
            "report_unique_citations": 0,
            "report_citation_instances": 0,
            "report_max_citation": 0,
            "report_phantom_refs": 0,
        }

    text = report_path.read_text(encoding="utf-8", errors="replace")
    words = len(text.split())

    # Count ## headings as sections
    sections = len(re.findall(r"^##\s", text, re.MULTILINE))

    # References: count entries in the References section
    # Reports use various formats: [N], list items (- or *), or numbered (1. / 1))
    ref_count = 0
    ref_match = re.search(r"^#{1,2}\s+References\s*$", text, re.MULTILINE | re.IGNORECASE)
    if ref_match:
        ref_section = text[ref_match.end():]
        # Stop at next heading
        next_heading = re.search(r"^#{1,2}\s", ref_section, re.MULTILINE)
        if next_heading:
            ref_section = ref_section[:next_heading.start()]
        # Count lines that start with [N], list marker, or numbered reference
        ref_count = len(re.findall(
            r"^\s*(?:\[\d+\]|[-*]|\d+[.\)])\s+", ref_section, re.MULTILINE
        ))

    # Citation markers [N] in body (before References section)
    body_text = text[:ref_match.start()] if ref_match else text
    citation_markers = re.findall(r"\[(\d+)\]", body_text)
    citation_numbers = [int(c) for c in citation_markers]
    unique_citations = len(set(citation_numbers))
    total_instances = len(citation_numbers)
    max_citation = max(citation_numbers) if citation_numbers else 0

    # Phantom refs: max citation number exceeds reference list length
    phantom = max(0, max_citation - ref_count) if ref_count > 0 else 0

    return {
        "report_exists": True,
        "report_word_count": words,
        "report_section_count": sections,
        "report_reference_count": ref_count,
        "report_unique_citations": unique_citations,
        "report_citation_instances": total_instances,
        "report_max_citation": max_citation,
        "report_phantom_refs": phantom,
    }


# ---------------------------------------------------------------------------
# File counts
# ---------------------------------------------------------------------------

def _file_counts(session_dir: Path) -> dict:
    return {
        "source_md_files": _count_glob(session_dir / "sources", "*.md"),
        "notes_md_files": _count_glob(session_dir / "notes", "*.md"),
        "metadata_json_files": _count_glob(session_dir / "sources" / "metadata", "*.json"),
        "toc_files": _count_glob(session_dir / "sources", "*.toc"),
    }


# ---------------------------------------------------------------------------
# Journal metrics
# ---------------------------------------------------------------------------

MILESTONE_PATTERNS = [
    r"brief\s+set",
    r"source.acquisition\s+return",
    r"readers?\s+complete",
    r"gap.mode\s+return",
    r"synthesis\s+handoff",
]


def _journal_metrics(session_dir: Path) -> dict:
    journal_path = session_dir / "journal.md"
    if not journal_path.exists():
        return {
            "journal_exists": False,
            "journal_char_count": 0,
            "journal_milestones_found": 0,
            "journal_milestones_detail": {},
        }

    text = journal_path.read_text(encoding="utf-8", errors="replace")
    char_count = len(text)

    milestones = {}
    for pattern in MILESTONE_PATTERNS:
        milestones[pattern] = bool(re.search(pattern, text, re.IGNORECASE))

    found = sum(1 for v in milestones.values() if v)

    return {
        "journal_exists": True,
        "journal_char_count": char_count,
        "journal_milestones_found": found,
        "journal_milestones_detail": {k: v for k, v in milestones.items()},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "status": "error",
            "errors": ["Usage: metrics.py SESSION_DIR"],
            "metrics": {},
        }))
        sys.exit(0)

    session_dir = Path(sys.argv[1]).resolve()
    errors: list[str] = []
    metrics: dict = {}

    # Validate session directory
    if not session_dir.is_dir():
        print(json.dumps({
            "status": "error",
            "errors": [f"Session directory not found: {session_dir}"],
            "metrics": {},
        }))
        sys.exit(0)

    db_path = session_dir / "state.db"
    if not db_path.exists():
        errors.append(f"state.db not found in {session_dir}")
    else:
        try:
            conn = _connect(db_path)
            metrics.update(_search_metrics(conn))
            metrics.update(_source_metrics(conn, session_dir))
            metrics.update(_coverage_metrics(conn))
            conn.close()
        except Exception as e:
            errors.append(f"Database error: {e}")

    # Report metrics (file-based, independent of db)
    try:
        metrics.update(_report_metrics(session_dir))
    except Exception as e:
        errors.append(f"Report metrics error: {e}")

    # File counts
    try:
        metrics.update(_file_counts(session_dir))
    except Exception as e:
        errors.append(f"File count error: {e}")

    # Journal metrics
    try:
        metrics.update(_journal_metrics(session_dir))
    except Exception as e:
        errors.append(f"Journal metrics error: {e}")

    status = "ok" if not errors else "partial"
    print(json.dumps({"status": status, "errors": errors, "metrics": metrics}, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
