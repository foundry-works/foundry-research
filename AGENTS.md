# Foundry Research

## Development Source

This repo is the source for Foundry Research plugin assets. Edit files in `skills/`, `agents/`, and `hooks/` directly.

## Claude Code Testing

- Run `claude --plugin-dir .` from the repo root.
- Use `/reload-plugins` after changing plugin files.
- Skill invocations are `/foundry-research:deep-research`, `/foundry-research:reflect`, `/foundry-research:improve`, and `/foundry-research:deep-research-revision`.

## Codex Dev Testing

Use the local dev helper to expose this checkout's skills to Codex:

```bash
scripts/codex-dev-install.sh install
```

This creates symlinks in `${CODEX_HOME:-~/.codex}/skills` for:

- `deep-research`
- `deep-research-revision`
- `reflect`
- `improve`

Codex loads them as namespaced skills:

- `foundry-research:deep-research`
- `foundry-research:deep-research-revision`
- `foundry-research:reflect`
- `foundry-research:improve`

Restart Codex after installing or removing skill symlinks. Because the install uses symlinks back to this checkout, normal file edits are picked up by new Codex sessions without reinstalling.

Useful commands:

```bash
scripts/codex-dev-install.sh status
scripts/codex-dev-install.sh uninstall
scripts/codex-dev-install.sh cleanup
```

`uninstall` removes only the skill symlinks that point at this checkout. `cleanup` also removes the temporary `foundry-local-test` Codex marketplace entry used during local plugin experiments.

For full Codex plugin testing, register or provide a marketplace, start Codex, open `/plugins`, install the plugin from the plugin browser, then start a new thread. `codex plugin marketplace add` only registers a marketplace source; it does not install or enable the plugin by itself.

## Plugin Gotchas

- `hooks.json` uses the plugin nested format: `{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "..."}]}]}}`.
- Agent frontmatter cannot include `permissionMode`, `hooks`, or `mcpServers`.
- Bump `.codex-plugin/plugin.json` `version` before release installs; installed plugins cache by version.
- Keep manifest paths relative to the repo root and starting with `./`.
- Do not commit local Codex state from `~/.codex`; use the dev script instead.

## Design Principles

Read `PRINCIPLES.md` before proposing or implementing changes to skills and agents. It captures the design philosophy for this project.
