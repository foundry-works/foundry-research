#!/usr/bin/env bash
# Copy the deep-research skill into .claude/skills/deep-research for local testing.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$REPO_DIR/.claude/skills/deep-research"

# Clean previous copy
rm -rf "$DEST"
mkdir -p "$DEST"

# --- Skill definition ---
cp "$REPO_DIR/SKILL.md" "$DEST/"

# --- CLI wrappers + bootstrap ---
cp "$REPO_DIR/search" "$DEST/"
cp "$REPO_DIR/download" "$DEST/"
cp "$REPO_DIR/enrich" "$DEST/"
cp "$REPO_DIR/state" "$DEST/"
cp "$REPO_DIR/setup.sh" "$DEST/"
cp "$REPO_DIR/requirements.txt" "$DEST/"

# --- Python scripts ---
cp -r "$REPO_DIR/scripts" "$DEST/scripts"

# Remove __pycache__ dirs
find "$DEST/scripts" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# --- Subagent ---
mkdir -p "$DEST/.claude/agents"
cp "$REPO_DIR/.claude/agents/research-reader.md" "$DEST/.claude/agents/"

echo "Copied deep-research skill to $DEST"
echo "Contents:"
find "$DEST" -type f | sort | sed "s|$DEST/||"
