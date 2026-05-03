#!/usr/bin/env bash
# Shared venv bootstrap — sourced by all CLI wrappers.
# Expects SKILL_DIR to be set by the caller.
set -euo pipefail

if [ -z "${SKILL_DIR:-}" ]; then
    echo "ERROR: SKILL_DIR must be set before sourcing bootstrap-venv.sh" >&2
    exit 1
fi

if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    DATA_DIR="$CLAUDE_PLUGIN_DATA"
elif [ -n "${FOUNDRY_RESEARCH_DATA:-}" ]; then
    DATA_DIR="$FOUNDRY_RESEARCH_DATA"
elif [ -n "${CODEX_HOME:-}" ]; then
    DATA_DIR="${CODEX_HOME}/foundry-research/deep-research"
elif [ -n "${HOME:-}" ]; then
    DATA_DIR="${HOME}/.codex/foundry-research/deep-research"
else
    DATA_DIR="${SKILL_DIR}/.foundry-research-data"
fi

mkdir -p "$DATA_DIR"
VENV_DIR="${DATA_DIR}/.venv"
REQ_FILE="${SKILL_DIR}/requirements.txt"
REQ_HASH_FILE="${DATA_DIR}/requirements.sha256"

requirements_hash() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d " " -f 1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d " " -f 1
    else
        python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
    fi
}

# Require Python 3.10+
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)" >&2
    exit 1
fi

if ! python3 -c "import venv" 2>/dev/null; then
    echo "ERROR: Python venv module not found. Install it with:" >&2
    echo "  sudo apt-get install python3-venv    # Debian/Ubuntu" >&2
    echo "  sudo dnf install python3-libs         # Fedora" >&2
    exit 1
fi

CURRENT_REQ_HASH="$(requirements_hash "$REQ_FILE")"
INSTALLED_REQ_HASH="$(cat "$REQ_HASH_FILE" 2>/dev/null || true)"
VENV_CREATED=0

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    VENV_CREATED=1
fi

# Older Claude plugin installs may already have a valid venv but no hash file.
# Preserve that behavior and start tracking the current requirements from here.
if [ "$VENV_CREATED" -eq 0 ] && [ -z "$INSTALLED_REQ_HASH" ]; then
    printf "%s\n" "$CURRENT_REQ_HASH" > "$REQ_HASH_FILE"
    INSTALLED_REQ_HASH="$CURRENT_REQ_HASH"
fi

if [ "$CURRENT_REQ_HASH" != "$INSTALLED_REQ_HASH" ]; then
    "$VENV_DIR/bin/pip" install -q -r "$REQ_FILE"
    printf "%s\n" "$CURRENT_REQ_HASH" > "$REQ_HASH_FILE"
fi
