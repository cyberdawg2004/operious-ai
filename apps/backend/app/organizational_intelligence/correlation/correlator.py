"""Pure correlation-seed helpers."""

from __future__ import annotations

from collections.abc import Iterable


def canonicalize_correlation_handles(
    handles: Iterable[str | None],
) -> tuple[str, ...]:
    """Sort + deduplicate cross-substrate correlation handles.

    Accepts a nullable iterable so callers do not have to filter
    upstream — empty strings and `None` entries are dropped here.
    The output is the deterministic, sorted, deduplicated set of
    non-empty handles.
    """
    cleaned = sorted(
        {h for h in handles if h is not None and h != ""}
    )
    return tuple(cleaned)


def build_correlation_seed(*parts: str | None) -> str:
    """Concatenate parts into a deterministic correlation seed."""
    cleaned = [p for p in parts if p is not None and p != ""]
    return "|".join(cleaned)


__all__ = [
    "build_correlation_seed",
    "canonicalize_correlation_handles",
]
