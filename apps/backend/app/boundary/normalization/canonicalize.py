"""Canonicalisation helpers for boundary payloads + metadata.

Three pure functions:

* `canonicalize_payload(value)`  — recursively re-orders mappings
                                    by sorted key, copies lists,
                                    and rejects unsupported types.
                                    Output is JSON-serialisable
                                    and key-order-stable.
* `canonicalize_metadata(value)` — same discipline but explicitly
                                    typed for `Mapping[str, Any]`.
* `content_fingerprint(value)`   — SHA-256 over the canonical
                                    JSON encoding. Used by the
                                    replay detector to recognise
                                    drift without storing full
                                    payload copies.

Determinism: identical inputs produce byte-identical outputs.
This is the bedrock of replay-safe ingestion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast


_PRIMITIVE_TYPES = (
    str,
    int,
    float,
    bool,
    type(None),
)


def canonicalize_payload(value: object) -> Any:
    """Recursively normalise into a canonical, JSON-serialisable shape.

    * Mappings → ``dict`` with keys sorted lexicographically.
    * Sequences (list/tuple/set) → ``list``; ``set`` is first
      sorted by canonical string representation for determinism.
    * Primitives → returned verbatim.
    * Other types → ``str(value)`` so caller-supplied opaque
      objects don't break canonicalisation. The substrate prefers
      defensive coercion over raising; adapters are expected to
      pre-normalise but the substrate must not crash on hostile
      payloads.
    """
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            key: canonicalize_payload(mapping[key])
            for key in sorted(mapping.keys(), key=_string_key)
        }
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [canonicalize_payload(item) for item in sequence]
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
        return [canonicalize_payload(item) for item in sorted_items]
    if isinstance(value, _PRIMITIVE_TYPES):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def canonicalize_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalise a metadata mapping (typed wrapper)."""
    return {
        key: canonicalize_payload(metadata[key])
        for key in sorted(metadata.keys(), key=_string_key)
    }


def content_fingerprint(value: Any) -> str:
    """Stable SHA-256 hex digest over canonical JSON encoding.

    Used by the replay detector to detect ``LINEAGE_DRIFT``: two
    deliveries with the same replay key and the same fingerprint
    are byte-identical retransmissions; mismatched fingerprints
    are drifted retransmissions.
    """
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
    """Force keys to a canonical string representation for sorting."""
    return key if isinstance(key, str) else json.dumps(
        key, default=str, sort_keys=True
    )


__all__ = [
    "canonicalize_metadata",
    "canonicalize_payload",
    "content_fingerprint",
]
