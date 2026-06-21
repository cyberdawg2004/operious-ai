"""Meta Graph API two-hop media fetch (Phase B1.5).

A WhatsApp webhook carries a media id, never bytes. Resolving it
requires two GETs:

1. ``GET /v{version}/{media_id}`` on the Graph API (Bearer auth) ->
   ``{url, mime_type}``. ``url`` is a short-lived (~5-15 min TTL)
   signed download URL — never persisted, only used immediately.
2. ``GET {url}`` — ALSO requires the same Bearer token (Meta's media
   URLs are not self-authenticating, unlike Twilio's).

Both hops never follow redirects and validate the destination via the
same SSRF pattern as ``WhatsAppGraphSender.send_text_message``
(app.boundary.outbound.whatsapp): pinned-IP transport after a
public-HTTPS-only validation. Hop 1's host is the well-known,
tenant-configured Graph API host, so it gets a strict host allowlist.
Hop 2's host is Meta-controlled but dynamic (a CDN host returned in
hop 1's own response, not tenant- or attacker-supplied) — it gets the
same public-IP-only validation with an OPEN host allowlist, per the
approved B1.5 spec.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.boundary.outbound.whatsapp import WhatsAppSSRFValidator
from app.core.http import create_isolated_http_client
from app.core.ssrf import PinnedIPAsyncHTTPTransport, validate_public_https_url

_MAX_ERROR_BODY_CHARS = 2048


@dataclass(frozen=True, slots=True)
class WhatsAppMediaUrlResolution:
    url: str
    mime_type: str | None


class WhatsAppMediaFetchHTTPResponseProtocol(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...

    def json(self) -> Any: ...


class WhatsAppMediaFetchHTTPClientProtocol(Protocol):
    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> WhatsAppMediaFetchHTTPResponseProtocol: ...


class WhatsAppMediaFetchError(RuntimeError):
    """Raised when either Graph API hop refuses or returns unusable data."""

    def __init__(self, *, hop: str, status_code: int, response_body: str) -> None:
        super().__init__(f"whatsapp media fetch hop {hop} returned {status_code}")
        self.hop = hop
        self.status_code = status_code
        self.response_body = response_body[:_MAX_ERROR_BODY_CHARS]


class WhatsAppGraphMediaFetcher:
    """Resolve a Meta media id to bytes via the two-hop Graph API flow."""

    def __init__(
        self,
        *,
        client: WhatsAppMediaFetchHTTPClientProtocol | None = None,
        graph_allowed_hosts: tuple[str, ...] | None = None,
        ssrf_validator: WhatsAppSSRFValidator | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._client = client
        self._graph_allowed_hosts = graph_allowed_hosts
        self._ssrf_validator = ssrf_validator or validate_public_https_url
        self._timeout_seconds = timeout_seconds

    def _resolved_graph_allowed_hosts(self) -> tuple[str, ...]:
        if self._graph_allowed_hosts is not None:
            return self._graph_allowed_hosts
        from app.core.config import get_settings

        return get_settings().whatsapp_graph_allowed_hosts

    async def resolve_media_url(
        self,
        media_id: str,
        *,
        access_token: str,
        graph_api_base_url: str,
        graph_api_version: str,
    ) -> WhatsAppMediaUrlResolution:
        """Hop 1: resolve a media id to a short-lived signed download URL."""
        url = "/".join(
            (
                graph_api_base_url.rstrip("/"),
                graph_api_version.strip("/"),
                media_id.strip("/"),
            )
        )
        response = await self._get(
            url,
            access_token=access_token,
            allowed_hosts=self._resolved_graph_allowed_hosts(),
            hop="resolve_media_url",
        )
        raw_body: object = response.json()
        body: Mapping[str, object] = (
            cast(Mapping[str, object], raw_body) if isinstance(raw_body, Mapping) else {}
        )
        resolved_url = body.get("url")
        if not isinstance(resolved_url, str) or not resolved_url:
            raise WhatsAppMediaFetchError(
                hop="resolve_media_url",
                status_code=response.status_code,
                response_body="response missing 'url'",
            )
        mime_type = body.get("mime_type")
        return WhatsAppMediaUrlResolution(
            url=resolved_url,
            mime_type=mime_type if isinstance(mime_type, str) else None,
        )

    async def download_media(
        self,
        url: str,
        *,
        access_token: str,
    ) -> bytes:
        """Hop 2: download the signed URL's bytes. Same Bearer token as hop
        1 — Meta's media URLs 401 without it, unlike Twilio's pre-signed
        URLs. Open host allowlist: this URL is the response body of OUR
        own authenticated hop-1 call, not tenant- or attacker-supplied."""
        response = await self._get(
            url,
            access_token=access_token,
            allowed_hosts=(),
            hop="download_media",
        )
        return response.content

    async def _get(
        self,
        url: str,
        *,
        access_token: str,
        allowed_hosts: tuple[str, ...],
        hop: str,
    ) -> WhatsAppMediaFetchHTTPResponseProtocol:
        validated = await asyncio.to_thread(
            self._ssrf_validator,
            url,
            allowed_hosts=allowed_hosts,
        )
        headers = {"Authorization": f"Bearer {access_token}"}
        if self._client is not None:
            response = await self._client.get(
                validated.url,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        else:
            transport = PinnedIPAsyncHTTPTransport(pinned_ip=validated.pinned_ip)
            async with create_isolated_http_client(
                transport=transport,
                timeout_seconds=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    validated.url,
                    headers=headers,
                    timeout=self._timeout_seconds,
                    follow_redirects=False,
                )
        if not 200 <= response.status_code < 300:
            raise WhatsAppMediaFetchError(
                hop=hop,
                status_code=response.status_code,
                response_body=getattr(response, "text", ""),
            )
        return response


__all__ = [
    "WhatsAppGraphMediaFetcher",
    "WhatsAppMediaFetchError",
    "WhatsAppMediaFetchHTTPClientProtocol",
    "WhatsAppMediaFetchHTTPResponseProtocol",
    "WhatsAppMediaUrlResolution",
]
