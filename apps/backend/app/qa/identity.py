"""Deterministic QA identity primitives."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import coerce_tenant_id


QAScoreId = NewType("QAScoreId", uuid.UUID)

_QA_SCORE_NAMESPACE = uuid.UUID("3b25a8d0-0001-4001-8001-000000000001")


def derive_qa_score_id(
    *,
    tenant_id: str,
    inspection_id: uuid.UUID | str,
) -> QAScoreId:
    """Derive the canonical QA score id for one supervisor inspection."""

    tenant = coerce_tenant_id(tenant_id)
    seed = f"{tenant}|{inspection_id}"
    return QAScoreId(uuid.uuid5(_QA_SCORE_NAMESPACE, seed))


def as_qa_score_id(value: uuid.UUID | str) -> QAScoreId:
    """Coerce a boundary value into a QA score id."""

    return QAScoreId(value if isinstance(value, uuid.UUID) else uuid.UUID(value))


__all__ = [
    "QAScoreId",
    "as_qa_score_id",
    "derive_qa_score_id",
]
