#!/usr/bin/env python3
"""Compute all Layer 1 deterministic metrics for a deep-research session.

Outputs a single JSON object to stdout. Exit 0 always; errors are collected
in a top-level "errors" array (following the deep-research output convention,
but self-contained — no cross-skill imports).

Usage:
    python3 metrics.py SESSION_DIR
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# Reuse evidence helpers from the deep-research skill to avoid logic divergence
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "deep-research", "scripts"))
from _shared.evidence_helpers import count_evidence_by_question


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for a table."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _count_glob(directory: Path, pattern: str) -> int:
    """Count files matching a glob pattern in directory."""
    return len(list(directory.glob(pattern)))


def _canonical_source_quality(quality: object) -> str:
    aliases = {
        "degraded": "degraded_extraction",
        "empty": "inaccessible",
        "paywall_page": "inaccessible",
        "paywall_stub": "abstract_only",
        "mismatched": "title_content_mismatch",
        "reader_validated": "ok",
    }
    canonical = {
        "ok",
        "inaccessible",
        "abstract_only",
        "degraded_extraction",
        "metadata_incomplete",
        "title_content_mismatch",
    }
    if quality is None or quality == "":
        return "unknown"
    if isinstance(quality, int | float):
        return "degraded_extraction" if quality < 0.5 else "ok"
    if not isinstance(quality, str):
        return "unknown"
    return aliases.get(quality, quality if quality in canonical else "unknown")


def _normalized_label(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return _json_list(parsed)
    return []


_WEAK_SUPPORT_CLASSIFICATIONS = {
    "weak",
    "weak_support",
    "unsupported",
    "partially_supported",
    "topically_related_only",
    "overstated",
    "missing_specific_fact",
    "needs_additional_source",
    "unresolved",
    "unverifiable",
}
_CITATION_WEAKENED_ACTIONS = {
    "weaken_wording",
    "split_claim",
    "add_source",
    "replace_source",
    "mark_unresolved",
}
_CLOSED_REVIEW_ISSUE_STATUSES = {
    "resolved",
    "accepted_as_limitation",
    "rejected_with_rationale",
}
_QUANTITATIVE_OR_FRAGILE_CLAIM_TYPES = {
    "quantitative",
    "fragile",
    "current",
    "high_stakes",
    "citation_sensitive",
}
_SOURCE_ACCESS_WARNING_QUALITIES = {
    "inaccessible",
    "abstract_only",
    "degraded_extraction",
    "metadata_incomplete",
    "title_content_mismatch",
}


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
    by_access_quality: dict[str, int] = {}
    for row in cur.execute("SELECT quality, count(*) FROM sources GROUP BY quality").fetchall():
        canonical_quality = _canonical_source_quality(row[0])
        by_access_quality[canonical_quality] = by_access_quality.get(canonical_quality, 0) + row[1]
    sources_with_quality_warnings = sum(
        count for quality, count in by_access_quality.items()
        if quality in _SOURCE_ACCESS_WARNING_QUALITIES
    )

    source_caution_total = 0
    source_caution_by_flag: dict[str, int] = {}
    source_caution_by_scope: dict[str, int] = {}
    sources_with_cautions = 0
    if _table_exists(conn, "source_flags"):
        source_caution_total = cur.execute("SELECT count(*) FROM source_flags").fetchone()[0]
        source_caution_by_flag = {
            r[0]: r[1]
            for r in cur.execute(
                "SELECT flag, count(*) FROM source_flags GROUP BY flag ORDER BY count(*) DESC"
            ).fetchall()
        }
        source_caution_by_scope = {
            r[0]: r[1]
            for r in cur.execute(
                "SELECT applies_to_type, count(*) FROM source_flags GROUP BY applies_to_type ORDER BY count(*) DESC"
            ).fetchall()
        }
        sources_with_cautions = cur.execute("SELECT count(DISTINCT source_id) FROM source_flags").fetchone()[0]
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
        "sources_by_access_quality": by_access_quality,
        "sources_with_extraction_access_quality_warnings": sources_with_quality_warnings,
        "sources_by_status": by_status,
        "sources_by_year": by_year,
        "source_caution_flags_total": source_caution_total,
        "source_caution_flags_by_flag": source_caution_by_flag,
        "source_caution_flags_by_scope": source_caution_by_scope,
        "sources_with_caution_flags": sources_with_cautions,
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
    r"brief",
    r"source.acqui",
    r"reader|reading|deep.read",
    r"gap.mode|gap.analysis|gap.search|gap.driven",
    r"synth|pre.synthesis|draft\s+complete|report\s+draft",
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
# Evidence metrics
# ---------------------------------------------------------------------------

def _evidence_metrics(conn: sqlite3.Connection, session_dir: Path) -> dict:
    """Compute evidence layer metrics. Graceful no-op if tables don't exist."""
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if "evidence_units" not in tables:
        return {
            "evidence_units_total": 0,
            "evidence_units_by_claim_type": {},
            "evidence_units_by_question": {},
            "evidence_units_by_source": {},
            "evidence_units_with_spans": 0,
            "evidence_units_avg_per_source": 0.0,
            "evidence_json_files": _count_glob(session_dir / "evidence", "*.json"),
            "evidence_link_count": 0,
            "findings_with_evidence": 0,
            "findings_without_evidence": 0,
        }

    cur = conn.cursor()

    total = cur.execute(
        "SELECT COUNT(*) FROM evidence_units WHERE status = 'active'"
    ).fetchone()[0]

    by_type = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT claim_type, COUNT(*) FROM evidence_units WHERE status = 'active' GROUP BY claim_type"
        ).fetchall()
    }

    by_question = count_evidence_by_question(cur.execute(
        "SELECT primary_question_id, question_ids FROM evidence_units "
        "WHERE status = 'active'"
    ).fetchall())

    by_source = {
        r[0]: r[1]
        for r in cur.execute(
            "SELECT source_id, COUNT(*) FROM evidence_units WHERE status = 'active' GROUP BY source_id"
        ).fetchall()
    }

    with_spans = cur.execute(
        "SELECT COUNT(*) FROM evidence_units "
        "WHERE status = 'active' AND line_start IS NOT NULL AND line_end IS NOT NULL"
    ).fetchone()[0]

    distinct_sources = len(by_source)
    avg_per_source = round(total / distinct_sources, 1) if distinct_sources > 0 else 0.0

    evidence_json_files = _count_glob(session_dir / "evidence", "*.json")

    # Finding-evidence linkage
    link_count = 0
    findings_with = 0
    findings_without = 0

    if "finding_evidence" in tables and total > 0:
        link_count = cur.execute(
            "SELECT COUNT(*) FROM finding_evidence fe "
            "INNER JOIN evidence_units eu ON fe.evidence_id = eu.id "
            "WHERE eu.status = 'active'"
        ).fetchone()[0]

        findings_total = cur.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        if findings_total > 0:
            findings_with = cur.execute(
                "SELECT COUNT(DISTINCT f.id) FROM findings f "
                "INNER JOIN finding_evidence fe ON f.id = fe.finding_id "
                "INNER JOIN evidence_units eu ON fe.evidence_id = eu.id "
                "WHERE eu.status = 'active'"
            ).fetchone()[0]
            findings_without = findings_total - findings_with

    return {
        "evidence_units_total": total,
        "evidence_units_by_claim_type": by_type,
        "evidence_units_by_question": by_question,
        "evidence_units_by_source": by_source,
        "evidence_units_with_spans": with_spans,
        "evidence_units_avg_per_source": avg_per_source,
        "evidence_json_files": evidence_json_files,
        "evidence_link_count": link_count,
        "findings_with_evidence": findings_with,
        "findings_without_evidence": findings_without,
    }


# ---------------------------------------------------------------------------
# Ingested support artifact metrics
# ---------------------------------------------------------------------------

def _flagged_report_target_count(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "report_targets") or not _table_exists(conn, "source_flags"):
        return 0

    targets = [dict(row) for row in conn.execute(
        "SELECT target_id, citation_refs, source_ids FROM report_targets"
    ).fetchall()]
    if not targets:
        return 0

    finding_links: dict[str, set[str]] = {}
    if _table_exists(conn, "report_target_findings"):
        for row in conn.execute("SELECT target_id, finding_id FROM report_target_findings").fetchall():
            finding_links.setdefault(row["target_id"], set()).add(row["finding_id"])

    flags_by_source: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT * FROM source_flags").fetchall():
        flags_by_source.setdefault(row["source_id"], []).append(dict(row))

    flagged: set[str] = set()
    for target in targets:
        target_id = target["target_id"]
        citations = set(_json_list(target.get("citation_refs")))
        findings = finding_links.get(target_id, set())
        for source_id in _json_list(target.get("source_ids")):
            for flag in flags_by_source.get(source_id, []):
                scope = flag.get("applies_to_type")
                applies_to_id = flag.get("applies_to_id") or ""
                if scope in ("run", "brief"):
                    flagged.add(target_id)
                elif scope == "report_target" and applies_to_id == target_id:
                    flagged.add(target_id)
                elif scope == "finding" and applies_to_id in findings:
                    flagged.add(target_id)
                elif scope == "citation" and applies_to_id in citations:
                    flagged.add(target_id)
    return len(flagged)


def _support_artifact_metrics(conn: sqlite3.Connection) -> dict:
    metrics = {
        "report_targets_total": 0,
        "report_targets_with_declared_finding_links": 0,
        "report_targets_with_declared_evidence_links": 0,
        "report_targets_without_grounding": 0,
        "quantitative_or_fragile_targets_without_structured_evidence": 0,
        "report_targets_depending_on_flagged_sources": 0,
        "citations_audited": 0,
        "citations_weakened_or_rejected": 0,
        "reviewer_issues_with_target_ids": 0,
        "reviewer_issues_resolved_before_delivery": 0,
        "unresolved_issues_before_delivery": 0,
        "citations_classified_weak_overstated_or_topically_related_only": 0,
        "unresolved_contradictions_or_limitations_disclosed": 0,
        "unresolved_contradictions_or_limitations_needing_review": 0,
    }

    if _table_exists(conn, "report_targets"):
        metrics["report_targets_total"] = conn.execute("SELECT COUNT(*) FROM report_targets").fetchone()[0]
        if _table_exists(conn, "report_target_findings"):
            metrics["report_targets_with_declared_finding_links"] = conn.execute(
                "SELECT COUNT(DISTINCT target_id) FROM report_target_findings"
            ).fetchone()[0]
        if _table_exists(conn, "report_target_evidence"):
            metrics["report_targets_with_declared_evidence_links"] = conn.execute(
                "SELECT COUNT(DISTINCT target_id) FROM report_target_evidence"
            ).fetchone()[0]
        metrics["report_targets_without_grounding"] = conn.execute(
            """SELECT COUNT(*) FROM report_targets rt
               WHERE rt.is_ungrounded = 1 OR (
                   COALESCE(rt.not_grounded_reason, '') = ''
                   AND NOT EXISTS (
                       SELECT 1 FROM report_target_evidence rte
                       WHERE rte.session_id = rt.session_id AND rte.target_id = rt.target_id
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM report_target_findings rtf
                       WHERE rtf.session_id = rt.session_id AND rtf.target_id = rt.target_id
                   )
               )"""
        ).fetchone()[0]
        fragile = 0
        for row in conn.execute("SELECT target_id, claim_type FROM report_targets").fetchall():
            if _normalized_label(row["claim_type"]) not in _QUANTITATIVE_OR_FRAGILE_CLAIM_TYPES:
                continue
            linked = conn.execute(
                "SELECT 1 FROM report_target_evidence WHERE target_id = ? LIMIT 1",
                (row["target_id"],),
            ).fetchone()
            if not linked:
                fragile += 1
        metrics["quantitative_or_fragile_targets_without_structured_evidence"] = fragile
        metrics["report_targets_depending_on_flagged_sources"] = _flagged_report_target_count(conn)

    if _table_exists(conn, "citation_audits"):
        rows = conn.execute("SELECT support_classification, recommended_action FROM citation_audits").fetchall()
        metrics["citations_audited"] = len(rows)
        metrics["citations_weakened_or_rejected"] = sum(
            1 for row in rows
            if (_normalized_label(row["support_classification"]) in _WEAK_SUPPORT_CLASSIFICATIONS
                or _normalized_label(row["recommended_action"]) in _CITATION_WEAKENED_ACTIONS)
        )
        metrics["citations_classified_weak_overstated_or_topically_related_only"] = sum(
            1 for row in rows
            if _normalized_label(row["support_classification"]) in {
                "weak_support",
                "overstated",
                "topically_related_only",
            }
        )

    if _table_exists(conn, "review_issues"):
        metrics["reviewer_issues_with_target_ids"] = conn.execute(
            "SELECT COUNT(*) FROM review_issues WHERE COALESCE(target_id, '') != ''"
        ).fetchone()[0]
        placeholders = ",".join("?" for _ in _CLOSED_REVIEW_ISSUE_STATUSES)
        metrics["reviewer_issues_resolved_before_delivery"] = conn.execute(
            f"SELECT COUNT(*) FROM review_issues WHERE status IN ({placeholders})",
            tuple(_CLOSED_REVIEW_ISSUE_STATUSES),
        ).fetchone()[0]
        metrics["unresolved_issues_before_delivery"] = conn.execute(
            f"SELECT COUNT(*) FROM review_issues WHERE status IS NULL OR status NOT IN ({placeholders})",
            tuple(_CLOSED_REVIEW_ISSUE_STATUSES),
        ).fetchone()[0]
        review_rows = conn.execute(
            """SELECT dimension, status, contradiction_type
               FROM review_issues
               WHERE COALESCE(contradiction_type, '') != ''
                  OR dimension IN ('internal_contradiction', 'limitation', 'missing_context')
                  OR status = 'accepted_as_limitation'"""
        ).fetchall()
        disclosed = 0
        needs_review = 0
        for row in review_rows:
            status = _normalized_label(row["status"])
            if status in {"resolved", "rejected_with_rationale"}:
                continue
            if status == "accepted_as_limitation":
                disclosed += 1
            else:
                needs_review += 1
        metrics["unresolved_contradictions_or_limitations_disclosed"] = disclosed
        metrics["unresolved_contradictions_or_limitations_needing_review"] = needs_review

    return metrics


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
            metrics.update(_evidence_metrics(conn, session_dir))
            metrics.update(_support_artifact_metrics(conn))
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
