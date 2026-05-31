"""Tenant-configured JSON webhook delivery adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.http import get_shared_http_client
from app.core.ssrf import validate_public_https_url

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
    """POST JSON to a tenant-configured webhook URL.

    Tenant URLs are attacker-influenced, so every destination is SSRF
    validated (HTTPS only, public address only, optional SaaS allowlist)
    BEFORE connecting, and redirects are never followed (S-06).
    """

    def __init__(self, *, allowed_hosts: tuple[str, ...] | None = None) -> None:
        # ``None`` -> read the operator-configured allowlist at call time.
        self._allowed_hosts = allowed_hosts

    def _resolved_allowed_hosts(self) -> tuple[str, ...]:
        if self._allowed_hosts is not None:
            return self._allowed_hosts
        return get_settings().outbound_webhook_allowed_hosts

    async def post(
        self,
        request: OutboundWebhookRequest,
    ) -> OutboundWebhookResponse:
        # SSRF guard runs off-loop (DNS resolution is blocking) and
        # raises SSRFValidationError, which the dispatch layer records as
        # a failed delivery.
        await asyncio.to_thread(
            validate_public_https_url,
            request.url,
            allowed_hosts=self._resolved_allowed_hosts(),
        )
        client = get_shared_http_client()
        response = await client.post(
            request.url,
            json=request.payload,
            headers={
                "Authorization": request.auth_header,
                "Content-Type": "application/json",
            },
            timeout=request.timeout_seconds,
            follow_redirects=False,
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
