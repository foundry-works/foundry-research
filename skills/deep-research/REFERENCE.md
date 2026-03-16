# Deep Research — Reference

Reference material for the deep research pipeline. The orchestrator's core workflow is in `SKILL.md`. This file contains provider guidance, session structure, adaptive guardrails, and output format — material that subagents and the orchestrator can consult as needed but that doesn't need to be in the hot path during research.

---

## Provider Selection Guidance

Provider selection is handled by the `source-acquisition` agent (see `agents/source-acquisition.md`), but you should understand the landscape to validate the agent's manifest and direct gap-mode searches:

- **Biomedical/clinical:** PubMed + bioRxiv + Semantic Scholar
- **CS/ML/AI:** arXiv + Semantic Scholar + OpenAlex
- **Psychology/cognitive science:** PubMed + Semantic Scholar + OpenAlex + OSF/PsyArXiv (preprints). Note: PubMed's MeSH vocabulary skews biomedical — for cognitive science topics (judgment, decision-making, metacognition), OpenAlex and Semantic Scholar with targeted journal-name queries are often more productive
- **Humanities/social science:** Crossref + OpenAlex + Semantic Scholar
- **Financial:** yfinance + EDGAR + academic providers for context
- **General technical:** tavily + GitHub; Reddit/HN for community perspective
- **When unsure:** at least 3 providers including one web source

---

## Session Structure

```
./deep-research-{session}/
├── state.db              # SQLite — search history + source index (source of truth)
├── journal.md            # Your reasoning scratchpad (append-only)
├── report.md             # Final report
├── notes/                # Per-source summaries (from reader subagents)
│   └── src-001.md
└── sources/
    ├── metadata/         # JSON metadata files
    │   └── src-001.json
    ├── src-001.md        # Pure markdown content
    ├── src-001.pdf       # PDF when available
    └── src-001.toc       # Table of contents with line numbers
```

- Initialize: `${CLAUDE_SKILL_DIR}/state init --query "..."`
- Sources and searches are auto-tracked by `${CLAUDE_SKILL_DIR}/search` (no manual step needed)
- Check duplicates: `${CLAUDE_SKILL_DIR}/state check-dup-batch --from-json` (batch)
- Review progress: `${CLAUDE_SKILL_DIR}/state summary`
- Pre-report check: `${CLAUDE_SKILL_DIR}/state audit`

---

## Adaptive Guardrails

Defaults with rationale — scale based on query complexity:

| Parameter | Default | Scale down | Scale up |
|-----------|---------|------------|----------|
| Research questions | 3-7 | Simple factual → 1-2 | Broad review → up to 10 |
| Searches per question | 1-3 | Comprehensive initial results → 1 | Niche topic → 3+ |
| Total sources | 15-40 | Simple query → 5-10 | Systematic review → 50+ |
| Sources cited | 10-25 | Scale with report length | |

Don't over-research simple questions. Don't under-research complex ones.

---

## Output Format

```markdown
# [Research Topic]

## Key Findings
- Finding 1 [1][2]
- Finding 2 [3]
- ...

## [Topic-appropriate sections]
### [Sections based on research questions]
...

## Methodology
- Sources deeply read: N (with notes in notes/)
- Abstract-only sources: M
- Web sources: K
- Providers used: [list]
- Session directory: [path]

## References (Sources Read)
[1] Author, "Title," Venue, Year. [URL/DOI] [academic]
[2] Author, "Title," Venue, Year. [URL/DOI] [preprint]
...

## Further Reading
- Author, "Title," Venue, Year. [URL/DOI] — cited for abstract/metadata only
- ...
```

Source type tags in references: `[academic]`, `[web]`, `[preprint]`, `[github]`, `[reddit]`, `[hn]`.

---

## Paywall Recovery Beyond the Cascade

The download cascade (OpenAlex → Unpaywall → arXiv → PMC → OSF → Anna's Archive → Sci-Hub) handles the common paths automatically. When it still fails — especially in paywall-heavy fields like psychology, education, or medicine — the underlying principle is that **authors often self-archive their work** outside of publisher paywalls:

- **Institutional repositories** — many universities require faculty to deposit preprints or postprints. A web search for `"{author surname}" "{short title}" filetype:pdf` often surfaces these.
- **Author pages** — ResearchGate, Academia.edu, and personal faculty pages frequently host author-uploaded copies.
- **Discipline-specific preprint servers** — the cascade already checks OSF/PsyArXiv and arXiv, but emerging servers (e.g., EdArXiv, SocArXiv, EarthArXiv) may have coverage the cascade doesn't yet include.

When using web search (Exa/tavily) for recovery, the most effective pattern is `"{exact title}" filetype:pdf` — this finds direct PDF links that the DOI-based cascade missed. Fall back to `"{author surname}" "{short title}"` if the exact title returns nothing.

**Citation rules:**
- Only sources with on-disk `.md` content AND reader notes in `notes/` go in **References (Sources Read)**
- Sources known only from abstracts or search metadata go in **Further Reading**
- The Methodology section must honestly report deep reads vs. abstract-only counts (use `${CLAUDE_SKILL_DIR}/state audit` output)
- Never claim to have "deeply read" a source that has `degraded` (unread) or abstract-only content. Sources upgraded to `reader_validated` by `mark-read` can be claimed as deep reads.
