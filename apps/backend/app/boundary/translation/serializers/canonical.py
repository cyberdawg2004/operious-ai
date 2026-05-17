"""Canonical text + attribute fingerprinting helpers."""

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


def canonicalize_attributes(
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(attributes, Mapping):
        raise TypeError(
            "canonicalize_attributes expected a Mapping"
        )
    return {
        key: _canonicalize(attributes[key])
        for key in sorted(attributes.keys())
    }


def content_fingerprint(value: Any) -> str:
    canonical = _canonicalize(value)
    blob = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _canonicalize(value[key])
            for key in sorted(value.keys())
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, set):
        sorted_items = sorted(
            value,
            key=lambda x: json.dumps(
                _canonicalize(x), default=str
            ),
        )
        return [_canonicalize(v) for v in sorted_items]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


__all__ = [
    "canonicalize_attributes",
    "content_fingerprint",
    "text_fingerprint",
]
