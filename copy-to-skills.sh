#!/usr/bin/env bash
# Deploy all skills from skills/*/ into .claude/skills/ for local testing.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

for skill_dir in "$REPO_DIR"/skills/*/; do
    [ -d "$skill_dir" ] || continue
    name="$(basename "$skill_dir")"
    dest="$REPO_DIR/.claude/skills/$name"

    # Clean previous copy
    rm -rf "$dest"
    mkdir -p "$dest"

    # Copy everything in the skill directory
    cp -r "$skill_dir"/* "$dest/"

    # Remove __pycache__ dirs
    find "$dest" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    echo "Deployed skill: $name"
done

# Copy agents from root agents/ directory
if [ -d "$REPO_DIR/agents" ]; then
    mkdir -p "$REPO_DIR/.claude/agents"
    cp "$REPO_DIR"/agents/*.md "$REPO_DIR/.claude/agents/" 2>/dev/null || true
    echo "Deployed agents"
fi

echo ""
echo "Skills deployed to .claude/skills/:"
ls -1 "$REPO_DIR/.claude/skills/"
