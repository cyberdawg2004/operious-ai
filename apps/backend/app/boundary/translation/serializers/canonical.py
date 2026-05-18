"""Canonical text + attribute fingerprinting helpers.

Pure functions only — substrate-sovereign canonicalisation per the
``_string_key`` canonical projection doctrine
(``docs/canonicalization/string-key-projection.md``).

The substrate MUST canonicalise mappings with the local ``_string_key``
projection at every nested sort site. Importing a shared ``_string_key``
from another substrate is forbidden by the doctrine; each substrate owns
its own implementation so canonical-form evolution cannot fan out across
substrates by accident.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping


_PRIMITIVES = (str, int, float, bool, type(None))


def text_fingerprint(text: str, *, language: str) -> str:
    """Stable SHA-256 hex digest over ``language|text``."""
    blob = f"{language}\x1f{text}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def canonicalize_payload(value: Any) -> Any:
    """Recursively normalise into a canonical JSON-safe shape.

    Mapping keys are projected through :func:`_string_key` before sorting
    so canonical form is deterministic for mixed-type-key mappings (the
    constitutional contract under F-28 binding in the canonicalisation
    doctrine).
    """
    if isinstance(value, Mapping):
        return {
            key: canonicalize_payload(value[key])
            for key in sorted(value.keys(), key=_string_key)
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_payload(item) for item in value]
    if isinstance(value, set):
        sorted_items = sorted(
            value,
            key=lambda x: json.dumps(canonicalize_payload(x), default=str),
        )
        return [canonicalize_payload(item) for item in sorted_items]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def canonicalize_attributes(
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalise an attribute mapping (typed wrapper)."""
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        attributes, Mapping
    ):
        raise TypeError(
            f"boundary/translation canonicalize_attributes expected a "
            f"Mapping, got {type(attributes).__name__!r}"
        )
    return {
        key: canonicalize_payload(attributes[key])
        for key in sorted(attributes.keys(), key=_string_key)
    }


def content_fingerprint(value: Any) -> str:
    """Stable SHA-256 hex digest over canonical JSON encoding."""
    canonical = canonicalize_payload(value)
    blob = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _string_key(key: Any) -> str:
    """Project a Mapping key to a deterministic sort string.

    See ``docs/canonicalization/string-key-projection.md`` for the
    constitutional contract. ``str`` keys pass through unchanged;
    every other key is projected via ``json.dumps(key, default=str,
    sort_keys=True)`` so cross-type comparison is avoided.
    """
    return key if isinstance(key, str) else json.dumps(key, default=str, sort_keys=True)


__all__ = [
    "canonicalize_attributes",
    "canonicalize_payload",
    "content_fingerprint",
    "text_fingerprint",
]
