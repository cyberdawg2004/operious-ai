from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.boundary.outbound import (
    InMemoryEmailDeliveryRepository,
    SesEmailSendRequest,
    SesEmailSendResponse,
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
from app.services.email_customer_reply_service import (
    EmailCustomerReplyGovernanceError,
    EmailCustomerReplySendService,
)
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import TenantChannelConfigurationRecord

TENANT_ID = "tenant-email-send"
OTHER_TENANT_ID = "tenant-email-other"
SOURCE = "support@example.com"
RECIPIENT = "customer@example.net"
SUBJECT = "Re: PowerCore support"
DECISION_ID = uuid.UUID("4e0a3987-5197-5e3d-bd74-6043fc638f8f")
PROPOSAL_ID = uuid.UUID("bd35e68d-ce33-51ec-b5ad-38f462e97a59")
DRAFT_ID = uuid.UUID("4daa3c44-d32d-5ecd-b4c5-e80b40d7e0d4")
SESSION_ID = "0e3b663b-aa09-5434-ae0b-20e64723abf0"
EXECUTION_ID = "712b1a73-7f1d-5fbf-85ef-c9da26fda4d6"
DISPATCH_ID = "10e86136-368b-5875-80a2-9de36d4563e5"
NOW = datetime(2026, 6, 8, tzinfo=timezone.utc)
REPLY = "Thanks for the details. Please try resetting the device once."


class _TenantRuntime:
    def __init__(self) -> None:
        self.credentials = {
            "access_key_id": "AKIASECRET",
            "secret_access_key": "secret-ses-key",
            "region": "us-east-1",
            "source_email_address": SOURCE,
            "endpoint_url": "https://email.test",
            "configuration_set_name": "operious-test",
        }

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        assert tenant_id == TENANT_ID
        assert channel_type is TenantChannelType.EMAIL
        return dict(self.credentials)

    async def resolve_active_channel_for_routing_address(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
        expected_tenant_id: str | None = None,
    ) -> TenantChannelConfigurationRecord | None:
        if (
            channel_type is not TenantChannelType.EMAIL
            or routing_address != SOURCE
            or expected_tenant_id != TENANT_ID
        ):
            return None
        return TenantChannelConfigurationRecord(
            config_id=derive_channel_configuration_id(
                tenant_id=TENANT_ID,
                channel_type=TenantChannelType.EMAIL,
            ),
            tenant_id=TENANT_ID,
            channel_type=TenantChannelType.EMAIL,
            status=TenantChannelStatus.ACTIVE,
            routing_address=SOURCE,
            credentials_enc=b"",
            webhook_secret="arn:aws:sns:us-east-1:123456789012:operious-email",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )


class _Sender:
    def __init__(self) -> None:
        self.requests: list[SesEmailSendRequest] = []

    async def send_email(
        self,
        request: SesEmailSendRequest,
    ) -> SesEmailSendResponse:
        self.requests.append(request)
        return SesEmailSendResponse(
            provider_message_id=f"ses-message-{len(self.requests)}",
            status_code=200,
        )


@pytest.mark.asyncio
async def test_governed_allow_email_transmits_once_and_ledgers_provider_id() -> None:
    service, sender, deliveries = await _service()

    result = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_email_address=RECIPIENT,
        subject=SUBJECT,
        in_reply_to_message_id="<customer-001@example.net>",
        references_header="<thread-root@example.net> <customer-001@example.net>",
    )

    assert result.transmitted is True
    assert result.status == "sent"
    assert result.provider_message_id == "ses-message-1"
    assert len(sender.requests) == 1
    assert sender.requests[0].secret_access_key == "secret-ses-key"
    assert sender.requests[0].in_reply_to_message_id == "<customer-001@example.net>"
    record = await deliveries.get_delivery(
        uuid.UUID(result.delivery_id),
        expected_tenant_id=TENANT_ID,
    )
    assert record is not None
    assert record.provider_message_id == "ses-message-1"
    assert record.in_reply_to_message_id == "<customer-001@example.net>"
    assert "secret-ses-key" not in str(result)
    assert "secret-ses-key" not in str(record)


@pytest.mark.asyncio
async def test_reprocessing_same_allowed_email_does_not_double_send() -> None:
    service, sender, _deliveries = await _service()

    first = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_email_address=RECIPIENT,
        subject=SUBJECT,
    )
    second = await service.send_draft(
        draft_id=str(DRAFT_ID),
        tenant_id=TENANT_ID,
        expected_tenant_id=TENANT_ID,
        recipient_email_address=RECIPIENT,
        subject=SUBJECT,
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
async def test_non_allow_pending_or_no_governance_email_never_transmits(
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

    with pytest.raises(EmailCustomerReplyGovernanceError):
        await service.send_draft(
            draft_id=str(DRAFT_ID),
            tenant_id=TENANT_ID,
            expected_tenant_id=TENANT_ID,
            recipient_email_address=RECIPIENT,
            subject=SUBJECT,
        )

    assert sender.requests == []


@pytest.mark.asyncio
async def test_email_send_is_tenant_scoped() -> None:
    service, sender, _deliveries = await _service()

    with pytest.raises(ValueError):
        await service.send_draft(
            draft_id=str(DRAFT_ID),
            tenant_id=TENANT_ID,
            expected_tenant_id=OTHER_TENANT_ID,
            recipient_email_address=RECIPIENT,
            subject=SUBJECT,
        )

    assert sender.requests == []


def test_email_delivery_migration_is_additive_rls_ledger() -> None:
    source = Path(
        "apps/backend/migrations/versions/0080_email_customer_reply_deliveries.py"
    ).read_text(encoding="utf-8")

    assert "email_customer_reply_deliveries" in source
    assert "uq_email_delivery_tenant_draft_governance" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "resolve_webhook_routing_secret_by_topic_arn" in source


async def _service(
    *,
    draft_status: ResolutionOutboundDraftStatus = ResolutionOutboundDraftStatus.READY,
    proposal_status: ResolutionProposalStatus = ResolutionProposalStatus.SEND_ELIGIBLE,
    decision: Decision = Decision.ALLOW,
    governance_decision_id: uuid.UUID | None = DECISION_ID,
) -> tuple[EmailCustomerReplySendService, _Sender, InMemoryEmailDeliveryRepository]:
    resolution = InMemoryResolutionProposalPersistence()
    await resolution.create_resolution_proposal(
        _proposal(
            status=proposal_status,
            governance_decision_id=governance_decision_id,
        ),
        expected_tenant_id=TENANT_ID,
    )
    await resolution.create_resolution_outbound_draft(
        _draft(
            status=draft_status,
            governance_decision_id=governance_decision_id,
        ),
        expected_tenant_id=TENANT_ID,
    )
    governance = InMemoryGovernanceRepository()
    if governance_decision_id is not None:
        await governance.record_decision(
            _decision(governance_decision_id, decision=decision)
        )
    deliveries = InMemoryEmailDeliveryRepository()
    sender = _Sender()
    return (
        EmailCustomerReplySendService(
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
) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply=REPLY,
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
        draft_body=REPLY,
        draft_body_sha256=_sha256(REPLY),
        resolution_category="technical_support",
        confidence=0.91,
        created_at=NOW,
        updated_at=NOW,
        metadata={"canonical_reply": REPLY, "localized_reply": REPLY},
    )


def _decision(
    decision_id: uuid.UUID,
    *,
    decision: Decision,
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
            "proposed_reply_sha256": _sha256(REPLY),
        },
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
