from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from app.boundary.outbound import (
    InMemoryWhatsAppDeliveryRepository,
    WhatsAppTextMessageRequest,
    WhatsAppTextMessageResponse,
)
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
)
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    as_resolution_outbound_draft_id,
    as_resolution_proposal_id,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.services.whatsapp_customer_reply_service import (
    WhatsAppCustomerReplyGovernanceError,
    WhatsAppCustomerReplySendService,
)
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import TenantChannelConfigurationRecord

TENANT_ID = "tenant-whatsapp-send"
OTHER_TENANT_ID = "tenant-whatsapp-other"
PHONE_NUMBER_ID = "1234567890"
RECIPIENT = "15551234567"
DECISION_ID = uuid.UUID("09d34380-97de-5d3c-a11d-96305adf91f5")
PROPOSAL_ID = uuid.UUID("b65f5aca-8bbf-5c4c-9e8b-69a314a6a8fa")
DRAFT_ID = uuid.UUID("4f85fc0f-a59b-51ab-95c9-393f99425e18")
SESSION_ID = "1e3d76ee-f1fa-5ddf-8dd6-4dc7d51ac3fb"
EXECUTION_ID = "ceab289a-6f09-5548-bc97-5e2447f87240"
DISPATCH_ID = "16f3244d-a14b-5558-995e-e9da8e462f36"
NOW = datetime(2026, 6, 8, tzinfo=timezone.utc)
REPLY = "Thanks for the details. Please try resetting the device once."


class _TenantRuntime:
    def __init__(self) -> None:
        self.credentials = {
            "access_token": "secret-whatsapp-token",
            "phone_number_id": PHONE_NUMBER_ID,
            "graph_api_version": "v-test",
            "graph_api_base_url": "https://graph.test",
        }

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        assert tenant_id == TENANT_ID
        assert channel_type is TenantChannelType.WHATSAPP
        return dict(self.credentials)

    async def resolve_active_channel_for_routing_address(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
        expected_tenant_id: str | None = None,
    ) -> TenantChannelConfigurationRecord | None:
        if (
            channel_type is not TenantChannelType.WHATSAPP
            or routing_address != PHONE_NUMBER_ID
            or expected_tenant_id != TENANT_ID
        ):
            return None
        return TenantChannelConfigurationRecord(
            config_id=derive_channel_configuration_id(
                tenant_id=TENANT_ID,
                channel_type=TenantChannelType.WHATSAPP,
            ),
            tenant_id=TENANT_ID,
            channel_type=TenantChannelType.WHATSAPP,
            status=TenantChannelStatus.ACTIVE,
            routing_address=PHONE_NUMBER_ID,
            credentials_enc=b"",
            webhook_secret="webhook-secret",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )


class _Sender:
    def __init__(self) -> None:
        self.requests: list[WhatsAppTextMessageRequest] = []

    async def send_text_message(
        self,
        request: WhatsAppTextMessageRequest,
    ) -> WhatsAppTextMessageResponse:
        self.requests.append(request)
        return WhatsAppTextMessageResponse(
            provider_message_id=f"wamid.{len(self.requests)}",
            status_code=200,
        )


@pytest.mark.asyncio
async def test_governed_allow_reply_transmits_once_and_ledgers_provider_id() -> None:
    service, sender, deliveries = await _service()

    result = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_phone_number=RECIPIENT,
    )

    assert result.transmitted is True
    assert result.status == "sent"
    assert result.provider_message_id == "wamid.1"
    assert len(sender.requests) == 1
    assert sender.requests[0].access_token == "secret-whatsapp-token"
    record = await deliveries.get_delivery(
        uuid.UUID(result.delivery_id),
        expected_tenant_id=TENANT_ID,
    )
    assert record is not None
    assert record.provider_message_id == "wamid.1"
    assert "secret-whatsapp-token" not in str(result)
    assert "secret-whatsapp-token" not in str(record)


@pytest.mark.asyncio
async def test_reprocessing_same_allowed_reply_does_not_double_send() -> None:
    service, sender, _deliveries = await _service()

    first = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_phone_number=RECIPIENT,
    )
    second = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_phone_number=RECIPIENT,
    )

    assert first.transmitted is True
    assert second.transmitted is False
    assert second.idempotent_replay is True
    assert second.status == "already_sent"
    assert second.provider_message_id == first.provider_message_id
    assert len(sender.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("draft_status", "proposal_status", "decision", "decision_id"),
    [
        (
            ResolutionOutboundDraftStatus.READY,
            ResolutionProposalStatus.SEND_ELIGIBLE,
            Decision.DENY,
            DECISION_ID,
        ),
        (
            ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL,
            ResolutionProposalStatus.SEND_ELIGIBLE,
            Decision.ALLOW,
            DECISION_ID,
        ),
        (
            ResolutionOutboundDraftStatus.READY,
            ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
            Decision.ALLOW,
            DECISION_ID,
        ),
        (
            ResolutionOutboundDraftStatus.READY,
            ResolutionProposalStatus.SEND_ELIGIBLE,
            Decision.ALLOW,
            None,
        ),
    ],
)
async def test_non_allow_pending_or_no_governance_draft_never_transmits(
    draft_status: ResolutionOutboundDraftStatus,
    proposal_status: ResolutionProposalStatus,
    decision: Decision,
    decision_id: uuid.UUID | None,
) -> None:
    service, sender, _deliveries = await _service(
        draft_status=draft_status,
        proposal_status=proposal_status,
        decision=decision,
        governance_decision_id=decision_id,
    )

    with pytest.raises(WhatsAppCustomerReplyGovernanceError):
        await service.send_draft(
            draft_id=str(DRAFT_ID),
            tenant_id=TENANT_ID,
            expected_tenant_id=TENANT_ID,
            recipient_phone_number=RECIPIENT,
        )

    assert sender.requests == []


@pytest.mark.asyncio
async def test_send_is_tenant_scoped() -> None:
    service, sender, _deliveries = await _service()

    with pytest.raises(ValueError):
        await service.send_draft(
            draft_id=str(DRAFT_ID),
            tenant_id=TENANT_ID,
            expected_tenant_id=OTHER_TENANT_ID,
            recipient_phone_number=RECIPIENT,
        )

    assert sender.requests == []


@pytest.mark.asyncio
async def test_citation_marks_are_stripped_before_whatsapp_transmission() -> None:
    """Priority 1 break-control: a governed reply with "[1]"-style citation
    marks must never reach the customer over WhatsApp -- email already
    strips these (render_customer_email_body); WhatsApp must too."""
    reply_with_citation = (
        "We checked your order and confirmed it's within warranty [1]."
    )
    service, sender, _deliveries = await _service(reply=reply_with_citation)

    result = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_phone_number=RECIPIENT,
    )

    assert result.transmitted is True
    assert len(sender.requests) == 1
    transmitted_body = sender.requests[0].body
    assert "[1]" not in transmitted_body
    assert transmitted_body == (
        "We checked your order and confirmed it's within warranty."
    )


async def _service(
    *,
    draft_status: ResolutionOutboundDraftStatus = ResolutionOutboundDraftStatus.READY,
    proposal_status: ResolutionProposalStatus = ResolutionProposalStatus.SEND_ELIGIBLE,
    decision: Decision = Decision.ALLOW,
    governance_decision_id: uuid.UUID | None = DECISION_ID,
    reply: str = REPLY,
) -> tuple[
    WhatsAppCustomerReplySendService,
    _Sender,
    InMemoryWhatsAppDeliveryRepository,
]:
    resolution = InMemoryResolutionProposalPersistence()
    await resolution.create_resolution_proposal(
        _proposal(
            status=proposal_status,
            governance_decision_id=governance_decision_id,
            reply=reply,
        ),
        expected_tenant_id=TENANT_ID,
    )
    await resolution.create_resolution_outbound_draft(
        _draft(
            status=draft_status,
            governance_decision_id=governance_decision_id,
            reply=reply,
        ),
        expected_tenant_id=TENANT_ID,
    )
    governance = InMemoryGovernanceRepository()
    if governance_decision_id is not None:
        await governance.record_decision(
            _decision(governance_decision_id, decision=decision, reply=reply)
        )
    deliveries = InMemoryWhatsAppDeliveryRepository()
    sender = _Sender()
    return (
        WhatsAppCustomerReplySendService(
            draft_repository=resolution,
            proposal_repository=resolution,
            governance_repository=governance,
            tenant_runtime=_TenantRuntime(),
            delivery_repository=deliveries,
            sender=sender,
        ),
        sender,
        deliveries,
    )


def _proposal(
    *,
    status: ResolutionProposalStatus,
    governance_decision_id: uuid.UUID | None,
    reply: str = REPLY,
) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply=reply,
        resolution_category="technical_support",
        confidence=0.91,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=(
            ResolutionGovernanceVerdict.ALLOW
            if status is ResolutionProposalStatus.SEND_ELIGIBLE
            else ResolutionGovernanceVerdict.REQUIRE_APPROVAL
        ),
        autonomy_decision=(
            ResolutionAutonomyDecision.AUTO_APPROVED
            if status is ResolutionProposalStatus.SEND_ELIGIBLE
            else ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
        ),
        status=status,
        created_at=NOW,
        updated_at=NOW,
        governance_decision_id=governance_decision_id,
        recommended_actions=(),
        evidence=({"source": "manual", "rank": 1},),
        source_language="en",
    )


def _draft(
    *,
    status: ResolutionOutboundDraftStatus,
    governance_decision_id: uuid.UUID | None,
    reply: str = REPLY,
) -> ResolutionOutboundDraftRecord:
    return ResolutionOutboundDraftRecord(
        draft_id=as_resolution_outbound_draft_id(DRAFT_ID),
        tenant_id=TENANT_ID,
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        governance_decision_id=governance_decision_id,
        status=status,
        draft_body=reply,
        draft_body_sha256=_sha256(reply),
        resolution_category="technical_support",
        confidence=0.91,
        created_at=NOW,
        updated_at=NOW,
        metadata={"canonical_reply": reply, "localized_reply": reply},
    )


def _decision(
    decision_id: uuid.UUID,
    *,
    decision: Decision,
    reply: str = REPLY,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=str(decision_id),
        decision=decision.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="resolution.standard",
        reason="test decision",
        decided_at=NOW.isoformat(),
        tenant_id=TENANT_ID,
        subject_kind="communication",
        metadata={
            "proposal_id": str(PROPOSAL_ID),
            "proposed_reply_sha256": _sha256(reply),
        },
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
