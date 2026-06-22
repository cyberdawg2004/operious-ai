"""Ticket ingress service composition (PR-W1)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.adapters import (
    BaseIngressAdapter,
    ChannelWebhookSecurityContext,
    EmailWebhookAdapter,
    LarkWebhookAdapter,
    ShulexWebhookAdapter,
    TenantWhatsAppWebhookAdapter,
    extract_routing_address,
    extract_webhook_security_context,
)
from app.attachments.records import AttachmentRecord
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.storage_service import AttachmentStorageService
from app.boundary.adapters.email_ses import (
    HttpSnsSubscriptionConfirmer,
    SesEmailMimeError,
    SesEmailWebhookAdapter,
    SesRawEmailFetcher,
    SnsConfirmationError,
    SnsMessageVerifier,
    SnsSubscriptionConfirmer,
    SnsVerificationError,
    pop_attachment_raw_bytes,
    ses_sns_message_to_email_payload,
)
from app.boundary.exceptions import WebhookFreshnessError, WebhookReplayError
from app.boundary.adapters.builtin import (
    TwilioVoiceAdapter,
    WhatsAppWebhookAdapter,
    ZendeskWebhookAdapter,
)
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryIngressId, derive_ingress_id
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.ingress_dispatch_outbox import IngressDispatchOutboxRecord
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import BoundaryPersistenceProtocol
from app.boundary.persistence.records import WebhookNonceRecord
from app.boundary.registry import BoundaryAdapterRegistry
from app.boundary.translation import (
    IngressTranslateRequest,
    TranslationPayload,
    TranslationRuntime,
)
from app.boundary.whatsapp_media_fetch import (
    WhatsAppMediaFetchRecord,
    WhatsAppMediaFetchRepositoryProtocol,
)
from app.core.config import get_settings
from app.core.twilio_signature import (
    TWILIO_CANONICAL_URL_HEADER,
    TWILIO_SIGNATURE_HEADER,
    verify_twilio_signature,
)
from app.core.webhook_url import (
    CanonicalWebhookUrlError,
    derive_canonical_webhook_url,
)
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.tenant_context import set_current_tenant
from app.governance.capability import OperationalAct
from app.hardening.admission import (
    AdmissionOutcome,
)
from app.identity import AuthorityContext, TenantId
from app.language import LanguageDetector
from app.semantic import (
    FINGERPRINT_VERSION,
    SemanticCircuitBreaker,
    SemanticCircuitEventRecord,
    SemanticCircuitEventRepository,
    SemanticCircuitState,
    TextFingerprinter,
)
from app.services.admission_service import AdmissionService
from app.services.quarantine_service import QuarantineService
from app.tenant.enums import TenantChannelType
from app.tenant.persistence import (
    TenantChannelConfigurationRecord,
    TenantWebhookRoutingSecretRecord,
)
from app.tenant.runtime import TenantConfigurationRuntime

TicketChannel = Literal["email", "whatsapp", "voice"]
WebhookTicketChannel = Literal["email", "whatsapp", "shulex", "lark"]
WEBHOOK_FRESHNESS_WINDOW_SECONDS = 300
WEBHOOK_NONCE_TTL_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)
IngressDispatchEnqueue = Callable[[IngressDispatchOutboxRecord], None]
WhatsAppMediaFetchEnqueue = Callable[[WhatsAppMediaFetchRecord], None]


@dataclass(frozen=True, slots=True)
class TicketIngressServiceResult:
    ingress_id: str | None
    canonical_envelope_id: str | None
    quarantine_id: str | None = None
    status: str = "received"


@dataclass(frozen=True, slots=True)
class WebhookDuplicateDeliveryResult:
    status: Literal["duplicate_delivery_acknowledged"] = (
        "duplicate_delivery_acknowledged"
    )


class TicketIngressService:
    """Service boundary for ticket ingress writes."""

    def __init__(
        self,
        *,
        persistence: BoundaryPersistenceProtocol,
        session: AsyncSession,
        tenant_configuration_runtime: TenantConfigurationRuntime | None = None,
        admission_service: AdmissionService | None = None,
        translation_runtime: TranslationRuntime | None = None,
        language_detector: LanguageDetector | None = None,
        fingerprinter: TextFingerprinter | None = None,
        circuit_breaker: SemanticCircuitBreaker | None = None,
        circuit_event_repo: SemanticCircuitEventRepository | None = None,
        quarantine_service: QuarantineService | None = None,
        webhook_queue_by_channel: (
            Mapping[TenantChannelType, Sequence[str]] | None
        ) = None,
        ingress_dispatch_enqueue: IngressDispatchEnqueue | None = None,
        sns_message_verifier: SnsMessageVerifier | None = None,
        sns_subscription_confirmer: SnsSubscriptionConfirmer | None = None,
        ses_raw_email_fetcher: SesRawEmailFetcher | None = None,
        attachment_blob_store: AttachmentBlobStore | None = None,
        whatsapp_media_fetch_repository: (
            WhatsAppMediaFetchRepositoryProtocol | None
        ) = None,
        whatsapp_media_fetch_enqueue: WhatsAppMediaFetchEnqueue | None = None,
    ) -> None:
        self._persistence = persistence
        self._session = session
        self._tenant_configuration_runtime = tenant_configuration_runtime
        self._admission_service = admission_service
        self._translation_runtime = translation_runtime
        self._language_detector = language_detector or LanguageDetector()
        self._fingerprinter = fingerprinter or TextFingerprinter()
        self._circuit_breaker = circuit_breaker
        self._circuit_event_repo = circuit_event_repo
        self._quarantine_service = quarantine_service
        self._webhook_queue_by_channel = {
            channel_type: tuple(queue_names)
            for channel_type, queue_names in (webhook_queue_by_channel or {}).items()
        }
        self._ingress_dispatch_enqueue = ingress_dispatch_enqueue
        self._sns_message_verifier = sns_message_verifier or SnsMessageVerifier()
        self._sns_subscription_confirmer = (
            sns_subscription_confirmer or HttpSnsSubscriptionConfirmer()
        )
        self._ses_raw_email_fetcher = ses_raw_email_fetcher
        self._attachment_blob_store = attachment_blob_store
        self._whatsapp_media_fetch_repository = whatsapp_media_fetch_repository
        self._whatsapp_media_fetch_enqueue = whatsapp_media_fetch_enqueue

    async def process(
        self,
        *,
        external_id: str,
        channel: TicketChannel,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
        semantic_quarantine_enabled: bool = True,
    ) -> TicketIngressServiceResult:
        canonical_content, source_language = await self._canonicalize_ticket_text(
            raw_text=raw_content,
            tenant_id=expected_tenant_id,
            correlation_id=external_id,
            request_id=external_id,
        )
        fingerprint_metadata = self._fingerprint_metadata(canonical_content)
        fingerprint = _fingerprint_from_metadata(fingerprint_metadata)
        circuit_state, cluster_size = await self._evaluate_semantic_circuit(
            tenant_id=expected_tenant_id,
            channel=channel,
            ticket_id=external_id,
            fingerprint=fingerprint,
        )
        if (
            semantic_quarantine_enabled
            and circuit_state is SemanticCircuitState.TRIPPED
            and self._quarantine_service is not None
        ):
            await self._record_semantic_circuit_trip(
                tenant_id=expected_tenant_id,
                channel=channel,
                trigger_ticket_id=None,
                cluster_size=cluster_size,
            )
            quarantine_id = await self._quarantine_ticket(
                tenant_id=expected_tenant_id,
                channel=channel,
                external_id=external_id,
                raw_content=raw_content,
                language_code=language_code,
                source_language=source_language,
                fingerprint=fingerprint,
                cluster_size=cluster_size,
            )
            await self._session.commit()
            return TicketIngressServiceResult(
                ingress_id=None,
                canonical_envelope_id=None,
                quarantine_id=quarantine_id,
                status="quarantined",
            )
        runtime = BoundaryIngressRuntime(
            adapters=_adapter_registry(),
            persistence=self._persistence,
        )
        envelope = await runtime.ingest(
            _to_boundary_request(
                external_id=external_id,
                channel=channel,
                raw_content=canonical_content,
                language_code="en",
                expected_tenant_id=expected_tenant_id,
                source_language=source_language,
                metadata=fingerprint_metadata,
            )
        )
        if envelope.error is not None:
            raise TicketIngressServiceError("ticket ingress failed")
        result = envelope.result
        if result is None or result.event_id is None:
            raise TicketIngressServiceError(
                "ticket ingress did not produce a canonical event"
            )
        if circuit_state is SemanticCircuitState.TRIPPED:
            await self._record_semantic_circuit_trip(
                tenant_id=expected_tenant_id,
                channel=channel,
                trigger_ticket_id=str(result.ingress_id),
                cluster_size=cluster_size,
            )

        await self._session.commit()
        await self._best_effort_enqueue_captured_ingress_dispatch(
            ingress_id=result.ingress_id,
            tenant_id=expected_tenant_id,
            channel=channel,
            request_correlation_id=external_id,
        )
        return TicketIngressServiceResult(
            ingress_id=str(result.ingress_id),
            canonical_envelope_id=str(result.event_id),
        )

    async def _canonicalize_ticket_text(
        self,
        *,
        raw_text: str,
        tenant_id: str,
        correlation_id: str,
        request_id: str,
    ) -> tuple[str, str]:
        try:
            detected_language = self._language_detector.detect(raw_text)
        except Exception:  # noqa: BLE001
            return raw_text, "en"
        if detected_language == "en":
            return raw_text, "en"
        if self._translation_runtime is None:
            return raw_text, "en"
        try:
            envelope = await self._translation_runtime.ingress.translate(
                IngressTranslateRequest(
                    source=TranslationPayload(
                        text=raw_text,
                        language=detected_language,
                    ),
                    seed=(
                        "ticket-ingress|"
                        f"{tenant_id}|{correlation_id}|"
                        f"{detected_language}|en"
                    ),
                    correlation_id=correlation_id,
                    request_id=request_id,
                    tenant_id=tenant_id,
                    authority=AuthorityContext(
                        tenant_id=TenantId(tenant_id),
                        capabilities=frozenset(
                            {
                                OperationalAct.BOUNDARY_TRANSLATION_INGRESS.value
                            }
                        ),
                    ),
                    attributes={
                        "source_language": detected_language,
                        "target_language": "en",
                    },
                )
            )
        except Exception:  # noqa: BLE001
            return raw_text, "en"
        result = envelope.result
        projection = getattr(result, "projection", None)
        canonical_payload = getattr(projection, "canonical_payload", None)
        canonical_text = getattr(canonical_payload, "text", None)
        if envelope.is_fully_clean and isinstance(canonical_text, str):
            return canonical_text, detected_language
        return raw_text, "en"

    def _fingerprint_metadata(self, canonical_text: str) -> dict[str, object]:
        # Fail-open fingerprinting: forensics must never block ingestion.
        try:
            fingerprint = self._fingerprinter.fingerprint(canonical_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "text_fingerprint_failed",
                extra={"error": str(exc)},
            )
            return {}
        return {
            "text_fingerprint": list(fingerprint),
            "fingerprint_version": FINGERPRINT_VERSION,
        }

    async def _evaluate_semantic_circuit(
        self,
        *,
        tenant_id: str,
        channel: str,
        ticket_id: str,
        fingerprint: tuple[int, ...] | None,
    ) -> tuple[SemanticCircuitState, int]:
        if self._circuit_breaker is None:
            return SemanticCircuitState.CLOSED, 0
        if fingerprint is None:
            return SemanticCircuitState.CLOSED, 0
        try:
            return await self._circuit_breaker.evaluate(
                tenant_id=tenant_id,
                channel=channel,
                ticket_id=ticket_id,
                fingerprint=fingerprint,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "semantic_circuit_eval_failed",
                extra={"tenant_id": tenant_id, "channel": channel, "error": str(exc)},
            )
            return SemanticCircuitState.CLOSED, 0

    async def _record_semantic_circuit_trip(
        self,
        *,
        tenant_id: str,
        channel: str,
        trigger_ticket_id: str | None,
        cluster_size: int,
    ) -> None:
        if self._circuit_event_repo is None or self._circuit_breaker is None:
            return
        try:
            await self._circuit_event_repo.write(
                SemanticCircuitEventRecord(
                    event_id=str(uuid.uuid4()),  # APPROVED_EXCEPTION: immutable audit event id
                    tenant_id=tenant_id,
                    channel=channel,
                    state=SemanticCircuitState.TRIPPED.value,
                    trigger_ticket_id=trigger_ticket_id,
                    cluster_size=cluster_size,
                    similarity_threshold=(self._circuit_breaker.similarity_threshold),
                    window_seconds=self._circuit_breaker.window_seconds,
                    occurred_at=datetime.now(timezone.utc),
                    metadata={},
                )
            )
            logger.warning(
                "semantic_circuit_tripped",
                extra={
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "cluster_size": cluster_size,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "semantic_circuit_event_write_failed",
                extra={"tenant_id": tenant_id, "channel": channel, "error": str(exc)},
            )

    async def _quarantine_ticket(
        self,
        *,
        tenant_id: str,
        channel: str,
        external_id: str,
        raw_content: str,
        language_code: str,
        source_language: str,
        fingerprint: tuple[int, ...] | None,
        cluster_size: int,
    ) -> str:
        if self._quarantine_service is None:
            raise TicketIngressServiceError(
                "semantic quarantine service is not configured"
            )
        if self._circuit_breaker is None:
            raise TicketIngressServiceError(
                "semantic circuit breaker is not configured"
            )
        return await self._quarantine_service.quarantine_ticket(
            tenant_id=tenant_id,
            channel=channel,
            external_id=external_id,
            ticket_payload=_extract_quarantine_payload(
                tenant_id=tenant_id,
                channel=channel,
                external_id=external_id,
                raw_content=raw_content,
                language_code=language_code,
                source_language=source_language,
            ),
            fingerprint=list(fingerprint or ()),
            cluster_size=cluster_size,
            similarity_threshold=self._circuit_breaker.similarity_threshold,
            expected_tenant_id=tenant_id,
        )

    async def process_channel_webhook(
        self,
        *,
        channel_type: str,
        body: Any,
        headers: Mapping[str, str],
        raw_body: bytes | None,
        content_type: str | None,
        tenant_hint: str | None = None,
        request_path: str | None = None,
    ) -> TicketIngressServiceResult | WebhookDuplicateDeliveryResult:
        if self._tenant_configuration_runtime is None:
            raise TicketIngressServiceError(
                "tenant configuration runtime is not configured"
            )
        tenant_channel_type = _tenant_channel_type(channel_type)
        if (
            tenant_channel_type is TenantChannelType.EMAIL
            and _is_sns_webhook_body(body)
        ):
            return await self._process_email_sns_webhook(
                body=body,
                raw_body=raw_body,
                content_type=content_type,
                tenant_hint=tenant_hint,
                request_path=request_path,
            )
        routing_address = _routing_address_for_webhook(
            channel_type=tenant_channel_type.value,
            body=body,
            headers=headers,
        )
        # WHY: Signature validation precedes all tenant processing
        # to prevent unauthenticated callers from triggering tenant
        # DB work. The minimal routing lookup is unavoidable because
        # the webhook secret is per-tenant, but all other processing
        # is gated on valid HMAC.
        if not _webhook_signature_header_present(
            channel_type=tenant_channel_type,
            headers=headers,
        ):
            raise _uniform_webhook_rejection("missing_signature")
        routing_secret = (
            await self._tenant_configuration_runtime
            .resolve_webhook_routing_secret(
                channel_type=tenant_channel_type,
                routing_address=routing_address,
            )
        )
        await _end_read_only_routing_transaction(self._session)
        if routing_secret is None:
            raise _uniform_webhook_rejection("unknown_channel_route")
        resolved_tenant_id = routing_secret.tenant_id
        if tenant_hint is not None and tenant_hint != resolved_tenant_id:
            raise _uniform_webhook_rejection("tenant_route_mismatch")
        webhook_secret = _select_webhook_secret(
            channel_type=tenant_channel_type,
            channel_config=routing_secret,
            body=body,
            headers=headers,
            raw_body=raw_body,
            request_path=request_path,
        )
        if not _webhook_signature_matches_secret(
            channel_type=tenant_channel_type,
            secret=webhook_secret,
            body=body,
            headers=headers,
            raw_body=raw_body,
            request_path=request_path,
        ):
            raise _uniform_webhook_rejection("invalid_signature")
        set_current_tenant(resolved_tenant_id)
        channel_config = (
            await self._tenant_configuration_runtime
            .resolve_active_channel_for_routing_address(
                channel_type=tenant_channel_type,
                routing_address=routing_address,
                expected_tenant_id=resolved_tenant_id,
            )
        )
        if channel_config is None:
            raise _uniform_webhook_rejection("unknown_channel_route")
        security_context = self._validated_webhook_security_context(
            channel_type=tenant_channel_type.value,
            body=body,
            headers=headers,
        )
        if await self._webhook_nonce_exists(
            tenant_id=channel_config.tenant_id,
            channel_type=tenant_channel_type.value,
            nonce=security_context.nonce,
        ):
            return WebhookDuplicateDeliveryResult()
        nonce_recorded = await self._record_webhook_freshness_nonce(
            tenant_id=channel_config.tenant_id,
            channel_type=tenant_channel_type.value,
            body=body,
            headers=headers,
            security_context=security_context,
        )
        if not nonce_recorded:
            return WebhookDuplicateDeliveryResult()
        adapter = _webhook_adapter_for_channel(
            channel_type=tenant_channel_type,
            webhook_secret=webhook_secret,
            routing_address=channel_config.routing_address,
        )
        webhook_request_id = _webhook_request_id(
            channel=tenant_channel_type.value,
            routing_address=channel_config.routing_address,
            body=body,
            raw_body=raw_body,
        )
        webhook_correlation_id = _webhook_correlation_id(
            channel=tenant_channel_type.value,
            routing_address=channel_config.routing_address,
            body=body,
            raw_body=raw_body,
        )
        source_language = "en"
        canonical_body = body
        fingerprint_metadata: dict[str, object] = {}
        ticket_text = _extract_webhook_ticket_text(
            channel_type=tenant_channel_type,
            body=body,
        )
        if ticket_text:
            canonical_text, source_language = await self._canonicalize_ticket_text(
                raw_text=ticket_text,
                tenant_id=channel_config.tenant_id,
                correlation_id=webhook_correlation_id,
                request_id=webhook_request_id,
            )
            canonical_body = _replace_webhook_ticket_text(
                channel_type=tenant_channel_type,
                body=body,
                text=canonical_text,
            )
            fingerprint_metadata = self._fingerprint_metadata(canonical_text)
        payload = IngressPayload(
            body=canonical_body,
            content_type=content_type,
            headers=dict(headers),
            raw_bytes=raw_body,
            request_path=request_path,
        )
        runtime = BoundaryIngressRuntime(
            adapters=BoundaryAdapterRegistry((adapter,)),
            persistence=self._persistence,
        )
        envelope = await runtime.ingest(
            BoundaryIngressRequest(
                source=BoundarySource(
                    source_type=_source_type_for_tenant_channel(
                        tenant_channel_type
                    ),
                    source_id=channel_config.routing_address,
                    tenant_id=channel_config.tenant_id,
                    display_name=f"tenant {tenant_channel_type.value}",
                    metadata={
                        "tenant_channel.config_id": str(
                            channel_config.config_id
                        ),
                        "source_language": source_language,
                    },
                ),
                adapter_name=adapter.name,
                payload=payload,
                correlation_id=webhook_correlation_id,
                request_id=webhook_request_id,
                ingress_id_override=derive_ingress_id(
                    seed=_webhook_ingress_seed(
                        tenant_id=channel_config.tenant_id,
                        channel=tenant_channel_type.value,
                        routing_address=channel_config.routing_address,
                        body=body,
                        raw_body=raw_body,
                    )
                ),
                authority=AuthorityContext.from_raw(
                    tenant_id=channel_config.tenant_id,
                ),
                metadata={
                    "tenant_channel.config_id": str(
                        channel_config.config_id
                    ),
                    "tenant_channel.channel_type": (
                        tenant_channel_type.value
                    ),
                    "tenant_channel.routing_address": (
                        channel_config.routing_address
                    ),
                    "source_language": source_language,
                    **fingerprint_metadata,
                },
            )
        )
        await self._session.commit()
        result = envelope.result
        if result is None:
            raise TicketIngressServiceError("channel webhook ingress failed")
        if (
            result.normalization.status
            is BoundaryNormalizationStatus.UNAUTHENTICATED
        ):
            raise _uniform_webhook_rejection("invalid_signature")
        if not result.normalization.is_ok or result.event_id is None:
            raise TicketIngressRejected(
                code="channel_webhook_rejected",
                reason=result.normalization.error or "normalization failed",
            )
        await self._best_effort_enqueue_captured_ingress_dispatch(
            ingress_id=result.ingress_id,
            tenant_id=channel_config.tenant_id,
            channel=tenant_channel_type.value,
            request_correlation_id=webhook_request_id,
        )
        if tenant_channel_type is TenantChannelType.WHATSAPP:
            await self._best_effort_capture_whatsapp_media(
                ingress_id=result.ingress_id,
                tenant_id=channel_config.tenant_id,
                external_message_id=result.normalization.external_message_id,
                canonical_payload=result.normalization.canonical_payload,
            )
        await self._record_processing_admission_after_capture(
            tenant_id=channel_config.tenant_id,
            channel_type=tenant_channel_type,
            request_correlation_id=webhook_request_id,
        )
        return TicketIngressServiceResult(
            ingress_id=str(result.ingress_id),
            canonical_envelope_id=str(result.event_id),
        )

    async def _process_email_sns_webhook(
        self,
        *,
        body: Any,
        raw_body: bytes | None,
        content_type: str | None,
        tenant_hint: str | None,
        request_path: str | None,
    ) -> TicketIngressServiceResult | WebhookDuplicateDeliveryResult:
        tenant_runtime = self._tenant_configuration_runtime
        if tenant_runtime is None:
            raise TicketIngressServiceError(
                "tenant configuration runtime is not configured"
            )
        sns_body = _sns_body_mapping(body)
        topic_arn = _first_text_value(sns_body.get("TopicArn"))
        if topic_arn is None:
            raise _uniform_webhook_rejection("sns_topic_missing")
        routing_secret = await tenant_runtime.resolve_webhook_routing_secret_by_topic_arn(
            channel_type=TenantChannelType.EMAIL,
            topic_arn=topic_arn,
        )
        await _end_read_only_routing_transaction(self._session)
        if routing_secret is None:
            raise _uniform_webhook_rejection("unknown_sns_topic")
        if tenant_hint is not None and tenant_hint != routing_secret.tenant_id:
            raise _uniform_webhook_rejection("tenant_route_mismatch")
        try:
            verified = await self._sns_message_verifier.verify(
                payload=sns_body,
                expected_topic_arn=topic_arn,
            )
        except SnsVerificationError as exc:
            raise _uniform_webhook_rejection("invalid_sns_signature") from exc
        if verified.message_type == "SubscriptionConfirmation":
            if verified.subscribe_url is None:
                raise TicketIngressRejected(
                    code="sns_subscription_confirmation_rejected",
                    reason="SNS SubscribeURL is missing",
                    status_code=400,
                )
            try:
                await self._sns_subscription_confirmer.confirm_subscription(
                    verified.subscribe_url
                )
            except SnsConfirmationError as exc:
                raise TicketIngressRejected(
                    code="sns_subscription_confirmation_failed",
                    reason="SNS subscription confirmation failed",
                    status_code=502,
                ) from exc
            return TicketIngressServiceResult(
                ingress_id=None,
                canonical_envelope_id=None,
                status="subscription_confirmed",
            )
        set_current_tenant(routing_secret.tenant_id)
        channel_config = await tenant_runtime.resolve_active_channel_for_routing_address(
            channel_type=TenantChannelType.EMAIL,
            routing_address=routing_secret.routing_address,
            expected_tenant_id=routing_secret.tenant_id,
        )
        if channel_config is None:
            raise _uniform_webhook_rejection("unknown_channel_route")
        try:
            email_payload = await ses_sns_message_to_email_payload(
                sns_message=verified.message,
                tenant_id=channel_config.tenant_id,
                raw_email_fetcher=self._ses_raw_email_fetcher,
            )
        except SesEmailMimeError as exc:
            raise TicketIngressRejected(
                code="ses_email_mime_rejected",
                reason=str(exc),
            ) from exc
        security_context = ChannelWebhookSecurityContext(
            timestamp=verified.timestamp,
            nonce=verified.message_id,
        )
        if await self._webhook_nonce_exists(
            tenant_id=channel_config.tenant_id,
            channel_type=TenantChannelType.EMAIL.value,
            nonce=security_context.nonce,
        ):
            return WebhookDuplicateDeliveryResult()
        nonce_recorded = await self._record_webhook_freshness_nonce(
            tenant_id=channel_config.tenant_id,
            channel_type=TenantChannelType.EMAIL.value,
            body=sns_body,
            headers={},
            security_context=security_context,
        )
        if not nonce_recorded:
            return WebhookDuplicateDeliveryResult()
        email_message_id = email_payload.get("message_id")
        await self._persist_email_attachments(
            email_payload,
            tenant_id=channel_config.tenant_id,
            # The email's own MIME Message-ID (the stable per-email
            # identifier B2/B3 will look attachments up by) — NOT the SNS
            # envelope's MessageId, which only identifies this delivery.
            message_id=(
                email_message_id
                if isinstance(email_message_id, str)
                else verified.message_id
            ),
        )
        source_language = "en"
        fingerprint_metadata: dict[str, object] = {}
        ticket_text = _extract_webhook_ticket_text(
            channel_type=TenantChannelType.EMAIL,
            body=email_payload,
        )
        canonical_body: Any = email_payload
        webhook_request_id = _webhook_request_id(
            channel=TenantChannelType.EMAIL.value,
            routing_address=channel_config.routing_address,
            body=sns_body,
            raw_body=raw_body,
        )
        webhook_correlation_id = _webhook_correlation_id(
            channel=TenantChannelType.EMAIL.value,
            routing_address=channel_config.routing_address,
            body=sns_body,
            raw_body=raw_body,
        )
        if ticket_text:
            canonical_text, source_language = await self._canonicalize_ticket_text(
                raw_text=ticket_text,
                tenant_id=channel_config.tenant_id,
                correlation_id=webhook_correlation_id,
                request_id=webhook_request_id,
            )
            canonical_body = _replace_webhook_ticket_text(
                channel_type=TenantChannelType.EMAIL,
                body=email_payload,
                text=canonical_text,
            )
            fingerprint_metadata = self._fingerprint_metadata(canonical_text)
        payload = IngressPayload(
            body=canonical_body,
            content_type=content_type,
            headers={},
            raw_bytes=raw_body,
            request_path=request_path,
        )
        adapter = SesEmailWebhookAdapter(
            routing_address=channel_config.routing_address,
        )
        runtime = BoundaryIngressRuntime(
            adapters=BoundaryAdapterRegistry((adapter,)),
            persistence=self._persistence,
        )
        envelope = await runtime.ingest(
            BoundaryIngressRequest(
                source=BoundarySource(
                    source_type=BoundarySourceType.EMAIL,
                    source_id=channel_config.routing_address,
                    tenant_id=channel_config.tenant_id,
                    display_name="tenant email",
                    metadata={
                        "tenant_channel.config_id": str(channel_config.config_id),
                        "source_language": source_language,
                    },
                ),
                adapter_name=adapter.name,
                payload=payload,
                correlation_id=webhook_correlation_id,
                request_id=webhook_request_id,
                ingress_id_override=derive_ingress_id(
                    seed=_webhook_ingress_seed(
                        tenant_id=channel_config.tenant_id,
                        channel=TenantChannelType.EMAIL.value,
                        routing_address=channel_config.routing_address,
                        body=sns_body,
                        raw_body=raw_body,
                    )
                ),
                authority=AuthorityContext.from_raw(
                    tenant_id=channel_config.tenant_id,
                ),
                metadata={
                    "tenant_channel.config_id": str(channel_config.config_id),
                    "tenant_channel.channel_type": TenantChannelType.EMAIL.value,
                    "tenant_channel.routing_address": channel_config.routing_address,
                    "source_language": source_language,
                    **fingerprint_metadata,
                },
            )
        )
        await self._session.commit()
        result = envelope.result
        if result is None:
            raise TicketIngressServiceError("SES email webhook ingress failed")
        if not result.normalization.is_ok or result.event_id is None:
            raise TicketIngressRejected(
                code="ses_email_webhook_rejected",
                reason=result.normalization.error or "normalization failed",
            )
        await self._best_effort_enqueue_captured_ingress_dispatch(
            ingress_id=result.ingress_id,
            tenant_id=channel_config.tenant_id,
            channel=TenantChannelType.EMAIL.value,
            request_correlation_id=webhook_request_id,
        )
        await self._record_processing_admission_after_capture(
            tenant_id=channel_config.tenant_id,
            channel_type=TenantChannelType.EMAIL,
            request_correlation_id=webhook_request_id,
        )
        return TicketIngressServiceResult(
            ingress_id=str(result.ingress_id),
            canonical_envelope_id=str(result.event_id),
        )

    def _build_attachment_storage_service(self) -> AttachmentStorageService | None:
        """Build a request-scoped AttachmentStorageService, or None if
        attachment storage isn't configured (no S3 bucket, or no data
        protection master key) — callers degrade to today's metadata-only
        behavior rather than failing closed, since this is an additive
        capability (PR-B1b), not a hard ingestion dependency."""
        if self._attachment_blob_store is None:
            return None
        settings = get_settings()
        if (
            not settings.DATA_PROTECTION_MASTER_KEYS.strip()
            and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
        ):
            return None
        data_protection = DataProtectionService.from_settings(
            self._session,
            settings,
            master_key_unwrap=build_master_key_unwrap(settings),
            legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
        )
        repository = AttachmentRepository(
            self._session,
            data_protection=data_protection,
            blob_store=self._attachment_blob_store,
        )
        return AttachmentStorageService.from_settings(
            settings,
            repository=repository,
            blob_store=self._attachment_blob_store,
            data_protection=data_protection,
        )

    async def _persist_email_attachments(
        self,
        email_payload: dict[str, Any],
        *,
        tenant_id: str,
        message_id: str,
    ) -> None:
        """Persist each email attachment's binary via AttachmentStorageService.

        Fail-soft by design: a storage failure on ONE attachment (S3 down,
        an unexpected exception) is recorded as ``storage_status: "failed"``
        on that attachment's metadata and logged — it never raises, so it
        can never drop the surrounding email/ticket. A sniff/size rejection
        from the storage service itself is not a failure here; it is the
        service's normal "rejected" outcome and is recorded the same way.

        Mutates ``email_payload["attachments"]`` in place: every raw-bytes
        payload is popped (via ``pop_attachment_raw_bytes``) before this
        returns, regardless of outcome, since the dict is about to become
        part of a canonical payload that gets JSON-serialized.
        """
        attachments = email_payload.get("attachments")
        if not isinstance(attachments, list):
            return
        storage_service = self._build_attachment_storage_service()
        conversation_id = email_payload.get("conversation_id")
        for attachment in cast(list[dict[str, Any]], attachments):
            raw_bytes = pop_attachment_raw_bytes(attachment)
            if raw_bytes is None or storage_service is None:
                continue
            try:
                record: AttachmentRecord = await storage_service.store(
                    [raw_bytes],
                    tenant_id=tenant_id,
                    channel="email",
                    external_message_id=message_id,
                    conversation_id=(
                        conversation_id
                        if isinstance(conversation_id, str)
                        else None
                    ),
                    content_type_declared=attachment.get("content_type"),
                )
            except Exception as exc:  # noqa: BLE001 — fail-soft by design
                logger.warning(
                    "email_attachment_storage_failed",
                    extra={
                        "tenant_id": tenant_id,
                        "message_id": message_id,
                        "attachment_filename": attachment.get("filename"),
                        "error": str(exc),
                    },
                )
                attachment["storage_status"] = "failed"
                attachment["storage_error"] = str(exc)[:500]
                continue
            attachment["storage_status"] = record.status
            attachment["attachment_id"] = str(record.attachment_id)
            if record.status == "rejected":
                attachment["storage_rejection_reason"] = record.rejection_reason
                logger.info(
                    "email_attachment_rejected",
                    extra={
                        "tenant_id": tenant_id,
                        "message_id": message_id,
                        "attachment_filename": attachment.get("filename"),
                        "reason": record.rejection_reason,
                    },
                )

    async def verify_channel_webhook(
        self,
        *,
        channel_type: str,
        mode: str,
        verify_token: str,
        challenge: str,
        phone_number_id: str,
        tenant_hint: str | None = None,
    ) -> str:
        """Complete Meta's GET webhook verification handshake."""

        if self._tenant_configuration_runtime is None:
            raise TicketIngressServiceError(
                "tenant configuration runtime is not configured"
            )
        tenant_channel_type = _tenant_channel_type(channel_type)
        if tenant_channel_type is not TenantChannelType.WHATSAPP:
            raise TicketIngressRejected(
                code="unsupported_webhook_verification_channel",
                reason="webhook verification is supported for whatsapp only",
                status_code=404,
            )
        if mode != "subscribe":
            raise TicketIngressRejected(
                code="webhook_verification_rejected",
                reason="unsupported verification mode",
                status_code=403,
            )
        routing_address = phone_number_id.strip()
        if not routing_address:
            raise TicketIngressRejected(
                code="webhook_verification_rejected",
                reason="phone_number_id is required",
                status_code=400,
            )
        routing_secret = (
            await self._tenant_configuration_runtime
            .resolve_webhook_routing_secret(
                channel_type=TenantChannelType.WHATSAPP,
                routing_address=routing_address,
            )
        )
        await _end_read_only_routing_transaction(self._session)
        if routing_secret is None:
            raise TicketIngressRejected(
                code="webhook_verification_rejected",
                reason="unknown whatsapp route",
                status_code=403,
            )
        if tenant_hint is not None and tenant_hint != routing_secret.tenant_id:
            raise TicketIngressRejected(
                code="webhook_verification_rejected",
                reason="tenant route mismatch",
                status_code=403,
            )
        set_current_tenant(routing_secret.tenant_id)
        channel_config = (
            await self._tenant_configuration_runtime
            .resolve_active_channel_for_routing_address(
                channel_type=TenantChannelType.WHATSAPP,
                routing_address=routing_address,
                expected_tenant_id=routing_secret.tenant_id,
            )
        )
        if channel_config is None:
            raise TicketIngressRejected(
                code="webhook_verification_rejected",
                reason="unknown whatsapp route",
                status_code=403,
            )
        credentials = (
            await self._tenant_configuration_runtime.load_channel_credentials(
                tenant_id=routing_secret.tenant_id,
                channel_type=TenantChannelType.WHATSAPP,
            )
        )
        if not _whatsapp_verify_token_matches(
            supplied_token=verify_token,
            credentials=credentials,
            routing_secret=routing_secret,
        ):
            raise TicketIngressRejected(
                code="webhook_verification_rejected",
                reason="verify token mismatch",
                status_code=403,
            )
        return challenge

    async def _record_webhook_freshness_nonce(
        self,
        *,
        tenant_id: str,
        channel_type: str,
        body: Any,
        headers: Mapping[str, str],
        security_context: ChannelWebhookSecurityContext | None = None,
    ) -> bool:
        try:
            context = (
                security_context
                if security_context is not None
                else self._validated_webhook_security_context(
                    channel_type=channel_type,
                    body=body,
                    headers=headers,
                )
            )
            if security_context is not None:
                _enforce_webhook_freshness(
                    timestamp=context.timestamp,
                    received_at=datetime.now(timezone.utc),
                )
            received_at = datetime.now(timezone.utc)
            await self._persistence.record_webhook_nonce(
                WebhookNonceRecord(
                    tenant_id=tenant_id,
                    channel_type=channel_type,
                    nonce=context.nonce,
                    received_at=received_at,
                    expires_at=received_at
                    + timedelta(seconds=WEBHOOK_NONCE_TTL_SECONDS),
                )
            )
            return True
        except ValueError as exc:
            reason = str(exc)
            code = (
                "webhook_nonce_missing"
                if "nonce" in reason
                else "stale_webhook_timestamp"
            )
            raise TicketIngressRejected(
                code=code,
                reason=reason,
                status_code=400 if code == "webhook_nonce_missing" else 401,
            ) from exc
        except WebhookFreshnessError as exc:
            raise TicketIngressRejected(
                code="stale_webhook_timestamp",
                reason=str(exc),
                status_code=401,
            ) from exc
        except WebhookReplayError:
            return False

    async def _webhook_nonce_exists(
        self,
        *,
        tenant_id: str,
        channel_type: str,
        nonce: str,
    ) -> bool:
        return await self._persistence.webhook_nonce_exists(
            tenant_id=tenant_id,
            channel_type=channel_type,
            nonce=nonce,
            now=datetime.now(timezone.utc),
        )

    def _validated_webhook_security_context(
        self,
        *,
        channel_type: str,
        body: Any,
        headers: Mapping[str, str],
    ) -> ChannelWebhookSecurityContext:
        try:
            context = extract_webhook_security_context(
                channel_type=channel_type,
                body=body,
                headers=headers,
            )
            _enforce_webhook_freshness(
                timestamp=context.timestamp,
                received_at=datetime.now(timezone.utc),
            )
            return context
        except ValueError as exc:
            reason = str(exc)
            code = (
                "webhook_nonce_missing"
                if "nonce" in reason
                else "stale_webhook_timestamp"
            )
            raise TicketIngressRejected(
                code=code,
                reason=reason,
                status_code=400 if code == "webhook_nonce_missing" else 401,
            ) from exc
        except WebhookFreshnessError as exc:
            raise TicketIngressRejected(
                code="stale_webhook_timestamp",
                reason=str(exc),
                status_code=401,
            ) from exc

    async def _best_effort_enqueue_captured_ingress_dispatch(
        self,
        *,
        ingress_id: BoundaryIngressId,
        tenant_id: str,
        channel: str,
        request_correlation_id: str,
    ) -> None:
        if self._ingress_dispatch_enqueue is None:
            return
        outbox = await self._persistence.get_ingress_dispatch_outbox_by_ingress(
            ingress_id
        )
        if outbox is None:
            return
        try:
            self._ingress_dispatch_enqueue(outbox)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ingress_dispatch_immediate_enqueue_failed",
                extra={
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "request_correlation_id": request_correlation_id,
                    "ingress_id": str(ingress_id),
                    "outbox_id": str(outbox.outbox_id),
                },
            )

    async def _best_effort_capture_whatsapp_media(
        self,
        *,
        ingress_id: BoundaryIngressId,
        tenant_id: str,
        external_message_id: str | None,
        canonical_payload: Mapping[str, Any],
    ) -> None:
        """Write a durable pending row per Meta media placeholder and
        best-effort enqueue its fetch task — mirrors
        _best_effort_enqueue_captured_ingress_dispatch's shape exactly.
        Never blocks or fails the webhook: a durable row is the recovery
        path if the immediate enqueue is lost (see
        app.workers.whatsapp_media_fetch_tasks.reconcile_whatsapp_media_fetch).
        """
        if (
            self._whatsapp_media_fetch_repository is None
            or external_message_id is None
        ):
            return
        attachments = canonical_payload.get("attachments")
        if not isinstance(attachments, list):
            return
        for item in cast(list[object], attachments):
            if not isinstance(item, Mapping):
                continue
            typed_item = cast(Mapping[str, Any], item)
            if (
                typed_item.get("storage_status") != "pending"
                or typed_item.get("provider") != "meta"
            ):
                continue
            media_id = typed_item.get("media_id")
            if not isinstance(media_id, str) or not media_id:
                continue
            mime_type = typed_item.get("content_type_declared")
            record = await self._whatsapp_media_fetch_repository.create_pending(
                tenant_id=tenant_id,
                ingress_id=cast(uuid.UUID, ingress_id),
                external_message_id=external_message_id,
                media_id=media_id,
                mime_type=mime_type if isinstance(mime_type, str) else None,
            )
            if self._whatsapp_media_fetch_enqueue is None:
                continue
            try:
                self._whatsapp_media_fetch_enqueue(record)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "whatsapp_media_fetch_immediate_enqueue_failed",
                    extra={
                        "tenant_id": tenant_id,
                        "ingress_id": str(ingress_id),
                        "fetch_id": str(record.fetch_id),
                        "media_id": media_id,
                    },
                )

    async def _record_processing_admission_after_capture(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
        request_correlation_id: str,
    ) -> None:
        if self._admission_service is None:
            return
        queue_names = _admission_queues_for_channel(
            channel_type=channel_type,
            queue_by_channel=self._webhook_queue_by_channel,
        )
        decision = await self._admission_service.evaluate_and_persist(
            queue_names=queue_names,
            tenant_id=tenant_id,
            channel=channel_type.value,
            request_correlation_id=request_correlation_id,
        )
        if decision.outcome is AdmissionOutcome.ADMIT:
            return
        logger.warning(
            "post_capture_processing_admission_pressure_recorded",
            extra={
                "tenant_id": tenant_id,
                "channel": channel_type.value,
                "dispatch_recovery": "ingress_dispatch_outbox",
                "decision_id": str(decision.decision_id),
                "outcome": decision.outcome.value,
                "reason": (
                    decision.reason.value if decision.reason is not None else None
                ),
                "retry_after_seconds": decision.retry_after_seconds,
            },
        )


async def _end_read_only_routing_transaction(session: object) -> None:
    """End anonymous routing lookups before tenant-scoped RLS work begins."""

    rollback = getattr(session, "rollback", None)
    if rollback is None:
        return
    await cast(Callable[[], Awaitable[None]], rollback)()


class TicketIngressServiceError(RuntimeError):
    """Raised when ticket ingress cannot be durably recorded."""


class TicketIngressRejected(TicketIngressServiceError):
    """Raised when an inbound channel webhook is rejected at boundary."""

    def __init__(
        self,
        *,
        code: str,
        reason: str,
        status_code: int = 400,
        headers: Mapping[str, str] | None = None,
        response_body: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.response_body = dict(response_body) if response_body is not None else None


#: One opaque code + status for every pre-authentication webhook rejection so an
#: attacker cannot distinguish "route/tenant exists" from "bad signature" (#24).
WEBHOOK_REJECTED_CODE = "webhook_rejected"
_WEBHOOK_REJECTED_STATUS = 401


def _uniform_webhook_rejection(internal_reason: str) -> "TicketIngressRejected":
    """Build an identical rejection for every enumeration-sensitive cause.

    The specific ``internal_reason`` (unknown route, tenant mismatch, missing or
    invalid signature) is logged server-side only; the external response is byte
    identical so route / tenant existence cannot be probed (#24).
    """
    logger.warning("webhook_rejected", extra={"reason": internal_reason})
    return TicketIngressRejected(
        code=WEBHOOK_REJECTED_CODE,
        reason=WEBHOOK_REJECTED_CODE,
        status_code=_WEBHOOK_REJECTED_STATUS,
    )


def _adapter_registry() -> BoundaryAdapterRegistry:
    return BoundaryAdapterRegistry(
        [
            ZendeskWebhookAdapter(),
            WhatsAppWebhookAdapter(),
            TwilioVoiceAdapter(),
        ]
    )


def _to_boundary_request(
    *,
    external_id: str,
    channel: TicketChannel,
    raw_content: str,
    language_code: str,
    expected_tenant_id: str,
    source_language: str = "en",
    metadata: Mapping[str, object] | None = None,
) -> BoundaryIngressRequest:
    return BoundaryIngressRequest(
        source=BoundarySource(
            source_type=_source_type_for_channel(channel),
            source_id=f"ticket-{channel}",
            tenant_id=expected_tenant_id,
            display_name=f"ticket {channel}",
            metadata={
                "language_code": language_code,
                "source_language": source_language,
            },
        ),
        adapter_name=_adapter_name_for_channel(channel),
        payload=IngressPayload(
            body=_payload_body_for_request(
                external_id=external_id,
                channel=channel,
                raw_content=raw_content,
            ),
            content_type="application/json",
        ),
        correlation_id=external_id,
        request_id=external_id,
        authority=AuthorityContext.from_raw(
            tenant_id=expected_tenant_id,
        ),
        metadata={
            "ticket.external_id": external_id,
            "ticket.channel": channel,
            "ticket.language_code": language_code,
            "source_language": source_language,
            **dict(metadata or {}),
        },
    )


def _fingerprint_from_metadata(
    metadata: Mapping[str, object],
) -> tuple[int, ...] | None:
    raw = metadata.get("text_fingerprint")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray):
        return None
    values = cast(Sequence[object], raw)
    fingerprint: list[int] = []
    for value in values:
        if not isinstance(value, int):
            return None
        fingerprint.append(value)
    return tuple(fingerprint)


def _extract_quarantine_payload(
    *,
    tenant_id: str,
    channel: str,
    external_id: str,
    raw_content: str,
    language_code: str,
    source_language: str,
) -> dict[str, Any]:
    return {
        "content": raw_content,
        "channel": channel,
        "tenant_id": tenant_id,
        "external_id": external_id,
        "language_code": language_code,
        "metadata": {
            "source_language": source_language,
            "fingerprint_version": FINGERPRINT_VERSION,
        },
    }


def _source_type_for_channel(channel: TicketChannel) -> BoundarySourceType:
    if channel == "email":
        return BoundarySourceType.EMAIL
    if channel == "whatsapp":
        return BoundarySourceType.WHATSAPP
    return BoundarySourceType.TWILIO_VOICE


def _adapter_name_for_channel(channel: TicketChannel) -> str:
    if channel == "email":
        return ZendeskWebhookAdapter.DEFAULT_NAME
    if channel == "whatsapp":
        return WhatsAppWebhookAdapter.DEFAULT_NAME
    return TwilioVoiceAdapter.DEFAULT_NAME


def _payload_body_for_request(
    *,
    external_id: str,
    channel: TicketChannel,
    raw_content: str,
) -> dict[str, Any]:
    if channel == "email":
        return {
            "event_id": external_id,
            "ticket_id": external_id,
            "type": "ticket.comment_created",
            "subject": raw_content,
            "comment": raw_content,
            "status": "open",
        }
    if channel == "whatsapp":
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": "ticket-ingress"
                                },
                                "messages": [
                                    {
                                        "id": external_id,
                                        "from": external_id,
                                        "type": "text",
                                        "text": {"body": raw_content},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    return {
        "CallSid": external_id,
        "CallStatus": "completed",
        "Direction": "inbound",
        "From": external_id,
        "To": "ticket-ingress",
        "Transcript": raw_content,
    }


def _extract_webhook_ticket_text(
    *,
    channel_type: TenantChannelType,
    body: Any,
) -> str | None:
    if not isinstance(body, Mapping):
        return None
    payload = cast(Mapping[str, Any], body)
    if channel_type is TenantChannelType.EMAIL:
        return _first_text_value(payload.get("text"), payload.get("message"))
    if channel_type is TenantChannelType.WHATSAPP:
        return _first_text_value(
            _nested(
                payload,
                "entry",
                0,
                "changes",
                0,
                "value",
                "messages",
                0,
                "text",
                "body",
            )
        )
    if channel_type is TenantChannelType.SHULEX:
        return _first_text_value(payload.get("message"), payload.get("text"))
    if channel_type is TenantChannelType.LARK:
        content = _nested(payload, "event", "message", "content")
        return _extract_lark_text(content)
    return None


def _replace_webhook_ticket_text(
    *,
    channel_type: TenantChannelType,
    body: Any,
    text: str,
) -> Any:
    if not isinstance(body, Mapping):
        return body
    updated: dict[str, Any] = deepcopy(dict(cast(Mapping[str, Any], body)))
    try:
        if channel_type is TenantChannelType.EMAIL:
            if "text" in updated:
                updated["text"] = text
            elif "message" in updated:
                updated["message"] = text
            return updated
        if channel_type is TenantChannelType.WHATSAPP:
            message_text = _nested(
                updated,
                "entry",
                0,
                "changes",
                0,
                "value",
                "messages",
                0,
                "text",
            )
            if isinstance(message_text, dict):
                cast(dict[str, Any], message_text)["body"] = text
            return updated
        if channel_type is TenantChannelType.SHULEX:
            if "message" in updated:
                updated["message"] = text
            elif "text" in updated:
                updated["text"] = text
            return updated
        if channel_type is TenantChannelType.LARK:
            message = _nested(updated, "event", "message")
            if isinstance(message, dict):
                message_payload = cast(dict[str, Any], message)
                content = message_payload.get("content")
                if isinstance(content, str):
                    try:
                        decoded = json.loads(content)
                    except json.JSONDecodeError:
                        message_payload["content"] = text
                    else:
                        if isinstance(decoded, dict):
                            decoded_payload = cast(dict[str, Any], decoded)
                            decoded_payload["text"] = text
                            message_payload["content"] = json.dumps(
                                decoded,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                        else:
                            message_payload["content"] = text
            return updated
        return updated
    except (IndexError, KeyError, TypeError):
        return dict(cast(Mapping[str, Any], body))


def _extract_lark_text(content: Any) -> str | None:
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return _first_text_value(content)
        if isinstance(decoded, Mapping):
            decoded_payload = cast(Mapping[str, Any], decoded)
            return _first_text_value(decoded_payload.get("text"))
        return None
    if isinstance(content, Mapping):
        content_payload = cast(Mapping[str, Any], content)
        return _first_text_value(content_payload.get("text"))
    return None


def _nested(value: Any, *path: object) -> Any:
    current: Any = value
    for key in path:
        if isinstance(key, int):
            if not isinstance(current, Sequence) or isinstance(
                current, (str, bytes, bytearray)
            ):
                return None
            sequence = cast(Sequence[Any], current)
            if key >= len(sequence):
                return None
            current = sequence[key]
            continue
        if not isinstance(current, Mapping):
            return None
        mapping = cast(Mapping[object, Any], current)
        current = mapping.get(key)
    return current


def _first_text_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tenant_channel_type(channel_type: str) -> TenantChannelType:
    try:
        parsed = TenantChannelType(channel_type)
    except ValueError as exc:
        raise TicketIngressRejected(
            code="unsupported_channel_type",
            reason="channel type is not supported for webhooks",
        ) from exc
    if parsed not in {
        TenantChannelType.EMAIL,
        TenantChannelType.WHATSAPP,
        TenantChannelType.SHULEX,
        TenantChannelType.LARK,
    }:
        raise TicketIngressRejected(
            code="unsupported_channel_type",
            reason="channel type is not supported for webhooks",
        )
    return parsed


def _is_sns_webhook_body(body: Any) -> bool:
    if not isinstance(body, Mapping):
        return False
    typed = cast(Mapping[str, Any], body)
    return _first_text_value(
        typed.get("Type"),
        typed.get("TopicArn"),
        typed.get("SigningCertURL"),
        typed.get("Signature"),
    ) is not None and _first_text_value(typed.get("TopicArn")) is not None


def _sns_body_mapping(body: Any) -> Mapping[str, Any]:
    if not isinstance(body, Mapping):
        raise TicketIngressRejected(
            code="sns_webhook_body_malformed",
            reason="SNS webhook body must be a JSON object",
        )
    return cast(Mapping[str, Any], body)


def _admission_queues_for_channel(
    *,
    channel_type: TenantChannelType,
    queue_by_channel: Mapping[TenantChannelType, Sequence[str]],
) -> tuple[str, ...]:
    queue_names = queue_by_channel.get(channel_type)
    if queue_names is not None:
        return tuple(queue_names)
    raise TicketIngressServiceError(
        f"admission queue map is not configured for {channel_type.value}"
    )


def _routing_address_for_webhook(
    *,
    channel_type: str,
    body: Any,
    headers: Mapping[str, str],
) -> str:
    try:
        return extract_routing_address(
            channel_type=channel_type,
            body=body,
            headers=headers,
        )
    except ValueError as exc:
        raise TicketIngressRejected(
            code="channel_routing_address_missing",
            reason=str(exc),
        ) from exc


def _webhook_adapter_for_channel(
    *,
    channel_type: TenantChannelType,
    webhook_secret: str,
    routing_address: str,
) -> BaseIngressAdapter:
    if channel_type is TenantChannelType.EMAIL:
        return EmailWebhookAdapter(
            webhook_secret=webhook_secret,
            routing_address=routing_address,
        )
    if channel_type is TenantChannelType.WHATSAPP:
        return TenantWhatsAppWebhookAdapter(
            webhook_secret=webhook_secret,
            routing_address=routing_address,
        )
    if channel_type is TenantChannelType.SHULEX:
        return ShulexWebhookAdapter(
            webhook_secret=webhook_secret,
            routing_address=routing_address,
        )
    if channel_type is TenantChannelType.LARK:
        return LarkWebhookAdapter(
            webhook_secret=webhook_secret,
            routing_address=routing_address,
        )
    raise TicketIngressRejected(
        code="unsupported_channel_type",
        reason="channel type is not supported for webhooks",
    )


def _source_type_for_tenant_channel(
    channel_type: TenantChannelType,
) -> BoundarySourceType:
    if channel_type is TenantChannelType.EMAIL:
        return BoundarySourceType.EMAIL
    if channel_type is TenantChannelType.WHATSAPP:
        return BoundarySourceType.WHATSAPP
    if channel_type is TenantChannelType.SHULEX:
        return BoundarySourceType.SHULEX
    if channel_type is TenantChannelType.LARK:
        return BoundarySourceType.LARK
    return BoundarySourceType.GENERIC


def _enforce_webhook_freshness(
    *,
    timestamp: datetime,
    received_at: datetime,
) -> None:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    else:
        received_at = received_at.astimezone(timezone.utc)
    drift_seconds = abs((received_at - timestamp).total_seconds())
    if drift_seconds > WEBHOOK_FRESHNESS_WINDOW_SECONDS:
        raise WebhookFreshnessError(
            "webhook timestamp is outside the freshness window"
        )


def _select_webhook_secret(
    *,
    channel_type: TenantChannelType,
    channel_config: (
        TenantChannelConfigurationRecord | TenantWebhookRoutingSecretRecord
    ),
    body: Any,
    headers: Mapping[str, str],
    raw_body: bytes | None,
    request_path: str | None = None,
) -> str:
    previous_secret = channel_config.previous_webhook_secret
    expires_at = channel_config.credential_rotation_expires_at
    if previous_secret is None or expires_at is None:
        return channel_config.webhook_secret
    if expires_at <= datetime.now(timezone.utc):
        return channel_config.webhook_secret
    if _webhook_signature_matches_secret(
        channel_type=channel_type,
        secret=previous_secret,
        body=body,
        headers=headers,
        raw_body=raw_body,
        request_path=request_path,
    ):
        return previous_secret
    return channel_config.webhook_secret


def _whatsapp_verify_token_matches(
    *,
    supplied_token: str,
    credentials: Mapping[str, Any],
    routing_secret: TenantWebhookRoutingSecretRecord,
) -> bool:
    token = supplied_token.strip()
    if not token:
        return False
    configured_tokens = [
        value.strip()
        for key in (
            "webhook_verify_token",
            "verify_token",
            "whatsapp_verify_token",
            "meta_verify_token",
        )
        for value in (credentials.get(key),)
        if isinstance(value, str) and value.strip()
    ]
    if not configured_tokens and routing_secret.webhook_secret.strip():
        configured_tokens.append(routing_secret.webhook_secret.strip())
    return any(hmac.compare_digest(token, candidate) for candidate in configured_tokens)


def _webhook_signature_matches_secret(
    *,
    channel_type: TenantChannelType,
    secret: str,
    body: Any,
    headers: Mapping[str, str],
    raw_body: bytes | None,
    request_path: str | None = None,
) -> bool:
    if channel_type is TenantChannelType.EMAIL:
        return _sha256_signature_matches(
            secret=secret,
            body=body,
            headers=headers,
            raw_body=raw_body,
            header_names=(
                "x-operious-signature",
                "x-email-signature",
                "x-amz-sns-message-signature",
            ),
        )
    if channel_type is TenantChannelType.WHATSAPP:
        return (
            _sha256_signature_matches(
                secret=secret,
                body=body,
                headers=headers,
                raw_body=raw_body,
                header_names=("x-hub-signature-256", "x-operious-signature"),
            )
            or _twilio_signature_matches(
                secret=secret,
                body=body,
                headers=headers,
                request_path=request_path,
            )
        )
    if channel_type is TenantChannelType.SHULEX:
        return _sha256_signature_matches(
            secret=secret,
            body=body,
            headers=headers,
            raw_body=raw_body,
            header_names=("x-shulex-signature", "x-operious-signature"),
        )
    if channel_type is TenantChannelType.LARK:
        return _lark_signature_matches(
            secret=secret,
            body=body,
            headers=headers,
            raw_body=raw_body,
        )
    return False


def _webhook_signature_header_present(
    *,
    channel_type: TenantChannelType,
    headers: Mapping[str, str],
) -> bool:
    if channel_type is TenantChannelType.EMAIL:
        return _any_header(
            headers,
            (
                "x-operious-signature",
                "x-email-signature",
                "x-amz-sns-message-signature",
            ),
        )
    if channel_type is TenantChannelType.WHATSAPP:
        return _any_header(
            headers,
            (
                "x-hub-signature-256",
                "x-operious-signature",
                "x-twilio-signature",
            ),
        )
    if channel_type is TenantChannelType.SHULEX:
        return _any_header(
            headers,
            ("x-shulex-signature", "x-operious-signature"),
        )
    if channel_type is TenantChannelType.LARK:
        return _header(headers, "x-lark-signature") is not None
    return False


def _sha256_signature_matches(
    *,
    secret: str,
    body: Any,
    headers: Mapping[str, str],
    raw_body: bytes | None,
    header_names: tuple[str, ...],
) -> bool:
    signature = None
    for name in header_names:
        signature = _header(headers, name)
        if signature:
            break
    if not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        _signature_bytes(body=body, raw_body=raw_body),
        hashlib.sha256,
    ).hexdigest()
    supplied = signature.strip()
    if supplied.startswith("sha256="):
        supplied = supplied.removeprefix("sha256=")
    return hmac.compare_digest(supplied.lower(), expected.lower())


def _twilio_signature_matches(
    *,
    secret: str,
    body: Any,
    headers: Mapping[str, str],
    request_path: str | None,
) -> bool:
    signature = _header(headers, TWILIO_SIGNATURE_HEADER)
    if not signature or not isinstance(body, Mapping):
        return False
    typed_body = cast(Mapping[str, Any], body)
    url = _twilio_canonical_url(headers=headers, request_path=request_path)
    if url is None:
        return False
    return verify_twilio_signature(
        auth_token=secret,
        url=url,
        params=typed_body,
        signature=signature,
    )


def _twilio_canonical_url(
    *,
    headers: Mapping[str, str],
    request_path: str | None,
) -> str | None:
    """The URL the Twilio signature is verified against (#23).

    Derived server-side from ``PUBLIC_BASE_URL`` + the trusted request path.
    The client-supplied canonical-URL header is honoured only when
    ``WEBHOOK_TRUST_URL_HEADER`` is explicitly enabled (non-prod).
    """
    settings = get_settings()
    if settings.WEBHOOK_TRUST_URL_HEADER:
        return _header(headers, TWILIO_CANONICAL_URL_HEADER)
    if request_path is None:
        return None
    try:
        return derive_canonical_webhook_url(
            public_base_url=settings.public_base_url_normalized,
            request_path=request_path,
            query_string="",
        )
    except CanonicalWebhookUrlError:
        return None


def _lark_signature_matches(
    *,
    secret: str,
    body: Any,
    headers: Mapping[str, str],
    raw_body: bytes | None,
) -> bool:
    signature = _header(headers, "x-lark-signature")
    timestamp = _header(headers, "x-lark-request-timestamp")
    nonce = _header(headers, "x-lark-request-nonce")
    if not signature or timestamp is None or nonce is None:
        return False
    signed = timestamp.encode("utf-8") + nonce.encode("utf-8")
    signed += _signature_bytes(body=body, raw_body=raw_body)
    expected = hmac.new(
        secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()
    supplied = signature.strip()
    if supplied.startswith("sha256="):
        supplied = supplied.removeprefix("sha256=")
    return hmac.compare_digest(supplied.lower(), expected.lower())


def _signature_bytes(*, body: Any, raw_body: bytes | None) -> bytes:
    if raw_body is not None:
        return raw_body
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _any_header(
    headers: Mapping[str, str],
    names: tuple[str, ...],
) -> bool:
    return any(_header(headers, name) is not None for name in names)


def _webhook_ingress_seed(
    *,
    tenant_id: str,
    channel: str,
    routing_address: str,
    body: Any,
    raw_body: bytes | None,
) -> str:
    return "|".join(
        (
            "tenant-channel-webhook",
            tenant_id,
            channel,
            routing_address,
            _payload_fingerprint(body=body, raw_body=raw_body),
        )
    )


def _webhook_correlation_id(
    *,
    channel: str,
    routing_address: str,
    body: Any,
    raw_body: bytes | None,
) -> str:
    return "webhook:" + _short_fingerprint(
        channel=channel,
        routing_address=routing_address,
        body=body,
        raw_body=raw_body,
    )


def _webhook_request_id(
    *,
    channel: str,
    routing_address: str,
    body: Any,
    raw_body: bytes | None,
) -> str:
    return "request:" + _short_fingerprint(
        channel=channel,
        routing_address=routing_address,
        body=body,
        raw_body=raw_body,
    )


def _short_fingerprint(
    *,
    channel: str,
    routing_address: str,
    body: Any,
    raw_body: bytes | None,
) -> str:
    material = "|".join(
        (
            channel,
            routing_address,
            _payload_fingerprint(body=body, raw_body=raw_body),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _payload_fingerprint(*, body: Any, raw_body: bytes | None) -> str:
    if raw_body is not None:
        payload = raw_body
    else:
        payload = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "TicketChannel",
    "WebhookTicketChannel",
    "TicketIngressRejected",
    "TicketIngressService",
    "TicketIngressServiceError",
    "TicketIngressServiceResult",
    "WebhookDuplicateDeliveryResult",
]
