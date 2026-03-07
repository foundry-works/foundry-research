"""Consistent JSON output envelope and stderr logging for all CLI scripts."""

import json
import sys


def success_response(results: list | dict, total_results: int | None = None, **extra) -> str:
    """Print JSON success envelope to stdout and return it.

    Envelope: {"status": "ok", "results": ..., "errors": [], "total_results": N, ...extra}

    Args:
        results: The result data (list or dict).
        total_results: Total count. Defaults to len(results) for lists, 1 for dicts.
        **extra: Additional top-level keys merged into the envelope.
    """
    if total_results is None:
        total_results = len(results) if isinstance(results, list) else 1

    envelope = {"status": "ok", "results": results, "errors": [], "total_results": total_results, **extra}
    output = json.dumps(envelope, ensure_ascii=False)
    print(output)
    return output


def error_response(errors: list[str], partial_results: list | dict | None = None,
                   error_code: str | None = None) -> str:
    """Print JSON error envelope to stdout and exit.

    Envelope: {"status": "error", "results": ..., "errors": [...], "total_results": N, "error_code": ...}

    Exits with code 0 if partial results exist, 1 if total failure.

    Args:
        errors: List of error message strings.
        partial_results: Any partial results collected before failure.
        error_code: Machine-readable error code (e.g., "rate_limited", "auth_failed").
    """
    if partial_results is None:
        partial_results = []

    total = len(partial_results) if isinstance(partial_results, list) else (1 if partial_results else 0)

    envelope: dict = {
        "status": "error",
        "results": partial_results,
        "errors": errors,
        "total_results": total,
    }
    if error_code:
        envelope["error_code"] = error_code

    output = json.dumps(envelope, ensure_ascii=False)
    print(output)

    sys.exit(0 if total > 0 else 1)


def log(message: str, level: str = "info") -> None:
    """Log a message to stderr (keeps stdout clean for JSON output).

    Args:
        message: The log message.
        level: Log level label (info, warn, error, debug).
    """
    print(f"[{level}] {message}", file=sys.stderr)
