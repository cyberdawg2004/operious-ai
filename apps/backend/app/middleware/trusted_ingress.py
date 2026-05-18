"""Trusted-ingress chain hardening (Wedge C4).

Enforces that authority-bearing headers — both the ``Authorization``
credential header and the canonical ``X-*-ID`` legacy identity
headers — only arrive from trusted upstream proxies. Direct
internet clients bypassing the gateway cannot inject identity.

Constitutional positioning
──────────────────────────
* Runs BEFORE :class:`AuthorityContextMiddleware` in the request
  flow. Composition in :func:`app.main.create_app`:

      RequestContext (outer) → TrustedIngress → AuthorityContext → Router

* Inspects the IMMEDIATE TCP peer (``request.client``). The
  ``X-Forwarded-*`` chain is NOT consulted here — that would
  create a chicken-and-egg trust dependency (the gateway tells us
  its own client IP, which we then trust because the gateway
  said so). Trust is established at the L4 boundary by the
  deployment's network topology, not by headers.
* Opt-in: the middleware is registered ONLY when
  ``trusted_proxies`` is explicitly passed to ``create_app``.
  Absent → no trust enforcement (B8/C2 behaviour byte-for-byte
  preserved for legacy / test deployments).
* When configured, ``trusted_proxies=()`` (empty allowlist) is the
  STRICT fail-closed default — every peer is untrusted and any
  authority-bearing header triggers a 400. This mirrors the B5
  AUTHORITY-class doctrine.

Failure shape (400 ``untrusted_ingress``):

    {
      "error":   "untrusted_ingress",
      "reason":  "peer ... is not in trusted_proxies; ...",
      "headers": ["<authorization-bearing header name>", ...]
    }

The response identifies the offending peer (when known) and the
list of authority-bearing headers detected. Audit + ops triage
can correlate the 400 with deployment topology drift (e.g.,
gateway moved subnets without an allowlist update).
"""

from __future__ import annotations

import logging
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address
from typing import Awaitable, Callable, Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.middleware.authority_context import (
    AUTHORITY_HEADERS,
    AUTHORIZATION_HEADER,
)

logger = logging.getLogger(__name__)


#: All headers whose presence implies the request is making an
#: authority claim. Drawn from the canonical AuthorityContextMiddleware
#: header surface so trust enforcement stays in lock-step with
#: the ingress contract.
AUTHORITY_BEARING_HEADERS: Final[tuple[str, ...]] = (
    AUTHORIZATION_HEADER,
    *AUTHORITY_HEADERS,
)


IPNetwork = IPv4Network | IPv6Network
IPAddress = IPv4Address | IPv6Address


class TrustedIngressMiddleware(BaseHTTPMiddleware):
    """Reject authority-bearing headers from untrusted peers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        trusted_proxies: tuple[IPNetwork, ...],
    ) -> None:
        super().__init__(app)
        self._networks = tuple(trusted_proxies)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        peer = self._peer_ip(request)
        if self._is_trusted(peer):
            return await call_next(request)

        tainted = [
            header
            for header in AUTHORITY_BEARING_HEADERS
            if header in request.headers
        ]
        if not tainted:
            return await call_next(request)

        peer_str = str(peer) if peer is not None else "unknown"
        logger.warning(
            "untrusted_ingress_rejected",
            extra={"peer": peer_str, "headers": tainted},
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": "untrusted_ingress",
                "reason": (
                    f"peer {peer_str} is not in trusted_proxies; "
                    "authority-bearing headers rejected"
                ),
                "peer": peer_str,
                "headers": tainted,
            },
        )

    @staticmethod
    def _peer_ip(request: Request) -> IPAddress | None:
        client = request.client
        if client is None:
            return None
        try:
            return ip_address(client.host)
        except ValueError:
            return None

    def _is_trusted(self, peer: IPAddress | None) -> bool:
        if peer is None:
            return False
        for network in self._networks:
            if isinstance(peer, IPv4Address) and isinstance(
                network, IPv4Network
            ):
                if peer in network:
                    return True
            elif isinstance(peer, IPv6Address) and isinstance(
                network, IPv6Network
            ):
                if peer in network:
                    return True
        return False


__all__ = [
    "AUTHORITY_BEARING_HEADERS",
    "IPAddress",
    "IPNetwork",
    "TrustedIngressMiddleware",
]
