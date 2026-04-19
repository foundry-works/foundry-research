"""Shared helpers for evidence unit question-id handling.

Used by both state.py and metrics.py to avoid logic divergence.
"""

import json


def evidence_question_ids(row) -> set[str]:
    """Return all question IDs associated with an evidence row.

    Handles both sqlite3.Row objects (with .keys()) and plain dicts.
    """
    question_ids: set[str] = set()
    keys = row.keys() if hasattr(row, "keys") else []

    if "primary_question_id" in keys:
        primary = row["primary_question_id"]
        if primary:
            question_ids.add(str(primary))

    if "question_ids" in keys:
        raw = row["question_ids"]
        if raw:
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                parsed = []
            for qid in parsed:
                if qid:
                    question_ids.add(str(qid))

    return question_ids


def evidence_matches_question(row, question_id: str) -> bool:
    """Return True when an evidence row is linked to a question ID."""
    return question_id in evidence_question_ids(row)


def count_evidence_by_question(rows) -> dict[str, int]:
    """Count evidence rows against every linked question ID."""
    counts: dict[str, int] = {}
    for row in rows:
        for qid in evidence_question_ids(row):
            counts[qid] = counts.get(qid, 0) + 1
    return counts
