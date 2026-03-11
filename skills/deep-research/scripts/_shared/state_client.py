"""Subprocess client for state.py — single place for the IPC contract.

All call sites that invoke state.py as a subprocess should use call_state()
rather than reimplementing the temp-file → subprocess → JSON-parse pattern.
If the IPC contract changes (args, envelope format, error handling), only
this module needs updating instead of four scattered call sites.
"""

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from _shared.output import log, log_subprocess_failure

# Locate state.py once — it lives in the parent of _shared/
_STATE_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state.py",
)


def call_state(
    session_dir: str,
    subcommand: str,
    *,
    args: list[str] | None = None,
    json_data: Any = None,
    timeout: int = 10,
) -> dict | None:
    """Invoke state.py as a subprocess and return parsed JSON response.

    Handles: temp file lifecycle for JSON payloads, sys.executable + state.py
    invocation, returncode check, JSON parse, log_subprocess_failure on error.

    Returns parsed dict on success, None on failure (callers already treat
    failures as non-fatal warnings).
    """
    cmd = [sys.executable, _STATE_SCRIPT, subcommand, "--session-dir", session_dir]
    if args:
        cmd.extend(args)

    tmp_path: str | None = None
    try:
        # Write JSON payload to temp file if provided
        if json_data is not None:
            fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="state_client_")
            with os.fdopen(fd, "w") as f:
                json.dump(json_data, f, ensure_ascii=False)
            cmd.extend(["--from-json", tmp_path])

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        if proc.returncode != 0:
            log_subprocess_failure(subcommand, proc)
            return None

        if not proc.stdout:
            return {}

        try:
            resp = json.loads(proc.stdout)
        except json.JSONDecodeError:
            log(f"{subcommand} returned non-JSON: {proc.stdout[:200]}", level="warn")
            return None

        if resp.get("status") == "error":
            errors = resp.get("errors", [])
            log(f"{subcommand} error: {errors}", level="warn")
            return None

        return resp

    except subprocess.TimeoutExpired:
        log(f"{subcommand} timed out after {timeout}s", level="warn")
        return None
    except Exception as e:
        log(f"{subcommand} failed: {e}", level="warn")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
