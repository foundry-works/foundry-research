# Adaptive Guardrails & Tool Usage

## Required Dependencies

**Tavily MCP** (`mcp__tavily-mcp__tavily_search`) is an optional but strongly recommended dependency. It provides higher-quality web search with structured extraction and deeper content access than Claude's built-in tools.

**Health check & fallback:** At the start of every research session, Claude should check if Tavily is available by calling `mcp__tavily-mcp__tavily_search` with a trivial test query. If Tavily is unavailable:
- **Fall back to Claude's native `WebSearch` and `WebFetch` tools** for web search. These are always available and require no configuration.
- Inform the user: *"Tavily MCP not configured — using native WebSearch/WebFetch for web results. For better web search quality, consider adding the `tavily-mcp` MCP server."*
- Continue research normally. Native web search is sufficient for most queries; Tavily provides better depth and structured extraction but is not essential.

**Bottom line:** The skill works without Tavily. Tavily makes it better.

## Adaptive Defaults

These are **defaults with rationale**, not hard limits. Claude scales up or down based on query breadth and complexity.

| Parameter | Default | Rationale | When to adjust |
|-----------|---------|-----------|----------------|
| Research questions | 3-7 | Covers most topics | Narrow factual query → 1-2; broad literature review → up to 10 |
| Searches per question | 1-3 | Diminishing returns after 3 | If initial search is comprehensive, stop at 1 |
| Total sources gathered | 15-40 | Comprehensive without overwhelming | Simple query → 5-10; systematic review → 50+ |
| Sources cited in report | 10-25 | Focused evidence base | Scale with report length and topic breadth |
| Search depth (Tavily) | advanced | Better results | Use basic for simple factual lookups |
| Academic results per provider | 5-10 | Good coverage vs noise | Increase for niche topics with few results |

## Tool Usage Reference

| Task | Tool |
|------|------|
| Web search | `mcp__tavily-mcp__tavily_search` (preferred) or native `WebSearch`/`WebFetch` (fallback) |
| Academic search | `./search --provider <name>` |
| Citation traversal | `./search --provider semantic_scholar --cited-by/--references` |
| Paper recommendations | `./search --provider semantic_scholar --recommendations` |
| Author search | `./search --provider semantic_scholar --author` |
| arXiv preprints | `./search --provider arxiv` |
| bioRxiv/medRxiv preprints | `./search --provider biorxiv` |
| PubMed biomedical search | `./search --provider pubmed` |
| MeSH term lookup | `./search --provider pubmed --mesh` |
| Google Scholar discovery | `./search --provider scholar` |
| GitHub repos & code | `./search --provider github` |
| Reddit discussions | `./search --provider reddit` |
| Hacker News discussions | `./search --provider hn` |
| DOI enrichment | `./enrich --doi` |
| Save web content | `./download --url --type web` |
| Download paper PDFs | `./download --doi / --arxiv / --pdf-url` |
| PDF → Markdown | `./download --to-md` |
| Read saved sources | `Read` tool (`.md` files in `sources/`) |
| State tracking | `./state <command>` |
| Save report | `Write` tool |

## Provider Selection Heuristics

These are guidelines, not lookup tables. Claude picks providers based on the query and what it's learned so far.

- **Biomedical / clinical / life science** → PubMed + bioRxiv; add Semantic Scholar for citation context
- **CS / ML / AI** → arXiv + Semantic Scholar; add OpenAlex for breadth
- **Cross-cutting queries** (e.g., "ML for drug safety") → start broad (Semantic Scholar + PubMed), narrow based on results
- **General technical** → Tavily/WebSearch + GitHub; add Reddit/HN for community perspective
- **Need BibTeX / citation exports** → Google Scholar
- **Need implementations / benchmarks** → GitHub
- **Need community opinions / practical experience** → Reddit + HN
- **Latest preprints (last N days)** → arXiv (CS/physics), bioRxiv (bio/med)
- **Well-cited survey papers** → Semantic Scholar or OpenAlex with citation sort

## When to Use What (Detailed)

| Scenario | Provider | Why |
|----------|----------|-----|
| Structured academic search with filters | `semantic_scholar` or `openalex` | Rich APIs with year, field, citation filters |
| Latest preprints in a specific arXiv category | `arxiv` | Real-time, fine-grained category taxonomy |
| Discovery search, don't know exact terms | `scholar` (best-effort) | Scholar's relevance ranking excels at exploration, but may be blocked. Fall back to `semantic_scholar` or `openalex`. |
| Have a DOI, need the PDF | `download.py --doi` | Multi-source cascade finds best copy |
| Citation graph for any paper | `semantic_scholar --cited-by/--references` | Covers all fields |
| Find similar papers | `semantic_scholar --recommendations` | Content + citation similarity |
| Biomedical/clinical with MeSH vocabulary | `pubmed` | 35M+ articles, structured vocabulary |
| Cutting-edge bio/med preprints | `biorxiv` | Weeks-months before PubMed indexing |
| Implementations, tools, datasets | `github` | Repos, code, READMEs |
| Community opinions, practical experiences | `reddit` | Full text + comments |
| Expert technical commentary | `hn` | High-signal discussions |
