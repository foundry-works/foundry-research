# Foundry Research

## Plugin Development

This repo is a Claude Code plugin. Edit files in `skills/` and `agents/` directly — they are the plugin source.

- **Local testing:** `claude --plugin-dir .` from the repo root
- **Reload after changes:** `/reload-plugins` in the session
- **Skill invocation:** `/foundry-research:deep-research`, `/foundry-research:reflect`, `/foundry-research:improve`, `/foundry-research:deep-research-revision`

## Design Principles

Read `PRINCIPLES.md` before developing new plans or proposing changes to skills and agents. It captures the design philosophy for this project — use it to evaluate whether proposed improvements align with how we build.
