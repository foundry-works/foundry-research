#!/usr/bin/env bash
# SessionStart hook: warm the deep-research venv when the host supports hooks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    PLUGIN_DATA="$CLAUDE_PLUGIN_DATA"
elif [ -n "${FOUNDRY_RESEARCH_DATA:-}" ]; then
    PLUGIN_DATA="$FOUNDRY_RESEARCH_DATA"
elif [ -n "${CODEX_HOME:-}" ]; then
    PLUGIN_DATA="${CODEX_HOME}/foundry-research"
elif [ -n "${HOME:-}" ]; then
    PLUGIN_DATA="${HOME}/.codex/foundry-research"
else
    PLUGIN_DATA="${PLUGIN_ROOT}/.foundry-research-data"
fi

REQ="${PLUGIN_ROOT}/skills/deep-research/requirements.txt"
DATA_REQ="${PLUGIN_DATA}/requirements.txt"
BOOTSTRAP="${PLUGIN_ROOT}/skills/deep-research/bootstrap-venv.sh"

mkdir -p "$PLUGIN_DATA"

if ! diff -q "$REQ" "$DATA_REQ" >/dev/null 2>&1; then
    cp "$REQ" "$DATA_REQ"
fi

SKILL_DIR="${PLUGIN_ROOT}/skills/deep-research"
CLAUDE_PLUGIN_DATA="$PLUGIN_DATA"
export SKILL_DIR CLAUDE_PLUGIN_DATA
source "$BOOTSTRAP"
