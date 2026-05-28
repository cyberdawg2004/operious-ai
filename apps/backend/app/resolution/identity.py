"""Deterministic identity for resolution proposals."""

from __future__ import annotations

import uuid
from typing import NewType

ResolutionProposalId = NewType("ResolutionProposalId", uuid.UUID)
ResolutionOutboundDraftId = NewType("ResolutionOutboundDraftId", uuid.UUID)

_RESOLUTION_PROPOSAL_NAMESPACE = uuid.UUID(
    "2b7b4f5a-0001-4b01-9001-000000000001"
)
_RESOLUTION_OUTBOUND_DRAFT_NAMESPACE = uuid.UUID(
    "2b7b4f5a-0001-4b01-9001-000000000002"
)


def derive_resolution_proposal_id(
    *,
    tenant_id: str,
    session_id: str | uuid.UUID,
    execution_id: str | uuid.UUID,
    dispatch_id: str | uuid.UUID,
    diagnostic_event_id: str | uuid.UUID | None,
    diagnostic_event_type: str,
) -> ResolutionProposalId:
    """Derive the durable proposal id from diagnostic lineage."""

    tenant = _required_text("tenant_id", tenant_id)
    event_type = _required_text("diagnostic_event_type", diagnostic_event_type)
    seed = "|".join(
        (
            tenant,
            _uuid_text("session_id", session_id),
            _uuid_text("execution_id", execution_id),
            _uuid_text("dispatch_id", dispatch_id),
            _optional_uuid_text("diagnostic_event_id", diagnostic_event_id),
            event_type,
        )
    )
    return ResolutionProposalId(
        uuid.uuid5(_RESOLUTION_PROPOSAL_NAMESPACE, seed)
    )


def as_resolution_proposal_id(value: str | uuid.UUID) -> ResolutionProposalId:
    """Coerce an external value into a typed proposal id."""

    return ResolutionProposalId(uuid.UUID(str(value)))


def derive_resolution_outbound_draft_id(
    *,
    tenant_id: str,
    proposal_id: str | uuid.UUID,
) -> ResolutionOutboundDraftId:
    """Derive the durable outbound draft id from proposal lineage."""

    tenant = _required_text("tenant_id", tenant_id)
    seed = "|".join((tenant, _uuid_text("proposal_id", proposal_id)))
    return ResolutionOutboundDraftId(
        uuid.uuid5(_RESOLUTION_OUTBOUND_DRAFT_NAMESPACE, seed)
    )


def as_resolution_outbound_draft_id(
    value: str | uuid.UUID,
) -> ResolutionOutboundDraftId:
    """Coerce an external value into a typed outbound draft id."""

    return ResolutionOutboundDraftId(uuid.UUID(str(value)))


def _required_text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _uuid_text(name: str, value: str | uuid.UUID) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid UUID") from exc


def _optional_uuid_text(
    name: str,
    value: str | uuid.UUID | None,
) -> str:
    if value is None:
        return "none"
    return _uuid_text(name, value)


__all__ = [
    "ResolutionOutboundDraftId",
    "ResolutionProposalId",
    "as_resolution_outbound_draft_id",
    "as_resolution_proposal_id",
    "derive_resolution_outbound_draft_id",
    "derive_resolution_proposal_id",
]
