"""Tenant-configured JSON webhook delivery adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.http import get_shared_http_client

_MAX_RESPONSE_BODY_CHARS = 2048

# WHY: Channel adapters never import Governance substrate.
# Constitutional rule: the adapter layer is a pure transport
# layer. Governance decisions are made above the adapter by
# the dispatch/orchestration layer before the adapter is called.


@dataclass(frozen=True, slots=True)
class OutboundWebhookRequest:
    url: str
    payload: dict[str, Any]
    auth_header: str
    channel_type: str
    timeout_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class OutboundWebhookResponse:
    status_code: int
    response_body: str
    success: bool


class OutboundWebhookAdapter:
    """POST JSON to a tenant-configured webhook URL."""

    async def post(
        self,
        request: OutboundWebhookRequest,
    ) -> OutboundWebhookResponse:
        client = get_shared_http_client()
        response = await client.post(
            request.url,
            json=request.payload,
            headers={
                "Authorization": request.auth_header,
                "Content-Type": "application/json",
            },
            timeout=request.timeout_seconds,
        )
        body = response.text[:_MAX_RESPONSE_BODY_CHARS]
        return OutboundWebhookResponse(
            status_code=response.status_code,
            response_body=body,
            success=200 <= response.status_code < 300,
        )


__all__ = [
    "OutboundWebhookAdapter",
    "OutboundWebhookRequest",
    "OutboundWebhookResponse",
]
