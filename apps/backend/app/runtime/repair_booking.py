"""MVP-9 — Repair Booking and Follow-Up Runtime.

Two components:

1. **Booking**: Repair dispatch via GenericConnectorTool ACT mode with
   commitment_kind = SERVICE_COMMITMENT. The money/goods gate fires
   (service commitments are in scope). Human approval required before
   dispatch fires.

2. **Follow-up**: After confirmed dispatch, a scheduled follow-up trigger
   is created. Follow-up sends a status-update outbound draft via the
   customer's last-active channel (from MVP-7 identity resolution).

INVARIANTS:
- Repair booking ALWAYS routes to PENDING_HUMAN_APPROVAL (service commitment)
- Follow-up draft routes through governance gate (NEVER auto-sent)
- Without MVP-7 context: follow-up uses originating ticket's channel
  (graceful degradation)
- Follow-up fires at T+N hours per tenant config
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Mapping

from app.agents.tools.operation_metadata import CommitmentKind
from app.governance.capability.acts import OperationalAct

logger = logging.getLogger(__name__)

_REPAIR_BOOKING_NAMESPACE = uuid.UUID("d5f7a1b3-2c4e-6f8a-b0d2-4e6f8a0c2d4e")

DEFAULT_FOLLOW_UP_DELAY_HOURS = 48


class RepairBookingStatus(StrEnum):
    PENDING_HUMAN_APPROVAL = "pending_human_approval"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FollowUpStatus(StrEnum):
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    DRAFT_CREATED = "draft_created"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RepairBookingRequest:
    """Input for creating a repair booking."""

    tenant_id: str
    session_id: str
    execution_id: str
    product_sku: str | None = None
    issue_description: str = ""
    customer_handle: str | None = None
    source_channel: str | None = None
    connector_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class RepairBookingRecord:
    """Persisted repair booking — always starts as PENDING_HUMAN_APPROVAL."""

    booking_id: str
    tenant_id: str
    session_id: str
    execution_id: str
    status: RepairBookingStatus
    commitment_kind: str
    product_sku: str | None = None
    issue_description: str = ""
    customer_handle: str | None = None
    source_channel: str | None = None
    connector_id: str | None = None
    governance_decision_id: str | None = None
    dispatched_at: str | None = None
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "booking_id": self.booking_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "commitment_kind": self.commitment_kind,
            "product_sku": self.product_sku,
            "issue_description": self.issue_description,
            "customer_handle": self.customer_handle,
            "source_channel": self.source_channel,
            "connector_id": self.connector_id,
            "governance_decision_id": self.governance_decision_id,
            "dispatched_at": self.dispatched_at,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepairBookingRecord:
        return cls(
            booking_id=str(data["booking_id"]),
            tenant_id=str(data["tenant_id"]),
            session_id=str(data["session_id"]),
            execution_id=str(data["execution_id"]),
            status=RepairBookingStatus(data["status"]),
            commitment_kind=str(data["commitment_kind"]),
            product_sku=data.get("product_sku"),
            issue_description=str(data.get("issue_description", "")),
            customer_handle=data.get("customer_handle"),
            source_channel=data.get("source_channel"),
            connector_id=data.get("connector_id"),
            governance_decision_id=data.get("governance_decision_id"),
            dispatched_at=data.get("dispatched_at"),
            created_at=str(data.get("created_at", "")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class FollowUpSchedule:
    """Scheduled follow-up after a confirmed repair dispatch."""

    follow_up_id: str
    tenant_id: str
    session_id: str
    booking_id: str
    status: FollowUpStatus
    scheduled_at: str
    trigger_at: str
    customer_handle: str | None = None
    channel: str | None = None
    follow_up_template: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "follow_up_id": self.follow_up_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "booking_id": self.booking_id,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at,
            "trigger_at": self.trigger_at,
            "customer_handle": self.customer_handle,
            "channel": self.channel,
            "follow_up_template": self.follow_up_template,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FollowUpSchedule:
        return cls(
            follow_up_id=str(data["follow_up_id"]),
            tenant_id=str(data["tenant_id"]),
            session_id=str(data["session_id"]),
            booking_id=str(data["booking_id"]),
            status=FollowUpStatus(data["status"]),
            scheduled_at=str(data["scheduled_at"]),
            trigger_at=str(data["trigger_at"]),
            customer_handle=data.get("customer_handle"),
            channel=data.get("channel"),
            follow_up_template=str(data.get("follow_up_template", "")),
            metadata=dict(data.get("metadata") or {}),
        )


class RepairBookingRuntime:
    """Runtime for repair booking with service commitment governance.

    INVARIANT: Every repair booking starts as PENDING_HUMAN_APPROVAL.
    The commitment_kind=SERVICE_COMMITMENT ensures the money/goods gate
    fires and routes to human approval. Only after explicit human approval
    does the dispatch connector fire.
    """

    def create_booking(
        self,
        request: RepairBookingRequest,
    ) -> RepairBookingRecord:
        """Create a repair booking in PENDING_HUMAN_APPROVAL state.

        NEVER auto-approves. The booking record captures the service
        commitment and awaits human decision.
        """
        now = datetime.now(timezone.utc)
        booking_id = str(uuid.uuid5(
            _REPAIR_BOOKING_NAMESPACE,
            f"booking:{request.tenant_id}:{request.session_id}:{request.execution_id}",
        ))

        return RepairBookingRecord(
            booking_id=booking_id,
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            execution_id=request.execution_id,
            status=RepairBookingStatus.PENDING_HUMAN_APPROVAL,
            commitment_kind=CommitmentKind.SERVICE_COMMITMENT.value,
            product_sku=request.product_sku,
            issue_description=request.issue_description,
            customer_handle=request.customer_handle,
            source_channel=request.source_channel,
            connector_id=request.connector_id,
            created_at=now.isoformat(),
            metadata=request.metadata,
        )

    def approve_booking(
        self,
        booking: RepairBookingRecord,
        *,
        governance_decision_id: str,
    ) -> RepairBookingRecord:
        """Mark a booking as approved after human review.

        Returns a new record with status=APPROVED and the governance
        decision ID that authorized the dispatch.
        """
        if booking.status != RepairBookingStatus.PENDING_HUMAN_APPROVAL:
            raise ValueError(
                f"Cannot approve booking in state {booking.status}"
            )

        from dataclasses import replace
        return replace(
            booking,
            status=RepairBookingStatus.APPROVED,
            governance_decision_id=governance_decision_id,
        )

    def mark_dispatched(
        self,
        booking: RepairBookingRecord,
    ) -> RepairBookingRecord:
        """Mark a booking as dispatched after connector fires successfully."""
        if booking.status != RepairBookingStatus.APPROVED:
            raise ValueError(
                f"Cannot dispatch booking in state {booking.status}"
            )

        from dataclasses import replace
        return replace(
            booking,
            status=RepairBookingStatus.DISPATCHED,
            dispatched_at=datetime.now(timezone.utc).isoformat(),
        )

    def schedule_follow_up(
        self,
        booking: RepairBookingRecord,
        *,
        delay_hours: int | None = None,
        channel: str | None = None,
        follow_up_template: str = "",
    ) -> FollowUpSchedule:
        """Schedule a follow-up after a confirmed dispatch.

        Graceful degradation: if no channel from MVP-7, uses the
        originating ticket's source_channel.
        """
        if booking.status != RepairBookingStatus.DISPATCHED:
            raise ValueError(
                f"Cannot schedule follow-up for booking in state {booking.status}"
            )

        effective_delay = delay_hours or DEFAULT_FOLLOW_UP_DELAY_HOURS
        now = datetime.now(timezone.utc)
        trigger_at = now + timedelta(hours=effective_delay)

        effective_channel = channel or booking.source_channel

        follow_up_id = str(uuid.uuid5(
            _REPAIR_BOOKING_NAMESPACE,
            f"followup:{booking.booking_id}:{trigger_at.isoformat()}",
        ))

        return FollowUpSchedule(
            follow_up_id=follow_up_id,
            tenant_id=booking.tenant_id,
            session_id=booking.session_id,
            booking_id=booking.booking_id,
            status=FollowUpStatus.SCHEDULED,
            scheduled_at=now.isoformat(),
            trigger_at=trigger_at.isoformat(),
            customer_handle=booking.customer_handle,
            channel=effective_channel,
            follow_up_template=follow_up_template,
            metadata={
                "delay_hours": effective_delay,
                "booking_id": booking.booking_id,
                "governance_decision_id": booking.governance_decision_id,
            },
        )


def repair_booking_commitment_kind() -> CommitmentKind:
    """The commitment kind for repair bookings — always SERVICE_COMMITMENT."""
    return CommitmentKind.SERVICE_COMMITMENT


def repair_booking_operational_act() -> OperationalAct:
    """The operational act emitted for follow-up triggers."""
    return OperationalAct.FOLLOW_UP_TRIGGER


def build_repair_connector_operation() -> dict[str, Any]:
    """Build the connector operation definition for repair dispatch.

    Returns the configuration dict that tenants use to define their
    repair dispatch connector operation. commitment_kind is ALWAYS
    SERVICE_COMMITMENT — this is not tenant-configurable.
    """
    return {
        "operation_id": "repair_dispatch",
        "mode": "act",
        "commitment_kind": CommitmentKind.SERVICE_COMMITMENT.value,
        "approval_policy": "always_require_approval",
        "input_schema": {
            "type": "object",
            "required": ["session_id", "issue_description"],
            "properties": {
                "session_id": {"type": "string"},
                "product_sku": {"type": "string"},
                "issue_description": {"type": "string"},
                "customer_handle": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                },
            },
        },
    }


__all__ = [
    "DEFAULT_FOLLOW_UP_DELAY_HOURS",
    "FollowUpSchedule",
    "FollowUpStatus",
    "RepairBookingRecord",
    "RepairBookingRequest",
    "RepairBookingRuntime",
    "RepairBookingStatus",
    "build_repair_connector_operation",
    "repair_booking_commitment_kind",
    "repair_booking_operational_act",
]
