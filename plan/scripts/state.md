# `state.py` — Session State Tracker

**Purpose:** Track search history, source index, research brief, key findings, and known gaps. Provides continuity across conversations — when Claude resumes a session, `summary` gives it enough context to pick up where it left off without re-reading every source.

## CLI Interface

```bash
# Initialize session state
python state.py init --query "original research query" --session-dir ./deep-research-{session}

# Save research brief and questions (persists across conversations)
python state.py set-brief \
  --from-json brief.json \
  --session-dir ./deep-research-{session}

# Log a search (prevent re-running the same query)
python state.py log-search \
  --provider semantic_scholar --query "transformer efficiency" \
  --result-count 8 --session-dir ./deep-research-{session}

# Add a source (with dedup check)
python state.py add-source \
  --from-json source.json \
  --session-dir ./deep-research-{session}

# Batch add sources (dedup + insert in one call — avoids 10+ sequential CLI invocations)
python state.py add-sources \
  --from-json results.json \
  --session-dir ./deep-research-{session}
# Input: JSON array of source objects (same schema as add-source --json)
# Output: {"added": [{"id": "src-005", "title": "..."}], "duplicates": [{"title": "...", "matched": "src-001"}], "errors": []}

# Check if a source is a duplicate (before downloading)
python state.py check-dup \
  --doi "10.1234/foo" --session-dir ./deep-research-{session}

python state.py check-dup \
  --url "https://example.com/article" --session-dir ./deep-research-{session}

python state.py check-dup \
  --title "Attention Is All You Need" --session-dir ./deep-research-{session}

# Batch dedup check (check multiple sources in one call)
python state.py check-dup-batch \
  --from-json candidates.json \
  --session-dir ./deep-research-{session}
# Input: JSON array of {doi?, url?, title?} objects
# Output: [{"index": 0, "is_dup": true, "matched": "src-001"}, {"index": 1, "is_dup": false, "matched": null}, ...]

# Log a key finding (structured tracking — brief text only, not full prose)
python state.py log-finding \
  --text "Quantization to INT8 preserves >99% accuracy above 6B params" \
  --sources "src-003,src-007" \
  --question "Q2" \
  --session-dir ./deep-research-{session}

# Log a known gap (structured tracking — brief text only)
python state.py log-gap \
  --text "No sources on inference cost comparison" \
  --question "Q3" \
  --session-dir ./deep-research-{session}

# Mark a gap as resolved
python state.py resolve-gap \
  --gap-id "gap-1" --session-dir ./deep-research-{session}

# List all searches performed
python state.py searches --session-dir ./deep-research-{session}

# List all sources collected
python state.py sources --session-dir ./deep-research-{session}

# Get a single source's metadata by ID
python state.py get-source --id src-003 --session-dir ./deep-research-{session}

# Update a source's metadata (e.g., after enrichment fills missing fields)
python state.py update-source \
  --id src-003 --from-json update.json \
  --session-dir ./deep-research-{session}

# Get compact summary for Claude's context (includes brief, findings, gaps)
python state.py summary --session-dir ./deep-research-{session}
```

## State File

`./deep-research-{session}/state.db` (SQLite, source of truth). The schema below shows the logical structure. A `state.py export` command generates a read-only `state.json` snapshot for human debugging:

```json
{
  "session_id": "dr-20260307-143022",
  "query": "original research query",
  "created_at": "2026-03-07T14:30:22Z",
  "brief": {
    "scope": "Compare transformer efficiency techniques for models >10B parameters",
    "questions": [
      "Q1: What are the main approaches to efficient inference?",
      "Q2: How do they compare on latency vs. accuracy tradeoffs?",
      "Q3: What are the infrastructure cost implications?"
    ],
    "completeness_criteria": "Each question answered with 2+ academic sources and 1+ benchmark"
  },
  "searches": [
    {
      "id": "search-1",
      "provider": "semantic_scholar",
      "query": "transformer efficiency",
      "result_count": 8,
      "timestamp": "2026-03-07T14:31:00Z"
    }
  ],
  "sources": [
    {
      "id": "src-001",
      "title": "Attention Is All You Need",
      "url": "https://arxiv.org/abs/1706.03762",
      "doi": "10.48550/arXiv.1706.03762",
      "type": "academic",
      "provider": "semantic_scholar",
      "content_file": "sources/src-001.md",
      "pdf_file": "sources/src-001.pdf",
      "added_at": "2026-03-07T14:32:00Z"
    }
  ],
  "findings": [
    {
      "id": "finding-1",
      "text": "Quantization to INT8 preserves >99% accuracy for models above 6B parameters",
      "sources": ["src-003", "src-007"],
      "question": "Q1",
      "timestamp": "2026-03-07T14:45:00Z"
    }
  ],
  "gaps": [
    {
      "id": "gap-1",
      "text": "No sources found comparing inference cost across cloud providers",
      "question": "Q3",
      "status": "open",
      "timestamp": "2026-03-07T14:50:00Z"
    }
  ],
  "stats": {
    "total_searches": 5,
    "total_sources": 12,
    "sources_by_type": {"academic": 8, "web": 3, "reddit": 1},
    "sources_by_provider": {"semantic_scholar": 4, "openalex": 2, "pubmed": 2, "reddit": 1, "web": 3}
  }
}
```

## Deduplication Logic (consolidated from `_shared/dedup.py`)

Three-tier dedup on `add-source`:

1. **Exact DOI match:** Normalized DOI via `_shared/doi_utils.py`
2. **Exact URL match:** Canonicalized URL via `_shared/doi_utils.canonicalize_url()` — strips trailing slash, fragment, query params, plus domain-specific normalization (arXiv abs/pdf, bioRxiv version suffixes, PMC path variants, doi.org resolver URLs)
3. **Fuzzy title match:** Simple token-overlap similarity (threshold 0.85). Handles case differences, punctuation, minor word variations. No ML dependencies. **Minimum title length: 15 characters** — skip fuzzy matching for short/generic titles like "Introduction", "Editorial", or "Review" to avoid false positives.
   - **Gray zone handling (0.85–0.95 similarity):** When title similarity falls in this range, additionally check author list overlap (≥50% shared authors) and year match (same year ±1). Both must pass to declare a duplicate. This prevents false positives on paper series ("V1" vs "V2", "Part 1" vs "Part 2") and similarly-titled papers by different groups.
   - **High confidence (>0.95 similarity):** Title match alone is sufficient — near-identical titles are almost always the same paper.

```python
def dedup_by_doi(papers: list[dict]) -> list[dict]:
    """Deduplicate papers by normalized DOI. Merges metadata from duplicates."""

def dedup_by_title(papers: list[dict], threshold: float = 0.85) -> list[dict]:
    """Fuzzy title dedup for papers without DOIs. Token-overlap similarity."""

def is_duplicate(paper: dict, existing: list[dict]) -> tuple[bool, str | None]:
    """Check if a single paper is a duplicate. Returns (is_dup, matched_id)."""
```

When a duplicate is detected, `add-source` returns the existing source ID instead of adding a new entry.

## Commands

| Command | Purpose |
|---------|---------|
| `init` | Create state.db, empty journal.md, and notes/ + sources/ directories |
| `export` | Generate a read-only `state.json` snapshot from state.db (for human debugging) |
| `set-brief` | Save research brief (scope, questions, completeness criteria) |
| `log-search` | Record a search query + provider (prevents re-running identical searches) |
| `add-source` | Add source with dedup check, auto-assign ID (src-NNN), return ID |
| `add-sources` | Batch add: accepts JSON array, dedup + insert all in one call, returns manifest |
| `check-dup` | Check if DOI/URL/title already exists (returns matched source ID or null) |
| `check-dup-batch` | Batch dedup: accepts JSON array, returns per-item dup status |
| `log-finding` | Record a key finding with supporting source IDs and linked question |
| `log-gap` | Record a coverage gap (drives further searching) |
| `resolve-gap` | Mark a gap as resolved |
| `searches` | List all searches performed |
| `sources` | List all sources collected |
| `get-source` | Get a single source's full metadata by ID |
| `update-source` | Update a source's metadata fields (merge, don't overwrite unspecified fields) |
| `summary` | Compact text summary for Claude's context window (includes brief, findings, gaps) |

## Financial Metrics Tracking (Phase 2)

When used with the `yfinance` or `edgar` providers, `state.py` tracks quantitative financial data to prevent redundant API calls during long sessions.

### CLI Commands

```bash
# Log a financial metric
python state.py log-metric \
  --ticker AAPL --metric "Trailing P/E" --value "32.5" \
  --source yfinance --session-dir ./deep-research-{session}

# Log multiple metrics from a profile pull
python state.py log-metrics \
  --from-json metrics.json \
  --session-dir ./deep-research-{session}
# Input: [{"ticker": "AAPL", "metric": "Market Cap", "value": "3200000000000", "source": "yfinance"}, ...]

# Retrieve metrics for a ticker
python state.py get-metrics \
  --ticker AAPL --session-dir ./deep-research-{session}

# Retrieve a specific metric across tickers (for comparison)
python state.py get-metric \
  --metric "Trailing P/E" --session-dir ./deep-research-{session}
```

### Schema

New SQLite table `metrics`:

```sql
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    metric TEXT NOT NULL,
    value TEXT NOT NULL,          -- stored as text; numeric parsing is Claude's job
    unit TEXT DEFAULT 'USD',      -- USD, ratio, percent, count
    period TEXT,                  -- e.g. "FY2025", "Q3 2025", "TTM", null for spot values
    source TEXT NOT NULL,         -- "yfinance", "edgar", "manual"
    filed_date TEXT,              -- for EDGAR: filing date of the source document
    logged_at TEXT NOT NULL,      -- ISO 8601 timestamp
    UNIQUE(ticker, metric, period, source)  -- prevent duplicate entries
);
```

### Design Decisions

- **Values stored as text:** Financial metrics include ratios (32.5), large integers (3200000000000), percentages (0.554), and text ("buy"). Storing as text avoids precision loss and type coercion issues. Claude interprets them in context.
- **UNIQUE constraint on (ticker, metric, period, source):** Re-logging a metric from the same source for the same period updates the existing row (via `INSERT OR REPLACE`). This prevents stale data accumulation while allowing different sources to provide the same metric for cross-reference.
- **`period` field:** Distinguishes TTM (trailing twelve months) values from specific fiscal periods. Spot values like current price use `period = NULL`.
- **`get-metric` across tickers:** Enables sector comparison screens (e.g., "show me Trailing P/E for TSLA, F, GM") without re-fetching.

### Output in `summary`

When metrics exist, the `summary` command appends a metrics section:

```
=== Metrics ===
AAPL: Market Cap=$3.2T, Trailing P/E=32.5, Profit Margin=26.4% (yfinance)
MSFT: Market Cap=$3.1T, Trailing P/E=35.1, Profit Margin=35.0% (yfinance)
TSLA: Revenue FY2025=$97B, Net Income FY2025=$7.1B (edgar)
```

## CLI vs. Direct File Editing

`state.py` handles operations that require **logic** (deduplication, ID generation, search-log matching, summary aggregation). It is not a general-purpose state store for prose content.

| Use `state.py` CLI for | Use Claude's native Read/Write/Edit for |
|------------------------|----------------------------------------|
| `init`, `set-brief` — session setup | `journal.md` — intermediate reasoning, contradictions, strategy decisions |
| `add-source`, `check-dup` — dedup logic | `notes/src-NNN.md` — per-source summaries and analysis |
| `log-search` — prevent re-running searches | `report.md` — final synthesis |
| `log-finding` — brief structured findings (1-2 sentences) | Extended analysis, detailed evidence discussion |
| `log-gap`, `resolve-gap` — gap tracking | |
| `get-source`, `update-source` — metadata ops | |
| `searches`, `sources`, `summary` — queries | |

**Why this split:** LLMs are prone to shell escaping errors when passing long, nuanced text through CLI arguments. Claude's native file tools (`Write`, `Edit`) handle prose reliably. Reserve CLI for structured, short-value operations where the logic (dedup, ID assignment, validation) justifies the Python wrapper.

### JSON Payload Policy: `--from-json` Only

**`state.py` does not accept inline `--json` arguments.** All JSON payloads must be passed via `--from-json FILE`. There is no `--json` flag.

**Why:** Abstract texts, paper titles, and author names routinely contain single quotes, double quotes, backslashes, parentheses, and Unicode characters that break bash argument parsing. If given the option to use inline JSON, LLMs will attempt it and eventually produce a shell escaping error that corrupts the command. Removing the option entirely eliminates this failure class.

**Workflow:**
1. Claude uses the Write tool to create a temporary JSON file (e.g., `/tmp/source.json`)
2. Claude runs the CLI command with `--from-json /tmp/source.json`
3. The JSON is parsed safely by Python's `json.load()`, not by bash

```bash
# Correct: all structured data via file
python state.py add-source --from-json /tmp/source.json --session-dir ./deep-research-{session}
python state.py set-brief --from-json /tmp/brief.json --session-dir ./deep-research-{session}
python state.py update-source --id src-003 --from-json /tmp/update.json --session-dir ./deep-research-{session}

# Simple scalar flags are fine inline (no JSON, no special characters):
python state.py log-search --provider semantic_scholar --query "transformer efficiency" --result-count 8 --session-dir ...
python state.py log-finding --text "INT8 preserves accuracy above 6B params" --sources "src-003,src-007" --question "Q2" --session-dir ...
```

Commands that accept `--from-json`: `set-brief`, `add-source`, `add-sources`, `update-source`, `check-dup-batch`, `log-metrics`.

## What's Tracked vs. Not

**Tracked** (persists across conversations):
- Research brief (scope, questions, completeness criteria)
- Search history (prevents re-running identical searches)
- Source index (prevents duplicate downloads)
- Key findings (with source citations and linked questions)
- Known gaps (with open/resolved status)

**Not tracked** (Claude's judgment, per-conversation):
- Credibility assessments
- Source ranking/prioritization
- Synthesis structure decisions
- Contradiction analysis details

## Implementation Details

- Auto-generates IDs: `src-001`, `src-002`, etc.
- Auto-assigns citation numbers sequentially
- **SQLite-backed state:** All state is stored in `{session_dir}/state.db`. SQLite handles concurrent read/write access natively via WAL mode (`PRAGMA journal_mode=WAL`) and busy timeout (`PRAGMA busy_timeout=20000`). This eliminates manual `fcntl.flock()`, stale lock recovery, and exponential backoff — SQLite's built-in locking is robust across platforms (Unix, Windows, WSL, Docker, NFS). The `summary` command outputs human-readable text from SQLite. The `export` command generates a read-only `state.json` snapshot for human debugging/inspection — no script ever reads from `state.json`; it exists purely for humans to inspect session state with `jq` or a text editor. Read-only commands (`searches`, `sources`, `get-source`, `summary`) use a shared (non-exclusive) lock to avoid reading mid-write.
- `summary` outputs a compact text block for Claude: search count, source count by type, list of source titles with IDs

## Dependencies

`_shared/` (config, output, doi_utils) + stdlib only (`json`, `argparse`, `datetime`).
