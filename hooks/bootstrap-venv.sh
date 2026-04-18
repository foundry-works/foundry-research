#!/usr/bin/env bash
# SessionStart hook: sync requirements.txt to CLAUDE_PLUGIN_DATA and
# (re)bootstrap the venv if requirements changed.
set -euo pipefail

REQ="${CLAUDE_PLUGIN_ROOT}/skills/deep-research/requirements.txt"
DATA_REQ="${CLAUDE_PLUGIN_DATA}/requirements.txt"
BOOTSTRAP="${CLAUDE_PLUGIN_ROOT}/skills/deep-research/bootstrap-venv.sh"

mkdir -p "${CLAUDE_PLUGIN_DATA}"

if ! diff -q "$REQ" "$DATA_REQ" >/dev/null 2>&1; then
    cp "$REQ" "$DATA_REQ"
    SKILL_DIR="${CLAUDE_PLUGIN_ROOT}/skills/deep-research" source "$BOOTSTRAP"
fi
