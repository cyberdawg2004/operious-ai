"""Governed AWS SES customer-reply send orchestration."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from app.boundary.outbound import (
    EmailCustomerReplyDeliveryRecord,
    EmailDeliveryRepository,
    EmailDeliveryStatus,
    SesEmailSendRequest,
    SesEmailSendResponse,
    SesV2EmailSender,
    SesV2SendError,
    derive_email_customer_reply_delivery_id,
)
from app.runtime.customer_email_template import (
    derive_ticket_reference,
    render_customer_email_body,
    render_customer_email_subject,
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
from app.tenant.enums import TenantChannelType
from app.tenant.persistence import TenantChannelConfigurationRecord

_DEFAULT_TIMEOUT_SECONDS = 10.0


class EmailCustomerReplySendError(RuntimeError):
    """Base customer-reply email send failure."""


class EmailCustomerReplyNotFoundError(EmailCustomerReplySendError):
    """The draft or proposal is not visible for the tenant."""


class EmailCustomerReplyGovernanceError(EmailCustomerReplySendError):
    """The draft is not governed-send eligible."""


class EmailCustomerReplyConfigurationError(EmailCustomerReplySendError):
    """Tenant SES send configuration is missing or invalid."""


class EmailCustomerReplyProviderError(EmailCustomerReplySendError):
    """SES rejected or failed the send attempt."""


@dataclass(frozen=True, slots=True)
class EmailCustomerReplySendResult:
    delivery_id: str
    status: Literal["sent", "already_sent", "pending"]
    provider_message_id: str | None
    transmitted: bool
    idempotent_replay: bool


class TenantEmailRuntimeProtocol(Protocol):
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


class EmailSenderProtocol(Protocol):
    async def send_email(
        self,
        request: SesEmailSendRequest,
    ) -> SesEmailSendResponse: ...


class TransactionControl(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _SesCredentials:
    access_key_id: str
    secret_access_key: str
    region: str
    source_email_address: str
    session_token: str | None
    endpoint_url: str | None
    configuration_set_name: str | None


class EmailCustomerReplySendService:
    """Send a resolution draft by email only after persisted tenant ALLOW."""

    def __init__(
        self,
        *,
        draft_repository: ResolutionOutboundDraftPersistenceProtocol,
        proposal_repository: ResolutionProposalPersistenceProtocol,
        governance_repository: BaseGovernanceRepository,
        tenant_runtime: TenantEmailRuntimeProtocol,
        delivery_repository: EmailDeliveryRepository,
        sender: EmailSenderProtocol | None = None,
        session: TransactionControl | None = None,
    ) -> None:
        self._draft_repository = draft_repository
        self._proposal_repository = proposal_repository
        self._governance_repository = governance_repository
        self._tenant_runtime = tenant_runtime
        self._delivery_repository = delivery_repository
        self._sender = sender or SesV2EmailSender()
        self._session = session

    async def send_draft(
        self,
        *,
        draft_id: str,
        tenant_id: str,
        expected_tenant_id: str,
        recipient_email_address: str,
        subject: str,
        source_email_address: str | None = None,
        in_reply_to_message_id: str | None = None,
        references_header: str | None = None,
        expected_governance_decision_id: uuid.UUID | str | None = None,
        expected_draft_body_sha256: str | None = None,
        allow_failed_delivery_retry: bool = False,
        customer_display_name: str | None = None,
    ) -> EmailCustomerReplySendResult:
        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        previous_tenant = get_current_tenant()
        set_current_tenant(expected_tenant_id)
        try:
            return await self._send_draft_scoped(
                draft_id=draft_id,
                tenant_id=tenant_id,
                expected_tenant_id=expected_tenant_id,
                recipient_email_address=recipient_email_address,
                subject=subject,
                source_email_address=source_email_address,
                in_reply_to_message_id=in_reply_to_message_id,
                references_header=references_header,
                expected_governance_decision_id=expected_governance_decision_id,
                expected_draft_body_sha256=expected_draft_body_sha256,
                allow_failed_delivery_retry=allow_failed_delivery_retry,
                customer_display_name=customer_display_name,
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
        recipient_email_address: str,
        subject: str,
        source_email_address: str | None,
        in_reply_to_message_id: str | None,
        references_header: str | None,
        expected_governance_decision_id: uuid.UUID | str | None,
        expected_draft_body_sha256: str | None,
        allow_failed_delivery_retry: bool,
        customer_display_name: str | None,
    ) -> EmailCustomerReplySendResult:
        recipient = _required_text("recipient_email_address", recipient_email_address)
        subject_text = _required_text("subject", subject)
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
        credentials = await self._load_ses_credentials(
            tenant_id=tenant_id,
            source_email_address=source_email_address,
        )
        governance_decision_id = _required_governance_decision_id(
            draft.governance_decision_id
        )
        delivery_id = derive_email_customer_reply_delivery_id(
            tenant_id=tenant_id,
            draft_id=draft.draft_id,
            governance_decision_id=governance_decision_id,
        )
        now = datetime.now(timezone.utc)
        delivery, created = await self._delivery_repository.reserve_delivery(
            EmailCustomerReplyDeliveryRecord(
                delivery_id=delivery_id,
                tenant_id=tenant_id,
                draft_id=uuid.UUID(str(draft.draft_id)),
                proposal_id=uuid.UUID(str(draft.proposal_id)),
                governance_decision_id=governance_decision_id,
                source_email_address=credentials.source_email_address,
                recipient_email_address=recipient,
                draft_body_sha256=draft.draft_body_sha256,
                subject=subject_text,
                in_reply_to_message_id=_optional_text(in_reply_to_message_id),
                references_header=_optional_text(references_header),
                status=EmailDeliveryStatus.PENDING,
                provider_message_id=None,
                provider_status_code=None,
                error_code=None,
                created_at=now,
                updated_at=now,
                sent_at=None,
                metadata={
                    "channel": TenantChannelType.EMAIL.value,
                    "source": "resolution_outbound_draft",
                    "proposal_id": str(draft.proposal_id),
                },
            ),
            expected_tenant_id=expected_tenant_id,
        )
        await self._commit()
        self._assert_delivery_matches_request(
            delivery=delivery,
            credentials=credentials,
            recipient_email_address=recipient,
            subject=subject_text,
            draft=draft,
            in_reply_to_message_id=_optional_text(in_reply_to_message_id),
            references_header=_optional_text(references_header),
        )
        should_transmit = created
        if not created:
            if delivery.status is EmailDeliveryStatus.SENT:
                return EmailCustomerReplySendResult(
                    delivery_id=str(delivery.delivery_id),
                    status="already_sent",
                    provider_message_id=delivery.provider_message_id,
                    transmitted=False,
                    idempotent_replay=True,
                )
            if delivery.status is EmailDeliveryStatus.PENDING:
                return EmailCustomerReplySendResult(
                    delivery_id=str(delivery.delivery_id),
                    status="pending",
                    provider_message_id=delivery.provider_message_id,
                    transmitted=False,
                    idempotent_replay=True,
                )
            if allow_failed_delivery_retry and _email_delivery_error_is_retryable(
                delivery.error_code
            ):
                should_transmit = True
            else:
                raise EmailCustomerReplyProviderError(
                    "email delivery previously failed and is not auto-retried"
                )

        if should_transmit:
            ticket_reference = derive_ticket_reference(draft.session_id)
            email_subject = render_customer_email_subject(
                subject=subject_text,
                ticket_reference=ticket_reference,
            )
            email_body = render_customer_email_body(
                body=draft.draft_body,
                ticket_reference=ticket_reference,
                tenant_id=tenant_id,
                customer_display_name=customer_display_name,
            )
            try:
                response = await self._sender.send_email(
                    SesEmailSendRequest(
                        region=credentials.region,
                        access_key_id=credentials.access_key_id,
                        secret_access_key=credentials.secret_access_key,
                        session_token=credentials.session_token,
                        endpoint_url=credentials.endpoint_url,
                        configuration_set_name=credentials.configuration_set_name,
                        from_email_address=credentials.source_email_address,
                        recipient_email_address=recipient,
                        subject=email_subject,
                        body_text=email_body,
                        in_reply_to_message_id=_optional_text(in_reply_to_message_id),
                        references_header=_optional_text(references_header),
                        timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
                    )
                )
            except SesV2SendError as exc:
                await self._mark_failed(
                    delivery_id=delivery_id,
                    expected_tenant_id=expected_tenant_id,
                    error_code=f"ses_v2_http_{exc.status_code}",
                    provider_status_code=exc.status_code,
                )
                raise EmailCustomerReplyProviderError(
                    "ses v2 rejected the message"
                ) from exc
            except Exception as exc:
                await self._mark_failed(
                    delivery_id=delivery_id,
                    expected_tenant_id=expected_tenant_id,
                    error_code=exc.__class__.__name__,
                )
                raise EmailCustomerReplyProviderError("ses v2 send failed") from exc

            sent = await self._delivery_repository.mark_sent(
                delivery_id,
                expected_tenant_id=expected_tenant_id,
                provider_message_id=response.provider_message_id,
                provider_status_code=response.status_code,
                sent_at=datetime.now(timezone.utc),
            )
            await self._commit()
            return EmailCustomerReplySendResult(
                delivery_id=str(sent.delivery_id),
                status="sent",
                provider_message_id=sent.provider_message_id,
                transmitted=True,
                idempotent_replay=False,
            )
        raise EmailCustomerReplyProviderError("email delivery was not transmitted")

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
            raise EmailCustomerReplyNotFoundError("outbound draft not found")
        if draft.status is not ResolutionOutboundDraftStatus.READY:
            raise EmailCustomerReplyGovernanceError(
                "outbound draft is not ready to send"
            )
        if draft.governance_decision_id is None:
            raise EmailCustomerReplyGovernanceError(
                "outbound draft has no governance decision"
            )
        if draft.draft_body_sha256 != _sha256_text(draft.draft_body):
            raise EmailCustomerReplyGovernanceError(
                "outbound draft body hash mismatch"
            )
        localized = draft.metadata.get("localized_reply")
        if isinstance(localized, str) and localized != draft.draft_body:
            raise EmailCustomerReplyGovernanceError(
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
            raise EmailCustomerReplyNotFoundError("resolution proposal not found")
        if (
            proposal.status is not ResolutionProposalStatus.SEND_ELIGIBLE
            or proposal.governance_decision_id is None
        ):
            raise EmailCustomerReplyGovernanceError(
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
            raise EmailCustomerReplyGovernanceError("tenant lineage mismatch")
        if str(draft.proposal_id) != str(proposal.proposal_id):
            raise EmailCustomerReplyGovernanceError("proposal lineage mismatch")
        if draft.governance_decision_id != proposal.governance_decision_id:
            raise EmailCustomerReplyGovernanceError(
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
            raise EmailCustomerReplyGovernanceError(
                "outbound draft has no governance decision"
            )
        decision = await self._governance_repository.get_decision(
            str(draft.governance_decision_id),
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None:
            raise EmailCustomerReplyGovernanceError(
                "governance decision is not visible for tenant"
            )
        if decision.decision != Decision.ALLOW.value:
            raise EmailCustomerReplyGovernanceError(
                "governance decision is not allow"
            )
        if decision.tenant_id != expected_tenant_id:
            raise EmailCustomerReplyGovernanceError(
                "governance decision tenant mismatch"
            )
        metadata = dict(decision.metadata)
        if str(metadata.get("proposal_id")) != str(proposal.proposal_id):
            raise EmailCustomerReplyGovernanceError(
                "governance decision proposal mismatch"
            )
        governed_reply = draft.metadata.get("canonical_reply")
        if not isinstance(governed_reply, str) or not governed_reply:
            governed_reply = draft.draft_body
        governed_hash = _sha256_text(governed_reply)
        if metadata.get("proposed_reply_sha256") != governed_hash:
            raise EmailCustomerReplyGovernanceError(
                "governance decision reply hash mismatch"
            )

    async def _load_ses_credentials(
        self,
        *,
        tenant_id: str,
        source_email_address: str | None,
    ) -> _SesCredentials:
        credentials = await self._tenant_runtime.load_channel_credentials(
            tenant_id=tenant_id,
            channel_type=TenantChannelType.EMAIL,
        )
        source = _resolved_source_email_address(
            credentials=credentials,
            requested_source=source_email_address,
        )
        channel_config = (
            await self._tenant_runtime.resolve_active_channel_for_routing_address(
                channel_type=TenantChannelType.EMAIL,
                routing_address=source,
                expected_tenant_id=tenant_id,
            )
        )
        if channel_config is None and "@" in source:
            channel_config = (
                await self._tenant_runtime.resolve_active_channel_for_routing_address(
                    channel_type=TenantChannelType.EMAIL,
                    routing_address=source.rsplit("@", 1)[1].lower(),
                    expected_tenant_id=tenant_id,
                )
            )
        if channel_config is None:
            raise EmailCustomerReplyConfigurationError(
                "active email channel route is not configured"
            )
        return _SesCredentials(
            access_key_id=_credential_string(
                credentials,
                "access_key_id",
                "aws_access_key_id",
            ),
            secret_access_key=_credential_string(
                credentials,
                "secret_access_key",
                "aws_secret_access_key",
            ),
            session_token=_optional_credential_string(
                credentials,
                "session_token",
                "aws_session_token",
                default=None,
            ),
            region=_credential_string(credentials, "region", "aws_region", "ses_region"),
            source_email_address=source,
            endpoint_url=_optional_credential_string(
                credentials,
                "endpoint_url",
                "ses_endpoint_url",
                default=None,
            ),
            configuration_set_name=_optional_credential_string(
                credentials,
                "configuration_set_name",
                "ses_configuration_set_name",
                default=None,
            ),
        )

    def _assert_delivery_matches_request(
        self,
        *,
        delivery: EmailCustomerReplyDeliveryRecord,
        credentials: _SesCredentials,
        recipient_email_address: str,
        subject: str,
        draft: ResolutionOutboundDraftRecord,
        in_reply_to_message_id: str | None,
        references_header: str | None,
    ) -> None:
        if delivery.source_email_address != credentials.source_email_address:
            raise EmailCustomerReplyGovernanceError(
                "delivery idempotency source email conflict"
            )
        if delivery.recipient_email_address != recipient_email_address:
            raise EmailCustomerReplyGovernanceError(
                "delivery idempotency recipient conflict"
            )
        if delivery.subject != subject:
            raise EmailCustomerReplyGovernanceError(
                "delivery idempotency subject conflict"
            )
        if delivery.draft_body_sha256 != draft.draft_body_sha256:
            raise EmailCustomerReplyGovernanceError(
                "delivery idempotency draft body conflict"
            )
        if delivery.in_reply_to_message_id != in_reply_to_message_id:
            raise EmailCustomerReplyGovernanceError(
                "delivery idempotency in-reply-to conflict"
            )
        if delivery.references_header != references_header:
            raise EmailCustomerReplyGovernanceError(
                "delivery idempotency references conflict"
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


def _resolved_source_email_address(
    *,
    credentials: Mapping[str, Any],
    requested_source: str | None,
) -> str:
    configured = _optional_credential_string(
        credentials,
        "source_email_address",
        "from_email_address",
        "ses_source_email_address",
        default=None,
    )
    requested = _optional_text(requested_source)
    if requested and configured and requested.lower() != configured.lower():
        raise EmailCustomerReplyConfigurationError(
            "requested source_email_address does not match tenant credentials"
        )
    resolved = requested or configured
    if resolved is None:
        raise EmailCustomerReplyConfigurationError(
            "tenant email source_email_address is required"
        )
    return resolved.lower()


def _assert_expected_outbox_guards(
    *,
    draft: ResolutionOutboundDraftRecord,
    expected_governance_decision_id: uuid.UUID | str | None,
    expected_draft_body_sha256: str | None,
) -> None:
    if expected_governance_decision_id is not None:
        expected_decision_id = uuid.UUID(str(expected_governance_decision_id))
        if draft.governance_decision_id != expected_decision_id:
            raise EmailCustomerReplyGovernanceError(
                "outbox governance decision mismatch"
            )
    if expected_draft_body_sha256 is not None:
        expected_digest = expected_draft_body_sha256.strip().lower()
        if draft.draft_body_sha256 != expected_digest:
            raise EmailCustomerReplyGovernanceError(
                "outbox draft body hash mismatch"
            )


def _email_delivery_error_is_retryable(error_code: str | None) -> bool:
    if error_code is None:
        return False
    if not error_code.startswith("ses_v2_http_"):
        return False
    try:
        status_code = int(error_code.removeprefix("ses_v2_http_"))
    except ValueError:
        return False
    return status_code == 429 or status_code >= 500


def _credential_string(credentials: Mapping[str, Any], *keys: str) -> str:
    value = _optional_credential_string(credentials, *keys, default=None)
    if value is None:
        raise EmailCustomerReplyConfigurationError(
            f"tenant email credential {keys[0]} is required"
        )
    return value


def _optional_credential_string(
    credentials: Mapping[str, Any],
    *keys: str,
    default: str | None,
) -> str | None:
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


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_governance_decision_id(value: uuid.UUID | None) -> uuid.UUID:
    if value is None:
        raise EmailCustomerReplyGovernanceError(
            "outbound draft has no governance decision"
        )
    return value


__all__ = [
    "EmailCustomerReplyConfigurationError",
    "EmailCustomerReplyGovernanceError",
    "EmailCustomerReplyNotFoundError",
    "EmailCustomerReplyProviderError",
    "EmailCustomerReplySendError",
    "EmailCustomerReplySendResult",
    "EmailCustomerReplySendService",
]
