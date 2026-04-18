# Foundry Research

## Plugin Development

This repo is a Claude Code plugin. Edit files in `skills/` and `agents/` directly — they are the plugin source.

- **Local testing:** `claude --plugin-dir .` from the repo root
- **Reload after changes:** `/reload-plugins` in the session
- **Skill invocation:** `/foundry-research:deep-research`, `/foundry-research:reflect`, `/foundry-research:improve`, `/foundry-research:deep-research-revision`

## Plugin Gotchas

- **hooks.json uses a nested format.** Each event entry wraps commands in a `hooks` array: `{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "..."}]}]}}`. This differs from `.claude/settings.json` hook format — don't confuse them.
- **Agent frontmatter cannot include `permissionMode`, `hooks`, or `mcpServers`.** These are blocked for plugin-shipped agents.
- **Bump `version` in `plugin.json` after changes.** Installed plugins cache by version — edits won't reach users until the version changes.
- **`agents`, `skills`, and `hooks` in `plugin.json` override defaults.** If omitted, the default `agents/`, `skills/`, and `hooks/hooks.json` are auto-discovered. Only set them explicitly if you need custom paths. **Do not point `hooks` at `hooks/hooks.json`** — it loads automatically and declaring it again causes a duplicate error.
- **All paths in `plugin.json` must start with `./`** and be relative to the repo root.

## Design Principles

Read `PRINCIPLES.md` before developing new plans or proposing changes to skills and agents. It captures the design philosophy for this project — use it to evaluate whether proposed improvements align with how we build.
