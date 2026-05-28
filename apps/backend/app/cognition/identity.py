"""Deterministic identities for cognition lineage."""

from __future__ import annotations

import uuid
from typing import NewType

CognitionLLMUsageId = NewType("CognitionLLMUsageId", uuid.UUID)
CognitionAuditId = NewType("CognitionAuditId", uuid.UUID)

_LLM_USAGE_NAMESPACE = uuid.UUID("7d7f91de-38e4-555c-bc45-7739d1185df6")
_COGNITION_AUDIT_NAMESPACE = uuid.UUID(
    "7d7f91de-38e4-555c-bc45-7739d1185df7"
)


def derive_llm_usage_id(
    *,
    tenant_id: str,
    execution_id: str,
    model: str,
    attempt_id: str | None = None,
) -> CognitionLLMUsageId:
    """Derive a stable usage id for one model-backed execution."""

    parts = [
        _normalize(tenant_id, "tenant_id"),
        _normalize(execution_id, "execution_id"),
        _normalize(model, "model"),
    ]
    if attempt_id is not None:
        parts.append(_normalize(attempt_id, "attempt_id"))
    seed = "|".join(parts)
    return CognitionLLMUsageId(uuid.uuid5(_LLM_USAGE_NAMESPACE, seed))


def as_llm_usage_id(value: str | uuid.UUID) -> CognitionLLMUsageId:
    return CognitionLLMUsageId(value if isinstance(value, uuid.UUID) else uuid.UUID(value))


def derive_cognition_audit_id(
    *,
    tenant_id: str,
    execution_id: str,
    model: str,
    prompt_sha256: str,
    completion_sha256: str,
    attempt_id: str | None = None,
) -> CognitionAuditId:
    """Derive a stable forensic snapshot id for one completed LLM call."""

    parts = [
        _normalize(tenant_id, "tenant_id"),
        _normalize(execution_id, "execution_id"),
        _normalize(model, "model"),
        _normalize(prompt_sha256, "prompt_sha256"),
        _normalize(completion_sha256, "completion_sha256"),
    ]
    if attempt_id is not None:
        parts.append(_normalize(attempt_id, "attempt_id"))
    seed = "|".join(parts)
    return CognitionAuditId(uuid.uuid5(_COGNITION_AUDIT_NAMESPACE, seed))


def as_cognition_audit_id(value: str | uuid.UUID) -> CognitionAuditId:
    return CognitionAuditId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def _normalize(value: str, field: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


__all__ = [
    "CognitionAuditId",
    "CognitionLLMUsageId",
    "as_cognition_audit_id",
    "as_llm_usage_id",
    "derive_cognition_audit_id",
    "derive_llm_usage_id",
]
