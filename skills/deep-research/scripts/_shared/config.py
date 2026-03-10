"""Shared configuration: API keys, session directory, rate limit defaults."""

import json
import os
from pathlib import Path

# Environment variable names for API keys
_ENV_KEYS = {
    "semantic_scholar_api_key": "SEMANTIC_SCHOLAR_API_KEY",
    "openalex_api_key": "OPENALEX_API_KEY",
    "unpaywall_email": "UNPAYWALL_EMAIL",
    "ncbi_api_key": "NCBI_API_KEY",
    "github_token": "GITHUB_TOKEN",
    "annas_secret_key": "ANNAS_SECRET_KEY",
    "sec_edgar_email": "SEC_EDGAR_EMAIL",
    "core_api_key": "CORE_API_KEY",
}

# All known config keys with None defaults
_DEFAULT_CONFIG: dict[str, str | None] = {
    "semantic_scholar_api_key": None,
    "openalex_api_key": None,
    "unpaywall_email": None,
    "ncbi_api_key": None,
    "github_token": None,
    "annas_secret_key": None,
    "sec_edgar_email": None,
    "core_api_key": None,
}

# Global config file path
_GLOBAL_CONFIG_PATH = Path.home() / ".deep-research" / "config.json"

# Default rate limits (requests per second) per domain
RATE_LIMITS = {
    "api.semanticscholar.org": 1.0,
    "api.openalex.org": 10.0,
    "api.crossref.org": 10.0,
    "api.unpaywall.org": 10.0,
    "www.reddit.com": 0.15,
    "eutils.ncbi.nlm.nih.gov": 3.0,
    "api.biorxiv.org": 1.0,
    "api.github.com": 0.5,
    "hn.algolia.com": 1.0,
    "sci-hub.*": 0.2,
    "arxiv.org": 1.0,
    "ncbi.nlm.nih.gov": 3.0,
    "query2.finance.yahoo.com": 0.4,
    "efts.sec.gov": 10.0,
    "data.sec.gov": 10.0,
    "www.sec.gov": 10.0,
    "_default": 2.0,
}


def _load_json_config(path: Path) -> dict:
    """Load a JSON config file, returning empty dict if missing or invalid."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_config(session_dir: str | None = None) -> dict:
    """Load config with precedence: env vars > global config > session config.

    Higher-priority sources overwrite lower-priority values.
    Returns dict with all known keys (None for unset).

    Args:
        session_dir: Optional session directory for session-local config.
    """
    config = dict(_DEFAULT_CONFIG)

    # Layer 1 (lowest priority): session-dir local config
    if session_dir:
        session_config = _load_json_config(Path(session_dir) / ".config.json")
        for key in config:
            if key in session_config and session_config[key] is not None:
                config[key] = session_config[key]

    # Layer 2: global config file
    global_config = _load_json_config(_GLOBAL_CONFIG_PATH)
    for key in config:
        if key in global_config and global_config[key] is not None:
            config[key] = global_config[key]

    # Layer 3 (highest priority): environment variables
    for key, env_var in _ENV_KEYS.items():
        value = os.environ.get(env_var)
        if value:
            config[key] = value

    return config


MARKER_FILENAME = ".deep-research-session"


def _discover_session_dir_from_marker() -> str | None:
    """Walk up from cwd looking for a .deep-research-session marker file.

    The marker file contains the absolute path to the session directory.
    Returns the session directory path if found, None otherwise.
    """
    current = Path.cwd()
    for directory in [current, *current.parents]:
        marker = directory / MARKER_FILENAME
        if marker.is_file():
            content = marker.read_text(encoding="utf-8").strip()
            if content and Path(content).is_dir():
                return content
        # Stop at filesystem root
        if directory == directory.parent:
            break
    return None


def write_session_marker(session_dir: str) -> None:
    """Write a .deep-research-session marker file in the current working directory.

    The marker contains the absolute path to the session directory,
    enabling auto-discovery by subsequent commands.
    """
    marker_path = Path.cwd() / MARKER_FILENAME
    marker_path.write_text(str(Path(session_dir).resolve()) + "\n", encoding="utf-8")


def get_session_dir(args) -> str:
    """Resolve session directory from CLI args, environment, or marker file.

    Precedence:
        1. args.session_dir (from --session-dir CLI flag)
        2. $DEEP_RESEARCH_SESSION_DIR environment variable
        3. .deep-research-session marker file (walk up from cwd)

    Creates the directory and sources/metadata/ subdirectory if they don't exist.

    Args:
        args: Namespace with optional session_dir attribute.

    Returns:
        Absolute path to the session directory.

    Raises:
        SystemExit: If no session directory is specified.
    """
    session_dir = getattr(args, "session_dir", None)
    if not session_dir:
        session_dir = os.environ.get("DEEP_RESEARCH_SESSION_DIR")
    if not session_dir:
        session_dir = _discover_session_dir_from_marker()
    if not session_dir:
        import sys
        print("Error: No session directory specified. Use --session-dir, set DEEP_RESEARCH_SESSION_DIR, or run from a directory with a .deep-research-session marker.", file=sys.stderr)
        sys.exit(1)

    path = Path(session_dir).resolve()
    (path / "sources" / "metadata").mkdir(parents=True, exist_ok=True)
    return str(path)
