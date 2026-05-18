"""Pure canonical serialisation + content-fingerprinting helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping


_PRIMITIVES = (str, int, float, bool, type(None))


def canonicalize_payload(value: Any) -> Any:
    """Recursively normalise into a canonical JSON-safe shape."""
    if isinstance(value, Mapping):
        return {
            key: canonicalize_payload(value[key])
            for key in sorted(value.keys(), key=_string_key)
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_payload(i) for i in value]
    if isinstance(value, set):
        sorted_items = sorted(
            value,
            key=lambda x: json.dumps(
                canonicalize_payload(x), default=str
            ),
        )
        return [canonicalize_payload(i) for i in sorted_items]
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
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        attributes, Mapping
    ):
        raise TypeError(
            f"hardening canonicalize_attributes expected a Mapping, got "
            f"{type(attributes).__name__!r}"
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
    return (
        key
        if isinstance(key, str)
        else json.dumps(key, default=str, sort_keys=True)
    )


__all__ = [
    "canonicalize_attributes",
    "canonicalize_payload",
    "content_fingerprint",
]
