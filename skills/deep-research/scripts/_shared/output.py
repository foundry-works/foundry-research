"""Consistent JSON output envelope and stderr logging for all CLI scripts."""

from __future__ import annotations

import json
import sys
from typing import NoReturn

# ---------------------------------------------------------------------------
# Canonical error codes — use these in error_response(error_code=...) calls.
# Providers should map HTTP status codes to one of these rather than using
# raw "http_NNN" strings, so callers can handle errors uniformly.
# ---------------------------------------------------------------------------
ERR_API = "api_error"            # Generic API/HTTP failure (5xx, unexpected status)
ERR_RATE_LIMITED = "rate_limited"  # 429 or provider-specific throttling
ERR_NOT_FOUND = "not_found"       # 404 or resource does not exist
ERR_AUTH_FAILED = "auth_failed"   # 401/403 or invalid API key
ERR_AUTH_MISSING = "auth_missing" # No API key configured
ERR_MISSING_QUERY = "missing_query"  # Required search query not provided

# Global quiet mode flag — suppresses stderr log output when True
_quiet = False


def set_quiet(quiet: bool) -> None:
    """Enable or disable quiet mode (suppresses stderr log output)."""
    global _quiet
    _quiet = quiet


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
                   error_code: str | None = None, **extra) -> NoReturn:
    """Print JSON error envelope to stdout and exit.

    Envelope: {"status": "error", "results": ..., "errors": [...], "total_results": N, "error_code": ...}

    Always exits with code 0. Error information is in the JSON envelope
    ("status": "error", "errors": [...]) — the supervisor detects failures from
    the structured output, not the exit code. Exit code 0 is critical because
    Claude Code cancels all sibling tool calls when any parallel call returns
    non-zero, so an API error from one provider would kill unrelated parallel
    searches against other providers.

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
    envelope.update(extra)

    output = json.dumps(envelope, ensure_ascii=False)
    print(output)

    sys.exit(0)


def log_subprocess_failure(name: str, proc, level: str = "warn", max_stderr: int = 500) -> None:
    """Log a subprocess failure with exit code and truncated stderr.

    Handles both text mode (proc.stderr is str) and binary mode (bytes).
    """
    stderr = proc.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    stderr = stderr.strip()[:max_stderr]
    log(f"{name} failed (exit {proc.returncode}): {stderr}", level=level)


def log(message: str, level: str = "info") -> None:
    """Log a message to stderr (keeps stdout clean for JSON output).

    Suppressed when quiet mode is enabled via set_quiet(True) or --quiet flag.

    Args:
        message: The log message.
        level: Log level label (info, warn, error, debug).
    """
    if not _quiet:
        print(f"[{level}] {message}", file=sys.stderr)
