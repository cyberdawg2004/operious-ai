"""Ticket ingress service composition (PR-W1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.adapters.builtin import (
    TwilioVoiceAdapter,
    WhatsAppWebhookAdapter,
    ZendeskWebhookAdapter,
)
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import BoundarySourceType
from app.boundary.idempotency.registry import BoundaryIdempotencyRegistry
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import BoundaryPersistenceProtocol
from app.boundary.registry import BoundaryAdapterRegistry
from app.identity import AuthorityContext

TicketChannel = Literal["email", "whatsapp", "voice"]


@dataclass(frozen=True, slots=True)
class TicketIngressServiceResult:
    ingress_id: str
    canonical_envelope_id: str


class TicketIngressService:
    """Service boundary for ticket ingress writes."""

    def __init__(
        self,
        *,
        persistence: BoundaryPersistenceProtocol,
        session: AsyncSession,
    ) -> None:
        self._persistence = persistence
        self._session = session

    async def process(
        self,
        *,
        external_id: str,
        channel: TicketChannel,
        raw_content: str,
        language_code: str,
        expected_tenant_id: str,
    ) -> TicketIngressServiceResult:
        runtime = BoundaryIngressRuntime(
            adapters=_adapter_registry(),
            idempotency=BoundaryIdempotencyRegistry(),
            persistence=self._persistence,
        )
        envelope = await runtime.ingest(
            _to_boundary_request(
                external_id=external_id,
                channel=channel,
                raw_content=raw_content,
                language_code=language_code,
                expected_tenant_id=expected_tenant_id,
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


class TicketIngressServiceError(RuntimeError):
    """Raised when ticket ingress cannot be durably recorded."""


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
) -> BoundaryIngressRequest:
    return BoundaryIngressRequest(
        source=BoundarySource(
            source_type=_source_type_for_channel(channel),
            source_id=f"ticket-{channel}",
            tenant_id=expected_tenant_id,
            display_name=f"ticket {channel}",
            metadata={"language_code": language_code},
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


__all__ = [
    "TicketChannel",
    "TicketIngressService",
    "TicketIngressServiceError",
    "TicketIngressServiceResult",
]
