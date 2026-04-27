#!/usr/bin/env python3
"""Session state tracker — SQLite-backed search history, source dedup, findings, gaps, and metrics."""

import argparse
import ast
import contextlib
import hashlib
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

CREATE TABLE IF NOT EXISTS evidence_units (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    primary_question_id TEXT,
    question_ids TEXT NOT NULL DEFAULT '[]',
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'supports',
    evidence_strength TEXT,
    provenance_type TEXT NOT NULL,
    provenance_path TEXT,
    line_start INTEGER,
    line_end INTEGER,
    quote TEXT,
    structured_data TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence_units(session_id, source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_question ON evidence_units(session_id, primary_question_id);

CREATE TABLE IF NOT EXISTS finding_evidence (
    session_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary',
    PRIMARY KEY (finding_id, evidence_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS source_flags (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    flag TEXT NOT NULL,
    applies_to_type TEXT NOT NULL DEFAULT 'run',
    applies_to_id TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (source_id) REFERENCES sources(id),
    UNIQUE(session_id, source_id, flag, applies_to_type, applies_to_id)
);

CREATE INDEX IF NOT EXISTS idx_source_flags_source ON source_flags(session_id, source_id);
CREATE INDEX IF NOT EXISTS idx_source_flags_scope ON source_flags(session_id, applies_to_type, applies_to_id);
"""

_ADDITIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_flags (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    flag TEXT NOT NULL,
    applies_to_type TEXT NOT NULL DEFAULT 'run',
    applies_to_id TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (source_id) REFERENCES sources(id),
    UNIQUE(session_id, source_id, flag, applies_to_type, applies_to_id)
);

CREATE INDEX IF NOT EXISTS idx_source_flags_source ON source_flags(session_id, source_id);
CREATE INDEX IF NOT EXISTS idx_source_flags_scope ON source_flags(session_id, applies_to_type, applies_to_id);
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
    ("findings", "question_id", "TEXT"),
    ("gaps", "question_id", "TEXT"),
]

_POLICY_FILENAME = "evidence-policy.yaml"
_POLICY_FIELDS = (
    "source_expectations",
    "freshness_requirement",
    "inference_tolerance",
    "high_stakes_claim_patterns",
    "known_failure_modes",
)
_POLICY_LIST_FIELDS = {"high_stakes_claim_patterns", "known_failure_modes"}

_SOURCE_QUALITY_CANONICAL = (
    "ok",
    "inaccessible",
    "abstract_only",
    "degraded_extraction",
    "metadata_incomplete",
    "title_content_mismatch",
)
_SOURCE_QUALITY_LEGACY_ALIASES = {
    "degraded": "degraded_extraction",
    "empty": "inaccessible",
    "paywall_page": "inaccessible",
    "paywall_stub": "abstract_only",
    "mismatched": "title_content_mismatch",
    "reader_validated": "ok",
}
_SOURCE_QUALITY_ACCEPTED = set(_SOURCE_QUALITY_CANONICAL) | set(_SOURCE_QUALITY_LEGACY_ALIASES)

_SOURCE_CAUTION_FLAGS = (
    "secondary_source",
    "self_interested_source",
    "undated",
    "potentially_stale",
    "low_relevance",
)
_SOURCE_FLAG_SCOPES = ("run", "brief", "finding", "report_target", "citation")
_REPORT_GROUNDING_FILENAME = "report-grounding.json"
_REPORT_GROUNDING_SCHEMA_VERSION = "report-grounding-v1"
_REPORT_GROUNDING_REQUIRED_FIELDS = (
    "target_id",
    "section",
    "paragraph",
    "text_hash",
    "text_snippet",
    "citation_refs",
    "source_ids",
    "finding_ids",
    "evidence_ids",
    "warnings",
)
_REPORT_GROUNDING_OPTIONAL_FIELDS = (
    "grounding_status",
    "not_grounded_reason",
    "support_note",
    "support_level",
    "claim_type",
)
_NON_BODY_SECTIONS = {"references", "further reading"}


def _empty_policy_fields() -> dict[str, str | list[str] | None]:
    return {
        field: [] if field in _POLICY_LIST_FIELDS else None
        for field in _POLICY_FIELDS
    }


def _strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_policy_list(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list | tuple):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (SyntaxError, ValueError):
            pass
        inner = value[1:-1]
        return [_strip_yaml_scalar(item) for item in inner.split(",") if item.strip()]
    return [_strip_yaml_scalar(value)]


def _parse_evidence_policy(text: str) -> tuple[dict[str, str | list[str] | None], list[str], list[str]]:
    """Parse the small run-local evidence policy subset without adding PyYAML."""
    fields = _empty_policy_fields()
    seen: set[str] = set()
    warnings: list[str] = []
    current_list_key: str | None = None

    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        if indent > 0 and current_list_key:
            if stripped.startswith("- "):
                items = fields[current_list_key]
                if isinstance(items, list):
                    items.append(_strip_yaml_scalar(stripped[2:]))
                continue
            warnings.append(f"line {lineno} ignored: expected list item for {current_list_key}")
            continue

        current_list_key = None
        if ":" not in stripped:
            warnings.append(f"line {lineno} ignored: expected key: value")
            continue

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if key not in _POLICY_FIELDS:
            warnings.append(f"line {lineno} ignored: unknown evidence policy field {key}")
            continue

        seen.add(key)
        if key in _POLICY_LIST_FIELDS:
            value = raw_value.strip()
            fields[key] = _parse_policy_list(value)
            if not value:
                current_list_key = key
        else:
            fields[key] = _strip_yaml_scalar(raw_value)

    missing = [field for field in _POLICY_FIELDS if field not in seen]
    return fields, missing, warnings


def _canonical_source_quality(quality: object) -> str:
    if quality is None or quality == "":
        return "unknown"
    if isinstance(quality, int | float):
        return "degraded_extraction" if quality < 0.5 else "ok"
    if not isinstance(quality, str):
        return "unknown"
    normalized = quality.strip()
    return _SOURCE_QUALITY_LEGACY_ALIASES.get(normalized, normalized if normalized in _SOURCE_QUALITY_CANONICAL else "unknown")


def _next_source_flag_id(conn: sqlite3.Connection, session_id: str) -> str:
    row = conn.execute("SELECT COUNT(*) as c FROM source_flags WHERE session_id = ?", (session_id,)).fetchone()
    return f"sflag-{row['c'] + 1:03d}"


def _source_quality_counts(conn: sqlite3.Connection, session_id: str) -> dict:
    raw_counts: dict[str, int] = {}
    access_counts: dict[str, int] = {}
    rows = conn.execute("SELECT quality, COUNT(*) as c FROM sources WHERE session_id = ? GROUP BY quality", (session_id,)).fetchall()
    for row in rows:
        raw_key = row["quality"] if row["quality"] not in (None, "") else "unknown"
        raw_counts[str(raw_key)] = row["c"]
        canonical = _canonical_source_quality(row["quality"])
        access_counts[canonical] = access_counts.get(canonical, 0) + row["c"]

    for key in _SOURCE_QUALITY_CANONICAL:
        access_counts.setdefault(key, 0)

    return {
        "raw_counts": raw_counts,
        "access_quality_counts": access_counts,
        "legacy_aliases": _SOURCE_QUALITY_LEGACY_ALIASES,
        "accepted_values": list(_SOURCE_QUALITY_CANONICAL),
    }


def _source_flag_rows(conn: sqlite3.Connection, session_id: str, limit: int | None = None) -> list[dict]:
    query = (
        "SELECT id, source_id, flag, applies_to_type, applies_to_id, rationale, created_by, created_at "
        "FROM source_flags WHERE session_id = ? ORDER BY source_id, flag, applies_to_type, applies_to_id, id"
    )
    params: list = [session_id]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _source_flag_summary(conn: sqlite3.Connection, session_id: str, include_rows: bool = False) -> dict:
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM source_flags WHERE session_id = ?", (session_id,)).fetchone()["c"]
    except sqlite3.OperationalError:
        return {"total": 0, "by_flag": {}, "by_scope": {}, "by_source": {}, "sources_with_flags": 0}

    by_flag = {
        row["flag"]: row["c"]
        for row in conn.execute(
            "SELECT flag, COUNT(*) as c FROM source_flags WHERE session_id = ? GROUP BY flag ORDER BY c DESC, flag",
            (session_id,),
        ).fetchall()
    }
    by_scope = {
        row["applies_to_type"]: row["c"]
        for row in conn.execute(
            "SELECT applies_to_type, COUNT(*) as c FROM source_flags WHERE session_id = ? GROUP BY applies_to_type ORDER BY c DESC, applies_to_type",
            (session_id,),
        ).fetchall()
    }
    by_source = {
        row["source_id"]: row["c"]
        for row in conn.execute(
            "SELECT source_id, COUNT(*) as c FROM source_flags WHERE session_id = ? GROUP BY source_id ORDER BY c DESC, source_id",
            (session_id,),
        ).fetchall()
    }
    result = {
        "total": total,
        "by_flag": by_flag,
        "by_scope": by_scope,
        "by_source": by_source,
        "sources_with_flags": len(by_source),
    }
    if include_rows:
        result["flags"] = _source_flag_rows(conn, session_id, limit=100)
    return result


def _normalize_grounding_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _grounding_text_hash(text: str) -> str:
    normalized = _normalize_grounding_text(text)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _grounding_snippet(text: str, max_chars: int = 220) -> str:
    normalized = _normalize_grounding_text(text)
    return normalized[:max_chars]


def _extract_citation_refs(text: str) -> list[str]:
    refs = []
    seen = set()
    for match in re.finditer(r"\[\d+\]", text):
        ref = match.group(0)
        if ref not in seen:
            refs.append(ref)
            seen.add(ref)
    return refs


def _resolve_session_file(session_dir: str, path: str | None, default_name: str | None = None) -> str:
    candidate = path or default_name
    if not candidate:
        return session_dir
    if os.path.isabs(candidate):
        return candidate
    session_candidate = os.path.join(session_dir, candidate)
    if os.path.exists(session_candidate):
        return session_candidate
    return os.path.abspath(candidate)


def _parse_report_paragraphs(report_text: str) -> list[dict]:
    paragraphs: list[dict] = []
    section = "Document"
    section_counts: dict[str, int] = {}
    in_fence = False
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        raw = "\n".join(buffer).strip()
        buffer = []
        if not raw:
            return
        paragraph_no = section_counts.get(section, 0) + 1
        section_counts[section] = paragraph_no
        normalized = _normalize_grounding_text(raw)
        paragraphs.append({
            "section": section,
            "paragraph": paragraph_no,
            "text": normalized,
            "text_hash": _grounding_text_hash(normalized),
            "text_snippet": _grounding_snippet(normalized),
            "citation_refs": _extract_citation_refs(normalized),
        })

    for line in report_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            buffer.append(line)
            continue
        if not in_fence:
            heading = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
            if heading:
                flush()
                section = heading.group(1).strip()
                section_counts.setdefault(section, 0)
                continue
            if not stripped:
                flush()
                continue
        buffer.append(line)
    flush()
    return paragraphs


def _body_paragraphs(paragraphs: list[dict]) -> list[dict]:
    return [
        p for p in paragraphs
        if p["section"].strip().lower() not in _NON_BODY_SECTIONS
    ]


def _load_report_grounding_manifest(path: str) -> tuple[dict | None, list[dict]]:
    if not os.path.exists(path):
        return None, [{"code": "manifest_missing", "message": f"Report grounding manifest not found: {path}"}]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return None, [{"code": "manifest_invalid_json", "message": f"Invalid JSON in report grounding manifest: {exc}"}]
    except OSError as exc:
        return None, [{"code": "manifest_unreadable", "message": f"Could not read report grounding manifest: {exc}"}]
    if not isinstance(data, dict):
        return None, [{"code": "manifest_invalid_shape", "message": "Report grounding manifest must be a JSON object"}]
    return data, []


def _load_evidence_policy(session_dir: str) -> dict:
    path = os.path.join(session_dir, _POLICY_FILENAME)
    result = {
        "present": False,
        "path": _POLICY_FILENAME,
        "fields": _empty_policy_fields(),
        "missing_fields": list(_POLICY_FIELDS),
        "warnings": [],
    }
    if not os.path.exists(path):
        return result

    result["present"] = True
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        result["warnings"] = [f"could not read {_POLICY_FILENAME}: {exc}"]
        return result

    fields, missing, warnings = _parse_evidence_policy(text)
    result["fields"] = fields
    result["missing_fields"] = missing
    result["warnings"] = warnings
    return result


def _build_support_context(
    session_dir: str,
    conn: sqlite3.Connection | None = None,
    session_id: str | None = None,
) -> dict:
    policy = _load_evidence_policy(session_dir)
    source_quality = None
    source_flags = None
    if conn is not None and session_id is not None:
        source_quality = _source_quality_counts(conn, session_id)
        source_flags = _source_flag_summary(conn, session_id, include_rows=True)
    grounding_path = os.path.join(session_dir, _REPORT_GROUNDING_FILENAME)
    grounding_present = os.path.exists(grounding_path)
    return {
        "schema_version": "support-context-v1",
        "session_dir": session_dir,
        "available_context": {
            "evidence_policy": policy["present"],
            "source_quality": source_quality is not None,
            "source_caution_flags": bool(source_flags and source_flags["total"] > 0),
            "report_grounding": grounding_present,
            "citation_audit": False,
            "review_issues": False,
        },
        "evidence_policy": policy,
        "source_quality": source_quality,
        "source_caution_flags": source_flags,
        "report_grounding": {
            "present": grounding_present,
            "path": _REPORT_GROUNDING_FILENAME,
            "status": "declared_provenance_not_verified" if grounding_present else "missing",
        },
        "notes": [
            "Evidence policy is optional run-local calibration, not a required workflow phase.",
            "Source caution flags are additive warnings; they do not replace access/extraction quality.",
            "Report grounding is declared provenance until an agent audits citation fit or claim support.",
            "Use this context to guide agent judgment; deterministic tools do not decide semantic support.",
        ],
    }


def _support_context_markdown(context: dict) -> str:
    policy = context["evidence_policy"]
    lines = ["# Support Context", ""]
    if policy["present"]:
        lines.append(f"Evidence policy: present at `{policy['path']}`.")
        fields = policy["fields"]
        for field in _POLICY_FIELDS:
            value = fields.get(field)
            if isinstance(value, list):
                if value:
                    lines.append(f"- `{field}`: " + "; ".join(value))
                else:
                    lines.append(f"- `{field}`: []")
            elif value:
                lines.append(f"- `{field}`: {value}")
            else:
                lines.append(f"- `{field}`: null")
        if policy["missing_fields"]:
            missing = ", ".join(policy["missing_fields"])
            lines.append(f"- Missing fields: {missing}")
        if policy["warnings"]:
            lines.append("- Warnings: " + "; ".join(policy["warnings"]))
    else:
        lines.append(f"Evidence policy: not present. Expected optional path: `{policy['path']}`.")

    source_flags = context.get("source_caution_flags")
    if source_flags and source_flags.get("total", 0) > 0:
        lines.extend(["", f"Source caution flags: {source_flags['total']} total."])
        for flag, count in source_flags.get("by_flag", {}).items():
            lines.append(f"- `{flag}`: {count}")
    else:
        lines.extend(["", "Source caution flags: none recorded."])

    lines.extend([
        "",
        "Use this as advisory calibration only. Absence of a policy must not block search, reading, synthesis, verification, or review.",
    ])
    return "\n".join(lines)


def _migrate_schema(db_path: str) -> None:
    """Run ALTER TABLE migrations in a dedicated writable connection.

    Single source of truth for the migration column list — called once
    before the main connection is returned, regardless of readonly mode.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}", uri=True)
        try:
            conn.executescript(_ADDITIVE_SCHEMA)
            conn.commit()
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
            # Gray zone: require author + year match
            if sim >= 0.85 and authors and _authors_overlap(row["authors"], authors) and year and row["year"] and abs(year - row["year"]) <= 1:
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


from _shared.evidence_helpers import count_evidence_by_question as _count_evidence_by_question


def _compact_linked_evidence_for_handoff(
    findings: list[dict], evidence_rows_by_id: dict[str, dict], cap_bytes: int
) -> tuple[list[dict], set[str], bool, int]:
    """Return a size-bounded evidence slice without dangling finding references."""
    if not evidence_rows_by_id:
        return [], set(), False, 0

    strength_order = {"strong": 0, "moderate": 1, "weak": 2, None: 3}

    def sort_key(ev_id: str) -> tuple[int, str]:
        row = evidence_rows_by_id[ev_id]
        return (strength_order.get(row.get("evidence_strength"), 3), ev_id)

    linked_ids: list[str] = []
    linked_seen: set[str] = set()
    for finding in findings:
        for ev_id in finding.get("evidence_ids", []):
            if ev_id in evidence_rows_by_id and ev_id not in linked_seen:
                linked_ids.append(ev_id)
                linked_seen.add(ev_id)

    if not linked_ids:
        return [], set(), False, 0

    # First pass: keep the strongest linked evidence row for as many findings
    # as possible before filling any remaining budget with extra rows.
    primary_ids: list[str] = []
    primary_seen: set[str] = set()
    for finding in findings:
        candidate_ids = [ev_id for ev_id in finding.get("evidence_ids", []) if ev_id in linked_seen]
        if not candidate_ids:
            continue
        best_id = min(candidate_ids, key=sort_key)
        if best_id not in primary_seen:
            primary_ids.append(best_id)
            primary_seen.add(best_id)

    remaining_ids = [ev_id for ev_id in linked_ids if ev_id not in primary_seen]
    remaining_ids.sort(key=sort_key)
    ordered_ids = primary_ids + remaining_ids

    selected_rows: list[dict] = []
    selected_ids: set[str] = set()
    for ev_id in ordered_ids:
        row = evidence_rows_by_id[ev_id]
        trial_rows = selected_rows + [row]
        encoded = json.dumps(trial_rows).encode("utf-8")
        if len(encoded) > cap_bytes and selected_rows:
            continue
        selected_rows = trial_rows
        selected_ids.add(ev_id)

    truncated = len(selected_rows) < len(linked_ids)
    return selected_rows, selected_ids, truncated, len(linked_ids)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    session_dir = args.session_dir
    os.makedirs(session_dir, exist_ok=True)
    for subdir in ("sources", "sources/metadata", "notes", "evidence"):
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
    log("Session marker written to .deep-research-session (auto-discovery enabled)")

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
    source_flags = _source_flag_rows(conn, sid)

    findings = [dict(r) for r in conn.execute("SELECT * FROM findings WHERE session_id = ? ORDER BY id", (sid,)).fetchall()]
    for f in findings:
        f["sources"] = json.loads(f["sources"]) if f.get("sources") else []

    gaps = [dict(r) for r in conn.execute("SELECT * FROM gaps WHERE session_id = ? ORDER BY id", (sid,)).fetchall()]

    metrics_rows = conn.execute("SELECT * FROM metrics WHERE session_id = ? ORDER BY ticker, metric", (sid,)).fetchall()
    metrics_list = [dict(r) for r in metrics_rows]

    # Evidence unit counts
    evidence_count = conn.execute(
        "SELECT COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
    ).fetchone()["c"]
    evidence_by_question: dict[str, int] = {}
    for r in conn.execute(
        "SELECT primary_question_id, COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active' AND primary_question_id IS NOT NULL GROUP BY primary_question_id", (sid,)
    ).fetchall():
        evidence_by_question[r["primary_question_id"]] = r["c"]

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
        "source_flags": source_flags,
        "findings": findings,
        "gaps": gaps,
        "metrics": metrics_list,
        "stats": {
            "total_searches": len(searches),
            "total_sources": len(sources),
            "sources_by_type": sources_by_type,
            "sources_by_provider": sources_by_provider,
            "source_caution_flags_count": len(source_flags),
            "evidence_units_count": evidence_count,
            "evidence_units_by_question": evidence_by_question,
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

    raw_questions = data.get("questions", [])
    # Normalize questions to objects with IDs: [{"id": "Q1", "text": "..."}]
    # Accepts plain strings (auto-assigned Q1, Q2, ...) or objects with id/text.
    questions = []
    for i, q in enumerate(raw_questions):
        if isinstance(q, str):
            questions.append({"id": f"Q{i + 1}", "text": q})
        elif isinstance(q, dict) and "text" in q:
            qid = q.get("id", f"Q{i + 1}")
            questions.append({"id": qid, "text": q["text"]})
        else:
            questions.append({"id": f"Q{i + 1}", "text": str(q)})

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
    # Accept explicit status from caller (e.g. "irrelevant" for zero-relevance
    # sources at ingestion) — otherwise default to "pending".
    status = data.get("status", "pending")
    conn.execute(
        """INSERT INTO sources (id, session_id, title, authors, year, abstract, doi, url,
           pdf_url, venue, citation_count, type, provider, content_file, pdf_file,
           relevance_score, status, added_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, session_id, title, json.dumps(authors), year,
         data.get("abstract"), doi, url, data.get("pdf_url"),
         data.get("venue"), data.get("citation_count"),
         data.get("type", "academic"), data.get("provider", "unknown"),
         data.get("content_file"), data.get("pdf_file"),
         data.get("relevance_score"), status, _now())
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
                with open(filepath, encoding="utf-8") as _f:
                    existing = json.loads(_f.read())
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


def _normalize_question(conn: sqlite3.Connection, session_id: str, question: str,
                        question_id: str | None = None) -> tuple[str, str | None]:
    """Normalize question text by matching against brief questions.

    Returns (question_text, question_id). Resolution priority:
    1. question_id arg → look up by ID in brief questions
    2. question starts with Q\\d+ → extract ID, match to brief
    3. Token-overlap matching (backward compat, threshold 0.9)
    """
    if not question and not question_id:
        return question, question_id
    try:
        row = conn.execute(
            "SELECT questions FROM brief WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return question, question_id
        brief_questions = json.loads(row["questions"])
        if not isinstance(brief_questions, list):
            return question, question_id

        # Build lookup maps for both object-style and plain-string briefs
        id_to_text: dict[str, str] = {}
        text_list: list[str] = []
        for bq in brief_questions:
            if isinstance(bq, dict):
                qid = bq.get("id", "")
                qtxt = bq.get("text", "")
                if qid:
                    id_to_text[qid.upper()] = qtxt
                text_list.append(qtxt)
            elif isinstance(bq, str):
                text_list.append(bq)

        # Priority 1: explicit question_id
        if question_id:
            matched = id_to_text.get(question_id.upper())
            if matched:
                return matched, question_id
            # ID didn't match — fall through to text matching

        # Priority 2: question starts with Q\d+ pattern
        if question:
            m = re.match(r"^Q(\d+)\b", question)
            if m:
                qid_candidate = f"Q{m.group(1)}"
                matched = id_to_text.get(qid_candidate.upper())
                if matched:
                    return matched, qid_candidate

        # Priority 3: token-overlap matching (backward compat)
        if question:
            best_match = question
            best_score = 0.0
            best_id: str | None = question_id
            for bq in brief_questions:
                if isinstance(bq, dict):
                    bq_text = bq.get("text", "")
                    bq_id = bq.get("id")
                elif isinstance(bq, str):
                    bq_text = bq
                    bq_id = None
                else:
                    continue
                score = _token_overlap(question, bq_text)
                if score > best_score:
                    best_score = score
                    best_match = bq_text
                    best_id = bq_id
            if best_score > 0.9 and best_match != question:
                log(f"Normalized question text (overlap={best_score:.2f}): {question!r} → {best_match!r}")
                return best_match, best_id
    except Exception:
        pass
    return question, question_id


def _normalize_source_id(sid: str) -> str:
    """Normalize source IDs to zero-padded 3-digit format (src-24 -> src-024).

    IDs are generated by _next_id with 3-digit padding, but agents may type them
    without padding. Normalizing on input prevents inconsistent joins in analysis.
    """
    m = re.match(r'^(src-)(\d+)$', sid)
    if m:
        return f"{m.group(1)}{int(m.group(2)):03d}"
    return sid


def cmd_log_finding(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    finding_id = _next_id(conn, "findings", "finding", sid)

    qid = getattr(args, "question_id", None)
    question, question_id = _normalize_question(conn, sid, args.question, question_id=qid)
    source_ids = [_normalize_source_id(s.strip()) for s in args.sources.split(",")] if args.sources else []
    conn.execute(
        "INSERT INTO findings (id, session_id, text, sources, question, question_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (finding_id, sid, args.text, json.dumps(source_ids), question, question_id, _now())
    )

    # Link evidence units if provided
    evidence_ids = getattr(args, "evidence_ids", None)
    linked_evidence = []
    if evidence_ids:
        for ev_id in [e.strip() for e in evidence_ids.split(",") if e.strip()]:
            row = conn.execute(
                "SELECT id FROM evidence_units WHERE id = ? AND session_id = ?",
                (ev_id, sid)
            ).fetchone()
            if row:
                try:
                    conn.execute(
                        "INSERT INTO finding_evidence (session_id, finding_id, evidence_id, role) VALUES (?, ?, ?, 'primary')",
                        (sid, finding_id, ev_id)
                    )
                    linked_evidence.append(ev_id)
                except sqlite3.IntegrityError:
                    pass

    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    result = {"id": finding_id, "text": args.text}
    if linked_evidence:
        result["evidence_ids"] = linked_evidence
    success_response(result)


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
    keeper_for: dict[str, str] = {}  # absorbed_id -> keeper_id

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
            keeper_for[absorbed["id"]] = keeper["id"]
            # Track cross-question relevance
            if absorbed["question"] and absorbed["question"] != keeper["question"]:
                merge_map.setdefault(keeper["id"], []).append(absorbed["question"])

    # Delete merged findings and update keeper texts with also_relevant_to
    if merged_ids:
        # Propagate evidence links from absorbed findings to their keepers
        for absorbed_id, keeper_id in keeper_for.items():
            rows = conn.execute(
                "SELECT evidence_id FROM finding_evidence WHERE finding_id = ? AND session_id = ?",
                (absorbed_id, sid)
            ).fetchall()
            for row in rows:
                try:
                    conn.execute(
                        "INSERT INTO finding_evidence (session_id, finding_id, evidence_id, role) VALUES (?, ?, ?, 'primary')",
                        (sid, keeper_id, row["evidence_id"])
                    )
                except sqlite3.IntegrityError:
                    pass  # already linked to keeper
            conn.execute(
                "DELETE FROM finding_evidence WHERE finding_id = ? AND session_id = ?",
                (absorbed_id, sid)
            )

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

    qid = getattr(args, "question_id", None)
    question, question_id = _normalize_question(conn, sid, args.question, question_id=qid)
    conn.execute(
        "INSERT INTO gaps (id, session_id, text, question, question_id, status, timestamp) VALUES (?, ?, ?, ?, ?, 'open', ?)",
        (gap_id, sid, args.text, question, question_id, _now())
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
                "rationale": "Keyword search using terms from gap text and question"
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

    return success_response({"gaps": plans, "total_open": len(plans)})


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
            "SELECT provider, COUNT(*) as count FROM sources WHERE session_id = ? AND status != 'irrelevant' GROUP BY provider ORDER BY count DESC",
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
    clauses = ["session_id = ?", "status != 'irrelevant'"]
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

    # Sync updated fields to on-disk metadata JSON so filesystem matches state.db
    metadata_fields = {"title", "authors", "year", "abstract", "doi", "url", "pdf_url", "venue", "citation_count", "type"}
    updated_metadata = {k: v for k, v in data.items() if k in metadata_fields and v is not None}
    if updated_metadata:
        metadata_dir = os.path.join(args.session_dir, "sources", "metadata")
        if os.path.isdir(metadata_dir):
            from _shared.metadata import read_source_metadata, write_source_metadata
            meta = read_source_metadata(metadata_dir, args.id)
            if meta:
                meta.update(updated_metadata)
                write_source_metadata(metadata_dir, args.id, meta)

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

    # Searches — break out by type so recovery vs discovery is visible
    search_count = conn.execute("SELECT COUNT(*) as c FROM searches WHERE session_id = ?", (sid,)).fetchone()["c"]
    search_type_rows = conn.execute(
        "SELECT search_type, COUNT(*) as c FROM searches WHERE session_id = ? GROUP BY search_type", (sid,)
    ).fetchall()
    searches_by_type: dict[str, int] = {r["search_type"]: r["c"] for r in search_type_rows}
    searches_discovery = search_count - searches_by_type.get("recovery", 0)
    searches_recovery = searches_by_type.get("recovery", 0)

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
        f_entry: dict = {
            "id": r["id"], "text": r["text"],
            "sources": json.loads(r["sources"]) if r["sources"] else [],
            "question": r["question"],
        }
        # Include question_id if column exists and has a value
        try:
            qid = r["question_id"]
            if qid:
                f_entry["question_id"] = qid
        except (IndexError, KeyError):
            pass
        # Attach linked evidence IDs
        ev_rows = conn.execute(
            "SELECT evidence_id FROM finding_evidence WHERE finding_id = ? AND session_id = ?",
            (r["id"], sid)
        ).fetchall()
        if ev_rows:
            f_entry["evidence_ids"] = [er["evidence_id"] for er in ev_rows]
        findings_list.append(f_entry)

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

    # Evidence units
    evidence_count = conn.execute(
        "SELECT COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
    ).fetchone()["c"]
    active_evidence_rows = conn.execute(
        "SELECT claim_type, primary_question_id, question_ids, source_id "
        "FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
    ).fetchall()

    evidence_by_type: dict[str, int] = {}
    for r in conn.execute(
        "SELECT claim_type, COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active' GROUP BY claim_type", (sid,)
    ).fetchall():
        evidence_by_type[r["claim_type"]] = r["c"]
    evidence_by_question = _count_evidence_by_question(active_evidence_rows)
    # Findings without linked evidence
    findings_without_evidence = []
    if evidence_count > 0:
        for f in findings_list:
            fid = f["id"]
            link = conn.execute(
                "SELECT 1 FROM finding_evidence WHERE finding_id = ? AND session_id = ? LIMIT 1",
                (fid, sid)
            ).fetchone()
            if not link:
                findings_without_evidence.append(fid)

    # Fetch compact evidence rows for handoff (while conn is still open)
    evidence_rows_by_id: dict[str, dict] = {}
    if evidence_count > 0:
        for r in conn.execute(
            """SELECT id, source_id, claim_text, claim_type, relation,
                      evidence_strength, primary_question_id
               FROM evidence_units
               WHERE session_id = ? AND status = 'active' ORDER BY id""", (sid,)
        ).fetchall():
            row_dict = dict(r)
            evidence_rows_by_id[row_dict["id"]] = row_dict

    source_quality_summary = _source_quality_counts(conn, sid)
    source_caution_summary = _source_flag_summary(conn, sid, include_rows=True)
    support_context = _build_support_context(args.session_dir, conn, sid)
    conn.close()

    full_result = {
        "brief": brief_data,
        "search_count": search_count,
        "searches_discovery": searches_discovery,
        "searches_recovery": searches_recovery,
        "searches_by_type": searches_by_type,
        "source_count": source_count,
        "sources_by_type": sources_by_type,
        "sources_by_provider": sources_by_provider,
        "sources": source_list,
        "findings": findings_list,
        "gaps": gaps_list,
        "metrics": metrics_list,
        "evidence_units_count": evidence_count,
        "evidence_units_by_type": evidence_by_type,
        "evidence_units_by_question": evidence_by_question,
        "findings_without_evidence": findings_without_evidence,
    }

    # --write-handoff: write full summary to file, return only path + counts
    if getattr(args, "write_handoff", False):
        # 1. Filter sources to only those cited in findings/gaps — the writer
        #    reads individual metadata files per source, so the full 500+ source
        #    catalogue is unused bulk (~120 KB).
        cited_ids: set[str] = set()
        for f in findings_list:
            cited_ids.update(f.get("sources", []))
        for g in gaps_list:
            cited_ids.update(g.get("sources", []))
        full_result["sources"] = [s for s in source_list if s["id"] in cited_ids]

        # 2. Strip redundant question text from findings — each finding repeats
        #    the full question string (250-500 chars × 50-80 findings ≈ 28 KB).
        #    The writer can cross-reference brief.questions by question_id.
        for f in full_result["findings"]:
            if f.get("question_id"):
                f.pop("question", None)

        # 3. Build source quality report with counts only — the writer needs
        #    totals for the Methodology section, not per-source ID lists.
        notes_dir = os.path.join(args.session_dir, "notes")
        quality_counts: dict[str, int] = {
            "on_topic_with_evidence": 0,
            "abstract_only_relevant": 0,
            "degraded_unread": 0,
            "mismatched": 0,
            "reader_validated": 0,
        }
        for r in source_rows:
            sid_val = r["id"]
            q = r["quality"] or ""
            has_note = os.path.exists(os.path.join(notes_dir, f"{sid_val}.md"))
            if q == "mismatched":
                quality_counts["mismatched"] += 1
            elif q == "reader_validated":
                quality_counts["reader_validated"] += 1
            elif q == "abstract_only":
                quality_counts["abstract_only_relevant"] += 1
            elif q == "degraded" and not has_note:
                quality_counts["degraded_unread"] += 1
            elif has_note:
                quality_counts["on_topic_with_evidence"] += 1

        full_result["source_quality_report"] = quality_counts
        full_result["source_quality_summary"] = source_quality_summary
        full_result["source_caution_summary"] = source_caution_summary
        full_result["support_context"] = support_context

        # 4. Include linked evidence units when available, with size guardrail.
        #    Keep the exported findings/evidence arrays internally consistent.
        if evidence_rows_by_id:
            EVIDENCE_CAP_BYTES = 15 * 1024
            selected_rows, selected_ids, truncated, total_count = _compact_linked_evidence_for_handoff(
                full_result["findings"], evidence_rows_by_id, EVIDENCE_CAP_BYTES
            )

            for f in full_result["findings"]:
                kept_ids = [ev_id for ev_id in f.get("evidence_ids", []) if ev_id in selected_ids]
                if kept_ids:
                    f["evidence_ids"] = kept_ids
                else:
                    f.pop("evidence_ids", None)

            if evidence_count > 0:
                full_result["findings_without_evidence"] = [
                    f["id"] for f in full_result["findings"] if not f.get("evidence_ids")
                ]

            if selected_rows:
                full_result["evidence_units"] = selected_rows
            full_result["evidence_truncated"] = truncated
            full_result["evidence_total_count"] = total_count

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
        # Build findings-per-question count map, keyed by "Q1: full text" when IDs available
        findings_by_question: dict[str, int] = {}
        for f in findings_list:
            qid = f.get("question_id")
            q = f.get("question") or "unassigned"
            key = f"{qid}: {q}" if qid and q != "unassigned" else q
            findings_by_question[key] = findings_by_question.get(key, 0) + 1

        success_response({
            "brief": {"questions": brief_data["questions"]} if brief_data else None,
            "search_count": search_count,
            "source_count": source_count,
            "sources_by_type": sources_by_type,
            "sources_by_provider": sources_by_provider,
            "findings_count": len(findings_list),
            "findings_by_question": findings_by_question,
            "gaps": gaps_list,
            "evidence_units_count": evidence_count,
            "evidence_units_by_type": evidence_by_type,
            "evidence_units_by_question": evidence_by_question,
        })
        return

    success_response(full_result)


def cmd_support_context(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    context = _build_support_context(args.session_dir, conn, sid)
    conn.close()
    if args.format == "markdown":
        success_response({"format": "markdown", "content": _support_context_markdown(context)})
        return
    success_response(context)


# ---------------------------------------------------------------------------
# Evidence commands
# ---------------------------------------------------------------------------

def _ingest_evidence_manifest(conn: sqlite3.Connection, sid: str, manifest: dict) -> list[str]:
    """Insert evidence units from a single source manifest. Returns list of IDs."""
    source_id = manifest.get("source_id", "")
    if not source_id:
        error_response(["Manifest missing source_id"])

    # Validate source exists
    row = conn.execute(
        "SELECT id FROM sources WHERE id = ? AND session_id = ?",
        (source_id, sid)
    ).fetchone()
    if not row:
        error_response([f"Source {source_id} not found in session"])

    units = manifest.get("units", [])
    if not units:
        return []

    # Get current evidence count for ID generation (may collide under
    # concurrent writes, so retry on IntegrityError with incremented suffix)
    count = conn.execute(
        "SELECT COUNT(*) as c FROM evidence_units WHERE session_id = ?", (sid,)
    ).fetchone()["c"]

    ids = []
    now = _now()
    next_seq = count + 1
    for unit in units:
        while True:
            ev_id = f"ev-{next_seq:04d}"
            try:
                conn.execute(
                    """INSERT INTO evidence_units
                       (id, session_id, source_id, primary_question_id, question_ids,
                        claim_text, claim_type, relation, evidence_strength,
                        provenance_type, provenance_path, line_start, line_end, quote,
                        structured_data, tags, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ev_id, sid, source_id,
                     unit.get("primary_question_id"),
                     json.dumps(unit.get("question_ids", [])),
                     unit["claim_text"],
                     unit["claim_type"],
                     unit.get("relation", "supports"),
                     unit.get("evidence_strength"),
                     unit["provenance_type"],
                     unit.get("provenance_path"),
                     unit.get("line_start"),
                     unit.get("line_end"),
                     unit.get("quote"),
                     json.dumps(unit.get("structured_data", {})),
                     json.dumps(unit.get("tags", [])),
                     "active", now)
                )
                break
            except sqlite3.IntegrityError:
                next_seq += 1
        ids.append(ev_id)
        next_seq += 1
    return ids


def cmd_add_evidence(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_dict(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)

    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    ids = _ingest_evidence_manifest(conn, sid, data)
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"evidence_ids": ids, "count": len(ids)})


def cmd_add_evidence_batch(args):
    json_path, is_temp = _resolve_json_input(args)
    try:
        data = _load_json_list(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)

    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    all_ids = []
    for manifest in data:
        ids = _ingest_evidence_manifest(conn, sid, manifest)
        all_ids.extend(ids)
    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"evidence_ids": all_ids, "count": len(all_ids)})


def cmd_evidence(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    query = "SELECT * FROM evidence_units WHERE session_id = ?"
    params: list = [sid]

    if getattr(args, "source_id", None):
        query += " AND source_id = ?"
        params.append(args.source_id)
    if getattr(args, "claim_type", None):
        query += " AND claim_type = ?"
        params.append(args.claim_type)

    question_id = getattr(args, "question_id", None)
    if question_id:
        query += " AND (primary_question_id = ? OR question_ids LIKE ?)"
        params.extend([question_id, f'%"{question_id}"%'])

    status = getattr(args, "status", "active")
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    units = []
    for r in rows:
        units.append({
            "id": r["id"],
            "source_id": r["source_id"],
            "primary_question_id": r["primary_question_id"],
            "question_ids": json.loads(r["question_ids"]),
            "claim_text": r["claim_text"],
            "claim_type": r["claim_type"],
            "relation": r["relation"],
            "evidence_strength": r["evidence_strength"],
            "provenance_type": r["provenance_type"],
            "provenance_path": r["provenance_path"],
            "line_start": r["line_start"],
            "line_end": r["line_end"],
            "quote": r["quote"],
            "structured_data": json.loads(r["structured_data"]),
            "tags": json.loads(r["tags"]),
            "status": r["status"],
            "created_at": r["created_at"],
        })
    success_response({"units": units, "count": len(units)})


def cmd_evidence_summary(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    total = conn.execute(
        "SELECT COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
    ).fetchone()["c"]

    by_type = {}
    for r in conn.execute(
        "SELECT claim_type, COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active' GROUP BY claim_type", (sid,)
    ).fetchall():
        by_type[r["claim_type"]] = r["c"]

    by_question = _count_evidence_by_question(conn.execute(
        "SELECT primary_question_id, question_ids FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
    ).fetchall())

    with_spans = conn.execute(
        "SELECT COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active' AND line_start IS NOT NULL AND line_end IS NOT NULL", (sid,)
    ).fetchone()["c"]

    by_source = {}
    for r in conn.execute(
        "SELECT source_id, COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active' GROUP BY source_id", (sid,)
    ).fetchall():
        by_source[r["source_id"]] = r["c"]

    conn.close()

    # Compute total size of evidence JSON artifacts on disk
    evidence_dir = os.path.join(args.session_dir, "evidence")
    total_json_size = 0
    if os.path.isdir(evidence_dir):
        for f in os.scandir(evidence_dir):
            if f.name.endswith(".json") and f.is_file():
                total_json_size += f.stat().st_size

    success_response({
        "total": total,
        "by_claim_type": by_type,
        "by_question": by_question,
        "with_provenance_spans": with_spans,
        "by_source": by_source,
        "total_json_size_bytes": total_json_size,
    })


def cmd_link_finding_evidence(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    finding_id = args.finding_id
    evidence_ids = [e.strip() for e in args.evidence_ids.split(",")]
    role = getattr(args, "role", "primary")

    # Validate finding exists
    row = conn.execute(
        "SELECT id FROM findings WHERE id = ? AND session_id = ?",
        (finding_id, sid)
    ).fetchone()
    if not row:
        conn.close()
        error_response([f"Finding {finding_id} not found"])

    # Validate evidence units exist and insert links
    linked = []
    for ev_id in evidence_ids:
        row = conn.execute(
            "SELECT id FROM evidence_units WHERE id = ? AND session_id = ?",
            (ev_id, sid)
        ).fetchone()
        if not row:
            conn.close()
            error_response([f"Evidence unit {ev_id} not found"])
        try:
            conn.execute(
                "INSERT INTO finding_evidence (session_id, finding_id, evidence_id, role) VALUES (?, ?, ?, ?)",
                (sid, finding_id, ev_id, role)
            )
            linked.append(ev_id)
        except sqlite3.IntegrityError:
            pass  # already linked

    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({"finding_id": finding_id, "linked_evidence": linked, "count": len(linked)})


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

    if args.quality not in _SOURCE_QUALITY_ACCEPTED:
        conn.close()
        allowed = sorted(_SOURCE_QUALITY_ACCEPTED)
        error_response([f"Invalid quality: {args.quality}. Allowed: {', '.join(allowed)}"])

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
    success_response({"id": args.id, "quality": args.quality, "access_quality": _canonical_source_quality(args.quality)})


def cmd_set_source_flag(args):
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    if args.flag not in _SOURCE_CAUTION_FLAGS:
        conn.close()
        error_response([f"Invalid source flag: {args.flag}. Allowed: {', '.join(_SOURCE_CAUTION_FLAGS)}"])
    if args.applies_to not in _SOURCE_FLAG_SCOPES:
        conn.close()
        error_response([f"Invalid applies_to: {args.applies_to}. Allowed: {', '.join(_SOURCE_FLAG_SCOPES)}"])
    applies_to_id = "" if args.applies_to == "run" else (args.applies_to_id or "")
    if args.applies_to != "run" and not applies_to_id:
        conn.close()
        error_response([f"--applies-to-id is required when --applies-to is {args.applies_to}"])

    row = conn.execute(
        "SELECT id FROM sources WHERE id = ? AND session_id = ?",
        (args.source_id, sid),
    ).fetchone()
    if not row:
        conn.close()
        error_response([f"Source {args.source_id} not found"])

    existing = conn.execute(
        """SELECT id FROM source_flags
           WHERE session_id = ? AND source_id = ? AND flag = ? AND applies_to_type = ? AND applies_to_id = ?""",
        (sid, args.source_id, args.flag, args.applies_to, applies_to_id),
    ).fetchone()

    if existing:
        flag_id = existing["id"]
        conn.execute(
            """UPDATE source_flags
               SET rationale = ?, created_by = ?, created_at = ?
               WHERE id = ? AND session_id = ?""",
            (args.rationale, args.created_by, _now(), flag_id, sid),
        )
        created = False
    else:
        flag_id = _next_source_flag_id(conn, sid)
        conn.execute(
            """INSERT INTO source_flags
               (id, session_id, source_id, flag, applies_to_type, applies_to_id, rationale, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (flag_id, sid, args.source_id, args.flag, args.applies_to, applies_to_id, args.rationale, args.created_by, _now()),
        )
        created = True

    conn.commit()
    _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()
    success_response({
        "id": flag_id,
        "source_id": args.source_id,
        "flag": args.flag,
        "applies_to": args.applies_to,
        "applies_to_id": applies_to_id,
        "created": created,
    })


def cmd_source_flags(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    clauses = ["session_id = ?"]
    params: list = [sid]
    if args.source_id:
        clauses.append("source_id = ?")
        params.append(args.source_id)
    if args.flag:
        clauses.append("flag = ?")
        params.append(args.flag)
    if args.applies_to:
        clauses.append("applies_to_type = ?")
        params.append(args.applies_to)
    if args.applies_to_id is not None:
        clauses.append("applies_to_id = ?")
        params.append(args.applies_to_id)

    rows = conn.execute(
        "SELECT id, source_id, flag, applies_to_type, applies_to_id, rationale, created_by, created_at "
        f"FROM source_flags WHERE {' AND '.join(clauses)} ORDER BY source_id, flag, applies_to_type, applies_to_id, id",
        params,
    ).fetchall()
    conn.close()
    success_response([dict(row) for row in rows])


def cmd_source_flag_summary(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    result = _source_flag_summary(conn, sid, include_rows=getattr(args, "include_rows", False))
    conn.close()
    success_response(result)


def cmd_source_quality_summary(args):
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    result = _source_quality_counts(conn, sid)
    result["source_caution_flags"] = _source_flag_summary(conn, sid, include_rows=getattr(args, "include_rows", False))
    conn.close()
    success_response(result)


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
           AND status != 'irrelevant'
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
                "wall_clock_estimate_per_batch_seconds": batch_size * 30,
                "total_batches_estimated_seconds": (batch_size * 30) * max_batches,
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

        # Internal subprocess timeout: scale with batch size, but cap at 90s
        # to stay within the default 120s Bash tool timeout (leaving margin for
        # state queries and JSON serialization around the subprocess call).
        timeout = timeout_override if timeout_override is not None else min(90, max(45, len(batch) * 15))
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
        "wall_clock_estimate_seconds": len(source_attempts) * 30,
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
        st = s["search_type"] if s["search_type"] else "manual"
        searches_by_type[st] = searches_by_type.get(st, 0) + 1

    # Load gaps
    gaps = [dict(r) for r in conn.execute(
        "SELECT * FROM gaps WHERE session_id = ? AND status = 'open' ORDER BY id", (sid,)
    ).fetchall()]

    # Evidence layer queries (while conn is open)
    audit_evidence_total = 0
    audit_evidence_warnings: list[str] = []
    audit_findings_without_evidence: list[str] = []
    audit_evidence_by_question: dict[str, int] = {}
    try:
        audit_evidence_total = conn.execute(
            "SELECT COUNT(*) as c FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
        ).fetchone()["c"]
        if audit_evidence_total > 0:
            audit_evidence_rows = conn.execute(
                "SELECT primary_question_id, question_ids FROM evidence_units WHERE session_id = ? AND status = 'active'", (sid,)
            ).fetchall()
            for f in findings:
                link = conn.execute(
                    "SELECT 1 FROM finding_evidence WHERE finding_id = ? AND session_id = ? LIMIT 1",
                    (f["id"], sid)
                ).fetchone()
                if not link:
                    audit_findings_without_evidence.append(f["id"])
            if audit_findings_without_evidence:
                audit_evidence_warnings.append(f"{len(audit_findings_without_evidence)} finding(s) have no linked evidence units")
            audit_evidence_by_question = _count_evidence_by_question(audit_evidence_rows)
    except Exception:
        pass  # table may not exist in old sessions

    source_quality_summary = _source_quality_counts(conn, sid)
    source_caution_summary = _source_flag_summary(conn, sid, include_rows=True)
    conn.close()

    # Check on-disk files
    notes_dir = os.path.join(args.session_dir, "notes")
    sources_dir = os.path.join(args.session_dir, "sources")

    downloaded = []
    with_notes = []
    degraded_unread = []
    reader_validated = []
    mismatched = []
    inaccessible = []
    metadata_incomplete = []
    no_content = []
    abstract_only = []
    irrelevant = []

    for s in sources:
        sid_val = s["id"]

        # Separate irrelevant sources (zero keyword overlap at ingestion) —
        # they're preserved for provenance but excluded from working counts.
        if s.get("status") == "irrelevant":
            irrelevant.append(sid_val)
            continue

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
        access_quality = _canonical_source_quality(quality)
        if quality == "reader_validated":
            reader_validated.append(sid_val)
        elif access_quality == "degraded_extraction":
            degraded_unread.append(sid_val)
        elif access_quality == "title_content_mismatch":
            mismatched.append(sid_val)
        elif access_quality == "abstract_only":
            abstract_only.append(sid_val)
        elif access_quality == "inaccessible":
            inaccessible.append(sid_val)
        elif access_quality == "metadata_incomplete":
            metadata_incomplete.append(sid_val)

    # Build question text list and ID-to-text map from brief
    question_texts = []
    question_id_map: dict[str, str] = {}  # "Q1" -> full text
    for q in questions:
        if isinstance(q, dict):
            qtxt = q.get("text", str(q))
            qid = q.get("id", "")
            question_texts.append(qtxt)
            if qid:
                question_id_map[qid.upper()] = qtxt
        elif isinstance(q, str):
            question_texts.append(q)

    # Match a finding's question field to brief questions.
    # Priority order:
    #   0. question_id column match (highest priority — exact ID lookup)
    #   1. Exact text match
    #   2. "Q<N>" pattern in question text matches the Nth question
    #   3. Finding question is a prefix/substring of a brief question
    #   4. Brief question starts with the finding's question text
    _qn_pattern = re.compile(r"^Q(\d+)\b")

    def _match_question(finding_q: str, finding_qid: str | None = None) -> str:
        """Return the matching brief question text, or the original string."""
        # Priority 0: question_id column
        if finding_qid:
            matched = question_id_map.get(finding_qid.upper())
            if matched:
                return matched
        if finding_q in question_texts:
            return finding_q
        fq_lower = finding_q.lower().strip()
        # Check Q<N> pattern (e.g. "Q1", "Q3: What mechanisms...")
        m = _qn_pattern.match(finding_q)
        if m:
            qid_candidate = f"Q{m.group(1)}"
            matched = question_id_map.get(qid_candidate.upper())
            if matched:
                return matched
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
        # Try to get question_id from the finding
        f_qid = f.get("question_id")
        q = _match_question(f.get("question") or "unassigned", finding_qid=f_qid)
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

    # Detect orphaned sources: status='downloaded' but no actual content on disk.
    # This catches both null content_file with no file on disk, and content_file
    # pointing to a file that was deleted or never written.
    orphaned_sources = []
    for s in sources:
        if s.get("status") != "downloaded":
            continue
        sid_val = s["id"]
        has_file = False
        if s.get("content_file"):
            has_file = os.path.exists(os.path.join(args.session_dir, s["content_file"]))
        if not has_file:
            for ext in (".md", ".pdf"):
                if os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")):
                    has_file = True
                    break
        if not has_file:
            orphaned_sources.append(sid_val)

    # Build warnings
    warnings = []
    for sid_val in degraded_unread:
        warnings.append(f"{sid_val} has degraded extraction quality — do not claim deep reading without reader validation")
    for sid_val in mismatched:
        warnings.append(f"{sid_val} has title/content mismatch — downloaded content may be the wrong source")
    for sid_val in inaccessible:
        warnings.append(f"{sid_val} is marked inaccessible — do not cite as deeply read")
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
    if orphaned_sources:
        warnings.append(
            f"{len(orphaned_sources)} orphaned source(s) have status='downloaded' but no content on disk: "
            f"{', '.join(orphaned_sources[:10])}. These are invisible to readers and synthesis."
        )
    if len(gaps) > 0:
        warnings.append(f"{len(gaps)} open research gaps remain")

    # Human-readable summary to stderr
    log("=== Pre-Report Audit ===")
    log(f"Sources tracked:     {len(sources)} ({len(irrelevant)} irrelevant, excluded from counts below)")
    log(f"Sources downloaded:  {total_downloaded}  ({', '.join(downloaded[:10])}{'...' if len(downloaded) > 10 else ''})")
    log(f"Sources with notes:  {deep_reads}  ({', '.join(with_notes[:10])}{'...' if len(with_notes) > 10 else ''})")
    log(f"Degraded (unread):   {len(degraded_unread)}  ({', '.join(degraded_unread)})" if degraded_unread else "Degraded (unread):   0")
    log(f"Reader validated:    {len(reader_validated)}  ({', '.join(reader_validated)})" if reader_validated else "Reader validated:    0")
    log(f"Mismatched content:  {len(mismatched)}  ({', '.join(mismatched)})" if mismatched else "Mismatched content:  0")
    log(f"Inaccessible:        {len(inaccessible)}  ({', '.join(inaccessible)})" if inaccessible else "Inaccessible:        0")
    log(f"Abstract only:       {len(abstract_only)}  ({', '.join(abstract_only)})" if abstract_only else "Abstract only:       0")
    log(f"Source cautions:     {source_caution_summary['total']}")
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
        "sources_irrelevant": len(irrelevant),
        "sources_downloaded": total_downloaded,
        "sources_with_notes": deep_reads,
        "degraded_unread": degraded_unread,
        "reader_validated": reader_validated,
        "mismatched_content": mismatched,
        "inaccessible": inaccessible,
        "metadata_incomplete": metadata_incomplete,
        "source_quality_summary": source_quality_summary,
        "source_caution_summary": source_caution_summary,
        "findings_count": len(findings),
        "findings_by_question": {k: len(v) for k, v in findings_by_question.items()},
        "open_gaps": len(gaps),
        "gaps": [{"id": g["id"], "text": g["text"], "question": g.get("question"), "status": g["status"]} for g in gaps],
        "sparse_questions": sparse_questions,
        "downloaded_no_content_file": downloaded_no_content_file,
        "orphaned_sources": orphaned_sources,
        "methodology": {
            "deep_reads": deep_reads,
            "abstract_only": total_abstract_only,
            "web_sources": web_sources,
            "searches": {
                "total": len(all_searches),
                "discovery": len(all_searches) - searches_by_type.get("recovery", 0),
                "recovery": searches_by_type.get("recovery", 0),
                **searches_by_type,
            },
        },
        "warnings": warnings,
    }

    # Evidence layer (data pre-computed while conn was open)
    if audit_evidence_total > 0:
        audit_result["evidence_units_total"] = audit_evidence_total
        if audit_findings_without_evidence:
            audit_result["findings_without_evidence"] = audit_findings_without_evidence
            warnings.extend(audit_evidence_warnings)
        # Questions with findings but no evidence
        questions_no_evidence = []
        for q_key in findings_by_question:
            qid = q_key.split(":")[0].strip() if ":" in q_key else None
            if qid and audit_evidence_by_question.get(qid, 0) == 0:
                questions_no_evidence.append(q_key)
        if questions_no_evidence:
            audit_result["questions_with_findings_but_no_evidence"] = questions_no_evidence

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
            f"SELECT {_src_cols} FROM sources WHERE session_id = ? AND title LIKE ? AND status != 'irrelevant' ORDER BY id",
            (session_id, f"%{title_filter}%")
        ).fetchall()]
    else:
        sources = [dict(r) for r in conn.execute(
            f"SELECT {_src_cols} FROM sources WHERE session_id = ? AND status != 'irrelevant' ORDER BY id", (session_id,)
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
        elif isinstance(quality, int | float) and quality < 0.5:
            quality_flag = "low_score"

        # Stat content file for content_chars (enables content-depth-aware dispatch)
        content_chars = None
        if has_content and s.get("content_file"):
            content_path = os.path.join(session_dir, s["content_file"])
            with contextlib.suppress(OSError):
                content_chars = os.path.getsize(content_path)

        scored.append({
            "id": s["id"],
            "title": s.get("title", ""),
            "citation_count": cite_count,
            "keyword_hits": keyword_hits,
            "score": round(score, 2),
            "has_content": has_content,
            "content_chars": content_chars,
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
            unresolvable.append({"gap_id": gap["id"], "reason": "No new high/medium sources with content match gap terms"})

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

    max_attempts = getattr(args, "max_attempts", 5) or 5
    recovered = []
    still_failed = []
    total_attempts = 0
    # Web search providers for recovery, in preference order.
    # Each provider checks its own env var (e.g. TAVILY_API_KEY) at search time;
    # we detect availability here so we don't waste budget on unconfigured providers.
    _WEB_PROVIDER_KEYS = [
        ("tavily", "TAVILY_API_KEY"),
        ("perplexity", "PERPLEXITY_API_KEY"),
        ("linkup", "LINKUP_API_KEY"),
        ("exa", "EXA_API_KEY"),
        ("gensee", "GENSEE_API_KEY"),
    ]
    web_providers = [name for name, env in _WEB_PROVIDER_KEYS if os.environ.get(env)]
    if not web_providers:
        log("No web search provider API keys found — web recovery channel disabled", level="warn")

    # Build channel_stats for all channels we might use
    channel_stats = {"doi": {"attempts": 0, "successes": 0},
                     "core": {"attempts": 0, "successes": 0}}
    for wp in web_providers:
        channel_stats[wp] = {"attempts": 0, "successes": 0}
    skipped_channels = []
    budget_exhausted = False

    def _channel_available(ch: str) -> bool:
        """Return False if a channel should be skipped (0 successes after 5+ attempts)."""
        s = channel_stats.get(ch)
        if not s:
            return False
        return not (s["attempts"] >= 5 and s["successes"] == 0)

    def _try_web_search(provider: str, sid: str, paper_title: str) -> bool:
        """Try recovering a source via a web search provider. Returns True on success."""
        if not paper_title or not _channel_available(provider):
            return False
        try:
            channel_stats[provider]["attempts"] += 1
            cmd = [
                sys.executable, search_script,
                "--provider", provider,
                "--query", f'"{paper_title[:150]}" pdf',
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
                                "--source-id", sid,
                                "--to-md",
                                "--session-dir", args.session_dir,
                            ]
                            dl_proc = subprocess.run(dl_cmd, capture_output=True, timeout=60)
                            if dl_proc.returncode == 0 and any(os.path.exists(os.path.join(sources_dir, f"{sid}{ext}")) for ext in (".md", ".pdf")):
                                log(f"Recovered {sid} via {provider} PDF search")
                                channel_stats[provider]["successes"] += 1
                                return True
                except (json.JSONDecodeError, TypeError):
                    pass
        except (subprocess.TimeoutExpired, Exception) as e:
            log(f"{provider} recovery failed for {sid}: {e}", level="debug")

        # Check if this provider should be skipped going forward
        if not _channel_available(provider) and provider not in skipped_channels:
            skipped_channels.append(provider)
            log(f"{provider} channel skipped: 0 successes after 5 attempts")
        return False

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

        # Strategy 1: Web search providers (try each configured provider in order)
        success = False
        for wp in web_providers:
            if total_attempts >= max_attempts:
                break
            total_attempts += 1
            if _try_web_search(wp, sid_val, title):
                recovered.append(sid_val)
                success = True
                break

        if success:
            continue
        if total_attempts >= max_attempts:
            still_failed.append(sid_val)
            continue

        # Strategy 2: DOI landing page as web source
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
                if dl_proc.returncode == 0 and any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
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

        if success:
            continue
        if total_attempts >= max_attempts:
            still_failed.append(sid_val)
            continue

        # Strategy 3: CORE keyword search (last resort — unreliable for title matching)
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
                        for r in (results if isinstance(results, list) else []):
                            pdf_url = r.get("pdf_url") or r.get("download_url")
                            if pdf_url:
                                dl_cmd = [
                                    sys.executable, download_script,
                                    "--pdf-url", pdf_url,
                                    "--source-id", sid_val,
                                    "--to-md",
                                    "--session-dir", args.session_dir,
                                ]
                                dl_proc = subprocess.run(dl_cmd, capture_output=True, timeout=60)
                                if dl_proc.returncode == 0 and any(os.path.exists(os.path.join(sources_dir, f"{sid_val}{ext}")) for ext in (".md", ".pdf")):
                                    log(f"Recovered {sid_val} via CORE")
                                    recovered.append(sid_val)
                                    channel_stats["core"]["successes"] += 1
                                    success = True
                                    break
                    except (json.JSONDecodeError, TypeError):
                        pass
            except (subprocess.TimeoutExpired, Exception) as e:
                log(f"CORE recovery failed for {sid_val}: {e}", level="debug")

            if not _channel_available("core") and "core" not in skipped_channels:
                skipped_channels.append("core")
                log("CORE channel skipped: 0 successes after 5 attempts")

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
    except json.JSONDecodeError as e:
        error_response([f"Invalid JSON in {path}: {e}"])


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
        # Write to temp file so _load_json_raw works uniformly
        session_dir = getattr(args, "session_dir", None) or "."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=session_dir, delete=False) as tf:
            tf_name = tf.name
            json.dump(data, tf)
        return tf_name, True
    error_response(["No JSON input specified. Use --from-json FILE or --from-stdin"])
    return None


def _cleanup_json_input(path: str, is_temp: bool) -> None:
    """Remove temp file created by _resolve_json_input if needed."""
    if is_temp:
        with contextlib.suppress(OSError):
            os.unlink(path)


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
# reconcile — post-batch sync of on-disk files to state.db status
# ---------------------------------------------------------------------------

def cmd_reconcile(args):
    """Scan sources/ on disk, cross-reference with state.db, update status.

    When parallel download batches complete, later batches may write files
    after earlier batches' sync has already run. This leaves files on disk
    with status still 'pending' in state.db. reconcile fixes that gap by:
    1. Linking content_file for any source with on-disk .md but no DB record
    2. Promoting status to 'downloaded' for any source with content on disk
       but status not yet 'downloaded' (or 'reader_validated')

    Safe to run multiple times — idempotent.
    """
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    sources_dir = os.path.join(args.session_dir, "sources")

    if not os.path.isdir(sources_dir):
        success_response({"linked": 0, "promoted": 0,
                          "message": "No sources/ directory found"})
        conn.close()
        return

    # Build map of source_id -> on-disk files
    disk_md = set()
    disk_pdf = set()
    for fname in os.listdir(sources_dir):
        name, ext = os.path.splitext(fname)
        if ext == ".md":
            disk_md.add(name)
        elif ext == ".pdf":
            disk_pdf.add(name)

    # Get all sources for this session
    rows = conn.execute(
        "SELECT id, content_file, pdf_file, status FROM sources WHERE session_id = ?",
        (sid,)
    ).fetchall()

    linked = 0
    promoted = 0

    for row in rows:
        src_id = row["id"]
        current_cf = row["content_file"]
        current_pf = row["pdf_file"]
        current_status = row["status"]

        updates = {}

        # Link content_file if file exists on disk but not recorded
        if src_id in disk_md and not current_cf:
            updates["content_file"] = f"sources/{src_id}.md"
            linked += 1
            log(f"Linked {src_id} -> sources/{src_id}.md")

        # Link pdf_file if file exists on disk but not recorded
        if src_id in disk_pdf and not current_pf:
            updates["pdf_file"] = f"sources/{src_id}.pdf"

        # Promote status if source has content on disk but isn't downloaded
        has_content = (current_cf or src_id in disk_md)
        already_done = current_status in ("downloaded", "reader_validated")
        if has_content and not already_done:
            updates["status"] = "downloaded"
            promoted += 1
            log(f"Promoted {src_id} status -> downloaded")

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE sources SET {set_clause} WHERE id = ? AND session_id = ?",
                (*updates.values(), src_id, sid)
            )

    conn.commit()

    if linked > 0 or promoted > 0:
        _regenerate_snapshot(args.session_dir, conn, sid)

    conn.close()

    success_response({
        "linked": linked,
        "promoted": promoted,
        "total_on_disk_md": len(disk_md),
        "total_on_disk_pdf": len(disk_pdf),
        "total_sources": len(rows),
    })


# ---------------------------------------------------------------------------
# convert-pdfs
# ---------------------------------------------------------------------------

def cmd_convert_pdfs(args):
    """Batch-convert unconverted PDFs to markdown and rescue PDF-in-markdown files.

    Two modes:
    1. Unconverted PDFs: .pdf files in sources/ with no corresponding .md → convert
    2. PDF-in-markdown: .md files starting with %PDF magic bytes → rename to .pdf,
       convert, update content_file in state.db
    """
    from _shared.pdf_utils import pdf_to_markdown, validate_pdf

    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)
    sources_dir = os.path.join(args.session_dir, "sources")

    if not os.path.isdir(sources_dir):
        success_response({
            "converted": 0, "rescued_from_md": 0, "failed": 0,
            "details": [], "message": "No sources/ directory found",
        })
        return

    details = []
    converted = 0
    rescued = 0
    failed = 0

    # --- Pass 1: Detect .md files containing raw PDF bytes ---
    for fname in sorted(os.listdir(sources_dir)):
        if not fname.endswith(".md"):
            continue
        md_path = os.path.join(sources_dir, fname)
        try:
            with open(md_path, "rb") as f:
                head = f.read(4)
        except OSError:
            continue
        if head != b"%PDF":
            continue

        source_id = fname[:-3]  # strip .md
        pdf_path = os.path.join(sources_dir, f"{source_id}.pdf")
        log(f"Rescuing PDF-in-markdown: {fname} → {source_id}.pdf")

        # Rename .md to .pdf
        os.rename(md_path, pdf_path)

        if not validate_pdf(pdf_path):
            details.append({"source_id": source_id, "action": "rescue", "success": False,
                            "error": "Renamed file is not a valid PDF"})
            failed += 1
            continue

        # Convert
        result = pdf_to_markdown(pdf_path, md_path)
        if result["success"]:
            # Update content_file in DB to point to .md
            conn.execute(
                "UPDATE sources SET content_file = ? WHERE id = ? AND session_id = ?",
                (f"sources/{source_id}.md", source_id, sid),
            )
            rescued += 1
            details.append({"source_id": source_id, "action": "rescue", "success": True,
                            "converter": result["converter"], "quality": result["quality"]})
        else:
            failed += 1
            details.append({"source_id": source_id, "action": "rescue", "success": False,
                            "error": "All converters failed"})

    # --- Pass 2: Convert .pdf files with no corresponding .md ---
    for fname in sorted(os.listdir(sources_dir)):
        if not fname.endswith(".pdf"):
            continue
        source_id = fname[:-4]  # strip .pdf
        md_path = os.path.join(sources_dir, f"{source_id}.md")
        if os.path.exists(md_path):
            continue  # already has markdown

        pdf_path = os.path.join(sources_dir, fname)
        if not validate_pdf(pdf_path):
            details.append({"source_id": source_id, "action": "convert", "success": False,
                            "error": "Invalid PDF"})
            failed += 1
            continue

        log(f"Converting unconverted PDF: {fname}")
        result = pdf_to_markdown(pdf_path, md_path)
        if result["success"]:
            # Update content_file in DB to point to .md
            conn.execute(
                "UPDATE sources SET content_file = ? WHERE id = ? AND session_id = ?",
                (f"sources/{source_id}.md", source_id, sid),
            )
            converted += 1
            details.append({"source_id": source_id, "action": "convert", "success": True,
                            "converter": result["converter"], "quality": result["quality"]})
        else:
            failed += 1
            details.append({"source_id": source_id, "action": "convert", "success": False,
                            "error": "All converters failed"})

    conn.commit()

    if converted > 0 or rescued > 0:
        _regenerate_snapshot(args.session_dir, conn, sid)

    conn.close()

    success_response({
        "converted": converted,
        "rescued_from_md": rescued,
        "failed": failed,
        "details": details,
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

    result: dict[str, int | list[str]] = {
        "enriched": enriched,
        "attempted": attempted,
        "total_missing": len(rows),
    }
    if errors:
        result["errors"] = errors[:5]  # Cap error list
    success_response(result)


# ---------------------------------------------------------------------------
# validate-edits — post-revision validation
# ---------------------------------------------------------------------------

def cmd_validate_edits(args):
    """Check whether reviser edits actually landed in the report.

    For each resolved edit in the manifest, checks old_text_snippet and
    new_text_snippet against the report text to determine confirmed/failed/inconclusive.
    """
    manifest_path = args.manifest
    report_path = args.report

    # Load manifest
    if not os.path.exists(manifest_path):
        error_response([f"Manifest not found: {manifest_path}"])
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        error_response([f"Invalid JSON in manifest: {e}"])

    # Load report
    if not os.path.exists(report_path):
        error_response([f"Report not found: {report_path}"])
    with open(report_path) as f:
        report_text = f.read()

    # Filter to the requested pass if specified
    pass_type = getattr(args, "pass_type", None)

    # Extract resolved edits from manifest
    entries = manifest if isinstance(manifest, list) else manifest.get("edits", manifest.get("entries", []))
    if not isinstance(entries, list):
        error_response(["Manifest must be a JSON array or object with 'edits'/'entries' array"])

    confirmed = []
    failed = []
    inconclusive = []
    warnings = []

    for entry in entries:
        status = entry.get("status", "")
        if status != "resolved":
            continue

        issue_id = entry.get("issue_id", "unknown")

        # Filter by pass type if specified
        if pass_type:
            entry_pass = entry.get("pass", entry.get("pass_type", ""))
            if entry_pass and entry_pass != pass_type:
                continue

        old_snip = entry.get("old_text_snippet", "")
        new_snip = entry.get("new_text_snippet", "")

        if not old_snip and not new_snip:
            inconclusive.append({"issue_id": issue_id, "reason": "no snippets in manifest entry"})
            continue

        old_present = old_snip and old_snip in report_text
        new_present = new_snip and new_snip in report_text

        if not old_present and new_present:
            confirmed.append(issue_id)
        elif old_present and not new_present:
            failed.append({"issue_id": issue_id, "reason": "old text still present, new text absent"})
        elif not old_present and not new_present:
            inconclusive.append({"issue_id": issue_id, "reason": "both snippets absent — context may have changed"})
        else:
            # Both present — likely edit landed but old text appears elsewhere too
            confirmed.append(issue_id)
            warnings.append({"issue_id": issue_id, "reason": "both old and new text present — edit likely landed but old text exists elsewhere"})

    result = {
        "confirmed": confirmed,
        "failed": failed,
        "inconclusive": inconclusive,
        "summary": {
            "total_checked": len(confirmed) + len(failed) + len(inconclusive),
            "confirmed": len(confirmed),
            "failed": len(failed),
            "inconclusive": len(inconclusive),
        },
    }
    if warnings:
        result["warnings"] = warnings
    if pass_type:
        result["pass"] = pass_type

        success_response(result)


# ---------------------------------------------------------------------------
# report-grounding — paragraph hashes and manifest validation
# ---------------------------------------------------------------------------

def cmd_report_paragraphs(args):
    report_path = _resolve_session_file(args.session_dir, args.report, None)
    if not os.path.exists(report_path):
        success_response({
            "status": "missing_report",
            "report_path": report_path,
            "paragraphs": [],
            "issues": [{"code": "report_missing", "message": f"Report not found: {report_path}"}],
        })
        return
    with open(report_path, encoding="utf-8") as f:
        report_text = f.read()
    paragraphs = _parse_report_paragraphs(report_text)
    body = _body_paragraphs(paragraphs)
    success_response({
        "schema_version": "report-paragraphs-v1",
        "report_path": os.path.relpath(report_path),
        "paragraph_count": len(paragraphs),
        "body_paragraph_count": len(body),
        "paragraphs": paragraphs,
        "hash_normalization": "Collapse all whitespace to single spaces, trim ends, SHA-256 UTF-8, prefix with sha256:",
    })


def cmd_validate_report_grounding(args):
    manifest_path = _resolve_session_file(args.session_dir, args.manifest, _REPORT_GROUNDING_FILENAME)
    manifest, manifest_issues = _load_report_grounding_manifest(manifest_path)
    if manifest is None:
        success_response({
            "schema_version": "report-grounding-validation-v1",
            "manifest_path": manifest_path,
            "manifest_status": "missing_or_invalid",
            "valid": False,
            "issues": manifest_issues,
            "summary": {"targets": 0, "valid_targets": 0, "stale_targets": 0, "orphaned_targets": 0, "ungrounded_paragraphs": 0},
        })
        return

    report_value = args.report or manifest.get("report_path") or "draft.md"
    report_path = _resolve_session_file(args.session_dir, report_value, None)
    issues: list[dict] = []
    target_results: list[dict] = []

    if manifest.get("schema_version") not in (None, _REPORT_GROUNDING_SCHEMA_VERSION):
        issues.append({
            "code": "schema_version_unknown",
            "message": f"Unknown report grounding schema_version: {manifest.get('schema_version')}",
        })

    if not os.path.exists(report_path):
        issues.append({"code": "report_missing", "message": f"Report path does not exist: {report_value}"})
        success_response({
            "schema_version": "report-grounding-validation-v1",
            "manifest_path": os.path.relpath(manifest_path),
            "manifest_status": "loaded",
            "report_path": report_value,
            "valid": False,
            "issues": issues,
            "targets": [],
            "summary": {"targets": len(manifest.get("targets", [])) if isinstance(manifest.get("targets"), list) else 0,
                        "valid_targets": 0, "stale_targets": 0, "orphaned_targets": 0, "ungrounded_paragraphs": 0},
        })
        return

    with open(report_path, encoding="utf-8") as f:
        report_text = f.read()
    paragraphs = _parse_report_paragraphs(report_text)
    body_paragraphs = _body_paragraphs(paragraphs)
    by_locator = {(p["section"], p["paragraph"]): p for p in paragraphs}
    by_hash: dict[str, list[dict]] = {}
    for p in paragraphs:
        by_hash.setdefault(p["text_hash"], []).append(p)

    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)
    source_ids = {row["id"] for row in conn.execute("SELECT id FROM sources WHERE session_id = ?", (sid,)).fetchall()}
    finding_ids = {row["id"] for row in conn.execute("SELECT id FROM findings WHERE session_id = ?", (sid,)).fetchall()}
    evidence_ids = {row["id"] for row in conn.execute("SELECT id FROM evidence_units WHERE session_id = ?", (sid,)).fetchall()}
    conn.close()

    targets = manifest.get("targets", [])
    if not isinstance(targets, list):
        issues.append({"code": "targets_invalid", "message": "Manifest field 'targets' must be an array"})
        targets = []

    grounded_keys = set()
    valid_targets = 0
    stale_targets = 0
    orphaned_targets = 0

    for index, target in enumerate(targets):
        target_id = target.get("target_id") if isinstance(target, dict) else None
        target_ref = target_id or f"target[{index}]"
        target_issues: list[dict] = []
        status = "valid"
        matched = None

        if not isinstance(target, dict):
            target_results.append({"target_id": target_ref, "status": "invalid", "issues": [{"code": "target_invalid", "message": "Target must be an object"}]})
            continue

        for field in _REPORT_GROUNDING_REQUIRED_FIELDS:
            if field not in target:
                target_issues.append({"code": "missing_required_field", "field": field})

        locator = (target.get("section"), target.get("paragraph"))
        if isinstance(locator[0], str) and isinstance(locator[1], int):
            matched = by_locator.get(locator)

        expected_hash = target.get("text_hash")
        if matched and expected_hash == matched["text_hash"]:
            grounded_keys.add((matched["section"], matched["paragraph"]))
        elif expected_hash in by_hash:
            relocated = by_hash[expected_hash][0]
            target_issues.append({
                "code": "stale_locator",
                "message": "Target hash exists in report but section/paragraph locator changed",
                "current_section": relocated["section"],
                "current_paragraph": relocated["paragraph"],
            })
            status = "stale_locator"
            matched = relocated
            grounded_keys.add((relocated["section"], relocated["paragraph"]))
        elif matched:
            target_issues.append({
                "code": "stale_hash",
                "message": "Target locator exists but text_hash no longer matches current paragraph text",
                "current_text_hash": matched["text_hash"],
            })
            status = "stale_hash"
            grounded_keys.add((matched["section"], matched["paragraph"]))
        else:
            snippet = _normalize_grounding_text(str(target.get("text_snippet", "")))
            if snippet:
                for p in paragraphs:
                    if snippet and snippet in p["text"]:
                        matched = p
                        target_issues.append({
                            "code": "stale_hash",
                            "message": "Target reconnected by snippet but text_hash/locator did not match",
                            "current_section": p["section"],
                            "current_paragraph": p["paragraph"],
                            "current_text_hash": p["text_hash"],
                        })
                        status = "stale_hash"
                        grounded_keys.add((p["section"], p["paragraph"]))
                        break
            if matched is None:
                target_issues.append({"code": "orphaned_target", "message": "Target could not be matched by locator, hash, or snippet"})
                status = "orphaned"

        text_for_checks = matched["text"] if matched else ""
        citation_refs = target.get("citation_refs", [])
        if not isinstance(citation_refs, list):
            target_issues.append({"code": "field_type", "field": "citation_refs", "message": "citation_refs must be an array"})
            citation_refs = []
        for ref in citation_refs:
            if ref not in text_for_checks:
                target_issues.append({"code": "citation_ref_missing", "citation_ref": ref, "message": "Listed citation_ref does not occur in target text"})

        for field, existing_ids in (("source_ids", source_ids), ("finding_ids", finding_ids), ("evidence_ids", evidence_ids)):
            values = target.get(field, [])
            if not isinstance(values, list):
                target_issues.append({"code": "field_type", "field": field, "message": f"{field} must be an array"})
                continue
            for value in values:
                if value not in existing_ids:
                    target_issues.append({"code": "missing_referenced_id", "field": field, "id": value})

        finding_values = target.get("finding_ids", [])
        evidence_values = target.get("evidence_ids", [])
        if (isinstance(finding_values, list)
                and isinstance(evidence_values, list)
                and not finding_values
                and not evidence_values
                and not target.get("not_grounded_reason")):
            target_issues.append({
                "code": "missing_declared_grounding",
                "message": "Target has no finding_ids, evidence_ids, or not_grounded_reason",
            })

        warnings_value = target.get("warnings", [])
        if "warnings" in target and not isinstance(warnings_value, list):
            target_issues.append({"code": "field_type", "field": "warnings", "message": "warnings must be an array"})

        if status == "valid" and target_issues:
            status = "invalid"
        if status == "valid":
            valid_targets += 1
        elif status.startswith("stale"):
            stale_targets += 1
        elif status == "orphaned":
            orphaned_targets += 1

        target_results.append({
            "target_id": target_ref,
            "status": status,
            "section": target.get("section"),
            "paragraph": target.get("paragraph"),
            "matched_section": matched["section"] if matched else None,
            "matched_paragraph": matched["paragraph"] if matched else None,
            "issues": target_issues,
        })

    ungrounded = []
    for p in body_paragraphs:
        key = (p["section"], p["paragraph"])
        if key not in grounded_keys:
            ungrounded.append({
                "section": p["section"],
                "paragraph": p["paragraph"],
                "text_hash": p["text_hash"],
                "text_snippet": p["text_snippet"],
                "citation_refs": p["citation_refs"],
            })

    if ungrounded:
        issues.append({
            "code": "ungrounded_paragraphs",
            "message": f"{len(ungrounded)} body paragraph(s) have no grounding target",
        })

    target_issue_count = sum(len(t["issues"]) for t in target_results)
    valid = not issues and target_issue_count == 0
    success_response({
        "schema_version": "report-grounding-validation-v1",
        "manifest_path": os.path.relpath(manifest_path),
        "manifest_status": "loaded",
        "report_path": report_value,
        "valid": valid,
        "issues": issues,
        "targets": target_results,
        "ungrounded_paragraphs": ungrounded,
        "summary": {
            "targets": len(target_results),
            "valid_targets": valid_targets,
            "stale_targets": stale_targets,
            "orphaned_targets": orphaned_targets,
            "target_issue_count": target_issue_count,
            "ungrounded_paragraphs": len(ungrounded),
            "report_body_paragraphs": len(body_paragraphs),
        },
    })


# ---------------------------------------------------------------------------
# validate-content — post-download content validation
# ---------------------------------------------------------------------------

def cmd_validate_content(args):
    """Check downloaded content files against source metadata.

    Heuristics: title-word overlap, venue/domain match, domain-term presence,
    stub detection. Auto-updates quality flags in state.db for flagged sources.
    """
    conn = _connect(args.session_dir)
    sid = _get_session_id(conn)

    top_n = args.top
    domain_terms = [t.strip().lower() for t in args.domain_terms.split(",") if t.strip()] if args.domain_terms else []
    expected_domains = [d.strip().lower() for d in args.expected_domains.split(",") if d.strip()] if args.expected_domains else []

    # Get top sources by triage score (relevance_score), with content files
    rows = conn.execute(
        """SELECT id, title, venue, content_file, quality
           FROM sources
           WHERE session_id = ? AND content_file IS NOT NULL AND content_file != ''
             AND (quality IS NULL OR quality NOT IN ('mismatched'))
           ORDER BY COALESCE(relevance_score, 0) DESC, citation_count DESC
           LIMIT ?""",
        (sid, top_n),
    ).fetchall()

    checked = 0
    valid = 0
    mismatched = []
    degraded = []
    details = []
    updated_ids = []

    for row in rows:
        src_id = row["id"]
        title = row["title"] or ""
        venue = row["venue"] or ""
        content_file = row["content_file"]

        # Resolve content file path
        content_path = content_file
        if not os.path.isabs(content_path):
            content_path = os.path.join(args.session_dir, content_path)

        if not os.path.exists(content_path):
            continue

        checked += 1

        try:
            with open(content_path) as f:
                content_head = f.read(2000)  # first ~2000 chars
        except Exception:
            continue

        content_lower = content_head.lower()
        issues = []

        # 1. Stub detection: content < 500 chars
        if len(content_head.strip()) < 500:
            issues.append("stub content (< 500 chars)")
            degraded.append(src_id)
            if row["quality"] != "degraded":
                conn.execute("UPDATE sources SET quality = 'degraded' WHERE id = ? AND session_id = ?", (src_id, sid))
                updated_ids.append(src_id)
            details.append({"id": src_id, "reason": "stub content (< 500 chars)", "title_overlap": 0.0})
            continue

        # 2. Title-word overlap
        title_words = set(re.findall(r'\w{4,}', title.lower()))  # words with 4+ chars
        stop_words = {"this", "that", "with", "from", "their", "about", "which", "these", "those",
                       "been", "have", "will", "would", "could", "should", "other", "some", "were"}
        title_words -= stop_words
        if title_words:
            matches = sum(1 for w in title_words if w in content_lower)
            title_overlap = matches / len(title_words) if title_words else 0.0
        else:
            title_overlap = 1.0  # can't check, assume ok

        if title_overlap < 0.3:
            issues.append(f"low title-word overlap ({title_overlap:.2f})")

        # 3. Venue/domain check
        if venue and expected_domains:
            venue_lower = venue.lower()
            venue_matches_domain = any(d in venue_lower for d in expected_domains)
            if not venue_matches_domain:
                # Check for obviously unrelated venues
                issues.append(f"venue '{venue}' outside expected domains")

        # 4. Domain-term presence
        if domain_terms:
            term_hits = sum(1 for t in domain_terms if t in content_lower)
            if term_hits == 0:
                issues.append("zero domain terms in first 2000 chars")

        # Classify
        if issues:
            mismatched.append(src_id)
            if row["quality"] not in ("mismatched", "degraded"):
                conn.execute("UPDATE sources SET quality = 'mismatched' WHERE id = ? AND session_id = ?", (src_id, sid))
                updated_ids.append(src_id)
            details.append({"id": src_id, "reason": "; ".join(issues), "title_overlap": round(title_overlap, 2)})
        else:
            valid += 1

    conn.commit()
    if updated_ids:
        _regenerate_snapshot(args.session_dir, conn, sid)
    conn.close()

    success_response({
        "checked": checked,
        "valid": valid,
        "mismatched": len(mismatched),
        "degraded": len(degraded),
        "mismatched_ids": mismatched,
        "degraded_ids": degraded,
        "details": details,
        "quality_updated": updated_ids,
    })


# ---------------------------------------------------------------------------
# dedup-issues — mechanical dedup for revision orchestrator
# ---------------------------------------------------------------------------

def _normalize_location(loc: str) -> str:
    """Extract normalized section+paragraph from free-text location string.

    Examples:
        "Section 3, paragraph 2" -> "s3p2"
        "Section 5, paragraph 1" -> "s5p1"
        "Introduction, paragraph 3" -> "s0p3"
        "Results" -> "results"
    """
    loc_lower = loc.lower().strip()

    # Extract section number
    sec_match = re.search(r'section\s+(\d+)', loc_lower)
    sec_num = sec_match.group(1) if sec_match else None

    # Extract paragraph number
    para_match = re.search(r'paragraph\s+(\d+)', loc_lower)
    para_num = para_match.group(1) if para_match else None

    if sec_num and para_num:
        return f"s{sec_num}p{para_num}"
    if sec_num:
        return f"s{sec_num}"

    # Named sections: intro, conclusion, etc.
    for name in ("introduction", "conclusion", "abstract", "methods", "results", "discussion", "recommendations"):
        if name in loc_lower:
            if para_num:
                return f"{name}p{para_num}"
            return name

    # Fallback: normalize whitespace
    return re.sub(r'\s+', ' ', loc_lower)


def _fix_specificity_score(fix_text: str) -> int:
    """Score how specific/actionable a suggested_fix is.

    Higher score = more specific. A fix saying "change X to Y" scores higher
    than "verify and correct".
    """
    if not fix_text:
        return 0
    lower = fix_text.lower()
    # Vague fixes
    vague_patterns = ["verify", "check", "review", "consider", "ensure", "clarify"]
    if any(lower.startswith(p) for p in vague_patterns):
        return 1
    # Specific fixes contain quotes, specific text, or "change/replace"
    if '"' in fix_text or "'" in fix_text or "→" in fix_text:
        return 3
    if any(w in lower for w in ("change", "replace", "remove", "delete", "add", "insert", "rewrite")):
        return 2
    return 1


_SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def cmd_dedup_issues(args):
    """Group issues by location, identify candidate duplicates, flag co-located non-duplicates.

    Takes issues as JSON (array of issue objects with issue_id, severity, location,
    description, suggested_fix fields). Returns candidate duplicates with merge
    suggestions and co-located groups for the orchestrator to confirm.
    """
    json_path, is_temp = _resolve_json_input(args)
    try:
        issues = _load_json_list(json_path)
    finally:
        _cleanup_json_input(json_path, is_temp)

    if not issues:
        success_response({
            "candidate_duplicates": [],
            "co_located_groups": [],
            "passthrough_issues": [],
            "summary": {"input_count": 0, "candidate_duplicates": 0, "co_located_groups": 0},
        })
        return

    # Step 1: Group by normalized location
    groups: dict[str, list[dict]] = {}
    for issue in issues:
        loc = issue.get("location", "")
        norm = _normalize_location(loc)
        groups.setdefault(norm, []).append(issue)

    candidate_duplicates = []
    co_located_groups = []
    passthrough_ids = []

    for norm_loc, group in groups.items():
        if len(group) == 1:
            passthrough_ids.append(group[0].get("issue_id", "unknown"))
            continue

        # Step 2: Within each group, identify candidate duplicate pairs
        # Two issues are candidates when they share location AND have high description overlap
        matched = set()
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a = group[i]
                b = group[j]
                a_id = a.get("issue_id", "unknown")
                b_id = b.get("issue_id", "unknown")

                if a_id in matched or b_id in matched:
                    continue

                # Text similarity between descriptions
                desc_sim = _title_similarity(
                    a.get("description", ""),
                    b.get("description", ""),
                )

                if desc_sim < 0.4:
                    # Low overlap — likely different problems at same location
                    continue

                # Step 3: Build merge suggestion
                a_fix = a.get("suggested_fix", "")
                b_fix = b.get("suggested_fix", "")
                a_spec = _fix_specificity_score(a_fix)
                b_spec = _fix_specificity_score(b_fix)

                if b_spec > a_spec:
                    keep, drop = b, a
                else:
                    keep, drop = a, b

                keep_id = keep.get("issue_id", "unknown")
                drop_id = drop.get("issue_id", "unknown")

                # Elevate severity
                sev_a = _SEVERITY_ORDER.get(a.get("severity", "medium"), 2)
                sev_b = _SEVERITY_ORDER.get(b.get("severity", "medium"), 2)
                merged_severity = a.get("severity", "medium") if sev_a >= sev_b else b.get("severity", "medium")

                candidate_duplicates.append({
                    "group_location": a.get("location", norm_loc),
                    "issues": [a_id, b_id],
                    "overlap_signal": f"description similarity {desc_sim:.2f} at same location",
                    "suggested_merge": {
                        "keep_id": keep_id,
                        "drop_id": drop_id,
                        "reason": f"{keep_id} has more specific suggested_fix" if keep != drop else "equal specificity, keeping first",
                        "merged_severity": merged_severity,
                        "flagged_by": [a_id, b_id],
                    },
                })
                matched.add(a_id)
                matched.add(b_id)

        # Remaining unmatched issues in this group
        unmatched = [iss for iss in group if iss.get("issue_id", "unknown") not in matched]
        for iss in unmatched:
            passthrough_ids.append(iss.get("issue_id", "unknown"))

        # Step 4: Flag co-located non-duplicates
        if len(unmatched) >= 2:
            co_located_groups.append({
                "location": group[0].get("location", norm_loc),
                "issue_ids": [iss.get("issue_id", "unknown") for iss in unmatched],
                "reason": "different problems at same paragraph — recommend atomic edit",
            })

    success_response({
        "candidate_duplicates": candidate_duplicates,
        "co_located_groups": co_located_groups,
        "passthrough_issues": passthrough_ids,
        "summary": {
            "input_count": len(issues),
            "candidate_duplicates": len(candidate_duplicates),
            "co_located_groups": len(co_located_groups),
        },
    })


# ---------------------------------------------------------------------------
# dedup-references — reference deduplication for synthesis writer
# ---------------------------------------------------------------------------

def _first_author(authors_json: str) -> str:
    """Extract and normalize the first author name from a JSON authors array."""
    try:
        authors = json.loads(authors_json) if isinstance(authors_json, str) else authors_json
    except (json.JSONDecodeError, TypeError):
        return ""
    if not authors or not isinstance(authors, list):
        return ""
    first = authors[0] if authors[0] else ""
    return first.lower().strip()


def cmd_dedup_references(args):
    """Identify duplicate sources among a set of cited source IDs.

    Groups by DOI (exact match), then by title + first author (fuzzy match).
    Returns duplicate groups for the writer to merge before assigning reference numbers.
    """
    conn = _connect(args.session_dir, readonly=True)
    sid = _get_session_id(conn)

    source_ids = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not source_ids:
        conn.close()
        error_response(["No source IDs provided"])

    # Fetch metadata for all requested sources
    placeholders = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"SELECT id, title, authors, doi FROM sources WHERE session_id = ? AND id IN ({placeholders})",
        [sid, *source_ids],
    ).fetchall()
    conn.close()

    sources = [dict(r) for r in rows]

    # Track which IDs have been grouped
    grouped = set()

    # Tier 1: Group by DOI (exact match)
    doi_groups: dict[str, list[str]] = {}
    for s in sources:
        doi = s.get("doi")
        if doi:
            doi_groups.setdefault(doi, []).append(s["id"])

    doi_duplicates = []
    for doi, ids in doi_groups.items():
        if len(ids) >= 2:
            doi_duplicates.append({"doi": doi, "source_ids": ids})
            grouped.update(ids)

    # Tier 2: Fuzzy match on title + first author (for ungrouped sources)
    ungrouped = [s for s in sources if s["id"] not in grouped]
    fuzzy_matches = []

    for i in range(len(ungrouped)):
        if ungrouped[i]["id"] in grouped:
            continue
        for j in range(i + 1, len(ungrouped)):
            if ungrouped[j]["id"] in grouped:
                continue

            a = ungrouped[i]
            b = ungrouped[j]

            title_sim = _title_similarity(a.get("title", ""), b.get("title", ""))
            if title_sim < 0.8:
                continue

            # Check first author match
            fa_a = _first_author(a.get("authors", "[]"))
            fa_b = _first_author(b.get("authors", "[]"))

            if fa_a and fa_b and fa_a == fa_b:
                fuzzy_matches.append({
                    "source_ids": [a["id"], b["id"]],
                    "similarity": round(title_sim, 2),
                    "reason": "same first author + near-identical title",
                })
                grouped.add(a["id"])
                grouped.add(b["id"])
            elif title_sim >= 0.95:
                # Very high title similarity even without author match
                fuzzy_matches.append({
                    "source_ids": [a["id"], b["id"]],
                    "similarity": round(title_sim, 2),
                    "reason": "near-identical title (author check inconclusive)",
                })
                grouped.add(a["id"])
                grouped.add(b["id"])

    unique_count = len(source_ids) - sum(len(d["source_ids"]) - 1 for d in doi_duplicates) - sum(len(f["source_ids"]) - 1 for f in fuzzy_matches)

    success_response({
        "doi_duplicates": doi_duplicates,
        "fuzzy_matches": fuzzy_matches,
        "unique_sources": unique_count,
        "total_input": len(source_ids),
    })


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
    p.add_argument("--question-id", default=None, help="Question ID (e.g. Q1) — preferred over --question for matching")
    p.add_argument("--evidence-ids", default=None, help="Comma-separated evidence unit IDs to link to this finding")
    p.add_argument("--session-dir", **_sd)

    # log-gap
    p = sub.add_parser("log-gap")
    p.add_argument("--text", required=True)
    p.add_argument("--question", default=None)
    p.add_argument("--question-id", default=None, help="Question ID (e.g. Q1) — preferred over --question for matching")
    p.add_argument("--session-dir", **_sd)

    # resolve-gap
    p = sub.add_parser("resolve-gap")
    p.add_argument("--gap-id", required=True)
    p.add_argument("--session-dir", **_sd)

    # deduplicate-findings
    p = sub.add_parser("deduplicate-findings")
    p.add_argument("--threshold", type=float, default=0.7, help="Token overlap threshold for merging (default 0.7)")
    p.add_argument("--session-dir", **_sd)

    # add-evidence
    p = sub.add_parser("add-evidence")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path (source manifest with units array)")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # add-evidence-batch
    p = sub.add_parser("add-evidence-batch")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path (array of source manifests)")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read JSON from stdin")
    p.add_argument("--session-dir", **_sd)

    # evidence
    p = sub.add_parser("evidence")
    p.add_argument("--source-id", default=None, help="Filter by source ID")
    p.add_argument("--question-id", default=None, help="Filter by primary question ID")
    p.add_argument("--claim-type", default=None, choices=["result", "method", "limitation", "contradiction", "background"])
    p.add_argument("--status", default="active", help="Filter by status (default: active)")
    p.add_argument("--session-dir", **_sd)

    # evidence-summary
    p = sub.add_parser("evidence-summary")
    p.add_argument("--session-dir", **_sd)

    # link-finding-evidence
    p = sub.add_parser("link-finding-evidence")
    p.add_argument("--finding-id", required=True)
    p.add_argument("--evidence-ids", required=True, help="Comma-separated evidence unit IDs")
    p.add_argument("--role", default="primary", help="Link role (default: primary)")
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

    # support-context
    p = sub.add_parser("support-context")
    p.add_argument("--format", choices=["json", "markdown"], default="json", help="Output JSON context or compact markdown")
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
    p.add_argument("--quality", type=str, choices=sorted(_SOURCE_QUALITY_ACCEPTED), required=True)
    p.add_argument("--session-dir", **_sd)

    # source flags
    p = sub.add_parser("set-source-flag")
    p.add_argument("--source-id", required=True)
    p.add_argument("--flag", required=True, choices=list(_SOURCE_CAUTION_FLAGS))
    p.add_argument("--applies-to", default="run", choices=list(_SOURCE_FLAG_SCOPES))
    p.add_argument("--applies-to-id", default="")
    p.add_argument("--rationale", required=True)
    p.add_argument("--created-by", default="agent")
    p.add_argument("--session-dir", **_sd)

    p = sub.add_parser("source-flags")
    p.add_argument("--source-id", default=None)
    p.add_argument("--flag", default=None, choices=list(_SOURCE_CAUTION_FLAGS))
    p.add_argument("--applies-to", default=None, choices=list(_SOURCE_FLAG_SCOPES))
    p.add_argument("--applies-to-id", default=None)
    p.add_argument("--session-dir", **_sd)

    p = sub.add_parser("source-flag-summary")
    p.add_argument("--include-rows", action="store_true")
    p.add_argument("--session-dir", **_sd)

    p = sub.add_parser("source-quality-summary")
    p.add_argument("--include-rows", action="store_true")
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
    p.add_argument("--batch-size", type=int, default=5, help="Max sources per batch (default 5). Small batches complete within the default 120s Bash timeout; caller loops until remaining=0.")
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
    p.add_argument("--max-attempts", type=int, default=5,
                   help="Maximum total recovery attempts per call (default 5). "
                        "Small default keeps each call within the default Bash timeout. "
                        "Call multiple times for more attempts. "
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

    # convert-pdfs
    p = sub.add_parser("convert-pdfs")
    p.add_argument("--session-dir", **_sd)

    # reconcile
    p = sub.add_parser("reconcile")
    p.add_argument("--session-dir", **_sd)

    # cleanup-orphans
    p = sub.add_parser("cleanup-orphans")
    p.add_argument("--session-dir", **_sd)

    # dedup-references
    p = sub.add_parser("dedup-references", help="Identify duplicate sources among cited references")
    p.add_argument("--sources", required=True, help="Comma-separated source IDs to check (e.g. src-001,src-003,src-007)")
    p.add_argument("--session-dir", **_sd)

    # dedup-issues
    p = sub.add_parser("dedup-issues", help="Deduplicate revision issues by location and description overlap")
    _json_input = p.add_mutually_exclusive_group(required=True)
    _json_input.add_argument("--from-json", help="JSON file path containing issues array")
    _json_input.add_argument("--from-stdin", action="store_true", help="Read issues JSON from stdin")

    # validate-edits
    p = sub.add_parser("validate-edits", help="Check whether reviser edits landed in the report")
    p.add_argument("--manifest", required=True, help="Path to revision-manifest.json")
    p.add_argument("--report", required=True, help="Path to report.md")
    p.add_argument("--pass", dest="pass_type", default=None, choices=["accuracy", "style"],
                   help="Filter to edits from a specific pass (default: check all)")

    # report grounding
    p = sub.add_parser("report-paragraphs", help="List report paragraphs with stable text hashes")
    p.add_argument("--report", required=True, help="Path to draft.md/report.md")
    p.add_argument("--session-dir", **_sd)

    p = sub.add_parser("validate-report-grounding", help="Validate report-grounding.json against report text and state IDs")
    p.add_argument("--manifest", default=None, help="Path to report-grounding.json (default: session/report-grounding.json)")
    p.add_argument("--report", default=None, help="Override report path from manifest")
    p.add_argument("--session-dir", **_sd)

    # validate-content
    p = sub.add_parser("validate-content", help="Validate downloaded content against source metadata")
    p.add_argument("--top", type=int, default=30, help="Number of top sources to check (default 30)")
    p.add_argument("--domain-terms", default=None,
                   help="Comma-separated domain terms to check in content (e.g. 'uncanny,valley,perception')")
    p.add_argument("--expected-domains", default=None,
                   help="Comma-separated expected venue domains (e.g. 'psychology,cognitive science,neuroscience')")
    p.add_argument("--session-dir", **_sd)

    args = parser.parse_args()

    if args.quiet:
        set_quiet(True)

    # Resolve session-dir via auto-discovery for all commands except init and validate-edits
    if args.command not in ("init", "validate-edits", "dedup-issues"):
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
        "add-evidence": cmd_add_evidence,
        "add-evidence-batch": cmd_add_evidence_batch,
        "evidence": cmd_evidence,
        "evidence-summary": cmd_evidence_summary,
        "link-finding-evidence": cmd_link_finding_evidence,
        "gap-search-plan": cmd_gap_search_plan,
        "searches": cmd_searches,
        "sources": cmd_sources,
        "get-source": cmd_get_source,
        "update-source": cmd_update_source,
        "summary": cmd_summary,
        "support-context": cmd_support_context,
        "mark-read": cmd_mark_read,
        "set-status": cmd_set_status,
        "add-tag": cmd_add_tag,
        "list-sources": cmd_list_sources,
        "search-sources": cmd_search_sources,
        "set-quality": cmd_set_quality,
        "set-source-flag": cmd_set_source_flag,
        "source-flags": cmd_source_flags,
        "source-flag-summary": cmd_source_flag_summary,
        "source-quality-summary": cmd_source_quality_summary,
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
        "convert-pdfs": cmd_convert_pdfs,
        "reconcile": cmd_reconcile,
        "cleanup-orphans": cmd_cleanup_orphans,
        "manifest": cmd_manifest,
        "dedup-references": cmd_dedup_references,
        "dedup-issues": cmd_dedup_issues,
        "validate-edits": cmd_validate_edits,
        "report-paragraphs": cmd_report_paragraphs,
        "validate-report-grounding": cmd_validate_report_grounding,
        "validate-content": cmd_validate_content,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
