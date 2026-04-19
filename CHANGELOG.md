# Changelog

## 1.0.3

- Fix research-verifier agent "Prompt is too long" error by switching to notes-first verification (reads summaries before full source docs), capping full-source reads at 3-4 per session, and reducing claim count from 8-15 to 5-10
- Update revision skill to pass condensed brief (scope + question IDs) instead of full brief.json to the verifier

## 1.0.2

- Remove explicit hooks path from plugin.json (auto-discovered by default)
- Add plugin development gotchas to CLAUDE.md

## 1.0.1

- Fix hooks.json format — wrap command in nested hooks array
- Remove explicit agents field from plugin.json — auto-discovered by default

## 1.0.0

- Convert to Claude Code plugin with docs and grey-sources opt-out
- Add gap-search tagging, source ID normalization, metadata sync, and search guardrails
- Add CLI commands for provider probing, content validation, issue dedup, reference dedup, and edit validation
- Add search metrics breakdown, reference renumbering, and cognitive science guidance
- Add title_from_content detection, gap-mode depth criteria, and reader quality logging
- Add OSF/PsyArXiv support, paywall recovery guidance, and content-mismatch improvements
- Add web-provider batch limits and Semantic Scholar query guidance
- Add venue/domain validation, quality gate, relevance floor, web-source triage, and paywall recovery guidance
- Add information density, exec summary, and statistical notation dimensions to style reviewer
