# SKILL.md Specification

The skill prompt should be ~200 lines, capabilities-based (not phase-based). It describes what good research looks like and provides a tool reference card. Claude uses its judgment to decide what to do and when.

## Target: ~230 lines, 8 sections

---

### Section 1: Purpose & Activation (~10 lines)

**When to activate:** User asks for deep research, literature review, systematic investigation, or any question that requires multiple sources and synthesis.

**What it produces:** A structured research report backed by on-disk sources (`.md` files with YAML metadata + PDFs when available), saved in a session directory.

**Key principle:** You are the reasoning engine. Use the tools below to search, download, and track sources. Trust your judgment on what to search, when to stop, and how to synthesize.

---

### Section 2: Tools Available (~60 lines)

Compact reference card format. For each tool, show the most common invocation patterns.

```
## Search (search.py --provider <name>)

| Provider | Best for | Key flags |
|----------|----------|-----------|
| semantic_scholar | Academic search, citations, recommendations | --cited-by, --references, --recommendations, --author |
| openalex | Broad academic, OA filtering | --open-access-only, --year-range |
| arxiv | Latest CS/physics preprints | --categories, --days, --download |
| pubmed | Biomedical, clinical, MeSH | --type, --cited-by, --references, --mesh |
| biorxiv | Bio/med preprints | --server, --days, --category |
| scholar | Discovery search, BibTeX | --format, --parse |
| github | Repos, code, implementations | --type, --min-stars, --repo |
| reddit | Community discussion | --subreddits, --post-url |
| hn | Technical commentary | --story-id, --tags |

Common: --query "..." --limit N --offset N --session-dir DIR

## Download (download.py)
--url URL --type web          # web content
--doi DOI --to-md             # PDF cascade by DOI
--arxiv ID --to-md            # arXiv PDF
--pdf-url URL --to-md         # direct PDF
--local-dir DIR --to-md       # ingest existing PDFs from a local folder

## Enrich (enrich.py)
--doi DOI [--doi DOI2 ...]    # Crossref metadata

## State (./state) — structured operations with logic
init --query "..."            # start session (creates state.db, journal.md, notes/, sources/)
set-brief --from-json FILE    # save research brief + questions
log-search --provider X ...   # prevent re-searching
add-source --from-json FILE   # dedup + track (single source)
add-sources --from-json FILE  # batch dedup + insert (preferred after search — one call for all results)
check-dup --doi/--url/--title # check before downloading
check-dup-batch --from-json   # batch dedup check
log-finding --text "..." --sources "src-001,src-003" --question "Q1"  # brief text only
log-gap --text "..."          # record coverage gap (brief text only)
resolve-gap --gap-id "gap-1"  # mark gap resolved
get-source --id src-003       # get source metadata
update-source --id src-003 --from-json FILE  # update metadata fields
searches                      # list all searches
sources                       # list all sources
summary                       # brief + sources + findings + gaps

IMPORTANT: All JSON payloads must be passed via --from-json FILE. Write JSON to a temp file first,
then pass the path. There is no --json flag — inline JSON breaks on special characters in titles/abstracts.

## Native tools — use for prose content
Tavily search, WebSearch      # web search
Read                          # read source files, notes, journal
Write / Edit                  # journal.md (reasoning scratchpad), notes/, report.md
```

---

### Section 3: What Good Research Looks Like (~60 lines)

Brief prose guidance, not a checklist:

**Starting**
- **Start with a research brief:** Transform the raw query into a structured brief — scope, key aspects, what a complete answer looks like. Save it with `state.py set-brief`. This sharpens every subsequent search.
- **Decompose into research questions:** Break the brief into 3-7 concrete questions. These drive your search strategy and become report sections. Save with `state.py set-brief`.

**Searching**
- **Search iteratively:** Start broad, then refine based on what you find. Don't plan all searches upfront — discovery is iterative.
- **Use multiple providers:** No single source covers everything. Cross-reference academic and web sources.
- **Know when to search more:** After each search round, assess: Are any research questions still unanswered? Did results reveal an important subtopic you hadn't considered? Are you seeing the same papers repeatedly (saturation)? If yes/yes/yes → stop. If gaps remain → search again with refined queries or different providers.

**Reading & Downloading**
- **Download before synthesizing:** Save sources to disk so you can verify claims against the exact content later. Don't synthesize from search result snippets alone.
- **Read selectively:** Don't read every source cover-to-cover. Read the metadata file first (`sources/metadata/src-NNN.json` — abstract, authors, venue, citations). Deep-read only the 5-10 most relevant sources. For those, focus on intro + results + conclusion, skip related work and boilerplate.
- **Read `.toc` before `.md`:** For PDF-converted sources, always read the `.toc` file first (e.g., `sources/src-001.toc`). It lists headings with line numbers so you can jump directly to Methods, Results, etc. with precise `offset`/`limit` reads. If no `.toc` exists (common with arXiv/LaTeX papers and older publications), fall back to `Grep` for keyword-based section location (search for "Results", "Discussion", etc.), then chunked sequential reading (200-line blocks) if keywords miss. For severely degraded conversions (quality: "degraded" in YAML), rely on the abstract and seek alternate sources.
- **Enrich important papers:** Use `enrich.py` for key papers to fill venue, authors, retraction status.

**Thinking & Reasoning**
- **Use journal.md as your scratchpad:** Append intermediate thoughts, emerging patterns, contradictions, and strategy decisions to `journal.md`. This prevents you from losing reasoning when context compresses and makes your thinking auditable. Write freely — it's append-only, not polished prose.
- **Read notes/ for source summaries:** When reader subagents have summarized sources, read the relevant `notes/src-NNN.md` files rather than re-reading full source texts.

**Synthesizing**
- **Organize by theme, not by source:** Group findings across sources by research question. Don't write "Source 1 says X, Source 2 says Y" — write "Three studies converge on X [1][3][7]."
- **NEVER write a claim without reading the source:** Before making any factual claim in the report, open and read the corresponding downloaded `.md` file to confirm the claim matches the actual content. Do not rely on search result snippets, abstracts, or your pre-trained knowledge. If you cannot verify a claim against an on-disk source, either find a source or drop the claim.
- **Be wary of garbled PDF conversions:** Converted PDFs may have scrambled text, especially around tables, figures, equations, and two-column layouts. Check `sources/metadata/src-NNN.json` for `"quality": "degraded"` — this means the conversion is unreliable. If source text looks garbled or nonsensical, do not interpret it — note the limitation and look for the same information in the abstract, a different source, or a web version of the paper.
- **Flag contradictions explicitly:** When sources disagree, present both sides with context (methodology differences, recency, evidence quality). Don't silently pick one.
- **Cite everything:** Every factual claim should reference a specific source. Use inline citations like [1], [2].

**Knowing When You're Done**
- **Saturation signal:** New searches return papers you've already collected → you've covered the space.
- **Coverage check:** Every research question from your brief has at least 2-3 supporting sources.
- **Diminishing returns:** Additional searches yield tangentially relevant results rather than core material.
- **Don't over-research simple questions.** A factual lookup needs 3-5 sources, not 30. Scale effort to query complexity.
- **Record your assessment:** Use `state.py log-finding` to track key findings and `state.py log-gap` for known gaps. These persist across conversations.

---

### Section 4: Provider Selection Guidance (~30 lines)

Heuristics in prose, not lookup tables:

- Biomedical → PubMed + bioRxiv; add Semantic Scholar for citation context
- CS/ML → arXiv + Semantic Scholar; add OpenAlex for breadth
- Cross-cutting queries → start broad, narrow based on results
- General technical → Tavily/WebSearch + GitHub; Reddit/HN for community perspective
- Need implementations/benchmarks → GitHub
- Latest preprints → arXiv (CS/physics), bioRxiv (bio/med)
- Well-cited surveys → Semantic Scholar or OpenAlex with citation sort
- Use your judgment for queries that don't fit neatly into one domain
- Google Scholar is **best-effort** — it aggressively blocks scrapers. If Scholar fails, fall back to Semantic Scholar or OpenAlex. Don't retry Scholar more than once per session.

---

### Section 5: Session Structure (~15 lines)

```
./deep-research-{session}/
├── state.db            # SQLite — search history + source index (source of truth)
├── journal.md          # Your reasoning scratchpad (append-only)
├── report.md           # Final report
├── notes/              # Per-source summaries (from reader subagents)
│   └── src-001.md      # Summary of src-001
└── sources/
    ├── metadata/       # JSON metadata files (machine-owned)
    │   └── src-001.json
    ├── src-001.md      # Pure markdown content (no frontmatter)
    ├── src-001.pdf     # PDF when available
    └── ...
```

- Initialize with `state.py init`
- Log searches with `state.py log-search`
- Track sources with `state.py add-source` (single) or `state.py add-sources --from-json` (batch, preferred)
- Check duplicates with `state.py check-dup` (single) or `state.py check-dup-batch --from-json` (batch)
- Export debug snapshot with `state.py export` (generates `state.json` for human inspection)

---

### Section 6: Delegation (~20 lines)

You are the supervisor. Run structured CLI commands (`./search`, `./download`, `./enrich`, `./state`) directly — no subagent needed for JSON output. Use **parallel Bash calls** (multiple Bash tool calls in one response) for simultaneous searches across different providers.

Use the **Agent tool** to spawn Sonnet subagents only for **unstructured text comprehension** — tasks where reading full paper text would bloat your context:

- **Source summarization:** Reader subagent reads full papers, writes summaries to `notes/`, returns a tiny manifest.
- **Claim verification:** Subagent checks draft claims against source files, returns a verification table.
- **Relevance assessment:** Subagent deep-reads a batch of sources and rates relevance.

**Keep in your context:** Research brief, search strategy, coverage assessment, contradiction analysis, synthesis, report writing, user interaction, and all CLI output parsing.

Give workers a clear directive with the session directory path. They write results to `notes/` on disk and return compressed manifests — not full text.

For small research sessions (< 10 sources), do everything inline. Delegation is a scaling strategy, not a requirement.

---

### Section 7: Adaptive Guardrails (~20 lines)

Defaults with rationale — scale based on query:

| Parameter | Default | Scale down | Scale up |
|-----------|---------|------------|----------|
| Research questions | 3-7 | Simple factual → 1-2 | Broad review → up to 10 |
| Searches per question | 1-3 | Comprehensive initial results → 1 | Niche topic → 3+ |
| Total sources | 15-40 | Simple query → 5-10 | Systematic review → 50+ |
| Sources cited | 10-25 | Scale with report length | |

Don't over-research simple questions. Don't under-research complex ones.

---

### Section 8: Output Format (~25 lines)

Report template:

```markdown
# [Research Topic]

## Key Findings
- Finding 1 [1][2]
- Finding 2 [3]
- ...

## [Topic-appropriate sections]
### [Section based on research questions]
...

## Methodology
- Sources examined: N
- Providers used: [list]
- Session directory: [path]

## References
[1] Author, "Title," Venue, Year. [URL/DOI]
[2] Author, "Title," Venue, Year. [URL/DOI]
...
```

Source type tags in references: `[academic]`, `[web]`, `[preprint]`, `[github]`, `[reddit]`, `[hn]`.

Every cited source must have a corresponding `.md` file in the session's `sources/` directory.

---

## What's NOT in the Prompt

- Fixed phase sequence (BRIEF → DECOMPOSE → INVESTIGATE → SYNTHESIZE → VERIFY)
- Domain taxonomy with provider lookup tables
- Credibility scoring formulas or venue tier lists
- Formal curation pass
- Fixed numeric limits
- Step-by-step procedure

Claude is trusted to exercise judgment. The prompt describes *capabilities and principles*, not a *procedure*.
