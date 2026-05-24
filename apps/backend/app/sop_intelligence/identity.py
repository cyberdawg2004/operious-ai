"""Deterministic SOP intelligence identity primitives."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import coerce_tenant_id


ApprovalId = NewType("ApprovalId", uuid.UUID)
ApprovalEventId = NewType("ApprovalEventId", uuid.UUID)

_APPROVAL_NAMESPACE = uuid.UUID("4c0af690-0001-4001-8001-000000000001")
_APPROVAL_EVENT_NAMESPACE = uuid.UUID(
    "4c0af690-0002-4001-8001-000000000002"
)


def derive_approval_id(
    *,
    tenant_id: str,
    document_id: uuid.UUID | str,
    evidence_sessions: tuple[str, ...],
    qa_score_id: uuid.UUID | str,
) -> ApprovalId:
    """Derive the stable id for one SOP proposal lineage."""

    tenant = coerce_tenant_id(tenant_id)
    if not evidence_sessions:
        raise ValueError("derive_approval_id requires evidence_sessions")
    canonical_sessions = ",".join(str(value) for value in evidence_sessions)
    seed = f"{tenant}|{document_id}|{canonical_sessions}|{qa_score_id}"
    return ApprovalId(uuid.uuid5(_APPROVAL_NAMESPACE, seed))


def as_approval_id(value: uuid.UUID | str) -> ApprovalId:
    """Coerce a boundary value into an approval id."""

    return ApprovalId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def derive_approval_event_id(
    *,
    approval_id: uuid.UUID | str,
    status: str,
) -> ApprovalEventId:
    """Derive a stable event id for one approval-record status projection."""

    if not status:
        raise ValueError("status is required")
    return ApprovalEventId(
        uuid.uuid5(_APPROVAL_EVENT_NAMESPACE, f"{approval_id}|{status}")
    )


__all__ = [
    "ApprovalEventId",
    "ApprovalId",
    "as_approval_id",
    "derive_approval_event_id",
    "derive_approval_id",
]
