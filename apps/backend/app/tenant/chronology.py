"""Chronology hashing helpers for tenant-owned version history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, cast
import uuid


@dataclass(frozen=True, slots=True)
class ChronologyVerificationResult:
    valid: bool
    broken_at_version: int | None = None


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(k): _json_safe(v) for k, v in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_json_safe(item) for item in sequence]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = ["ChronologyVerificationResult", "canonical_sha256"]
