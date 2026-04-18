# Architecture

foundry-research is a multi-agent research pipeline built on Claude Code skills and subagents. This document explains how the pieces fit together.

## Skill/Agent Model

```
User → Claude Code → /deep-research skill (orchestrator)
                          │
                          ├─ brief-writer agent        (research brief)
                          ├─ source-acquisition agent   (search + download)
                          │       └─ CLI tools: search, download, state, enrich
                          ├─ research-reader agents     (read + summarize sources)
                          ├─ findings-logger agents     (extract findings per question)
                          ├─ synthesis-writer agent     (draft report)
                          ├─ synthesis-reviewer agent   (audit for contradictions)
                          ├─ research-verifier agent    (fact-check claims)
                          ├─ style-reviewer agent       (plain-language review)
                          └─ report-reviser agent       (surgical edits)
```

The orchestrator is defined in `skills/deep-research/SKILL.md` and manages a 15-step workflow. Each subagent is a markdown prompt in `agents/` with YAML frontmatter specifying its model tier and available tools.

## Pipeline Overview

1. **Brief** — Generate a research brief with evaluative questions from the user's topic
2. **Acquire sources** — Multi-round search across providers, download PDFs, validate content
3. **Read sources** — Extract key information from each downloaded source
4. **Log findings** — Map extracted findings to research questions
5. **Identify gaps** — Find under-covered questions and search for more sources
6. **Synthesize** — Draft a research report from the findings
7. **Review** — Check for contradictions, unsupported claims, and style issues
8. **Revise** — Make targeted edits based on review feedback
9. **Deliver** — Final report with references and methodology

## Directory Structure

```
foundry-research/
├── skills/                      # Source of truth for skills
│   ├── deep-research/           # Main research skill
│   │   ├── SKILL.md             # Orchestrator prompt (15-step workflow)
│   │   ├── REFERENCE.md         # Provider guidance, session structure
│   │   ├── requirements.txt     # Python dependencies
│   │   ├── bootstrap-venv.sh    # Shared venv bootstrap (sourced by wrappers)
│   │   ├── setup.sh             # Venv bootstrap entry point
│   │   ├── search               # CLI wrapper → scripts/search.py
│   │   ├── download             # CLI wrapper → scripts/download.py
│   │   ├── state                # CLI wrapper → scripts/state.py
│   │   ├── enrich               # CLI wrapper → scripts/enrich.py
│   │   ├── triage-relevance     # CLI wrapper → scripts/triage-relevance
│   │   └── scripts/
│   │       ├── search.py        # Multi-provider search dispatcher
│   │       ├── download.py      # PDF cascade downloader
│   │       ├── state.py         # SQLite session state tracker
│   │       ├── enrich.py        # Crossref metadata enrichment
│   │       ├── providers/       # 20 search provider modules
│   │       └── _shared/         # Config, HTTP client, PDF utils, etc.
│   ├── deep-research-revision/  # Report revision skill
│   ├── reflect/                 # Quality evaluation skill
│   └── improve/                 # Pipeline improvement skill
├── agents/                      # Source of truth for subagent prompts
│   ├── brief-writer.md
│   ├── source-acquisition.md
│   ├── research-reader.md
│   ├── findings-logger.md
│   ├── synthesis-writer.md
│   ├── synthesis-reviewer.md
│   ├── research-verifier.md
│   ├── style-reviewer.md
│   └── report-reviser.md
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── hooks/
│   └── hooks.json               # SessionStart venv bootstrap
├── PRINCIPLES.md                # Design principles
└── docs/                        # User documentation
```

## CLI Tools

The Python scripts in `scripts/` are the operational backbone. They're invoked through bash wrappers that auto-bootstrap a virtual environment on first use.

### search.py
Multi-provider search dispatcher. Routes queries to the right provider(s) based on domain and availability. Auto-logs searches to the session state database.

### download.py
PDF download cascade with seven sources. Tries each source in order until one succeeds. Supports PDF-to-markdown conversion, quality checks, and parallel downloads.

### state.py
SQLite-backed session state tracker. Manages search history, source index, findings, gaps, and audit trails. Provides summary and audit commands for pipeline observability.

### enrich.py
Crossref-based metadata enrichment. Fills in missing DOIs, titles, authors, and journal names for sources that have incomplete metadata.

## Search Provider Landscape

20 providers organized by type:

**Academic search** — Semantic Scholar, OpenAlex, arXiv, PubMed, bioRxiv, Crossref, OpenCitations, DBLP, CORE

**Web search** — Tavily, Perplexity, Linkup, Exa, GenSee (at least one key required)

**Discussion** — Reddit, Hacker News

**Financial** — yfinance, SEC EDGAR

**Code** — GitHub

The source-acquisition agent selects providers based on research domain. See [configuration.md](configuration.md) for credential details.

## Download Cascade

When downloading a paper by DOI, the system tries sources in order:

```
OpenAlex → Unpaywall → arXiv → PMC → OSF → Anna's Archive → Sci-Hub
```

The first five are legitimate open-access channels. The last two are shadow libraries that can be disabled. See [grey-sources.md](grey-sources.md) for details.

## Session Structure

Each research run creates a session directory:

```
deep-research-{session}/
├── state.db              # SQLite — search history + source index
├── journal.md            # Orchestrator reasoning trail (append-only)
├── report.md             # Final research report
├── notes/                # Per-source summaries from reader agents
│   └── src-001.md
└── sources/
    ├── metadata/         # JSON metadata files
    │   └── src-001.json
    ├── src-001.md        # Extracted markdown content
    ├── src-001.pdf       # Original PDF (if downloaded)
    └── src-001.toc       # Table of contents with line numbers
```

## Model Tiers

Subagents use different model tiers based on their task:

- **opus** — Complex reasoning tasks: brief writing, source acquisition, synthesis, verification, revision
- **sonnet** — Review tasks: contradiction checking, style auditing
- **haiku** — High-volume tasks: reading sources, logging findings

## Installation Flow

1. Install the plugin: `claude plugin install foundry-research`
2. Or clone and test locally: `git clone ... && claude --plugin-dir .`
3. Configure API keys (see [configuration.md](configuration.md))
4. Invoke with `/foundry-research:deep-research` or just describe your research question

The skill activates automatically when Claude Code detects a research-oriented query. No manual invocation needed (though you can use `/foundry-research:deep-research` explicitly).
