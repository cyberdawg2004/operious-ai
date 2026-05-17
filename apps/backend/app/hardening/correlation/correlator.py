"""Pure correlation-seed helpers."""

from __future__ import annotations

from typing import Mapping


def canonicalize_correlation_handles(
    handles: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    """Sort + drop empty values for deterministic seeds."""
    out: list[tuple[str, str]] = []
    for key in sorted(handles.keys()):
        value = handles[key]
        if value:
            out.append((key, value))
    return tuple(out)


def build_correlation_seed(
    *, kind: str, handles: Mapping[str, str]
) -> str:
    if not kind:
        raise ValueError(
            "build_correlation_seed requires non-empty kind"
        )
    canonical = canonicalize_correlation_handles(handles)
    parts = [kind] + [f"{k}={v}" for k, v in canonical]
    return "|".join(parts)


__all__ = [
    "build_correlation_seed",
    "canonicalize_correlation_handles",
]
