"""Search provider registry — maps provider names to modules with lazy import."""

import importlib

# Provider name -> module path (relative to this package)
_REGISTRY: dict[str, str] = {
    "semantic_scholar": "providers.semantic_scholar",
    "openalex": "providers.openalex",
    "arxiv": "providers.arxiv",
    "pubmed": "providers.pubmed",
    "biorxiv": "providers.biorxiv",
    "github": "providers.github",
    "reddit": "providers.reddit",
    "hn": "providers.hn",
    "tavily": "providers.tavily",
    "gensee": "providers.gensee",
    "yfinance": "providers.yfinance_provider",
    "edgar": "providers.edgar",
    "crossref": "providers.crossref",
    "core": "providers.core",
    "opencitations": "providers.opencitations",
    "dblp": "providers.dblp",
}


def get_provider(name: str):
    """Lazy-import and return a provider module by name.

    Raises KeyError if the provider name is not registered.
    Raises ImportError if the module cannot be loaded.
    """
    if name not in _REGISTRY:
        raise KeyError(f"Unknown provider: {name}. Available: {', '.join(sorted(_REGISTRY))}")
    return importlib.import_module(_REGISTRY[name])


def available_providers() -> list[str]:
    """Return sorted list of registered provider names."""
    return sorted(_REGISTRY)
