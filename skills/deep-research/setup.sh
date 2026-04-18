#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=bootstrap-venv.sh
# Sets VENV_DIR (preferring $CLAUDE_PLUGIN_DATA, falling back to $SKILL_DIR).
source "$SKILL_DIR/bootstrap-venv.sh"

echo "$VENV_DIR/bin/python"
