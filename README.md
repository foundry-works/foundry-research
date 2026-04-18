# foundry-research

A Claude Code plugin for deep research with academic database search, structured source management, and multi-agent synthesis. Give it a topic and it produces a cited, structured literature synthesis — tracking hundreds of sources across 20+ academic and web providers, deeply reading the most relevant 20-30, and delivering a report with key findings, contradiction analysis, confidence ratings, and a full reference list.

## Install

### From this repo (recommended)

```bash
# Add the repo as a marketplace source
claude /plugin marketplace add foundry-works/foundry-research

# Install the plugin
claude plugin install foundry-research
```

Or from inside a Claude Code session:

```
/plugin marketplace add foundry-works/foundry-research
/plugin install foundry-research
```

### Local / development

```bash
git clone https://github.com/foundry-works/foundry-research.git
cd foundry-research
claude --plugin-dir .
```

Use `/reload-plugins` in the session to pick up changes.

## Configure

On first enable, you'll be prompted for:
- **Tavily API key** — for web search (get one at [tavily.com](https://tavily.com))

Additional API keys can be set as environment variables. See [.env.example](.env.example) or [docs/configuration.md](docs/configuration.md) for the full reference.

## Skills

| Skill | Invocation | Description |
|-------|-----------|-------------|
| deep-research | `/foundry-research:deep-research` | Multi-source research with synthesis |
| deep-research-revision | `/foundry-research:deep-research-revision` | Review-then-revise cycle for existing reports |
| reflect | `/foundry-research:reflect` | Quality assessment of completed sessions |
| improve | `/foundry-research:improve` | Pipeline improvement across sessions |

## Agents

9 specialized subagents handle different phases of the research pipeline:

| Agent | Model | Role |
|-------|-------|------|
| brief-writer | opus | Generate research briefs with evaluative questions |
| source-acquisition | opus | Run search, triage, and download pipeline |
| research-reader | haiku | Read and summarize individual source files |
| findings-logger | haiku | Extract and log findings per research question |
| synthesis-writer | opus | Draft theme-based research reports |
| research-verifier | opus | Fact-check claims against authoritative sources |
| synthesis-reviewer | sonnet | Audit drafts for contradictions and gaps |
| style-reviewer | sonnet | Audit for clarity and plain-language style |
| report-reviser | opus | Make targeted edits based on review issues |

## Requirements

- Python 3.10+
- Python `venv` module (on Debian/Ubuntu: `sudo apt-get install python3-venv`)

Dependencies are auto-installed on first use via virtual environment.

## Grey Sources

The PDF download cascade includes Anna's Archive and Sci-Hub, which provide access to paywalled papers. Using them is a **personal choice**. To disable:

```bash
export DEEP_RESEARCH_DISABLED_SOURCES="annas_archive,scihub"
```

See [docs/grey-sources.md](docs/grey-sources.md) for details.

## Documentation

- [Configuration](docs/configuration.md) — API keys, provider setup
- [Grey Sources](docs/grey-sources.md) — shadow library details and opt-out
- [Architecture](docs/architecture.md) — skill/agent model, pipeline overview
- [Design Principles](PRINCIPLES.md) — project philosophy

## License

[MIT](LICENSE)
