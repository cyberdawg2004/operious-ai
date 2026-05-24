"""Deterministic escalation identity primitives."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import coerce_tenant_id


EscalationId = NewType("EscalationId", uuid.UUID)
EscalationOutboxId = NewType("EscalationOutboxId", uuid.UUID)
EscalationOutboxClaimId = NewType("EscalationOutboxClaimId", uuid.UUID)

_ESCALATION_NAMESPACE = uuid.UUID("8f85a2aa-0001-4a01-9001-000000000001")
_ESCALATION_EVENT_NAMESPACE = uuid.UUID(
    "8f85a2aa-0002-4a01-9001-000000000002"
)
_ESCALATION_GOVERNANCE_NAMESPACE = uuid.UUID(
    "8f85a2aa-0003-4a01-9001-000000000003"
)
_ESCALATION_OUTBOX_NAMESPACE = uuid.UUID(
    "8f85a2aa-0004-4a01-9001-000000000004"
)
_ESCALATION_OUTBOX_CLAIM_NAMESPACE = uuid.UUID(
    "8f85a2aa-0005-4a01-9001-000000000005"
)


def derive_escalation_id(
    *,
    tenant_id: str,
    session_id: uuid.UUID | str,
    governance_decision_id: uuid.UUID | str,
) -> EscalationId:
    """Derive the canonical escalation id for one denied decision."""

    tenant = coerce_tenant_id(tenant_id)
    seed = f"{tenant}|{session_id}|{governance_decision_id}"
    return EscalationId(uuid.uuid5(_ESCALATION_NAMESPACE, seed))


def derive_escalation_event_id(
    *,
    escalation_id: uuid.UUID | str,
    status: str,
) -> uuid.UUID:
    """Derive a stable event id for one escalation status projection."""

    if not status:
        raise ValueError("status is required")
    return uuid.uuid5(
        _ESCALATION_EVENT_NAMESPACE,
        f"{escalation_id}|{status}",
    )


def derive_escalation_override_decision_id(
    *,
    escalation_id: uuid.UUID | str,
    governance_decision_id: uuid.UUID | str,
    tenant_id: str,
) -> uuid.UUID:
    """Derive the human-approval governance override decision id."""

    tenant = coerce_tenant_id(tenant_id)
    return uuid.uuid5(
        _ESCALATION_GOVERNANCE_NAMESPACE,
        f"override|{tenant}|{escalation_id}|{governance_decision_id}",
    )


def derive_escalation_override_action_id(
    *,
    escalation_id: uuid.UUID | str,
    override_decision_id: uuid.UUID | str,
    tenant_id: str,
) -> uuid.UUID:
    """Derive the enforcement-action id for an override decision."""

    tenant = coerce_tenant_id(tenant_id)
    return uuid.uuid5(
        _ESCALATION_GOVERNANCE_NAMESPACE,
        f"override-action|{tenant}|{escalation_id}|{override_decision_id}",
    )


def derive_escalation_outbox_id(
    *,
    escalation_id: uuid.UUID | str,
    tenant_id: str,
) -> EscalationOutboxId:
    """Derive the stable outbox row id for one escalation."""

    tenant = coerce_tenant_id(tenant_id)
    return EscalationOutboxId(
        uuid.uuid5(_ESCALATION_OUTBOX_NAMESPACE, f"{tenant}|{escalation_id}")
    )


def derive_escalation_outbox_claim_id(
    *,
    outbox_id: uuid.UUID | str,
    publisher_id: str,
    republish_count: int,
) -> EscalationOutboxClaimId:
    """Derive the claim token for one outbox publication attempt."""

    if not publisher_id:
        raise ValueError("publisher_id is required")
    if republish_count < 1:
        raise ValueError("republish_count must be >= 1")
    return EscalationOutboxClaimId(
        uuid.uuid5(
            _ESCALATION_OUTBOX_CLAIM_NAMESPACE,
            f"{outbox_id}|{publisher_id}|{republish_count}",
        )
    )


def as_escalation_id(value: uuid.UUID | str) -> EscalationId:
    """Coerce a boundary value into an escalation id."""

    return EscalationId(value if isinstance(value, uuid.UUID) else uuid.UUID(value))


def as_escalation_outbox_id(value: uuid.UUID | str) -> EscalationOutboxId:
    """Coerce a boundary value into an escalation outbox id."""

    return EscalationOutboxId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_escalation_outbox_claim_id(
    value: uuid.UUID | str,
) -> EscalationOutboxClaimId:
    """Coerce a boundary value into an escalation outbox claim id."""

    return EscalationOutboxClaimId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "EscalationId",
    "EscalationOutboxClaimId",
    "EscalationOutboxId",
    "as_escalation_id",
    "as_escalation_outbox_claim_id",
    "as_escalation_outbox_id",
    "derive_escalation_event_id",
    "derive_escalation_id",
    "derive_escalation_outbox_claim_id",
    "derive_escalation_override_action_id",
    "derive_escalation_override_decision_id",
    "derive_escalation_outbox_id",
]
