"""Ticket ingress service composition (PR-W1)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
from app.boundary.identity import derive_ingress_id
from app.boundary.ingress import BoundaryIngressRuntime
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
from app.db.tenant_context import set_current_tenant
from app.governance.capability import OperationalAct
from app.hardening.admission import (
    AdmissionDecision,
    AdmissionOutcome,
)
from app.identity import AuthorityContext, TenantId
from app.language import LanguageDetector
from app.services.admission_service import AdmissionService
from app.tenant.enums import TenantChannelType
from app.tenant.persistence import TenantChannelConfigurationRecord
from app.tenant.runtime import TenantConfigurationRuntime

TicketChannel = Literal["email", "whatsapp", "voice"]
WebhookTicketChannel = Literal["email", "whatsapp", "shulex", "lark"]
WEBHOOK_FRESHNESS_WINDOW_SECONDS = 300
WEBHOOK_NONCE_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class TicketIngressServiceResult:
    ingress_id: str
    canonical_envelope_id: str


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
        webhook_queue_by_channel: (
            Mapping[TenantChannelType, Sequence[str]] | None
        ) = None,
    ) -> None:
        self._persistence = persistence
        self._session = session
        self._tenant_configuration_runtime = tenant_configuration_runtime
        self._admission_service = admission_service
        self._translation_runtime = translation_runtime
        self._language_detector = language_detector or LanguageDetector()
        self._webhook_queue_by_channel = {
            channel_type: tuple(queue_names)
            for channel_type, queue_names in (webhook_queue_by_channel or {}).items()
        }

    async def process(
        self,
        *,
        external_id: str,
        channel: TicketChannel,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
    ) -> TicketIngressServiceResult:
        canonical_content, source_language = await self._canonicalize_ticket_text(
            raw_text=raw_content,
            tenant_id=expected_tenant_id,
            correlation_id=external_id,
            request_id=external_id,
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
            )
        )
        if envelope.error is not None:
            raise TicketIngressServiceError("ticket ingress failed")
        result = envelope.result
        if result is None or result.event_id is None:
            raise TicketIngressServiceError(
                "ticket ingress did not produce a canonical event"
            )

        await self._session.commit()
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

    async def process_channel_webhook(
        self,
        *,
        channel_type: str,
        body: Any,
        headers: Mapping[str, str],
        raw_body: bytes | None,
        content_type: str | None,
        tenant_hint: str | None = None,
    ) -> TicketIngressServiceResult | WebhookDuplicateDeliveryResult:
        if self._tenant_configuration_runtime is None:
            raise TicketIngressServiceError(
                "tenant configuration runtime is not configured"
            )
        tenant_channel_type = _tenant_channel_type(channel_type)
        routing_address = _routing_address_for_webhook(
            channel_type=tenant_channel_type.value,
            body=body,
            headers=headers,
        )
        resolved_tenant_id = (
            await self._tenant_configuration_runtime.resolve_tenant_by_routing_address(
                routing_address=routing_address,
            )
        )
        await _end_read_only_routing_transaction(self._session)
        if resolved_tenant_id is None:
            raise TicketIngressRejected(
                code="unknown_channel_route",
                reason="channel route is not configured or active",
            )
        if tenant_hint is not None and tenant_hint != resolved_tenant_id:
            raise TicketIngressRejected(
                code="tenant_route_mismatch",
                reason="channel route does not belong to tenant scope",
            )
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
            raise TicketIngressRejected(
                code="unknown_channel_route",
                reason="channel route is not configured or active",
            )

        if not _webhook_signature_header_present(
            channel_type=tenant_channel_type,
            headers=headers,
        ):
            raise TicketIngressRejected(
                code="missing_signature",
                reason="webhook signature header is required",
                status_code=401,
            )
        webhook_secret = _select_webhook_secret(
            channel_type=tenant_channel_type,
            channel_config=channel_config,
            body=body,
            headers=headers,
            raw_body=raw_body,
        )
        if not _webhook_signature_matches_secret(
            channel_type=tenant_channel_type,
            secret=webhook_secret,
            body=body,
            headers=headers,
            raw_body=raw_body,
        ):
            raise TicketIngressRejected(
                code="invalid_signature",
                reason="invalid_signature",
                status_code=401,
            )
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
        await self._enforce_admission(
            tenant_id=channel_config.tenant_id,
            channel_type=tenant_channel_type,
            request_correlation_id=_webhook_request_id(
                channel=tenant_channel_type.value,
                routing_address=channel_config.routing_address,
                body=body,
                raw_body=raw_body,
            ),
        )
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
        payload = IngressPayload(
            body=canonical_body,
            content_type=content_type,
            headers=dict(headers),
            raw_bytes=raw_body,
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
            raise TicketIngressRejected(
                code="invalid_signature",
                reason=result.normalization.error or "invalid_signature",
                status_code=401,
            )
        if not result.normalization.is_ok or result.event_id is None:
            raise TicketIngressRejected(
                code="channel_webhook_rejected",
                reason=result.normalization.error or "normalization failed",
            )
        return TicketIngressServiceResult(
            ingress_id=str(result.ingress_id),
            canonical_envelope_id=str(result.event_id),
        )

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

    async def _enforce_admission(
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
        raise _admission_rejection(decision)


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
        },
    )


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


def _admission_rejection(decision: AdmissionDecision) -> TicketIngressRejected:
    reason = decision.reason.value if decision.reason is not None else "UNKNOWN"
    headers = {
        "X-Operious-Admission-Decision-Id": str(decision.decision_id),
    }
    if decision.outcome is AdmissionOutcome.DEFER:
        headers["Retry-After"] = str(decision.retry_after_seconds)
        return TicketIngressRejected(
            code="admission_deferred",
            reason=reason,
            status_code=503,
            headers=headers,
            response_body={
                "error": "admission_deferred",
                "reason": reason,
                "decision_id": str(decision.decision_id),
                "retry_after_seconds": decision.retry_after_seconds,
                "message": "Platform under pressure. Retry after delay.",
            },
        )
    return TicketIngressRejected(
        code="admission_rejected",
        reason=reason,
        status_code=429,
        headers=headers,
        response_body={
            "error": "admission_rejected",
            "reason": reason,
            "decision_id": str(decision.decision_id),
            "message": "Platform capacity exceeded. Request rejected.",
        },
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
    channel_config: TenantChannelConfigurationRecord,
    body: Any,
    headers: Mapping[str, str],
    raw_body: bytes | None,
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
    ):
        return previous_secret
    return channel_config.webhook_secret


def _webhook_signature_matches_secret(
    *,
    channel_type: TenantChannelType,
    secret: str,
    body: Any,
    headers: Mapping[str, str],
    raw_body: bytes | None,
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
) -> bool:
    signature = _header(headers, "x-twilio-signature")
    webhook_url = _header(headers, "x-operious-webhook-url")
    if not signature or webhook_url is None or not isinstance(body, Mapping):
        return False
    pieces = [webhook_url]
    typed_body = cast(Mapping[str, Any], body)
    for key in sorted(str(k) for k in typed_body.keys()):
        value = typed_body.get(key)
        pieces.append(key)
        pieces.append("" if value is None else str(value))
    expected = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            "".join(pieces).encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    return hmac.compare_digest(signature.strip(), expected)


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
