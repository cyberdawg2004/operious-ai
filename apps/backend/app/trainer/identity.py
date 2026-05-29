"""Deterministic identity helpers for trainer recommendations."""

from __future__ import annotations

import uuid

from app.identity import coerce_tenant_id

_TRAINER_NAMESPACE = uuid.UUID("aa6e7001-0007-4007-8007-000000000007")


def derive_recommendation_id(
    *,
    tenant_id: str,
    session_id: str,
    qa_score_id: str,
    dimension: str,
) -> uuid.UUID:
    tenant = coerce_tenant_id(tenant_id)
    if not session_id:
        raise ValueError("session_id is required")
    if not qa_score_id:
        raise ValueError("qa_score_id is required")
    if not dimension:
        raise ValueError("dimension is required")
    seed = f"{tenant}|{session_id}|{qa_score_id}|{dimension}"
    return uuid.uuid5(_TRAINER_NAMESPACE, seed)


__all__ = ["derive_recommendation_id"]
