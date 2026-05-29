"""Pure canonical serialisation + content-fingerprinting helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast


_PRIMITIVES = (str, int, float, bool, type(None))


def canonicalize_payload(value: object) -> Any:
    """Recursively normalise into a canonical JSON-safe shape."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            key: canonicalize_payload(mapping[key])
            for key in sorted(mapping.keys(), key=_string_key)
        }
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [canonicalize_payload(i) for i in sequence]
    if isinstance(value, set):
        items = cast(set[object], value)
        sorted_items = sorted(
            items,
            key=lambda x: json.dumps(
                canonicalize_payload(x),
                default=str,
                sort_keys=True,
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


def canonicalize_attributes(attributes: object) -> dict[str, Any]:
    if not isinstance(attributes, Mapping):
        raise TypeError(
            f"hardening canonicalize_attributes expected a Mapping, got "
            f"{type(attributes).__name__!r}"
        )
    mapping = cast(Mapping[str, Any], attributes)
    return {
        key: canonicalize_payload(mapping[key])
        for key in sorted(mapping.keys(), key=_string_key)
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


def _string_key(key: object) -> str:
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
