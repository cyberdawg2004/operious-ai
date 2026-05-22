"""Deterministic identities for cognition lineage."""

from __future__ import annotations

import uuid
from typing import NewType

CognitionLLMUsageId = NewType("CognitionLLMUsageId", uuid.UUID)

_LLM_USAGE_NAMESPACE = uuid.UUID("7d7f91de-38e4-555c-bc45-7739d1185df6")


def derive_llm_usage_id(
    *,
    tenant_id: str,
    execution_id: str,
    model: str,
) -> CognitionLLMUsageId:
    """Derive a stable usage id for one model-backed execution."""

    seed = "|".join(
        (
            _normalize(tenant_id, "tenant_id"),
            _normalize(execution_id, "execution_id"),
            _normalize(model, "model"),
        )
    )
    return CognitionLLMUsageId(uuid.uuid5(_LLM_USAGE_NAMESPACE, seed))


def as_llm_usage_id(value: str | uuid.UUID) -> CognitionLLMUsageId:
    return CognitionLLMUsageId(value if isinstance(value, uuid.UUID) else uuid.UUID(value))


def _normalize(value: str, field: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


__all__ = [
    "CognitionLLMUsageId",
    "as_llm_usage_id",
    "derive_llm_usage_id",
]
