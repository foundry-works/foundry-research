#!/usr/bin/env python3
"""Unified search CLI — routes queries to provider-specific modules."""

import argparse
import os
import sys

# Add parent directory so _shared imports work when run from any location
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _shared.output import error_response, log  # noqa: E402
from providers import available_providers, get_provider  # noqa: E402

# Flags that substitute for --query (provider -> set of flag dest names)
_IDENTIFIER_FLAGS = {
    "semantic_scholar": {"cited_by", "references", "recommendations", "author"},
    "reddit": {"post_url", "post_id", "browse"},
    "hn": {"story_id"},
    "biorxiv": {"doi"},
    "pubmed": {"fetch_pmids"},
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

    provider = args.provider

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

    # Call provider search
    log(f"Searching {provider}" + (f" for: {args.query}" if args.query else ""))
    result = mod.search(args)

    # Inject provider metadata into the result envelope
    if isinstance(result, dict):
        result.setdefault("provider", provider)
        if args.query:
            result.setdefault("query", args.query)
        result.setdefault("offset", args.offset)
        result.setdefault("limit", args.limit)

    # Log search to session state if --session-dir provided
    if args.session_dir and isinstance(result, dict) and result.get("status") == "ok":
        _log_search_to_state(args, result)


def _log_search_to_state(args, result: dict) -> None:
    """Log the search to session state via state.py."""
    try:
        import subprocess

        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        state_script = os.path.join(scripts_dir, "state.py")
        cmd = [
            sys.executable, state_script, "log-search",
            "--provider", args.provider,
            "--query", args.query or "",
            "--result-count", str(result.get("total_results", 0)),
            "--session-dir", args.session_dir,
        ]
        subprocess.run(cmd, capture_output=True, timeout=5)
    except Exception as e:
        log(f"Failed to log search to state: {e}", level="warn")


if __name__ == "__main__":
    main()
