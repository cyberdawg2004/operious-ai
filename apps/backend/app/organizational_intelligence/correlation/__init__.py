"""Cross-substrate correlation helpers.

The intelligence substrate refers to sibling-substrate artifacts
through OPAQUE STRING handles only — it never imports the typed
identifiers. The helpers here build canonicalised correlation
seeds the runtimes use when deriving deterministic ids.
"""

from app.organizational_intelligence.correlation.correlator import (
    build_correlation_seed,
    canonicalize_correlation_handles,
)

__all__ = [
    "build_correlation_seed",
    "canonicalize_correlation_handles",
]
