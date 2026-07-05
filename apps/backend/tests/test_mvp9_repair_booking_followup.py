"""MVP-9 — Repair Booking and Follow-Up tests.

INVARIANT TESTS (per build plan):
1. Repair booking with commitment_kind = SERVICE_COMMITMENT → PENDING_HUMAN_APPROVAL
2. Human approves → dispatch connector fires → OperationalEvent persisted with
   governance_decision_id
3. Follow-up trigger fires at T+N hours per tenant config
4. Follow-up outbound draft routes through governance gate (not auto-sent)
5. Without MVP-7 context: follow-up uses originating ticket's channel (graceful
   degradation)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.agents.tools.operation_metadata import CommitmentKind
from app.governance.capability.acts import OperationalAct
from app.runtime.money_goods_commitment import (
    has_money_or_goods_commitment,
    money_or_goods_commitment_kinds,
)
from app.runtime.repair_booking import (
    DEFAULT_FOLLOW_UP_DELAY_HOURS,
    FollowUpSchedule,
    FollowUpStatus,
    RepairBookingRecord,
    RepairBookingRequest,
    RepairBookingRuntime,
    RepairBookingStatus,
    build_repair_connector_operation,
    repair_booking_commitment_kind,
    repair_booking_operational_act,
)

_TENANT = "tenant-repair-mvp9"
_SESSION = "session-repair-1"
_EXECUTION = "exec-repair-1"


def _make_request(
    *,
    product_sku: str = "SKU-LAPTOP-001",
    issue_description: str = "Screen cracked, needs replacement",
    customer_handle: str = "user@example.com",
    source_channel: str = "email",
    connector_id: str = "connector-repair-vendor",
) -> RepairBookingRequest:
    return RepairBookingRequest(
        tenant_id=_TENANT,
        session_id=_SESSION,
        execution_id=_EXECUTION,
        product_sku=product_sku,
        issue_description=issue_description,
        customer_handle=customer_handle,
        source_channel=source_channel,
        connector_id=connector_id,
    )


class TestRepairBookingCreation:
    """Repair booking always starts as PENDING_HUMAN_APPROVAL."""

    def test_booking_starts_pending_human_approval(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())

        assert booking.status == RepairBookingStatus.PENDING_HUMAN_APPROVAL
        assert booking.commitment_kind == CommitmentKind.SERVICE_COMMITMENT.value
        assert booking.tenant_id == _TENANT
        assert booking.session_id == _SESSION

    def test_booking_id_is_deterministic(self) -> None:
        runtime = RepairBookingRuntime()
        b1 = runtime.create_booking(_make_request())
        b2 = runtime.create_booking(_make_request())
        assert b1.booking_id == b2.booking_id

    def test_booking_captures_all_request_fields(self) -> None:
        runtime = RepairBookingRuntime()
        request = _make_request(
            product_sku="SKU-PHONE",
            issue_description="Battery swelling",
            customer_handle="phone@user.com",
            source_channel="whatsapp",
            connector_id="connector-field-service",
        )
        booking = runtime.create_booking(request)

        assert booking.product_sku == "SKU-PHONE"
        assert booking.issue_description == "Battery swelling"
        assert booking.customer_handle == "phone@user.com"
        assert booking.source_channel == "whatsapp"
        assert booking.connector_id == "connector-field-service"

    def test_booking_created_at_populated(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        assert booking.created_at != ""
        datetime.fromisoformat(booking.created_at)


class TestInvariantServiceCommitment:
    """INVARIANT: SERVICE_COMMITMENT fires money/goods gate."""

    def test_commitment_kind_is_service_commitment(self) -> None:
        assert repair_booking_commitment_kind() == CommitmentKind.SERVICE_COMMITMENT

    def test_service_commitment_in_commitment_kind_enum(self) -> None:
        assert "service_commitment" in [k.value for k in CommitmentKind]

    def test_repair_dispatch_tool_triggers_commitment_gate(self) -> None:
        actions = [{"tool_name": "repair.dispatch"}]
        kinds = money_or_goods_commitment_kinds(
            recommended_actions=actions,
        )
        assert len(kinds) > 0
        assert "tool_name:repair.dispatch" in kinds

    def test_service_dispatch_tool_triggers_commitment_gate(self) -> None:
        actions = [{"tool_name": "service.dispatch"}]
        kinds = money_or_goods_commitment_kinds(
            recommended_actions=actions,
        )
        assert len(kinds) > 0
        assert "tool_name:service.dispatch" in kinds

    def test_repair_booking_action_type_triggers_gate(self) -> None:
        actions = [{"type": "repair_dispatch"}]
        kinds = money_or_goods_commitment_kinds(
            recommended_actions=actions,
        )
        assert len(kinds) > 0
        assert "action_type:repair_dispatch" in kinds

    def test_service_dispatch_action_type_triggers_gate(self) -> None:
        actions = [{"type": "service_dispatch"}]
        kinds = money_or_goods_commitment_kinds(
            recommended_actions=actions,
        )
        assert "action_type:service_dispatch" in kinds

    def test_dispatch_reply_pattern_triggers_gate(self) -> None:
        reply = "We'll dispatch a technician to your location tomorrow."
        assert has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )

    def test_schedule_repair_pattern_triggers_gate(self) -> None:
        reply = "I will schedule a repair visit for next Tuesday."
        assert has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )

    def test_appointment_scheduled_pattern_triggers_gate(self) -> None:
        reply = "Your appointment is scheduled for Friday at 2pm."
        assert has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )

    def test_book_service_pattern_triggers_gate(self) -> None:
        reply = "Let me book a service appointment for you."
        assert has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )

    def test_technician_dispatched_pattern_triggers_gate(self) -> None:
        reply = "A technician has been dispatched to your address."
        assert has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )

    def test_repair_scheduled_pattern_triggers_gate(self) -> None:
        reply = "Your repair has been scheduled for tomorrow."
        assert has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )

    def test_non_commitment_reply_does_not_trigger(self) -> None:
        reply = "I've noted your issue. Let me check the status."
        assert not has_money_or_goods_commitment(
            recommended_actions=[],
            reply=reply,
        )


class TestBookingApproval:
    """Human approval flow: approve → dispatch → event persisted."""

    def test_approve_changes_status(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        decision_id = str(uuid.uuid4())

        approved = runtime.approve_booking(
            booking, governance_decision_id=decision_id
        )

        assert approved.status == RepairBookingStatus.APPROVED
        assert approved.governance_decision_id == decision_id
        assert approved.booking_id == booking.booking_id

    def test_approve_preserves_all_fields(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        decision_id = str(uuid.uuid4())

        approved = runtime.approve_booking(
            booking, governance_decision_id=decision_id
        )

        assert approved.tenant_id == booking.tenant_id
        assert approved.session_id == booking.session_id
        assert approved.product_sku == booking.product_sku
        assert approved.commitment_kind == booking.commitment_kind

    def test_cannot_approve_already_approved(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )

        with pytest.raises(ValueError, match="Cannot approve"):
            runtime.approve_booking(
                approved, governance_decision_id=str(uuid.uuid4())
            )

    def test_cannot_approve_dispatched(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        with pytest.raises(ValueError, match="Cannot approve"):
            runtime.approve_booking(
                dispatched, governance_decision_id=str(uuid.uuid4())
            )


class TestDispatchConfirmation:
    """After approval, dispatch connector fires."""

    def test_mark_dispatched_changes_status(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        assert dispatched.status == RepairBookingStatus.DISPATCHED
        assert dispatched.dispatched_at is not None
        datetime.fromisoformat(dispatched.dispatched_at)

    def test_cannot_dispatch_without_approval(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())

        with pytest.raises(ValueError, match="Cannot dispatch"):
            runtime.mark_dispatched(booking)

    def test_dispatch_preserves_governance_decision_id(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        decision_id = str(uuid.uuid4())
        approved = runtime.approve_booking(
            booking, governance_decision_id=decision_id
        )
        dispatched = runtime.mark_dispatched(approved)

        assert dispatched.governance_decision_id == decision_id


class TestFollowUpScheduling:
    """Follow-up fires at T+N hours per tenant config."""

    def test_follow_up_scheduled_after_dispatch(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched)

        assert follow_up.status == FollowUpStatus.SCHEDULED
        assert follow_up.booking_id == dispatched.booking_id
        assert follow_up.tenant_id == _TENANT
        assert follow_up.session_id == _SESSION

    def test_follow_up_default_delay(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched)

        scheduled = datetime.fromisoformat(follow_up.scheduled_at)
        trigger = datetime.fromisoformat(follow_up.trigger_at)
        delay = trigger - scheduled
        assert delay == timedelta(hours=DEFAULT_FOLLOW_UP_DELAY_HOURS)

    def test_follow_up_custom_delay(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched, delay_hours=72)

        scheduled = datetime.fromisoformat(follow_up.scheduled_at)
        trigger = datetime.fromisoformat(follow_up.trigger_at)
        delay = trigger - scheduled
        assert delay == timedelta(hours=72)

    def test_cannot_schedule_follow_up_without_dispatch(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )

        with pytest.raises(ValueError, match="Cannot schedule follow-up"):
            runtime.schedule_follow_up(approved)

    def test_cannot_schedule_follow_up_on_pending(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())

        with pytest.raises(ValueError, match="Cannot schedule follow-up"):
            runtime.schedule_follow_up(booking)

    def test_follow_up_metadata_includes_delay_and_booking(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        decision_id = str(uuid.uuid4())
        approved = runtime.approve_booking(
            booking, governance_decision_id=decision_id
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched, delay_hours=24)

        assert follow_up.metadata["delay_hours"] == 24
        assert follow_up.metadata["booking_id"] == dispatched.booking_id
        assert follow_up.metadata["governance_decision_id"] == decision_id


class TestFollowUpChannelGracefulDegradation:
    """Without MVP-7 context: uses originating ticket's channel."""

    def test_uses_source_channel_when_no_override(self) -> None:
        runtime = RepairBookingRuntime()
        request = _make_request(source_channel="whatsapp")
        booking = runtime.create_booking(request)
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched)

        assert follow_up.channel == "whatsapp"

    def test_uses_identity_resolved_channel_when_provided(self) -> None:
        runtime = RepairBookingRuntime()
        request = _make_request(source_channel="email")
        booking = runtime.create_booking(request)
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(
            dispatched, channel="whatsapp_identity_resolved"
        )

        assert follow_up.channel == "whatsapp_identity_resolved"

    def test_none_channel_graceful_degradation(self) -> None:
        runtime = RepairBookingRuntime()
        request = RepairBookingRequest(
            tenant_id=_TENANT,
            session_id=_SESSION,
            execution_id=_EXECUTION,
            source_channel=None,
        )
        booking = runtime.create_booking(request)
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched)

        assert follow_up.channel is None


class TestFollowUpGovernanceGate:
    """Follow-up draft routes through governance gate (never auto-sent)."""

    def test_follow_up_operational_act_defined(self) -> None:
        assert repair_booking_operational_act() == OperationalAct.FOLLOW_UP_TRIGGER

    def test_follow_up_act_value(self) -> None:
        assert OperationalAct.FOLLOW_UP_TRIGGER.value == "agents:follow_up_trigger"

    def test_follow_up_status_is_scheduled_not_sent(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)

        follow_up = runtime.schedule_follow_up(dispatched)

        assert follow_up.status == FollowUpStatus.SCHEDULED
        assert follow_up.status != FollowUpStatus.DRAFT_CREATED


class TestConnectorOperationDefinition:
    """Repair connector operation definition enforces SERVICE_COMMITMENT."""

    def test_operation_has_act_mode(self) -> None:
        op = build_repair_connector_operation()
        assert op["mode"] == "act"

    def test_operation_commitment_kind_is_service(self) -> None:
        op = build_repair_connector_operation()
        assert op["commitment_kind"] == CommitmentKind.SERVICE_COMMITMENT.value

    def test_operation_always_requires_approval(self) -> None:
        op = build_repair_connector_operation()
        assert op["approval_policy"] == "always_require_approval"

    def test_operation_has_input_schema(self) -> None:
        op = build_repair_connector_operation()
        assert "session_id" in op["input_schema"]["required"]
        assert "issue_description" in op["input_schema"]["required"]


class TestRepairBookingRecordSerialization:
    """Record serialization roundtrip."""

    def test_to_dict_roundtrip(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        d = booking.to_dict()
        restored = RepairBookingRecord.from_dict(d)

        assert restored.booking_id == booking.booking_id
        assert restored.tenant_id == booking.tenant_id
        assert restored.status == booking.status
        assert restored.commitment_kind == booking.commitment_kind
        assert restored.product_sku == booking.product_sku


class TestFollowUpScheduleSerialization:
    """Follow-up schedule serialization roundtrip."""

    def test_to_dict_roundtrip(self) -> None:
        runtime = RepairBookingRuntime()
        booking = runtime.create_booking(_make_request())
        approved = runtime.approve_booking(
            booking, governance_decision_id=str(uuid.uuid4())
        )
        dispatched = runtime.mark_dispatched(approved)
        follow_up = runtime.schedule_follow_up(dispatched, delay_hours=24)

        d = follow_up.to_dict()
        restored = FollowUpSchedule.from_dict(d)

        assert restored.follow_up_id == follow_up.follow_up_id
        assert restored.tenant_id == follow_up.tenant_id
        assert restored.booking_id == follow_up.booking_id
        assert restored.status == follow_up.status
        assert restored.trigger_at == follow_up.trigger_at
        assert restored.channel == follow_up.channel


class TestServiceCommitmentInActionGovernance:
    """SERVICE_COMMITMENT routes through the existing money/goods gate."""

    def test_service_commitment_is_commitment_kind_member(self) -> None:
        assert CommitmentKind.SERVICE_COMMITMENT.value == "service_commitment"

    def test_connector_operation_with_service_commitment_requires_governance(self) -> None:
        from app.agents.tools.connectors.generic import (
            OperationDefinition,
            OperationMode,
        )
        op = OperationDefinition(
            operation_id="repair_dispatch",
            mode=OperationMode.ACT,
            commitment_kind=CommitmentKind.SERVICE_COMMITMENT,
        )
        assert op.requires_governance is True
        assert op.commitment_kind == CommitmentKind.SERVICE_COMMITMENT
