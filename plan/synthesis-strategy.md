# Synthesis Strategy

How Claude consumes, compresses, and synthesizes research material within context window constraints.

## The Core Problem

A research session may collect 15-40 sources. Full-text papers are 5,000-30,000 tokens each. Reading all of them sequentially would consume 150K-1.2M tokens — far beyond what's useful even in a large context window. The synthesis strategy must be **token-efficient** without sacrificing accuracy.

## Three-Pass Reading Model

### Pass 1: Triage (metadata only, no file reads)

After searching, Claude has search result snippets, titles, abstracts, and metadata from `state.py summary`. This is enough to:

- Categorize sources by subtopic/research question
- Identify the 5-10 most relevant sources for deep reading
- Identify sources that are likely redundant (similar titles, same authors, overlapping scope)
- Decide which sources need full-text download vs. abstract-only is sufficient

**No file reads in this pass.** Claude works from search result data already in context.

### Pass 2: Selective Deep Reading (targeted file reads)

For high-relevance sources, read strategically — not the entire file:

- **Read the metadata file first** (`sources/metadata/src-NNN.json` — title, abstract, authors, venue, year, citation_count) — this is compact and often sufficient for supporting sources
- **Read the introduction + conclusion** for the core argument and findings
- **Read specific sections** relevant to the research question (e.g., "Methods" for a methodology comparison, "Results" for empirical data)
- **Skip** related work, acknowledgments, appendices, and boilerplate

**Always read the `.toc` file before the `.md` source file.** If `sources/src-001.toc` exists, read it first — it contains heading names with line numbers (e.g., `450\t2\tMethodology`). Use these line numbers to make precise `offset`/`limit` reads of just the sections you need.

**When no `.toc` exists** (common with arXiv preprints compiled from LaTeX, pre-2015 papers, and web sources where PDF conversion couldn't detect headings), use a tiered fallback:

1. **Keyword search:** Use `Grep` to locate section headers or key terms (e.g., "Results", "Discussion", "Conclusion") and read surrounding context with offset/limit.
2. **Chunked sequential reading:** If keyword search fails (garbled text, non-standard section names), read the document in 200-line chunks, starting from the top. After each chunk, decide whether to continue or skip ahead. This is expensive but ensures content isn't missed entirely.
3. **Abstract-only fallback:** If the PDF conversion is severely degraded (`"quality": "degraded"` in `sources/metadata/src-NNN.json`), rely on the abstract from metadata and seek a web version or alternate source for the full text.

Do not assume all sources will have usable `.toc` files — many academic PDFs lack embedded bookmarks.

### Pass 3: Inline Verification (during report writing)

Verify claims **while drafting**, not as a separate post-hoc step. Before writing a factual claim, read the cited source to confirm it. This produces better prose (the claim is written with the evidence fresh in context) and avoids the cost of a separate full-document re-read pass later.

While drafting, go back to specific sources to:

- Confirm exact numbers, quotes, or claims
- Resolve contradictions between sources
- Fill gaps discovered during writing

This is surgical — read 10-30 lines from a specific source to verify a specific claim.

**Separate verification pass (optional, for high-stakes research):** After drafting, a reader subagent can do a "red team" pass — checking for logical leaps, unsupported generalizations, or claims that go beyond what the sources actually say. This is a peer-review function, not basic citation checking (which was already done inline during drafting).

## Intermediate Summaries

For research sessions with 20+ sources, Claude should create **working notes** before attempting the final report. These are not shown to the user — they're Claude's scratch space.

### Per-Source Summaries

After reading a key source, write a 3-5 line summary capturing:
- Core finding/argument
- Key data points or evidence
- How it relates to the research question
- Any contradictions with other sources

For small sessions, hold these in reasoning. For larger sessions, reader subagents write summaries to `notes/src-NNN.md` files automatically (see delegation strategy). You can also append key observations to `journal.md`.

### Thematic Grouping

Before synthesizing, organize sources by theme/subtopic rather than by order discovered. This prevents the report from reading like "source 1 says X, source 2 says Y" and instead produces genuine synthesis: "Three studies converge on X [1][3][7], while two others argue Y [4][9]."

## Context Window Budget

Rough token allocation for a typical research session:

| Activity | Token budget | Notes |
|----------|-------------|-------|
| Search results (in context) | ~10K | Snippets from search.py output |
| Source metadata (state summary) | ~3K | Compact source index |
| Deep reads (5-10 sources) | ~30-50K | Selective sections, not full text |
| Verification reads | ~5-10K | Surgical reads during writing |
| Report drafting | ~5-10K | The output itself |
| **Total reading budget** | **~50-80K** | Leaves room for reasoning |

This means Claude should **not** attempt to read more than ~10 sources in full. For the remaining sources, abstracts and metadata are sufficient for supporting citations.

## Handling Contradictions

When sources disagree:

1. **Note the contradiction explicitly** in the report — don't silently pick one side
2. **Check source quality asymmetry** — is one source a peer-reviewed meta-analysis and the other a blog post? Say so
3. **Check recency** — newer evidence may supersede older findings
4. **Check methodology** — different methods can explain different results
5. **Present both sides** with appropriate weight, citing specific sources for each position

## Multi-Conversation Sessions

When a research session is resumed in a new conversation:

1. Run `./state summary` to reload the source index and search history
2. Read `journal.md` (contains intermediate reasoning, decisions, and contradictions from prior conversations)
3. Scan `notes/` directory for per-source summaries written by reader subagents
4. Read `report.md` if it exists (may be a partial draft)
5. Claude now has enough context to continue without re-reading all sources

This is why `state.py` tracks findings and research brief, and why `journal.md` and `notes/` exist on disk — they bridge the gap between conversations.

## Anti-Patterns

- **Don't read all sources before writing anything.** Start writing after the first pass of deep reading. Gaps discovered during writing drive targeted follow-up.
- **Don't synthesize from search snippets alone.** Snippets are for triage. Claims in the report must be verified against downloaded source files.
- **Don't treat all sources equally.** A highly-cited systematic review deserves a full read. A tangentially-related blog post needs only its abstract.
- **Don't re-read sources you've already summarized.** Use your notes or memory from earlier in the conversation.
- **Don't write the report section by section in source order.** Organize by theme, not by discovery order.
