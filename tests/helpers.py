"""Shared test helpers — importable by test modules."""

import json
import os
import subprocess
import sys

STATE_PY = os.path.join(os.path.dirname(__file__), os.pardir, "skills", "deep-research", "scripts", "state.py")


def run_state(*cli_args):
    """Run state.py as a subprocess and return (result, parsed_json)."""
    result = subprocess.run(
        [sys.executable, STATE_PY, *cli_args],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout) if result.stdout.strip() else {}
    return result, data


def init_session(session_dir: str, query: str = "test query") -> str:
    """Initialize a session via CLI and return the session ID."""
    result, data = run_state("init", "--session-dir", session_dir, "--query", query)
    assert result.returncode == 0, f"init failed: {result.stderr}"
    return data["results"]["session_id"]


def write_json_file(tmp_path, data, name="input.json") -> str:
    """Write data to a JSON file and return its path."""
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as f:
        json.dump(data, f)
    return path
