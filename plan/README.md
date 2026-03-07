# Plan: Standalone Claude Deep Research Skill

## Goal
Create a Claude Code skill that implements deep research capabilities. Claude + its native tools + Tavily MCP + lightweight Python helper scripts for academic API access. Claude itself is the reasoning engine and orchestrator.

**External dependency:** Tavily MCP server (`tavily_search`) is an optional but strongly recommended dependency for web search. Without it, the skill falls back to Claude's native `WebSearch`/`WebFetch` tools automatically.

## Design Philosophy

Claude *is* the reasoning engine. The infrastructure gives it tools and trusts its judgment — it doesn't dictate a fixed procedure. Research is an intelligent exploration, not a manufacturing process.

**Key principles:**
- **4 CLI commands** instead of 12 — Claude learns `search.py`, `download.py`, `enrich.py`, `state.py`
- **Capabilities, not phases** — Claude invokes tools as needed, not in a fixed sequence
- **Persistent state** — track searches, sources, findings, and gaps across conversations
- **Full provider breadth** — all 9+ search providers preserved with provider-specific features
- **Tavily MCP** — optional dependency for enhanced web search (auto-fallback to native tools)

## Plan Structure

- [Architecture](./architecture.md) — File structure, session directory, why Python scripts

### Script Specifications

- [search.py](./scripts/search.md) — Unified search CLI with `--provider` flag
  - [Provider specs](./scripts/providers/) — Per-provider API details
- [download.py](./scripts/download.md) — Web content + PDF download + DOI cascade + PDF→Markdown
  - [Anna's Archive integration](./scripts/annas-archive.md) — Shadow library source with dynamic mirror discovery
- [enrich.py](./scripts/enrich.md) — Crossref DOI metadata enrichment
- [state.py](./scripts/state.md) — Session state tracker (searches, sources, findings, gaps, brief)

### Strategy & Infrastructure
- [Shared Dependencies](./shared-deps.md) — `_shared/` utilities (7 modules)
- [Guardrails](./guardrails.md) — Adaptive defaults, tool usage guidance
- [Skill Prompt Spec](./skill-prompt.md) — SKILL.md design (~230 lines, capabilities-based)
- [Synthesis Strategy](./synthesis-strategy.md) — Context window management, selective reading, intermediate summarization
- [Delegation Strategy](./delegation-strategy.md) — Subagent usage, model routing (Opus/Sonnet/Haiku)
- [Implementation Order](./implementation-order.md) — Build sequence
- [Tests](./tests.md) — Automated test plan
- [Multi-Session Architecture](./multi-session.md) — Phase 3: multi-conversation research sessions
