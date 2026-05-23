"""Canonical deterministic runtime identity derivation."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any


def derive_runtime_id(
    *,
    namespace: uuid.UUID,
    tenant_id: str | None,
    seed_components: Sequence[object],
) -> uuid.UUID:
    """Derive a UUID5 from stable tenant-scoped seed components."""

    seed = json.dumps(
        {
            "tenant_id": tenant_id or "",
            "seed_components": [_json_safe(item) for item in seed_components],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return uuid.uuid5(namespace, seed)


def _json_safe(value: object) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = ["derive_runtime_id"]
