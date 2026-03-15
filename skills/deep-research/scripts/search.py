#!/usr/bin/env python3
"""Unified search CLI — routes queries to provider-specific modules."""

import argparse
import json
import os
import sys

# Add parent directory so _shared imports work when run from any location
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shared.config import _discover_session_dir_from_marker  # noqa: E402
from _shared.output import error_response, log, set_quiet  # noqa: E402
from _shared.state_client import call_state  # noqa: E402
from providers import available_providers, get_provider  # noqa: E402

# Flags that substitute for --query (provider -> set of flag dest names)
_IDENTIFIER_FLAGS = {
    "semantic_scholar": {"cited_by", "references", "recommendations", "author"},
    "openalex": {"cited_by", "references"},
    "reddit": {"post_url", "post_id", "browse"},
    "hn": {"story_id"},
    "biorxiv": {"doi", "list_categories"},
    "pubmed": {"fetch_pmids"},
    "edgar": {"ticker", "accession"},
    "yfinance": {"ticker"},
    "arxiv": {"list_categories"},
    "crossref": {"doi"},
    "core": {"core_id"},
    "tavily": {"urls"},
    "opencitations": {"cited_by", "references"},
    "dblp": {"author", "venue"},
}


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with common flags only."""
    parser = argparse.ArgumentParser(
        description="Unified search CLI — routes to provider-specific modules.",
        add_help=True,
    )
    parser.add_argument(
        "--provider", required=True, choices=available_providers(),
        help="Search provider to use",
    )
    parser.add_argument("--query", default=None, help="Search query")
    parser.add_argument("--limit", "--max-results", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N results (default: 0)")
    parser.add_argument("--session-dir", default=None, help="Session directory for state integration")
    parser.add_argument("--quiet", action="store_true", help="Suppress stderr log output")
    parser.add_argument("--compact", action="store_true",
                        help="Return only (id, title, citation_count, doi, provider) per result — strips abstracts and full metadata")
    parser.add_argument("--search-type", default="manual",
                        choices=["manual", "recovery", "citation", "gap_search"],
                        help="Search type for state tracking (default: manual)")
    parser.add_argument("--brief-keywords", default=None,
                        help="Comma-separated domain terms from the research brief for title-relevance scoring at ingestion")
    return parser


def _has_identifier_flag(provider: str, extra_args: list[str]) -> bool:
    """Check if extra_args contain an identifier flag that substitutes for --query."""
    flags = _IDENTIFIER_FLAGS.get(provider, set())
    if not flags:
        return False
    for arg in extra_args:
        if arg.startswith("--"):
            dest = arg.lstrip("-").replace("-", "_").split("=")[0]
            if dest in flags:
                return True
    return False


def main() -> None:
    parser = _build_parser()
    args, extra_args = parser.parse_known_args()

    if args.quiet:
        set_quiet(True)

    provider = args.provider

    # Treat empty/whitespace-only query the same as missing
    if args.query is not None and args.query.strip() == "":
        args.query = None

    # Validate that --query or an identifier flag is present
    if args.query is None and not _has_identifier_flag(provider, extra_args):
        id_flags = _IDENTIFIER_FLAGS.get(provider, set())
        if id_flags:
            flag_list = ", ".join(f"--{f.replace('_', '-')}" for f in sorted(id_flags))
            error_response(
                [f"--query is required for {provider} (or use one of: {flag_list})"],
                error_code="missing_query",
            )
        else:
            error_response(
                [f"--query is required for {provider}"],
                error_code="missing_query",
            )

    # Load provider module
    try:
        mod = get_provider(provider)
    except ImportError as e:
        error_response(
            [f"Provider module for '{provider}' not found: {e}"],
            error_code="provider_not_found",
        )
        return  # unreachable (error_response exits), but satisfies type checker

    # Provider must export a search() function
    if not hasattr(mod, "search"):
        error_response(
            [f"Provider module for '{provider}' has no search() function"],
            error_code="provider_invalid",
        )
        return

    # Build the full argument namespace for the provider
    # Provider modules define add_arguments(parser) to register their flags
    if hasattr(mod, "add_arguments"):
        mod.add_arguments(parser)
        args = parser.parse_args()
    elif extra_args:
        log(f"Provider '{provider}' does not define add_arguments(); ignoring extra flags: {extra_args}", level="warn")

    # Call provider search (prints JSON to stdout and returns JSON string)
    log(f"Searching {provider}" + (f" for: {args.query}" if args.query else ""))

    compact = getattr(args, "compact", False)
    if compact:
        # Capture stdout so we can replace the full output with a compact version
        import io
        old_stdout = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf  # type: ignore[assignment]

    result_str = mod.search(args)

    if compact:
        captured = buf.getvalue()
        sys.stdout = old_stdout
        # Parse the captured output to strip it down
        try:
            full = json.loads(captured)
            if full.get("status") == "ok":
                _COMPACT_FIELDS = {"id", "title", "citation_count", "doi", "provider", "year", "type"}
                results = full.get("results", [])
                if isinstance(results, list):
                    full["results"] = [
                        {k: v for k, v in item.items() if k in _COMPACT_FIELDS}
                        for item in results
                    ]
                print(json.dumps(full, ensure_ascii=False))
            else:
                print(captured, end="")
        except (json.JSONDecodeError, TypeError):
            print(captured, end="")

    # Parse result back into dict for state integration (use full data, not compact)
    result = None
    if isinstance(result_str, str):
        try:
            result = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(result_str, dict):
        result = result_str

    if not result or result.get("status") != "ok":
        return

    # Auto-discover session dir if not explicitly provided
    if not args.session_dir:
        args.session_dir = _discover_session_dir_from_marker() or os.environ.get("DEEP_RESEARCH_SESSION_DIR")

    if not args.session_dir:
        return

    # Detect search mode from provider-specific flags
    search_mode = _detect_search_mode(provider, args)

    # Log search to session state
    _log_search_to_state(args, result, search_mode)

    # Auto-add sources to session state
    _add_sources_to_state(args, result)

    # Auto-append structured journal entry
    _append_journal_entry(args, result, search_mode)


def _detect_search_mode(provider: str, args) -> str:
    """Detect the search mode from provider-specific flags."""
    id_flags = _IDENTIFIER_FLAGS.get(provider, set())
    for flag in id_flags:
        val = getattr(args, flag, None)
        if val is not None and val is not False:
            # Map flag names to canonical search modes
            mode_map = {
                "cited_by": "cited_by",
                "references": "references",
                "recommendations": "recommendations",
                "author": "author",
                "post_url": "browse",
                "post_id": "browse",
                "browse": "browse",
                "story_id": "browse",
                "fetch_pmids": "fetch",
                "list_categories": "browse",
                "doi": "fetch",
                "core_id": "fetch",
                "urls": "fetch",
                "accession": "fetch",
                "venue": "browse",
            }
            return mode_map.get(flag, "keyword")
    return "keyword"


def _log_search_to_state(args, result: dict, search_mode: str) -> None:
    """Log the search to session state via state.py."""
    ingested_count = len(result.get("results", []))
    search_type = getattr(args, "search_type", "manual") or "manual"

    # For citation traversals, construct a query string that includes the mode
    # and seed paper identifier so each traversal is uniquely identifiable.
    query = args.query or ""
    if search_mode in ("cited_by", "references") and not query:
        # Extract the identifier from provider-specific flags
        identifier = (
            getattr(args, "cited_by", None)
            or getattr(args, "references", None)
            or ""
        )
        if identifier:
            query = f"{search_mode}:{identifier}"
    elif search_mode in ("cited_by", "references") and query:
        # Even when query is set, prefix with mode for uniqueness
        if not query.startswith(f"{search_mode}:"):
            query = f"{search_mode}:{query}"

    resp = call_state(
        args.session_dir, "log-search",
        args=[
            "--provider", args.provider,
            "--query", query,
            "--search-mode", search_mode,
            "--search-type", search_type,
            "--result-count", str(ingested_count),
            "--ingested-count", str(ingested_count),
        ],
        timeout=5,
    )
    if resp is not None:
        log(f"Search logged to state (provider={args.provider}, mode={search_mode})")


def _add_sources_to_state(args, result: dict) -> None:
    """Auto-add search results as sources to session state via state.py."""
    results = result.get("results")
    if not isinstance(results, list) or not results:
        return

    # Filter to items that look like citable sources (have title)
    sources = []
    for item in results:
        if isinstance(item, dict) and item.get("title"):
            sources.append(item)

    if not sources:
        return

    # Compute title-keyword relevance scores when brief keywords are provided
    brief_kw = getattr(args, "brief_keywords", None)
    if brief_kw:
        terms = [t.strip().lower() for t in brief_kw.split(",") if t.strip()]
        if terms:
            for src in sources:
                title_lower = (src.get("title") or "").lower()
                hits = sum(1 for t in terms if t in title_lower)
                src["relevance_score"] = round(min(hits / max(len(terms), 1), 1.0), 3)
                # Mark zero-relevance sources so they're excluded from triage and
                # download queues while preserving their record for audit/provenance.
                if src["relevance_score"] == 0.0:
                    src["status"] = "irrelevant"

    resp = call_state(
        args.session_dir, "add-sources",
        json_data=sources,
        timeout=10,
    )
    if resp is not None:
        added = resp.get("results", {})
        if isinstance(added, dict):
            n_added = len(added.get("added", []))
            n_dup = len(added.get("duplicates", []))
            log(f"Sources auto-added to state: {n_added} new, {n_dup} duplicates")
        else:
            log("Sources sent to state")


def _append_journal_entry(args, result: dict, search_mode: str) -> None:
    """Auto-append a structured journal entry to journal.md after each search."""
    try:
        journal_path = os.path.join(args.session_dir, "journal.md")
        if not os.path.exists(journal_path):
            return

        provider = args.provider
        query = args.query or "(identifier-based)"
        results_list = result.get("results", {})
        if isinstance(results_list, dict):
            results_list = results_list.get("results", [])
        if not isinstance(results_list, list):
            results_list = []

        count = len(results_list)

        # Extract top 3 result titles
        top_titles = []
        for r in results_list[:3]:
            if isinstance(r, dict):
                title = r.get("title", "")
                if title:
                    top_titles.append(title[:80])

        # Format entry
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## Search: {provider} ({search_mode}) — {timestamp}\n"
        entry += f"**Query:** {query}\n"
        entry += f"**Results:** {count}\n"
        if top_titles:
            entry += "**Top results:**\n"
            for t in top_titles:
                entry += f"- {t}\n"
        entry += "\n"

        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        log(f"Failed to append journal entry: {e}", level="debug")


if __name__ == "__main__":
    main()
