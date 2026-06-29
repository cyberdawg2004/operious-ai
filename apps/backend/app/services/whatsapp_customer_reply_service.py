"""Governed WhatsApp customer-reply send orchestration."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from app.boundary.outbound import (
    WhatsAppCustomerReplyDeliveryRecord,
    WhatsAppDeliveryRepository,
    WhatsAppDeliveryStatus,
    WhatsAppGraphAPIError,
    WhatsAppGraphSender,
    WhatsAppTextMessageRequest,
    WhatsAppTextMessageResponse,
    derive_whatsapp_customer_reply_delivery_id,
)
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.governance.enums import Decision
from app.governance.persistence import BaseGovernanceRepository
from app.resolution.enums import (
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
)
from app.resolution.persistence import (
    ResolutionOutboundDraftPersistenceProtocol,
    ResolutionProposalPersistenceProtocol,
)
from app.resolution.persistence.records import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.runtime.customer_whatsapp_template import render_customer_whatsapp_body
from app.tenant.enums import TenantChannelType
from app.tenant.persistence import TenantChannelConfigurationRecord

_GRAPH_API_BASE_URL = "https://graph.facebook.com"
_DEFAULT_TIMEOUT_SECONDS = 10.0


class WhatsAppCustomerReplySendError(RuntimeError):
    """Base customer-reply send failure."""


class WhatsAppCustomerReplyNotFoundError(WhatsAppCustomerReplySendError):
    """The draft or proposal is not visible for the tenant."""


class WhatsAppCustomerReplyGovernanceError(WhatsAppCustomerReplySendError):
    """The draft is not governed-send eligible."""


class WhatsAppCustomerReplyConfigurationError(WhatsAppCustomerReplySendError):
    """Tenant WhatsApp send configuration is missing or invalid."""


class WhatsAppCustomerReplyProviderError(WhatsAppCustomerReplySendError):
    """WhatsApp provider rejected or failed the send attempt."""


@dataclass(frozen=True, slots=True)
class WhatsAppCustomerReplySendResult:
    delivery_id: str
    status: Literal["sent", "already_sent", "pending"]
    provider_message_id: str | None
    transmitted: bool
    idempotent_replay: bool


class TenantWhatsAppRuntimeProtocol(Protocol):
    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]: ...

    async def resolve_active_channel_for_routing_address(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
        expected_tenant_id: str | None = None,
    ) -> TenantChannelConfigurationRecord | None: ...


class WhatsAppTextSenderProtocol(Protocol):
    async def send_text_message(
        self,
        request: WhatsAppTextMessageRequest,
    ) -> WhatsAppTextMessageResponse: ...


class TransactionControl(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _WhatsAppCredentials:
    access_token: str
    phone_number_id: str
    graph_api_version: str
    graph_api_base_url: str


class WhatsAppCustomerReplySendService:
    """Send a resolution draft only after persisted tenant-scoped ALLOW."""

    def __init__(
        self,
        *,
        draft_repository: ResolutionOutboundDraftPersistenceProtocol,
        proposal_repository: ResolutionProposalPersistenceProtocol,
        governance_repository: BaseGovernanceRepository,
        tenant_runtime: TenantWhatsAppRuntimeProtocol,
        delivery_repository: WhatsAppDeliveryRepository,
        sender: WhatsAppTextSenderProtocol | None = None,
        session: TransactionControl | None = None,
    ) -> None:
        self._draft_repository = draft_repository
        self._proposal_repository = proposal_repository
        self._governance_repository = governance_repository
        self._tenant_runtime = tenant_runtime
        self._delivery_repository = delivery_repository
        self._sender = sender or WhatsAppGraphSender()
        self._session = session

    async def send_draft(
        self,
        *,
        draft_id: str,
        tenant_id: str,
        expected_tenant_id: str,
        recipient_phone_number: str,
        phone_number_id: str | None = None,
        expected_governance_decision_id: uuid.UUID | str | None = None,
        expected_draft_body_sha256: str | None = None,
        allow_failed_delivery_retry: bool = False,
    ) -> WhatsAppCustomerReplySendResult:
        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        previous_tenant = get_current_tenant()
        set_current_tenant(expected_tenant_id)
        try:
            return await self._send_draft_scoped(
                draft_id=draft_id,
                tenant_id=tenant_id,
                expected_tenant_id=expected_tenant_id,
                recipient_phone_number=recipient_phone_number,
                phone_number_id=phone_number_id,
                expected_governance_decision_id=expected_governance_decision_id,
                expected_draft_body_sha256=expected_draft_body_sha256,
                allow_failed_delivery_retry=allow_failed_delivery_retry,
            )
        except Exception:
            await self._rollback()
            raise
        finally:
            set_current_tenant(previous_tenant)

    async def _send_draft_scoped(
        self,
        *,
        draft_id: str,
        tenant_id: str,
        expected_tenant_id: str,
        recipient_phone_number: str,
        phone_number_id: str | None,
        expected_governance_decision_id: uuid.UUID | str | None,
        expected_draft_body_sha256: str | None,
        allow_failed_delivery_retry: bool,
    ) -> WhatsAppCustomerReplySendResult:
        recipient = _required_text("recipient_phone_number", recipient_phone_number)
        draft = await self._load_sendable_draft(
            draft_id=draft_id,
            expected_tenant_id=expected_tenant_id,
        )
        proposal = await self._load_sendable_proposal(
            proposal_id=str(draft.proposal_id),
            expected_tenant_id=expected_tenant_id,
        )
        _assert_expected_outbox_guards(
            draft=draft,
            expected_governance_decision_id=expected_governance_decision_id,
            expected_draft_body_sha256=expected_draft_body_sha256,
        )
        self._assert_draft_and_proposal_lineage(draft=draft, proposal=proposal)
        await self._assert_persisted_governance_allow(
            draft=draft,
            proposal=proposal,
            expected_tenant_id=expected_tenant_id,
        )
        credentials = await self._load_whatsapp_credentials(
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
        )
        governance_decision_id = _required_governance_decision_id(
            draft.governance_decision_id
        )
        delivery_id = derive_whatsapp_customer_reply_delivery_id(
            tenant_id=tenant_id,
            draft_id=draft.draft_id,
            governance_decision_id=governance_decision_id,
        )
        now = datetime.now(timezone.utc)
        delivery, created = await self._delivery_repository.reserve_delivery(
            WhatsAppCustomerReplyDeliveryRecord(
                delivery_id=delivery_id,
                tenant_id=tenant_id,
                draft_id=uuid.UUID(str(draft.draft_id)),
                proposal_id=uuid.UUID(str(draft.proposal_id)),
                governance_decision_id=governance_decision_id,
                phone_number_id=credentials.phone_number_id,
                recipient_phone_number=recipient,
                draft_body_sha256=draft.draft_body_sha256,
                status=WhatsAppDeliveryStatus.PENDING,
                provider_message_id=None,
                provider_status_code=None,
                error_code=None,
                created_at=now,
                updated_at=now,
                sent_at=None,
                metadata={
                    "channel": TenantChannelType.WHATSAPP.value,
                    "source": "resolution_outbound_draft",
                    "proposal_id": str(draft.proposal_id),
                },
            ),
            expected_tenant_id=expected_tenant_id,
        )
        await self._commit()
        self._assert_delivery_matches_request(
            delivery=delivery,
            phone_number_id=credentials.phone_number_id,
            recipient_phone_number=recipient,
            draft=draft,
        )
        should_transmit = created
        if not created:
            if delivery.status is WhatsAppDeliveryStatus.SENT:
                return WhatsAppCustomerReplySendResult(
                    delivery_id=str(delivery.delivery_id),
                    status="already_sent",
                    provider_message_id=delivery.provider_message_id,
                    transmitted=False,
                    idempotent_replay=True,
                )
            if delivery.status is WhatsAppDeliveryStatus.PENDING:
                return WhatsAppCustomerReplySendResult(
                    delivery_id=str(delivery.delivery_id),
                    status="pending",
                    provider_message_id=delivery.provider_message_id,
                    transmitted=False,
                    idempotent_replay=True,
                )
            if allow_failed_delivery_retry and _whatsapp_delivery_error_is_retryable(
                delivery.error_code
            ):
                should_transmit = True
            else:
                raise WhatsAppCustomerReplyProviderError(
                    "whatsapp delivery previously failed and is not auto-retried"
                )

        if should_transmit:
            try:
                response = await self._sender.send_text_message(
                    WhatsAppTextMessageRequest(
                        graph_api_base_url=credentials.graph_api_base_url,
                        graph_api_version=credentials.graph_api_version,
                        phone_number_id=credentials.phone_number_id,
                        access_token=credentials.access_token,
                        recipient_phone_number=recipient,
                        body=render_customer_whatsapp_body(body=draft.draft_body),
                        timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
                    )
                )
            except WhatsAppGraphAPIError as exc:
                await self._mark_failed(
                    delivery_id=delivery_id,
                    expected_tenant_id=expected_tenant_id,
                    error_code=f"whatsapp_graph_http_{exc.status_code}",
                    provider_status_code=exc.status_code,
                )
                raise WhatsAppCustomerReplyProviderError(
                    "whatsapp graph api rejected the message"
                ) from exc
            except Exception as exc:
                await self._mark_failed(
                    delivery_id=delivery_id,
                    expected_tenant_id=expected_tenant_id,
                    error_code=exc.__class__.__name__,
                )
                raise WhatsAppCustomerReplyProviderError(
                    "whatsapp graph api send failed"
                ) from exc

            sent = await self._delivery_repository.mark_sent(
                delivery_id,
                expected_tenant_id=expected_tenant_id,
                provider_message_id=response.provider_message_id,
                provider_status_code=response.status_code,
                sent_at=datetime.now(timezone.utc),
            )
            await self._commit()
            return WhatsAppCustomerReplySendResult(
                delivery_id=str(sent.delivery_id),
                status="sent",
                provider_message_id=sent.provider_message_id,
                transmitted=True,
                idempotent_replay=False,
            )
        raise WhatsAppCustomerReplyProviderError(
            "whatsapp delivery was not transmitted"
        )

    async def _load_sendable_draft(
        self,
        *,
        draft_id: str,
        expected_tenant_id: str,
    ) -> ResolutionOutboundDraftRecord:
        draft = await self._draft_repository.get_resolution_outbound_draft(
            draft_id,
            expected_tenant_id=expected_tenant_id,
        )
        if draft is None:
            raise WhatsAppCustomerReplyNotFoundError("outbound draft not found")
        if draft.status is not ResolutionOutboundDraftStatus.READY:
            raise WhatsAppCustomerReplyGovernanceError(
                "outbound draft is not ready to send"
            )
        if draft.governance_decision_id is None:
            raise WhatsAppCustomerReplyGovernanceError(
                "outbound draft has no governance decision"
            )
        if draft.draft_body_sha256 != _sha256_text(draft.draft_body):
            raise WhatsAppCustomerReplyGovernanceError(
                "outbound draft body hash mismatch"
            )
        localized = draft.metadata.get("localized_reply")
        if isinstance(localized, str) and localized != draft.draft_body:
            raise WhatsAppCustomerReplyGovernanceError(
                "outbound draft localized reply mismatch"
            )
        return draft

    async def _load_sendable_proposal(
        self,
        *,
        proposal_id: str,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord:
        proposal = await self._proposal_repository.get_resolution_proposal(
            proposal_id,
            expected_tenant_id=expected_tenant_id,
        )
        if proposal is None:
            raise WhatsAppCustomerReplyNotFoundError("resolution proposal not found")
        if (
            proposal.status is not ResolutionProposalStatus.SEND_ELIGIBLE
            or proposal.governance_decision_id is None
        ):
            raise WhatsAppCustomerReplyGovernanceError(
                "resolution proposal is not send eligible"
            )
        return proposal

    def _assert_draft_and_proposal_lineage(
        self,
        *,
        draft: ResolutionOutboundDraftRecord,
        proposal: ResolutionProposalRecord,
    ) -> None:
        if draft.tenant_id != proposal.tenant_id:
            raise WhatsAppCustomerReplyGovernanceError("tenant lineage mismatch")
        if str(draft.proposal_id) != str(proposal.proposal_id):
            raise WhatsAppCustomerReplyGovernanceError("proposal lineage mismatch")
        if draft.governance_decision_id != proposal.governance_decision_id:
            raise WhatsAppCustomerReplyGovernanceError(
                "governance decision lineage mismatch"
            )

    async def _assert_persisted_governance_allow(
        self,
        *,
        draft: ResolutionOutboundDraftRecord,
        proposal: ResolutionProposalRecord,
        expected_tenant_id: str,
    ) -> None:
        if draft.governance_decision_id is None:
            raise WhatsAppCustomerReplyGovernanceError(
                "outbound draft has no governance decision"
            )
        decision = await self._governance_repository.get_decision(
            str(draft.governance_decision_id),
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None:
            raise WhatsAppCustomerReplyGovernanceError(
                "governance decision is not visible for tenant"
            )
        if decision.decision != Decision.ALLOW.value:
            raise WhatsAppCustomerReplyGovernanceError(
                "governance decision is not allow"
            )
        if decision.tenant_id != expected_tenant_id:
            raise WhatsAppCustomerReplyGovernanceError(
                "governance decision tenant mismatch"
            )
        metadata = dict(decision.metadata)
        if str(metadata.get("proposal_id")) != str(proposal.proposal_id):
            raise WhatsAppCustomerReplyGovernanceError(
                "governance decision proposal mismatch"
            )
        governed_reply = draft.metadata.get("canonical_reply")
        if not isinstance(governed_reply, str) or not governed_reply:
            governed_reply = draft.draft_body
        governed_hash = _sha256_text(governed_reply)
        if metadata.get("proposed_reply_sha256") != governed_hash:
            raise WhatsAppCustomerReplyGovernanceError(
                "governance decision reply hash mismatch"
            )

    async def _load_whatsapp_credentials(
        self,
        *,
        tenant_id: str,
        phone_number_id: str | None,
    ) -> _WhatsAppCredentials:
        credentials = await self._tenant_runtime.load_channel_credentials(
            tenant_id=tenant_id,
            channel_type=TenantChannelType.WHATSAPP,
        )
        resolved_phone_number_id = _resolved_phone_number_id(
            credentials=credentials,
            requested_phone_number_id=phone_number_id,
        )
        channel_config = (
            await self._tenant_runtime.resolve_active_channel_for_routing_address(
                channel_type=TenantChannelType.WHATSAPP,
                routing_address=resolved_phone_number_id,
                expected_tenant_id=tenant_id,
            )
        )
        if channel_config is None:
            raise WhatsAppCustomerReplyConfigurationError(
                "active whatsapp channel route is not configured"
            )
        return _WhatsAppCredentials(
            access_token=_credential_string(
                credentials,
                "access_token",
                "graph_api_access_token",
                "bearer_token",
            ),
            phone_number_id=resolved_phone_number_id,
            graph_api_version=_credential_string(credentials, "graph_api_version"),
            graph_api_base_url=_optional_credential_string(
                credentials,
                "graph_api_base_url",
                default=_GRAPH_API_BASE_URL,
            ),
        )

    def _assert_delivery_matches_request(
        self,
        *,
        delivery: WhatsAppCustomerReplyDeliveryRecord,
        phone_number_id: str,
        recipient_phone_number: str,
        draft: ResolutionOutboundDraftRecord,
    ) -> None:
        if delivery.phone_number_id != phone_number_id:
            raise WhatsAppCustomerReplyGovernanceError(
                "delivery idempotency phone_number_id conflict"
            )
        if delivery.recipient_phone_number != recipient_phone_number:
            raise WhatsAppCustomerReplyGovernanceError(
                "delivery idempotency recipient conflict"
            )
        if delivery.draft_body_sha256 != draft.draft_body_sha256:
            raise WhatsAppCustomerReplyGovernanceError(
                "delivery idempotency draft body conflict"
            )

    async def _mark_failed(
        self,
        *,
        delivery_id: uuid.UUID,
        expected_tenant_id: str,
        error_code: str,
        provider_status_code: int | None = None,
    ) -> None:
        await self._delivery_repository.mark_failed(
            delivery_id,
            expected_tenant_id=expected_tenant_id,
            error_code=error_code,
            provider_status_code=provider_status_code,
            failed_at=datetime.now(timezone.utc),
        )
        await self._commit()

    async def _commit(self) -> None:
        if self._session is not None:
            await self._session.commit()

    async def _rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()


def _resolved_phone_number_id(
    *,
    credentials: Mapping[str, Any],
    requested_phone_number_id: str | None,
) -> str:
    configured = _optional_credential_string(
        credentials,
        "phone_number_id",
        "whatsapp_phone_number_id",
        default="",
    )
    requested = (requested_phone_number_id or "").strip()
    if requested and configured and requested != configured:
        raise WhatsAppCustomerReplyConfigurationError(
            "requested phone_number_id does not match tenant credentials"
        )
    resolved = requested or configured
    if not resolved:
        raise WhatsAppCustomerReplyConfigurationError(
            "tenant whatsapp phone_number_id is required"
        )
    return resolved


def _assert_expected_outbox_guards(
    *,
    draft: ResolutionOutboundDraftRecord,
    expected_governance_decision_id: uuid.UUID | str | None,
    expected_draft_body_sha256: str | None,
) -> None:
    if expected_governance_decision_id is not None:
        expected_decision_id = uuid.UUID(str(expected_governance_decision_id))
        if draft.governance_decision_id != expected_decision_id:
            raise WhatsAppCustomerReplyGovernanceError(
                "outbox governance decision mismatch"
            )
    if expected_draft_body_sha256 is not None:
        expected_digest = expected_draft_body_sha256.strip().lower()
        if draft.draft_body_sha256 != expected_digest:
            raise WhatsAppCustomerReplyGovernanceError(
                "outbox draft body hash mismatch"
            )


def _whatsapp_delivery_error_is_retryable(error_code: str | None) -> bool:
    if error_code is None:
        return False
    if not error_code.startswith("whatsapp_graph_http_"):
        return False
    try:
        status_code = int(error_code.removeprefix("whatsapp_graph_http_"))
    except ValueError:
        return False
    return status_code == 429 or status_code >= 500


def _credential_string(
    credentials: Mapping[str, Any],
    *keys: str,
) -> str:
    value = _optional_credential_string(credentials, *keys, default="")
    if not value:
        raise WhatsAppCustomerReplyConfigurationError(
            f"tenant whatsapp credential {keys[0]} is required"
        )
    return value


def _optional_credential_string(
    credentials: Mapping[str, Any],
    *keys: str,
    default: str,
) -> str:
    for key in keys:
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _required_text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_governance_decision_id(value: uuid.UUID | None) -> uuid.UUID:
    if value is None:
        raise WhatsAppCustomerReplyGovernanceError(
            "outbound draft has no governance decision"
        )
    return value


__all__ = [
    "WhatsAppCustomerReplyConfigurationError",
    "WhatsAppCustomerReplyGovernanceError",
    "WhatsAppCustomerReplyNotFoundError",
    "WhatsAppCustomerReplyProviderError",
    "WhatsAppCustomerReplySendError",
    "WhatsAppCustomerReplySendResult",
    "WhatsAppCustomerReplySendService",
]
