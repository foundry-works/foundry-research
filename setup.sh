#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SKILL_DIR/.venv"

# Require Python 3.10+
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)" >&2
    exit 1
fi

# Check that venv module is available (missing on some Debian/Ubuntu systems)
if [ ! -d "$VENV_DIR" ]; then
    if ! python3 -c "import venv" 2>/dev/null; then
        echo "ERROR: Python venv module not found. Install it with:" >&2
        echo "  sudo apt-get install python3-venv    # Debian/Ubuntu" >&2
        echo "  sudo dnf install python3-libs         # Fedora" >&2
        exit 1
    fi
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -r "$SKILL_DIR/requirements.txt"
fi
echo "$VENV_DIR/bin/python"
